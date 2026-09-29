import unittest
import httpx
from app.crawl_pdfs import download, reservation

class PDFCrawlTests(unittest.IsolatedAsyncioTestCase):
    def test_reserve_includes_base_allowance(self):
        self.assertEqual(reservation(8), 9)

    async def test_external_redirect_is_not_followed(self):
        calls=[]
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={'location':'https://example.com/private.pdf'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ValueError):
                await download(client, 'https://www.skatturinn.is/example.pdf')
        self.assertEqual(len(calls),1)

    async def test_html_error_page_is_not_archived_as_pdf(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='<html>Not found</html>'))) as client:
            with self.assertRaises(ValueError):
                await download(client,'https://www.skatturinn.is/missing.pdf')

class BudgetPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserved_budget_blocks_paid_request_on_resume(self):
        import argparse
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from app import crawl_pdfs as module
        url='https://www.skatturinn.is/a.pdf'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'links.json').write_text(json.dumps([url]))
            (root/'manifest.json').write_text(json.dumps({url:{'status':'downloaded','pages':2,'file':'unused.pdf'}}))
            (root/'ledger.json').write_text(json.dumps({'budget':10,'initial_balance':100,'reserved':9,'attempts':{}}))
            calls=[]
            def handler(request):
                calls.append(request.method)
                return httpx.Response(200,json={'data':{'remainingCredits':100}})
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch.object(module,'ROOT',root), patch.object(module,'key',return_value='test'), patch.object(module.httpx,'AsyncClient',return_value=client):
                await module.run(argparse.Namespace(links=str(root/'links.json'),extract=True,budget=10))
            self.assertNotIn('POST',calls)
            self.assertEqual(json.loads((root/'ledger.json').read_text())['reserved'],9)

class BatchBudgetTests(unittest.TestCase):
    def test_group_is_capped_by_total_reservation_and_page_count(self):
        from app.crawl_pdfs_batch import select_group
        manifest={'a':{'status':'downloaded','pages':1},'b':{'status':'downloaded','pages':1},'c':{'status':'downloaded','pages':2}}
        ledger={'budget':900,'reserved':897,'attempts':{}}
        self.assertEqual(select_group(manifest,ledger,900),(['a'],1))
        self.assertEqual(select_group(manifest,ledger,1),([],1))
        ledger['reserved']=0
        self.assertEqual(select_group(manifest,ledger,900),(['a','b'],1))

class SettlementTests(unittest.TestCase):
    def test_verified_charges_release_only_completed_allowances(self):
        from app.crawl_pdfs_batch import settle_completed
        ledger={'initial_balance':100,'reserved':7,'attempts':{'a':{'status':'extracted','reserved':5,'reported_credits':4},'b':{'status':'failed','reserved':2}}}
        settle_completed(ledger,96)
        self.assertEqual(ledger['reserved'],6)
        self.assertEqual(ledger['attempts']['b']['reserved'],2)
        settle_completed(ledger,96)
        self.assertEqual(ledger['reserved'],6)

    def test_unreconciled_account_usage_blocks_release(self):
        from app.crawl_pdfs_batch import settle_completed
        ledger={'initial_balance':100,'reserved':5,'attempts':{'a':{'status':'extracted','reserved':5,'reported_credits':4}}}
        with self.assertRaises(ValueError): settle_completed(ledger,90)
        self.assertEqual(ledger['reserved'],5)
