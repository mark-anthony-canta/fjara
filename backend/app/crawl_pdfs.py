"""Archive approved PDFs, then optionally extract within a persistent credit budget.
Run from backend. Install requirements-pdf.txt first. No indexing is performed.
"""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .core import key, validate_source

ROOT = Path('data/pdf-crawl')


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def reservation(pages):
    # PDF page charges plus one conservative base-request allowance.
    return pages + 1


async def download(client, url):
    validate_source(url)
    for _ in range(6):
        async with client.stream('GET', url) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers['location'])
                validate_source(url)
                continue
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 50_000_000:
                    raise ValueError('PDF exceeds 50MB archive limit')
            if not content.startswith(b'%PDF-'):
                raise ValueError('Response is not a PDF')
            return bytes(content)
    raise ValueError('Too many redirects')


async def run(args):
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    urls = json.loads(Path(args.links).read_text(encoding='utf-8'))
    approved = []
    for url in urls:
        try:
            validate_source(url)
            approved.append(url)
        except ValueError:
            pass
    async with httpx.AsyncClient(timeout=60) as client:
        semaphore = asyncio.Semaphore(3)
        async def archive(url):
            if manifest.get(url, {}).get('status') == 'downloaded':
                return
            async with semaphore:
                name = hashlib.sha256(url.encode()).hexdigest()
                path = ROOT / f'{name}.pdf'
                try:
                    if not path.exists():
                        path.write_bytes(await download(client, url))
                    from pypdf import PdfReader
                    pages = len(PdfReader(path).pages)
                    if pages < 1:
                        raise ValueError('Empty PDF')
                    manifest[url] = {'status': 'downloaded', 'file': str(path), 'pages': pages}
                except Exception as exc:
                    manifest[url] = {'status': 'download_failed', 'error': type(exc).__name__}
                save(manifest_path, manifest)
                print(f"archive {len(manifest)}/{len(approved)}: {manifest[url]['status']}", flush=True)
        await asyncio.gather(*(archive(url) for url in sorted(set(approved))))
        print('Archived pages:', sum(v.get('pages', 0) for v in manifest.values()), flush=True)
        if not args.extract:
            return
        headers = {'Authorization': 'Bearer ' + key('FIRECRAWL_API_KEY')}
        async def balance():
            r = await client.get('https://api.firecrawl.dev/v2/team/credit-usage', headers=headers)
            r.raise_for_status()
            return int(r.json()['data']['remainingCredits'])
        ledger_path = ROOT / 'ledger.json'
        ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {
            'budget': args.budget, 'initial_balance': await balance(), 'reserved': 0, 'attempts': {}}
        if args.budget != ledger['budget']:
            raise ValueError('Existing budget cannot be changed by a resume')
        save(ledger_path, ledger)
        candidates = sorted(((u,v) for u,v in manifest.items() if v['status']=='downloaded'), key=lambda item:(item[1]['pages'],item[0]))
        for url, info in candidates:
            if url in ledger['attempts']:
                continue  # Never repeat a paid request, even after an uncertain timeout.
            cost = reservation(info['pages'])
            available = await balance()
            if cost > min(ledger['budget'] - ledger['reserved'], available):
                continue
            entry = {'status': 'pending', 'reserved': cost, 'pages': info['pages'], 'started_at': datetime.now(timezone.utc).isoformat()}
            ledger['attempts'][url] = entry
            ledger['reserved'] += cost
            save(ledger_path, ledger)  # Reserve before any paid request; survives crashes.
            try:
                r = await client.post('https://api.firecrawl.dev/v2/scrape', headers=headers, timeout=180, json={
                    'url': url, 'formats': ['markdown'], 'proxy': 'basic',
                    'parsers': [{'type': 'pdf', 'mode': 'auto', 'maxPages': info['pages'], 'pages': True}],
                    'onlyMainContent': True})
                if r.is_error:
                    entry.update(status='failed', http_status=r.status_code)
                    save(ledger_path, ledger)
                    print(f'Stopping after HTTP {r.status_code}; no automatic paid retry', flush=True)
                    break
                result = r.json()
                doc = result.get('data') or {}
                path = Path(info['file']).with_suffix('.json')
                save(path, {'createdAt': entry['started_at'], 'data': [doc]})
                metadata = doc.get('metadata') or {}
                used = metadata.get('creditsUsed')
                entry.update(status='extracted' if result.get('success') and (doc.get('markdown') or '').strip() and metadata.get('statusCode',200)<400 else 'empty_or_failed', file=str(path), characters=len(doc.get('markdown') or ''), reported_credits=used, returned_pages=len(doc.get('pages') or []))
                ledger['last_balance'] = await balance()
                save(ledger_path, ledger)
                print(f"{len(ledger['attempts'])}: {entry['status']}; reserved {ledger['reserved']}/{ledger['budget']}; balance {ledger['last_balance']}", flush=True)
                if used is not None and used > cost:
                    raise ValueError('Provider cost exceeded reservation; stopped')
            except Exception as exc:
                entry['error'] = type(exc).__name__
                save(ledger_path, ledger)
                raise
        ledger['last_balance'] = await balance()
        save(ledger_path, ledger)
        print(json.dumps({'attempted':len(ledger['attempts']), 'reserved':ledger['reserved'], 'remaining_credits':ledger['last_balance']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--links', default='data/crawl-pdf-links.json')
    parser.add_argument('--budget', type=int, choices=range(1,901), default=900)
    parser.add_argument('--extract', action='store_true')
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}. Inspect saved ledger before resuming.')
        raise SystemExit(1)

