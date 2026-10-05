# kin-answer-accuracy — Design

> Plan: `kin-answer-accuracy.plan.md`(같은 폴더) · 작성 2026-10-03
> 범위: Plan P0-1~P0-3, P1-4~P1-6. P2는 범위 밖.

## 0. 설계 결정 요약

| # | 결정 | 이유 |
|---|---|---|
| D1 | 현행 기준 블록은 **`_KNOWLEDGE_MODULES`가 아닌 별도 목록 `_RULE_FACT_MODULES`** 에 등록하고, `rules_enabled()`와 무관하게 실행한다 | `_KNOWLEDGE_MODULES`는 `LEGAL_RULES_ENABLED=true`에서 통째로 꺼진다(`pipeline.py:2168`). 승인 저장소가 대체하는 것은 **수치 기준 11키**뿐이다. 요건·기간·조문 같은 비수치 규칙은 대체 경로가 없어서, 같은 목록에 두면 관리 모드를 켜는 순간 조용히 사라진다 |
| D2 | 폐기 기준 필터는 **`format_pinecone_hits()` 진입부, G4 캡보다 앞**에 둔다 | RAG hit이 컨텍스트에 들어가는 유일한 초크포인트다(`legal_consultation.process_consultation`은 법제처 조문만 반환). G4와 같은 이유로 여기 둬야 새지 않는다. 캡보다 앞이어야 걸러진 자리를 다른 출처가 채운다 |
| D3 | 필터는 **qa·counsel만 제외**하고, 판례·행정해석·해설서는 남기되 `[구 기준]` 주석을 단다 | 판례가 제35조를 인용한 것은 당시 유효한 법리라, 지우면 근거가 통째로 사라진다. 상담글은 "현재 이렇게 하라"는 조언 형식이라 낡으면 그 자체로 오답이 된다 |
| D4 | 인용 관련성 검사는 **`monitor` 기본**으로 배포하고(기록만), 임계를 실측한 뒤 `enforce`로 전환한다 | 임계를 잘못 잡으면 정당한 판례가 지워진다. 오억제가 오탐지보다 비싸다는 것이 이 저장소의 반복된 교훈이다 |
| D5 | 지식iN fixture에는 **질문 원문이 아니라 사실관계 요약(자체 작성)** 을 싣는다 | 저장소가 PUBLIC이다. 지식iN 질문은 제3자가 쓴 글이고 개인 사정이 담겨 있다. 원문 대신 `docId` 링크와 출처 표기로 추적성을 유지한다 |
| D6 | `forbidden_claims` 매처에 **부정 문맥 예외**를 추가한다(하위 호환) | 부분문자열 매칭은 "구 기준인 10일 미만은 폐지됐다"는 정답도 감점한다. 정답이 오답 문구를 *언급하며 부정*하는 것이 바로 이번에 원하는 출력이다 |

## 1. 모듈 구성

```
app/core/rule_facts.py        (신규) 비수치 현행 규칙 블록 4종 + 감지 함수
app/core/stale_rules.py       (신규) STALE_RULES 레지스트리 + filter_stale_hits()
app/core/citation_relevance.py(신규) 인용 판례 ↔ 질문 관련성 판정
app/core/rag.py               format_pinecone_hits 진입부에 filter_stale_hits 호출
app/core/pipeline.py          _RULE_FACT_MODULES 실행 · 관련성 검사 배선 · 규칙 접미
app/templates/prompts.py      ANSWER_ACCURACY_RULES (P1-5·P1-6)
fetch_official_rules.py       ARTICLES에 조문 6개 추가 (keys=[])
eval_consultation.py          forbidden_claims 부정 문맥 예외 · --fixture 인자
data/eval_kin_queries.json    (신규) 20문항 fixture
test_kin_accuracy.py          (신규) 오프라인 회귀 — CI 등록
```

## 2. P0-2 현행 규칙 블록 (`app/core/rule_facts.py`)

### 2.1 블록 정의

각 블록은 `RuleFact(name, detect, text, sources, as_of)` 데이터클래스 하나다. `text`는 손으로 쓴 사실문이고, 그 문장의 핵심 구절은 §2.3의 원문 대조 테스트로 고정한다.

| name | 감지 (`detect(query, analysis)`) | 핵심 사실 | 근거 |
|---|---|---|---|
| `unemployment` | `consultation_topic=="고용보험"` ∨ `"unemployment" ∈ calculation_types` ∨ 키워드(실업급여·구직급여·조기재취업·일용) | ① 일용근로자 수급요건: 수급자격 인정신청일이 속한 달의 **직전 달 초일부터 신청일까지 근로일수 합이 같은 기간 총일수의 3분의 1 미만**. 건설일용은 신청일 이전 **14일간 연속 근로내역 없음**으로도 충족 ② 대기기간: 실업신고일부터 **7일**은 구직급여 미지급(제49조) ③ **조기재취업수당: 대기기간이 지난 뒤 재취업하고, 실업신고일부터 14일이 지난 뒤 재취업한 경우**(제64조, 시행령 제84조) — 7일 대기기간과 다른 기준이다 ④ 이전 사업 기준 예외(제43조③ 단서)는 본문 요건을 함께 충족할 때만 적용 | 고용보험법 제40조·제43조·제49조·제64조, 시행령 제84조 |
| `dismissal_notice` | `consultation_topic=="해고·징계"` ∨ 키워드(해고예고·해고 수당·30일 전) | 계속근로 **3개월 미만**은 해고예고 예외(근로기준법 **제26조 단서 제1호**). 구 제35조(예외 대상)는 **삭제된 조문**이므로 인용 금지 | 근로기준법 제26조 |
| `weekly_holiday` | `"weekly_holiday" ∈ calculation_types` ∨ 키워드(주휴) | 해당 1주 동안 근로관계가 존속하고 소정근로일을 개근하면 발생한다. **다음 주 근무 예정은 요건이 아니다**(고용노동부 2021-08-04 행정해석 변경). 1주 소정 15시간 판단은 4주 평균(제18조③) | 근로기준법 제18조·제55조, 행정해석 |
| `probation_wage` | 키워드(수습) ∧ (`minimum_wage` ∈ types ∨ 키워드 최저임금) | 수습 감액은 1년 이상 계약 + 수습 3개월 이내 + 단순노무 직종 아님일 때 **최저임금의 90%까지**만 가능하다. 80% 지급은 어떤 경우에도 최저임금 위반 | 최저임금법 제5조②, 시행령 제3조 |

- 블록 헤더는 기존 사실 블록과 같은 형식을 쓴다: `[현행 기준 — 아래 요건·기간·조문은 반드시 이 내용을 따르세요. 학습 지식이나 참고 자료의 상담글이 다르면 이 내용이 우선합니다]`.
- 마지막 줄에 `(기준일 {as_of}, 근거: …)`를 붙인다. 법 개정 시 갱신 대상이 된다.
- 감지는 최대 2블록까지만 붙인다(우선순위는 표 순서). 실업급여 질문에 주휴 블록까지 붙으면 잡음이다.

### 2.2 배선 (`pipeline.py`)

```python
_RULE_FACT_MODULES = [(f.name, f.build) for f in rule_facts.RULE_FACTS]
# 기존 _KNOWLEDGE_MODULES 루프 바로 뒤 — rules_enabled()와 무관 (D1)
for name, build in _RULE_FACT_MODULES:
    try:
        block = build(query, analysis)
        if block: parts.append(block); used_rule_facts.append(name)
    except Exception as e:
        logger.warning("규칙 블록 %s 실패 (무시): %s", name, e)
```

- `conv_metadata["rule_facts"] = used_rule_facts`(빈 목록이면 기록하지 않음)로 남겨 사후 집계한다.
- 블록 위치는 `parts` 중간(지식 모듈 뒤)이다. 최상단은 `conflict_note` 자리라 바꾸지 않는다.

### 2.3 원문 대조 (테스트 고정)

`fetch_official_rules.py::ARTICLES`에 다음을 추가한다. 승인 키가 없으므로 `keys=[]`이고, 승인 게이트와는 무관하다. 목적은 **사실문 검증용 원문 확보**다.

| doc_id | 법령 | 조 |
|---|---|---|
| `ei_act_40` | 고용보험법 | 40 |
| `ei_act_43` | 고용보험법 | 43 |
| `ei_act_64` | 고용보험법 | 64 |
| `ei_enf_84` | 고용보험법 시행령 | 84 |
| `lsa_act_26` | 근로기준법 | 26 |
| `mw_enf_3` | 최저임금법 시행령 | 3 |

- `test_kin_accuracy.py::test_rule_fact_quotes_exist_in_official_text` — 각 `RuleFact`의 `anchors`(예: `"3분의 1 미만"`, `"14일"`)가 `output_공식법령/{doc_id}.md` 본문에 공백을 무시하고 존재하는지 검사한다(PDF·XML 공백 차이 대응은 `alignQuote`와 같은 원리). `output_*`는 gitignore라 CI에서는 **파일이 없으면 skip**한다. 그래서 로컬 검사가 수동 관문이 되고, 완료 조건에 명시한다.
- 행정해석(2021-08-04)은 법제처 원문이 없으므로 앵커 대조 대상에서 빼고, `sources`에 고용노동부 URL만 남긴다.
- 적재: `pinecone_upload_official_rules.py`로 laborlaw-v2에 함께 올리면 검색 근거로도 쓰인다. 적재 후 BM25 재빌드가 필요하다(3.5시간). **재빌드는 이 사이클 필수가 아니다** — 사실 블록은 검색과 무관하게 주입된다.

## 3. P0-3 폐기 기준 필터 (`app/core/stale_rules.py`)

### 3.1 레지스트리

```python
@dataclass(frozen=True)
class StaleRule:
    id: str
    pattern: re.Pattern      # 공기어 창 필수 — 단독 키워드 금지
    changed: str             # "2021-08-04"
    replacement: str         # 주석에 쓸 현행 기준 한 줄

STALE_RULES = (
  StaleRule("daily_10days",
    re.compile(r"일용.{0,40}(이전|전)\s*1\s*개월.{0,20}10일\s*미만|10일\s*미만.{0,40}일용"),
    "2019-10-01", "일용근로자 수급요건은 직전 달 초일~신청일 근로일수 1/3 미만"),
  StaleRule("weekly_next_week",
    re.compile(r"주휴.{0,80}(다음\s*주|익주|그\s*다음\s*주).{0,30}(근로|근무).{0,10}(예정|계속|해야)"),
    "2021-08-04", "주휴는 해당 주 근로관계 존속 + 개근이면 발생, 다음 주 근무 예정 불요"),
  StaleRule("lsa_35",
    re.compile(r"근로기준법\s*제\s*35\s*조"),
    "2019-01-15", "해고예고 예외는 근로기준법 제26조 단서"),
)
```

- 폐기일은 Do 단계에서 공포일로 확정하고 테스트에 고정한다(위 날짜는 잠정값).
- **`weekly_next_week`에는 `주휴` 공기어를 반드시 넣는다** — "다음 주 근무 예정"은 교대제·스케줄 상담에도 나온다.

### 3.2 동작

```python
def filter_stale_hits(hits) -> tuple[list[dict], list[dict]]:
    """(kept, dropped). qa·counsel 일치 → 제외, 그 외 일치 → content 앞에 주석."""
```

- qa·counsel 판정은 `rag.is_counsel_source()`를 재사용한다(Q6과 같은 정의).
- 주석 형식: `[구 기준 주의 — {changed} 이후 변경: {replacement}]\n` + 원본. hit을 **복사해서** 수정한다(제자리 변경은 rerank 결과를 참조하는 다른 경로를 오염시킨다).
- 제외된 hit은 meta_list(인용 화이트리스트)에서도 빠진다. G4와 같은 성질이다.
- **전량 제외 방지**: 제외 후 남은 hit이 0이면 제외를 취소하고 주석 방식으로 되돌린다. 근거가 0이 되면 LLM이 기억으로 답하는데, 그것이 더 나쁘다.
- 로그: `logger.info("폐기 기준 필터: 제외 %d · 주석 %d (%s)", …, rule_ids)`. `conv_metadata["stale_filtered"]`에 rule id 목록을 기록한다.
- 킬스위치: `STALE_FILTER=off`(재배포 반영, `TEXTBOOK_PROMOTE`와 같은 의미론).

### 3.3 영향 측정 (Do 첫 단계)

`python3 -m app.core.stale_rules --scan`이 BM25 코퍼스 전량에 레지스트리를 적용해 규칙별·출처별 일치 건수와 표본 5건을 출력한다. Plan §2.1 실측(qa 31건 내외 + 판례·해설서 주석 대상)과 크게 다르면 패턴을 재검토한다. **표본 육안 확인 없이 배포하지 않는다.**

## 4. P1-4 인용 관련성 (`app/core/citation_relevance.py`)

### 4.1 판정 대상

`validate_response_citations`가 `valid`로 판정한 판례마다, 그 번호가 화이트리스트에 들어온 경로를 구분한다(`extract_precedents_from_hits`의 `source`).

| 경로 | 의미 | 판정 |
|---|---|---|
| `title` / `meta` | 그 hit **자체**가 해당 판례 | 질문 ↔ hit 본문(판시사항·요지 앞 1,500자) 임베딩 유사도 |
| `chunk` | 다른 문서 본문이 **언급**한 번호(상담글이 인용한 판례 등) | 2차 인용 — 원문 미확인 |

- 판정 결과: `relevant` / `low_relevance`(유사도 < `CITATION_RELEVANCE_MIN`) / `secondhand`.
- 2019다293449 유형(상담글 본문 언급만으로 통과)은 `secondhand`로, 2018두63235 유형(쟁점이 다른 판례 자체)은 `low_relevance`로 걸리는 것이 목표다.

### 4.2 실행

- 답변 완성 후, 기존 6-1 인용 검증 직후에 한 번 실행한다. 임베딩은 **배치 1회**(질문 1 + 대상 N, 상한 6건)다. `case_match.py`와 같은 클라이언트·타임아웃(10초, 재시도 0)을 쓴다.
- `CITATION_RELEVANCE_MODE`:
  - `off`: 실행하지 않음.
  - `monitor`(기본): `conv_metadata["citation_relevance"] = {key: {verdict, sim}}`만 기록.
  - `enforce`: `low_relevance`는 기존 `correct_hallucinated_citations`로 넘겨 번호를 제거한다. `secondhand`는 같은 함수에 **다른 안내 문구**를 넘겨 "원문 확인 필요"로 바꾼다. 함수에 `reason` 인자(`"hallucinated"|"low_relevance"|"secondhand"`)를 추가해 프롬프트 1번 규칙의 문구만 갈아끼운다.
- 실패는 fail-open이다(기록 없이 통과). 이미 환각 교정이 돈 경우 대상에서 빼서 교정을 두 번 하지 않는다. `CITATION_STAGE_BUDGET`을 공유한다.

### 4.3 임계 결정

fixture 20건 Live 실행의 `monitor` 기록으로 양성(2020다270503 등 리포트가 관련 있다고 확인한 것)과 음성(2018두63235)의 유사도 분포를 보고 정한다. **양성을 하나라도 자르는 임계면 `enforce`로 전환하지 않는다.** 그 경우 P1-4는 monitor로 남기고 Report에 기록한다.

## 5. P1-5·P1-6 답변 규칙 (`prompts.py::ANSWER_ACCURACY_RULES`)

`WAGE_CALC_RULES`와 같은 방식으로 **두 답변 분기에 모두** 접미한다(`pipeline.py:2367` 옆, 조건 없이 항상).

```
[정확성 규칙]
1. 요약·결론·표의 판단은 서로 같아야 한다. 하나라도 "위반 소지"면 요약에서 "합법일 수 있다"고 쓰지 않는다.
2. 성립 요건 중 하나라도 사실관계가 불분명하면 "가능성이 높다"고 단정하지 말고, 확인할 사실을 먼저 적는다.
3. 날짜·입사일·퇴사일·신고일을 바꾸라는 조언은 (a) 근거 조문 (b) 기간 기산 방식 (c) "고용센터에서 확정 확인"을 함께 쓸 때만 한다. 특정 날짜 하나만 권하지 않는다.
4. 사용자 자료(계약서·통상임금·소정근로시간)로 확정되지 않은 금액은 "예시"라고 밝힌다.
5. 참고 자료에 [구 기준 주의] 표시가 있으면 그 내용을 현행 기준으로 안내하지 않는다.
```

- 규칙 5는 §3의 주석과 짝이다. 주석만 달고 이 규칙이 없으면 LLM이 주석을 무시할 수 있다.
- 프롬프트 길이 증가는 약 400자다. 캐시 접두부(시스템 프롬프트 본문)를 건드리지 않고 접미하므로 기존 구조와 같다.

## 6. P0-1 fixture와 평가기

### 6.1 `data/eval_kin_queries.json`

`eval_consultation.py`의 `EvalCase` 스키마를 그대로 쓴다. 검증기는 키 집합 **정확일치**다(`set(item) != REQUIRED_CASE_KEYS`, `eval_consultation.py:103`). 그래서 ① 기존 필수 키(`expected_intent`·`expected_topic`·`expected_calculation`·`expected_values` 등)를 빈 값으로라도 전부 넣고 ② 추가 필드 `source_ref`·`report_score`는 `OPTIONAL_CASE_KEYS`를 새로 두어 `REQUIRED ⊆ keys ⊆ REQUIRED ∪ OPTIONAL`로 판정을 바꾼다. 기존 60건은 그대로 통과한다(K1·K3). 아래 예시는 추가 필드 위주로 줄인 것이다.

```json
{
  "id": "kin-12",
  "category": "지식iN·고용보험",
  "question": "(자체 요약) 10월 7일 실업신고 후 10월 12일 입사 예정. 조기재취업수당을 받을 수 있는지, 입사일을 바꾸면 되는지",
  "source_ref": "kin docId=495385213",
  "report_score": 54,
  "required_laws": ["고용보험법 제64조"],
  "required_notices": ["14일"],
  "forbidden_claims": ["re:10월\\s*14일.{0,20}(입사|취업).{0,20}(가능|충족|받을 수)"],
  "allowed_sources": ["law_article","precedent","interpretation","regulation","counsel","qa","textbook","nlrc_case","graph"],
  "risk_level": "high"
}
```

- 20건 모두 이 형식이다. 질문 요약은 `qa_conversations.question_text`(10-02 14:08~14:19 KST)에서 **사실관계만 뽑아 다시 쓴다**(D5). 이름·지역·회사명은 넣지 않는다.
- 리포트가 "핵심 내용 일치"로 본 문항(10·14번 등)도 포함한다. 개선이 기존 정답을 깨지 않는지 보는 **음성 대조군**이다.

### 6.2 매처 확장 (`eval_consultation.py`)

```python
_NEGATION = re.compile(r"(폐지|삭제|구\s*기준|과거|이전 기준|더 이상|아닙니다|아니라|적용되지 않|요건이 아닙)")
def _claim_found(claim, answer):
    if claim.startswith("re:"): hits = list(re.finditer(claim[3:], answer))
    else: hits = [m for m in re.finditer(re.escape(claim), answer)]
    return any(not _NEGATION.search(answer[max(0, m.start()-40): m.end()+40]) for m in hits)
```

- 기존 60건 fixture의 결과가 바뀌지 않아야 한다. 회귀 테스트로 기존 `forbidden_claims` 전부가 같은 판정을 내는지 확인한다.
- `--fixture data/eval_kin_queries.json` 인자를 추가한다(기본은 기존 파일). 게시 경로(`--publish-admin`)는 그대로 쓴다. 관리자 화면에서는 `run_metadata.fixture`로 구분한다.

### 6.3 실행 순서

1. **기준선**: 현 배포(effort=medium) 그대로 `--live --fixture data/eval_kin_queries.json` → `docs/04-report/consultation-eval-baseline.md`에 "지식iN" 절을 추가한다. 리포트 점수(사람 채점)와 자동 판정이 어떻게 대응하는지도 함께 적는다. 자동 판정은 문자열 기반이라 78.4점 체계와 같은 척도가 아니다.
2. 구현 후 같은 명령으로 재측정한다.
3. 사람 재채점: 리포트 배점표로 오류 문항(1·3·5·8·9·11·12·17·18·19·20)을 재채점해 평균을 비교한다. 목표 ≥ 88은 이 수치로 판정한다.

## 7. 테스트 (`test_kin_accuracy.py`, 오프라인, CI 등록)

| ID | 검사 |
|---|---|
| K1 | fixture 스키마 — 20건, 필수 키, `re:` 패턴 컴파일, 질문에 `source_ref` 존재 |
| K2 | 매처 부정 문맥 — "10일 미만은 구 기준이라 폐지" → 미검출, "10일 미만이어야 합니다" → 검출 |
| K3 | 기존 60건 fixture의 `forbidden_claims` 판정이 매처 변경 전후로 같음 |
| K4 | `rule_facts` 감지 — 실업급여 질문 → `unemployment`, 연장수당 질문 → 없음, 최대 2블록 |
| K5 | `rules_enabled()=True`에서도 규칙 블록이 실행됨 (D1 회귀) |
| K6 | 원문 앵커 대조 — `output_공식법령/` 없으면 skip |
| K7 | 폐기 필터 — qa 일치 제외, 판례 일치 주석, 전량 제외 시 주석으로 되돌림, 원본 hit 불변, `STALE_FILTER=off` |
| K8 | 폐기 패턴 음성 — "다음 주 근무 예정표"(교대제, 주휴 없음), "3개월 미만 근로자 해고예고 예외(제26조)" 미일치 |
| K9 | `format_pinecone_hits`가 필터 → G4 → G4-T → Q4 순서로 적용됨 |
| K10 | 관련성 경로 분류 — title/meta → 유사도 판정, chunk 언급 → `secondhand`; 임베딩 실패 시 fail-open |
| K11 | `ANSWER_ACCURACY_RULES`가 두 답변 분기 모두에 접미됨 |
| K12 | `correct_hallucinated_citations(reason=…)`가 사유별 문구를 쓰고 기본값은 기존 동작과 같음 |

`.github/workflows/tests.yml`에 `python3 test_kin_accuracy.py`를 추가한다. 테스트 파일을 만들고 CI 등록을 빠뜨린 전례(PR #94 c2bc4ab)가 있으므로 같은 커밋에 넣는다.

## 8. 메타데이터·관측

`qa_conversations.metadata`에 추가하는 키(전부 **값이 있을 때만** 기록):

- `rule_facts`: 주입된 블록 이름 목록
- `stale_filtered`: 적용된 폐기 규칙 id 목록
- `citation_relevance`: `{사건번호: {verdict, sim}}`

공개 게시판 제외 키(`PUBLIC_EXCLUDE_KEYS`)에는 넣지 않는다. 품질 관측용이지 노출 제한 사유가 아니다.

## 9. 구현 순서

1. `stale_rules.py` + `--scan` 실측 → 표본 육안 확인
2. `fetch_official_rules.py` 조문 6개 수집 → `rule_facts.py` + 앵커 테스트
3. `pipeline.py` 배선(규칙 블록·필터 호출·규칙 접미) + `rag.py` 필터 위치
4. `eval_consultation.py` 매처·`--fixture` + `data/eval_kin_queries.json` 20건
5. **기준선 Live 측정**(구현 배포 전 프로덕션 코드로 실행할 수 있도록 4를 먼저 별도 커밋해도 된다)
6. `citation_relevance.py`(monitor) + `correct_hallucinated_citations(reason)`
7. 테스트 K1~K12 + CI 등록 → 재측정 → 임계 결정(§4.3)

## 10. 위험과 롤백

| 위험 | 탐지 | 롤백 |
|---|---|---|
| 규칙 블록 문구 오류 | K6 앵커 대조(로컬) | 해당 `RuleFact` 제거 후 재배포 |
| 폐기 필터 오억제 | `--scan` 표본 · `stale_filtered` 집계 | `STALE_FILTER=off` |
| 관련성 판정 오삭제 | monitor 기록 분포 | `CITATION_RELEVANCE_MODE=monitor/off` |
| 지연 증가 | 관련성 임베딩 1회(약 0.3~1초, 답변 완성 후) | `off` |
| 규칙 접미로 답변 형식 변화 | 기존 60건 Live 비회귀(91.7%) | 규칙 문구 축소 |

## 11. 구현 중 변경 (Do, 2026-10-03)

| # | 설계 | 구현 | 이유 |
|---|---|---|---|
| C1 | `StaleRule(id, pattern, changed, replacement)` | `current` 패턴 추가 — 상담글이라도 현행 기준을 함께 언급하면 제외하지 않고 주석 | `--scan` 표본에서 행정해석 변경을 올바르게 설명한 상담글(`ctx_qa_2253369_c1`)이 제외 대상이었다 |
| C2 | `weekly_next_week` 3번째 묶음 `(예정\|계속\|해야)` | `(근로\|근무)…(예정\|계속)` 또는 `출근…(하여야\|해야)` | 휴일대체 상담("다음주 소정근로일 중 1일을 쉬게 하여 보상해야") 오탐 |
| C3 | `lsa_35` = `근로기준법\s*제\s*35\s*조` | `근로기준법[^.\n]{0,20}?제\s*35\s*조` | 원답변이 "근로기준법 제26조·제35조"로 나열했다(kin-17) |
| C4 | 적용 규칙 id → `conv_metadata` | `format_pinecone_hits(stale_out=)` 인자로 수집 | 제외된 hit은 meta에 남지 않아 meta로는 수집할 수 없다 |
| C5 | 수집 조문 6개 | 8개(`ei_act_49`·`lsa_act_18` 추가) | 대기기간·4주 평균 문구의 앵커가 필요했다 |
| C6 | 사실문 초안 | 원문 대조 후 2곳 수정 | 조기재취업(시행령 제84조)에 "대기기간 경과" 요건이 없고 대신 1/2 잔여·12개월·**신고 전 채용 약속 제외**가 있었다. 제43조③ 단서 요약도 원문과 달랐다 |
| C7 | 부정 문맥 창 = 일치 앞뒤 40자 | 일치 **바깥**만 + 사건번호 리터럴·`re!:`는 예외 없음 | K3: 기존 금지 문구 자체에 "아닙니다"가 있어 영영 검출되지 않았다. kin-01: "실제 일한 시간이 아니라"가 판례 오인용을 통과시켰다. kin-17: "적용되지 않습니다"가 삭제 조문 인용을 통과시켰다 |
| C8 | fixture 13·18번 | 원답변 대조로 매핑 교정 | 질문 제목이 같아("실업급여 관련") 시각 순서로 매핑하면 뒤바뀐다 — 리포트의 제43조③ 단서 인용 여부로 확정 |
| C9 | — | `_citation_source_hits()`가 `case_no`·`source_type`을 넘김 | **기존 결함**: T31 메타 사건번호 경로가 파이프라인에서 죽어 있었다. 관련성 판정도 이 값이 필요하다 |
| C10 | — | `fetch_official_rules.write_doc`이 헤더에 없는 필드를 건너뜀 + `--doc` 인자 | **기존 결함**: 고시용 `notice_no` 필드 추가 뒤 조문 수집이 매번 KeyError로 죽었다 |
| C12 | — | `legal_api`의 조문 포맷에 **목(目)** 포함 + 캐시 세대 `v2:`→`v3:` | **기존 결함**(1차 Live 비교에서 발견): 법제처 현행 조문을 받고도 제40조①5호 가·나목이 빠져, LLM이 빈자리를 '10일 미만'으로 채워 현행 조문처럼 인용했다(기준선 13·18번) |
| C13 | — | 현행 규칙 블록 `harassment_retaliation` 추가 + 수집 조문 `lsa_act_76_3`·`lsa_act_109` | 2차 Live에서 9번이 두 번 연속 "제109조 제2항"을 벌칙으로 인용 — 그 항은 **2026. 4. 7. 삭제**(원문 확인). 실행 간 편차가 아니라 기억의 고정 오류다 |
| C14 | §4.3 임계 결정 후 enforce | **monitor 유지** | 실측(2차 Live): 음성 2018두63235가 0.56·0.36, 양성 2016다212869 0.553·2009다35040 0.448 — 임베딩 유사도로 분리되지 않는다. `secondhand`는 2023다302838·임금근로시간과-1736 같은 정당한 인용까지 잡아 그대로 교정하면 근거가 대량 삭제된다 |
| C15 | `daily_10days` = `일용.{0,40}(이전\|전)\s*1\s*개월.{0,20}10일\s*미만` | `일용.{0,60}10\s*일\s*미만` (+ `current` 예외) | 실측 표현이 "30일 이전 기간 동안 10일 미만"·"6월에 10일 미만" 등으로 다양해 '1개월' 고정이 놓쳤다. 넓힌 대신 `current`(3분의 1 언급) 예외와 `--scan` 전량 육안으로 막는다 |
| C16 | qa·counsel 판정은 `rag.is_counsel_source()` 재사용 | 사본 `_EXCLUDE_SOURCES` + 동일성 테스트 | `rag`를 import하면 순환이다. K7이 `COUNSEL_SOURCES`와의 동일성을 고정한다 |
| C17 | §3.1 "폐기일은 공포일로 확정" | **시행일**로 확정 + K7 고정 | 주석 문구가 "이후 변경"이라 사용자에게 의미 있는 날짜는 시행일이다 |
| C18 | `_RULE_FACT_MODULES` 목록 + 블록별 try | `build_rule_facts()`가 블록별 try | 목록을 pipeline에 복제하지 않고 모듈이 소유한다. 격리 요건은 같다(K4) |
| C11 | — | 관리자 테스트 호출(`api/model_settings.test_messages`)에도 `ANSWER_ACCURACY_RULES` 접미 | 실제 답변과 같은 크기로 첫 응답 시간을 재야 한다는 기존 규약 |

**fixture 검증**: 10-02 원답변 20건에 매처를 적용해 리포트가 지목한 확정 오류 12건(1·3·5·8·9·11·12·13·15·17·18·19)을 전부 검출했다. 나머지 8건은 조건 누락형이라 문자열 검사 대상이 아니다(사람 재채점 대상).
