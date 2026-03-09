# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean labor law (노동법) Q&A crawler, RAG chatbot, and wage calculator system for nodong.kr. Three main subsystems:

1. **Crawlers** — Scrape Q&A posts from nodong.kr into markdown files
2. **RAG Pipeline** — Chunk, embed (OpenAI), store in Pinecone, query via Claude chatbot
3. **Wage Calculator** — 19 Korean labor law calculators with unified facade

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
```

## Environment Variables

Defined in `.env` (see `.env.example`):
- `OPENAI_API_KEY` — embeddings (text-embedding-3-small)
- `PINECONE_API_KEY` — vector DB
- `ANTHROPIC_API_KEY` — chatbot responses + Q&A analysis

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

### Wage Calculator (`wage_calculator/`)

Facade pattern with `WageCalculator` as the single entry point.

```
wage_calculator/
├── __init__.py          # Public API exports
├── models.py            # WageInput dataclass, enums (WageType, BusinessSize, AllowanceCondition, etc.)
├── facade.py            # WageCalculator class — orchestrates all calculators
├── ordinary_wage.py     # Base ordinary wage calculation (foundation for all other calcs)
├── constants.py         # Minimum wages by year, insurance rates, tax brackets, legal rates
├── result.py            # WageResult dataclass, format_result(), format_result_json()
├── legal_hints.py       # Legal review point generation system
├── shift_work.py        # Shift work hour calculation utilities
└── calculators/         # 17 individual calculator modules
    ├── overtime.py      # Overtime/night/holiday pay + weekly hours compliance check
    ├── minimum_wage.py  # Minimum wage verification (with inclusion scope)
    ├── severance.py     # Severance pay
    ├── insurance.py     # 4 social insurances + income tax (employee & employer)
    ├── annual_leave.py, weekly_holiday.py, dismissal.py, comprehensive.py
    ├── prorated.py, public_holiday.py, unemployment.py
    ├── compensatory_leave.py, wage_arrears.py
    ├── parental_leave.py, maternity_leave.py, flexible_work.py
    └── __init__.py
```

**Key design decisions:**
- `WageCalculator.calculate(inp, targets)` — pass `WageInput` + list of target calculator names (e.g., `["overtime", "minimum_wage"]`). If `targets=None`, auto-detected from input fields.
- `WageCalculator.from_analysis(calculation_type, provided_info)` — converts Korean analysis labels (e.g., "연장수당") to calculator targets via `CALC_TYPE_MAP`.
- `calc_ordinary_wage()` runs first as the foundation — all other calculators depend on its result.
- `AllowanceCondition` enum reflects Supreme Court ruling 2023다302838: NONE/ATTENDANCE/EMPLOYMENT conditions are included in ordinary wage; PERFORMANCE is excluded.
- `calc_wage_arrears()` is a standalone function (no WageInput dependency).
- `constants.py` holds yearly minimum wages, insurance rates, tax brackets — update these when laws change.

### Q&A Analysis Pipeline

`crawl_qna.py` → `analyze_qna.py` → `summarize_analysis.py`

- `analyze_qna.py`: Batch-analyzes markdown Q&A files using Claude Haiku (5 per batch), outputs `analysis_qna.jsonl`. Each entry classified with question_type, sub_type, provided_info, missing_info, calculation_type.
- `summarize_analysis.py`: Aggregates JSONL into frequency stats and calculator design docs.

## Key Conventions

- All monetary amounts in Korean Won (원), no decimal for display (use `{:,.0f}`)
- Korean variable names used in `facade.py::_provided_info_to_input()` (e.g., `임금형태`, `임금액`) to match analysis output schema
- Legal references follow format: "근로기준법 제N조" or "대법원 YYYY다NNNN"
- Test cases in `wage_calculator_cli.py` numbered #1–#32 covering all calculator types
