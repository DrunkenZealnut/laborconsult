# 노동OK Q&A 갱신·복구 운영

기준일: 2026-10-24. 실행 명령은 저장소 루트에서 사용한다. 원문·백업·평가 답변은 접근 제한된 저장소 밖 디렉터리에 둔다. 아래 `RUN`은 실행마다 새로 정하는 전용 경로이며, 같은 실행을 재개할 때만 재사용한다.

## 1. 수집

```bash
umask 077
RUN=/private/path/nodong-qa-YYYYMMDD
python crawl_qna_refresh.py \
  --source-dir /path/output_qna --source-dir /path/output_qna_2 \
  --run-dir "$RUN/crawl" --since 2026-03-01 --end-page 100 \
  --revisit-pending --delay 1
```

처음의 종료 시각이 state에 고정된다. 동일 명령으로 재개하면 성공한 페이지·글은 건너뛰고 실패를 다시 시도한다. `report.json.complete=false`, 실패 페이지·ID, 날짜 불명, 미방문 ID는 정상 갱신으로 처리하지 않는다. 접근 실패는 글 삭제가 아니다.

재시도 후에도 원문을 확인할 수 없는 글은 실패로 남긴다. 운영자가 실패 ID 전부를 명시한 `--quarantine-id ID`를 prepare/manifest에 넘기면 그 글의 기존 원문·벡터를 유지한 채 성공 문서만 후보로 만들 수 있다. 페이지 실패·미방문·날짜 불명에는 이 예외를 허용하지 않는다. 격리 목록은 후보 manifest와 보고서에 남으며 원본 수집 report의 complete=false를 바꾸지 않는다.

완료 후 다음 수집의 기준 manifest를 만든다. **수집 완료와 검색 배포 완료는 별도 상태다.**

```bash
python qna_update.py manifest --crawl "$RUN/crawl" --output "$RUN/collection-manifest.json"
```

다음 실행은 `--source-dir` 대신 `--baseline-manifest "$PREVIOUS/collection-manifest.json"`을 사용한다. 최근 30일을 `--since`로 주고 미답변 글을 재방문한다. 월간 점검 때 오래된 목록 페이지 구간을 `--start-page/--end-page`로 순환한다. 목록 정렬/공지 변화가 있으므로 첫 오래된 글에서 멈추지 않는다. 전체 사이트를 확인했다고 보고하지 않는다.

현재 주간·월간 자동 예약은 만들지 않았다. 예약을 적용할 때는 별도 실행 계정·실패 통지 수단·비용 한도를 정한다.

## 2. 갱신 전 백업과 후보

실제 인덱스는 `laborconsult`다. qa 전체 초기화·기존 업로더 `--reset`은 사용하지 않는다.

- `qa`, `counsel`, `laborlaw-v2`의 전체 ID 목록과 값·메타데이터를 보관한다.
- 스냅샷 형식: `<namespace>/ids.json`, 번호별 `*.json.gz`(ID→벡터 사전), 검증 후 `complete.json`의 count. `qna_snapshot.iter_namespace`가 ID·개수·샤드 완전성을 확인한다.
- 배포 중인 BM25와 사용자 로컬 수정본을 따로 보관한다.
- `qna_snapshot.clone_qa(snapshot, index, namespace, ledger, source_namespace=...)`로 소유한 `qa-eval-*` namespace에 복사한다. 기존 자료가 있는 미소유 namespace는 거부한다. before/after의 qa와 공통 counsel/laborlaw-v2를 각각 고정한다.
- 명령 중단 후 같은 장부로 재개한다. 동일한 벡터는 실제 fetch 확인 후 재사용한다. `complete.json` 없이 다음 단계로 넘어가지 않는다.

```bash
python qna_update.py prepare --crawl "$RUN/crawl" --candidate "$RUN/candidate"
```

`manifest.json`의 문서 수·청크 수·embedding_tokens를 먼저 검토한다. 모델은 text-embedding-3-small, 1536차원, 청킹700/중첩80이다. 과거 qa가 contextualized=false였으므로 이 비교는 맥락 생성 모델을 추가하지 않는다. 신규/변경 외에 기존 미답변 문서는 잘못 저장된 로그인 안내를 지우기 위해 재구성한다.

```bash
python qna_update.py embed --candidate "$RUN/candidate"
python qna_update.py apply --candidate "$RUN/candidate" \
  --namespace qa-eval-after-YYYYMMDD --ledger "$RUN/apply-candidate"
python qna_update.py build --candidate "$RUN/candidate" \
  --snapshot "$RUN/vectors-before" --output "$RUN/bm25-after.jsonl.gz"
```

새 청크 upsert→fetch 대조→해당 글의 잔여 청크 삭제→정확한 ID 대조 후에만 완료 장부를 쓴다. 중단 중에는 구/신 청크가 함께 있을 수 있으므로 후보를 운영에 연결하지 않는다. 다른 글·소스는 삭제 범위에 들어가지 않는다.

## 3. 검증

- before/after 벡터와 BM25에서 표본 신규·수정·과거 글의 document_version, ID, 날짜를 대조한다.
- namespace별 청크 수와 삭제·추가 장부를 설명한다. 빈 namespace/20% 초과 감소는 중단한다.
- `QNA_EVAL_BM25_PATH="$RUN/bm25-after.jsonl.gz" python test_bm25_memory.py`: 기존550MB 관문을 유지한다.
- `python -m app.core.stale_rules --path "$RUN/bm25-after.jsonl.gz" --output "$RUN/stale-matches.jsonl"`: 표본 출력만 보지 말고 신규/변경 제외 전량을 검토한다.
- 자동 단위·통합 검증은 `.github/workflows/tests.yml`을 실행한다.

A/B/C는 같은 커밋·설정·법령 캐시를 쓴다. A는 nodong_qna만 제외하고 후보 자리는 기존 검색 예산 안에서 다른 자료가 채운다. qa 전체나 counsel을 끄지 않는다. 모든 조건에 같은 Q3 시점 필터를 사용하므로 이 비교는 코퍼스 효과이며 Q3 단독 개선 실험이 아니다.

```bash
export QNA_EVAL_MODE=with                     # A=without, B/C=with
export QNA_EVAL_NAMESPACE=qa-eval-before-YYYYMMDD # C=after
export QNA_EVAL_BM25_PATH="$RUN/bm25-before.jsonl.gz" # C=after
export QNA_EVAL_FIXED_NAMESPACES='{"counsel":"qa-eval-fixed-counsel-YYYYMMDD","laborlaw-v2":"qa-eval-fixed-laborlaw-v2-YYYYMMDD"}'
python qna_evaluation.py --frozen "$RUN/evaluation-frozen.json" \
  --fixture data/eval_consultation_queries.json --fixture data/eval_kin_queries.json \
  --fixture data/eval_qna_queries.json --condition B --out "$RUN/eval-B.json"
```

`evaluation-frozen.json`은 유효 법령 캐시·모델 설정·법률 기준 registry를 읽기 전용으로 보관한 자료다. 하네스가 런타임 DB 접근·캐시 쓰기를 막으며 운영 HTTP 상담/관리자 평가 게시를 호출하지 않는다. 차단된 DB 시도가 하나라도 있으면 그 실행은 무효다. 반환된 API 토큰 사용량을 남기되, 누락된 공급자 사용량이나 청구서 비용을 측정했다고 표시하지 않는다.

자동 형식 통과율, 숫자·단위 언급, 조건을 가린 사람의 법률·계산·유용성 평가를 구분한다. `data/eval_qna_rubric.json`이 신규 경계 사례의 검토 기준이다. 사람 평가가 비어 있으면 법률 정확도 관문은 미완료다. 반복실행 수와 표본 수를 보고서에 명시한다.

## 4. 운영 반영 관문

검증 결과와 manifest를 리뷰한 뒤 운영 반영한다. `gate.json`은 승인된 candidate_version과 `passed:true`를 가진 기록이다. 자동 키워드 통과만으로 작성하지 않는다.

1. 새 BM25/코드 배포 산출물·복구본을 먼저 준비한다.
2. 갱신 중 검색 버전 혼합을 피할 유지보수 구간 또는 명시적 버전 라우팅을 사용한다. 두 저장소를 원자적으로 교체한다고 가정하지 않는다.
3. 운영 문서 교체:

```bash
python qna_update.py apply --candidate "$RUN/candidate" --namespace qa \
  --ledger "$RUN/apply-production" --production --gate "$RUN/gate.json"
```

4. 운영 벡터 검증 후 새 BM25와 builder가 생성한 `qa_legacy_versions.json.gz`를 함께 `data/`에 포함하여 교체하고, `data/qa_corpus_release.json`에 corpus_version/calculator_version/answer_code_version을 기록한다.
5. 운영의 두 검색 경로를 재확인한 후 정상 완료로 표시한다. 부분 실패 시 새 BM25를 배포하지 않는다.

## 5. 복구

실패 실행의 `apply-production/<post_id>/before.json`에는 덮어쓰기 전 값과 메타데이터가 있다. ID 목록만으로는 복구할 수 없다.

```bash
python qna_update.py restore --namespace qa --production \
  --ledger "$RUN/apply-production" --post-id POST_ID
```

영향받은 모든 문서에 반복한다. 원래 벡터 복원·fetch 대조 후 새 잔여 ID만 제거한다. 기존 문서가 없던 신규 글은 이 실행에서 추가한 청크만 제거된다. 이어서 **같은 백업 시점의 BM25·legacy 버전 맵·release 메타데이터**를 복원하고 Dense/BM25 문서 버전을 다시 확인한다. 다른 실행이 이후 같은 글을 변경한 경우 먼저 장부를 대조한다. 과거 장부를 무조건 덮어쓰지 않는다.

## 6. 내부 추적·사용자 의견

`supabase_qa_quality.sql`을 검토·적용하고 API/화면과 release 메타데이터를 배포한 후 `QA_QUALITY_ENABLED=true`로 켠다. 기본값은 꺼짐이다. 앱 공개 DB 역할에 쓰기 권한을 추가하지 않는다. 별도 서비스 역할만 내부 테이블/RPC를 사용한다.

- 실제 웹 답변 저장 성공 후에만 추적을 저장하고 서명된 의견 토큰을 발급한다. 합성/평가/절단 답변 제외.
- 토큰은 대화·세션·버전에 묶이며14일 유효하다. 화면 노출 확인 후 투표한다.
- 같은 투표는 멱등, 변경은 최소10초 간격이다. API는 IP당분당30회 제한(인스턴스별), DB는 대화행 잠금으로 변경 제한을 보장한다.
- 부정 사유는 선택식이며 원문·자유서술을 복제하지 않는다. 대화 삭제 시 내부 행도 삭제된다.
- 관리자: 긍정/유효투표, 유효투표/노출, 표본·부정사유·버전, 검색 후보/공급 수. 30건 미만은 탐색적, 그 이상도 자발적 응답 편향을 함께 표시한다.
- 4주 관찰은 출시 후 수행한다. 현재 사용자의 만족도 개선을 측정한 것으로 쓰지 않는다.

변경하지 않은 기존 글의 Dense 메타데이터에는 문서 해시가 없을 수 있다. 검증한 스냅샷의 게시글별 legacy 버전 맵을 BM25와 함께 배포하여 두 검색 경로가 같은 버전을 기록하게 한다. 다른 업로더가 이후 같은 문서를 갱신하면 이 맵도 새 스냅샷으로 재생성해야 한다.
