import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from app import embedding_cache as subject

class EmbeddingCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_preserves_order_and_avoids_repeated_requests(self):
        vectors=[[float(i)]*768 for i in (1,2)]
        with tempfile.TemporaryDirectory() as directory, patch.object(subject,'key',return_value='test'), patch.object(subject,'request',AsyncMock(return_value={'embeddings':[{'values':v} for v in vectors]})) as request:
            path=Path(directory)
            self.assertEqual(await subject.embed_cached(None,['a','b'],16,path),vectors)
            self.assertEqual(await subject.embed_cached(None,['b','a'],16,path),list(reversed(vectors)))
            self.assertEqual(request.await_count,1)
            body=request.await_args.kwargs['json']
            self.assertEqual(body['requests'][0]['taskType'],'RETRIEVAL_DOCUMENT')

    async def test_invalid_batch_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(subject,'key',return_value='test'), patch.object(subject,'request',AsyncMock(return_value={'embeddings':[{'values':[1]}]})):
            with self.assertRaises(ValueError): await subject.embed_cached(None,['a'],16,Path(directory))
            self.assertEqual(list(Path(directory).iterdir()),[])

    async def test_rate_limit_retries_after_wait(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(subject,'key',return_value='test'), patch.object(subject,'request',AsyncMock(side_effect=[subject.ProviderError('provider',429),{'embeddings':[{'values':[0.1]*768}]}])), patch.object(subject.asyncio,'sleep',AsyncMock()) as sleep:
            await subject.embed_cached(None,['a'],16,Path(directory))
            sleep.assert_awaited_once_with(60)
