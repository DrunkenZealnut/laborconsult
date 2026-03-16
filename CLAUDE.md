# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean labor law (노동법) Q&A crawler, RAG chatbot, and wage calculator system for nodong.kr. Four main subsystems:

1. **Crawlers** — Scrape Q&A posts from nodong.kr into markdown files
2. **RAG Pipeline** — Chunk, embed (OpenAI), store in Pinecone, query via Claude chatbot
3. **Wage Calculator** — 25 Korean labor law calculators with unified facade
4. **Web API** — FastAPI + Vercel serverless chatbot with intent analysis, legal API integration, and file upload

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
uvicorn api.index:app --reload    # FastAPI dev server
```

## Environment Variables

Defined in `.env` (see `.env.example`):
- `OPENAI_API_KEY` — embeddings (text-embedding-3-small)
- `PINECONE_API_KEY` — vector DB
- `ANTHROPIC_API_KEY` — chatbot responses + Q&A analysis
- `SUPABASE_URL` / `SUPABASE_KEY` — session persistence (optional)

## Architecture

### Crawlers

All crawlers use `lxml` parser (not `html.parser` — it has `<hr>` void element bugs) and `markdownify` for HTML-to-markdown conversion. Each produces markdown files named `{post_id}_{title}.md`.

- `crawl_bestqna.py` → `output/` (BEST Q&A, ~274 posts)
- `crawl_qna.py` → `output_qna/` (general Q&A, ~10K posts, resumable via saved file detection)
- `crawl_2025.py`, `crawl_imgum.py` — variant crawlers for different board sections

### RAG Pipeline

`pinecone_upload.py` → `chatbot.py`

- **Chunking**: Section-based (h2/h3) split, max 700 chars, 80 char overlap. Critical: `split_by_size` must have `end >= len(text): break` guard to prevent tiny trailing chunks.
- **Embedding**: OpenAI text-embedding-3-small (1536 dim)
- **Vector DB**: Pinecone Serverless (AWS us-east-1, cosine metric)
- **Chatbot**: OpenAI embed query → Pinecone search → Claude streaming response

### Web API (`api/` + `app/`)

FastAPI app deployed to Vercel serverless. `api/index.py` is the entry point with `/api/chat`, `/api/chat/stream` (SSE), and `/api/admin/*` endpoints.

**Request flow**: `api/index.py` → `app/core/pipeline.py` (orchestrator) → branches into:
- **Wage calculation path**: `analyzer.py` (Claude tool_use intent extraction) → `calculator.py` → `wage_calculator/` → `composer.py`
- **Legal consultation path**: `legal_consultation.py` → `legal_api.py` (법제처 API) + `rag.py` (Pinecone) → `composer.py`

Key modules in `app/core/`:
- `analyzer.py` — Intent classification via Claude tool_use; extracts wage info with NUMERIC_RANGES guardrails
- `rag.py` — Vector search via Pinecone (OpenAI embeddings)
- `legal_api.py` — 법제처 법령 API with circuit breaker, HTTPS, retry
- `citation_validator.py` — Detects hallucinated case numbers in LLM responses
- `legal_consultation.py` — Non-calculation legal Q&A (해고, 휴직, etc.) with topic→law mapping
- `storage.py` — Supabase session persistence
- `file_parser.py` — PDF/Excel attachment parsing

Frontend: `public/index.html` (chat UI) and `public/admin.html` (admin dashboard).

### Wage Calculator (`wage_calculator/`)

Facade pattern with `WageCalculator` as the single entry point.

```
wage_calculator/
├── __init__.py              # Public API exports
├── models.py                # WageInput dataclass, enums (WageType, BusinessSize, AllowanceCondition, etc.)
├── base.py                  # BaseCalculatorResult base class
├── result.py                # WageResult dataclass, format_result(), format_result_json()
├── constants.py             # Minimum wages by year, insurance rates, tax brackets, legal rates
├── utils.py                 # Utilities (parse_date, RoundingPolicy enum)
├── legal_hints.py           # Legal review point generation system
├── facade/                  # Unified facade (split from single facade.py)
│   ├── __init__.py          # WageCalculator class — calculate(), from_analysis()
│   ├── registry.py          # CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS dispatcher
│   ├── helpers.py           # _pop_* result population functions, _merge()
│   └── conversion.py        # _provided_info_to_input() — Korean labels → WageInput
└── calculators/             # 25 individual calculator modules
    ├── shared.py            # DateRange, AllowanceClassifier, MultiplierContext (common utilities)
    ├── ordinary_wage.py     # Base ordinary wage (foundation for all other calcs)
    ├── overtime.py          # Overtime/night/holiday pay + weekly hours compliance
    ├── minimum_wage.py      # Minimum wage verification (with inclusion scope)
    ├── severance.py, insurance.py, retirement_tax.py, retirement_pension.py
    ├── average_wage.py, eitc.py, industrial_accident.py, business_size.py
    ├── shutdown_allowance.py, unemployment.py
    ├── annual_leave.py, weekly_holiday.py, dismissal.py, comprehensive.py
    ├── prorated.py, public_holiday.py, compensatory_leave.py, wage_arrears.py
    ├── parental_leave.py, maternity_leave.py, flexible_work.py
    └── __init__.py
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

### Q&A Analysis Pipeline

`crawl_qna.py` → `analyze_qna.py` → `summarize_analysis.py`

- `analyze_qna.py`: Batch-analyzes markdown Q&A files using Claude Haiku (5 per batch), outputs `analysis_qna.jsonl`. Each entry classified with question_type, sub_type, provided_info, missing_info, calculation_type.
- `summarize_analysis.py`: Aggregates JSONL into frequency stats and calculator design docs.

## Key Conventions

- All monetary amounts in Korean Won (원), no decimal for display (use `{:,.0f}`)
- Korean variable names used in `facade/conversion.py::_provided_info_to_input()` (e.g., `임금형태`, `임금액`) to match analysis output schema
- Legal references follow format: "근로기준법 제N조" or "대법원 YYYY다NNNN"
- Test cases in `wage_calculator_cli.py` numbered #1–#32; batch tests in `calculator_batch_test.py` with 102 cases
