"""Baton Sandglass: the wide end of the sandglass.

The on-device Gemma sends a short question over a constrained link. This service does
the heavy work (hybrid retrieval, Gemini reasoning, quote verification, confidence
calibration) and returns a small, byte-budgeted answer.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware

from . import storage
from .config import Settings, get_settings
from .engine import Engine
from .gemini import LLM, VertexGemini
from .payload import compact, encode, fit, fit_search
from .schemas import AskRequest, AskResult, SearchRequest

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("sandglass")
JSON = "application/json"


class ResponseCache:
    """Small LRU of encoded answers. Keys include the corpus version, so a reindex invalidates it."""

    def __init__(self, size: int):
        self.size = size
        self._items: OrderedDict[str, bytes] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        return None

    def put(self, key: str, value: bytes) -> None:
        if self.size <= 0:
            return
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = Engine(settings, llm or VertexGemini(settings))
        await asyncio.to_thread(engine.load)
        app.state.engine = engine
        app.state.cache = ResponseCache(settings.cache_size)
        app.state.reindexing = asyncio.Lock()
        app.state.checked_at = time.monotonic()
        if not settings.api_keys:
            log.warning("BATON_API_KEYS is empty: the API is open. Set it before exposing the service.")
        yield

    app = FastAPI(title="Baton Sandglass", version=settings.version, lifespan=lifespan,
                  description="Document-grounded answers for an on-device model over constrained links.")
    app.add_middleware(GZipMiddleware, minimum_size=400)

    def require_key(x_api_key: str | None = Header(None)) -> None:
        if settings.api_keys and not any(hmac.compare_digest(x_api_key or "", k) for k in settings.api_keys):
            raise HTTPException(401, "invalid or missing X-API-Key")

    def require_admin(x_admin_key: str | None = Header(None)) -> None:
        if not settings.admin_key or not hmac.compare_digest(x_admin_key or "", settings.admin_key):
            raise HTTPException(403, "admin key required")

    async def _refresh(app: FastAPI) -> None:
        engine: Engine = app.state.engine
        async with app.state.reindexing:
            try:
                fp = await asyncio.to_thread(storage.fingerprint, settings.corpus_uri)
                if fp != engine.index.corpus_fingerprint:
                    log.info("corpus changed, reloading index")
                    await asyncio.to_thread(engine.load)
                    app.state.cache.clear()
            except Exception as exc:
                log.warning("corpus refresh failed: %s", exc)

    def maybe_refresh(request: Request) -> None:
        """Triggered by traffic (not a timer) so it also runs under request-based CPU billing."""
        app_ = request.app
        now = time.monotonic()
        if settings.refresh_s > 0 and now - app_.state.checked_at > settings.refresh_s \
                and not app_.state.reindexing.locked():
            app_.state.checked_at = now
            app_.state.refresh_task = asyncio.create_task(_refresh(app_))

    def cached_response(request: Request, body: bytes) -> Response:
        etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(body, media_type=JSON, headers={"ETag": etag, "Cache-Control": "private, max-age=300"})

    @app.get("/health")
    def healthz(request: Request):
        engine: Engine = request.app.state.engine
        return {"status": "ok", "version": settings.version, "corpus": engine.index.version}

    @app.get("/v1/corpus", dependencies=[Depends(require_key)])
    def corpus(request: Request):
        """Corpus version and size. The device can compare `version` with `v` in answers to drop stale cache."""
        return request.app.state.engine.index.stats()

    @app.post("/v1/ask", dependencies=[Depends(require_key), Depends(maybe_refresh)],
              responses={200: {"description": "Compact answer (see payload.py for keys)"}})
    async def ask(req: AskRequest, request: Request, view: str = "compact"):
        """Answer a question from the corpus. `view=full` returns the verbose AskResult for debugging."""
        engine: Engine = request.app.state.engine
        cache: ResponseCache = request.app.state.cache
        key = hashlib.sha1(json.dumps(
            [engine.index.version, view, req.model_dump(exclude_none=True)], sort_keys=True, ensure_ascii=False
        ).encode()).hexdigest()
        body = cache.get(key)
        if body is None:
            result: AskResult = await engine.ask(req)
            body = encode(result.model_dump()) if view == "full" else fit(compact(result), req.budget)
            # Do not pin degraded answers: the next request may reach Gemini.
            if result.generator == "gemini" or result.decision == "N":
                cache.put(key, body)
        return cached_response(request, body)

    @app.post("/v1/search", dependencies=[Depends(require_key), Depends(maybe_refresh)])
    async def search(req: SearchRequest, request: Request):
        """Retrieval only, no Gemini call: ranked passages the device can read itself."""
        engine: Engine = request.app.state.engine
        ctx_tags = (req.ctx.tags + [str(k) for k in req.ctx.state]) if req.ctx else []
        _, hits, rconf = await engine.retrieve(req.q, ctx_tags, req.k)
        top = hits[0].score if hits else 1.0
        payload = {"v": engine.index.version, "rc": rconf,
                   "r": [[h.chunk.id, h.chunk.section, round(h.score / top, 2), h.chunk.text] for h in hits]}
        return cached_response(request, fit_search(payload, req.budget))

    @app.post("/v1/admin/reindex", dependencies=[Depends(require_admin)])
    async def reindex(request: Request):
        """Rebuild the index from the corpus (after uploading documents) and swap it in."""
        engine: Engine = request.app.state.engine
        lock: asyncio.Lock = request.app.state.reindexing
        if lock.locked():
            raise HTTPException(409, "reindex already running")
        async with lock:
            await asyncio.to_thread(engine.load, True)
            request.app.state.cache.clear()
        return engine.index.stats()

    return app


app = create_app()
