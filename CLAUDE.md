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

# 법제처 API 판례 보강 (사건번호 목록 → 원문 수집 → 쟁점 태깅 → 업로드)
python3 fetch_court_precedents.py              # output_노동법교재/누락_판례목록.csv → output_판례_보강/
python3 fetch_court_precedents.py --limit 20   # 부분 수집(재개 지원, _progress.json)
python3 fetch_court_precedents.py --cases <csv>  # 명시 대상 재수집(L2 중복검사 생략 — 겹침분 통일용)
python3 fetch_court_precedents.py --input <csv>  # 입력 CSV 교체(L2 유지 — 신규 수집용, --cases와 의미가 다름)
python3 enrich_court_precedents.py             # 교재 목차에서 '관련 쟁점' 태깅 (멱등, 저작권 경계는 스크립트 docstring)
python3 pinecone_upload_court_precedents.py --dry-run  # 청킹 검증
python3 pinecone_upload_court_precedents.py    # laborlaw-v2 업로드
python3 sync_overlap_precedents.py --emit-targets      # 교재∩기존코퍼스 겹침 대상 CSV 생성 (교재 원본 필요, 로컬 전용)
python3 sync_overlap_precedents.py --delete-ctx --dry-run  # 대체 성공분의 ctx 구벡터 삭제 (실행 전 반드시 dry-run)
python3 test_precedent_ingest.py               # 오프라인 회귀 테스트 (API 키 불요)

# 노동법 해설서 코퍼스 (본문 임베딩 + 인용 판례 추출)
python3 pinecone_upload_textbook.py --all --dry-run   # 청킹 검증 (서적 간 chunk_id 충돌 검사 포함)
python3 pinecone_upload_textbook.py --book juhae3     # 1권 업로드 (--all은 전권)
python3 extract_textbook_cases.py                     # 해설서 인용 판례 → 수집 대상 CSV

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
- `SUPABASE_URL` / `SUPABASE_KEY` — session persistence + conversation storage. **`NEXT_PUBLIC_*` 이름은 읽지 않는다**(Next.js 관례) — 대시보드 스니펫을 그대로 붙이면 Supabase 기능 전체가 조용히 꺼진다
- `SUPABASE_SCHEMA` — 접속 스키마, 미설정 시 `laborconsult` (`app/core/storage.py`)
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
- Additional corpus dirs (untracked, fed by their own crawl/metadata/upload scripts): `output_법원 노동판례/`, `output_노동부 행정해석/`, `output_훈령예규고시지침/`, `output_자료실/`, `nodong_counsel/`, `output_legal_cases/`, `output_판례_보강/`, `output_노동법교재/`(해설서 원본 + 수집 대상 CSV + `_uploaded_ids.json`)
- 코퍼스 소스는 세 계열로 나뉜다 — **게시판 크롤 계열**(`output/`·`output_2025/`·`output_imgum/`)은 `crawl_*` → `generate_metadata_*` → `pinecone_upload_*` 3종 세트를 유지하고, **문서·API 계열**(판례·행정해석·훈령예규·counsel·`output_판례_보강/`)은 metadata.json 단계 없이 수집 스크립트 + `pinecone_upload_*` 2종이 관례다(upload가 `.md`를 직접 파싱). **해설서 계열**(`output_노동법교재/`)은 marker로 변환한 단일 `.md`를 `pinecone_upload_textbook.py`의 `BOOKS` 레지스트리에 등록하는 것으로 끝난다 — 수집 스크립트조차 없다. 새 소스 추가 시 해당 계열의 세트를 함께 추가/동기화할 것
- **`output_판례_보강/`는 크롤러가 아니라 법제처 Open API로 채운다** (`fetch_court_precedents.py`). 사건번호 목록만 있으면 원문을 받아올 수 있는 유일한 경로다 — nodong.kr 크롤러들은 게시판 순회 방식이라 특정 사건을 지목할 수 없다. 설계·실측 근거는 `docs/02-design/features/precedent-corpus-expansion.design.md`. 주의점 셋(전부 **조용히** 실패한다):
  - **법제처 검색은 사건명 기준 fuzzy 매칭**이라 사건번호로 조회해도 무관한 판례를 반환한다(실측: `90누9421` → 6건 반환, 요청 사건 없음). 응답 XML의 `<사건번호>` 정확일치 게이트 없이 채택하면 엉뚱한 판례가 코퍼스에 섞인다.
  - **법제처 수집 성공률 예측은 72%를 기준선으로 쓸 것.** 표본으로 잡으면 낙관 편향이 크다 — 40건 표본 95% → 전량 83%(precedent-corpus-expansion), 교재 인용 판례는 하급심·구판례 비중이 높아 다시 72%(textbook-corpus-embedding, 166건 중 120건)였다. 미달분은 법제처 DB 미수록이라 재시도해도 회수되지 않고 `_미발견.csv`에 누적된다(현재 156건).
  - **판례 중복 판정은 파일당 대표 사건번호 1개로 해야 한다.** 본문 전체를 정규식으로 긁으면 참조판례 인용까지 잡혀 "A가 B를 인용"을 "B가 코퍼스에 있음"으로 오판한다(실측: 836개 파일에서 819개가 아니라 2,450개가 잡혀 수집 대상 601건 중 133건이 부당 스킵).
  - **`prec`(법원)와 `detc`(헌재)는 XML 스키마가 다르다** — 결과 태그 대소문자(`prec`/`Detc`), `판결요지`↔`결정요지`, `판례내용`↔`전문`, `선고일자`↔`종국일자`. 법원명·판결유형은 detc에 없다.
- **노동법 해설서 코퍼스(`source_type="textbook"`)는 저작물 본문이라 인용 가드 5종이 전제다.** 2026-08-10에 "교재 본문은 Pinecone에 올리지 않는다"는 기존 결정(`precedent-corpus-expansion` 사이클)을 **가드 구현을 조건으로 변경**했다. 가드 중 하나라도 빠지면 설계 전제가 깨진다:
  - **G1~G3**(`app/templates/prompts.py::TEXTBOOK_CITATION_RULES`) — 축자 인용 금지·해설서 단독 근거 금지·서명 표기. **소프트 가드**라 LLM이 우회할 수 있다. **시스템 프롬프트 본문에 넣지 말 것** — 답변 경로가 `CONSULTATION_SYSTEM_PROMPT`와 `SYSTEM_PROMPT_TEMPLATE`(`pipeline.py` 인라인) 두 갈래인데 해설서 청크는 그 분기와 무관하게 컨텍스트에 실린다. 한쪽에만 넣으면 임금계산·괴롭힘 판정·법제처 실패 경로에서 저작물이 무가드로 나간다(실제로 그렇게 구현했다가 발견됨). `INJECTION_RESISTANCE`와 같이 `pipeline.py`가 두 분기 모두에 접미하고, 컨텍스트에 해설서가 실렸을 때만 붙인다.
  - **G4**(`app/core/rag.py::_cap_by_book`, 상한 3) — **유일한 구조적 통제.** `format_pinecone_hits()` 진입부에 두는 이유는 그 함수가 파이프라인의 단일 초크포인트(`pipeline.py`에서만 호출)이기 때문이다. 다른 곳으로 옮기면 호출부가 늘 때 가드가 샌다.
  - **G4는 BM25 경로에서 새기 쉽다** — BM25 코퍼스는 `{id,text,title,section,source_type}`만 담아 `book_id`가 없었다. `build_bm25_corpus.py`가 `book_id`를 보존하고 `rag.py::_book_id_of()`가 벡터 ID(`textbook_{book_id}_...`)에서 되뽑는 폴백을 갖는 2중 구조다. 둘 중 하나만 두면 구 코퍼스나 신규 소스에서 가드가 무력화된다.
  - **G5** — `rag.py` 라벨 맵과 `public/index.html::renderSources`의 `labels` 양쪽. 한쪽만 고치면 raw `textbook`이 노출된다.
  - **G6 — 해설서 근거 답변은 공개 게시판에서 제외한다**(`metadata.textbook` → `api/index.py::_PUBLIC_EXCLUDE_KEYS`). G1이 소프트 가드라 축자 인용이 새어나갈 수 있는데, 그 답변이 크롤 가능한 공개 페이지로 재게시되면 노출이 1:1 상담에서 공개 배포로 확대된다. 부착 판정과 게시판 제외는 **같은 `used_textbook` 변수**를 써야 한다 — 판정을 복제하면 한쪽만 어긋나 "가드는 붙는데 게시판엔 올라가는" 상태가 된다. 회귀는 T19b.
  - 롤백은 `output_노동법교재/_uploaded_ids.json`의 ID 목록으로만 가능하다(Pinecone Serverless는 메타데이터 필터 삭제 미지원). 이 파일을 지우면 되돌릴 방법이 사실상 없다. 기록은 **upsert보다 먼저** 쓰고 기존 기록과 합집합을 취한다 — 중간에 죽으면 적재분이 추적에서 빠지고, 존재하지 않는 ID의 delete는 무해하므로 상위집합이 안전한 방향이다.
- **해설서 `chunk_id`에는 반드시 `book_id`가 들어가야 한다** — `textbook_{book_id}_{section_idx:04d}_{chunk_idx}`. 서적 식별자가 없던 구 체계로 2권을 올리면 **177건이 조용히 덮어써진다**(실측). NFD post_id 충돌(474벡터 유실)과 같은 실패 모드다. `section_idx`는 **위생 처리 후 유지된 섹션의 순번**이라 폐기 헤딩이 번호를 소비하지 않는다 — 소비하면 `ocr_fixes` 한 줄만 바뀌어도 뒤쪽 ID가 전부 밀려 고아 벡터가 생긴다. 회귀는 `test_precedent_ingest.py` T17.
- **해설서 헤딩 위생 처리는 "폐기만 범용, 복원은 명시 치환"이다**(`sanitize_heading`). 오폐기는 섹션 경계 하나를 잃을 뿐이지만 오복원은 코퍼스에 오정보를 남긴다. 규칙 수정 시 주의점 셋 — (1) 의미문자 비율의 **분모에서 공백·구두점을 빼야** 한다(`2. 요 건`이 2/6=0.33로 오폐기됨), (2) 조문 표기 추출은 **길이 검사보다 먼저** 해야 한다(59자짜리가 상한 60을 통과해 잡음째 살아남음), (3) `ocr_fixes`는 **원문 키**로 매칭한다(정제 후 매칭하면 정제 로직 변경 시 치환 키가 조용히 무효). 폐기율 10% 초과 시 업로드가 중단된다. 회귀는 T18.
- **해설서에서 사건번호를 뽑을 땐 사건부호 화이트리스트가 필수다**(`extract_textbook_cases.py::CASE_RE`). 범용 `CASE_NO_RE`(`\d{2,4}[가-힣]{1,4}\d+`)는 **조문 표기를 사건번호로 오인한다** — 실측(주해Ⅲ): 308건 중 113건이 노이즈였고 상위 오탐이 `43조의2`(31회)·`43조의4`(28)·`109조2`(7)였다. 조문 해설서는 판례 수험서보다 조문 표기 밀도가 훨씬 높아 이 오염이 크다. 화이트리스트는 **긴 부호를 먼저** 나열해야 한다(`다`가 `다카`보다 앞서면 `87다카2803`이 `87다`로 잘린다). 회귀는 T20.
- **macOS 파일명은 NFD(자모 분해)로 저장된다.** 사건번호를 파일명에서 뽑는 코드는 `unicodedata.normalize("NFC", ...)`를 먼저 걸어야 한다 — `[다두도가누]` 같은 완성형 문자 클래스는 NFD 문자열에 절대 매치되지 않고, 폴백이 연도만 잡으면 같은 해 판례들이 동일 ID로 충돌해 Pinecone에서 서로를 덮어쓴다. `pinecone_upload_legal.py::extract_post_id()`가 실제로 이 버그를 갖고 있었고(판례 836개 → 고유 post_id 362개, 474개 덮어쓰기) **2026-08-09 봉인됨**(NFC 선행 + 부호 매핑 + hex 폴백, 회귀는 `test_precedent_ingest.py` T14). 이미 손상된 `precedent` 네임스페이스 자체는 복구하지 않았다 — 프로덕션 검색 대상이 아니고, 그 안의 교재 인용 판례들은 laborlaw-v2에 `precedent_{사건번호}` ID로 재수집돼 있다.

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

- **gap-detector의 Match Rate는 "설계대로 만들었는가"만 답한다 — 설계 자체의 공백은 원리적으로 못 잡는다.** 실측 사례(textbook-corpus-embedding): 120항목 대조로 100%를 냈는데 그 뒤 `/simplify`와 `code-analyzer`가 High 2건을 더 찾았다. ① 답변 경로가 `CONSULTATION_SYSTEM_PROMPT`와 `SYSTEM_PROMPT_TEMPLATE` 두 갈래인 걸 설계가 놓쳐 저작물이 무가드로 LLM에 들어가고 있었고, ② Plan의 저작권 근거("코퍼스는 비공개 백엔드")가 답변이 공개 게시판에 전문 게시된다는 사실을 따지지 않았다. **Match Rate가 90%를 넘어도 그대로 배포하지 말 것** — 변경이 닿는 경로를 설계와 무관하게 훑는 리뷰를 한 번 더 거친다.

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
- `qa_conversations` 공개 조회(게시판)는 `_fetch_qa_public()`(내부에서 `_apply_guard_filter()` PostgREST 필터 + `_drop_flagged()` Python 후처리를 이중으로 건다)를 거쳐 제외 대상 대화를 걸러내고, select에 `metadata`를 포함해야 한다. **`board_posts`에는 적용 금지** — metadata 컬럼이 없어 PostgREST 400이 `try/except`에 삼켜져 사용자 게시글이 통째로 사라진다.
- **Supabase의 모든 객체는 `laborconsult` 스키마에 있고, `public`을 쓰지 않는다.** 이 프로젝트는 다른 앱과 Supabase 프로젝트를 공유할 수 있고, 실제로 2026-08-13에 `public.board_posts`가 **다른 앱의 테이블**(구 단위 권한·승인 사용자·관리자 모델)인데 이름만 같아 우리 코드가 자기 것으로 오인했다. 컬럼 3개(`id`·`category`·`created_at`)가 우연히 겹쳐 "우리 테이블의 스키마 드리프트"로 보였고, Plan·Design·구현까지 간 뒤 `pg_policies`를 보고서야 드러났다. **소유권을 이름으로 판단하지 말 것** — 새 스토어에 손대기 전에 `pg_policies`·`information_schema.columns`로 실제 내용을 먼저 확인한다.
  - **테이블만이 아니다. 같은 사이클에서 네 번 반복됐다** — ① `board_posts`(테이블) ② `search_path=public`(함수의 미지정 참조) ③ `attachments` vs `qa_attachments`(이름이 비슷한 남의 테이블) ④ **`update_updated_at()`(공유 트리거 함수)**. ④는 옛 프로젝트에서 그 앱의 테이블 8개가 쓰고 있었고, 우리 `supabase_schema.sql`이 `CREATE OR REPLACE FUNCTION`으로 **덮어쓸 수 있는 상태**였다(본문이 같아 사고가 안 났을 뿐). 정리 단계에서 `pg_trigger`를 조회하지 않았다면 그 함수를 지워 8개 테이블의 UPDATE를 전부 깨뜨렸을 것이다.
  - **공유 DB에서 무언가를 지우기 전 확인 순서**: 테이블은 `pg_policies`·`information_schema.columns`, 함수는 **`pg_trigger`·`pg_depend`로 의존자**를, 이름이 비슷한 것들은 전체 목록을 눈으로. `DROP`·`CREATE OR REPLACE`는 둘 다 남의 것을 조용히 덮어쓸 수 있다.
  - **접속은 `app/core/storage.py::make_supabase_client()` 한 곳에서만 만든다.** `create_client()`를 직접 부르면 스키마 옵션이 빠져 `public`으로 새고, 그 실패가 조용하다(테이블이 없으면 PGRST205, 있으면 남의 것을 건드린다). 기본값이 `public`이 아니라 `laborconsult`인 것이 핵심이다 — fail-closed. 기동 시 `Supabase 연결: schema=…` 로그를 남겨 사후 확인이 가능하게 한다.
  - **`SECURITY DEFINER` 함수의 `search_path`에 `public`을 넣지 말 것.** 정의자 권한으로 실행되고 미지정 참조가 `search_path` 순서로 해석되므로, `public`이 있으면 함수가 남의 테이블을 읽고 쓴다 — 구 `purge_expired_data()`의 `DELETE FROM board_posts`가 정확히 그 경로였다(pg_cron 미활성이라 실행되진 않았다). `SET search_path = laborconsult, pg_temp`로 두고 `storage.objects`처럼 다른 스키마 객체는 **항상 명시**한다. 회귀는 `test_offline_units.py` D6(스키마 미지정 참조 0건)·D7(`search_path`에 `public` 부재)이 고정한다.
  - **커스텀 스키마에는 Supabase 기본 권한이 자동 부여되지 않는다 — 테이블도 함수도.** `public`은 default privileges가 새 객체에 anon·authenticated·service_role 권한을 자동으로 주지만 `laborconsult`는 대상이 아니다. `GRANT USAGE ON SCHEMA`만으로는 부족하다. 2026-08-13에 **같은 클래스로 두 번** 걸렸다:
    - **테이블** — RLS 정책만 만들고 `GRANT SELECT, INSERT …`를 빠뜨려 `qa_*`·`law_article_cache`가 전부 `permission denied`. **RLS 정책(어느 **행**)과 GRANT(**접근 자체**)는 다른 계층이라 둘 다 있어야 한다.**
    - **함수** — `REVOKE ALL ON FUNCTION … FROM PUBLIC`이 **service_role의 유일한 경로까지 지웠다.** 함수는 생성 시 PUBLIC에 EXECUTE가 기본 부여되고 `public` 스키마에선 default privileges가 service_role에도 따로 주는데, 커스텀 스키마엔 그게 없다. `service_role`은 BYPASSRLS일 뿐 **superuser가 아니다** — 같은 이유로 자기가 소유하지 않은 함수에 GRANT를 줄 수도 없다(회수하면 SQL Editor로만 복구 가능). `purge_storage_orphans.py`가 `42501 permission denied for function storage_purge_claim`으로 죽었다.
    - 반대로 **`purge_expired_data`는 일부러 service_role에 주지 않는다** — pg_cron이 `postgres`(superuser)로 실행하므로 불필요하고, 영구 삭제 함수라 호출 경로를 좁게 둔다.
  - **DDL은 최종 상태 4파일이고 적용 순서가 있다**: `supabase_schema.sql`(스키마 생성) → `supabase_abuse_guard.sql` → `supabase_board_posts.sql` → `supabase_retention_purge.sql`. **패치 파일을 따로 두지 말 것** — 이전 프로젝트 전환에서 base만 적용하고 후속 패치를 놓쳐 `qa_sessions.session_data`·`law_article_cache`가 빠진 채 프로덕션이 돌았다(매 채팅 PGRST204 → 후속 질문 맥락 유실, 법령 L2 캐시 404). `supabase_fix_*.sql` 3종은 본문에 흡수됐고 이력으로만 남아 있다.
  - **완료 조건은 "실행했다"가 아니라 `python3 check_schema.py` 전수 통과다.** SQL Editor는 구문 오류 하나로 전량 롤백하고, 선택 영역만 실행되기도 한다(둘 다 실제로 겪음). CI는 DB 자격증명이 없어 **파일↔코드만** 대조한다(D5~D9) — 실제 DB 대조는 이 스크립트가 유일하다.
  - **SQL Editor에 붙여넣을 DDL에는 큰따옴표 식별자를 쓰지 말 것.** 복사 과정에서 스마트 따옴표(U+201C)로 바뀌면 `syntax error at or near …`로 죽는다(실제 발생). 인용부호 없는 이름은 그 실패 모드 자체가 없다. 회귀는 D8.
- **스키마 파일 없는 테이블을 만들지 말 것.** `board_posts`가 `supabase_schema.sql`에 없이 SQL Editor 수동 실행으로 생겼고, 그 DDL이 **부분만 적용된 채** 사이클이 종료됐다 — 2026-08-13 실측에서 8컬럼 중 5개(`nickname`·`password_hash`·`question_text`·`status`·`ip_hash`)가 없었고, **게시판 글쓰기·삭제는 배포된 채로 한 번도 작동한 적이 없었다**(INSERT에 `try/except`가 없어 HTTP 500). `board_posts` 0행은 "아무도 안 썼다"가 아니라 "쓸 수 없었다"였다. 저장소에 단일 출처가 없으면 **어긋났다는 사실 자체를 아무도 모른다.**
  - DDL 단일 출처: `supabase_board_posts.sql`(멱등 — `ADD COLUMN IF NOT EXISTS` + 제약은 `pg_constraint` 이름 검사). 부분 적용 상태에서 재실행해도 안전하다.
  - 컬럼 집합 단일 출처: `app/core/storage.py::BOARD_POST_COLUMNS` / `BOARD_POST_PUBLIC_COLUMNS`. 공개 목록에는 `password_hash`·`ip_hash`·`status`가 **없어야** 하며 회귀는 `test_offline_units.py::test_board_posts_schema_source`가 고정한다.
  - **감시는 2층이고 CI는 절반만 본다.** 오프라인(`test_offline_units.py`)은 **DDL 파일 ↔ 코드 상수**만 대조한다 — 파일이 맞아도 그 DDL을 DB에 적용하지 않았으면 못 잡는다(이번 드리프트가 그 유형). **코드 ↔ 실제 DB** 대조는 `python3 check_schema.py`이고 자격증명이 필요해 CI에서 돌지 않는다. **배포 전 수동 실행 항목이다.**
  - DDL이 필요한 사이클은 완료 조건을 "실행했다"가 아니라 **"실측했다"** 로 둘 것. 선행 사이클(`board-write-security`)은 배포 체크리스트를 미체크로 남긴 채 Report까지 작성됐고 아무도 몰랐다.
- **`board_posts`의 anon UPDATE는 soft delete 단방향으로만 열려 있다** — RLS `USING (status='active') WITH CHECK (status='deleted')` + `GRANT UPDATE (status)` 컬럼 권한. RLS는 행 단위라 "status만 수정"을 표현할 수 없어 GRANT가 함께 필요하다. `USING (true)`로 열면 누구든 `question_text`를 고치거나 삭제된 글을 되살릴 수 있다(bcrypt 검사는 앱 단이라 RLS로 막지 못한다). ⚠️ Supabase 기본 설정의 `GRANT ALL ON ALL TABLES IN SCHEMA public TO anon`을 재실행하면 이 제한이 **조용히 원복된다** — `supabase_board_posts.sql` 말미의 검증 SQL ③이 감지 수단이고, 파일 재실행이 복구 수단이다.
- **공개 게시판 제외 계약의 단일 출처는 `app/core/storage.py`다** — `PUBLIC_EXCLUDE_KEYS` + `is_public_excluded()`. 이 모듈이 FastAPI·pipeline·API 키 어디에도 의존하지 않아 게시판(`api/index.py`)·운영 스크립트(`dedupe_board.py`)·저장부가 **모두 import할 수 있는 유일한 지점**이기 때문이다. **어디서도 재선언하지 말 것** — 재선언하면 키가 늘 때 한쪽만 갱신돼 갈라진다. 회귀는 `test_offline_units.py::test_public_exclude_keys`가 `dedupe_board.PUBLIC_EXCLUDE_KEYS is storage.PUBLIC_EXCLUDE_KEYS` 동일성으로 고정한다(대조가 아니라 구조적 보장).
  - **집행은 `_PUBLIC_EXCLUDE_KEYS`(`api/index.py`가 storage에서 import) 한 곳이 하고, 판정은 여러 곳이 한다.** 현재 4종 — `guard_flag`(가드 의심)·`truncated`(절단 답변)·`textbook`(해설서 근거)·`synthetic`(벤치마크·CLI·테스트 산출물). 새 제외 사유를 추가할 때 판정부만 만들고 이 튜플에 키를 안 넣으면 아무 일도 일어나지 않는다(조용한 실패).
  - **이 키들은 `True`일 때만 기록한다.** PostgREST 필터는 키 부재(`IS NULL`)로, Python 후처리(`_drop_flagged`)는 truthiness로 판정하므로 `{"truncated": False}`처럼 명시적 False를 쓰면 두 경로가 갈라진다.
  - `dedupe_board.py`가 생성하는 검증 SQL의 `IS NULL` 조건도 이 상수에서 만든다 — 손으로 나열하면 키가 늘 때 SQL이 조용히 틀린 검증문을 담고, 그걸 잡는 테스트가 없다.
- **`metadata.synthetic` 판정은 3중이고 각자 다른 실패 클래스를 담당한다**(board-duplicate-cleanup). 하나만 두면 나머지 경로로 샌다 — 실측상 공개 463건 중 323건(69.8%)이 이 경로로 유입된 합성 데이터였다.
  - **G-A `pipeline.py`(`conv_metadata` 조립부) — `guard_ctx is None`이면 합성.** `guard_ctx`는 웹 엔드포인트만 넘기므로 이 조건이 "비웹 호출"과 동치다(`ABUSE_GUARD_MODE=off`에서도 `_guard_chat_request()`는 모드 값만 `"off"`인 컨텍스트를 반환하므로 웹 경로에서 `None`이 되지 않는다). **광의 규칙** — 새 테스트 스크립트를 아무 규약 없이 작성해도 자동으로 걸린다.
  - **G-B `api/index.py::_is_synthetic_request()` — 비프로덕션 출처 HTTP 요청.** `test_e2e.py`류는 서버가 정상 hex12 세션을 발급해 세션 ID로 구별이 불가능하므로 요청 환경(`VERCEL_ENV`·loopback IP)으로 판정한다. **반드시 양성 검출로만 쓸 것** — "프로덕션임을 증명 못 하면 합성" 방식은 `VERCEL_ENV`가 누락된 순간 모든 실사용 대화가 합성으로 찍혀 **게시판이 조용히 얼어붙는다.** 판정 불가는 실사용으로 떨어뜨린다.
  - **G-C `storage.py::save_conversation()` — 예약 접두사(`SYNTHETIC_SESSION_PREFIXES`).** `save_conversation`은 `pipeline.py` 단일 호출부를 갖는 초크포인트라 여기 두면 저장 경로가 늘어도 새지 않는다. `record.metadata`는 **복사해서** 수정할 것(제자리 변경 시 호출부가 이후 참조하는 값이 오염된다). 접두사는 `_`로 끝나야 hex12 세션(16진수)과 충돌하지 않는다.
  - **G-C가 단독으로 잡는 케이스는 현재 0건이고, 부하를 지는 것은 G-A다.** 예약 접두사 세션은 인프로세스 호출부에서만 생긴다 — 웹 경로는 `abuse_guard._SESSION_ID_RE`(`^[A-Za-z0-9-]{8,64}$`)가 `_`를 받지 않아 클라이언트가 `test_foo`를 보내도 폐기하고 신규 hex12를 발급하기 때문이다. 그 집합은 정확히 `guard_ctx is None`, 즉 G-A가 이미 덮는 범위다(`cmp_*`도 `compare_llm_models.py`의 G-A 케이스이고 `verify_*`·`eval_*`는 사용처 0건). G-C는 향후 파이프라인 외 저장 경로를 위한 백스톱으로 남기되, **"G-C가 접두사를 다 잡으니 G-A는 중복"이라 판단해 G-A를 지우지 말 것** — 커버리지가 통째로 사라진다.
  - 이 가드들은 **신규 저장분에만** 적용된다. 기존 데이터를 소급 제외하지 않으므로, 방침을 바꾸려면 백필 스크립트가 별도로 필요하다.
- **DELETE는 anon 키로 불가능하고, 실패가 조용하다 — `qa_conversations`·`qa_sessions`·`qa_attachments` 전부.** RLS 정책이 `INSERT`·`SELECT`(세션은 `UPDATE`까지)만 부여돼 있어(`supabase_schema.sql:47-55`) DELETE는 권한 오류가 아니라 **"일치 행 0개"로 처리**된다 — PostgREST가 200 OK + 빈 배열을 반환하므로 `try/except`로는 절대 감지되지 않는다(2026-08-12 실측: 스크립트가 "225/225 삭제"를 출력하고 실제로는 0건 삭제). **Supabase 쓰기 스크립트는 예외가 아니라 `len(res.data)` 반영 행 수로 성공을 판정할 것.** 삭제 경로는 둘 — ① 생성된 SQL을 Supabase SQL Editor에서 실행(`postgres` 역할이라 RLS 우회) ② `SUPABASE_SERVICE_ROLE_KEY` 추가. **anon에 DELETE 정책을 부여하지 말 것** — 일회성 정리를 위해 상시 삭제 권한을 여는 것은 비대칭적이고, 키 유출 시 상담 이력 전체가 삭제 가능해진다.
  - **이 판정을 한 함수에만 넣고 끝내지 말 것.** `dedupe_board.py`가 `_delete_batches()`는 고쳤는데 형제 함수 `_purge_orphan_sessions()`는 `done += 1`로 남아 있어 **`--purge-sessions`가 "N건 정리 완료"를 출력하고 0건을 지우는 상태**였다(2026-08-13, CodeRabbit 리뷰에서 발견). DELETE를 부르는 지점을 파일 단위로 전부 훑을 것.
  - **삭제 대상 선정과 DELETE가 별도 요청이면 그 사이가 경합 창이다.** `qa_conversations.session_id`가 `ON DELETE CASCADE`라, 고아 판정 후 삭제 전에 그 세션으로 새 대화가 저장되면 CASCADE가 그것까지 지우고 **백업 어디에도 없다**. 구조적 해소는 `DELETE ... WHERE NOT EXISTS (...) RETURNING`을 단일 SECURITY DEFINER RPC로 도는 것이고, 그때까지는 쓰기가 멈춘 유지보수 창에서만 실행한다.
  - **정리 스크립트가 남기는 백업 JSON·생성 SQL은 상담 원문 평문 덤프다.** `.gitignore`는 커밋만 막고 로컬 디스크·백업 도구·운영자 사본은 보호하지 않는다 — 검증이 끝나면 파기하거나 저장소 밖 암호화 위치로 옮길 것(`--backup-dir`). 개인정보처리방침의 보유기간 대상과 같은 내용이다.
- **게시판 정리(`dedupe_board.py`)는 `--apply` 없이는 쓰기 0건이고, 백업 JSON 생성 성공이 삭제의 전제조건이다.** 백업엔 상담 원문이 그대로 들어가므로 `.gitignore`의 `backup_board_dedupe_*.json`을 지우지 말 것. **`--purge-sessions`는 CASCADE 지뢰다** — `qa_conversations.session_id`가 `ON DELETE CASCADE`라 세션을 지우면 그 세션의 **남은 대화까지 사라진다**(벤치마크 세션 하나가 대화 4건을 갖고 그중 1건만 유지 대상인 상황이 실제로 있다). 삭제 직전 세션별 잔여 대화 수 재조회 가드를 제거하지 말 것.
- **재발 방지(가드)를 정리보다 먼저 배포할 것.** 순서가 바뀌면 정리 완료 시점부터 가드 배포 시점까지의 벤치마크 실행이 다시 오염을 만든다. 배포 후 **양성 검증 2단계 필수** — ① 프로덕션에서 실제 질문 1건이 게시판에 나타나는지(G-B 오탐 0 확인) ② 로컬 벤치마크 실행 후 게시판 건수가 불변인지(가드 작동 확인). 가드가 fail-open이라 오작동이 조용하다.
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
  - **`public/index.html`의 `.chat-card`(채팅창 외곽 컨테이너)는 카드 시각 효과(`background`/`border`/`box-shadow`)를 두지 않는다** — 레이아웃(`overflow`/`flex`/`text-align`)만 담당하는 투명 래퍼다. `#chat-card` id·`.active` 클래스 토글은 `expandChat()`/`resetChat()`/`showAnswerActions()`(JS)이 계속 참조하므로 요소 자체는 유지해야 한다. (이전엔 카드 규격에 `border-radius: 0` 예외를 둬 각진 프레임 안에 둥근 내부 요소를 넣는 절충이었으나, 카드 시각 자체를 제거하는 쪽으로 대체됨 — 부조화 문제는 다른 컴포넌트에 카드 규격을 적용할 때 여전히 재현될 수 있다.)
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
