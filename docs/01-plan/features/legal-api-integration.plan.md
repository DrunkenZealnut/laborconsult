# Plan: 법제처 국가법령정보 API 연동

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 법조문은 RAG(크롤링 시점 고정), 계산기 하드코딩, LLM 학습 데이터에 의존하여 법 개정 시 최신 정보 반영이 불가능 |
| **Solution** | 법제처 국가법령정보센터 Open API (law.go.kr/DRF) 연동으로 실시간 법령 조문 조회 + 캐싱 + RAG 컨텍스트 주입 |
| **Function UX Effect** | "근로기준법 제56조가 어떻게 되나요?" 질문 시 항상 현행 법률 원문을 인용하여 답변 |
| **Core Value** | 법 개정 즉시 반영 → 오래된 정보로 인한 오답 위험 제거, 법조문 인용의 신뢰도 향상 |

---

## 1. 문제 정의

### 현재 법조문 소스 3가지와 한계

| # | 소스 | 방식 | 한계 |
|---|------|------|------|
| 1 | **RAG (Pinecone)** | nodong.kr Q&A 크롤링 → 임베딩 | 게시글 작성 시점의 법률, 개정 미반영 |
| 2 | **계산기 하드코딩** | `constants.py`, `legal_hints.py` | 코드 수정 배포 전까지 구 법률 유지 |
| 3 | **LLM 학습 데이터** | Claude/GPT/Gemini 학습 시점 | 학습 컷오프 이후 개정 미반영, 환각 위험 |

### 실제 위험 사례
- 2024.12.19 대법원 전원합의체 판결(2023다302838)로 통상임금 판단 기준 변경 — LLM은 구 기준으로 답변할 수 있음
- 최저임금법 시행령 매년 개정 (2025년 10,030원 → 2026년 미정) — `constants.py` 수동 업데이트 필요
- 근로기준법 일부개정 시 시행일 이전/이후 조문 혼동 가능

---

## 2. API 조사 결과

### 2.1 법제처 국가법령정보센터 Open API (채택)

| 항목 | 내용 |
|------|------|
| **제공 기관** | 법제처 (Ministry of Government Legislation) |
| **포털** | open.law.go.kr |
| **비용** | 무료 |
| **인증** | `OC=사용자ID` 파라미터 (OAuth 불필요) |
| **응답 형식** | XML (기본), HTML |
| **API 키** | 환경변수 `LAW_API_KEY`로 관리 |

### 2.2 핵심 엔드포인트

| 엔드포인트 | URL | 용도 |
|-----------|-----|------|
| 법령 검색 | `http://www.law.go.kr/DRF/lawSearch.do` | 법령명으로 검색, MST(일련번호) 획득 |
| 법령 본문 | `http://www.law.go.kr/DRF/lawService.do` | MST로 전체 조문 조회 |
| 조문 조회 | `lawService.do?target=lawjosub` | 특정 조·항·호 단위 조회 |
| 판례 검색 | `lawSearch.do?target=prec` | 대법원 판례 검색 |
| 판례 본문 | `lawService.do?target=prec` | 판례 전문 조회 |
| 법령해석례 | `lawSearch.do?target=expc` | 행정해석(질의회시) 검색 |

### 2.3 주요 파라미터

| 파라미터 | 설명 | 예시 |
|---------|------|------|
| `OC` | 사용자 ID (인증) | `OC=myid123` |
| `target` | 데이터 유형 | `law`, `prec`, `expc` |
| `type` | 응답 형식 | `XML`, `HTML` |
| `query` | 검색어 | `근로기준법` |
| `MST` | 법령 일련번호 | `270551` |
| `display` | 페이지당 결과 수 | `100` |
| `page` | 페이지 번호 | `1` |

### 2.4 대안 검토

| 옵션 | 장점 | 단점 | 결론 |
|------|------|------|------|
| **법제처 DRF API** | 무료, 간단 인증, 공식 데이터 | XML 파싱 필요 | **채택** |
| data.go.kr 공공데이터포털 | serviceKey 방식 | 별도 신청 필요, 동일 데이터 | 불필요한 중복 |
| MCP Server (mcp-kr-legislation) | 130+ 도구 | 별도 서버 운영 필요 | 과도한 의존성 |
| 직접 크롤링 | 자유도 높음 | 법적 리스크, 불안정 | 부적절 |

---

## 3. 기능 범위

### 3.1 포함 (In Scope)

#### Phase 1: 법령 조문 조회 (MVP)
- 법령 API 클라이언트 모듈 (`app/core/legal_api.py`)
- 법령명 → MST 매핑 테이블 (노동법 관련 10개 법률 사전 등록)
- 특정 조문 조회 함수 (`fetch_article("근로기준법", 56)` → 제56조 전문)
- 인메모리 캐시 (TTL 24시간) — 동일 조문 반복 조회 방지
- `pipeline.py` 연동: 의도 분석에서 추출된 `relevant_laws` 기반 자동 조회
- LLM 컨텍스트에 `[현행 법조문]` 블록으로 주입

#### Phase 2: 판례·해석례 연동 (확장)
- 판례 검색 (`search_precedent("통상임금")`)
- 법령해석례 검색 (`search_interpretation("연장근로")`)
- RAG 결과와 병합하여 컨텍스트 보강

### 3.2 제외 (Out of Scope)
- 영문 법령 조회
- 자치법규 (지방 조례)
- 법령 개정 이력 비교 (3단 대비표)
- 법률 전문 다운로드/저장
- Pinecone에 법령 데이터 업로드 (별도 배치 작업으로 분리)

---

## 4. 기술 전략

### 4.1 아키텍처

```
사용자 질문
    ↓
의도 분석 (ANALYZE_TOOL)
    ↓ relevant_laws 추출 (예: ["근로기준법 제56조", "최저임금법 제6조"])
    ↓
┌─────────────────────────────────────────────┐
│ [신규] 법령 API 조회                          │
│  ① 법령명 파싱 ("근로기준법" + "제56조")       │
│  ② 캐시 확인 → 히트 시 즉시 반환              │
│  ③ 미스 시 API 호출 → XML 파싱 → 캐시 저장    │
│  ④ 조문 텍스트 반환                           │
└─────────────────────────────────────────────┘
    ↓
임금계산기 실행 (기존)
    ↓
RAG 검색 (기존 Pinecone)
    ↓
메시지 조립:
  [참고 문서] + [현행 법조문] + [계산기 결과] + [질문]
    ↓
LLM 답변 생성 (fallback: Claude → OpenAI → Gemini)
```

### 4.2 노동법 MST 매핑 테이블

사전 등록할 법령 목록 (법령 검색 API 호출 최소화):

| 법령명 | 약칭 | 예상 MST | 주요 조문 |
|--------|------|---------|----------|
| 근로기준법 | labor_standards | 조회 필요 | 제2조, 제11조, 제18조, 제46조, 제50조, 제56조, 제57조, 제60조 |
| 최저임금법 | minimum_wage | 조회 필요 | 제5조, 제6조, 제28조 |
| 고용보험법 | employment_insurance | 조회 필요 | 제40조, 제69조, 제70조, 제75조 |
| 산업재해보상보험법 | industrial_accident | 조회 필요 | 제52조, 제54조, 제57조, 제62조, 제66조, 제71조 |
| 근로자퇴직급여보장법 | retirement_pension | 조회 필요 | 제4조, 제8조, 제9조 |
| 남녀고용평등과 일·가정 양립 지원에 관한 법률 | equal_employment | 조회 필요 | 제14조, 제19조 |
| 소득세법 | income_tax | 조회 필요 | 제48조, 제59조 |
| 조세특례제한법 | tax_special | 조회 필요 | 제100조의5, 제100조의27 |
| 근로기준법 시행령 | labor_standards_decree | 조회 필요 | 제6조의2 |
| 최저임금법 시행령 | minimum_wage_decree | 조회 필요 | 제5조의2 |

### 4.3 캐싱 전략

```python
# 인메모리 캐시 (서버리스 환경 고려)
CACHE = {}  # key: "근로기준법_제56조" → value: (timestamp, article_text)
CACHE_TTL = 86400  # 24시간

# Vercel serverless 콜드스타트 시 캐시 초기화됨
# → 법령은 자주 바뀌지 않으므로 24시간 TTL 충분
# → 향후 Redis/Supabase 캐시 테이블로 확장 가능
```

### 4.4 법조문 참조 파싱 규칙

`relevant_laws` 배열에서 법령명과 조문 번호를 추출:

| 입력 패턴 | 파싱 결과 |
|----------|----------|
| `"근로기준법 제56조"` | 법령=근로기준법, 조=56 |
| `"최저임금법 제6조 제2항"` | 법령=최저임금법, 조=6, 항=2 |
| `"고용보험법 제70조"` | 법령=고용보험법, 조=70 |
| `"대법원 2023다302838"` | → 판례 검색 (Phase 2) |

### 4.5 에러 처리

| 상황 | 처리 |
|------|------|
| API 타임아웃 (>5초) | 무시하고 기존 RAG만으로 진행 |
| MST 미발견 | 법령 검색 API로 동적 조회 시도, 실패 시 생략 |
| XML 파싱 오류 | 로깅 후 생략, 기존 흐름 유지 |
| API 키 미설정 | 기능 비활성화, 기존 방식으로 동작 |
| Rate limit | 0.5초 딜레이 삽입, 초과 시 캐시된 결과만 사용 |

---

## 5. 변경 대상 파일

| # | 파일 | 변경 유형 | 설명 |
|---|------|----------|------|
| 1 | `app/core/legal_api.py` | **신규** | 법제처 API 클라이언트, XML 파싱, 캐시, 조문 조회 |
| 2 | `app/core/pipeline.py` | 수정 | `relevant_laws` 기반 법령 API 호출 → 컨텍스트 주입 |
| 3 | `app/config.py` | 수정 | `LAW_API_KEY` 환경변수 추가, AppConfig 필드 추가 |
| 4 | `.env.example` | 수정 | `LAW_API_KEY` 예시 추가 |
| 5 | `requirements.txt` | 확인 | `requests`는 이미 포함 (XML 파싱은 stdlib `xml.etree`) |

### 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `wage_calculator/constants.py` | 하드코딩 상수는 계산기 정확도 위해 유지 (API 장애 대비 기준값) |
| `wage_calculator/legal_hints.py` | 조건부 법적 힌트 로직은 계산기 전용 |
| `chatbot.py` | CLI 전용, API 통합은 pipeline.py만 |
| Pinecone 데이터 | 기존 RAG 데이터는 유지, 법령 API는 보조 소스 |

---

## 6. 환경변수 설계

```bash
# .env
LAW_API_KEY=a0b5fdbe24bf7f5d77b5c3a807e64aa961735cc7831e6b093614c2c1a440f6af

# 선택적 설정
LAW_API_CACHE_TTL=86400        # 캐시 유효시간(초), 기본 24시간
LAW_API_TIMEOUT=5              # API 타임아웃(초), 기본 5초
LAW_API_ENABLED=true           # 기능 ON/OFF 토글
```

---

## 7. 검증 시나리오

| # | 입력 | 기대 결과 |
|---|------|----------|
| 1 | "근로기준법 제56조가 뭔가요?" | 현행 제56조 원문을 인용하여 답변 |
| 2 | "연장근로수당 계산해주세요" (관련 법조문 자동 추출) | 계산 결과 + 근로기준법 제56조 현행 조문 포함 |
| 3 | "최저임금이 얼마인가요?" | 최저임금법 제5조 현행 조문 + 2025년 최저임금 |
| 4 | API 키 미설정 상태 | 기존 방식(RAG+LLM)으로 정상 동작, 경고 로그 |
| 5 | API 타임아웃 발생 | 타임아웃 후 기존 RAG만으로 답변 생성 |
| 6 | 동일 조문 2회 질문 | 2번째는 캐시에서 즉시 반환 (API 미호출) |
| 7 | `relevant_laws` 없는 일반 질문 | 법령 API 호출 안 함, 기존 흐름 유지 |
| 8 | "대법원 2023다302838 판례 알려줘" | (Phase 2) 판례 검색 결과 반환 |

---

## 8. 구현 순서

```
Step 1: app/config.py — LAW_API_KEY 환경변수 + AppConfig 필드
Step 2: app/core/legal_api.py — API 클라이언트 (검색 + 조문조회 + 캐시)
Step 3: app/core/pipeline.py — relevant_laws → 법령 API → 컨텍스트 주입
Step 4: .env.example 업데이트
Step 5: 통합 테스트 (로컬 서버에서 질문 → 법조문 포함 답변 확인)
```

---

## 9. 참고 자료

- 국가법령정보 공동활용 포털: https://open.law.go.kr/LSO/main.do
- API 활용 가이드: https://open.law.go.kr/LSO/openApi/guideList.do
- 법령 검색 API: `http://www.law.go.kr/DRF/lawSearch.do`
- 법령 본문 API: `http://www.law.go.kr/DRF/lawService.do`
- 조문 조회 API 가이드: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwJoListGuide
- 판례 조회 API 가이드: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=precListGuide
