"""The live panel: one page, server-sent events from `/events`, a few POST actions."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from earpiece.app.pipeline import CallSession

WEB = Path(__file__).resolve().parent.parent / "web"
KEEPALIVE_S = 15.0


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(session: CallSession) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session.start_preparing()
        yield
        await session.close()

    app = FastAPI(title="Earpiece", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/events")
    async def events(request: Request) -> StreamingResponse:
        queue = session.bus.subscribe()

        async def stream() -> AsyncIterator[str]:
            try:
                yield sse(session.snapshot())
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                        yield sse(event)
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                session.bus.unsubscribe(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/state")
    async def state() -> dict:
        return session.snapshot()

    @app.post("/api/consent")
    async def consent() -> dict:
        session.give_consent()
        return {"consent_at": session.consent_at.isoformat()}

    @app.post("/api/items/{item_id}/pin")
    async def pin(item_id: int, pinned: bool = True) -> dict:
        try:
            session.pin(item_id, pinned)
        except KeyError as e:
            raise HTTPException(404, "No such item") from e
        return {"ok": True}

    @app.post("/api/items/{item_id}/dismiss")
    async def dismiss(item_id: int) -> dict:
        try:
            session.dismiss(item_id)
        except KeyError as e:
            raise HTTPException(404, "No such item") from e
        return {"ok": True}

    @app.post("/api/end")
    async def end() -> dict:
        session.request_end()
        return {"ok": True}

    return app
