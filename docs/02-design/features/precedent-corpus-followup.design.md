# precedent-corpus-followup Design

> Plan: `docs/01-plan/features/precedent-corpus-followup.plan.md`
> 작성일: 2026-08-09
> 선행: `docs/archive/2026-08/precedent-corpus-expansion/` (파이프라인 3종을 그대로 재사용)

## 1. 설계 개요

세 트랙이 공유하는 원칙: **선행 사이클에서 검증된 파이프라인을 최대 재사용**하고,
신규 코드는 (a) 명시 대상 수집 모드, (b) ctx 구벡터 정리 스크립트, (c) NFD 수정
세 가지로 한정한다.

```text
Track B (핵심):
  sync_overlap_precedents.py --emit-targets        [신규] 겹침 대상 재계산
        │  교재 인용 ∩ 기존 코퍼스 → output_판례_보강/_겹침대상.csv (사건번호,법원,게시글ID)
        ▼
  fetch_court_precedents.py --cases _겹침대상.csv  [--cases 모드 추가]
        │  L2 중복검사 생략(명시 대상), _progress.json 재개는 유지
        ▼
  enrich_court_precedents.py                       [무수정] 신규 수집분 자동 태깅
        ▼
  pinecone_upload_court_precedents.py              [무수정] precedent_{사건번호} → laborlaw-v2
        ▼
  sync_overlap_precedents.py --delete-ctx          [신규] 수집 성공분의 ctx 구벡터 삭제
        │  index.list(prefix=f"ctx_precedent_{게시글ID}_") → 라이브 ID → delete(ids=...)
        ▼
  build_bm25_corpus.py → data/bm25_corpus.json.gz  [커밋 필수]

Track A: pinecone_upload_legal.py · upload_new_precedents.py NFD 수정 + T14
Track C: portal.scourt.go.kr 접근성 스파이크 (구현 없음, 판정 기록만)
```

---

## 2. Track B — 유실 139건 복구 + 겹침 266건 태깅 통일

### 2.1 대상 산출 — `sync_overlap_precedents.py --emit-targets`

겹침 266건 목록의 원천이 세션 스크래치(휘발)였으므로 **리포 스크립트가 재계산**한다:

```python
book_cases   = 교재 본문 인용 추출        # SPACED_CASE_RE + OCR_FIXES (enrich 모듈 재사용)
corpus_cases = {파일별 대표 사건번호: (파일명, 게시글ID|None)}
               # extract_representative_case_no 재사용, output_법원 노동판례 전체
targets      = book_cases ∩ corpus_cases   # ≈266건
```

출력 `output_판례_보강/_겹침대상.csv`: `사건번호,법원,게시글ID` —
- `법원`: 사건부호로 유추(`헌` 포함 → 헌법재판소, 그 외 대법원). `resolve_target`이
  사건부호 우선이라 이 컬럼은 참고용.
- `게시글ID`: 파일명 선두 숫자(nodong 크롤 출신 127건). 사건번호 선두 파일(139건,
  `upload_new_precedents` 출신)은 빈 값 — **빈 값 = ctx 벡터 없음 = 삭제 대상 아님**.
  이 컬럼이 §2.3 삭제의 유일한 근거이므로 여기서 함께 산출한다(매핑 로직 단일 소유).

교재 원본(`output_노동법교재/`, untracked)이 필요한 **로컬 전용 작업**이다 —
스크립트는 커밋하되 실행은 이 머신에서만 가능함을 docstring에 명시.

### 2.2 수집 — `fetch_court_precedents.py --cases <csv>`

| 동작 | 기본 모드 | `--cases` 모드 |
|------|-----------|----------------|
| 입력 | `누락_판례목록.csv` (601건) | 지정 CSV |
| L2 기존 코퍼스 대조 | 수행 (있으면 스킵) | **생략** — 있는 걸 알고 재수집하는 모드 |
| `_progress.json` 재개 | 유지 | 유지 (fetched/not_found에 누적) |
| 그 외(정확일치 게이트·라우팅·OCR 보정·재시도) | 동일 | 동일 |

구현: `INPUT_CSV`를 인자로 교체 + `skip_l2` 불리언 하나. CSV에 `게시글ID` 등
추가 컬럼이 있어도 무시(사건번호·법원만 읽음 — 기존 파서 재사용).

이미 `_progress.json.fetched`에 500건, `not_found`에 98건이 있고 겹침 266건은
어느 쪽에도 없으므로 재개 로직과 충돌하지 않는다.

### 2.3 ctx 구벡터 삭제 — `sync_overlap_precedents.py --delete-ctx`

**안전 규칙 (전부 강제):**

1. **삭제 대상 = 수집 성공 ∩ 게시글ID 보유** — `_progress.json.fetched`에 있는
   사건번호 중 `_겹침대상.csv`의 게시글ID가 빈 값이 아닌 것만. 수집 실패분은
   ctx 벡터가 유일한 검색 경로이므로 절대 삭제하지 않는다.
2. **라이브 ID 기준** — 로컬 gz 사본이 아니라
   `index.list(prefix=f"ctx_precedent_{게시글ID}_", namespace="laborlaw-v2")`로
   현재 존재하는 ID를 직접 나열한다(실측 검증 완료 — prefix 조회 지원).
   접미 `_`까지 포함해 `403778`이 `4037789`를 잡는 오폭을 차단한다.

   > 주의: prefix가 `..._c`가 아니라 `..._`인 이유 — 청크 접미가 전부 `c{n}`인
   > 것은 사실이나 prefix를 느슨하게 잡고 나열 결과를 정규식
   > `^ctx_precedent_{id}_c\d+$`로 재검증하는 이중 확인이 더 안전하다.
3. `--dry-run` 기본 아님, 그러나 **실행 시 삭제 예정 ID 전량을
   `output_판례_보강/_ctx_deleted.json`에 먼저 기록**(사건번호→ID 목록) 후 삭제.
   복구가 필요하면 이 목록으로 gz 사본에서 재구성 가능.
4. 배치 삭제는 1,000 ID 단위(`index.delete(ids=batch, namespace=...)`).
5. `--reset`·`delete_all`·메타데이터 필터 삭제는 **어떤 형태로도 두지 않는다**.

### 2.4 벡터 수 검증 (4시점 스냅샷)

| 시점 | 기대값 |
|------|--------|
| V0 업로드 전 | 10,989 |
| V1 업로드 후 | V0 + N_new (dry-run 총청크 − 1,901 = 신규분. 사건번호 기반 ID라 기존 500건과 충돌 없음) |
| V2 삭제 후 | V1 − D (D = `_ctx_deleted.json`의 ID 수) |
| BM25 재빌드 | 문서 수 = V2 + counsel + qa |

각 시점 값을 스크립트가 출력하고 불일치 시 경고. `describe_index_stats`는
결과 반영에 수 초 지연이 있으므로 삭제 직후 검증은 재시도(3회, 5초 간격).

### 2.5 수집 실패분 처리

266건 중 법제처 미수록이 있으면(예상 ~10%):
- 139 유실군에서 실패 → **여전히 검색 불가로 남음.** `_미발견.csv`에 누적되고
  Track C 스파이크의 대상 목록에 합류한다.
- 127 ctx군에서 실패 → ctx 벡터 유지(삭제 제외). 태그만 없는 현상 유지.

---

## 3. Track A — NFD 버그 봉인

### 3.1 `pinecone_upload_legal.py::extract_post_id()`

```python
def extract_post_id(filepath: str, source_type: str) -> str:
    basename = unicodedata.normalize("NFC", ...)          # ① NFD 흡수 (핵심 수정)
    ...
    case_m = re.match(r"(\d{2,4}[가-힣]{1,4}\d+)", basename)  # ② 2자리 연도·복합 부호
    if case_m:
        ascii_id = _case_no_to_ascii(case_m.group(1))     # ③ 45종 매핑(긴 부호 우선)
        if ascii_id is not None:
            return ascii_id
    # ④ 매핑 불가 부호: 종전처럼 비ASCII를 조용히 지우면 연도 충돌이 재발하므로
    #    NFC 사건번호 전체의 hex 표기로 폴백 (예: case_x{nfc_utf8hex}) —
    #    절단 금지: 앞 바이트를 공유하는 사건끼리 ID가 충돌한다
```

`_case_no_to_ascii`·`_CASE_CODE_MAP`은 `pinecone_upload_court_precedents.py`의
사본을 둔다(업로드 스크립트 간 유틸 복사가 리포 관례 — CLAUDE.md 2계열 규칙).

### 3.2 `upload_new_precedents.py`

`CASE_NO_PATTERN = r"(\d{2,4}[가-힣]{1,4}\d+)"` 로 교체 +
`collect_existing_case_numbers()`가 파일 읽기 직후 NFC 정규화.

**추가(구현 중 확정)**: 이 함수는 본문 전체 `finditer`였다 — 정규식만 넓히면
참조판례 인용 오탐이 오히려 커진다. CLAUDE.md의 "중복 판정은 파일당 대표
사건번호 1개" 규칙에 맞춰 대표 추출(메타→파일명→본문 앞 1500자) 방식으로 전환.

### 3.3 범위 제외

`precedent` NS의 손상 474건 재업로드는 하지 않는다(Plan 의사결정 #3). 이
수정의 목적은 **재발 방지**다 — 두 스크립트를 다음에 실행할 때 새 손상이
생기지 않게 하는 것.

---

## 4. Track C — F3 스파이크 (타임박스 30분)

절차:
1. Playwright로 `portal.scourt.go.kr` 판례 검색 화면 로드 → 사건번호
   (`2000다51476`) 검색 → 네트워크 패널에서 XHR 엔드포인트·요청 형식 관찰
2. 관찰된 엔드포인트를 `requests`로 재현 시도(세션·토큰 요구 여부 확인)
3. 판정 기록: ① 재현 가능(→ 후속 사이클 후보) / ② 세션 결합으로 곤란 /
   ③ 접근 차단. AI Hub·유료 열람·수용 대안과 함께 권고 1건 작성.

산출물: 본 설계 문서 §7 부록에 판정표 기입(구현 없음). 브라우저 자동화가
불가한 환경이면 "환경 제약으로 미판정"으로 기록하고 종료 — 스파이크가
사이클을 블로킹하지 않는다.

---

## 5. 테스트 (`test_precedent_ingest.py` 확장, CI)

| # | 테스트 | 검증 |
|---|--------|------|
| T14-a | `legal.extract_post_id` NFD 파일명 | NFD `2020다242423_제목` → `2020da242423` |
| T14-b | 2자리 연도·복합 부호 | `90누9421`→`90nu9421`, `86다카24445`→`86daka24445`, `2011헌바395`→`2011heonba395` |
| T14-c | 고유성 시뮬레이션 | 부호 픽스처 전종 NFD 변환 후 post_id 충돌 0 |
| T14-d | `upload_new_precedents` 정규식 | NFD 본문에서 `다카`/`헌바` 추출 성공 |
| T15-a | `--cases` 모드 L2 생략 | 기존 코퍼스에 있는 사건도 대상에 들어감 (함수 단위) |
| T15-b | 대상 CSV 파싱 | `게시글ID` 빈 값 허용, 추가 컬럼 무시 |
| T16-a | 삭제 대상 산출 | fetched ∩ 게시글ID 보유만 선정, 실패분 제외 |
| T16-b | ID 재검증 정규식 | `ctx_precedent_403778_c3` 통과, `ctx_precedent_4037789_c0` 거부 |

네트워크 호출부(list/delete)는 오프라인 테스트 범위 밖 — 대상 산출·ID 검증
로직만 순수 함수로 분리해 고정한다.

---

## 6. 구현 순서

1. Track A 수정 + T14 (독립적, 선행)
2. `sync_overlap_precedents.py` 골격 + `--emit-targets` + T15·T16
3. `fetch_court_precedents.py` `--cases` 모드
4. 대상 CSV 생성 → `--cases` 수집(266건 ≈ 5분) → enrich → 업로드 dry-run → 업로드
5. `--delete-ctx --dry-run` → 목록 검토 → 실삭제 → 벡터 수 4시점 검증
6. BM25 재빌드 → gz 커밋 준비
7. Track C 스파이크 → §7 부록 기입
8. CLAUDE.md 커맨드 블록 갱신 (`--cases`·sync 스크립트)

## 7. 부록 — Track C 판정 (2026-08-09 스파이크 수행)

| 후보 | 판정 | 근거 |
|------|:---:|------|
| ① 통합 포털(portal.scourt.go.kr) XHR 재현 | **곤란** | 구 도메인(glaw)은 DNS 소멸. 신 포털은 정적 GET이 474바이트 JS 셸만 반환하고, Playwright 헤드리스 로드가 60초 타임아웃(`domcontentloaded` 미도달) — 무거운 SPA 또는 헤드리스 차단. 실사용 브라우저(Chrome 익스텐션 연동) 관찰 없이는 엔드포인트 특정 불가 |
| ② AI Hub 법률 데이터셋 | 수동 절차 | 계정·승인·수동 다운로드 필요. 미발견 98건 포함 여부는 데이터셋 명세를 열어봐야 확인 가능 |
| ③ 판결서 인터넷열람 | 가능하나 유료·수동 | 건당 수수료 기준 98건 ≈ 10만원 내외 + 건별 수동 열람. 비신원처리 판결문이라 후처리 필요 |
| ④ 영구 미수록 수용 | **권고(기본값)** | 98건은 전량 인용 1~3회의 롱테일이고, 교재 인용 상위 판례는 이미 확보됨 |

**권고**: ④ 수용. 단, 사용자가 Claude Chrome 익스텐션을 연동하는 시점이 오면
①을 실브라우저 네트워크 관찰로 재시도할 가치는 있다(관찰만 되면 재현 가능성을
확정 판정할 수 있음). ②·③은 투입 대비 회수(롱테일 98건)가 낮아 보류.

## 8. 리스크 재확인

| 리스크 | 대응 (설계 반영 지점) |
|--------|------|
| ctx 오폭 | §2.3 안전 규칙 5종 — 성공분∩게시글ID 교집합·라이브 prefix+정규식 재검증·사전 목록 기록 |
| prefix 부분일치 오폭 | `_` 포함 prefix + `^...c\d+$` 재검증 (T16-b) |
| 수집 실패 = 손실 | §2.5 — 실패분은 삭제 제외라 어떤 실패도 현상 유지로 수렴 |
| stats 반영 지연 오판 | §2.4 — 재시도 검증 |
| NFD 수정이 기존 업로드와 ID 불일치 유발 | `precedent` NS는 미사용이라 기존 ID와의 연속성 요구 없음(§3.3). laborlaw-v2의 ctx·precedent_* ID는 이 함수와 무관 |
