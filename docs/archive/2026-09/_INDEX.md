# Archive Index — 2026-09

| Feature | Match Rate | Archived Date | Documents |
|---------|:----------:|:-------------:|:---------:|
| precedent-archive | 97% | 2026-09-02 | [Plan](precedent-archive/precedent-archive.plan.md), [Design](precedent-archive/precedent-archive.design.md), [Analysis](precedent-archive/precedent-archive.analysis.md), [Report](precedent-archive/precedent-archive.report.md) |
| yeoncha-corpus-cycle | 90% | 2026-09-06 | [Report](yeoncha-corpus-cycle/yeoncha-corpus-cycle.report.md) ※ |
| deferred-items-batch | 미측정 ※※ | 2026-09-07 | [Report](deferred-items-batch/deferred-items-batch.report.md) ※ |
| crawl-precedent-production-ns | 94.8% | 2026-09-15 | [Plan](crawl-precedent-production-ns/crawl-precedent-production-ns.plan.md), [Design](crawl-precedent-production-ns/crawl-precedent-production-ns.design.md), [Analysis](crawl-precedent-production-ns/crawl-precedent-production-ns.analysis.md), [Report](crawl-precedent-production-ns/crawl-precedent-production-ns.report.md) |
| nlrc-decisions-corpus | 96% | 2026-09-16 | [Plan](nlrc-decisions-corpus/nlrc-decisions-corpus.plan.md), [Design](nlrc-decisions-corpus/nlrc-decisions-corpus.design.md), [Report](nlrc-decisions-corpus/nlrc-decisions-corpus.report.md) ※※※ |

※ **두 사이클 모두 Report만 있다.** 신규 Plan/Design 없이 기존 설계(또는 직전
사이클의 이월 표)를 입력으로 삼은 증분 사이클이라 그 문서들이 애초에 생성되지
않았다 — 누락이 아니다.
  · `yeoncha-corpus-cycle`: Do → Check → Report. 승계 설계 6종은 Report §1의 표에
    있고(`textbook-corpus-embedding`·`textbook-corpus-followup`·
    `textbook-retrieval-balance`·`precedent-corpus-expansion`·`precedent-archive`·
    `bm25-memory-scaling`), Check는 별도 analysis 문서 없이 gap-detector 결과를
    Report §3에 직접 실었다.
  · `deferred-items-batch`: Do → Report. 입력이 `yeoncha-corpus-cycle` Report §6의
    이월 표다.

※※ **Match Rate를 일부러 측정하지 않았다.** 대조할 설계 문서가 없어 gap-detector가
답하는 질문("설계대로 만들었는가")이 성립하지 않는다. 수치를 만들어 붙이는 대신
이월 항목별 이행을 직접 검증했고 그 표가 Report §3에 있다.

※※※ **Analysis 문서가 없다** — gap-detector의 대조 대상이 Design 문서 자체였고
발견된 Gap 전부가 Design의 해당 절을 직접 수정하는 형태로 해소돼, Design과
분리된 별도 기록의 실익이 적었다. Check 결과·Gap 목록·Act 조치는 Design
문서 §11("Check 결과")에 직접 있다. `yeoncha-corpus-cycle`이 Check를 Report에
접은 것과 같은 판단이며, 이번엔 Design에 접었다는 점만 다르다.
