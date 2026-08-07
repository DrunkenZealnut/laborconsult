# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**laborconsult** — Korean labor law (노동법) Q&A crawler, RAG chatbot, and wage calculator system. Corpus sourced from nodong.kr Q&A plus 법원 노동판례 / 노동부 행정해석 / 훈령·예규·고시 / 노동상담 (multiple `output_*/` dirs, each with its own crawler + metadata + upload script). Four main subsystems:

1. **Crawlers** — Scrape Q&A and legal documents into markdown files (multiple sources, see Crawlers)
2. **RAG Pipeline** — Chunk, embed (OpenAI), store in Pinecone, multi-query hybrid search with Cohere reranking
3. **Wage Calculator** — 25 Korean labor law calculators with unified facade
4. **Web API** — FastAPI + Vercel serverless chatbot with intent analysis, legal API integration, file upload, harassment assessment, agency-contact matching, public Q&A board, and answer email delivery

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Crawling pipeline (multiple sources — see Crawlers section)
python3 crawl_bestqna.py          # BEST Q&A (274 posts → output/)
python3 crawl_qna.py              # General Q&A (10K posts → output_qna/), resumable
python3 crawl_boards.py           # 자료실/판례/행정해석 등 게시판 크롤 → output_*/
python3 generate_metadata.py      # Generate metadata.json from output/

# Pinecone upload (one variant per corpus source)
python3 pinecone_upload.py        # Chunk + embed + upsert to Pinecone (Q&A)
python3 pinecone_upload.py --reset  # Reset index and re-upload
python3 pinecone_upload_legal.py  # 법원 노동판례 업로드 (다른 변형: _2025/_imgum/_counsel/_contextual)
python3 upload_new_precedents.py  # 신규 판례 증분 업로드

# Chatbot
python3 chatbot.py                # Interactive RAG chatbot
python3 chatbot.py --search-only  # Vector search only (no Claude)

# Q&A analysis (Claude Haiku batch analysis)
python3 analyze_qna.py            # Analyze all Q&A posts
python3 analyze_qna.py --limit 100 --dry-run  # Test run
python3 summarize_analysis.py     # Aggregate analysis → stats JSON + design doc

# Wage calculator tests
python3 wage_calculator_cli.py           # Run all 32 test cases
python3 wage_calculator_cli.py --case 1  # Run specific test case
python3 wage_calculator_cli.py --interactive  # Interactive mode
python3 calculator_batch_test.py         # Run all 102 batch test cases (output_qna/ 원문 필요)

# Offline test suites (API 키 불요 — CI에서도 실행, .github/workflows/tests.yml)
python3 test_wage_golden.py       # 계산 엔진 골든 테스트
python3 test_pipeline_wiring.py   # analyzer→계산기 배선 테스트 (CALC-1/2/3)
python3 test_offline_units.py     # 검색·인용·세션 모듈 단위 테스트
python3 test_abuse_guard.py       # 남용 가드(인젝션·스코프·쿼터·게시판 필터) 테스트
python3 test_llm_fallback.py      # LLM 폴백(빈응답·절단·전환 하트비트·교차벤더) 테스트

# Local API server
uvicorn api.index:app --reload --port 5555  # FastAPI dev server (port 5555)

# BM25 corpus build (Hybrid Search용, Pinecone API 필요)
# 코퍼스 업로드(pinecone_upload*) 후 재실행 → data/bm25_corpus.json.gz 커밋 필수
# (gz 미커밋 시 프로덕션 하이브리드 검색이 Dense-only로 폴백됨)
python3 build_bm25_corpus.py      # Pinecone → data/bm25_corpus.json.gz

# NLRC 판정사례 번들 갱신 (odcloud API 키 필요, 주기 실행 후 커밋)
python3 refresh_nlrc_cases.py     # odcloud → data/nlrc_cases.json

# 보유기간 경과 첨부파일 파기 (개인정보처리방침 제5항 — 주기 실행 필요)
# Supabase가 storage.objects 직접 DELETE를 차단하므로 2단계 구조다:
#   ① pg_cron이 purge_expired_data()로 DB 행 삭제 + 파일 경로를 storage_purge_queue에 적재
#   ② 이 스크립트가 Storage API로 실제 파일 삭제
# 둘 다 돌아야 방침이 이행된다. 스키마·함수는 supabase_retention_purge.sql
python3 purge_storage_orphans.py            # 큐 비우기
python3 purge_storage_orphans.py --dry-run  # 대상만 확인

# Environment check
python3 check_env.py              # Validate all API keys configured
```

## Environment Variables

Defined in `.env` (see `.env.example`):

**Required:**
- `OPENAI_API_KEY` — embeddings (text-embedding-3-small) + fallback LLM (o3)
- `PINECONE_API_KEY` — vector DB
- `ANTHROPIC_API_KEY` — primary LLM (Claude) + intent analysis

**Optional:**
- `GEMINI_API_KEY` — tertiary LLM fallback (모델은 `GEMINI_MODEL`, 기본 `gemini-pro-latest`)
- `SUPABASE_URL` / `SUPABASE_KEY` — session persistence + conversation storage
- `LAW_API_KEY` — 법제처 법령 API
- `ODCLOUD_API_KEY` — 공공데이터포털 API (중앙노동위원회 판정사례)
- `COHERE_API_KEY` — search result reranking
- `ADMIN_PASSWORD` — admin dashboard login (also default for `ADMIN_JWT_SECRET` + CAPTCHA HMAC signing)
- `ADMIN_JWT_SECRET` — JWT signing (defaults to ADMIN_PASSWORD)
- `PINECONE_INDEX_NAME` — defaults to `semiconductor-lithography` (legacy name)

**Email delivery** (`POST /api/send-email`, **not in `.env.example`**):
- `MAIL_SMTP_USERNAME` / `MAIL_SMTP_PASSWORD` — SMTP auth (required for sending; 500 if absent)
- `MAIL_SMTP_HOST` (default `smtp.gmail.com`) / `MAIL_SMTP_PORT` (default `587`, STARTTLS)
- `MAIL_FROM_EMAIL` (defaults to username) / `MAIL_FROM_NAME` (default `기초 노동상담`)

**Model config** in `app/config.py`: `claude-sonnet-5` (primary, 상수 고정), `o3` (fallback, `OPENAI_CHAT_MODEL`로 교체 가능), `gemini-pro-latest` (tertiary, `GEMINI_MODEL`). 타임아웃·재시도 예산도 같은 파일이 단일 출처다 — 값 변경 시 `docs/02-design/features/llm-fallback-hardening.design.md` §3.4 예산표를 함께 갱신할 것.

## Architecture

### Web API (`api/` + `app/`)

FastAPI app deployed to Vercel serverless. `api/index.py` is the entry point.

**Endpoints** (all in `api/index.py`):

*Chat:* (3경로 모두 `_guard_chat_request()` 선통과 — 아래 Abuse Guard 참조)
- `GET /api/health` — health check
- `GET /api/chat/stream?message=...` — SSE streaming (text only)
- `POST /api/chat/stream` — SSE streaming (with file attachments as base64)
- `POST /api/chat` — sync full response

*Admin* (require Bearer JWT from login):
- `POST /api/admin/login` → JWT token (24h expiry)
- `GET /api/admin/stats` — totals + 30-day daily + category counts
- `GET /api/admin/conversations` — paged, supports `search`/`category`/`date_from`/`date_to`
- `GET /api/admin/conversations/{conv_id}` — 단일 대화 상세 (+ attachments)
- `GET /api/admin/abuse?days=7` — 남용 이벤트 집계·최근 목록·활성 차단 (`abuse_summary` RPC)
- `POST /api/admin/abuse/unblock` — 수동 차단 해제 (`abuse_unblock` RPC)

*Public Q&A board* (all `_anonymize()` applied):
- `GET /api/board/recent`, `GET /api/board/categories`, `GET /api/board/search?q=&category=`, `GET /api/board/{item_id}` — read AI conversations (`qa_conversations`) + user posts (`board_posts`), merged
- `GET /api/captcha` — math CAPTCHA + HMAC-signed token (5min expiry, signed with `JWT_SECRET`)
- `POST /api/board/write` — user post: CAPTCHA verify → IP rate-limit (3/60s) → length/bad-word validation → bcrypt password (rounds=12) → INSERT `board_posts`
- `POST /api/board/{post_id}/delete` — bcrypt password check → soft delete (`status='deleted'`)

*Email:*
- `POST /api/send-email` — SMTP delivery of an answer; in-memory rate-limit 10/60s, `_sanitize_html()` strips `<script>`/`on*=`, wraps body in branded template (needs `MAIL_*` env)

*Static serving:* `GET /` (index.html), `/admin` (admin.html), `/calculators`+`/calculators.html`, `/calculator_flow/{filename}` (`.html` allowlist + `commonpath` traversal guard)

**Static pages:**
- `public/index.html` — 메인페이지(~1,470줄, 단일 파일): Google 스타일 중앙 랜딩(로고 `#landing` + 채팅 입력창). 첫 메시지 전송 시 `expandChat()`이 `.chat-card.active`를 추가해 채팅 영역 확장. FAQ(6 카테고리, `FAQ_DATA`)와 질문게시판(`#board-section`)은 인라인이 아니라 **햄버거 슬라이드 메뉴**(`.slide-menu`)에서 접근. 각 답변 하단 액션 버튼: `actionCopy`/`actionPDF`/`actionMarkdown`/`actionEmail`(이메일은 `prompt()`로 주소 입력 → `POST /api/send-email`). 디자인: Swiss Modernism 2.0 (아래 참조).
- `public/calculators.html` — 25개 계산기 흐름도 메뉴 (사이드바 + iframe 뷰어)
- `public/calculator_flow/` — 25개 standalone HTML 계산기 시각화 (SVG 플로우차트)
- `public/admin.html` — 관리자 대시보드 (라우트: `/admin`, `/admin.html`은 404)

**SSE event types** (consumed by `public/index.html::readSSE()`):
- `session` — session_id (emitted by `api/index.py`, not pipeline)
- `status` — progress text (e.g., "질문 분석 중...")
- `chunk` / `text` — streaming / non-streamed answer text
- `replace` — full answer replacement (after citation correction)
- `contacts` — agency contact cards (노동위/고용센터/근로복지공단)
- `sources` — 검색 출처 목록 (`_build_sources_payload()`, 상위 5건 {title, section, source_type, score, origin}) → 프론트 `renderSources()`가 답변 하단에 표시
- `meta` — calc_result (프론트는 현재 미표시 — 수치 카드 UI는 제품 결정 대기)
- `error` — error message
- `done` — stream end marker

### Abuse Guard (`app/core/abuse_guard.py`) — chatbot-security

악의적 접근·노동법 외 용도 사용을 LLM 호출 전(또는 의도분석 1회 비용)에 차단하는 2단 가드.
설계: `docs/02-design/features/chatbot-security.design.md`. **전 계층 fail-open** — 가드 내부
예외나 Supabase 장애가 상담을 막지 않는다.

**1단 (엔드포인트, `api/index.py::_guard_chat_request`)** — 반드시 `get_or_create_session()`·
첨부 파싱보다 **먼저** 호출(session_id 검증이 세션 생성 전이어야 하고, 차단 대상이 파싱 비용을
지불하지 않도록):
1. `validate_message()` — 길이(기본 2,000자) · 제어문자 제거 · NFC · `session_id` 형식(`^[A-Za-z0-9-]{8,64}$`, 불일치 시 무시하고 신규 발급)
2. `_check_rate_limit(store=_chat_rate)` — IP당 5회/60초. **인메모리라 Vercel 인스턴스별 베스트에포트**(총량 방어는 3의 쿼터가 담당)
3. `check_guard()` — `chat_guard_check` RPC 1왕복(차단 조회 + 일일 쿼터 원자 증가, 기본 50/일)
- 거절 시 `GuardRejection` → `/api/chat`은 HTTP 400/429, 스트림 2경로는 `_sse_error()`

**2단 (파이프라인, `process_question(guard_ctx=...)`)** — `guard_ctx=None`이면 가드 전체 비활성
(CLI·`benchmark_pipeline.py`·E2E 테스트 호출부 무변경):
- `scan_injection()` — 정규식+가중치, **의도분석 이전**이라 차단 시 LLM 호출 0회
- `scope_gate_decision()` — `analyze_intent`의 `is_labor_related`에 **편승**(추가 LLM 호출 0회). block 시 RAG·법령 API·답변 LLM 전부 생략
- `scan_leak()` — 답변 완성 후 시스템 프롬프트 유출 감지 → 기존 `replace` 이벤트로 대체 + 저장 금지
- 저장 게이팅 — block/leak은 미저장, monitor 의심은 `metadata.guard_flag` 기록 후 게시판 노출 제외

**인젝션 패턴(`INJECTION_PATTERNS`) 수정 시 주의**: 노동상담 언어와 공격 언어는 어휘를 공유한다
("무시"·"규칙"·"역할 변경"). `_BENIGN_ACTOR` 억제자가 "제3자(회사·상사) 주어 서술"을 무효화해
오탐을 막으므로, 패턴 변경 시 `test_abuse_guard.py`의 코퍼스 회귀(공격 38건 차단율 ≥90%,
정상 35건 오차단 0)를 반드시 통과시킬 것.

**운영**: `ABUSE_GUARD_MODE`·`SCOPE_GATE_MODE`를 `monitor`로 배포해 1주 관측 → 오탐 0 확인 후
`block` 전환. 즉시 완화는 `off`. Supabase 스키마는 `supabase_abuse_guard.sql`(테이블 3종 +
SECURITY DEFINER RPC 4개). **fail-open은 조용하므로 배포 후 쿼터 양성 검증 필수**
(`DAILY_CHAT_QUOTA=3`으로 4번째 요청이 실제 429인지).

### Pipeline Flow (`app/core/pipeline.py`)

`process_question()` is the main orchestrator. It yields SSE events:

1. **Intent analysis** → `analyzer.py` (Claude tool_use extracts params, `NUMERIC_RANGES` guardrails, timeout 12s)
2. **Branching**:
   - **Wage calculation**: `_analysis_to_extract_params()` → `_run_calculator()` (extracted_info → `WageInput` 인라인 배선, `calculation_types` 전체를 union 라우팅) → calculators → formatted result. 계산 예외 시 오류 문자열 주입 없이 None(상담 경로 진행)
   - **Harassment assessment**: `harassment_assessor.assess_harassment()` → element scoring
   - **Legal consultation**: `legal_consultation.py` (topic→law mapping) + RAG + legal API
3. **RAG search** → Adaptive complexity classification (`classify_complexity()` → SIMPLE/MODERATE/COMPLEX) → `query_decomposer.py` (LLM multi-query) → `rag.py::search_hybrid()` (BM25+Dense RRF fusion → Pinecone 2-group parallel) → `rerank_results()` (Cohere) → Self-RAG relevance filter (COMPLEX only, `self_rag.py`) + `graph.py` (GraphRAG multi-hop)
4. **Legal API** → `legal_api.py` (법제처, circuit breaker + L1/L2/L3 cache) + `nlrc_cases.py` (판정사례 360건 — `data/nlrc_cases.json` 번들 우선 로드, 부재 시에만 odcloud API 폴백; 갱신은 `refresh_nlrc_cases.py`). `precedent_query.py::build_precedent_queries()` expands precedent search terms.
5. **Source conflict resolution** → `conflict_resolver.py::annotate_source_priority()` tags hits by source-type priority before they reach the LLM.
6. **Agency contacts** → `labor_offices.py` / `employment_centers.py` / `comwel_offices.py` match the user's region to 노동위원회(14)/고용센터(133)/근로복지공단(63) and emit a `contacts` event.
7. **LLM streaming** → Claude → OpenAI → Gemini fallback chain (`_stream_answer()` in `pipeline.py`)
8. **Citation validation** → `citation_validator.py` detects hallucinated case numbers, sends `replace` event
9. **Persistence** → Supabase conversation + session snapshot

**Other `app/core/` modules:** `composer.py` now holds only `compose_follow_up()` — **legacy**, kept solely because `test_followup_consistency*.py` import it; the web pipeline builds its answer inline (`_stream_answer()`) and never calls it. (The former `calculator.py`/`converter.py` analysis→calculator bridge was removed as orphaned dead code — the pipeline converts `extracted_info` → `WageInput` inline.)

### Crawlers

All crawlers use `lxml` parser (not `html.parser` — it has `<hr>` void element bugs) and `markdownify` for HTML-to-markdown conversion. Each produces markdown files named `{post_id}_{title}.md`.

- `crawl_bestqna.py` → `output/` (BEST Q&A, ~274 posts)
- `crawl_qna.py` → `output_qna/` (general Q&A, ~10K posts, resumable via saved file detection)
- `crawl_2025.py`, `crawl_imgum.py`, `crawl_boards.py` — variant crawlers for other board sections (2025 Q&A, 임금/근로감독 자료, 자료실)
- Additional corpus dirs (untracked, fed by their own crawl/metadata/upload scripts): `output_법원 노동판례/`, `output_노동부 행정해석/`, `output_훈령예규고시지침/`, `output_자료실/`, `nodong_counsel/`, `output_legal_cases/`
- Each source has a matching `generate_metadata_*.py` and `pinecone_upload_*.py` (e.g. `_2025`, `_imgum`, `_legal`, `_counsel`, `_contextual`) — keep the three in sync when adding a source

### RAG Pipeline

- **Chunking**: Section-based (h2/h3) split, max 700 chars, 80 char overlap. Critical: `split_by_size` must have `end >= len(text): break` guard to prevent tiny trailing chunks.
- **Embedding**: OpenAI text-embedding-3-small (1536 dim)
- **Vector DB**: Pinecone Serverless (AWS us-east-1, cosine metric), 3 namespaces
- **Hybrid Search**: `bm25_search.py` (BM25 keyword, 쿼리별 검색 후 `rrf_merge_ranked_lists()` 병합) + Dense (Pinecone) → Reciprocal Rank Fusion (`search_hybrid()` in `rag.py`). BM25 uses `rank_bm25` with Mecab tokenizer (fallback: regex). Corpus built by `build_bm25_corpus.py` → `data/bm25_corpus.json.gz`(**커밋 대상** — 없으면 프로덕션이 Dense-only 폴백, raw json은 gitignore). Graceful fallback to Dense-only if BM25 unavailable.
- **Adaptive Retrieval**: `classify_complexity()` in `query_decomposer.py` scores query complexity → SIMPLE (top_k=8, no decomposition) / MODERATE (top_k=15) / COMPLEX (top_k=20, force decomposition, Self-RAG enabled). `COMPLEXITY_PARAMS` dict drives all dynamic parameters.
- **Multi-query**: `query_decomposer.py` decomposes user query via LLM, merged with rule-based queries, deduped. `force` param bypasses `_should_decompose()` for COMPLEX queries.
- **Reranking**: Cohere Rerank v3.5 (optional, falls back to cosine score sorting)
- **Self-RAG**: `self_rag.py` — Claude Haiku judges relevance per document (COMPLEX only). `filter_by_relevance()` returns `(hits, needs_wider)` — if all docs irrelevant, triggers wider search (top_k*2). Min 2 hits guaranteed.
- **Min score threshold**: 0.35
- **GraphRAG**: `graph.py` uses NetworkX DiGraph for multi-hop BFS over law-concept relationships. Graph built by `build_graph.py`, cached globally for Vercel warm starts. Graceful fallback if `networkx` unavailable.

### Wage Calculator (`wage_calculator/`)

Facade pattern with `WageCalculator` as the single entry point.

```
wage_calculator/
├── models.py                # WageInput dataclass (~50 fields), enums
├── constants.py             # Minimum wages by year, insurance rates, tax brackets
├── result.py                # WageResult dataclass, format_result()
├── legal_hints.py           # Legal review point generation
├── facade/
│   ├── __init__.py          # WageCalculator.calculate()
│   ├── registry.py          # CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS dispatcher
│   ├── helpers.py           # _pop_* result population, _merge()
│   └── conversion.py        # 파싱 유틸 (_guess_start_date 등) — 변환은 pipeline 인라인이 정식
└── calculators/
    ├── shared.py            # DateRange, AllowanceClassifier, MultiplierContext
    ├── ordinary_wage.py     # Base ordinary wage (foundation for all other calcs)
    └── [24 more calculators]
```

**Key design decisions:**
- `WageCalculator.calculate(inp, targets)` — pass `WageInput` + list of target calculator names. If `targets=None`, auto-detected from input fields.
- 웹 파이프라인의 유일한 변환 경로는 `pipeline.py::_run_calculator()` — 한국어 라벨은 `resolve_calc_type_strict()`(exact match → slash/comma split → keyword fallback, 미매칭 시 None)로 targets 변환. 구 `from_analysis()`/`_provided_info_to_input()`은 호출처가 없어 제거됨(calc-db-integration-review D1).
- `calc_ordinary_wage()` runs first as the foundation — all other calculators depend on its result.
- `_STANDARD_CALCS` in `registry.py` is the dispatcher: list of `(key, func, section_name, populate_fn, precondition)` tuples.
- `AllowanceCondition` enum reflects Supreme Court ruling 2023다302838: NONE/ATTENDANCE/EMPLOYMENT are included in ordinary wage; PERFORMANCE is excluded.
- `FixedAllowance` dataclass in `models.py` has `from_dict()` factory and `monthly_amount` property.
- `calc_wage_arrears()` is a standalone function (no WageInput dependency).
- `constants.py` holds yearly minimum wages, insurance rates, tax brackets — update these when laws change.
- `shared.py` extracts common patterns: `DateRange` (tenure calc, 8 modules), `AllowanceClassifier` (minimum wage inclusion, 3 modules), `MultiplierContext` (sub-5-employee rates, 5 modules).

### Calculator Targets (25 types)
`overtime`, `minimum_wage`, `weekly_holiday`, `annual_leave`, `dismissal`, `comprehensive`, `prorated`, `public_holiday`, `insurance`, `employer_insurance`, `severance`, `unemployment`, `compensatory_leave`, `wage_arrears`, `parental_leave`, `maternity_leave`, `flexible_work`, `weekly_hours_check`, `legal_hints`, `business_size`, `eitc`, `retirement_tax`, `retirement_pension`, `average_wage`, `shutdown_allowance`, `industrial_accident`

### Harassment Assessor (`harassment_assessor/`)

Standalone module for workplace harassment (직장 내 괴롭힘) assessment.

- `assess_harassment(HarassmentInput)` → `AssessmentResult` with element-by-element scoring
- Relationship type analysis (상급자, 사용자, 정규직_비정규직, etc.)
- Behavior classification (폭행_협박, 폭언_모욕, 따돌림_무시, etc.)
- Frequency/duration/evidence weighing with configurable thresholds in `constants.py`
- Integrated into pipeline via `HARASSMENT_TOOL` in `app/templates/prompts.py`

### Session Management (`app/models/session.py`)

- In-memory `_sessions` dict (Vercel serverless = per-invocation, so relies on Supabase for persistence)
- `Session` stores: history (recent 6 turns), summary (condensed older turns, 2KB cap), calc_cache, pending analysis
- `condense_if_needed()` compresses history beyond 6 turns into summary text
- Supabase snapshot: `to_snapshot()` / `from_snapshot()` for cross-request persistence

### Q&A Analysis Pipeline

`crawl_qna.py` → `analyze_qna.py` → `summarize_analysis.py`

- `analyze_qna.py`: Batch-analyzes markdown Q&A files using Claude Haiku (5 per batch), outputs `analysis_qna.jsonl`. Each entry classified with question_type, sub_type, provided_info, missing_info, calculation_type.
- `summarize_analysis.py`: Aggregates JSONL into frequency stats and calculator design docs.

## Deployment

- **Vercel**: `api/index.py` (FastAPI, `@vercel/python`) + `public/**` (static). Auto-deploy on push to main. Config in `vercel.json`.
- **GitHub Pages 미러는 폐기됨**(2026-08-01). `.github/workflows/pages.yml` 삭제. 서브패스 서빙이라 `/manifest.webmanifest`·`/sw.js`·`/pwa.js`·`/icons/*` 등 루트 절대경로 자산이 전부 404였다. **배포처는 Vercel 단일.** `public/*.html`의 `location.hostname.includes('github.io')` 분기는 무해한 폴백으로 남아 있다(비-Vercel 호스트에서 열 때 API를 프로덕션으로 향하게 함).
- All `app/core/*.py` files imported by `pipeline.py` **must** be committed to git — untracked files cause Vercel import errors (500).

## Key Conventions

- All monetary amounts in Korean Won (원), no decimal for display (use `{:,.0f}`)
- 계산기 입력 params는 영문 키(`wage_type`, `wage_amount` 등, `pipeline.py::_run_calculator()` 규약) — 한국어는 계산 유형 라벨(`CALC_TYPE_MAP` 키, 예: "연장수당")에만 사용
- Legal references follow format: "근로기준법 제N조" or "대법원 YYYY다NNNN"
- Test cases in `wage_calculator_cli.py` numbered #1–#32; batch tests in `calculator_batch_test.py` with 102 cases
- LLM provider fallback **기본 순서**: Claude → OpenAI → Gemini (`_stream_answer`). `ANSWER_PROVIDER`(claude|openai|gemini)를 설정하면 **그 제공자가 1순위로 재정렬**되고 나머지는 기본 순서를 유지한다 — 장애 시 무배포 롤백 수단이다. Gemini는 `GEMINI_API_KEY`가 있을 때만 목록에 들어간다. **폴백 규약**(llm-fallback-hardening):
  - **빈 응답은 실패다** — 예외 없이 실질 0자로 끝난 제공자는 성공이 아니라 다음 제공자로 전환한다. reasoning 모델이 추론으로 토큰 한도를 소진해 본문 0자를 반환하는 사례가 실측됐다.
  - **절단은 고지한다** — 첫 청크 이후 실패 시 부분 응답을 유지하되(재시도 없음) 사용자에게 절단 고지를 붙이고, `metadata.truncated`로 저장해 공개 게시판에서 제외한다(`api/index.py::_PUBLIC_EXCLUDE_KEYS`). 고지 없이 두면 잘린 답변에 면책 고지가 붙어 완결된 답변으로 오인된다.
  - **전환 구간은 하트비트를 낸다** — `_stream_answer`가 `(provider, "")` 빈 텍스트를 흘리면 호출부가 `ping`으로 변환한다. 무이벤트 구간이 프론트 idle(60초, `public/index.html`)을 넘으면 폴백이 도달하기 전에 브라우저가 abort한다.
  - **재시도보다 전환** — 답변 경로는 `max_retries=0`. 동일 벤더 재시도는 같은 장애를 다시 만난다.
  - **모델명은 별칭으로** — 고정 버전은 모델 폐기 시 조용히 404가 된다(실제로 `gemini-2.5-pro`가 그렇게 죽어 있었고, 폴백 계측이 없어 아무도 몰랐다).
- 의도분석(`analyze_intent`)은 Claude 실패 시 OpenAI function calling으로 폴백한다. 후처리는 `_build_analysis_result` 단일 출처를 두 벤더가 공유해야 추출 결과가 갈라지지 않는다. 어댑터는 `app/core/llm_fallback.py` — `analyzer.py`가 `pipeline.py`를 import하면 순환이 되므로 하위 모듈에 둔 것이다.
- 폴백 결과는 `qa_conversations.metadata.llm`(provider·attempts·fallback·empty·truncated·citation_fixed)에 기록한다. **계측이 없으면 폴백 경로가 통째로 죽어도 아무도 모른다.**
- All `app/core/*.py` modules use `from __future__ import annotations` for forward reference support.
- Legal API (`legal_api.py`) has circuit breaker pattern: 3 consecutive failures → 30s cooldown. L1 in-memory → L2 Supabase → L3 API call.
- Citation validator (`citation_validator.py`) regex patterns: `대법원 YYYY[가-힣]NNNN` for precedents, `[부서명]과-NNNN` for administrative interpretations.
- Graceful degradation everywhere: Pinecone 초기화/쿼리 실패 → `pinecone_index=None`으로 RAG 비활성(계산기·법령 API·LLM 답변은 정상, `config.py`에서 try/except), BM25 미설치 → Dense-only, Self-RAG 실패 → rerank 유지, `classify_complexity` 실패 → MODERATE 폴백. 새 기능 추가 시 반드시 폴백 경로 구현.
- `public/calculator_flow/*.html` 내 `sendPrompt()` 호출은 반드시 `window.parent?.sendPrompt?.()` 로 — iframe 내에서 실행되므로 부모 컨텍스트 필요.
- `api/index.py`의 파일 서빙 엔드포인트는 `os.path.commonpath` + `.html` allowlist로 path traversal 방지 필수.
- `public/index.html`의 채팅 UI는 `expandChat()`으로 제어 — 초기에 입력창만 표시, 첫 메시지 전송 시 `.chat-card.active` 클래스 추가로 채팅 영역 확장.
- 공개 게시판/대화 응답은 반드시 `_anonymize()`(이름·회사·전화·이메일 마스킹) 통과 후 반환. 신규 공개 엔드포인트 추가 시 동일 적용.
- 신규 채팅 엔드포인트 추가 시 `_guard_chat_request()`를 세션 생성·첨부 파싱보다 먼저 호출하고, `process_question(guard_ctx=...)`으로 컨텍스트를 전달할 것.
- `qa_conversations` 공개 조회(게시판)는 `_exclude_guard_flagged()` + `_drop_flagged()`를 거쳐 `metadata.guard_flag` 대화를 제외하고, select에 `metadata`를 포함해야 한다. **`board_posts`에는 적용 금지** — metadata 컬럼이 없어 PostgREST 400이 `try/except`에 삼켜져 사용자 게시글이 통째로 사라진다.
- `abuse_events`/`block_list`/`chat_quota`는 RLS 활성 + 정책 무부여(anon 직접 접근 차단). 접근은 `SECURITY DEFINER` RPC로만 — 정책을 부여하면 클라이언트가 차단을 자가 해제할 수 있다.
- 게시판 글쓰기 보안 체인 순서 고정: CAPTCHA(HMAC, `JWT_SECRET` 서명) → IP rate-limit → 입력 검증/금칙어 → bcrypt(rounds=12) 해싱 → INSERT. 삭제는 bcrypt `checkpw` 후 soft delete.
- 이메일 발송(`/api/send-email`)은 전송 전 `_sanitize_html()`로 `<script>`/`on*=` 제거 필수, 분당 10건 인메모리 rate-limit.
- 새 코퍼스 소스 추가 시 `crawl_*` → `generate_metadata_*` → `pinecone_upload_*` 3종 스크립트를 함께 추가/동기화.
- `public/privacy.html` 제5항(보유기간) 문구는 `supabase_retention_purge.sql`의 `purge_expired_data()` 기본값과, 제7항(첨부 접근통제) 문구는 `app/core/storage.py::upload_attachment`(public_url 미저장) + `api/index.py::admin_conversation_detail`(1시간 signed URL)과 반드시 함께 갱신할 것. 이 파일들이 바뀌면 방침이 지켜지지 않는 약속이 된다.
- `public/terms.html` 제5조(이용 한도) 수치는 `app/core/abuse_guard.py:25-32`(`MAX_MESSAGE_LENGTH`·`CHAT_RATE_LIMIT`·`CHAT_RATE_WINDOW`·`DAILY_CHAT_QUOTA`·`ABUSE_BLOCK_MINUTES`)와 반드시 함께 갱신할 것. 공지 채널(제3·7조)의 실체는 `public/notice.json`(원본) + `public/index.html`의 `#notice-banner`/`initNotice()`(렌더러) — 공지 내용을 바꿀 때 `notices[].id`도 함께 바꿔야 이미 닫은 사용자에게 다시 노출된다.
- 공개 페이지(`public/*.html`)의 HTML 주석에는 내부 파일 경로·함수명을 적지 말 것 — 소스 보기로 그대로 노출된다. 그런 유지보수 의존관계는 이 문서(CLAUDE.md)에 기록한다. `public/finalize.js`·`public/pwa.js` 등 공개 JS 주석도 같다.
- **디자인 시스템은 `public/tokens.css`가 단일 출처**(Swiss Modernism 2.0). 색·간격·서체·모션 값을 페이지 인라인 `<style>`에 리터럴로 두지 말 것 — 공개 8페이지가 모두 `<link rel="stylesheet" href="/tokens.css">`로 참조하며, **인라인 `<style>`보다 반드시 앞에** 와야 페이지 고유 레이아웃이 토큰을 덮는다. 규범·근거는 `docs/02-design/features/swiss-modernism-design-system.design.md`가 관리하며, 값을 바꿀 때 그 문서를 먼저 갱신한다. 강제 규칙 중 대비 계산에서 나온 것들:
  - **라이트 모드에서 액센트(코퍼 `#C08050`)를 텍스트 색으로 쓰지 말 것** — 흰 배경 3.26:1, 서피스 2.99:1로 WCAG AA 미달이다. 링크는 색이 아니라 밑줄로 구분한다. 다크 모드 액센트(`#D9A273`)는 8.42:1이라 텍스트 사용이 가능하다.
  - **액센트 면 위의 글자는 `--accent-on`(`#111111`)이다. 흰색 금지** — 흰 글씨 3.26:1 미달, 오프블랙 5.80:1 통과.
  - **액센트 hover는 밝아진다**(`#C58A5E`). 규격의 "8% 어둡게"를 따르면 오프블랙 라벨과의 대비가 4.31:1로 떨어져 미달한다.
  - 애니메이션은 `transform`·`opacity`만. `background-position`·`width` 전이 금지.
- 계산기 흐름도 25종(`public/calculator_flow/*.html`)은 **아직 미전환**이다. 6색 의미 체계(`c-blue`/`c-teal`/`c-amber`/`c-coral`/`c-purple`/`c-gray`)를 데이터시각화 예외로 유지하기로 확정했고 매핑표는 설계 문서 §8.1에 있다. 그 결과 `calculators.html`(무채색)과 iframe 안 흐름도(기존 색) 사이에 시각적 이음매가 있다 — 후속 사이클에서 해소.
- `public/index.html`의 콜아웃 판정(`CALLOUT_MAP`)·핵심답변 판정·면책 고지 판정과 `public/finalize.js`의 `isTerminator`는 **정규식에 이모지(📘⚠️🚨💡⚖️📋)를 포함한다.** LLM 출력의 이모지 접두사를 벗겨 내는 용도이므로 "UI 이모지 제거" 작업 시에도 **지우면 안 된다** — 지우면 콜아웃이 평문이 되고 면책 고지가 접힌 채 숨는다. 표시용 아이콘만 인라인 SVG(`.icon`)로 교체한다.
- `public/sw.js`의 `ASSET_PATTERN`은 css·js를 포함하므로 **배포마다 `VERSION`을 올릴 것.** 안 올리면 낡은 스타일·스크립트가 cache-first로 남아 새 디자인이 적용되지 않는다(실패가 조용하다). `SHELL_URLS`에 `/tokens.css`가 있어야 오프라인 화면이 무스타일로 뜨지 않는다.
- **프론트 `fetch`는 반드시 `resp.ok`를 검사할 것.** `fetch`는 네트워크 실패에만 reject하고 4xx·5xx는 정상 이행하므로, `.then(r => r.json())`으로 바로 넘기면 **오류 본문이 정상 데이터로 흘러가 화면에 `undefined`가 찍힌다**(2026-08-07 실장애: `CAPTCHA_SECRET` 미설정 → `/api/captcha` 503 → "보안문자: undefined" → 이메일 발송·게시판 등록 불가). 200이어도 필수 필드 존재를 함께 확인한다. 사용자 안내에는 서버 `detail`(예: "서버 설정 오류")을 노출하지 말고 고정 문구를 쓴다. 회귀는 `test_public_fetch.js`가 공개 페이지 전 `fetch`를 훑어 고정한다.
- CAPTCHA로 게이팅되는 제출 버튼(`index.html` 이메일 모달, `board.html` 글쓰기)은 **토큰 확보 전까지 비활성**을 유지해야 한다. `board.html`은 버튼 상태를 만지는 지점이 셋(`loadCaptcha` 성공, `submitPost`의 429 타이머, `finally`)이라 **단일 불변식으로 통일**돼 있다 — "토큰이 있고 rate limit이 풀렸을 때만 열린다"(`!captchaToken || Date.now() < rateLimitedUntil`). 한 지점만 무조건 `false`로 바꾸면 나머지 둘의 게이팅이 무력화된다. 403 재로딩은 `await loadCaptcha()`로 순서를 확정할 것 — `await` 없이 호출하면 `finally`가 먼저 실행돼 잠금을 덮는다.
- **답변 조망 레이어**(`public/finalize.js`, answer-at-a-glance): 완성된 답변 DOM에만 적용하는 순수 후처리(목차·`<details>` 접기·핵심 복귀 버튼). `index.html`(`readSSE` 말미, 스트리밍 완료 후 1회)과 `board.html`(`renderDetail` 렌더 직후)이 공유하며, `pwa.js`와 같은 정적 파일 분리 방식이다. 주의점:
  - **h2 태그만 근거로 동작해야 한다** — `board.html`은 `md()`가 아니라 `marked.parse()`만 써서 콜아웃·`.summary-badge` 클래스가 없다. `md()` 전용 클래스에 의존하면 게시판에서 깨진다.
  - **접기 종료 마커를 지우지 말 것**(`isTerminator`) — 프롬프트는 주의사항을 블록쿼트로, 면책 고지를 평문으로 지시하므로(`app/templates/prompts.py`) heading 단위 방어만으로는 마지막 접기 섹션이 이들을 통째로 흡수해 **면책 고지가 접힌 채 숨는다**.
  - **목차 id는 답변 시퀀스 접두사가 필수** — 채팅은 후속 답변이 누적되므로 인덱스만 쓰면 `getElementById`가 항상 첫 답변을 잡는다.
  - `board.html`에서는 `<script src="/finalize.js">`가 본문 인라인 스크립트보다 **앞**에 있어야 `?id=` 딥링크의 첫 상세 렌더에도 적용된다.
  - sticky 목차는 **모바일에서만 유효**하다(`#chat`이 데스크톱에서 `height:auto`라 스크롤포트가 없음). 플로팅 복귀 버튼이 전 환경 경로이므로 둘 중 하나만 남기지 말 것.
  - PDF·이메일 내보내기는 `expandForExport`로 접힌 섹션을 강제로 편 사본을 쓴다 — 접힌 채 나가면 내용 누락으로 보인다. 복사·마크다운 저장은 원문(`dataset.md`)을 쓰므로 무관하다.
