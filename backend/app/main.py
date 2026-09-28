import asyncio
import json
from contextlib import suppress
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .core import COLLECTION, QDRANT, ProviderError, request
from .chat import ChatRequest, ChatResponse, answer_question

app = FastAPI(title="Fjara", description="Icelandic accounting knowledge service", version="0.3.0")


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
async def stream_chat(body: ChatRequest):
    async def stream():
        task = asyncio.create_task(chat(body))
        try:
            yield event("status", {"message": "Searching sources and preparing a verified answer…"})
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=5)
                if not done:
                    yield ": keepalive\n\n"
            result = await task
            # Never expose unvalidated model tokens. Publish only the checked answer.
            yield event("answer", result.model_dump())
            yield event("done", {})
        except HTTPException as exc:
            yield event("error", {"message": exc.detail, "status": exc.status_code})
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    try:
        async with asyncio.timeout(60):
            return await answer_question(body)
    except ProviderError as exc:
        if exc.status == 429:
            raise HTTPException(429, "Provider usage limit reached. Try again later.") from None
        raise HTTPException(503, "A required service is unavailable.") from None
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "The answer timed out. Try again later.") from None
    except httpx.HTTPError:
        raise HTTPException(503, "A required service is unavailable.") from None
    except (ValueError, KeyError, TypeError, IndexError):
        raise HTTPException(502, "The service could not produce a valid grounded answer.") from None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            result = await request(client, "GET", f"{QDRANT}/collections/{COLLECTION}")
        count = result["result"]["points_count"]
        return JSONResponse({"status": "ready" if count else "empty", "chunks": count},
                            status_code=200 if count else 503)
    except (httpx.HTTPError, RuntimeError, KeyError):
        return JSONResponse({"status": "unavailable"}, status_code=503)
