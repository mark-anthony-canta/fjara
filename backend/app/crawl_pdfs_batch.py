"""Resume the existing PDF budget ledger using same-page-count Firecrawl batches.
Never run concurrently with crawl_pdfs. Run only after its download phase.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID
import httpx
from .core import key, validate_source
from .crawl_pdfs import ROOT, save, reservation


def select_group(manifest, ledger, available):
    pending=sorted(((u,v['pages']) for u,v in manifest.items() if v['status']=='downloaded' and u not in ledger['attempts']),key=lambda x:(x[1],x[0]))
    if not pending:
        return [],0
    pages=pending[0][1]
    count=min(50, max(0,min(available,ledger['budget']-ledger['reserved'])//reservation(pages)))
    return [u for u,p in pending if p==pages][:count],pages


async def run():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    ledger_path=ROOT/'ledger.json'
    ledger=json.loads(ledger_path.read_text(encoding='utf-8'))
    if not 0<ledger['budget']<=900:
        raise ValueError('Invalid budget')
    headers={'Authorization':'Bearer '+key('FIRECRAWL_API_KEY')}
    async with httpx.AsyncClient(timeout=120) as client:
        async def get(url):
            r=await client.get(url,headers=headers); r.raise_for_status(); return r.json()
        async def balance():
            return int((await get('https://api.firecrawl.dev/v2/team/credit-usage'))['data']['remainingCredits'])
        while True:
            active=ledger.get('active_batch')
            if not active:
                urls,pages=select_group(manifest,ledger,await balance())
                if not urls: break
                for u in urls: validate_source(u)
                started=datetime.now(timezone.utc).isoformat()
                for u in urls:
                    ledger['attempts'][u]={'status':'pending','reserved':reservation(pages),'pages':pages,'started_at':started}
                ledger['reserved']+=len(urls)*reservation(pages)
                save(ledger_path,ledger)
                r=await client.post('https://api.firecrawl.dev/v2/batch/scrape',headers=headers,json={'urls':urls,'maxConcurrency':2,'formats':['markdown'],'proxy':'basic','parsers':[{'type':'pdf','mode':'auto','maxPages':pages,'pages':True}]})
                r.raise_for_status()
                job=str(UUID(r.json()['id']))
                active={'id':job,'urls':urls,'pages':pages,'started_at':started}
                ledger['active_batch']=active
                save(ledger_path,ledger)
                print(f'Batch submitted: {len(urls)} PDFs x {pages} pages; reserved {ledger["reserved"]}/900',flush=True)
            endpoint=f'https://api.firecrawl.dev/v2/batch/scrape/{active["id"]}'
            while True:
                result=await get(endpoint)
                if result.get('status') in ('completed','failed','cancelled'): break
                print(f'Batch progress: {result.get("completed",0)}/{result.get("total",0)}',flush=True)
                await asyncio.sleep(15)
            documents=list(result.get('data') or [])
            next_url=result.get('next'); seen=set()
            while next_url:
                parsed=urlparse(next_url)
                if parsed.scheme!='https' or parsed.netloc!='api.firecrawl.dev' or parsed.path!=urlparse(endpoint).path or next_url in seen:
                    raise ValueError('Unsafe pagination')
                seen.add(next_url)
                page=await get(next_url); documents.extend(page.get('data') or []); next_url=page.get('next')
            save(ROOT/f'batch-{active["id"]}.json',{'createdAt':active['started_at'],'data':documents})
            for doc in documents:
                meta=doc.get('metadata') or {}; url=meta.get('sourceURL') or meta.get('url')
                if url not in active['urls']: continue
                validate_source(meta.get('url') or url)
                entry=ledger['attempts'][url]
                path=Path(manifest[url]['file']).with_suffix('.json')
                save(path,{'createdAt':entry['started_at'],'data':[doc]})
                entry.update(status='extracted' if (doc.get('markdown') or '').strip() and meta.get('statusCode',200)<400 else 'empty_or_failed',file=str(path),characters=len(doc.get('markdown') or ''),reported_credits=meta.get('creditsUsed'),returned_pages=len(doc.get('pages') or []))
            for url in active['urls']:
                if ledger['attempts'][url]['status']=='pending': ledger['attempts'][url]['status']='missing_result'
            ledger['last_balance']=await balance()
            ledger.pop('active_batch')
            save(ledger_path,ledger)
            print(f'Batch complete; balance {ledger["last_balance"]}',flush=True)
            await asyncio.sleep(31) # Free plan permits two batch submissions/minute.
        ledger['last_balance']=await balance(); save(ledger_path,ledger)
        print(f'Finished budgeted batches; reserved {ledger["reserved"]}, balance {ledger["last_balance"]}',flush=True)

if __name__=='__main__':
    try: asyncio.run(run())
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}; saved batch can be resumed without resubmission.')
        raise SystemExit(1)
