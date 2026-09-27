import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.core import request
from app.main import app


class ApiTests(unittest.TestCase):
    def test_health(self):
        self.assertEqual(TestClient(app).get('/health').json(), {'status': 'ok'})

    def test_readiness_requires_content(self):
        for count, status in [(0, 503), (12, 200)]:
            with patch('app.main.request', AsyncMock(return_value={'result': {'points_count': count}})):
                response = TestClient(app).get('/ready')
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()['chunks'], count)

    def test_readiness_handles_outage(self):
        with patch('app.main.request', AsyncMock(side_effect=httpx.ConnectError('offline'))):
            self.assertEqual(TestClient(app).get('/ready').status_code, 503)


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_error_does_not_expose_body(self):
        transport = httpx.MockTransport(lambda req: httpx.Response(401, text='private-provider-data'))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(RuntimeError) as error:
                await request(client, 'GET', 'https://example.com')
        self.assertNotIn('private-provider-data', str(error.exception))
        self.assertIn('401', str(error.exception))
