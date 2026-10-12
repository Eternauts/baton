from __future__ import annotations

import asyncio

from app.corpus import parse_file
from app.index import HybridIndex
from app.rules import RuleSet, canon_tags, tokenize


def test_tags_are_canonicalised_without_eating_numbers_in_prose():
    assert canon_tags("check p101a and PSV104") == "check P-101A and PSV-104"
    assert canon_tags("wait for 15 minutes at 18 barg") == "wait for 15 minutes at 18 barg"


def test_tokenize_splits_hyphenated_words_but_keeps_tags_whole():
    tokens = tokenize("Hot-work near P-101A valves")
    assert {"hot", "work", "hot-work", "p-101a", "valve"} <= set(tokens)
    assert "101a" not in tokens


def test_plan_resolves_aliases_and_expands_synonyms():
    rules = RuleSet({"aliases": {"P-101A": ["pump A"]}, "synonyms": [["psv", "relief valve"]]})
    plan = rules.plan("Can I start pump A with its relief valve out?", ["GD-311", "wind_speed"])
    assert plan.tags == {"P-101A"}
    assert plan.context_tags == {"GD-311"}  # non-tag context keys are ignored
    assert plan.weights["p-101a"] == 1.5
    assert plan.weights["psv"] == 0.5  # expansion, lower weight
    assert plan.weights["relief"] == 1.0  # from the question itself


def test_markdown_chunks_carry_front_matter_sections_and_tags():
    raw = b"---\ntitle: Demo SOP\ntype: sop\nrevision: 2\n---\n# Demo\n\n## 1 Start\n\nStart P-101A slowly.\n"
    [chunk] = parse_file("docs/DEMO-1.md", raw, RuleSet(), 1000)
    assert (chunk.id, chunk.title, chunk.section, chunk.doc_type, chunk.revision) == \
        ("DEMO-1#1", "Demo SOP", "1 Start", "SOP", "2")
    assert chunk.tags == ["P-101A"]


def test_bulletin_outranks_sop_for_stripper_platform_bypass(make_engine):
    engine, _ = make_engine()
    _, hits, rconf = asyncio.run(engine.retrieve(
        "Can hot work resume on the stripper platform while GD-311 is bypassed?", [], 5))
    ids = [h.chunk.doc_id for h in hits]
    assert ids[0] == "BUL-2026-07"
    assert "SOP-GD-03" in ids and "SOP-HW-01" in ids
    assert rconf >= 0.8


def test_alias_query_finds_relief_valve_procedure(make_engine):
    engine, _ = make_engine()
    _, hits, _ = asyncio.run(engine.retrieve("Is it OK to start pump A while its relief valve is at the bench?", [], 4))
    assert {"SOP-PSV-02", "MAN-P101"} & {h.chunk.doc_id for h in hits[:2]}


def test_index_round_trips_through_files(make_engine):
    engine, _ = make_engine()
    restored = HybridIndex.from_files(engine.index.to_files(), engine.index.rules)
    assert restored.version == engine.index.version
    assert len(restored.chunks) == len(engine.index.chunks)


def test_cached_index_is_reused_until_corpus_changes(settings, make_engine, tmp_path):
    engine, _ = make_engine()
    first = engine.index
    engine.load()
    assert engine.index is not first and engine.index.version == first.version  # loaded from cache

    import shutil
    from dataclasses import replace

    corpus = tmp_path / "corpus"
    shutil.copytree(settings.corpus_uri, corpus)
    engine.s = replace(settings, corpus_uri=str(corpus))
    engine.load()
    before = engine.index.version
    (corpus / "NOTE-1.md").write_text("# Note\n\nPump P-101B vibration checked at 04:00.\n")
    engine.load()
    assert engine.index.version != before
    assert any(c.doc_id == "NOTE-1" for c in engine.index.chunks)
