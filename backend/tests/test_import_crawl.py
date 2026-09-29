import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app import import_crawl as subject

URL = 'https://www.skatturinn.is/english/test/'
JOB = '01a0e6ca-cf71-70dd-8071-cb8cab0fad31'

def archive():
    return {'createdAt': '2026-09-28T06:54:06Z', 'data': [
        {'metadata': {'sourceURL': URL}, 'markdown': 'Useful article text.'}]}

class ImportTests(unittest.IsolatedAsyncioTestCase):
    def test_menu_removal_preserves_articles(self):
        menu = '\n'.join(f'- [Link{i}](https://example.com)' for i in range(6))
        for heading in ('English', 'Síðuvalmynd'):
            text = f'# Article\nBefore\n## {heading}\n{menu}\n## Details\nAfter'
            self.assertEqual(subject.clean_markdown(text), '# Article\nBefore\n## Details\nAfter')
        self.assertEqual(subject.clean_markdown('## English\nArticle text'), '## English\nArticle text')

    def test_prepare_filters_duplicates_and_external_redirects(self):
        data = archive()
        data['data'] += [data['data'][0], {'metadata': {'sourceURL': URL, 'url': 'https://evil.test/'}, 'markdown': 'Bad'}, {'metadata': {'sourceURL': URL}, 'markdown': ''}]
        records, skipped = subject.prepare(data)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(skipped), 3)
        self.assertEqual(records[0]['crawled_at'], '2026-09-28T06:54:06+00:00')
        with self.assertRaises(ValueError):
            subject.prepare(data, '2026-09-28')

    async def test_download_rejects_external_pagination_before_request(self):
        response = {'status': 'completed', 'data': [], 'next': 'https://evil.test/'}
        with patch.object(subject, 'request', AsyncMock(return_value=response)) as request, patch.object(subject, 'key', return_value='test'):
            with self.assertRaises(ValueError):
                await subject.download(None, JOB)
            self.assertEqual(request.await_count, 1)

    async def test_download_pagination(self):
        responses = [{'status': 'completed', 'data': [1], 'next': f'https://api.firecrawl.dev/v2/crawl/{JOB}?skip=1'}, {'status': 'completed', 'data': [2]}]
        with patch.object(subject, 'request', AsyncMock(side_effect=responses)), patch.object(subject, 'key', return_value='test'):
            self.assertEqual((await subject.download(None, JOB))['data'], [1, 2])

    async def test_embedding_failure_preserves_existing_points(self):
        responses = [{'result': {'exists': True}}, {'result': {'config': {'params': {'vectors': {'size': 768, 'distance': 'Cosine'}}}}}, {'result': {'count': 0}}]
        with patch.object(subject, 'request', AsyncMock(side_effect=responses)) as request, patch.object(subject, 'key', return_value='test'), patch.object(subject, 'embed', AsyncMock(side_effect=ValueError('bad vector'))):
            with self.assertRaises(ValueError):
                await subject.index_records(None, subject.prepare(archive())[0], Path('unused'))
            self.assertFalse(any('delete' in call.args[2] or call.args[1] == 'PUT' for call in request.await_args_list))

    async def test_resume_skips_embeddings_and_finishes_cleanup(self):
        responses = [{'result': {'exists': True}}, {'result': {'config': {'params': {'vectors': {'size': 768, 'distance': 'Cosine'}}}}}, {'result': {'count': 1}}, {'result': True}]
        with tempfile.TemporaryDirectory() as directory, patch.object(subject, 'request', AsyncMock(side_effect=responses)) as request, patch.object(subject, 'key', return_value='test'), patch.object(subject, 'embed', AsyncMock()) as embed:
            report = await subject.index_records(None, subject.prepare(archive())[0], Path(directory) / 'report.json')
            embed.assert_not_awaited()
            self.assertEqual(report['documents'][0]['status'], 'unchanged')
            self.assertIn('/points/delete', request.await_args.args[2])
