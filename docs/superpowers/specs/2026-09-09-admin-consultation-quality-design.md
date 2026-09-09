# Admin 상담 답변 품질 조회 설계

## 1. 목적

`eval_consultation.py --live`로 측정한 상담 답변 품질 결과를 관리자 페이지에서
안전하게 확인한다. 관리자 페이지는 평가를 실행하지 않고, 서버 측에서 저장된 평가
실행 결과만 조회한다.

현재 평가기는 실행 결과를 로컬 JSON으로만 저장한다. Vercel 함수의 로컬 파일은
지속 저장소가 아니므로, 운영 조회용 결과는 Supabase의 관리자 전용 테이블에
저장한다.

## 2. 범위와 비범위

포함:

- 평가 CLI의 명시적 관리자 게시 옵션
- 평가 실행 요약과 사례별 결과의 Supabase 저장
- 관리자 JWT로 보호되는 평가 결과 조회 API
- `public/admin.html`의 `답변 품질` 화면
- 저장 실패, 실행 미완료, 라이브 미실행 상태 표시

제외:

- 브라우저에서 Live 평가를 실행하는 기능
- 일반 사용자에게 평가 결과를 노출하는 기능
- 상담 답변 생성 파이프라인의 동작 변경
- 전문가 수동 검토 입력·승인 워크플로
- 기존 대화·첨부·남용 API의 스키마 변경

## 3. 사용자 흐름

1. 운영자가 서버 자격증명이 있는 환경에서 `eval_consultation.py --live`를 실행한다.
2. 먼저 로컬 결과 JSON을 완성한 뒤 `--publish-admin`이 지정된 경우에만 평가 결과를
   `consultation_eval_runs`에 한 번 저장한다.
3. 운영자가 `/admin`에 로그인한다.
4. `답변 품질` 메뉴에서 최신 실행 요약을 본다.
5. 실행 목록에서 특정 실행을 선택하면 사례별 점수, 오류, 제한된 답변, 근거와
   실행 메타데이터를 확인한다.

`--publish-admin`은 `--live`와 함께 사용해야 한다. `--offline --publish-admin`은
CLI 오류(종료 코드 2)로 거부한다. Live 측정 자체는 기존처럼 순차 실행하며,
평가 중에는 파이프라인의 운영 대화 저장을 막고, 완료 후 평가 전용 테이블에만
명시적으로 저장한다.

## 4. 저장 모델

새 SQL 파일 `supabase_consultation_eval.sql`을 추가한다.

테이블 `public.consultation_eval_runs`:

| 컬럼 | 타입 | 제약/의미 |
|---|---|---|
| `id` | `uuid` | PK, `gen_random_uuid()` |
| `run_id` | `text` | NOT NULL, UNIQUE, CLI가 생성하는 실행 식별자 |
| `mode` | `text` | `live` 또는 `offline` |
| `status` | `text` | `completed`, `partial`, `failed`, `unexecuted` |
| `started_at` | `timestamptz` | 실행 시작 시각 |
| `finished_at` | `timestamptz` | 실행 종료 시각, 미완료면 NULL |
| `fixture_case_count` | `integer` | 전체 fixture 사례 수 |
| `evaluated_case_count` | `integer` | 실제 선택·실행 사례 수 |
| `summary` | `jsonb` | `aggregate_results` 결과 |
| `results` | `jsonb` | 사례별 평가 결과 배열 |
| `metadata` | `jsonb` | commit, fixture 경로/개수, Python 버전 등 |
| `created_at` | `timestamptz` | 저장 시각 |

`results`에는 기존 CLI 결과의 사례별 필드를 그대로 보존하되 저장 답변은 기존
3,000자 상한을 따른다. 운영 DB에 원문 전체 답변을 새로 저장하지 않는다.

RLS를 활성화하고 anon/authenticated 정책은 만들지 않는다. API와 게시 CLI는
기존 서버 측 Supabase 클라이언트를 사용한다. 관리자 JWT는 Supabase에 전달하지
않으며, 브라우저가 Supabase에 직접 접속하지 않는다.

인덱스:

- `created_at DESC`
- `run_id UNIQUE`
- `mode, status`

## 5. CLI 게시 인터페이스

기존 CLI에 다음 옵션을 추가한다.

```text
--publish-admin   live 결과를 관리자 평가 테이블에 저장
```

동작 계약:

- `--publish-admin` 단독 사용 또는 `--offline --publish-admin`은 CLI 오류 2
- `--live --publish-admin`은 평가 JSON을 먼저 저장한 후 DB 게시
- DB 미설정·게시 실패는 로컬 결과 파일을 보존하고 종료 코드 1
- 게시 성공 시 stdout에 `admin publish: PASS`와 `run_id`를 표시
- 게시하지 않은 실행은 기존 동작과 결과 형식을 유지
- 결과 게시 시 기존 평가용 config 복사본의 `supabase=None` 격리를 유지

게시 함수는 `publish_admin_run(report: dict, supabase) -> str` 경계를 갖고,
CLI 본문과 분리한다. 게시 payload의 키·타입을 검증한 뒤 단일 insert를 수행하며,
동일 `run_id` 재게시에는 중복 오류를 사용자에게 명확히 표시한다.

## 6. 관리자 API

기존 `require_admin`을 재사용한다.

### `GET /api/admin/evaluation-runs`

최근 실행 목록을 반환한다.

- 기본 20건, `limit`은 1~100으로 제한
- `mode`, `status` 선택 필터
- `created_at` 내림차순
- `results` 본문은 포함하지 않고 요약·메타데이터만 반환

응답:

```json
{
  "runs": [
    {
      "run_id": "eval_20260909T120000Z_abc123",
      "mode": "live",
      "status": "completed",
      "started_at": "2026-09-09T12:00:00+00:00",
      "finished_at": "2026-09-09T12:08:00+00:00",
      "fixture_case_count": 60,
      "evaluated_case_count": 60,
      "summary": {},
      "metadata": {}
    }
  ],
  "total": 1
}
```

### `GET /api/admin/evaluation-runs/{run_id}`

특정 실행의 요약과 사례별 결과를 반환한다. 없는 실행은 404, DB 오류는 503이다.

API는 답변 원문을 그대로 HTML에 삽입하지 않고, 프론트엔드가 text node로 렌더링할
수 있는 문자열 필드로 반환한다. 기존 관리자 API와 같은 인증·오류 형식을 따른다.

## 7. 관리자 화면

`public/admin.html`에 기존 대시보드/대화목록과 같은 수준의 세 번째 메뉴
`답변 품질`을 추가한다.

화면 구성:

- 상태 배너: `실행 없음`, `Live 미실행`, `완료`, `일부 실패`, `게시 실패`
- 최신 실행 지표 카드: 자동 합격률, 의도 정확도, 주제 정확도, 법조문 커버리지,
  고지율, 평균/P95 실행 시간
- 실행 목록: 실행 시각, 모드, 상태, 실행 사례 수
- 사례 표: 사례 ID, 분류, 자동 합격 여부, 주요 점수, pipeline 오류
- 사례 상세: 질문, 제한된 답변, 근거 유형, 계산/분석 관찰값, 오류
- 새로고침 버튼과 로딩/빈 상태/오류 상태

Live 결과가 없으면 숫자를 0으로 표시하지 않고 `측정 없음`으로 표시한다.
오프라인 검증 결과는 `구조 검증`으로 구분하고 실제 답변 품질 지표로 오인되지
않게 한다.

## 8. 오류·보안·운영 규칙

- 모든 조회 API는 관리자 JWT가 없으면 401을 반환한다.
- 결과 조회는 `run_id`를 URL-safe 문자열로 제한하고 Supabase 필터에 그대로
  구문을 주입하지 않는다.
- 대형 `results` 배열은 실행 상세 한 건에서만 읽으며, 목록 API에는 포함하지 않는다.
- DB 결과가 손상됐거나 summary가 비어도 페이지 전체가 깨지지 않고 `데이터 없음`을
  표시한다.
- 게시 CLI는 평가 중 기존 상담 저장을 수행하지 않는다.
- Live 실행과 게시 명령은 운영자가 명시적으로 호출해야 하며 Admin 화면에는
  실행 버튼을 두지 않는다.

## 9. 테스트 계획

- Python API 테스트: 인증 누락, 목록/상세 응답, 404/503, limit 상한, 결과 직렬화
- Python CLI 테스트: 옵션 조합, publish payload, Supabase insert 성공/실패,
  기존 파이프라인 Supabase 격리
- SQL 정적 검증: 컬럼·제약·RLS·정책 부재·인덱스
- JavaScript 테스트: 메뉴 전환, 요약 렌더링, 미실행/빈 상태, HTML escaping,
  상세 결과 렌더링
- 기존 관리자 로그인·통계·대화목록 테스트와 평가 하네스 회귀 테스트 유지

## 10. 단계적 출시

1. SQL을 Supabase에 적용하고 서버/CLI 환경변수를 확인한다.
2. 1건 Live 실행과 게시로 API·화면 연결을 검증한다.
3. 전체 60건 Live 실행 결과를 게시한다.
4. 관리자 화면에서 `미실행`과 실제 실행 결과를 구분하는지 확인한다.
5. 전문가 검토와 P0/P1 배포 게이트는 이 기능의 표시 완료와 별도로 진행한다.
