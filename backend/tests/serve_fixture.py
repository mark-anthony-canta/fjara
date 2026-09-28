"""Local-only upstream fixture for testing the Next.js proxy without API credits.

Run from backend/: python -m tests.serve_fixture
This module is excluded from the backend Docker image.
"""
import uvicorn
from app import main
from app.chat import ChatResponse, Citation
from app.core import ProviderError


async def fixed_answer(body):
    if body.question == 'quota test':
        raise ProviderError('fixture', 429)
    return ChatResponse(answer='Fixture answer [1]', status='answered', citations=[Citation(
        id=1, url='https://www.skatturinn.is/english/', title='Fixture source',
        quote='This is fixture evidence for a proxy test.', crawled_at='2026-09-28T00:00:00Z')])


if __name__ == '__main__':
    main.answer_question = fixed_answer
    uvicorn.run(main.app, host='127.0.0.1', port=8000)
