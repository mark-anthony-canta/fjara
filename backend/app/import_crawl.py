"""Import an existing Firecrawl crawl or JSON export. Never starts a new crawl.

Default is a dry run; --index explicitly enables paid embeddings and Qdrant writes.
"""
import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, NAMESPACE_URL, uuid5

import httpx

from .core import COLLECTION, DIMENSIONS, QDRANT, ProviderError, chunks, embed, key, request, validate_source

IMPORT_VERSION = 'skatturinn-crawl-v1'


async def retry(operation):
    for attempt in range(5):
        try:
            return await operation()
        except ProviderError as exc:
            if exc.status not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
        except httpx.TransportError:
            if attempt == 4:
                raise
        await asyncio.sleep(2 ** attempt)


def clean_markdown(text):
    # Remove observed site navigation blocks, retaining the article before/after.
    # Only recognize an actual link-list menu, not an arbitrary article heading.
    lines = text.splitlines()
    kept = []
    i = 0
    while i < len(lines):
        if lines[i].strip() in ('## English', '## Síðuvalmynd'):
            j = i + 1
            while j < len(lines) and not re.match(r'^#{1,2} ', lines[j]):
                j += 1
            block = lines[i + 1:j]
            if sum(bool(re.match(r'^\s*- \[', line)) for line in block) >= 5:
                i = j
                continue
        if not (lines[i].startswith('[![Directorate of Internal Revenue]')
                or lines[i].startswith('[Navigation](') or lines[i].startswith('[Hlusta](')):
            kept.append(lines[i])
        i += 1
    return '\n'.join(kept).strip()


def crawl_url(url, job_id):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'api.firecrawl.dev'
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path != f'/v2/crawl/{job_id}' or parsed.fragment):
        raise ValueError('Unsafe Firecrawl pagination URL')
    return url


async def download(client, job_id):
    job_id = str(UUID(job_id))
    url = f'https://api.firecrawl.dev/v2/crawl/{job_id}'
    seen = set()
    archive = None
    while url:
        crawl_url(url, job_id)
        if url in seen or len(seen) >= 1000:
            raise ValueError('Invalid or excessive crawl pagination')
        seen.add(url)
        data = await retry(lambda: request(client, 'GET', url,
            headers={'Authorization': f"Bearer {key('FIRECRAWL_API_KEY')}"}))
        if data.get('status') != 'completed':
            raise ValueError('Crawl is not completed; retry after completion')
        if archive is None:
            archive = {k: v for k, v in data.items() if k not in ('data', 'next')}
            archive.update({'crawl_id': job_id, 'data': []})
        archive['data'].extend(data.get('data', []))
        url = data.get('next')
    return archive


def prepare(archive, crawled_at=None):
    if isinstance(archive, list):
        documents = archive
    elif isinstance(archive, dict):
        documents = archive.get('data', [])
        crawled_at = crawled_at or archive.get('createdAt')
    else:
        raise ValueError('Expected a Firecrawl JSON object or document list')
    if not isinstance(documents, list) or not crawled_at:
        raise ValueError('Export needs a data list and createdAt, or --crawled-at timestamp')
    parsed_time = datetime.fromisoformat(crawled_at.replace('Z', '+00:00'))
    if parsed_time.tzinfo is None:
        raise ValueError('Crawl timestamp must include a timezone')
    records, skipped, seen = [], [], set()
    for number, document in enumerate(documents):
        try:
            meta = document.get('metadata') or {}
            url = meta.get('sourceURL') or meta.get('url')
            if not isinstance(url, str):
                raise ValueError('Missing source URL')
            validate_source(url)
            # Do not admit documents redirected away from the approved source.
            if meta.get('url'):
                validate_source(meta['url'])
            if int(meta.get('statusCode', 200)) >= 400 or meta.get('error'):
                raise ValueError('Failed page')
            raw = document.get('markdown')
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError('Missing Markdown content')
            text = clean_markdown(raw)
            if not text:
                raise ValueError('No usable text after cleaning')
            if url in seen:
                raise ValueError('Duplicate source URL')
            seen.add(url)
            records.append({'url': url, 'title': meta.get('title') or url,
                'crawled_at': parsed_time.isoformat(), 'imported_at': datetime.now(timezone.utc).isoformat(),
                'content_hash': hashlib.sha256(text.encode()).hexdigest(), 'text': text,
                'import_version': IMPORT_VERSION, 'raw_characters': len(raw)})
        except (ValueError, TypeError, AttributeError) as exc:
            skipped.append({'document': number, 'reason': type(exc).__name__})
    return records, skipped


async def index_records(client, records, report_path):
    import os
    model = os.getenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001')
    key('GEMINI_API_KEY')
    endpoint = f'{QDRANT}/collections/{COLLECTION}'
    exists = await request(client, 'GET', f'{endpoint}/exists')
    if not exists['result']['exists']:
        await request(client, 'PUT', endpoint, json={'vectors': {'size': DIMENSIONS, 'distance': 'Cosine'}})
    info = await request(client, 'GET', endpoint)
    vectors = info['result']['config']['params']['vectors']
    if vectors['size'] != DIMENSIONS or vectors['distance'].lower() != 'cosine':
        raise ValueError('Incompatible collection; use a new collection')
    report = {'collection': COLLECTION, 'embedding_model': model, 'documents': []}
    for record in records:
        parts = chunks(record['text'])
        identity = {k: record[k] for k in ('url', 'content_hash', 'import_version')}
        identity['embedding_model'] = model
        count = await request(client, 'POST', f'{endpoint}/points/count', json={
            'exact': True, 'filter': {'must': [{'key': k, 'match': {'value': v}} for k, v in identity.items()]}})
        if count['result']['count'] == len(parts):
            status = 'unchanged'
        else:
            # All embeddings must succeed before replacing any stored source.
            points = []
            for i, part in enumerate(parts):
                vector = await retry(lambda: embed(client, part))
                points.append({'id': str(uuid5(NAMESPACE_URL,
                    f"{record['url']}:{record['content_hash']}:{IMPORT_VERSION}:{model}:{i}")),
                    'vector': vector,
                    'payload': {k: v for k, v in record.items() if k not in ('text', 'raw_characters')}
                    | {'text': part, 'chunk_index': i, 'embedding_model': model}})
            await retry(lambda: request(client, 'PUT', f'{endpoint}/points?wait=true', json={'points': points}))
            status = 'indexed'
        # Also finish cleanup when resuming after an interrupted successful upsert.
        await retry(lambda: request(client, 'POST', f'{endpoint}/points/delete?wait=true', json={'filter': {
            'must': [{'key': 'url', 'match': {'value': record['url']}}],
            'must_not': [{'must': [{'key': k, 'match': {'value': v}} for k, v in identity.items()]}]}}))
        report['documents'].append({'url': record['url'], 'status': status, 'chunks': len(parts)})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{status}: {record['url']} ({len(parts)} chunks)", flush=True)
    return report


async def run(args):
    Path('data').mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=120) as client:
        if args.crawl_id:
            archive = await download(client, args.crawl_id)
            output = Path('data') / f'crawl-{str(UUID(args.crawl_id))}.json'
            output.write_text(json.dumps(archive, ensure_ascii=False), encoding='utf-8')
            print(f'Saved existing crawl to {output}', flush=True)
        else:
            archive = json.loads(Path(args.file).read_text(encoding='utf-8-sig'))
        records, skipped = prepare(archive, args.crawled_at)
        summary = {'valid_documents': len(records), 'skipped': skipped,
            'chunks': sum(len(chunks(r['text'])) for r in records),
            'raw_characters': sum(r['raw_characters'] for r in records),
            'cleaned_characters': sum(len(r['text']) for r in records)}
        print(json.dumps(summary), flush=True)
        if not records:
            raise ValueError('No usable documents in this crawl')
        if args.index:
            await index_records(client, records, Path('data/crawl-import-report.json'))
        else:
            print('Dry run: no embeddings requested or database changes made. Add --index to import.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--crawl-id')
    group.add_argument('--file')
    parser.add_argument('--crawled-at', help='ISO timestamp with timezone when export has no createdAt')
    parser.add_argument('--index', action='store_true')
    try:
        asyncio.run(run(parser.parse_args()))
    except (ValueError, RuntimeError, httpx.HTTPError, KeyError) as exc:
        print(f'Import failed: {type(exc).__name__}. Completed pages remain stored; rerun to resume.')
        if isinstance(exc, ProviderError):
            print(str(exc))
        raise SystemExit(1)
