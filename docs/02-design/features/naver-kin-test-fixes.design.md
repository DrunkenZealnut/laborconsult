# 네이버 지식iN 테스트 보완 Design Document

> **Summary**: 면책 고지 강화 + 환각 교정 모델 최적화 + 테스트 자동화 상세 설계
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-20
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/naver-kin-test-fixes.plan.md`
> **Branch**: `feat/naver-kin-test-improvements`

---

## 1. FR-01: 시스템 프롬프트 면책 고지 강화 (구현 순서 1번)

### 1.1 변경 파일

| 파일 | 변경 유형 | 위치 |
|------|----------|------|
| `app/core/pipeline.py` | 수정 | `SYSTEM_PROMPT_TEMPLATE` (726~797행) |

### 1.2 현재 문제

`SYSTEM_PROMPT_TEMPLATE`의 답변 원칙 14번(마지막 규칙)에 면책 고지가 위치:

```python
14. **면책 고지** (반드시 포함):
   "본 답변은 참고용 정보 제공이며 법적 효력이 없습니다.
   구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."
```

LLM은 프롬프트의 후반부 규칙을 누락하는 경향이 있으며, 특히 긴 컨텍스트(판례+법조문+계산결과) 제공 시 면책 규칙의 준수율이 떨어짐.

### 1.3 변경 설계

**전략**: 면책 규칙을 "답변 원칙" 최상단(2번)으로 이동하고, 14번 위치에도 유지하여 **이중 강조**. 또한 "반드시" → "**절대 규칙**"으로 강도 상향.

#### 변경 전 (pipeline.py:731~)

```
답변 원칙:
1. **임금계산기 결과가 포함된 경우** (가장 중요): ...
2. 참고 자료 ...
```

#### 변경 후

```
답변 원칙:
1. **임금계산기 결과가 포함된 경우** (가장 중요): ...
2. **면책 고지** (절대 규칙 — 모든 답변에 반드시 포함):
   답변의 마지막에 아래 면책 문구를 `---` 구분선 아래에 반드시 포함하세요.
   이 규칙은 예외 없이 모든 답변에 적용됩니다:
   "---
   ⚠️ 본 답변은 참고용 정보 제공이며 법적 효력이 없습니다.
   구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."
3. 참고 자료(판례·행정해석·법조문) ...  (기존 2번 → 3번으로 이동)
```

기존 14번 면책 규칙도 유지하되 "위 2번 규칙 참고"로 변경.

#### 구체적 코드 변경

`SYSTEM_PROMPT_TEMPLATE` 내 답변 원칙 블록에서:

```python
# 기존 1번 규칙 바로 뒤에 삽입
"2. **면책 고지** (절대 규칙 — 모든 답변에 반드시 포함):\n"
"   답변의 마지막에 아래 면책 문구를 `---` 구분선 아래에 반드시 포함하세요.\n"
"   이 규칙은 예외 없이 모든 답변에 적용됩니다:\n"
'   "---\n'
"   ⚠️ 본 답변은 참고용 정보 제공이며 법적 효력이 없습니다.\n"
'   구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."\n'
```

그리고 기존 2~13번 규칙 번호를 3~14번으로 리넘버링. 기존 14번(면책)은 15번으로 변경하고 내용을 "위 2번 참고"로 축약.

### 1.4 기대 효과

- 면책 포함률: 20% → 90%+ (프롬프트 최상단 + 이중 강조)
- `---` 구분선 지시로 면책 문구가 답변 본문과 분리되어 시각적으로 명확

---

## 2. FR-02: 환각 교정 모델 최적화 (구현 순서 2번)

### 2.1 변경 파일

| 파일 | 변경 유형 | 위치 |
|------|----------|------|
| `app/core/citation_validator.py` | 수정 | `correct_hallucinated_citations()` (199~268행) |

### 2.2 현재 문제

```
현재 순서: Gemini 2.5 Pro (1순위, ~40초) → OpenAI o3 (2순위, ~30초)
```

Gemini 2.5 Pro는 응답 품질이 높지만 응답 시간이 30~40초로 전체 파이프라인의 병목. 환각 판례 교정은 "판례 번호 제거 + 대체 문구 삽입"이라는 단순 작업이므로 가벼운 모델로 충분.

### 2.3 변경 설계

```
변경 후: Claude Haiku (1순위, ~3초) → Gemini (2순위) → OpenAI (3순위)
```

함수 시그니처에 `anthropic_client` 파라미터 추가:

```python
def correct_hallucinated_citations(
    response_text: str,
    hallucinated: list[str],
    anthropic_client=None,     # ← 추가 (1순위)
    gemini_api_key: str | None = None,
    openai_client: object | None = None,
) -> str | None:
```

Haiku 호출 블록을 Gemini 블록 **앞에** 삽입:

```python
    CORRECTION_MODEL = "claude-haiku-4-5-20251001"
    CORRECTION_TIMEOUT = 5.0

    # 1순위: Claude Haiku (빠른 응답)
    if anthropic_client:
        try:
            resp = anthropic_client.messages.create(
                model=CORRECTION_MODEL,
                max_tokens=3000,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
                timeout=CORRECTION_TIMEOUT,
            )
            text = resp.content[0].text.strip()
            if text and len(text) > len(response_text) * 0.7:
                logger.info("Haiku 판례 교정 완료: %d개 환각 제거", len(hallucinated))
                return text
        except Exception as e:
            logger.warning("Haiku 판례 교정 실패: %s", e)

    # 2순위: Gemini (기존)
    # 3순위: OpenAI (기존)
```

### 2.4 pipeline.py 호출부 변경

현재 (`pipeline.py` ~1272행):
```python
corrected = correct_hallucinated_citations(
    response_text=full_text,
    hallucinated=citation_check["hallucinated"],
    gemini_api_key=config.gemini_api_key,
    openai_client=config.openai_client,
)
```

변경 후:
```python
corrected = correct_hallucinated_citations(
    response_text=full_text,
    hallucinated=citation_check["hallucinated"],
    anthropic_client=config.claude_client,     # ← 추가
    gemini_api_key=config.gemini_api_key,
    openai_client=config.openai_client,
)
```

### 2.5 기대 효과

- 환각 교정 시간: 40초 → 3~5초 (Haiku 성공 시)
- 전체 응답 시간: 89.9초 → ~55초 예상
- Haiku 실패 시 Gemini→OpenAI 폴백 유지 (기존 안전성 보장)

---

## 3. FR-03: 테스트 자동화 스크립트 (구현 순서 3번)

### 3.1 파일 위치

| 파일 | 변경 유형 |
|------|----------|
| `test_naver_kin.py` | **신규** — 프로젝트 루트에 생성 |

### 3.2 기능 명세

```
사용법:
  python3 test_naver_kin.py                         # 분야별 대표 10건 테스트
  python3 test_naver_kin.py --all                   # 198건 전량 테스트
  python3 test_naver_kin.py --count 20              # 랜덤 20건 테스트
  python3 test_naver_kin.py --field 근로기준         # 특정 분야만 테스트

출력:
  test_sample/naver_kin_608_test_results.md          # 마크다운 보고서 (덮어쓰기)
  test_sample/naver_kin_608_test_results.json        # JSON 원본 데이터
```

### 3.3 품질 지표 자동 검증

보고서 말미에 자동 품질 검증 섹션 추가:

```markdown
## 품질 지표

| 지표 | 목표 | 실제 | 상태 |
|------|------|------|------|
| 성공률 | 100% | 100% | PASS |
| 면책 고지 포함률 | ≥90% | 90% | PASS |
| 평균 응답 시간 | ≤60초 | 55초 | PASS |
| 환각 판례 감지 | 보고만 | 1건 | INFO |
| 기관 연락처 포함률 | ≥80% | 100% | PASS |
```

### 3.4 핵심 로직

```python
# 품질 검증 함수
def verify_quality(results):
    checks = []

    # 면책 포함률
    disclaimer_markers = ['법적 효력', '참고용', '공인노무사']
    has_disclaimer = sum(
        1 for r in results
        if any(m in r['answer'] for m in disclaimer_markers)
    )
    rate = has_disclaimer / len(results) * 100
    checks.append(("면책 고지 포함률", "≥90%", f"{rate:.0f}%", rate >= 90))

    # 평균 응답 시간
    avg_time = sum(r['elapsed'] for r in results) / len(results)
    checks.append(("평균 응답 시간", "≤60초", f"{avg_time:.1f}초", avg_time <= 60))

    # 성공률
    success = sum(1 for r in results if not r['error'])
    success_rate = success / len(results) * 100
    checks.append(("성공률", "100%", f"{success_rate:.0f}%", success_rate == 100))

    # 기관 연락처
    contact_markers = ['1350', '1588-0075', '고용노동부', '근로복지공단', '노동위원회', '고용센터']
    has_contact = sum(
        1 for r in results
        if any(m in r['answer'] for m in contact_markers)
    )
    contact_rate = has_contact / len(results) * 100
    checks.append(("기관 연락처 포함률", "≥80%", f"{contact_rate:.0f}%", contact_rate >= 80))

    return checks
```

---

## 4. 구현 순서 및 의존성

```
Phase 1: FR-01 (시스템 프롬프트 면책 강화)
    ↓
Phase 2: FR-02 (환각 교정 모델 전환)
    ↓
Phase 3: FR-03 (테스트 자동화 스크립트)
    ↓
Phase 4: 10건 재테스트 → 결과 비교
```

---

## 5. 변경 영향도 요약

| 파일 | 변경 유형 | 예상 줄 수 | FR |
|------|----------|:----------:|-----|
| `app/core/pipeline.py` | 수정 | ~15줄 | FR-01 |
| `app/core/citation_validator.py` | 수정 | ~20줄 | FR-02 |
| `test_naver_kin.py` | **신규** | ~180줄 | FR-03 |

**총계**: 수정 2개 + 신규 1개. ~215줄.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-20 | Initial design — 3 FRs detailed | Claude |
