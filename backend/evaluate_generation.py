"""Live Gemini smoke test with fixed saved excerpts; does NOT test retrieval.

Run explicitly with python evaluate_generation.py; consumes provider credits.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from app import chat
from app.core import chunks
from evaluate import CASES, check_response


async def main():
    documents = [json.loads(p.read_text(encoding='utf-8')) for p in Path('data').glob('*.json')]
    document = next(d for d in documents if isinstance(d, dict) and 'markdown' in d
                    and '/value-added-tax/' in d['url'])
    excerpts = [text for text in chunks(document['markdown']) if '24%' in text or '11%' in text]
    points = [{'payload': {**{k: v for k, v in document.items() if k != 'markdown'}, 'text': text}}
              for text in excerpts]
    original = chat.request
    drafts = []

    async def fixed_retrieval(client, method, url, **kwargs):
        if '/points/query' in url:
            return {'result': {'points': points}}
        result = await original(client, method, url, **kwargs)
        if ':generateContent' in url:
            drafts.append(result)
        return result

    results = []
    for name, question, language, expected in CASES:
        with patch('app.chat.request', fixed_retrieval):
            result = await chat.answer_question(chat.ChatRequest(question=question, language=language))
        passed = check_response(name, expected, result.model_dump())
        results.append({'case': name, 'passed': passed, 'response': result.model_dump(),
                        'draft': drafts[-1] if drafts else None})
        print(f'{name}: {"PASS" if passed else "FAIL"}', flush=True)
    Path('data/week2-generation-smoke.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    if not all(r['passed'] for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
