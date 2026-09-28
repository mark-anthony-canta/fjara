import json
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.chat import abstain
from app.core import ProviderError
from app.main import app


class StreamTests(unittest.TestCase):
    def test_checked_answer_and_done_follow_status(self):
        with patch('app.main.answer_question', AsyncMock(return_value=abstain('is'))):
            response = TestClient(app).post('/chat/stream', json={'question': 'VAT?', 'language': 'is'})
        frames = [f for f in response.text.split('\n\n') if f.startswith('event:')]
        self.assertEqual([f.splitlines()[0] for f in frames], ['event: status', 'event: answer', 'event: done'])
        self.assertIn('text/event-stream', response.headers['content-type'])
        self.assertEqual(json.loads(frames[1].split('data: ')[1])['status'], 'insufficient_evidence')

    def test_provider_error_never_emits_answer(self):
        with patch('app.main.answer_question', AsyncMock(side_effect=ProviderError('secret-host', 429))):
            response = TestClient(app).post('/chat/stream', json={'question': 'VAT?'})
        self.assertIn('event: error', response.text)
        self.assertNotIn('event: answer', response.text)
        self.assertNotIn('secret-host', response.text)

    def test_bad_input_rejected_before_stream(self):
        self.assertEqual(TestClient(app).post('/chat/stream', json={'question': ' '}).status_code, 422)
