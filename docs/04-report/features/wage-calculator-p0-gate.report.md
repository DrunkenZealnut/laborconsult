# 계산기 P0 통합 검증 및 비교 평가 고정 버전

> 2026-10-24 · C0·C4a·C3·C1+C7·C2·C4b · 통과

## 릴리스와 증거

| 단계 | PR | 검증 보고서 | 누적 갱신 회귀 |
|---|---|---|---:|
| C4a 미실행 카드 보호 | #126 | [보고서](https://github.com/DrunkenZealnut/laborconsult/blob/codex/wage-update-card-guard/docs/04-report/features/wage-calculator-card-guard.report.md) | 31 |
| C3 연차 | #127 | [보고서](wage-calculator-annual-leave-update.report.md) | 60 |
| C1+C7 육아휴직·단축 | #128 | [보고서](wage-calculator-parental-benefits.report.md) | 89 |
| C2 체불이자 | #129 | [보고서](wage-calculator-arrears-interest.report.md) | 111 |
| C4b 주기·평균임금·휴가 입력 | #130 | [보고서](wage-calculator-pay-inputs.report.md) | 144 |

각 단계의 변경 전후 질문을 동일 fixture로 두 번씩 실행하고 카드와 답변을 읽었다. 통합 버전에서는 전체 오프라인 CI와 PostgreSQL, 공유 입력·카드 회귀, CLI를 다시 실행해 통과했다. 무관한 기능의 숫자 변화는 단계별 보고서에서 추적한다. 공개 HTML을 변경한 C1·C2·C3는 Python·JS 값과 원본·사본 일치 및 화면 렌더를 각 릴리스에서 확인했다. C4b에는 공개 HTML 변경이 없다.

## 지정 변이검사

정상 코드에서 대응 테스트가 통과하는지 확인한 뒤, 별도 Python 프로세스의 메모리에서만 핵심 분기를 변경했다. 파일과 실제 평가 프로세스는 변경하지 않았다. 변이 검출은 예외가 아닌 테스트 assertion 실패로 판정했다.

| 변이 | 대응 테스트 | 변이 감지 / 복구 |
|---|---|---|
| 육아휴직 구 상한 복원 | `test_parental_2026_general_12_months` | 실패 / 통과 |
| 사후지급 25% 복원 | `test_parental_2026_general_12_months` | 실패 / 통과 |
| 체불 개정 경계 하루 이동 | `test_regular_payday_transition_is_cause_based` | 실패 / 통과 |
| 퇴직 시 이자 기산일 재설정 | `test_arrears_retirement_does_not_reset_start` | 실패 / 통과 |
| 현행 연차 첫해 사용분 차감 복원 | `test_annual_first_year_used_not_deducted` | 실패 / 통과 |
| 단축급여 최초 10시간 누락 | `test_reduced_40_to_30_2026` | 실패 / 통과 |
| 미실행 결과에 월급 총액 복원 | `test_direct_skipped_result_has_no_amounts_in_text_or_json` | 실패 / 통과 |

7/7 감지, 복구 7/7 통과. 실행 버전 `b998c40` 이후 `62667da`의 변경은 비과세 참고 문구와 해당 회귀검사다. 위 법률·금액 분기는 동일하며 최종 통합 회귀도 통과했다.

## Q&A 품질 비교의 계산기 고정점

Q&A 코퍼스 갱신 실험에서는 다음 코드와 모델 조건을 양쪽에 고정한다. P1의 일할계산·원금 정산이 진행돼도 이 비교의 계산기를 임의로 바꾸지 않는다.

| 대상 | 고정값 |
|---|---|
| 계산·입력·답변 코드 | `62667da530c2b6cd9217a50b740f81e713e9b2ce` |
| 시행일 규칙 파일 SHA-256 | `b4e343252d24f5da4ce1feb6497ca2d3841c9d31874162a86ed1db1b3eabc73f` |
| 현 BM25 코퍼스 SHA-256 | `7317aaf3b20b964fa9c55326aa27987e62aa7894ec228d16355c05c045b262e3` |
| P0 fixture SHA-256 | `5ebab40216882acc60deef0441969cc22bf107a16032899b1f688dd3aae1bd7d` |
| 외부 평가 runner SHA-256 | `eed6982e0cd098eb67131ccaebdba498680ce3d599d9229597b51cf2ee50352a` |
| 모델 설정 | revision 12, OpenAI 기본 제공자, 실제 모델·폴백 결과는 각 실행 메타데이터에 기록 |
| 법령 조건 | 로컬 `prod` 실패 재현, 대화 저장·운영 L2 쓰기 차단 |

Pinecone·원격 법령 캐시의 외부 변경을 독점 잠근 실험은 아니다. Q&A 갱신 실험 시에는 기존·신규 코퍼스의 namespace/manifest와 원문 ID 목록, 검색·필터 버전, 법령 캐시 조건도 별도로 고정해야 한다. 이 문서는 계산기 고정점을 제공하며, Q&A 갱신이나 사용자 만족도 측정을 수행했다는 뜻은 아니다.

## 완료 판정과 잔여 범위

최종 C4b 실제 답변 12개 확인을 마쳤고 P0 관문을 통과했다. 최종 전체 CI는 PostgreSQL을 포함해 통과했으며, 144개 누적 갱신 회귀와 261개 관련 회귀도 통과했다. P1은 승인된 순서대로 C6 일할계산 → C5 체불 원금·차액 정산을 진행한다. P2/P3는 개별 후속 설계 범위다. 각 PR은 선행 PR 위에 쌓여 있으며 main 병합·운영 배포는 수행하지 않았다.
