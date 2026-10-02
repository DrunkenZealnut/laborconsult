# llm-fallback-alert Design Document

> **Planning Doc**: [llm-fallback-alert.plan.md](llm-fallback-alert.plan.md) · **Date**: 2026-10-02 · **Status**: Implemented (PR #89, 2026-10-02)

확정 결정: 채널 = **GitHub Actions 실패 메일** · 임계 = **최근 실사용 3건 연속 저하** · 주기 = **6시간**

## 1. 구성

```
.github/workflows/llm-fallback-alert.yml  (cron 0 */6 * * * + workflow_dispatch)
  └─ python check_llm_fallback.py --window 3
       ├─ fetch_recent(db, window)     qa_conversations(created_at desc) 페이지 조회 — anon 키
       ├─ judge(rows, window=3) -> Verdict   ← 순수 함수, 오프라인 테스트 대상
       └─ exit 0 정상/판정불가 · 1 알림 · 2 감시 실패
```

## 2. 판정 (`judge`)

```python
@dataclass
class Verdict:
    status: str          # "ok" | "alert" | "insufficient"
    considered: list     # 판정에 쓴 실사용 행(최근 → 과거, 최대 window)
    reasons: list[str]   # 각 행의 저하 사유

def degraded(llm: dict) -> list[str]:
    # fallback(시도 2개 이상) · empty(빈 응답 제공자) · intent_provider(의도분석 교차벤더)
```

- 대상: `metadata.synthetic`이 참이 아니고 `metadata.llm`이 있는 행만. 최신순 정렬 후 앞에서 `window`개.
- `len(considered) < window` → `insufficient`(exit 0). 표본 부족은 장애 신호가 아니다.
- 전부 저하 → `alert`. 하나라도 정상 → `ok`.
- **"Claude가 아님"으로 판정하지 않는다.** 관리자 화면에서 1순위를 OpenAI로 두면 `provider=OpenAI, attempts=['OpenAI']`가 정상이다. 저하는 "1순위가 실패해 다음으로 넘어갔다"(`fallback`)이다.
- `truncated`는 저하로 보지 않는다 — 긴 답변의 정상 절단·네트워크 끊김이 섞여 있고 별도 고지·게시판 제외가 이미 있다.

## 3. 조회

- `make_supabase_client(postgrest_timeout=15)` — `SUPABASE_KEY`(anon). service-role은 `qa_conversations` 권한이 없다(실측 42501).
- `select("id,created_at,metadata").order("created_at", desc=True).range(...)`를 **50행 페이지로 이어 조회**해 실사용 행이 `window`개 모이면 멈춘다(최대 20페이지). 고정 `limit(50)` 한 번이면 벤치마크가 쌓은 합성 행이 창을 채워 실사용 폴백이 밀려나 "판정 불가"로 통과한다(CodeRabbit PR #89). 기록이 바닥났을 때만 표본 부족이다.
- 클라이언트 없음·예외 → **exit 2**(FR-04). 감시가 fail-open이면 감시가 죽은 것도 조용해진다.

## 4. 출력

- stdout + `$GITHUB_STEP_SUMMARY`(있으면): 판정, 최근 행 표(시각 KST·provider·model·attempts·사유).
- alert 시 첫 줄 `::error::` 어노테이션 — 실패 메일 본문에 원인이 바로 보이도록.
- 대화 본문(question/answer)은 **읽지도 출력하지도 않는다** — Actions 로그는 저장소 협업자에게 보인다.

## 5. 워크플로

- `permissions: contents: read`, `timeout-minutes: 5`, `concurrency` 그룹.
- 설치는 `pip install supabase python-dotenv` 최소 셋(requirements 전체는 수 분 소요) — 스크립트는 `app.core.storage` 하나만 import하고 그 모듈이 FastAPI·pipeline에 의존하지 않는다(CLAUDE.md 공개 게시판 단일 출처 절).
- Secret: `SUPABASE_URL`, `SUPABASE_KEY`.

## 6. Test Plan — `test_llm_fallback_alert.py` (오프라인)

| ID | 검사 |
|---|---|
| A-1 | 실사용 3건 모두 fallback → alert |
| A-2 | 최근 1건이라도 정상 → ok (그 뒤 과거가 전부 저하여도) |
| A-3 | 합성·llm 없는 행은 건너뛰고 실사용 3건을 모은다 |
| A-4 | 실사용 2건뿐 → insufficient |
| A-5 | OpenAI 1순위 정상(`attempts=['OpenAI']`) → 저하 아님 |
| A-6 | empty·intent_provider도 저하 / truncated는 아님 |
| A-7 | **8월 실측 재현**: 8-21 22:29·22:35·8-22 12:14 실사용 3건 → alert |
| A-8 | 조회 실패 → exit 2 |

CI `offline-tests`에 단계 추가.
