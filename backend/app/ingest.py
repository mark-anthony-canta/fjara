"""Bounded, manual ingestion. Run from backend: python -m app.ingest."""
import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx

from .core import COLLECTION, DIMENSIONS, QDRANT, chunks, embed, key, request, validate_source


async def run(scrape_only: bool = False, limit: int = 5, offset: int = 0):
    key("FIRECRAWL_API_KEY")
    if not scrape_only:
        key("GEMINI_API_KEY")
    urls = json.loads(Path("sources.json").read_text(encoding="utf-8"))[offset:offset + limit]
    for url in urls:
        validate_source(url)
    Path("data").mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=120) as client:
        if not scrape_only:
            exists = await request(client, "GET", f"{QDRANT}/collections/{COLLECTION}/exists")
            if not exists["result"]["exists"]:
                await request(client, "PUT", f"{QDRANT}/collections/{COLLECTION}",
                              json={"vectors": {"size": DIMENSIONS, "distance": "Cosine"}})
            info = await request(client, "GET", f"{QDRANT}/collections/{COLLECTION}")
            if info["result"]["config"]["params"]["vectors"]["size"] != DIMENSIONS:
                raise ValueError("Collection dimensions differ; use a new collection")
        for url in urls:
            data = await request(client, "POST", "https://api.firecrawl.dev/v2/scrape",
                headers={"Authorization": f"Bearer {key('FIRECRAWL_API_KEY')}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True})
            if not data.get("success"):
                raise RuntimeError("Firecrawl scrape unsuccessful")
            document = data["data"]
            markdown = document.get("markdown", "").strip()
            if not markdown or document.get("metadata", {}).get("statusCode", 200) >= 400:
                raise RuntimeError("Source returned empty or failed content")
            digest = hashlib.sha256(markdown.encode()).hexdigest()
            source_id = hashlib.sha256(url.encode()).hexdigest()
            record = {"url": url, "title": document.get("metadata", {}).get("title", url),
                      "crawled_at": datetime.now(timezone.utc).isoformat(),
                      "content_hash": digest, "markdown": markdown}
            Path(f"data/{source_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            parts = chunks(markdown)
            if not scrape_only:
                # Prepare all embeddings before changing the stored source.
                points = [{"id": str(uuid5(NAMESPACE_URL, f"{url}:{digest}:{i}")),
                           "vector": await embed(client, part),
                           "payload": {k: v for k, v in record.items() if k != "markdown"}
                           | {"text": part, "chunk_index": i}}
                          for i, part in enumerate(parts)]
                await request(client, "PUT", f"{QDRANT}/collections/{COLLECTION}/points?wait=true",
                              json={"points": points})
                # Remove old versions only after the new version has been stored.
                await request(client, "POST", f"{QDRANT}/collections/{COLLECTION}/points/delete?wait=true",
                    json={"filter": {"must": [{"key": "url", "match": {"value": url}}],
                                     "must_not": [{"key": "content_hash", "match": {"value": digest}}]}})
            print(f"{'Scraped' if scrape_only else 'Indexed'} {url}: {len(parts)} chunks")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrape-only", action="store_true")
    parser.add_argument("--limit", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--offset", type=int, choices=range(5), default=0,
                        help="Skip already completed sources when resuming a failed run")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.scrape_only, args.limit, args.offset))
    except Exception as exc:
        print(f"Ingestion failed ({type(exc).__name__}). Check credentials, network, and service availability.", file=sys.stderr)
        if isinstance(exc, (RuntimeError, ValueError)):
            print(str(exc), file=sys.stderr)
        sys.exit(1)
