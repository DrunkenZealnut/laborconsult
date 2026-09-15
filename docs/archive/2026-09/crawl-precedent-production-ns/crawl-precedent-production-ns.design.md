# crawl-precedent-production-ns Design

> **Plan**: `docs/01-plan/features/crawl-precedent-production-ns.plan.md`
> **Period**: 2026-09-14 (Design)
> **Status**: Design — Plan §7 미결 3건 실측 완료

---

## 0. Plan 미결 사항 해소 (2026-09-14 실측)

| Plan §7 미결 | 실측 결과 | 설계 반영 |
|---|---|---|
| `【이 유】` 뒤 블록의 절단 지점 | **315/318은 【이 유】가 마지막.** 후속 블록 3건뿐(원심판결 1 · 이하생략 1 · 원고,피상고인 1), 합계 19,393자 | §2.2 — 다음 `【】` 직전까지, 없으면 끝까지 |
| crawl 내부 `case_no` 중복 | **0건** — 1사건 1문서 | §3.1 — 그룹 키를 사건번호로 둬도 안전 |
| `overlap` 표식 8건의 성격 | `_겹침대상.csv`(post_id 기반) 표식이고 8건 전부 **`doc_letec=0`** — letec 중복이 아니다 | 특별 처리 불요 |

추가 확인:

| 항목 | 결과 |
|---|---|
| `case_no_to_ascii` 변환 실패 | **0/318** |
| letec과 사건 중복 | **0건** |
| `doctype` | 전량 `prec` (detc 없음 → 헌재 분기 불요) |
| 분류 | 근로기준 213 · 노동조합 52 · 산재보상 31 · 비정규직 22 |

---

## 1. 범위

### 1.1 대상 선정 — 재구현 금지

대상은 **`data/precedent_archive/documents.csv`에서 읽는다.** 게이트 판정을 스크립트가 다시 하지 않는다.

```python
source == "crawl"  AND  gate == "verbatim"  AND
inventory[case_no]: doc_crawl>0 AND vec_chunks==0 AND vec_ctx==0
```

**재구현 금지의 이유**: 게이트는 2026-09-01 표본 육안을 거쳐 승인된 것이고(`crawl_gate.json: approved=true`), `GATE_RULE_VERSION` 변경 시에만 무효화되는 구조다. 업로더가 독자 판정을 하면 승인 절차 밖에서 editorial이 적재될 수 있다.

### 1.2 제외 대상

| 대상 | 건수 | 사유 |
|---|---:|---|
| editorial | 22 | nodong.kr 편집 저작물 — 저작권 판단 별건 |
| post | 0 | 이 집합엔 없음 |
| letec 전문만 | 12 | `EMBED_SECTIONS` 규약의 의도된 결과 |
| 이미 검색되는 crawl | 475 | 대상 아님 |

---

## 2. 본문 추출 규칙

### 2.1 문서 구조

```
# {게시물 제목}
| 항목 | 내용 |        ← 메타 표
| 분류 | 근로기준 |
| 작성일 | 2020.01.16 |
| 사건번호 | 2014다41520 |
---                      ← 구분선
대법 2020.1.16. 선고 2014다41520
【원 고, 상고인】 …
【피 고, 피상고인】 …
【원심 판결】 …
【주 문】 …
【이 유】 …
```

### 2.2 `extract_reasoning(md) -> str | None`

```
① body = md.split("\n---\n", 1)[1]           # 메타 표 절단(없으면 md 전체)
② m = search(r"【\s*이\s*유\s*】", NFC(body))  # 공백 허용 — '【이 유】' 실측
③ nxt = 다음 【】 블록 매치 (m.end() 이후)
④ return body[m.end() : nxt.start() if nxt else len(body)]
⑤ 【이 유】 없으면 None → 스킵 + 집계 보고
```

**설계 결정 셋:**

- **`【】` 정규식에 공백을 허용한다.** 원문이 `【이 유】`·`【원 고, 상고인】`처럼 자간 공백을 쓴다. `【이유】`만 찾으면 **318건 전부 0건 매칭**된다.
- **다음 블록 "직전"까지 자른다.** 315건은 차이가 없지만 3건에서 `【원심판결】`·`【원고,피상고인】`이 본문에 섞인다. 그 3건이 규칙을 정하는 근거다 — 다수가 무해하다고 규칙을 느슨하게 두면 소수에서 조용히 샌다.
- **종결자 정규식에 길이 상한 20을 둔다**(`【\s*[^】]{1,20}\s*】`). 본문 중
  계산식·인용에 쓰인 긴 `【…】`(실측 코퍼스 전체 18건, 최장 96자)을 종결자로
  오인하면 본문이 조기 절단된다. 현재 대상 318건의 【이 유】 뒤 블록은 전부
  20자 이하라 영향 0건이지만, **게이트 재분류나 대상 확장으로 verbatim 범위가
  넓어지면 반대 방향(종결자 미매치 → 보일러플레이트 혼입)이 생긴다** — 그때는
  상한을 늘리기 전에 어느 실패가 더 비싼지 다시 판단할 것.
- **`【이 유】` 부재 시 스킵하고 **집계로 보고**한다.** 실측 318/318 보유이나, 향후 크롤 형식이 바뀌면 0건 매칭이 조용한 실패가 된다. `EMBED_SECTIONS` 0건 매칭을 이번에 발견한 경로와 같다.

### 2.3 청킹

기존 판례 규약을 그대로 쓴다 — `CHUNK_MAX=700`, `CHUNK_OVERLAP=80`.

`split_by_size`는 **`pinecone_upload_court_precedents`에서 import**한다. 사본을 두면 두 판례 코퍼스의 청크 경계가 갈라지고, 그 차이는 어떤 게이트에도 안 걸린다.

예상 산출: 1,213,038자 → **약 1,956청크**(dry-run으로 확정 — **실측 2,403**.
`split_by_size`가 구분자를 역탐색해 700자 미만에서 끊기 때문이며, Design이
"dry-run으로 확정"으로 둔 항목이다).

**임베딩 입력은 저장 본문과 다르다**:

```
embed_text = f"{case_no} {title}\n\n{본문}"
```

판결문 본문만으로는 "어느 사건인가"가 벡터에 남지 않는다. letec은 `판시사항`
섹션명이 그 역할을 했으나 이 코퍼스에는 섹션이 없다. 제목(`휴일근로 판단에
관한 법리…`)은 주제 요약이라 검색에 직접 기여한다.

---

## 3. 벡터 규약

### 3.1 `vector_id`

```
crawlprec_{case_key}_{chunk_idx}
        예) crawlprec_2014da41520_0
```

| 결정 | 근거 |
|---|---|
| 접두사 `crawlprec_` 분리 | letec은 `precedent_{case}_chunk_N`. 접두사가 같으면 두 코퍼스의 원장·prune 범위가 섞여, 한쪽 부분 실행이 다른 쪽을 고아로 오판한다 |
| `case_key` = `case_no_to_ascii(case_no)` **import** | 원장을 만든 바로 그 함수. 사본은 금지(`legal._case_no_to_ascii`는 계약이 다르다 — None 반환·NFC 미수행) |
| 그룹 키 = **ASCII 사건번호**(`2014da41520`) | 한 번의 실행이 통째로 다루는 단위이고, crawl 내부 중복 0건이라 1그룹=1문서. **letec과 같은 형식이어야 한다** — `archive_precedents.reverse_case_key`가 ASCII를 전제하므로 한글 키는 인벤토리에서 조용히 빠지고 선정 술어가 수렴하지 않는다(§4 참조) |
| `chunk_idx`는 0부터 연속 | 구멍이 생기면 원장 검증 정규식(`_\d+$`)이 통과시켜 조용하다 |

### 3.2 메타데이터 — 기존 `precedent` 스키마 준수

```python
{
  "source_type": "precedent",      # 라벨 맵·G5 기존 규약 재사용
  "title":       doc["title"][:200],
  "section":     "이유",            # 고정 — 이 코퍼스는 단일 섹션
  "case_no":     doc["case_no"],
  "court":       "대법원",          # doctype 전량 prec
  "date":        메타표 '작성일',
  "chunk_index": int,
  "chunk_text":  f"[{case_no}] {text}"[:900],
  "text":        동일,               # 이중 필드 — rag.py의 폴백 규약
}
```

**`text`/`chunk_text` 양쪽을 채운다.** `rag.py::_query_namespaces`가 `text`/`chunk_text` 이중 폴백인 것은 laborlaw-v2에 두 스키마가 섞여 있기 때문이고, 한쪽만 채우면 적재 시기에 따라 content가 빈 채 흘러가 `format_pinecone_hits`가 조용히 버린다.

**`source_type`을 새로 만들지 않는다.** `precedent`를 쓰면 `rag.py` 라벨 맵·`public/index.html::renderSources`·법률근거 다양성 승격(`LEGAL_PROMOTE`)이 전부 그대로 적용된다. 새 값을 만들면 그 셋을 모두 갱신해야 하고, 하나라도 빠지면 raw 값이 사용자에게 노출된다(G5 실패 모드).

### 3.3 네임스페이스

```python
NAMESPACE = "laborlaw-v2"
```

`test_offline_units.py::test_upload_namespace_contract`가 검사하는 규약을 따른다 — `pc.delete_index()` 금지, upsert에 네임스페이스 명시, 사장 NS 적재 시 `NS-CONTRACT: unsearched` 마커. 이 스크립트는 검색 대상 NS에 쓰므로 마커를 **달지 않는다**.

---

## 4. 원장

```python
_LEDGER = VectorLedger(
    os.path.join(CRAWL_DIR, "_uploaded_ids.json"),
    group_re=re.compile(r"^[A-Za-z0-9_]+$"),        # letec과 동일 — ASCII 사건번호
    id_re_for=lambda case_key: re.compile(rf"^crawlprec_{re.escape(case_key)}_\d+$"),
)
```

| 결정 | 근거 |
|---|---|
| 원장 파일을 **코퍼스별로 분리** | `output_법원 노동판례/_uploaded_ids.json`. 한 파일 공유 시 한쪽의 손상 격리(.bak 이동)가 다른 쪽 롤백까지 중단시킨다 |
| `record` → upsert → `prune` → `finalize` 순서 | 롤백 기록이 upsert보다 **먼저**. 중간에 죽으면 적재분이 추적에서 빠지고, 존재하지 않는 ID의 delete는 무해하므로 상위집합이 안전한 방향 |
| 대량 삭제 가드는 **합계**로 판정 | 그룹별로 걸면 청크 1개짜리 판례에서 1건만 줄어도 50%를 넘어 상시 발동한다 |

⚠️ 원장은 `.gitignore`(`output_*/`) 대상이라 **로컬 전용**이다. 아카이브 스냅샷(`archive_precedents.py build`)이 유일한 백업이므로 적재 후 build 재실행이 필수다.

### 4.1 인벤토리 반영 — `load_ledger`가 코퍼스별 원장을 병합해야 한다

`archive_precedents.load_ledger`는 letec 원장만 읽고 있었다. 그래서 크롤 적재분이
`inventory.csv`의 `vec_chunks`에 반영되지 않았고, 그 열을 선정 술어로 쓰는
`select_targets()`가 **적재 후에도 같은 318건을 계속 반환**했다 — 인자 없이
재실행하면 2,403청크를 전량 재임베딩하는 상태였다(2026-09-14 실측·수정).

**V0~V8이 잡지 못한다.** V4는 letec 스코프이고, V8(멱등)은 재빌드해도 같은 0이
나오므로 통과하는 것이 정상이다. 즉 **verify 통과가 무결성의 증거가 아닌** 구간이
있었다. 회귀 T32가 이 수렴을 별도로 고정한다.

새 코퍼스를 추가할 때 지킬 것 둘:
- `load_ledger`의 병합 목록에 그 코퍼스 디렉터리를 넣을 것
- 그룹 키를 **ASCII 사건번호**로 둘 것(`reverse_case_key` 전제). 어기면 그
  코퍼스만 조용히 인벤토리에서 빠진다

---

## 5. 산출물

| # | 파일 | 내용 |
|---|---|---|
| 1 | `pinecone_upload_crawl_precedents.py` | 신규 — 대상 선정·`extract_reasoning`·청킹·임베딩·upsert·prune |
| 2 | `output_법원 노동판례/_uploaded_ids.json` | 원장(자동 생성) |
| 3 | `test_precedent_ingest.py` T30 | 회귀 |
| 4 | `data/bm25_corpus.jsonl.gz` | 재빌드(커밋) |
| 5 | `data/precedent_archive/**` | `build` 재실행 산출물(커밋) |

### 5.1 CLI

```bash
python3 pinecone_upload_crawl_precedents.py --dry-run    # 청킹 검증
python3 pinecone_upload_crawl_precedents.py              # 적재
python3 pinecone_upload_crawl_precedents.py --limit 20   # 부분 실행(재개)
```

`--allow-large-prune`은 두지 않는다 — 최초 적재라 이전 집합이 없고, 규격 변경 시에만 필요한 플래그를 미리 만들면 오용 경로만 생긴다.

---

## 6. 회귀 T30

| ID | 검사 | 막는 실패 |
|---|---|---|
| T30-a | `【이 유】` 추출 — 자간 공백(`【이 유】`) 매칭 | 공백 미허용 시 **318건 전부 0건 매칭**(조용) |
| T30-b | 후속 `【】` 블록 직전에서 절단 | 당사자 표시가 본문에 섞임 |
| T30-c | `【이 유】` 부재 시 None + 집계 | 형식 변경이 조용한 0건 적재가 되는 것 |
| T30-d | 대상 선정이 `documents.csv`의 `gate` 열을 읽는다 | 게이트 재구현 → 승인 절차 우회 |
| T30-e | editorial·post 문서는 대상에서 제외 | 저작권 경계 침범 |
| T30-f | `vector_id` 접두사가 letec과 분리 | 원장·prune 범위 혼선 |
| T30-g | `case_no_to_ascii`를 import (동일성 `is`) | 사본 드리프트 |
| T30-h | `NAMESPACE == "laborlaw-v2"` | 사장 NS 재발 |
| T30-i | 메타데이터에 `text`·`chunk_text` 양쪽 존재 | content 빈 채 흘러가 조용히 버려짐 |
| T30-j | `chunk_index` 0부터 연속 + `chunk_text` 전 청크 사건번호 접두 | 원장 검증 정규식이 구멍을 통과시킴 / 인용 화이트리스트 누락(§9) |

### 6.1 T31 — 인용 화이트리스트 (§9)

| ID | 검사 |
|---|---|
| T31-a·b | 메타 `case_no`만 있어도 인용 목록 등재, 출처가 `meta`로 기록 |
| **T31-c** | **메타 기반 인용이 환각으로 판정되지 않음** — 이 변경의 목적 자체 |
| T31-d | LLM에 주는 `build_available_citations_text`에 포함 |
| T31-e·f | 기존 제목 파싱 경로 유지 / `case_no` 부재 hit 안전(ctx 구크롤) |
| T31-g·h | `rag.py` 두 지점이 실제로 `case_no`를 실어 보냄 — 여기서 끊기면 위가 전부 무의미 |

### 6.2 T32 — 원장 수렴 (§4.1)

| ID | 검사 |
|---|---|
| T32-a | `load_ledger`가 letec·crawl 원장을 모두 읽음 |
| T32-b·c | 두 원장의 키가 ASCII이고 `reverse_case_key`로 해석됨 |
| T32-d·e | 업로더가 ASCII 그룹 키 사용, 정규식이 letec과 동일 계열 |

---

## 7. 실행 순서 (Do)

1. `--dry-run` → 청크 수·제외 건수 확인 (예상 1,956 ± α)
2. T30 작성·통과
3. `laborlaw-v2` 벡터 수 기준선 기록
4. 적재 → 증가분 == 신규 청크 수 확인
5. `archive_precedents.py build` → `verify` (V0~V8)
6. `build_bm25_corpus.py` 재빌드 (**약 3.5시간**)
7. `test_bm25_memory.py` — RSS 상한 550MB 확인 (현재 455MB, +1,956문서 여유 확인 필요)
8. `eval_retrieval.py` 재측정 → analysis 기록
9. CI 전량 + 커밋

⚠️ **7번이 이 사이클의 실질 리스크다.** 현재 RSS 455MB에 +1,956문서면 상한 550MB에 근접할 수 있다. 초과 시 **상한을 올리는 것이 기본 대응이 아니다** — `bm25-memory-scaling.design.md` §1의 구조 개선 대안을 먼저 검토한다.

---

## 8. Plan 대비 변경

| 항목 | Plan | Design | 사유 |
|---|---|---|---|
| `chunk_id` | `crawlprec_{case_key}_{chunk_idx}` | 동일 | — |
| `section` 값 | 미정 | `"이유"` 고정 | 단일 섹션 코퍼스 |
| `--allow-large-prune` | 언급 없음 | **두지 않음** | 최초 적재라 불필요, 오용 경로만 생김 |
| BM25 메모리 | 리스크 미기재 | **§7 7번으로 승격** | 455MB + 1,956문서가 550MB 상한에 근접 |
| `embed_text` 구성 | 언급 없음 | §2.3 — `{case_no} {title}` 접두 | 섹션명이 없어 "어느 사건인가"가 벡터에 안 남음 |
| `chunk_text` | `text[:900]` | §3.2 — `[{case_no}] ` 접두 | 인용 화이트리스트가 읽는 것이 `chunk_text`(§9) |
| `metadata.category` | 9필드 | 10필드(`category` 추가) | 분류(근로기준/노동조합/산재/비정규직) 보존. 현재 소비자 없음 |
| 원장 그룹 키 | "사건번호"(형식 미지정) | **ASCII 고정** | `reverse_case_key` 전제 — 한글이면 인벤토리에서 빠진다(§4.1) |
| 인용 화이트리스트 | 범위 밖 | **§9 신설** | Design 이후 사용자 요청으로 추가 |

---

## 9. 인용 화이트리스트에 메타 사건번호 (Design 이후 추가)

> 이 절은 Do 단계에서 사용자 요청으로 확장된 범위다. 원 Design(§1~§8)의 목표는
> "사장 NS → 프로덕션 NS"이고, 이 절은 **적재된 판례가 실제로 인용되게 하는 것**을
> 다룬다. 두 목표가 다르므로 절을 분리해 둔다.

### 9.1 문제

`citation_validator.extract_precedents_from_hits`는 hit의 `title`·`chunk_text`에서
**정규식으로만** 사건번호를 뽑는다. 그런데 판시사항·판결요지는 자기 사건번호를 적지
않는 것이 보통이라, **letec 6,440청크 중 6,060(94%)이 인용 가능 목록에 오르지
못했다**(2026-09-14 실측).

결과는 "검색은 되는데 인용은 못 하는 상태"다 — 판례가 컨텍스트에 실리고 LLM이 그것을
근거로 인용해도, 화이트리스트에 없으니 환각으로 판정돼 `replace` 이벤트가 지운다.

### 9.2 경로

끊긴 지점이 셋이었다:

| 위치 | 변경 |
|---|---|
| `rag.py::_query_namespaces` | hit dict에 `case_no` 적재(메타에 이미 있던 값) |
| `rag.py::format_pinecone_hits` | `meta_list`에 `case_no` 전달 |
| `citation_validator.extract_precedents_from_hits` | `case_no`를 `title`·`chunk_text`와 **동등한 원천**(`source="meta"`)으로 추가 |

세 곳이 모두 있어야 한다 — 하나라도 빠지면 값이 중간에서 끊기고, 그 실패는 조용하다.
T31-g·h가 `rag.py` 두 지점을 소스 검사로 고정하는 이유다.

### 9.3 범위와 한계

| | |
|---|---|
| 효과 범위 | **8,843청크** — letec 6,440 + 신규 crawl 2,403 |
| 대상 밖 | ctx 구크롤 1,310청크 — 메타에 `case_no`가 **없다**(봉인된 `pinecone_upload_legal.py` 산출) |
| 신뢰도 | `case_no`는 법제처 API·아카이브가 확인한 값이라 본문 정규식보다 높다 |

신규 318건은 `chunk_text` **전 청크**에 사건번호를 접두했다(§3.2). 판결문 전문은
서두에 사건 표시가 있어 첫 청크는 75%가 통과하지만, 근거로 쓰이는 것이 첫 청크라는
보장이 없다. 결과 100%(2,403/2,403).

### 9.4 측정 한계

**이 변경의 효과는 `eval_retrieval`에 잡히지 않는다.** 그 평가는 검색 도달률을
재는데 §9는 인용 가능성을 바꾼다. 자동 지표가 없어 **프로덕션 관찰 항목**으로 남는다
— 측정하지 않은 것을 측정한 것처럼 적으면 다음 사이클의 판단 근거가 오염된다.
