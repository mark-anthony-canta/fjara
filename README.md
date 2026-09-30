# Fjara

Icelandic accounting and tax question answering, following the supplied four-week roadmap.

## Current milestone: Week 3 complete

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

Live Docker acceptance: with the Compose stack running, execute `node tests/live.mjs` from `frontend/`. It uses three real Gemini requests through port 3000, checks English SSE event order, an Icelandic browser answer with source expansion and mobile layout, and unrelated-question abstention. It saves screenshots and `test-results/live-report.json`. These requests consume API credits; the browser interaction suite above uses mocked answers.

The optional local proxy test uses fixture answers rather than provider APIs: run `python -m tests.serve_fixture` from `backend/`, then `node tests/proxy.mjs` from `frontend/`. Stop the fixture server after the test; it binds port 8000 and must not run alongside the actual backend.

## Ask a question

After rebuilding the backend, use `/docs` or PowerShell:

```powershell
$body = @{ question = 'What are the standard and reduced VAT rates in Iceland?'; language = 'en' } | ConvertTo-Json
Invoke-RestMethod http://localhost:8000/chat -Method Post -ContentType 'application/json' -Body $body
```

Use `language: "is"` for Icelandic responses. Each question is independent; conversation history is not supported yet. Questions are limited to 2,000 characters. Each request uses one query embedding and, when relevant excerpts are found, one generation call.

The response contains `answer`, `status` (`answered`, `general_knowledge`, or `insufficient_evidence`), `citations` with source URLs, exact supporting quotes, and crawl timestamps, and `general_answer` (unverified general knowledge, possibly empty; see "General knowledge fallback" below). The server verifies quote presence and source identifiers before returning citations. Each claim is checked separately: a claim is kept only if every one of its quotes appears verbatim in its cited excerpt, and unsupported claims are dropped rather than discarding the whole answer. The response abstains only when no claim survives. This checks provenance, not semantic entailment: a valid quote alone cannot guarantee that every generated claim is correct. The corpus is a dated snapshot of five English pages; it does not cover all Icelandic tax topics or guarantee current rules.

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
- Week 3 complete: responsive Next.js interface, validated-answer progress streaming, clickable citations, Docker frontend, and passing local plus live Docker browser/proxy checks.
- Extracted PDFs: 161 of 163 indexed into Qdrant (1,537 total chunks); two remaining PDFs await Gemini quota.
- Week 4: retries, rate limits, authentication before public exposure, evaluation, scheduled refresh, and deployment.

This development stack binds only to localhost. It is not a public production deployment.

## Week 3 verification on 2026-09-28

- 23 backend tests and three frontend stream-parser tests pass.
- The Next.js production build, including TypeScript checking, passes.
- Automated Microsoft Edge checks pass at desktop (1440 × 1000) and mobile (390 × 844) sizes: question input, language selection, source quotes/links, abstention, retry, cancellation, new conversation, HTTP errors, and stream errors. No browser exceptions or horizontal overflow were observed. Answer responses in these browser tests are fixtures.
- The real Next.js server proxy successfully forwarded FastAPI SSE status/answer/done events, citation data, quota errors, and input-validation errors using a local fixture backend. The fixture was stopped after testing.
- After Docker Desktop recovered, `docker compose up -d --build` successfully built and started the production frontend with FastAPI and Qdrant. `/ready` reported 60 chunks. Live requests traversed the frontend proxy, backend, Qdrant, and Gemini without fixtures. English progress arrived in 188 ms and the validated answer in 3,149 ms in this sample; these are observed timings, not a latency guarantee. The Icelandic browser answer displayed both VAT rates with expandable official citations; unrelated questions abstained. Desktop/mobile interaction tests also passed against the Docker-served frontend with mocked responses for deterministic error and cancellation scenarios. No browser exceptions or horizontal overflow were observed.

## Version control

The Week 1–2 baseline is on `codex/week-1-2-baseline`. Week 3 implementation is on `codex/week-3-chat-ui`; its Docker acceptance checks and completion notes are on `codex/week-3-docker-verification`. Future changes should use a new `codex/` branch, be committed after relevant checks, and be pushed to the GitHub remote. Secrets, downloaded data, and test screenshots stay ignored.

## Verification on 2026-09-28

All 20 local tests passed. Live Gemini generation with fixed saved VAT excerpts passed five smoke cases: English VAT, Icelandic VAT, unrelated questions, unsupported future rates, and an instruction to fabricate a rate. The fabrication check accepts either abstention or a cited correction that excludes the false rate. Exact quotation instructions were clarified after an initial English answer abstained. This is a small, nondeterministic smoke sample; citation presence does not prove semantic accuracy.

The full Docker-based `/chat` evaluation passed all five cases with HTTP 200 after resolving the Windows host-port reservation. These requests exercised FastAPI → live Gemini query embeddings → persisted Qdrant retrieval → live Gemini generation → citation validation. `/ready` returned HTTP 200 and 60 chunks, confirming that stored data survived container recreation. Reports are saved under ignored `backend/data/week2-evaluation.json` and `backend/data/week2-generation-smoke.json`. Both containers were left running; no database reset or removal was performed. This verification does not diagnose the separate reported Codex sign-in issue.

## Verification on 2026-09-24

Eight local tests passed (chunking, source restrictions, health/readiness, and sanitized provider errors). Docker images built successfully and FastAPI plus Qdrant are running locally. Live Firecrawl extraction and Gemini embedding succeeded for all five sources, yielding 60 stored chunks. An initial provider failure after three sources was recovered by resuming at offset 3. `/ready` returned HTTP 200 with 60 chunks. A live retrieval-query embedding for an Icelandic VAT question returned the official VAT page for all three top results. The configured generation model's metadata endpoint returned HTTP 200 and confirmed `generateContent` support; answer generation itself is not implemented or tested yet. Changes are local and have not been pushed to GitHub.

## Import an existing Firecrawl crawl

The app uses Firecrawl for ingestion, then answers from Qdrant; it does not browse the entire website for each question. A completed crawl in the Firecrawl dashboard is not automatically indexed.

From `backend/`, preview a completed crawl or saved JSON export:

```powershell
..\.venv\Scripts\python.exe -m app.import_crawl --crawl-id 01a0e6ca-cf71-70dd-8071-cb8cab0fad31
..\.venv\Scripts\python.exe -m app.import_crawl --file data/firecrawl-crawl-first-page.json
```

Add `--index` to generate embeddings and store the pages in the configured Qdrant collection. Keep Docker running. Downloading an existing job does not start a new crawl. The job response is archived under ignored `backend/data/`; use the saved file after Firecrawl results expire. Exports without `createdAt` need `--crawled-at` with an ISO timestamp and timezone.

The importer follows validated Firecrawl pagination, accepts only approved Skatturinn pages, removes observed repeated navigation menus, and skips failed/empty/duplicate pages. It retries transient provider failures and can be resumed with the same command without embedding completed unchanged pages again. Each page is embedded and upserted before old versions are removed. Crawl timestamps represent the job start, not the publication date. Changing embedding models still requires a separate collection and full reindex.

The supplied job contains **10 pages**, not the full website, yielding 37 cleaned chunks. Additional source coverage needs a separate reviewed crawl. The supplied VR membership question returns `insufficient_evidence`; the app must not invent union-specific percentages from general tax excerpts. A live tax-residency question successfully retrieves and cites the newly imported official tax-liability article. Local backend validation passes 29 tests, including pagination, source filtering, menu removal, failure preservation, and import resumption.

Import verification: all ten pages completed after resuming a transient Gemini HTTP 429. `/ready` reports 97 chunks, and a Qdrant payload check confirms 15 distinct source URLs. Existing 60 chunks were retained. No new Firecrawl crawl was started.

## Budgeted PDF crawling

Install the optional PDF page counter with `.\.venv\Scripts\python.exe -m pip install -r backend/requirements-pdf.txt`. From `backend/`, run `..\.venv\Scripts\python.exe -m app.crawl_pdfs --links data/crawl-pdf-links.json` to download approved PDF links and count pages without Firecrawl calls. Add `--extract --budget 900` to extract the archived URLs using Firecrawl. This is a separate operation from Qdrant indexing.

Original PDFs, extracted JSON, and the manifest/credit ledger are saved in ignored `backend/data/pdf-crawl/`. The extractor processes shorter documents first, reserves one credit per page plus a base-request allowance before each request, caps PDF parsing at the observed page count, disables enhanced proxies, checks live account balance, and never automatically repeats paid attempts. Reservations remain spent in its local budget even after failures or cheaper responses. The persisted budget cannot be increased on resume. Do not delete the ledger to resume. Other account activity can consume credits independently.

Failed or uncertain requests stop extraction for inspection. URLs on other hosts and redirects outside the approved source are rejected by the downloader. Extracted text is not automatically indexed and needs review, particularly scanned pages, forms, and historical tax documents. The page count describes the downloaded version; a remote PDF changing before extraction could affect completeness. No claim of full-site PDF coverage is made.

For faster extraction after a rate-limit interruption, `..\.venv\Scripts\python.exe -m app.crawl_pdfs_batch` resumes the existing ledger with batches of equal-page-count PDFs. It reserves the full worst-case group cost before submission, uses two concurrent workers, and persists the job ID so status polling can resume without resubmitting. Run only one extractor at a time. A crash between submission and saving the job ID leaves reserved pending entries for manual reconciliation; it never automatically resubmits them. Failed individual attempts remain recorded and are not retried by this command.

After all active jobs finish, `..\.venv\Scripts\python.exe -m app.crawl_pdfs_batch --settle` can reconcile conservative allowances and continue under the same budget. It requires exact agreement between the live account balance change and all completed documents' reported charges. It releases only completed documents' unused allowances; failed/uncertain requests retain their reservations. It refuses reconciliation when an active batch exists, charges are missing, or account usage does not match. This does not increase the 900-credit ceiling.

### PDF extraction verification on 2026-09-29

Downloaded all 166 approved PDF URLs (1,004 pages). Firecrawl extracted 163 PDFs / 868 pages, containing 3,142,731 Markdown characters. Every extracted document has nonempty text and a reported page count matching its downloaded original. This checks extraction completeness by page count, not OCR/table accuracy. The single initial HTTP 429 was explicitly retried after confirming no charge; the retry succeeded.

The account started at 903 credits and ended at 35: exactly 868 credits used, below the authorized 900-credit ceiling. Reported document charges match the balance change. Three PDFs totaling 136 pages (48, 44, and 44 pages) remain downloaded but unprocessed because no complete remaining document fits the task budget. The ledger retains 876 credits in conservative reservations, including the earlier rejected attempt. No jobs remain active.

The ignored `backend/data/pdf-crawl/` directory contains original PDFs, per-document JSON, `ledger.json`, `manifest.json`, `verification.json`, `pending-pdfs.json`, and combined `extracted-pdfs.json`. The combined export passes the importer dry run: 163 valid documents, no skipped records, and 1,551 prospective chunks. No embeddings were requested and Qdrant was not modified. All 36 backend tests pass, including budget persistence, bounded batch selection, and verified charge reconciliation.

### PDF indexing on 2026-09-30

From `backend/`, the extracted PDFs are indexed with:

```powershell
..\.venv\Scripts\python.exe -m app.import_crawl --file data/pdf-crawl/extracted-pdfs.json --index --embedding-batch-size 16
```

`--embedding-batch-size` above 1 sends up to that many chunks per `batchEmbedContents` request and caches each vector under ignored `backend/data/embedding-cache/`, keyed by model, dimensions, task type, and chunk text. A rerun after a rate limit reuses cached vectors instead of paying for them again. HTTP 429 waits 60 seconds and 5xx/connection errors back off briefly, up to four attempts per batch; the import then stops and can be resumed with the same command. The default of 1 keeps the original one-request-per-chunk path.

Status: 161 of 163 extracted PDFs are indexed. Documents already stored with a matching URL, content hash, import version, and embedding model are reported as `unchanged` and are not re-embedded. `/ready` rose from 532 to 1,537 chunks (97 web-page chunks plus 1,440 PDF chunks). The last two PDFs (111 chunks) remain unindexed because Gemini's free-tier embedding quota returned HTTP 429 on every retry; rerun the command after the quota resets. Each document is fully embedded before its upsert, so no partial documents were stored.

Live `/chat` checks against the indexed PDFs answered two form questions (RSK 5.17 supporting documents; RSK 3.30 system ID and residency) with verified quotes from the official English PDFs. This is a small smoke sample, not a coverage or accuracy evaluation. All 39 backend tests pass, including embedding-cache reuse and validation.

## Answer reliability fix on 2026-10-01

Diagnosis: "How to file tax return in Iceland?" retrieved the official filing page as its best match (similarity 0.76), and the model produced a correct answer, but one of its two quotes left out the Markdown link around a heading (`### [Log in to complete your tax return](https://innskraning.rsk.is/)`) and exceeded the 600-character schema limit. Validation was all-or-nothing, so the verified claim was discarded too and the user saw an abstention.

Changes in `backend/app/chat.py`:

- Per-claim validation. Model output is parsed leniently and each claim is verified independently; a claim is dropped if any quote is missing from its source, shorter than 15 or longer than 1,000 characters, cites an unknown source, or the claim text contains links or citation markers. Only if no claim survives does the service abstain.
- Cleaner excerpts. Before generation, lines that consist only of a link (site navigation menus) are removed, and link and image markup is reduced to plain text, so quotes can be copied exactly. Quote matching ignores link markup on both sides.
- Noise filtering. Retrieval now requests 10 candidates, skips excerpts with too little text after cleaning (menus, empty table borders), and sends at most five to the model. Data tables are kept.
- Out-of-scope sources. The annual car tax-valuation lists (RSK 6.03, 1998–2016, 19 PDFs, 822 chunks) remain in Qdrant but are excluded from retrieval by a Qdrant `must_not` filter (`EXCLUDED_SOURCES` in `chat.py`). Nothing was deleted; removing the list makes them searchable again without re-embedding.

`RETRIEVAL_MIN_SCORE` stays at 0.55, based on live calibration of 16 labelled questions. Relevant questions scored 0.61–0.78, but "What are the income tax brackets in 2026?" scored 0.606 while unrelated questions (car insurance 0.610, VR union 0.605) scored the same. Raising the threshold would block relevant questions, so unrelated questions are left to the model's abstention.

Verification: 52 backend tests pass (13 new). All 163 extracted PDFs are now indexed; `/ready` reports 1,648 chunks. Live `/chat` checks after the fix: "How to file tax return in Iceland?" answered with a citation from the official filing page (previously abstained); the VAT question answered 24% and 11% with citations; "Tell me about car insurance" abstained.

## General knowledge fallback (2026-10-01)

When the indexed sources do not cover a question, or cover only part of it, the model may add an answer from its general knowledge. It is returned separately from the verified answer and is never cited:

- `status: "answered"`: at least one claim was verified against a cited source. `answer` holds only those claims; `general_answer` may add general knowledge for the parts the sources do not cover.
- `status: "general_knowledge"`: no claim could be verified (off-topic question, nothing relevant retrieved, or every quote failed). `answer` is empty and `general_answer` holds the reply. No citations are returned.
- `status: "insufficient_evidence"`: neither part produced anything.

Generation now runs even when retrieval returns no excerpts, so off-topic questions cost one embedding and one generation call. The instructions tell the model to follow the excerpts where they conflict with its own knowledge, to say that Icelandic tax specifics from general knowledge may be out of date and should be confirmed with Skatturinn, not to predict future rates, and to include no citations, source numbers or quotes. The server strips citation markers and any link that is not on skatturinn.is from `general_answer` and caps it at 2,500 characters. General knowledge is not checked against sources and can be wrong; the web interface shows it in a separate box labelled "General knowledge · not from official sources".

Set `GENERAL_KNOWLEDGE_FALLBACK=false` in `.env` and recreate the backend container to restore strict grounded-only answers. The opt-in `evaluate.py` now accepts either abstention or uncited general knowledge for unrelated, future-rate, and injection cases, and still fails any of them that returns citations.

Live check through `/chat` (8 questions): "What is life", "Tell me about VR Union" and a 2040 VAT-rate question returned `general_knowledge` with no citations (the 2040 answer says future rates cannot be known). "How to file tax return in Iceland?", the personal tax credit question and the Icelandic VAT question returned verified, cited claims. "Tell me about car insurance" returned one verified claim from form RSK 4.03 (insurance as a car operating cost) plus a labelled general supplement. The injection prompt returned only the cited 24% rate. After this run the instructions were tightened: claims follow the requested language, general_answer does not mention the sources, and unrelated general questions are answered explicitly (a recheck showed the model otherwise sometimes declined "What is life"). The server also drops a general_answer that is a single sentence only telling the user that rules may change and should be confirmed with Skatturinn or an accountant, provided it contains no figures; the interface already shows that caveat. 68 backend tests pass; the frontend production build, including type checking, passes in Docker.
