# 상담 평가 기준선 보고서

## 실행 정보

2026-09-09 기준 오프라인 fixture·지표 계약 검증은 통과했다. **라이브 기준선은 미실행**이며, 답변 품질·정확도·지연의 실측 점수는 아직 없다. 이번 Task 5의 조정자 지시에 따라 외부 API를 호출하지 않았다. 환경변수 유무나 서비스 가용성은 확인하지 않았으므로 미실행 원인을 키 누락이나 서비스 장애로 기록하지 않는다.

| 항목 | 기록 |
|---|---|
| 검증 시각 | 2026-09-09 05:49 KST (2026-09-08 20:49 UTC) |
| 평가 코드 기준 커밋 | `f5607ecfed5e99ee97d37f17aae13ccb7e93ba69` |
| Python | 3.11.3 (`./.venv/bin/python`) |
| fixture | [data/eval_consultation_queries.json](../../data/eval_consultation_queries.json) |
| fixture SHA-256 | `13b525298b1cedd4b5bed1e93435a4707c480fe44a1ac5efc177bad34d49a6de` |
| 평가기 / 테스트 | [eval_consultation.py](../../eval_consultation.py) / [test_consultation_eval.py](../../test_consultation_eval.py) |
| 라이브 실행 / 결과 파일 | 미실행 / 이번 실행에서 생성하지 않음 |
| 모델·인덱스 | 미측정; 실행에 사용된 모델·인덱스 없음 |

재현 명령:

```bash
./.venv/bin/python eval_consultation.py --offline
./.venv/bin/python test_consultation_eval.py
```

첫 명령은 exit 0으로 다음을 출력했다.

```text
fixture: 60건
schema: PASS
distribution: PASS
offline evaluation contract: PASS
```

두 번째 명령은 직접 실행형 테스트 **32개 모두 통과**, exit 0이었다. fixture 필드·enum·분포, 결정론적 지표, 이벤트 수집과 분석기 복원, CLI 선택·오류·직렬화를 확인했다. CLI subprocess 테스트는 임시 작업 디렉터리에서 `-I -S`로 실행하여 외부 패키지·클라이언트 없이 성공하고 파일을 생성하지 않음을 검증한다. CLI의 `offline evaluation contract: PASS` 문구 자체는 실제 답변 채점 결과가 아니며, 지표 계산 계약은 별도 테스트의 합격으로 확인했다.

Task 4 인계 기록에는 계산기 골든, 파이프라인 wiring, offline units, LLM fallback, answer renderer, answer glance 회귀 명령의 exit 0이 기록되어 있다. 이 문서 작업에서는 위 두 명령을 새로 실행했으며 기존 회귀 전체를 다시 실행한 것으로 보고하지 않는다.

향후 라이브 실행 명령은 `./.venv/bin/python eval_consultation.py --live --limit 60`이다. 기본 결과 파일 `eval_consultation_results.json`은 기존 `.gitignore`의 `*_results.json` 규칙으로 제외된다. 파일에는 `run_metadata`, `summary`, `results`가 저장되고, 메타데이터는 UTC ISO 시작 시각·fixture 경로·전체 case 수·Python 버전·git commit을 담는다. 모델·인덱스·fixture 해시는 현재 JSON 메타데이터에 없으므로 실제 재실행 시 함께 기록해야 한다.

개별 결과는 `case_id`, `category`, `question`, `observed`, `scores`, `pipeline_error`를 포함한다. 채점은 답변 전문으로 수행하고 저장 답변만 3,000자로 제한한다. 평가기는 설정 복사본의 Supabase를 비활성화하여 운영 DB 저장을 막는다. 라이브 질문·답변·출처 원문 결과는 커밋하지 않는다.

## 평가셋 분포

실제 상담 원문을 복제하지 않은 비식별 합성 질문 60건이며 ID는 모두 고유하다. 질문에 명시된 기준 연도와 조건을 유지한다.

| 범주 | ID | 건수 |
|---|---|---:|
| 임금·계산 | wage-01~wage-10 | 10 |
| 해고·징계·구제절차 | dismissal-01~dismissal-10 | 10 |
| 근로시간·휴일·연차 | hours-01~hours-10 | 10 |
| 퇴직금·퇴직·고용보험 | retirement-01~retirement-08 | 8 |
| 산재·괴롭힘·차별 | risk-01~risk-08 | 8 |
| 판례·행정해석·법령 조회 | law-01~law-08 | 8 |
| 정보 부족·복합·구어체 질문 | missing-01~missing-06 | 6 |
| **합계** | | **60** |

각 항목의 12개 필드는 식별·질문(`id`, `category`, `question`), 분석 정답(`expected_intent`, `expected_topic`), 근거(`required_laws`, `allowed_sources`), 계산(`expected_calculation`, `expected_values`), 고지·오답(`required_notices`, `forbidden_claims`), 위험도(`risk_level`)다.

`expected_intent`는 analyzer의 `consultation_type`과 비교하며 빈 문자열이면 판정하지 않는다. 주제와 계산 라벨은 `None`이면 판정하지 않는다. 의도·주제 판정 대상은 각각 45건, 계산 이벤트 요구는 10건, 필수 법조문 문자열이 있는 질문은 47건이다. 위험도 분포는 low 34건, medium 4건, high 22건이며 이 라벨 자체는 자동 통과 조건에 사용하지 않는다. `expected_values`는 참고값으로만 보관한다.

## 자동 지표

아래는 **지표 정의**이며 라이브 측정치는 모두 미측정이다. 빈 요구 목록의 만점이나 테스트용 fake 답변의 점수를 라이브 성적으로 옮기지 않는다.

| 개별 지표 | 판정 방법·한계 |
|---|---|
| `intent_match`, `topic_match` | 분석 결과와 fixture 라벨의 정확한 일치; 선택 항목은 `None` |
| `required_law_coverage` | 답변에 포함된 필수 법조문 문자열 수 / 요구 수; 빈 목록은 1.0 |
| `required_notice_coverage` | 답변에 포함된 필수 고지 문자열 수 / 요구 수; 빈 목록은 1.0 |
| `allowed_source_only` | 수집된 모든 `source_type`이 허용 목록에 속하는지; 출처가 비어 있어도 참이므로 근거 확보 여부를 보장하지 않음 |
| `forbidden_claims_found` | 답변에서 단순 substring으로 발견한 금지문 목록; 의미·부정 문맥을 해석하지 않음 |
| `disclaimer_present` | 답변에 `법적 효력` 문자열이 있는지 |
| `calculation_present` | 계산 요구 시 `calc_result is not None`; 계산 유형·금액 정확성은 검증하지 않음 |
| `pipeline_ok` | 공백 이외 답변이 있고 `pipeline_error`가 없는지 |
| `automatic_pass` | 파이프라인 성공, 금지문 없음, 허용 출처만 존재, 법조문·고지 coverage 각각 1.0, 면책 존재, 요구된 의도·주제·계산 판정 모두 참 |

집계의 `pipeline_success_rate`, `automatic_pass_rate`, 법조문·고지 coverage 평균, `disclaimer_rate`는 전체 실행 사례를 분모로 한다. `intent_accuracy`, `topic_accuracy`는 해당 판정이 `None`인 사례를 분모에서 제외한다. 파이프라인 실패 사례는 적용 대상 품질 지표에서 0점으로 계산한다. 전체 60건 실행 시 의도·주제 분모는 각각 45건이다. 필수 법조문이 없는 13건도 법조문 coverage 평균에 포함되므로 47건 대상만의 포함률과 동일하지 않다.

`forbidden_claim_count`는 실패 사례까지 포함한 발견 문자열 수다. `average_total_ms`는 측정값의 반올림 평균, `p95_total_ms`는 정렬 후 nearest-rank 95백분위이며 실패 실행의 측정값도 포함한다. 시간은 첫 이벤트부터 `done`까지이고 TTFT는 첫 이벤트부터 첫 `chunk`까지다. 첫 이벤트 전 처리 시간은 포함하지 않으며 `chunk`가 없으면 TTFT는 0이다. TTFT는 개별 결과에만 저장된다.

빈 집계의 비율·시간 0은 라이브 성공이나 빠른 응답을 뜻하지 않는다. 사례는 있으나 선택 정확도의 대상이 전혀 없으면 해당 정확도는 `None`이다. 허용 출처·계산 존재는 개별 점수에 있으며 현재 요약에는 별도 집계율이 없다.

설계의 라우팅 95% 이상, 필수 근거 90% 이상, 계산값 정확도 100%, 인용 환각 0건, 면책 100%는 향후 품질 목표다. 현재 문자열 채점으로 법적 적절성·법조문 실재/내용·판례 환각·계산값 정확도·공개 노출 안전성을 증명할 수 없다. P95 회귀 한계도 실측 이후 정한다.

## 실패 케이스

| 구분 | 이번 상태 | 해석 |
|---|---|---|
| 오프라인 fixture·테스트 실패 | 관측 없음 | 오프라인 CLI exit 0, 테스트 32개 통과 |
| 라이브 파이프라인 성공·실패 | 판정 없음 | 실제 호출 0건; 성공률 0% 또는 100%로 기록하지 않음 |
| 라이브 자동 품질 실패 | 미측정 | 실패 사례 목록을 만들 답변이 없음 |
| 라이브 미실행 | 전체 60건 | 조정자의 외부 API 호출 금지 지시 |

향후 실행에서는 성공(`pipeline_ok=true`), 실행 실패(`pipeline_ok=false` 또는 설정·저장 오류), 미실행을 분리한다. 자동 품질 미달은 실행 성공과 별개다. CLI exit 0도 `automatic_pass=true`를 보장하지 않으며, exit 1은 설정·fixture·저장·파이프라인 오류를 구분해 기록해야 한다. 오류 레코드는 사례 ID·실패 지표·오류 유형으로 요약하고 원문 결과는 로컬에만 보관한다.

법조문 검증 대상은 아래 **47개 질문, 24개 고유 필수 문자열**이다. 이 목록은 fixture 라벨을 전사한 것으로, 현행 법령 또는 실제 답변의 인용을 검증했다는 뜻이 아니다.

| 필수 법조문 문자열 | 질문 ID |
|---|---|
| 최저임금법 제6조 | wage-01 |
| 근로기준법 제55조 | wage-02, wage-10, hours-04, law-03 |
| 근로기준법 제56조 | wage-03, wage-04, wage-05, wage-10, missing-02 |
| 근로자퇴직급여 보장법 제8조 | wage-06, retirement-03 |
| 근로기준법 제60조 | wage-07, hours-05, hours-10, law-04 |
| 근로기준법 제43조 | wage-08, missing-05 |
| 고용보험법 제70조 | wage-09, retirement-07 |
| 근로기준법 제26조 | dismissal-01, dismissal-06, law-05 |
| 근로기준법 제27조 | dismissal-02, law-01 |
| 근로기준법 제28조 | dismissal-03, dismissal-07, law-08, missing-04 |
| 근로기준법 제23조 | dismissal-04, dismissal-05 |
| 근로기준법 제50조 | hours-01 |
| 근로기준법 제53조 | hours-02 |
| 근로기준법 제61조 | hours-06 |
| 근로기준법 제18조 | hours-07 |
| 근로기준법 제57조 | hours-09 |
| 근로자퇴직급여 보장법 제4조 | retirement-01 |
| 근로기준법 제2조 | retirement-02, missing-03 |
| 근로기준법 제36조 | retirement-04 |
| 고용보험법 제40조 | retirement-05, retirement-06 |
| 산업재해보상보험법 제37조 | risk-01, risk-02 |
| 근로기준법 제76조의2 | risk-03 |
| 근로기준법 제76조의3 | risk-04, risk-05 |
| 근로기준법 제17조 | law-06 |

필수 법조문 라벨이 없는 13건은 dismissal-08, dismissal-09, dismissal-10, hours-03, hours-08, retirement-08, risk-06, risk-07, risk-08, law-02, law-07, missing-01, missing-06이다. 이들 답변이 자발적으로 생성하는 법조문도 현재 coverage 검사로는 검증하지 않는다.

현재 [citation_validator.py](../../app/core/citation_validator.py)는 판례·행정해석 번호 검증을 중심으로 구성되어 있다. 다음 단계에 필요한 미검증 사례는 법률명·조문번호가 근거에 없는 인용, 번호는 있으나 인용 내용이 다른 경우, 시행시점이 다른 내용, `제76조의2`와 같은 가지조문·항/호 표기, 조회 실패로 대조 근거가 없는 경우, 교정 실패다. 예를 들어 risk-03~risk-05의 가지조문 구별과 law-01의 법조문/판례 동시 인용은 별도 검사 대상이다. 이는 코드·fixture에서 도출한 검토 항목이며 라이브에서 발견된 오류 사례가 아니다.

## 전문가 검토 큐

**상태: 대기, 검토 완료 0건.** 라이브 답변 확보 후 전체의 10% 이상(최소 6건)을 블라인드 검토한다. 초기 표본은 7개 범주에서 각 1건인 다음 7건(60건의 약 11.7%)으로 정하고, 실행 실패·금지문 발견·고위험 누락 사례를 추가한다.

| 질문 ID | 검토 초점 |
|---|---|
| wage-01 | 질문에 명시된 2025년 기준·계산 조건과 결과의 일치 |
| dismissal-03 | 구제 절차·기관·기한 설명의 적절성 |
| hours-05 | 연차 발생 기준과 조건·예외 |
| retirement-06 | 조건부 결론과 필요한 사실·증빙 안내 |
| risk-04 | 신고·조사 절차와 고위험 안내 |
| law-01 | 법조문·확인된 판례번호·판단 요지의 근거 일치 |
| missing-04 | 해고일 누락 시 신청기한을 단정하는지 |

검토자는 자동 점수를 보지 않고 답변·근거를 검토한 뒤 사례 ID별 적절성, 근거 일치, 누락 사실, 수정 필요 여부를 기록한다. 저장 답변이 3,000자에서 잘리면 그 요약만으로 전문 검토를 완료하지 않고 통제된 재실행 등으로 필요한 전문을 확보한다. 전문가 담당자 배정과 검토 일정은 아직 정해지지 않았다.

## 다음 게이트

[구현 계획 Task 5](../superpowers/plans/2026-09-09-consultation-eval-harness.md)와 [설계 6.2](../superpowers/specs/2026-09-08-consultation-answer-pdca-design.md)에 따른 상태는 다음과 같다.

| 2단계 계획 진입 조건 | 상태·근거 |
|---|---|
| fixture 60건 모두 유효 | 충족: 고유 ID·필드·enum·7개 분포 테스트 통과 |
| 오프라인 실행 재현 가능 | 충족: CLI·32개 테스트 및 격리 subprocess 계약 통과 |
| 라이브 성공·실패·미실행 구분 | 충족: 이번 60건은 명시적 미실행, 실측 점수 없음 |
| 법조문 검증 대상과 미검증 사례 목록화 | 충족: 47건/24개 문자열, 무라벨 13건, 검증 공백 목록 |

**법조문 검증기의 별도 구현 계획 작성에 필요한 인계 조건은 충족했다. 라이브 답변 품질이나 운영 배포 게이트가 통과한 것은 아니다.** 다음 계획은 `app/core/citation_validator.py`의 법조문 패턴·허용 목록·내용 대조·교정 실패 처리를 대상으로 하고 기존 판례·행정해석 API와 평가 fixture/CLI 결과 계약을 유지한다.

운영 차단 정책 활성화 전에는 허용된 환경에서 60건 라이브 결과와 실행 설정을 기록하고, 실행·품질 실패를 분류하고, 전문가 표본 검토를 완료해야 한다. 설계의 P0(계산값 오류·미확인 인용 단정·절단 답변 공개 노출)는 배포 차단, P1(라우팅 95% 미만·필수 근거 90% 미만)은 수정 후 재평가로 다룬다. 아직 자동 측정할 수 없는 항목은 별도 검증과 전문가 판단을 확보해야 하며, 이번 오프라인 합격으로 대체하지 않는다.
