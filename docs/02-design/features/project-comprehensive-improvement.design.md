# 전체 프로젝트 종합 개선 Design (project-comprehensive-improvement)

> **Summary**: 종합 감사에서 도출된 Wave 1~5(보안 하드닝·계산 정확성·RAG 기능결함·프론트/배포·저장소 정리)의 구현 수준 기술 설계. Wave 0(긴급)은 완료·머지(PR #11)됨.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-07-02
> **Status**: Draft
> **Planning Doc**: [project-comprehensive-improvement.plan.md](../../01-plan/features/project-comprehensive-improvement.plan.md)

---

## 1. Overview

### 1.1 설계 목표

기존 아키텍처(FastAPI + Vercel serverless + Supabase/Pinecone)를 **변경하지 않고**, 감사에서 확인된 결함을 코드 수준에서 하드닝·정합화한다. 각 항목은 독립적으로 구현·검증·롤백 가능하도록 최소 침습으로 설계한다.

### 1.2 설계 원칙

- **최소 침습**: 함수 시그니처·호출 계약을 최대한 보존, 신규 파일보다 기존 파일 보강 우선
- **폴백 필수** (CLAUDE.md 규약): 신규 외부 의존(공유 rate-limit 스토어 등) 실패 시 기존 인메모리로 graceful degrade
- **계약 정합**: 생성 로직과 검증 로직이 동일 데이터 소스를 사용하도록 통일(특히 판례 인용)
- **검증 가능**: 각 수정마다 재현 테스트 또는 골든 케이스로 회귀 방지

### 1.3 완료 항목 (Wave 0, 참조용)

| ID | 항목 | 커밋 |
|----|------|------|
| S-0 | send-email CAPTCHA 필수화 + IP rate-limit | `cc4e96c` |
| S-1a | 커밋된 API 키 마스킹 | `cc4e96c` |
| C-0 | ZeroDivision 가드(ordinary/minimum) | `cc4e96c` |

---

## 2. Architecture

### 2.1 영향 범위 맵

```
[Wave 1 보안]        api/index.py  ── JWT/CAPTCHA/rate-limit/PostgREST/anonymize/sanitize
                     app/config.py ── 시크릿 로딩
                     vercel.json   ── CORS/보안헤더
                     (신규) Supabase 테이블: rate_limits, captcha_used

[Wave 2 계산]        wage_calculator/constants.py       ── 보험료 상수
                     wage_calculator/facade/__init__.py ── 음수 가드/maternity 자동감지
                     wage_calculator/calculators/*.py   ── 매직넘버/유급공휴일
                     wage_calculator_cli.py             ── 골든 테스트

[Wave 3 RAG]         app/core/rag.py             ── format_pinecone_hits
                     app/core/citation_validator ── build_available_citations_text
                     app/core/nlrc_cases.py      ── 판례 보강 키
                     app/core/pipeline.py        ── 의도분석 게이팅/sources emit
                     data/bm25_corpus.json       ── BM25 배포

[Wave 4 프론트]      public/index.html           ── md()/board/timeout/a11y/email UX
                     public/calculators.html     ── sendPrompt 정의
                     api/index.py                ── 공용 예외 핸들러/스키마
                     vercel.json                 ── maxDuration

[Wave 5 정리]        .gitignore / 루트 쓰레기 / 죽은 코드 / PDCA 상태
```

### 2.2 신규 데이터 모델 (Wave 1, Supabase)

공유 rate-limit·CAPTCHA 1회용 소비를 위한 경량 테이블. **미생성 시 인메모리 폴백**.

```sql
-- 공유 rate-limit (부작용 엔드포인트: board_write, send-email)
CREATE TABLE IF NOT EXISTS rate_limits (
  bucket      TEXT NOT NULL,          -- 'board:<ip_hash>' | 'email:<ip_hash>'
  ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket, ts)
);
CREATE INDEX IF NOT EXISTS idx_rate_limits_bucket_ts ON rate_limits (bucket, ts DESC);

-- CAPTCHA 1회용 소비 (jti = 토큰 payload 해시)
CREATE TABLE IF NOT EXISTS captcha_used (
  jti         TEXT PRIMARY KEY,
  used_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 3. Wave 1 — 보안 하드닝 (상세 설계)

### 3.1 JWT 시크릿 분리·강제 (S-1b)

**대상**: `api/index.py:209-210`, `440-457`(CAPTCHA 서명), `app/config.py`

**현재**: `JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", ADMIN_PASSWORD)` — 미설정 시 관리자 비밀번호가 서명키. CAPTCHA HMAC도 `JWT_SECRET` 재사용.

**설계**:
```python
# api/index.py 상단
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", "")
CAPTCHA_SECRET = os.environ.get("CAPTCHA_HMAC_SECRET", JWT_SECRET)  # 없으면 JWT_SECRET로 폴백(분리 권장)

def _require_admin_secret() -> str:
    """관리자 기능 진입 시 호출 — 시크릿 미설정/약함이면 503."""
    if len(JWT_SECRET) < 32:
        raise HTTPException(503, "관리자 인증이 구성되지 않았습니다(ADMIN_JWT_SECRET ≥ 32자 필요).")
    return JWT_SECRET
```
- 관리자 로그인/검증 진입부에서 `_require_admin_secret()` 호출 → 약한 시크릿이면 기동은 유지하되 관리자 기능만 비활성(graceful).
- CAPTCHA 서명/검증(`_generate_captcha`, `_verify_captcha`)의 `JWT_SECRET.encode()` → `CAPTCHA_SECRET.encode()`로 교체(키 용도 분리).
- **엣지**: 기존 발급 토큰은 시크릿 변경 시 무효화됨(24h 만료라 영향 제한). 배포 노트에 명시.

### 3.2 관리자 로그인 브루트포스 방어 (S-1c)

**대상**: `api/index.py:242-253`

**설계**:
```python
@app.post("/api/admin/login")
def admin_login(body: AdminLoginRequest, request: Request):
    _require_admin_secret()
    ip = _client_ip(request)  # 공통 헬퍼로 추출
    if not _check_rate_limit(ip, max_count=5, window=300, store=_login_rate):
        raise HTTPException(429, "로그인 시도가 많습니다. 잠시 후 다시 시도하세요.")
    if not hmac.compare_digest(body.password, ADMIN_PASSWORD):  # 상수시간 비교
        raise HTTPException(401, "인증 실패")
    ...
```
- `_client_ip(request)` 헬퍼 신설(현재 board_write/send-email에 중복된 IP 추출 로직 통합).
- 5회/5분 초과 시 429. 인메모리 `_login_rate` + (Wave 1 공유 스토어 적용 시 승격).

### 3.3 공유 rate-limit 스토어 (S-2a)

**대상**: `_check_rate_limit`(현재 인메모리), 신규 `rate_limits` 테이블

**설계**: `_check_rate_limit`에 Supabase 백엔드 경로 추가, 실패 시 인메모리 폴백.
```python
def _check_rate_limit(ip, max_count=3, window=60, store=None, bucket_prefix="board"):
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    sb = _get_supabase_safe()          # 실패 시 None
    if sb is not None:
        try:
            bucket = f"{bucket_prefix}:{ip_hash}"
            since = _iso(time.time() - window)
            cnt = sb.table("rate_limits").select("ts", count="exact")\
                    .eq("bucket", bucket).gte("ts", since).execute().count or 0
            if cnt >= max_count:
                return False
            sb.table("rate_limits").insert({"bucket": bucket}).execute()
            return True
        except Exception:
            pass  # ↓ 인메모리 폴백
    return _check_rate_limit_memory(ip_hash, max_count, window, store or _write_rate)
```
- 오래된 행 정리는 별도 크론/TTL(또는 주기적 delete)로 — 초기엔 미도입(테이블 증가 허용, Wave 5 후속).
- **폴백**: Supabase 없으면 기존 인메모리 그대로.

### 3.4 PostgREST 필터 이스케이프 (S-2b)

**대상**: `api/index.py:335-337`(admin `or_`), `699`·`724`(board_search `ilike`)

**설계**: LIKE 와일드카드·PostgREST 구문 문자 이스케이프 헬퍼.
```python
def _safe_like(term: str) -> str:
    term = term[:100]                              # 길이 제한
    term = re.sub(r'[%_\\]', lambda m: '\\' + m.group(), term)  # LIKE 와일드카드 이스케이프
    return term.replace(",", " ").replace("(", " ").replace(")", " ")  # or_ 구문문자 제거

# board_search
if q:
    qa_qb = qa_qb.ilike("question_text", f"%{_safe_like(q)}%")
# admin or_()
safe = _safe_like(search)
query.or_(f"question_text.ilike.%{safe}%,answer_text.ilike.%{safe}%")
```
- **엣지**: 이스케이프 후에도 정상 검색 동작 유지(한글·영문·숫자 무영향).

### 3.5 board_posts 익명화 + PII 정규식 확장 (S-2c, S-2d)

**대상**: `api/index.py:610-615`(`_ANON_PATTERNS`), `731`(board_search), `794-804`(board_detail)

**설계 — 정규식 추가**:
```python
_ANON_PATTERNS = [
    (re.compile(r'\d{6}[-\s]?[1-4]\d{6}'), '******-*******'),          # 주민등록번호
    (re.compile(r'\d{6}[-\s]?\d{7}'), '******-*******'),               # 주민번호 일반형
    (re.compile(r'\b\d{2,6}[-\s]?\d{2,6}[-\s]?\d{2,6}\b(?=\s*(?:계좌|번호))'), '***계좌***'),  # 계좌(보수적)
    # ... 기존 4개 패턴 유지 ...
]
```
**설계 — board_posts 적용** (`board_search` line 731, `board_detail`):
```python
"question": _anonymize(row.get("question_text", "")),
"nickname": _anonymize(row.get("nickname", "")),
```
- **주의**: 주민번호 패턴을 전화·일반 숫자열보다 **앞**에 배치(우선 매칭). 계좌 패턴은 오탐 방지 위해 문맥 키워드 요구(보수적).

### 3.6 HTML 새니타이저 교체 (S-2e)

**대상**: `api/index.py:858-862`(`_sanitize_html`), `requirements.txt`

**설계**: 정규식 → allowlist 라이브러리(`nh3` — Rust 기반, 빠르고 의존성 경량).
```python
import nh3
_ALLOWED_TAGS = {"p","br","strong","em","ul","ol","li","h1","h2","h3","h4","blockquote","code","pre","table","thead","tbody","tr","th","td","a","span"}
def _sanitize_html(html: str) -> str:
    return nh3.clean(html, tags=_ALLOWED_TAGS,
                     attributes={"a": {"href"}, "span": {"style"}},
                     url_schemes={"https", "mailto"})
```
- `requirements.txt`에 `nh3>=0.2` 추가. import 실패 시 기존 정규식 폴백(graceful).

### 3.7 CORS·보안 헤더 + CAPTCHA 1회용 (S-3)

- **CORS** (`api/index.py:36-41`): `allow_origins`를 실제 도메인(예: `https://<vercel-domain>`, 로컬 `http://localhost:5555`)으로 제한. `vercel.json`의 중복 CORS 헤더 제거.
- **보안 헤더** (`vercel.json`): 정적 라우트에 `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Strict-Transport-Security`, 최소 `Content-Security-Policy` 추가.
- **CAPTCHA 1회용**: `_verify_captcha` 성공 후 `jti = sha256(payload)[:32]`를 `captcha_used`에 INSERT(중복이면 재사용 거부). Supabase 없으면 스킵(현행 유지).

---

## 4. Wave 2 — 계산 정확성·안정성 (상세 설계)

### 4.1 국민연금 기준소득월액 갱신 (C-1)

**대상**: `wage_calculator/constants.py:225-234`

**설계**:
```python
2026: {
    ...요율 유지...,
    "pension_income_max":  6_370_000,   # 2025.7 개정 상한
    "pension_income_min":    400_000,   # 2025.7 개정 하한
    "health_premium_max":  4_240_710,   # 확정 시 갱신
    "health_premium_min":      9_890,
},
```
- 주석에 "국민연금 소득월액은 매년 7월 변경(적용기간 7월~익년6월)" 명시.
- **회귀**: 월보수 617만~637만 구간 케이스를 골든 테스트에 추가.

### 4.2 음수 임금 가드 (C-2c)

**대상**: `wage_calculator/facade/__init__.py::calculate` 진입부

**설계**:
```python
def calculate(self, inp, targets=None):
    _clamp_negative(inp)   # hourly/daily/monthly/annual_wage, schedule 시간 필드 max(0,·)
    ...
```
- 음수 발견 시 0 클램프 + `result.warnings`에 "음수 입력 보정" 추가. 파싱 단계(`_provided_info_to_input`)에도 동일 방어.

### 4.3 출산휴가 자동감지 수정 (C-2a)

**대상**: `wage_calculator/facade/__init__.py:216-217`(죽은 `pass` 블록)

**설계**:
```python
if inp.is_multiple_birth or getattr(inp, "maternity_leave_start", None):
    targets.append("maternity_leave")
```
- 트리거 필드 없으면 블록 삭제. `_auto_detect_targets` 반환에 실제 반영.

### 4.4 골든 테스트 도입 (C-2b)

**대상**: `wage_calculator_cli.py::TEST_CASES`

**설계**: 각 케이스에 `expected` dict + 단언 + 종료코드.
```python
{"name": "...", "input": {...}, "targets": [...],
 "expected": {"통상시급": 10_000, "월최저임금미달": False}, "tol": 0.01}
# 실행부
for c in cases:
    r = WageCalculator().calculate(build(c["input"]), c["targets"])
    for k, v in c.get("expected", {}).items():
        assert abs(actual(r, k) - v) <= v * c.get("tol", 0.01), f"{c['name']}: {k}"
sys.exit(1 if failures else 0)
```
- 최소 20케이스(핵심 계산 커버) + 2026/2025 요율 분기 케이스. `calculator_batch_test.py`는 "크래시/파싱 실패 감지" 용도로 주석·리포트 분리.

### 4.5 매직넘버·유급공휴일 (C-3)

- `minimum_wage.py:107`: `legal_minimum * 209.0` → `legal_minimum * MONTHLY_STANDARD_HOURS`.
- `comprehensive.py:34`: 파일 내 `WEEKS_PER_MONTH` 재정의 제거 → `utils.WEEKS_PER_MONTH` import.
- `helpers.py:85`(`_pop_public_holiday`): `inp.wage_type in (MONTHLY, ANNUAL)`면 월합산 0, `HOURLY/DAILY`만 가산.

---

## 5. Wave 3 — RAG 기능결함 (상세 설계)

### 5.1 판례 인용 목록 통일 (R-1b) — 최우선

**문제 근거(확인)**: `rag.py:316-321` `format_pinecone_hits`의 meta는 `{title, section, source_type, score}`(case_name 없음). `citation_validator.py:105` `build_available_citations_text`는 `extract_precedents_from_hits(hits)`로 **hits의 content/title에서 판례번호를 파싱**하는데, 파이프라인이 `hits=[]` + `legal_precedents=precedent_meta`로 호출 → Pinecone 판례번호가 목록에 안 실림.

**설계**: 파이프라인이 **판례 hit의 title+content를 담은 리스트**를 `hits`로 전달.
```python
# rag.py format_pinecone_hits: meta에 content 동봉
meta_list.append({
    "title": h["title"], "section": h.get("section",""),
    "source_type": h["source_type"], "score": h["score"],
    "content": content,        # ← 추가 (판례번호 파싱 소스)
})
# pipeline.py 인용목록 생성부
citations_text = build_available_citations_text(
    hits=[m for m in precedent_meta if m.get("source_type")=="precedent"],  # ← hits로 전달
    legal_precedents=api_precedents,   # 법제처 API 결과(case_name 보유)만
)
```
- 사후 검증(`pipeline.py:1292` `m.get("case_name", m.get("title"))`)과 **동일 소스**를 보게 되어 가이드↔검증 정합.
- **엣지**: content가 커지면 목록 텍스트 길이 증가 → `extract_precedents_from_hits`는 번호만 추출하므로 프롬프트 영향 미미.

### 5.2 NLRC 판례 보강 키 교정 (R-1a)

**대상**: `app/core/nlrc_cases.py:229-236`

**설계**: `search_precedent()` 실제 반환 키(`case_name`/`court`/`date`)로 교정, 존재하지 않는 `사건번호` 제거.
```python
for r in related:
    name = r.get("case_name", "")
    if not name: continue
    lines.append(f"- {name} ({r.get('court','')} {r.get('date','')})")
```

### 5.3 의도분석 2회 → 게이팅 (R-2a)

**문제 근거(확인)**: `pipeline.py:887` else 분기가 **비계산 질문 전량**에 `_extract_params`(Sonnet 2 tools) 재호출. 두 번째 호출의 실효는 괴롭힘 파라미터뿐.

**설계**: else 분기를 괴롭힘 가능성이 있을 때만 실행.
```python
else:
    topic = getattr(analysis, "consultation_topic", "") if analysis else ""
    harass_likely = (topic == "직장내괴롭힘") or _HARASS_KW.search(query)
    if harass_likely:
        tool_type, params = _extract_params(combined_query, config.claude_client)
        if tool_type == "harassment" and params and params.get("is_harassment_question"):
            ... 괴롭힘 판정 ...
    # 그 외 일반 상담: _extract_params 생략 → 곧바로 RAG/consultation 경로
```
- `_HARASS_KW = re.compile(r"괴롭힘|폭언|따돌림|모욕|갑질|폭행")`.
- **효과**: 비계산·비괴롭힘 상담에서 Sonnet 1회 절감(대표 트래픽 지연·비용↓). **엣지**: 괴롭힘 키워드 누락 시 판정 스킵 → topic 기반 1차 방어 유지.

### 5.4 sources 이벤트 실체화 (R-2b)

**대상**: `pipeline.py:1068`(빈 배열 emit), `public/index.html:1018`

**설계**: `precedent_meta`(title/source_type/score)를 `sources`로 전송, 프론트에 출처 칩 렌더.
```python
yield {"type": "sources", "hits": [
    {"title": m["title"], "type": m["source_type"], "score": round(m["score"],3)}
    for m in precedent_meta[:8]]}
```
- 프론트 `readSSE`의 `sources` no-op → 출처 목록 렌더 함수로 교체. (미채택 시 이벤트·CLAUDE.md 문서에서 제거해 계약 정리 — 택1)

### 5.5 BM25 배포 (R-2c)

**설계**: `python3 build_bm25_corpus.py` 산출물 `data/bm25_corpus.json`을 커밋(또는 배포 훅). Vercel 함수 번들 크기 확인(초과 시 Dense-only 유지 + CLAUDE.md 서술 현실화). Mecab 미설치 → 정규식 토크나이저 폴백(현행).

---

## 6. Wave 4 — 프론트/UX/배포 (상세 설계)

### 6.1 Vercel maxDuration (F-1b)

`vercel.json`:
```json
{ "functions": { "api/index.py": { "maxDuration": 60 } } }
```
Pro 플랜 필요. 미지원 시 파이프라인 first-token 조기 스트리밍으로 대체.

### 6.2 클라이언트 타임아웃·재시도 (F-2d)

`public/index.html::send()`/`readSSE()`:
```javascript
const ctrl = new AbortController();
const t = setTimeout(() => ctrl.abort(), 60000);
fetch(url, { signal: ctrl.signal, ... }).finally(() => clearTimeout(t));
// catch에서 "다시 시도" 버튼 렌더
```

### 6.3 렌더 XSS 차단 (F-2a, F-2b)

- `md()` 진입부: 원문 1회 `escapeHtml`(`&<>"'`) 후 마크다운 파싱. 코드펜스 기존 이스케이프 유지.
- 게시판 항목: 인라인 `onclick="askQuestion('...')"` → `<button data-q="...">` + 위임 `addEventListener('click', e => askQuestion(e.target.dataset.q))`. 문자열 조립 제거.

### 6.4 sendPrompt 복구 (F-2c)

`public/calculators.html`(부모)에 정의:
```javascript
window.sendPrompt = (q) => { location.href = '/?q=' + encodeURIComponent(q); };
// 또는 iframe→부모 postMessage 수신 후 메인 챗봇 입력창에 주입
```
- 미지원 노드는 onclick 제거(죽은 인터랙션 정리).

### 6.5 접근성 (F-2e)

`#chat` `aria-live="polite"`, `#msg-input` `aria-label`, 게시판 항목 `<button>`, 슬라이드 메뉴 포커스 트랩, FAQ 탭 `role="tab"`/`aria-selected`.

### 6.6 API 예외/스키마 정합 (F-2f)

- `@app.exception_handler(Exception)` 공용 핸들러로 DB 오류 → `{"detail": ...}` 503 일관 반환(traceback 미노출).
- 페이지네이션 응답 표준화: `{items, total, page, per_page, has_more}` 통일(admin `pages`, board `total_pages` → 통일).
- `send-email` SMTP 미설정 500 → **503**.

### 6.7 이메일 입력 UX (F-3)

Wave 0의 `prompt()` 2회 → 인라인 모달(이메일 + CAPTCHA 한 화면). 기능 계약(POST 바디)은 불변.

---

## 7. Wave 5 — 저장소 위생·죽은 코드 (상세 설계)

### 7.1 쓰레기 삭제 + .gitignore

```bash
rm -f '=0.8.0' '=2.0.0' '=4.0.0' '=5.0.0'
```
`.gitignore` 추가 블록:
```gitignore
output_*/
nodong_counsel/
documents/
test_sample/
benchmark_*.json
*_results.json
batch_test_report.md
test_*.json
metadata*.json
*.jsonl
_contextual_upload_progress.json
=*
.vscode/
.devproxy.json
.bkit/runtime/
.bkit/snapshots/
.bkit/state/pdca-status.json
```
- `metadata.json`·`supabase_fix_session_id.sql`은 런타임/마이그레이션 여부 확인 후 처리. `.vercelignore`와 동기화.

### 7.2 죽은 코드 정리

| 대상 | 조치 |
|------|------|
| `app/core/composer.py` | legacy 확정 — `answer_model` AttributeError 잠복. 삭제 또는 test 전용 명시 |
| `app/core/converter.py`·`calculator.py` | 오펀(호출 0). 삭제 또는 파이프라인 인라인과 계약 통일 |
| session `pending`·`follow_up` | 미배선. 배선 복원 or 제거(택1) + CLAUDE.md SSE 목록 정정 |
| 프론트 `initHeroCalcs`·`escHtml` 중복정의 | 제거 |
| `legal_api.py` circuit half-open | 단일 probe 방식으로 보수화(저우선) |

### 7.3 PDCA 정합

- `chatbot-network-error-fix`: 코드 해소 확인됨 → `/pdca archive`.
- `interactive-follow-up`(97%): pending 미배선 재점검 후 상태 정정.
- 유출 키 히스토리 정리(`git filter-repo`)는 **파괴적** — 팀 합의 후 별도 수행.

---

## 8. 보안 고려사항 (체크리스트)

- [ ] 입력 검증: PostgREST 이스케이프(S-2b), HTML allowlist(S-2e), 렌더 이스케이프(F-2a/b)
- [ ] 인증/인가: JWT 시크릿 강제(S-1b), 로그인 브루트포스(S-1c), CAPTCHA 1회용(S-3)
- [ ] 민감정보: board 익명화(S-2c), 주민번호 마스킹(S-2d), 키 히스토리(Wave 5)
- [ ] Rate limiting: 공유 스토어(S-2a)
- [ ] 전송/헤더: CORS 제한·보안 헤더·HSTS(S-3)

---

## 9. 테스트 계획

| 유형 | 대상 | 방법 |
|------|------|------|
| 단위(계산) | 골든 20+ 케이스 | `wage_calculator_cli.py` assert + 종료코드 |
| 단위(계산) | 음수/0/경계 입력 | 회귀 케이스(크래시 0 확인) |
| 통합(RAG) | 판례 인용 목록에 Pinecone 번호 노출 | 대표 질의 10건, 인용목록 문자열 검증 |
| 통합(보안) | PostgREST 이스케이프·익명화·rate-limit | `q="x,id.not.is.null"`, 주민번호 포함 게시글 |
| 통합(API) | 예외→503 일관, 스키마 | DB 실패 모킹 |
| 프론트 | XSS 페이로드 렌더, 타임아웃, a11y | 수동 + axe |
| 회귀 | 기존 32 CLI + 102 배치 크래시 0 | 전체 실행 |

---

## 10. 구현 순서 및 의존성

```
Wave 1(보안) ──┐
Wave 2(계산) ──┼─ 상호 독립, 병렬 가능
Wave 3(RAG)  ──┘
Wave 4(프론트) ── 일부 Wave 1(API 스키마)·Wave 3(sources)와 연동
Wave 5(정리) ── 전 웨이브 후 (죽은코드 판정은 Wave 3 배선 결정에 의존)
```

**웨이브 내 권장 순서**
1. Wave 1: 3.4→3.5(공개 노출면) → 3.1→3.2→3.3(인증) → 3.6→3.7
2. Wave 2: 4.1(값)→4.2(가드)→4.4(골든) → 4.3→4.5
3. Wave 3: 5.1(인용, 최우선)→5.2 → 5.3 → 5.4→5.5
4. Wave 4: 6.1→6.2(견고성) → 6.3(보안) → 6.4~6.7
5. Wave 5: 7.1→7.2→7.3

각 항목 완료 시 §9 해당 테스트로 검증 후 커밋. 웨이브 단위 PR 권장.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-07-02 | Wave 1~5 기술 설계 초안 (Wave 0 완료 반영) | DrunkenZealnut |
