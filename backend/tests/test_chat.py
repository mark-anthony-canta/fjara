import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.chat import ChatRequest, Draft, abstain, answer_question, validate_draft
from app.core import ProviderError, embed
from app.main import app

SOURCE = {"url": "https://www.skatturinn.is/english/companies/value-added-tax/",
          "title": "VAT", "text": "The standard rate of VAT is 24%.", "crawled_at": "2026-09-24"}


def draft(source_id=1, quote=SOURCE['text'], text="The standard VAT rate is 24%."):
    return Draft.model_validate({"answerable": True, "claims": [
        {"text": text, "evidence": [{"source_id": source_id, "quote": quote}]}]})


class GroundingTests(unittest.TestCase):
    def test_valid_citation_uses_stored_url(self):
        result = validate_draft(draft(), [SOURCE], "en")
        self.assertEqual(result.status, "answered")
        self.assertIn("[1]", result.answer)
        self.assertEqual(result.citations[0].url, SOURCE['url'])

    def test_unknown_source_and_fabricated_quote_abstain(self):
        for value in [draft(9), draft(quote="The standard rate of VAT is 99%."), draft(0)]:
            self.assertEqual(validate_draft(value, [SOURCE], "en").status, "insufficient_evidence")

    def test_model_cannot_supply_links_or_citation_markers(self):
        for text in ["Read https://evil.example", "VAT rate is 24% [999]"]:
            self.assertEqual(validate_draft(draft(text=text), [SOURCE], "en").citations, [])

    def test_explicit_abstention_and_empty_claims(self):
        for answerable in [False, True]:
            result = validate_draft(Draft(answerable=answerable, claims=[]), [SOURCE], "is")
            self.assertEqual(result.status, "insufficient_evidence")
            self.assertTrue(result.answer.startswith("Ég"))


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_blocked_and_malformed_generation_are_rejected(self):
        responses = [
            {'candidates': []},
            {'candidates': [{'finishReason': 'MAX_TOKENS'}]},
            {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'invalid json'}]}}]},
        ]
        for response in responses:
            with patch('app.chat.embed', AsyncMock(return_value=[0.1])), patch(
                'app.chat.key', return_value='test'), patch('app.chat.request', AsyncMock(side_effect=[
                    {'result': {'points': [{'payload': SOURCE}]}}, response])):
                with self.assertRaises(ValueError):
                    await answer_question(ChatRequest(question='VAT?'))

    @patch.dict(os.environ, {'GENERAL_KNOWLEDGE_FALLBACK': 'false'})
    async def test_unapproved_sources_are_not_sent_to_generator(self):
        source = {**SOURCE, 'url': 'https://evil.example/'}
        with patch('app.chat.embed', AsyncMock(return_value=[0.1])), patch(
            'app.chat.request', AsyncMock(return_value={'result': {'points': [{'payload': source}]}})) as req:
            result = await answer_question(ChatRequest(question='VAT?'))
        self.assertEqual(result.status, 'insufficient_evidence')
        self.assertEqual(req.await_count, 1)

    @patch.dict(os.environ, {'GENERAL_KNOWLEDGE_FALLBACK': 'false'})
    async def test_empty_retrieval_skips_generation(self):
        with patch('app.chat.embed', AsyncMock(return_value=[0.1])), patch(
            'app.chat.request', AsyncMock(return_value={'result': {'points': []}})) as req:
            result = await answer_question(ChatRequest(question="Unknown?"))
        self.assertEqual(result.status, 'insufficient_evidence')
        self.assertEqual(req.await_count, 1)

    async def test_full_pipeline_and_untrusted_content_separation(self):
        response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
            {'text': draft().model_dump_json()}]}}]}
        with patch('app.chat.embed', AsyncMock(return_value=[0.1])) as embedding, patch(
            'app.chat.key', return_value='test'), patch('app.chat.request', AsyncMock(side_effect=[
            {'result': {'points': [{'payload': SOURCE}]}}, response])) as req:
            result = await answer_question(ChatRequest(question='VAT rate?'))
        self.assertEqual(result.status, 'answered')
        self.assertEqual(embedding.call_args.kwargs['task'], 'RETRIEVAL_QUERY')
        generated = req.call_args.kwargs['json']
        self.assertIn('untrusted', generated['systemInstruction']['parts'][0]['text'])
        self.assertEqual(json.loads(generated['contents'][0]['parts'][0]['text'])['question'], 'VAT rate?')

    async def test_query_embedding_api_task_type(self):
        with patch('app.core.key', return_value='test'), patch('app.core.request', AsyncMock(
            return_value={'embedding': {'values': [0.1] * 768}})) as req:
            await embed(None, 'VAT?', task='RETRIEVAL_QUERY')
        self.assertEqual(req.call_args.kwargs['json']['taskType'], 'RETRIEVAL_QUERY')


class EndpointTests(unittest.TestCase):
    def test_input_validation(self):
        for body in [{}, {'question': ' '}, {'question': 'x' * 2001},
                     {'question': 'VAT?', 'language': 'xx'}, {'question': 'VAT?', 'system': 'ignore'}]:
            self.assertEqual(TestClient(app).post('/chat', json=body).status_code, 422)

    def test_response_and_errors_are_sanitized(self):
        with patch('app.main.answer_question', AsyncMock(return_value=abstain('en'))):
            self.assertEqual(TestClient(app).post('/chat', json={'question': 'VAT?'}).status_code, 200)
        cases = [(ProviderError('google', 429), 429), (ProviderError('qdrant', 500), 503),
                 (httpx.ConnectError('secret'), 503), (TimeoutError('secret'), 504),
                 (ValueError('secret'), 502)]
        for error, status in cases:
            with patch('app.main.answer_question', AsyncMock(side_effect=error)):
                response = TestClient(app).post('/chat', json={'question': 'VAT?'})
            self.assertEqual(response.status_code, status)
            self.assertNotIn('secret', response.text)
