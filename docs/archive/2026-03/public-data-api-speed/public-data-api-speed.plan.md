# Plan: 법령/판례 등 공공데이터 API 연결 속도 개선

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 법제처 API 호출이 순차적(MST 조회 → 조문 조회 × 5건)이라 최악 50초 지연. Vercel 콜드스타트마다 캐시 초기화로 첫 응답이 특히 느림 |
| **Solution** | 병렬 조회(asyncio/concurrent), 영속 캐시(Supabase/파일), MST 사전 매핑, 판례 API Phase 2 병합 |
| **Function UX Effect** | 법조문 포함 답변의 지연 시간 5~25초 → 1~3초로 단축. "법조문 로딩 중..." 메시지가 거의 사라짐 |
| **Core Value** | 실시간 법조문 조회가 체감상 즉각 응답이 되어, RAG 전용 모드와 동일한 속도감 제공 |

---

## 1. 문제 정의

### 1.1 현재 성능 병목

| # | 병목 | 위치 | 영향 |
|---|------|------|------|
| 1 | **순차 API 호출** | `fetch_relevant_articles()` → 최대 5건 순차 fetch | 5건 × (MST + 조문) = 최대 10회 HTTP 호출 |
| 2 | **MST 이중 조회** | MST 캐시 미스 시 매번 법령 검색 API 호출 | 동일 법령이라도 첫 호출 시 2회 API 필요 |
| 3 | **인메모리 캐시 휘발** | `_MST_CACHE`, `_ARTICLE_CACHE` = Python dict | Vercel 콜드스타트마다 초기화 → 모든 조회 재시작 |
| 4 | **HTTP (비HTTPS)** | `http://www.law.go.kr/DRF/...` | TLS 미사용, 일부 환경에서 리다이렉트 발생 가능 |
| 5 | **연결 풀 미사용** | 매 호출마다 `requests.get()` 새 연결 | TCP handshake 반복 (약 100ms/회) |
| 6 | **판례 API 미구현** | `parse_law_reference` → "대법원 YYYY다NNNNN" → None | Phase 2 미착수 상태, 판례 질문 시 빈 결과 |
| 7 | **5초 타임아웃** | `LAW_API_TIMEOUT = 5` | law.go.kr 응답 지연 시 대기 시간이 체감됨 |

### 1.2 현재 호출 시퀀스 (Worst Case)

```
사용자 질문 → analyze → relevant_laws: ["근기법 제56조", "근기법 제60조", "최임법 제6조"]
                                                        ↓
                                        fetch_relevant_articles()
                                                        ↓
  [순차 1] parse → _lookup_mst("근로기준법") → API 호출 (5s)
           fetch_article(근로기준법, 56) → API 호출 (5s)
  [순차 2] parse → _lookup_mst("근로기준법") → 캐시 히트
           fetch_article(근로기준법, 60) → API 호출 (5s)
  [순차 3] parse → _lookup_mst("최저임금법") → API 호출 (5s)
           fetch_article(최저임금법, 6) → API 호출 (5s)
                                                        ↓
                                총 지연: 최대 25초 (API 응답 지연 시)
```

### 1.3 실측 데이터 (예상)

| 시나리오 | 현재 예상 지연 | 목표 |
|---------|-------------|------|
| 캐시 히트 (모든 조문) | ~0ms | ~0ms (유지) |
| 인메모리 캐시 미스, 단일 조문 | 2~5초 | <1초 |
| 콜드스타트, 3개 법조문 | 10~25초 | 1~3초 |
| 콜드스타트, 5개 법조문 | 15~50초 | 2~5초 |
| 판례 질문 | ∞ (미구현) | 2~5초 |

---

## 2. 개선 전략

### 2.1 병렬 조회 (P0 — 가장 큰 효과)

현재: `for ref in relevant_laws[:5]` → 순차 fetch
개선: `concurrent.futures.ThreadPoolExecutor` 또는 `asyncio.gather` 병렬화

```
[AS-IS]  A(5s) → B(5s) → C(5s)               = 15s
[TO-BE]  A(5s) ─┐
         B(5s) ─┤→ max(5s) = 5s
         C(5s) ─┘
```

**선택**: `concurrent.futures.ThreadPoolExecutor`
- pipeline.py가 동기 코드 → async 전환 불필요
- `requests` 라이브러리 호환
- 최대 5 스레드 (API 건수 제한과 동일)

### 2.2 MST 사전 매핑 테이블 (P0)

현재: MST를 매번 API 검색으로 동적 조회
개선: 주요 노동법 10개 MST를 하드코딩 → 검색 API 호출 제거

```python
# 법령 MST 사전 매핑 (변경 빈도: 법 전부개정 시에만)
_PRELOADED_MST: dict[str, int] = {
    "근로기준법": 270551,
    "최저임금법": 270545,
    "고용보험법": 270463,
    "산업재해보상보험법": 270346,
    "근로자퇴직급여 보장법": 270488,
    # ... 10개 법률
}
```

효과: 법령 검색 API 호출 제거 → MST 조회 0ms

### 2.3 영속 캐시 계층 (P1)

| 계층 | 저장소 | TTL | 용도 |
|------|--------|-----|------|
| L1 | Python dict (인메모리) | 프로세스 수명 | 동일 요청 내 중복 방지 |
| L2 | Supabase `law_article_cache` 테이블 | 7일 | 콜드스타트 이후 재조회 방지 |
| L3 | law.go.kr API | 실시간 | L2 미스 시 원본 조회 |

Supabase 이미 optional 연동 → `law_article_cache` 테이블 추가만으로 구현 가능

### 2.4 연결 풀링 (P1)

```python
# requests.Session 사용 → Keep-Alive + 연결 재사용
_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/xml"})
```

효과: TCP handshake 반복 제거 → 건당 ~100ms 절감

### 2.5 판례 API 연동 (P2 — Phase 2 구현)

현재 `parse_law_reference()` 에서 `"대법원 2023다302838"` → `None` 반환

추가 구현:
- 판례 검색: `lawSearch.do?target=prec&query=통상임금`
- 판례 본문: `lawService.do?target=prec&ID=판례일련번호`
- 동일 캐시 계층 적용

### 2.6 응답 타임아웃 세분화 (P2)

| 타입 | connect_timeout | read_timeout | 이유 |
|------|----------------|-------------|------|
| MST 검색 | 2초 | 3초 | 응답 작음 (<10KB) |
| 조문 조회 | 2초 | 5초 | 응답 큼 (전체 법령 XML) |
| 판례 검색 | 2초 | 5초 | 결과 수 가변 |

---

## 3. 기능 범위

### 3.1 포함 (In Scope)

| # | 기능 | 우선순위 | 예상 효과 |
|---|------|---------|----------|
| 1 | 병렬 조회 (`ThreadPoolExecutor`) | P0 | 5배 속도 향상 |
| 2 | MST 사전 매핑 하드코딩 | P0 | 법령 검색 API 제거 |
| 3 | `requests.Session` 연결 풀링 | P1 | 건당 100ms 절감 |
| 4 | Supabase 영속 캐시 계층 | P1 | 콜드스타트 지연 제거 |
| 5 | 판례 검색/본문 API 구현 | P2 | Phase 2 완성 |
| 6 | 법령해석례(행정해석) API | P2 | "질의회시" 질문 대응 |
| 7 | 타임아웃 세분화 | P2 | 불필요 대기 감소 |

### 3.2 제외 (Out of Scope)

| 항목 | 이유 |
|------|------|
| Redis 캐시 | Vercel Serverless에서 Redis 운영 복잡. Supabase로 충분 |
| 법령 전문 Pinecone 업로드 | 별도 배치 프로젝트로 분리 |
| API 키 자동 갱신 | 법제처 키는 영구 유효 |
| 법령 비교(신구대비표) | 별도 기능 |
| MCP Server 방식 | 별도 서버 운영 불필요 |

---

## 4. 변경 대상 파일

| # | 파일 | 변경 유형 | 설명 |
|---|------|----------|------|
| 1 | `app/core/legal_api.py` | **대폭 수정** | 병렬 조회, 연결 풀, MST 사전매핑, 판례 API, 캐시 계층 |
| 2 | `app/core/pipeline.py` | 수정 | 병렬 조회 호출 방식 변경 (동기→스레드풀) |
| 3 | `app/config.py` | 수정 | Supabase 캐시 테이블 설정 추가 |
| 4 | `.env.example` | 수정 | 캐시 관련 환경변수 추가 |

### 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `wage_calculator/` 전체 | 계산기와 법령 API는 독립 시스템 |
| `chatbot.py` | CLI 전용, 파이프라인만 수정 |
| 크롤러 (`crawl_*.py`) | RAG 데이터와 법령 API는 별도 |
| Pinecone 업로드 | 기존 RAG 흐름 유지 |

---

## 5. 기술 전략

### 5.1 개선 후 호출 시퀀스

```
사용자 질문 → analyze → relevant_laws: ["근기법 제56조", "근기법 제60조", "최임법 제6조"]
                                                        ↓
                                        fetch_relevant_articles()
                                                        ↓
  [Step 1] MST 조회 — 사전 매핑 테이블 → 즉시 반환 (0ms)
  [Step 2] Supabase L2 캐시 확인 → 히트 시 즉시 반환
  [Step 3] L2 미스 건만 ThreadPoolExecutor 병렬 API 호출
           ┌─ fetch(근로기준법, 56) ─┐
           ├─ fetch(근로기준법, 60) ─┤→ max(latency) ≈ 2~5초
           └─ fetch(최저임금법, 6)  ─┘
  [Step 4] 결과를 L1 + L2 캐시에 저장
                                                        ↓
                                총 지연: 0ms (전부 캐시) ~ 5초 (전부 미스, 병렬)
```

### 5.2 Supabase 캐시 테이블 스키마

```sql
CREATE TABLE IF NOT EXISTS law_article_cache (
    cache_key   TEXT PRIMARY KEY,     -- "근로기준법_56" 또는 "prec_2023다302838"
    law_name    TEXT NOT NULL,
    article_no  INTEGER,
    content     TEXT NOT NULL,
    fetched_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);

CREATE INDEX idx_cache_expires ON law_article_cache(expires_at);
```

### 5.3 판례 API 클라이언트 설계

```python
def search_precedent(query: str, api_key: str, max_results: int = 3) -> list[dict]:
    """판례 검색 → [{판례일련번호, 사건명, 선고일자, 요지}]"""
    # lawSearch.do?target=prec&query={query}&display={max_results}

def fetch_precedent(prec_id: int, api_key: str) -> str | None:
    """판례 전문 조회 → 판시사항 + 판결요지 텍스트"""
    # lawService.do?target=prec&ID={prec_id}
```

### 5.4 에러 처리 전략

| 상황 | 현재 | 개선 |
|------|------|------|
| 단일 조문 API 실패 | 전체 결과 None 가능 | 실패 건만 스킵, 성공 건은 반환 |
| Supabase 연결 실패 | (미적용) | L1 캐시로 폴백, API 직접 호출 |
| 모든 API 실패 | None → RAG만 사용 | 동일 (graceful degradation 유지) |
| 병렬 스레드 예외 | (미적용) | 개별 스레드 except → None, 다른 스레드 영향 없음 |

---

## 6. 검증 시나리오

| # | 시나리오 | 기대 결과 | 측정 지표 |
|---|---------|----------|----------|
| 1 | 콜드스타트 + 3개 법조문 (캐시 없음) | 병렬 조회, 5초 이내 | 응답 시간 <5s |
| 2 | 동일 질문 2회째 (L1 캐시 히트) | 즉시 반환 | 응답 시간 ~0ms |
| 3 | 콜드스타트 + L2 캐시 히트 | Supabase에서 즉시 조회 | 응답 시간 <500ms |
| 4 | "대법원 2023다302838 판결" 질문 | 판례 검색 + 판결요지 반환 | 판례 텍스트 포함 |
| 5 | API 1건 실패 + 2건 성공 | 성공 2건만 포함하여 답변 | 부분 실패 허용 |
| 6 | Supabase 미설정 상태 | L1 캐시 + API 직접 호출로 동작 | 기능 정상 |
| 7 | API 키 미설정 | 법령/판례 조회 비활성화 | 기존 RAG만 동작 |
| 8 | 5개 법조문 병렬 조회 | 순차 대비 4~5배 빠름 | 5s vs 25s |

---

## 7. 구현 순서

```
Phase A (P0 — 병렬화 + MST 사전매핑):
  Step 1: legal_api.py — MST 사전 매핑 테이블 추가, _lookup_mst() 수정
  Step 2: legal_api.py — requests.Session 연결 풀링 도입
  Step 3: legal_api.py — fetch_relevant_articles() 병렬화 (ThreadPoolExecutor)
  Step 4: 성능 테스트 (병렬 vs 순차 비교)

Phase B (P1 — 영속 캐시):
  Step 5: Supabase 캐시 테이블 생성 (SQL 마이그레이션)
  Step 6: legal_api.py — L2 캐시 계층 추가 (_supabase_cache_get/set)
  Step 7: app/config.py — 캐시 설정 환경변수 추가
  Step 8: 콜드스타트 시나리오 테스트

Phase C (P2 — 판례·해석례):
  Step 9: legal_api.py — search_precedent(), fetch_precedent() 구현
  Step 10: legal_api.py — parse_law_reference() 판례 패턴 지원 추가
  Step 11: pipeline.py — 판례 결과 컨텍스트 주입
  Step 12: 통합 테스트 (법조문 + 판례 혼합 질문)
```

---

## 8. 리스크 및 완화 방안

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| law.go.kr API 응답 지연 증가 | 중 | 중 | 타임아웃 세분화 + 캐시 강화 |
| Supabase 무료 티어 한도 | 낮 | 낮 | 캐시 행 수 제한 (1,000행), 만료 자동 삭제 |
| 병렬 호출 시 rate limit | 중 | 중 | 동시 5건으로 제한 (이미 API 최대치) |
| MST 번호 변경 (법 전부개정) | 낮 | 중 | 사전매핑 미스 → 동적 조회 폴백 유지 |

---

## 9. 참고 자료

- 기존 법령 API 통합 Plan: `docs/01-plan/features/legal-api-integration.plan.md`
- 현재 구현: `app/core/legal_api.py` (274줄)
- 법제처 API 가이드: `https://open.law.go.kr/LSO/openApi/guideList.do`
- 판례 API: `lawSearch.do?target=prec` / `lawService.do?target=prec`
- 해석례 API: `lawSearch.do?target=expc`
