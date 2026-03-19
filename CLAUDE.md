# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**laborconsult** — Korean labor law (노동법) Q&A crawler, RAG chatbot, and wage calculator system. Data sourced from nodong.kr. Four main subsystems:

1. **Crawlers** — Scrape Q&A posts from nodong.kr into markdown files
2. **RAG Pipeline** — Chunk, embed (OpenAI), store in Pinecone, multi-query search with Cohere reranking
3. **Wage Calculator** — 25 Korean labor law calculators with unified facade
4. **Web API** — FastAPI + Vercel serverless chatbot with intent analysis, legal API integration, file upload, and harassment assessment

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Crawling pipeline
python3 crawl_bestqna.py          # BEST Q&A (274 posts → output/)
python3 crawl_qna.py              # General Q&A (10K posts → output_qna/), resumable
python3 generate_metadata.py      # Generate metadata.json from output/

# Pinecone upload
python3 pinecone_upload.py        # Chunk + embed + upsert to Pinecone
python3 pinecone_upload.py --reset  # Reset index and re-upload

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
python3 calculator_batch_test.py         # Run all 102 batch test cases

# Local API server
uvicorn api.index:app --reload --port 5555  # FastAPI dev server (port 5555)

# BM25 corpus build (Hybrid Search용, Pinecone API 필요)
python3 build_bm25_corpus.py      # Pinecone → data/bm25_corpus.json

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
- `GEMINI_API_KEY` — tertiary LLM fallback (Gemini 2.5 Pro)
- `SUPABASE_URL` / `SUPABASE_KEY` — session persistence + conversation storage
- `LAW_API_KEY` — 법제처 법령 API
- `ODCLOUD_API_KEY` — 공공데이터포털 API (중앙노동위원회 판정사례)
- `COHERE_API_KEY` — search result reranking
- `ADMIN_PASSWORD` — admin dashboard login
- `ADMIN_JWT_SECRET` — JWT signing (defaults to ADMIN_PASSWORD)
- `PINECONE_INDEX_NAME` — defaults to `semiconductor-lithography` (legacy name)

**Model config** in `app/config.py`: Claude Sonnet 4.6 (primary), OpenAI o3 (fallback), Gemini 2.5 Pro (tertiary).

## Architecture

### Web API (`api/` + `app/`)

FastAPI app deployed to Vercel serverless. `api/index.py` is the entry point.

**Endpoints:**
- `GET /api/health` — health check
- `GET /api/chat/stream?message=...` — SSE streaming (text only)
- `POST /api/chat/stream` — SSE streaming (with file attachments as base64)
- `POST /api/chat` — sync full response
- `POST /api/admin/login` → JWT token (24h expiry)
- `GET /api/admin/stats`, `GET /api/admin/conversations` — analytics (requires Bearer token)
- `GET /api/admin/conversations/{conv_id}` — 단일 대화 상세 (requires Bearer token)
- `GET /api/board/recent?page=1&per_page=10` — 최근 공개 Q&A (비식별화, `_anonymize()` 적용)

**Static pages:**
- `public/index.html` — 메인페이지: 히어로(제목) → 채팅 입력창(첫 메시지 시 확장) → FAQ 6카테고리 → 질문게시판 → 푸터. 디자인: Noto Serif KR + Pretendard, 네이비(#1B2A4A) + 코퍼(#C08050), max-width 800px.
- `public/calculators.html` — 25개 계산기 흐름도 메뉴 (사이드바 + iframe 뷰어)
- `public/calculator_flow/` — 25개 standalone HTML 계산기 시각화 (SVG 플로우차트)
- `public/admin.html` — 관리자 대시보드 (라우트: `/admin`, `/admin.html`은 404)

**SSE event types** (consumed by `public/index.html::readSSE()`):
- `session` — session_id
- `status` — progress text (e.g., "질문 분석 중...")
- `chunk` — streaming answer text
- `replace` — full answer replacement (after citation correction)
- `follow_up` — follow-up question (rendered as separate message)
- `contacts` — agency contact cards
- `error` — error message
- `meta` — calc_result, sources

### Pipeline Flow (`app/core/pipeline.py`)

`process_question()` is the main orchestrator. It yields SSE events:

1. **Intent analysis** → `analyzer.py` (Claude tool_use extracts params, `NUMERIC_RANGES` guardrails)
2. **Branching**:
   - **Wage calculation**: `WageCalculator.from_analysis()` → calculators → formatted result
   - **Harassment assessment**: `harassment_assessor.assess_harassment()` → element scoring
   - **Legal consultation**: `legal_consultation.py` (topic→law mapping) + RAG + legal API
3. **RAG search** → Adaptive complexity classification (`classify_complexity()` → SIMPLE/MODERATE/COMPLEX) → `query_decomposer.py` (LLM multi-query) → `rag.py::search_hybrid()` (BM25+Dense RRF fusion → Pinecone 2-group parallel) → `rerank_results()` (Cohere) → Self-RAG relevance filter (COMPLEX only, `self_rag.py`) + `graph.py` (GraphRAG multi-hop)
4. **Legal API** → `legal_api.py` (법제처, circuit breaker + L1/L2/L3 cache) + `nlrc_cases.py` (공공데이터포털 판정사례 360건 캐싱 + 법제처 판례 보강)
5. **LLM streaming** → Claude → OpenAI → Gemini fallback chain (`_stream_answer()`)
6. **Citation validation** → `citation_validator.py` detects hallucinated case numbers, sends `replace` event
7. **Persistence** → Supabase conversation + session snapshot

### Crawlers

All crawlers use `lxml` parser (not `html.parser` — it has `<hr>` void element bugs) and `markdownify` for HTML-to-markdown conversion. Each produces markdown files named `{post_id}_{title}.md`.

- `crawl_bestqna.py` → `output/` (BEST Q&A, ~274 posts)
- `crawl_qna.py` → `output_qna/` (general Q&A, ~10K posts, resumable via saved file detection)
- `crawl_2025.py`, `crawl_imgum.py` — variant crawlers for different board sections

### RAG Pipeline

- **Chunking**: Section-based (h2/h3) split, max 700 chars, 80 char overlap. Critical: `split_by_size` must have `end >= len(text): break` guard to prevent tiny trailing chunks.
- **Embedding**: OpenAI text-embedding-3-small (1536 dim)
- **Vector DB**: Pinecone Serverless (AWS us-east-1, cosine metric), 3 namespaces
- **Hybrid Search**: `bm25_search.py` (BM25 keyword) + Dense (Pinecone) → Reciprocal Rank Fusion (`search_hybrid()` in `rag.py`). BM25 uses `rank_bm25` with Mecab tokenizer (fallback: regex). Corpus built by `build_bm25_corpus.py` → `data/bm25_corpus.json`. Graceful fallback to Dense-only if BM25 unavailable.
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
│   ├── __init__.py          # WageCalculator.calculate(), from_analysis()
│   ├── registry.py          # CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS dispatcher
│   ├── helpers.py           # _pop_* result population, _merge()
│   └── conversion.py        # _provided_info_to_input() — Korean labels → WageInput
└── calculators/
    ├── shared.py            # DateRange, AllowanceClassifier, MultiplierContext
    ├── ordinary_wage.py     # Base ordinary wage (foundation for all other calcs)
    └── [24 more calculators]
```

**Key design decisions:**
- `WageCalculator.calculate(inp, targets)` — pass `WageInput` + list of target calculator names. If `targets=None`, auto-detected from input fields.
- `WageCalculator.from_analysis(calculation_type, provided_info)` — converts Korean analysis labels (e.g., "연장수당") to calculator targets via `CALC_TYPE_MAP` in `registry.py`. The `resolve_calc_type()` function handles exact match → slash/comma split → keyword fallback.
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
- **GitHub Pages**: `public/**` deployed via `.github/workflows/pages.yml` when changed.
- All `app/core/*.py` files imported by `pipeline.py` **must** be committed to git — untracked files cause Vercel import errors (500).

## Key Conventions

- All monetary amounts in Korean Won (원), no decimal for display (use `{:,.0f}`)
- Korean variable names used in `facade/conversion.py::_provided_info_to_input()` (e.g., `임금형태`, `임금액`) to match analysis output schema
- Legal references follow format: "근로기준법 제N조" or "대법원 YYYY다NNNN"
- Test cases in `wage_calculator_cli.py` numbered #1–#32; batch tests in `calculator_batch_test.py` with 102 cases
- LLM provider fallback: Claude (primary) → OpenAI o3 → Gemini. If streaming starts then fails mid-stream, partial response is kept (no retry).
- All `app/core/*.py` modules use `from __future__ import annotations` for forward reference support.
- Legal API (`legal_api.py`) has circuit breaker pattern: 3 consecutive failures → 30s cooldown. L1 in-memory → L2 Supabase → L3 API call.
- Citation validator (`citation_validator.py`) regex patterns: `대법원 YYYY[가-힣]NNNN` for precedents, `[부서명]과-NNNN` for administrative interpretations.
- Graceful degradation everywhere: BM25 미설치 → Dense-only, Self-RAG 실패 → rerank 유지, `classify_complexity` 실패 → MODERATE 폴백. 새 기능 추가 시 반드시 폴백 경로 구현.
- `public/calculator_flow/*.html` 내 `sendPrompt()` 호출은 반드시 `window.parent?.sendPrompt?.()` 로 — iframe 내에서 실행되므로 부모 컨텍스트 필요.
- `api/index.py`의 파일 서빙 엔드포인트는 `os.path.commonpath` + `.html` allowlist로 path traversal 방지 필수.
- `public/index.html`의 채팅 UI는 `expandChat()`으로 제어 — 초기에 입력창만 표시, 첫 메시지 전송 시 `.chat-card.active` 클래스 추가로 채팅 영역 확장.
