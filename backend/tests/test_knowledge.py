import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from app.knowledge import embed, search as search_mod, store
from app.knowledge.chunking import chunk_markdown
from app.knowledge.handover_chunker import _pretty_shift, chunk_handover, scrub_names
from app.knowledge.schema import MAX_CHUNK_CHARS, make_chunk_id
from app.knowledge.tags import detect_language, extract_asset_tags, normalize_unit

SOP = """---
title: Isolation and Lockout-Tagout
type: SOP
revision: 5
---
# Isolation and Lockout-Tagout

## 1 Isolation standard

Hydrocarbon service above 10 barg requires double block and bleed on P-201A/B.

## 2 Verification

Check zero energy.
"""

BULLETIN = """---
title: Bulletin
type: BULLETIN
revision: 1
---
# Bulletin

Issued by the superintendent. This bulletin supersedes SOP-GD-03 section 2 for area 3C only.

## Requirement

No hot work while GD-311 is bypassed.
"""


# ---------- tags ----------
def test_extract_tags():
    assert extract_asset_tags("P-201B isolated, see esdv-301 and TK-501; P-101A/B too") == \
        ["P-201B", "ESDV-301", "TK-501", "P-101A", "P-101B"]
    assert extract_asset_tags("no tags here, section 2-3") == []
    # document references are not equipment
    assert extract_asset_tags("See SOP-ISO-04 and BUL-2026-07 for P-201B; SOP-GD-03 covers GD-311") == ["P-201B", "GD-311"]


def test_normalize_unit():
    assert normalize_unit("Hydrocracker Unit 01") == "HYDROCRACKER-01"
    assert normalize_unit("hydrocracker-01") == "HYDROCRACKER-01"
    assert normalize_unit("HYDROCRACKER-01") == "HYDROCRACKER-01"
    assert normalize_unit(None) is None
    # "UNIT" is only dropped between a name and a number
    assert normalize_unit("UNIT-01") == "UNIT-01"
    assert normalize_unit("CANARY-UNIT") == "CANARY-UNIT"
    assert normalize_unit("Unit 3") == "UNIT-3"


def test_detect_language():
    assert detect_language("பம்ப் P-201B அதிகமாக அதிருது") == "ta"
    assert detect_language("Pump is vibrating") == "en"


# ---------- chunking ----------
def test_chunk_markdown_sections_and_metadata():
    chunks = chunk_markdown("SOP-ISO-04", SOP)
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert chunks[0].title == "SOP-ISO-04 1 Isolation standard"
    assert chunks[0].text.startswith("SOP-ISO-04 - Isolation and Lockout-Tagout - 1 Isolation standard")
    assert chunks[0].asset_tags == ["P-201A", "P-201B"]
    assert chunks[0].doc_type == "SOP" and chunks[0].revision == "5" and chunks[0].source_type == "SOP"
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)


def test_bulletin_records_what_it_supersedes():
    chunks = chunk_markdown("BUL-2026-07", BULLETIN)
    assert all(c.supersedes == "SOP-GD-03#2" and c.doc_type == "BULLETIN" and c.source_type == "SOP" for c in chunks)


def test_long_section_is_split_under_limit():
    raw = "# T\n\n## 1 Big\n\n" + "\n\n".join(f"Paragraph {i} " + "x" * 400 for i in range(10))
    chunks = chunk_markdown("SOP-X", raw)
    assert len(chunks) > 1 and all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)


def test_chunk_id_is_deterministic_and_content_sensitive():
    a = make_chunk_id("SOP", "SOP-A", 0, "text")
    assert a == make_chunk_id("SOP", "SOP-A", 0, "text")
    assert a != make_chunk_id("SOP", "SOP-A", 0, "text2")
    assert a != make_chunk_id("SOP", "SOP-A", 1, "text")
    assert [c.chunk_id for c in chunk_markdown("SOP-ISO-04", SOP)] == [c.chunk_id for c in chunk_markdown("SOP-ISO-04", SOP)]


# ---------- handover chunker ----------
CAPS = [
    {"uuid": "1", "asset_tag": "P-201B", "asserted_state": "RUNNING", "category": "EQUIPMENT",
     "text_transcript": "Vibrating heavily, seal looks wet. Work order raised by Arun.", "timestamp": "2026-10-11T14:30:00Z"},
    {"uuid": "2", "asset_tag": "V-102", "asserted_state": "CLOSED", "category": "ISOLATION",
     "text_transcript": "Arun closed it", "timestamp": "2026-10-11T14:40:00Z"},
]


def test_handover_chunk_format_and_no_names():
    chunks = chunk_handover("h1", CAPS, unit_name="Hydrocracker Unit 01", shift_name="NIGHT-SHIFT-A", operator_id="TECH-ARUN-42")
    assert len(chunks) == 1
    c = chunks[0]
    assert "P-201B: RUNNING. Vibrating heavily, seal looks wet" in c.text
    assert "(operator, 14:30, Night shift A)" in c.text
    assert "arun" not in c.text.lower()
    assert c.unit == "HYDROCRACKER-01" and c.asset_tags == ["P-201B", "V-102"]
    assert c.author_role == "operator" and c.source_type == "HANDOVER" and c.shift_id == "NIGHT-SHIFT-A"
    assert c.created_at == datetime(2026, 10, 11, 14, 40, tzinfo=timezone.utc)


def test_handover_groups_under_size_limit():
    many = [{"uuid": str(i), "asset_tag": f"P-{100+i}", "asserted_state": "RUNNING", "text_transcript": "n" * 300,
             "timestamp": "2026-10-11T10:00:00Z"} for i in range(12)]
    chunks = chunk_handover("h2", many, unit_name="U", shift_name="DAY")
    assert len(chunks) > 1 and all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    assert sum(c.text.count("RUNNING.") for c in chunks) == 12


def test_scrub_names():
    assert "Ravi" not in scrub_names("put on manual by Ravi", ["Ravi"])
    assert scrub_names("raised by Priya Nair at 10:30") == "raised at 10:30"
    assert scrub_names("no names here") == "no names here"


def test_pretty_shift():
    assert _pretty_shift("NIGHT-SHIFT-A") == "Night shift A"


# ---------- embeddings ----------
def _emb_response(n, dim=4):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=[3.0, 4.0] + [0.0] * (dim - 2)) for _ in range(n)])


def test_embed_batches_normalizes_and_uses_task_types(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "emb-model")
    monkeypatch.setenv("EMBEDDING_LOCATION", "asia-southeast1")
    client = MagicMock()
    client.models.embed_content.side_effect = lambda model, contents, config: _emb_response(len(contents))
    with patch.object(embed, "get_client", return_value=client) as gc:
        vecs = embed.embed_texts([f"t{i}" for i in range(250)], embed.DOCUMENT)
    gc.assert_called_with("asia-southeast1")
    assert len(vecs) == 250
    assert client.models.embed_content.call_count == 3  # 100 + 100 + 50
    assert math.isclose(math.sqrt(sum(x * x for x in vecs[0])), 1.0, rel_tol=1e-9)
    cfg = client.models.embed_content.call_args.kwargs["config"]
    assert cfg.task_type == "RETRIEVAL_DOCUMENT" and cfg.output_dimensionality == 768
    with patch.object(embed, "get_client", return_value=client):
        embed.embed_query("q")
    assert client.models.embed_content.call_args.kwargs["config"].task_type == "RETRIEVAL_QUERY"


def test_embed_retries_429(monkeypatch):
    monkeypatch.setattr(embed.time, "sleep", lambda s: None)
    monkeypatch.setenv("EMBEDDING_MODEL", "emb-model")
    client = MagicMock()
    client.models.embed_content.side_effect = [errors.ClientError(429, {"error": {"message": "q"}}), _emb_response(1)]
    with patch.object(embed, "get_client", return_value=client):
        assert len(embed.embed_texts(["a"])) == 1
    assert client.models.embed_content.call_count == 2


def test_embed_empty():
    assert embed.embed_texts([]) == []


# ---------- search ----------
def _doc(i, distance, created=None, **extra):
    d = {"source_type": "SOP", "source_id": f"S{i}", "title": f"t{i}", "text": "x", "asset_tags": [],
         "created_at": created, "distance": distance, **extra}
    return SimpleNamespace(id=f"id{i}", to_dict=lambda d=d: d)


def _fake_db(docs):
    chain = MagicMock()
    chain.where.return_value = chain
    chain.select.return_value = chain
    chain.find_nearest.return_value = chain
    chain.stream.return_value = docs
    db = MagicMock()
    db.collection.return_value = chain
    return db, chain


@pytest.fixture
def _no_embed(monkeypatch):
    monkeypatch.setattr(search_mod, "embed_query", lambda q: [0.1, 0.2])


def test_search_filters_threshold_and_sorting(_no_embed, monkeypatch):
    monkeypatch.setenv("SEARCH_MAX_DISTANCE", "0.55")
    db, chain = _fake_db([_doc(1, 0.4), _doc(2, 0.2), _doc(3, 0.3)])
    with patch.object(search_mod, "get_db", return_value=db):
        hits = search_mod.search("isolate a pump", k=2, source_types=["SOP"], unit="Hydrocracker Unit 01", asset_tag="p-201b")
    assert [h.chunk_id for h in hits] == ["id2", "id3"]  # sorted by distance, trimmed to k
    kw = chain.find_nearest.call_args.kwargs
    assert kw["distance_threshold"] == 0.55 and kw["distance_result_field"] == "distance" and kw["limit"] == 2
    assert "distance" in chain.select.call_args.args[0]  # the field mask must include the distance field
    filters = [c.kwargs["filter"] for c in chain.where.call_args_list]
    assert [(f.field_path, f.op_string, f.value) for f in filters] == [
        ("source_type", "==", "SOP"), ("unit", "==", "HYDROCRACKER-01"), ("asset_tags", "array_contains", "P-201B")]


def test_search_multiple_types_uses_in(_no_embed):
    db, chain = _fake_db([])
    with patch.object(search_mod, "get_db", return_value=db):
        search_mod.search("q", source_types=["HANDOVER", "OBSERVATION"])
    f = chain.where.call_args.kwargs["filter"]
    assert f.op_string == "in" and f.value == ["HANDOVER", "OBSERVATION"]


def test_search_since_is_post_filter_with_overfetch(_no_embed):
    now = datetime.now(timezone.utc)
    docs = [_doc(1, 0.1, now - timedelta(hours=100)), _doc(2, 0.2, now - timedelta(hours=10))]
    db, chain = _fake_db(docs)
    with patch.object(search_mod, "get_db", return_value=db):
        hits = search_mod.search("q", k=3, since=now - timedelta(hours=72))
    assert [h.chunk_id for h in hits] == ["id2"]
    assert chain.find_nearest.call_args.kwargs["limit"] == 12


def test_search_does_not_log_query_text(_no_embed, caplog):
    import logging
    db, _ = _fake_db([])
    with patch.object(search_mod, "get_db", return_value=db), caplog.at_level(logging.INFO, logger="baton.knowledge.search"):
        search_mod.search("secret operator question text")
    assert "secret operator question" not in " ".join(caplog.messages)
    assert "qlen=29" in " ".join(caplog.messages)


# ---------- store ----------
def test_upsert_is_keyed_by_chunk_id(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "emb-model")
    chunks = chunk_markdown("SOP-ISO-04", SOP)
    db = MagicMock()
    with patch.object(store, "get_db", return_value=db), patch.object(store, "embed_texts", return_value=[[1.0, 0.0]] * len(chunks)):
        store.upsert_chunks(chunks)
        store.upsert_chunks(chunks)
    refs = [c.args[0] for c in db.batch.return_value.set.call_args_list]
    ids = [db.collection.return_value.document.call_args_list[i].args[0] for i in range(len(refs))]
    assert len(set(ids)) == len(chunks)  # two runs, same IDs: no duplicates
    doc = db.batch.return_value.set.call_args_list[0].args[1]
    assert doc["schema_version"] == "1" and doc["embedding_model"] == "emb-model" and doc["seeded"] is False
    assert type(doc["embedding"]).__name__ == "Vector"
