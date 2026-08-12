# 질문게시판 중복 정리 Design Document

> **Summary**: 중복 225건을 하드 삭제하는 일회성 스크립트(`dedupe_board.py`)와, 합성/테스트 대화가 공개 게시판에 도달하지 못하게 하는 4단 가드를 설계한다.
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-08-12
> **Status**: Draft
> **Planning Doc**: [board-duplicate-cleanup.plan.md](../../01-plan/features/board-duplicate-cleanup.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. **정리는 되돌릴 수 있게** — 하드 삭제를 선택했지만 백업 없는 삭제는 0건이어야 한다.
2. **재발 방지는 구조적으로** — "테스트 스크립트가 조심하기"에 의존하지 않는다. 새 테스트 스크립트를 아무 생각 없이 작성해도 공개 게시판에 새지 않아야 한다.
3. **실패는 시끄럽게** — 가드 오작동이 "게시판이 조용히 성장을 멈춤"으로 나타나면 안 된다. 판정은 **양성 검출(positive detection)** 로만 하고, 판단 불가 상태는 "실사용"으로 취급한다.
4. **기존 메커니즘 재사용** — 새 개념을 만들지 않는다. 공개 제외는 이미 `_PUBLIC_EXCLUDE_KEYS`가 3종을 처리하고 있으므로 4번째 키를 추가하는 것으로 끝낸다.

### 1.2 Design Principles

- **단일 초크포인트에 가드를 둔다** — 해설서 가드 G4(`_cap_by_book`)를 `format_pinecone_hits()` 진입부에 둔 것과 같은 이유. 호출부가 늘어도 새지 않는 지점을 고른다.
- **판정과 집행을 분리한다** — "이 대화는 합성인가"(판정, 3곳)와 "합성이면 숨긴다"(집행, 1곳)를 나눈다. 집행이 한 곳이므로 판정 로직이 늘어도 노출 규칙은 하나로 유지된다.
- **fail-open 유지** — 가드 내부 예외가 상담 저장을 막지 않는다. 기존 전 계층 규약을 그대로 따른다.
- **멱등** — 정리 스크립트를 두 번 돌려도 같은 결과. 이미 삭제된 id의 재삭제는 무해하다.

---

## 2. Architecture

### 2.1 두 갈래 작업

```
┌──────────────────────────────────────────────────────────────┐
│ ① 정리 (일회성)                                               │
│    dedupe_board.py  ──►  Supabase qa_conversations           │
│      dry-run → 백업 JSON → 배치 DELETE → 검증 → (고아세션)    │
│    463건 ─────────────────────────────────────────► 238건     │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ ② 재발 방지 (영구)                                            │
│    판정 3곳 ──► metadata.synthetic ──► 집행 1곳               │
│                                        _PUBLIC_EXCLUDE_KEYS   │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 재발 방지 — 판정/집행 데이터 흐름

```
[비웹 호출부]                    [웹 호출부]
benchmark_pipeline.py            POST /api/chat/stream
chatbot.py                              │
test_legal_cases_e2e.py                 ▼
      │                          _guard_chat_request(request, ...)
      │                                 │  G-B: 비프로덕션 요청 판정
      │                                 ▼
      │                          GuardContext(synthetic=True|False)
      │                                 │
      ▼                                 ▼
  process_question(query, session, config, guard_ctx=None) ──┐
                                                   guard_ctx ─┤
                                                              ▼
                              pipeline.py:2083  conv_metadata 조립
                                G-A: guard_ctx is None        → synthetic
                                G-B: guard_ctx.synthetic       → synthetic
                                                              │
                                                              ▼
                              storage.py::save_conversation(sb, record)
                                G-C: session_id 예약 접두사    → synthetic
                                                              │
                                                              ▼
                                        Supabase qa_conversations
                                                              │
                                                              ▼
                              api/index.py::_PUBLIC_EXCLUDE_KEYS
                                G-D: "synthetic" 포함 → 게시판 노출 차단
```

### 2.3 각 가드가 담당하는 실패 클래스

| 가드 | 위치 | 판정 근거 | 담당 클래스 | 실측 대상 |
|------|------|-----------|-------------|-----------|
| **G-A** | `pipeline.py:2083` 부근 | `guard_ctx is None` | 프로그램에서 직접 파이프라인을 부르는 모든 호출부 | `bench_*` 225, `test_*` 9, CLI |
| **G-B** | `api/index.py::_guard_chat_request` | 비프로덕션 요청 | HTTP로 로컬/preview 서버를 때리는 e2e 테스트 | hex12 중 32건 유형 |
| **G-C** | `storage.py::save_conversation` | `session_id` 예약 접두사 | 위 둘을 우회한 저장 (초크포인트 백스톱) | `cmp_*` 51, `verify_*` 등 |
| **G-D** | `api/index.py:360` | `metadata.synthetic` 존재 | **집행** — 목록·검색·상세 전 경로 | — |

**G-A가 광의 규칙이고 G-C는 백스톱이다.** G-A만으로 대부분이 잡히지만, `save_conversation()`이 `pipeline.py:2118` 단일 호출부를 갖는 유일한 초크포인트이므로 여기에도 판정을 남겨 둔다. 향후 파이프라인을 거치지 않는 저장 경로가 생겨도 접두사 규약을 지키는 한 새지 않는다.

---

## 3. FR-07 결정 — HTTP 테스트 트래픽 식별

Plan에서 Design으로 미룬 유일한 미결 항목이다.

### 3.1 문제

`test_e2e.py`·`test_e2e_20.py`는 `BASE_URL = "http://localhost:8000"`으로 **실제 서버를 HTTP로 호출**한다. 이때 세션 ID는 서버가 `app/models/session.py:130`에서 `uuid.uuid4().hex[:12]`로 발급하므로 실사용자와 **문자열상 구별이 불가능**하다. 실측에서 hex12 140건 중 32건이 합성 질문과 문구가 동일했던 것이 이 경로다.

### 3.2 채택안 — 양성 검출 복합 조건

```python
# api/index.py
_LOOPBACK = ("127.", "::1", "localhost")

def _is_synthetic_request(request: Request) -> bool:
    """비프로덕션 출처 요청인지 판정. 판단 불가 시 False(=실사용) 반환.

    양성 검출만 한다 — '프로덕션임을 증명하지 못하면 합성' 방식은
    환경변수 하나가 빠졌을 때 게시판이 조용히 얼어붙는다.
    """
    try:
        env = os.environ.get("VERCEL_ENV")
        if env and env != "production":
            return True                      # preview / development 배포
        ip = _client_ip(request)
        return any(ip.startswith(p) for p in _LOOPBACK)
    except Exception:
        return False                          # 판정 실패 → 실사용 취급
```

`_guard_chat_request()`가 `GuardContext(synthetic=_is_synthetic_request(request))`로 결과를 실어 보낸다.

**진리표**

| 상황 | `VERCEL_ENV` | client IP | 판정 | 기대 |
|------|--------------|-----------|------|------|
| Vercel 프로덕션 실사용자 | `production` | 공인 IP | 실사용 | ✅ |
| Vercel 프로덕션, env 누락(설정사고) | 없음 | 공인 IP | 실사용 | ✅ **게시판 안 멈춤** |
| Vercel preview 배포 | `preview` | 공인 IP | 합성 | ✅ |
| 로컬 `uvicorn` + `test_e2e.py` | 없음 | `127.0.0.1` | 합성 | ✅ |
| 로컬 `uvicorn` 수동 테스트 | 없음 | `127.0.0.1` | 합성 | ✅ (의도된 동작) |

### 3.3 기각한 대안

| 대안 | 기각 사유 |
|------|-----------|
| **`VERCEL_ENV != "production"` 단독 (음성 검출)** | 프로덕션에서 `VERCEL_ENV`가 누락되면 **모든 실사용 대화가 합성으로 찍혀 게시판이 조용히 멈춘다.** CLAUDE.md가 반복 경고한 "실패가 조용하다" 패턴 — Vercel이 자동 주입하는 값이라 확률은 낮지만 실패 비용이 비대칭적으로 크다. §3.2는 이 조건을 **보조**로만 쓴다 |
| **테스트 전용 헤더 단독 (`X-Test-Run: 1`)** | 외부에서 임의로 켤 수 있다. 악용해도 "자기 글이 게시판에서 숨겨질 뿐"이라 보안 문제는 아니지만, 신뢰할 수 없는 입력을 판정 근거로 삼는 설계는 남기지 않는다 |
| **RFC1918 사설 IP까지 합성 처리** | `uvicorn --host 0.0.0.0` + LAN 접속 케이스를 추가로 커버하지만, 저장소의 e2e 스크립트는 전부 `localhost`라 실익이 없다. 반면 프록시 구성에 따라 `x-forwarded-for[0]`에 사설 IP가 실릴 경우 **실사용자 오탐**이 생긴다. 오탐 비용 > 커버리지 이득 |
| **테스트 스크립트가 스스로 예약 접두사 세션을 쓰도록 규약화** | HTTP 경로에서는 서버가 세션을 발급하므로 클라이언트가 접두사를 정할 수 없다. `session_id`를 클라이언트가 지정할 수는 있으나(`_SESSION_ID_RE` 통과 시), 규약 준수를 사람에게 의존하는 방식이라 목표 2에 위배 |

### 3.4 남는 구멍 (의도된 수용)

- **프로덕션 URL에 직접 붙는 e2e 테스트**는 잡히지 않는다. 현재 저장소에 그런 스크립트는 없다.
- **G-B는 신규 저장분에만 적용**된다. 기존 463건 중 잔존분의 소급 표시는 하지 않는다(Plan §7.2).

---

## 4. 재발 방지 상세 설계

### 4.1 G-A — 비웹 호출부 판정 (`app/core/pipeline.py`)

`conv_metadata` 조립부(현재 2083행)에 기존 3종과 같은 형태로 추가한다.

```python
conv_metadata: dict = {"has_attachments": has_attachments}
# 웹 요청이 아닌 호출부(벤치마크·CLI·테스트)의 대화는 저장하되 공개 게시판에서
# 제외한다. guard_ctx는 웹 엔드포인트만 넘기므로 None이면 비웹 호출이다
# (CLAUDE.md의 guard_ctx 계약). api/index.py::_PUBLIC_EXCLUDE_KEYS가 이 키를 읽는다.
if guard_ctx is None or getattr(guard_ctx, "synthetic", False):
    conv_metadata["synthetic"] = True
```

`getattr` 폴백을 쓰는 이유: `GuardContext`를 직접 구성하는 기존 테스트(`test_abuse_guard.py`)가 새 필드를 모른 채 만든 인스턴스를 넘겨도 깨지지 않게 한다.

**핵심 계약**: `guard_ctx is None ⟺ 비웹 호출`. 이는 이미 CLAUDE.md가 명문화한 계약이며, `_guard_chat_request()`는 `ABUSE_GUARD_MODE=off`에서도 항상 `GuardContext`를 만들어 반환하므로(모드 값만 `"off"`가 됨) 웹 경로에서 `None`이 되는 일은 없다.

### 4.2 G-B — 요청 환경 판정 (`api/index.py`, `app/core/abuse_guard.py`)

```python
# app/core/abuse_guard.py — GuardContext에 필드 추가 (기본값 있어 하위호환)
@dataclass
class GuardContext:
    subject_key: str
    session_id: str = ""
    injection_mode: str = "monitor"
    scope_mode: str = "monitor"
    synthetic: bool = False      # 비프로덕션 출처 요청 (board-duplicate-cleanup FR-07)
```

`_guard_chat_request()` 말미의 `ctx` 생성부에 `synthetic=_is_synthetic_request(request)`를 추가한다. 판정은 §3.2 함수.

**가드 순서에 영향 없음** — `synthetic` 판정은 차단 여부와 무관하고 예외를 던지지 않으므로, 기존 1~3단(입력 검증 → rate limit → 쿼터) 순서를 건드리지 않는다.

### 4.3 G-C — 예약 접두사 백스톱 (`app/core/storage.py`)

```python
# 직접 세션 ID를 만드는 호출부(벤치마크·비교 실행·검증 스크립트)를 위한 규약.
# save_conversation()은 pipeline.py:2118 단일 호출부를 갖는 초크포인트라
# 여기에 두면 향후 저장 경로가 늘어도 가드가 새지 않는다.
SYNTHETIC_SESSION_PREFIXES = ("bench_", "test_", "cmp_", "verify_", "eval_")


def save_conversation(sb, record: ConversationRecord) -> str | None:
    conv_id = str(uuid.uuid4())
    metadata = dict(record.metadata or {})
    try:
        if (record.session_id or "").startswith(SYNTHETIC_SESSION_PREFIXES):
            metadata["synthetic"] = True
    except Exception:      # 가드 실패가 저장을 막지 않는다 (fail-open)
        pass
    ...insert(..., "metadata": metadata)
```

`record.metadata`를 **복사해서** 수정한다 — 호출부의 `conv_metadata` 딕셔너리를 제자리 변경하면 파이프라인이 이후에 그 값을 참조할 때 예상 밖 상태가 된다.

### 4.4 G-D — 집행 (`api/index.py:360`)

```python
_PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated", "textbook", "synthetic")
```

한 줄 변경으로 `_apply_guard_filter()`(PostgREST 필터)와 `_is_public_excluded()`(Python 후처리) **양쪽에 동시 적용**된다. `_fetch_qa_public()`의 이중 방어(필터 실패 시 무필터 재조회 + Python 후처리)를 그대로 물려받는다.

**영향 범위 확인**

| 호출부 | 적용 여부 |
|--------|-----------|
| `board_recent` | ✅ `_fetch_qa_public` 경유 |
| `board_categories` | ✅ 동일 |
| `board_search` (qa 부분) | ✅ 동일 |
| `board_detail` | ✅ `_is_public_excluded` 직접 호출 |
| `board_search` (board_posts 부분) | ➖ 미적용 — **정상**. `board_posts`에는 `metadata` 컬럼이 없어 필터를 걸면 PostgREST 400이 `try/except`에 삼켜져 사용자 글이 통째로 사라진다(CLAUDE.md 명시 금지사항) |
| `/api/admin/*` | ➖ 미적용 — **정상**. 관리자 화면은 합성 대화도 봐야 한다 |

### 4.5 소급 적용 없음

`metadata.synthetic`은 신규 저장분에만 붙는다. 기존 463건에는 이 키가 없으므로 G-D 추가가 과거 데이터를 숨기지 않는다. 정리 후 남는 238건(그중 105건이 `bench_*` 소속)은 그대로 노출된다 — Plan §7.2의 의도된 수용이며, `session_id`는 공개 응답 스키마에 없어 사용자에게 보이지 않는다.

---

## 5. 정리 스크립트 설계 — `dedupe_board.py`

### 5.1 CLI 계약

```bash
python3 dedupe_board.py                          # dry-run (기본) — 쓰기 0
python3 dedupe_board.py --apply                  # 백업 후 실제 삭제
python3 dedupe_board.py --apply --purge-sessions # + 고아 세션 정리 (옵트인)
python3 dedupe_board.py --backup-dir ./backups   # 백업 경로 지정 (기본: 현재 디렉터리)
```

`--apply` 없이는 어떤 쓰기도 발생하지 않는다. 프로젝트의 `sync_overlap_precedents.py --dry-run` 관례를 따른다.

### 5.2 실행 흐름

```
① 환경 로드      load_dotenv(override=True)          ← ~/.zshrc 낡은 키 덮어쓰기 방지
② 전량 조회      range(off, off+999) 페이징            ← 1000건 한계 회피, 470건이라 2회
③ 공개 필터      _PUBLIC_EXCLUDE_KEYS 제외 → 463건
④ 그룹핑         _norm_question(q) 키 → 238 그룹
⑤ 대표 선정      그룹별 (created_at, id) 최댓값 1건 유지
⑥ 요약 출력      삭제 225 / 유지 238 / 카테고리 분포 / 카테고리 불일치 그룹 목록
⑦ [dry-run] 종료
   [apply]
   ⑦-1 백업      backup_board_dedupe_{YYYYMMDD_HHMMSS}.json 쓰기
   ⑦-2 검증      파일 존재 + 레코드 수 == 삭제 대상 수  → 불일치 시 중단
   ⑦-3 삭제      50건 배치 DELETE, 배치마다 진행 로그
   ⑦-4 재조회    공개 대상 == 238 && 중복 그룹 == 0  → 불일치 시 경고 종료
   ⑦-5 [옵트인]  고아 세션 정리 (§5.6)
```

### 5.3 정규화 (FR-01)

```python
def _norm_question(t: str) -> str:
    t = unicodedata.normalize("NFC", t or "").lower()
    return re.sub(r"[^\w가-힣]", "", t)
```

| 단계 | 근거 |
|------|------|
| `NFC` 선행 | macOS·클라이언트에 따라 한글이 NFD로 들어오면 완성형과 다른 키가 된다. `pinecone_upload_legal.py`가 이 누락으로 474벡터를 덮어쓴 전례가 있다 |
| `lower()` | 영문 혼용 질문 |
| `[^\w가-힣]` 제거 | 공백·줄바꿈·구두점·이모지 차이 흡수. **실측상 완전일치(239) 대비 1건만 추가 병합**되므로 과병합 위험이 낮음을 확인 |

`\w`가 유니코드 모드에서 한글을 이미 포함하므로 `가-힣`은 중복이지만, 의도를 명시하는 방어적 표기로 유지한다.

### 5.4 대표 선정 (동률 처리 포함)

```python
group.sort(key=lambda r: (r["created_at"], r["id"]))
keep, drop = group[-1], group[:-1]
```

`created_at`이 동일한 경우 `id` 사전순 최댓값을 남긴다 → **재실행 시 같은 결과**(멱등성 확보). 카테고리가 갈리는 3개 그룹에서는 최신 항목의 카테고리가 자동으로 채택되며, dry-run이 해당 그룹을 별도 섹션으로 출력해 실행 전 확인할 수 있게 한다.

### 5.5 백업 스키마

```json
{
  "created_at": "2026-08-12T…",
  "reason": "board-duplicate-cleanup FR-02",
  "norm_rule": "NFC+lower+strip_non_word",
  "kept_count": 238,
  "conversations": [
    {"id": "…", "session_id": "…", "category": "…", "question_text": "…",
     "answer_text": "…", "calculation_types": [], "metadata": {}, "created_at": "…"}
  ],
  "sessions": [ {"id": "…", "session_data": {}, "created_at": "…", "updated_at": "…"} ]
}
```

`id`를 포함하므로 원본 UUID까지 복원할 수 있다. `sessions`는 `--purge-sessions` 사용 시에만 채운다.

**복구 절차** (문서화만, 스크립트 미구현):
1. `sessions` 먼저 삽입 (FK 선행) — 또는 `storage.ensure_session()` 호출
2. `conversations`를 배치 삽입

### 5.6 고아 세션 정리 — CASCADE 위험

> ⚠️ **`qa_conversations.session_id`는 `ON DELETE CASCADE`다.** 세션 행을 지우면 그 세션의 **남은 대화까지 함께 사라진다.**

실제 위험 사례: `bench_*` 세션 하나가 대화 4건을 갖고 그중 3건이 중복 삭제 대상, 1건이 유지 대상일 수 있다. 세션을 무심코 지우면 **유지하기로 한 1건이 CASCADE로 증발한다.**

따라서 고아 세션 정리는:

1. **기본 비활성** — `--purge-sessions` 명시 필요
2. 대상은 "이번 삭제로 영향받은 `session_id`" 로 한정 (전체 고아 스캔 금지 — 불필요한 폭발 반경)
3. 삭제 **직전** 세션별로 `count(qa_conversations where session_id = s)` 를 **재조회**해 `0`인 것만 삭제
4. 세션 행을 백업 JSON에 먼저 기록

`supabase_retention_purge.sql:166-168`의 기존 고아 판정과 같은 조건이지만, 위 3번의 즉시 재확인이 이 스크립트만의 추가 안전장치다.

### 5.7 배치 삭제 파라미터

| 항목 | 값 | 근거 |
|------|-----|------|
| 배치 크기 | 50 | UUID 36자 × 50 ≈ 1.9KB — PostgREST 쿼리스트링 길이 여유 확보 (225건 일괄 시 8.3KB로 프록시 한계에 근접) |
| API | `sb.table("qa_conversations").delete().in_("id", batch).execute()` | |
| **반영 행 수 확인** | `len(res.data)` 이 0이면 `RLSBlocked` 예외 | **§5.8 참조 — 필수** |
| 실패 처리 | 해당 배치에서 중단, 진행분·잔여분 리포트 후 비정상 종료 | 부분 삭제 상태를 숨기지 않는다 |
| 재실행 | 이미 삭제된 id의 DELETE는 0행 영향 → 무해 | 멱등 |

### 5.8 ⚠️ RLS가 DELETE를 무성 차단한다 — 실행 중 발견 (2026-08-12)

`--apply` 첫 실행에서 **삭제가 0건 반영됐다.** 스크립트는 예외 없이 "225/225 삭제"를 출력했고, 검증 단계(⑦-4)만이 이를 잡아냈다.

**원인**: `qa_conversations`의 RLS 정책은 anon에 대해 `INSERT`·`SELECT`만 부여돼 있다(`supabase_schema.sql:51-52`). DELETE 정책이 없으면 PostgreSQL RLS는 **권한 오류가 아니라 "일치하는 행 0개"로 처리**하므로, PostgREST가 200 OK + 빈 배열을 반환한다. 예외 기반 오류 처리로는 절대 감지되지 않는다.

```
supabase_schema.sql:51  CREATE POLICY "Allow anon insert conversations" … FOR INSERT
supabase_schema.sql:52  CREATE POLICY "Allow anon select conversations" … FOR SELECT
                        ← FOR DELETE 정책 없음
```

`.env`의 `SUPABASE_KEY`는 `sb_publishable_…` 형식(anon/publishable)이라 RLS 적용 대상이다. 저장소에 `service_role` 키는 없다.

**설계 반영**

1. `_delete_batches()`가 배치마다 `len(res.data)`를 확인하고 0이면 `RLSBlocked`를 던진다. "성공했다고 보고하고 아무것도 안 하는" 실패 모드를 제거한다.
2. `main()`이 `SUPABASE_SERVICE_ROLE_KEY`(또는 `SUPABASE_SERVICE_KEY`)를 우선 사용하고, 없으면 `--apply` 진입 시 경고한다.
3. `RLSBlocked` 포착 시 `_emit_sql()`이 `dedupe_board_{stamp}.sql`을 생성한다 — Supabase SQL Editor는 `postgres` 역할로 실행돼 RLS를 우회하므로, **영구적인 권한 확대 없이** 일회성 정리를 끝낼 수 있다.

**기각한 대안**: anon에 DELETE 정책 부여. 일회성 정리를 위해 상시 삭제 권한을 여는 것은 비대칭적이다 — 키가 유출되면 상담 이력 전체가 삭제 가능해진다. `abuse_events`류에 정책을 부여하지 않는 기존 판단(CLAUDE.md)과 같은 이유다.

**실행 경로 (택일)**

| 경로 | 작업 | 영구 권한 변경 |
|------|------|:--------------:|
| ① SQL Editor | 생성된 `.sql`을 Supabase 대시보드에서 실행 | 없음 |
| ② service_role 키 | `.env`에 `SUPABASE_SERVICE_ROLE_KEY` 추가 후 `--apply` 재실행 | 없음(로컬 비밀만 추가) |

---

## 6. 데이터 모델

### 6.1 `metadata` 키 계약 (확장 후)

| 키 | 타입 | 설정 위치 | 공개 제외 | 도입 |
|----|------|-----------|:---------:|------|
| `has_attachments` | bool | `pipeline.py` | ❌ | file-attachment |
| `guard_flag` | str | `pipeline.py` | ✅ | chatbot-security FR-09 |
| `truncated` | bool | `pipeline.py` | ✅ | llm-fallback-hardening FR-02 |
| `textbook` | bool | `pipeline.py` | ✅ | textbook-corpus-embedding G6 |
| `llm` | dict | `pipeline.py` | ❌ | llm-fallback-hardening FR-10 |
| **`synthetic`** | **bool** | **`pipeline.py` + `storage.py`** | **✅** | **본 사이클 FR-05/07** |

### 6.2 스키마 변경

**없음.** `metadata`는 JSONB이므로 DDL이 필요 없다. Supabase 마이그레이션 파일 추가 불요.

---

## 7. 테스트 설계 (FR-08)

`test_offline_units.py`에 함수 4개 추가. API 키·네트워크 불요 — CI(`.github/workflows/tests.yml`)에서 그대로 돈다.

| ID | 함수 | 검증 내용 |
|----|------|-----------|
| **D1** | `test_dedupe_normalization` | `"주휴수당이 뭔가요?"` / `" 주휴수당이  뭔가요 "` / `"주휴수당이뭔가요"` / NFD 분해 문자열이 **같은 키**로 묶인다. `"주휴수당"` 과 `"연차수당"` 은 **다른 키** |
| **D2** | `test_dedupe_representative` | 동일 질문 3건(`created_at` 상이) → 최신 1건 유지. `created_at` 동률 2건 → `id` 사전순 최댓값 유지, **2회 호출 시 동일 결과**(멱등) |
| **D3** | `test_synthetic_prefix_guard` | `save_conversation`의 접두사 판정 — `bench_1`·`test_x`·`cmp_o3_1` → `synthetic` 부착 / `a1b2c3d4e5f6`(hex12) → **미부착**(오탐 0) / 원본 `record.metadata` 딕셔너리가 **변형되지 않음** |
| **D4** | `test_public_exclude_keys` | `_PUBLIC_EXCLUDE_KEYS`에 4종 전부 존재. `_is_public_excluded({"synthetic": True})` → `True`, `{"has_attachments": True}` → `False` |

**D3 구현 메모**: `save_conversation`은 Supabase 클라이언트를 요구하므로, 접두사 판정만 `_is_synthetic_session(session_id)` 순수 함수로 분리해 테스트한다. 부착 로직은 그 함수를 호출한다.

**기존 테스트 영향 — 사전 확인 완료 (2026-08-12)**

`test_abuse_guard.py:541`·`test_llm_fallback.py:208`이 `pipeline.save_conversation`을 몽키패치하고 `GuardContext`를 직접 구성한다. 실제 코드를 확인한 결과:

| 확인 항목 | 결과 |
|-----------|------|
| `GuardContext` 생성자 호환 | ✅ `synthetic`은 기본값 필드 → `GuardContext(subject_key=..., injection_mode=..., scope_mode=...)` 그대로 동작 |
| metadata 키 집합 **완전 일치** 단언 존재 여부 | ✅ **없음** — 양쪽 다 `meta.get("truncated")` · `"guard_flag" not in meta` 같은 **부분 검사**만 한다 |
| `test_llm_fallback.py:219`가 `guard_ctx` 없이 호출 | ⚠️ G-A가 발동해 `synthetic: True`가 새로 붙지만, 단언 대상이 `truncated`·`llm`뿐이라 **통과** |
| 몽키패치된 저장 함수가 G-C를 우회 | ✅ 정상 — G-C는 실제 `storage.save_conversation`에만 있으므로 기존 단언에 영향 없음 |

→ **기존 테스트 수정 불필요.** §10 체크리스트 1번은 확인 완료 상태로 진입한다.

---

## 8. 배포·검증 순서

> **재발 방지를 먼저 배포한다.** 순서가 바뀌면 정리 완료 시점부터 가드 배포 시점까지의 벤치마크 실행이 다시 오염을 만든다 (Plan §7.3).

```
1. 코드 변경 (G-A~G-D + 테스트) 커밋 → main 푸시 → Vercel 자동 배포
2. 양성 검증 ①  프로덕션에서 실제 질문 1건 전송
                → 게시판 목록에 나타나는지 확인          (오탐 0 확인)
3. 양성 검증 ②  로컬에서 benchmark_pipeline.py 소수 케이스 실행
                → 게시판 건수 불변 확인                   (가드 작동 확인)
4. dedupe_board.py                 (dry-run: 225/238 확인)
5. dedupe_board.py --apply         (백업 → 삭제 → 검증)
6. 최종 확인    게시판 1~5페이지 육안 + 카테고리 14종 잔존
```

**2번을 생략하지 말 것.** 가드는 fail-open이라 조용히 오작동한다 — chatbot-security 배포 때 "쿼터 양성 검증 필수"였던 것과 같은 이유다. G-B가 오탐이면 프로덕션 대화가 게시판에 영영 올라오지 않는데, 아무 에러도 나지 않는다.

---

## 9. 파일별 변경 명세

| 파일 | 변경 | 규모 |
|------|------|------|
| `dedupe_board.py` | **신규** — §5 전체 | ~200줄 |
| `app/core/storage.py` | `SYNTHETIC_SESSION_PREFIXES` + `_is_synthetic_session()` + `save_conversation()` 스탬프 | ~15줄 |
| `app/core/pipeline.py` | `conv_metadata` 조립부에 G-A 3줄 (2083행 부근) | ~5줄 |
| `app/core/abuse_guard.py` | `GuardContext.synthetic` 필드 | 1줄 |
| `api/index.py` | `_is_synthetic_request()` + `ctx` 생성부 인자 + `_PUBLIC_EXCLUDE_KEYS` 1키 | ~15줄 |
| `test_offline_units.py` | D1~D4 + `main()` 등록 | ~60줄 |
| `CLAUDE.md` | `metadata` 키 계약 · 가드 위치 · 배포 순서 규약 기록 | ~10줄 |

**Vercel 주의**: 변경 파일이 전부 기존 추적 파일이라 신규 미추적 import는 없다. `dedupe_board.py`는 런타임에 import되지 않는 운영 스크립트다.

---

## 10. 구현 체크리스트

- [x] ~~`test_abuse_guard.py` / `test_llm_fallback.py`가 저장 metadata를 **완전 일치**로 단언하는지 확인~~ → **확인 완료: 부분 검사만 하므로 수정 불필요** (§7 표)
- [ ] `.gitignore`에 `backup_board_dedupe_*.json` 추가 — **현재 `.gitignore`에 이를 덮는 패턴이 없음을 확인함**(`test_*.json`·`benchmark_*.json`은 있으나 `backup_*`은 없다). 백업 파일에는 상담 원문(개인정보)이 그대로 들어간다
- [ ] `_is_synthetic_request()`를 `_guard_chat_request()` **내부**에서 호출 (3개 채팅 경로가 모두 이 함수를 거치므로 한 곳이면 충분)
- [ ] `save_conversation()`에서 `record.metadata` 원본 비변형 (`dict()` 복사)
- [ ] `dedupe_board.py`에 `load_dotenv(override=True)` — 로컬 환경변수 덮어쓰기 함정 회피
- [ ] 백업 파일 쓰기 실패 시 삭제 진입 금지 (예외 전파, `try/except pass` 금지)
- [ ] `--purge-sessions`의 삭제 직전 잔여 대화 수 재확인 (CASCADE 방어)
- [ ] dry-run 출력에 카테고리 불일치 3그룹 별도 표시

---

## 11. Risks (Design 단계 추가분)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **고아 세션 CASCADE로 유지 대상이 함께 삭제** | **High** | `--purge-sessions` 기본 비활성 + 삭제 직전 잔여 대화 수 재조회(§5.6). 이 사이클에서는 생략해도 무방 |
| G-B 오탐으로 프로덕션 대화가 영구히 게시판 미노출 | High | 양성 검출 방식 채택(§3.2)으로 확률 최소화 + 배포 후 양성 검증 2단계 의무화(§8) |
| `x-forwarded-for` 위조로 자기 대화를 합성 처리 | Low | 자기 글이 게시판에서 숨겨질 뿐 — 가드 우회·권한 상승 없음. 수용 |
| ~~기존 테스트가 metadata 키 집합 완전 일치를 단언해 깨짐~~ | — | **해소** — 사전 확인 결과 부분 검사만 한다(§7) |
| 백업 JSON에 개인정보 포함 | Medium | 상담 원문이므로 당연히 포함된다. **`.gitignore`에 `backup_board_dedupe_*.json` 추가 필수** — 현재 이를 덮는 패턴이 없음을 확인했다. 커밋되면 개인정보가 저장소 히스토리에 영구 기록된다 |

---

## 12. Approvals

| Role | Name | Date | Status |
|------|------|------|--------|
| Author | Claude | 2026-08-12 | Draft |
| Reviewer | — | — | Pending |
