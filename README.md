# Fjara

Icelandic accounting and tax question answering, following the supplied four-week roadmap.

## Current milestone: Week 3 implemented; Docker verification pending

Implemented: FastAPI health/readiness endpoints, persistent Qdrant storage, bounded Firecrawl → Gemini → Qdrant ingestion, grounded question answering, and a responsive Next.js chat interface with citations and progress streaming. Deployment and production hardening belong to Week 4.

## Browser interface

Run `docker compose up -d --build` and open http://localhost:3000. The frontend proxies same-origin `/api/chat` requests to the backend; provider keys remain on the backend. `BACKEND_URL` is a server-only setting, defaulting to `http://127.0.0.1:8000` for local frontend development and `http://backend:8000` in Compose.

The interface includes suggested questions, English/Icelandic answer selection, clickable citation references, expandable supporting quotes and crawl dates, retry, cancellation, and a new-conversation button. History is held only in the current tab's memory and disappears on reload; each question remains independent.

`POST /chat/stream` uses server-sent events over a POST request: `status`, `answer`, `done`, or `error`. The stream starts immediately and sends periodic keepalive comments. Answer text is deliberately buffered until citation validation completes, then sent as one verified answer event; this is progress streaming, not unchecked token-by-token output. Disconnecting cancels pending backend work, although providers may still charge for work already started. The existing JSON `/chat` endpoint remains available.

For local frontend development:

```powershell
cd frontend
npm ci
npm run dev
```

Frontend checks: `npm test`, `npm run typecheck`, and `npm run build`. Backend tests run from `backend/` with `..\.venv\Scripts\python.exe -m unittest discover -s tests -q`.

Browser checks: start the local frontend on port 3001 (`npm run dev -- --port 3001`), then run `npm run test:browser`. The test uses installed Microsoft Edge by default, mocks answer responses, and saves ignored screenshots under `frontend/test-results/`. Set `FRONTEND_URL` and `BROWSER_CHANNEL` to override the URL or browser channel.

The optional local proxy test uses fixture answers rather than provider APIs: run `python -m tests.serve_fixture` from `backend/`, then `node tests/proxy.mjs` from `frontend/`. Stop the fixture server after the test; it binds port 8000 and must not run alongside the actual backend.

## Ask a question

After rebuilding the backend, use `/docs` or PowerShell:

```powershell
$body = @{ question = 'What are the standard and reduced VAT rates in Iceland?'; language = 'en' } | ConvertTo-Json
Invoke-RestMethod http://localhost:8000/chat -Method Post -ContentType 'application/json' -Body $body
```

Use `language: "is"` for Icelandic responses. Each question is independent; conversation history is not supported yet. Questions are limited to 2,000 characters. Each request uses one query embedding and, when relevant excerpts are found, one generation call.

The response contains `answer`, `status` (`answered` or `insufficient_evidence`), and `citations` with source URLs, exact supporting quotes, and crawl timestamps. The server verifies quote presence and source identifiers before returning citations. This checks provenance, not semantic entailment: a valid quote alone cannot guarantee that every generated claim is correct. The corpus is a dated snapshot of five English pages; it does not cover all Icelandic tax topics or guarantee current rules.

Retrieval selects at most five chunks using the same embedding model with `RETRIEVAL_QUERY`. `RETRIEVAL_MIN_SCORE` defaults to `0.55`; this is an initial heuristic, not a calibrated confidence probability. Insufficient evidence yields an abstention. Invalid provider responses return 502, unavailable services 503, timeouts 504, and provider quota limits 429. Errors exclude credentials and provider response bodies.

Run the opt-in live evaluation from `backend/` with `..\.venv\Scripts\python.exe evaluate.py`. It makes five requests using provider credits and saves results under ignored `backend/data/week2-evaluation.json`. Passing is a smoke check, not a comprehensive tax-accuracy assessment.

When Docker is unavailable, `..\.venv\Scripts\python.exe evaluate_generation.py` tests live Gemini using fixed VAT excerpts from saved `backend/data/` snapshots. This bypasses Qdrant and the HTTP endpoint, so it does not establish end-to-end retrieval quality. Its separate report is `backend/data/week2-generation-smoke.json`.

Firecrawl is integrated through its REST API inside the application. Claude MCP configuration is unnecessary for this backend. No global CLI or agent skills installation is required.

## Setup

1. Copy `.env.example` to `.env` if `.env` does not already exist. Set `FIRECRAWL_API_KEY` and `GEMINI_API_KEY` locally. Never commit this file.
2. Start Docker Desktop (Linux containers).
3. From this directory:

```powershell
docker compose up -d --build qdrant backend
docker compose --profile ingest run --rm ingest
Invoke-RestMethod http://localhost:8000/ready
```

API docs: http://localhost:8000/docs. `/health` reports process health; `/ready` returns 503 until Qdrant has indexed content.

Qdrant is exposed at http://localhost:16333 (dashboard: http://localhost:16333/dashboard). Windows reserved ports 6318–6417 on this workstation, preventing Docker from binding host port 6333. Compose therefore maps host port 16333 to container port 6333. Backend and ingestion containers still connect internally to `http://qdrant:6333`; local Python uses `http://localhost:16333`. The port change preserves the database volume.

Run ingestion manually, one job at a time. Each run makes up to five Firecrawl requests and one Gemini request per chunk, using provider credits. Rerunning replaces outdated versions after successful embedding and upsert. An interruption between upsert and cleanup can leave old versions until the next successful run. Removing a URL from the seed list does not automatically delete its existing vectors.

To resume after three completed sources, use `docker compose --profile ingest run --rm --no-deps ingest python -m app.ingest --offset 3`. Offsets are zero-based positions in `sources.json`; use the completed-source logs to choose the position. HTTP errors report the provider hostname and status without exposing response bodies or credentials.

Downloaded source snapshots are stored in ignored `data/`. Qdrant persists in the Compose volume. Do not run `docker compose down -v` unless you intend to discard that database.

## Local Python development

Use Python 3.12 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
cd backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
..\.venv\Scripts\python.exe -m app.ingest --scrape-only --limit 1
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The local ingestion command runs from `backend/`; Docker handles this working directory automatically. Local snapshots go to `backend/data/`. If Python or Docker is installed but not recognized, restart the terminal/app after installation or use the executable's full path.

On this workstation, Docker is at `C:\Users\Mark\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`. In PowerShell, invoke it with `&` followed by the quoted path and the Compose arguments above.

## Sources and model configuration

`backend/sources.json` contains five verified official pages: VAT, contractors, VAT reimbursement, company registration, and filing a tax return. The roadmap's other proposed domains are not treated as verified sources. Initial coverage is English; add reviewed Icelandic pages in a later ingestion pass.

Embedding uses `gemini-embedding-001` with 768 dimensions and retrieval-document task type. Changing embedding models requires a new collection and a full reindex, even when dimensions match. Future query embeddings must use the same model/dimensions and retrieval-query task type.

`GEMINI_MODEL=gemini-3.5-flash-lite` records the selected answer-generation model for Week 2. Keep this separate from `GEMINI_EMBEDDING_MODEL`; generation models cannot be substituted for embedding models. Google's model metadata confirmed generation support for this configured model.

References: [Firecrawl scrape API](https://docs.firecrawl.dev/api-reference/endpoint/scrape), [Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings), [Qdrant v1.17.0](https://github.com/qdrant/qdrant/releases/tag/v1.17.0).

## Next milestones

- Week 1 complete: all five pages indexed and `/ready` reports 60 chunks.
- Week 2 complete: `/chat`, retrieval, generated answers, verified citation provenance, abstention, 20 passing local tests, and five passing Docker-based end-to-end smoke cases.
- Week 3 implemented: responsive Next.js interface, validated-answer progress streaming, clickable citations, and Docker frontend configuration. Local browser and proxy checks pass; the full Docker run remains pending recovery of Docker Desktop.
- Week 4: retries, rate limits, authentication before public exposure, evaluation, scheduled refresh, and deployment.

This development stack binds only to localhost. It is not a public production deployment.

## Week 3 verification on 2026-09-28

- 23 backend tests and three frontend stream-parser tests pass.
- The Next.js production build, including TypeScript checking, passes.
- Automated Microsoft Edge checks pass at desktop (1440 × 1000) and mobile (390 × 844) sizes: question input, language selection, source quotes/links, abstention, retry, cancellation, new conversation, HTTP errors, and stream errors. No browser exceptions or horizontal overflow were observed. Answer responses in these browser tests are fixtures.
- The real Next.js server proxy successfully forwarded FastAPI SSE status/answer/done events, citation data, quota errors, and input-validation errors using a local fixture backend. The fixture was stopped after testing.
- Docker Desktop again failed to start because of its `sailor-ingest.sock` error. Per the user's direction, testing continued locally. The new frontend container and integrated live Gemini path have not been verified in Docker yet; run `docker compose up -d --build` after Docker recovers, then test a question at http://localhost:3000.

## Version control

The Week 1–2 baseline is on `codex/week-1-2-baseline`. Week 3 work is on `codex/week-3-chat-ui`. Future changes should use a new `codex/` branch, be committed after relevant checks, and be pushed to the GitHub remote. Secrets, downloaded data, and test screenshots stay ignored.

## Verification on 2026-09-28

All 20 local tests passed. Live Gemini generation with fixed saved VAT excerpts passed five smoke cases: English VAT, Icelandic VAT, unrelated questions, unsupported future rates, and an instruction to fabricate a rate. The fabrication check accepts either abstention or a cited correction that excludes the false rate. Exact quotation instructions were clarified after an initial English answer abstained. This is a small, nondeterministic smoke sample; citation presence does not prove semantic accuracy.

The full Docker-based `/chat` evaluation passed all five cases with HTTP 200 after resolving the Windows host-port reservation. These requests exercised FastAPI → live Gemini query embeddings → persisted Qdrant retrieval → live Gemini generation → citation validation. `/ready` returned HTTP 200 and 60 chunks, confirming that stored data survived container recreation. Reports are saved under ignored `backend/data/week2-evaluation.json` and `backend/data/week2-generation-smoke.json`. Both containers were left running; no database reset or removal was performed. This verification does not diagnose the separate reported Codex sign-in issue.

## Verification on 2026-09-24

Eight local tests passed (chunking, source restrictions, health/readiness, and sanitized provider errors). Docker images built successfully and FastAPI plus Qdrant are running locally. Live Firecrawl extraction and Gemini embedding succeeded for all five sources, yielding 60 stored chunks. An initial provider failure after three sources was recovered by resuming at offset 3. `/ready` returned HTTP 200 with 60 chunks. A live retrieval-query embedding for an Icelandic VAT question returned the official VAT page for all three top results. The configured generation model's metadata endpoint returned HTTP 200 and confirmed `generateContent` support; answer generation itself is not implemented or tested yet. Changes are local and have not been pushed to GitHub.
