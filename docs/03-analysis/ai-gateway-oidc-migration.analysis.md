# ai-gateway-oidc-migration — Gap Analysis (Check)

> 2026-10-28 · gap-detector 대조(143항목) + 분석자 재검증(Medium 3건·❌ 4건 코드 확인, main 오프라인 테스트 재실행)
> 대상: Design v0.2 §0~§14 ↔ main `74aa04d`(PR #145 머지, 기준 `9529cf1`, 커밋 3개·파일 16개 +1,560/−35)
> **Act(2026-10-28)**: §1.1 — Medium 3·Low 8을 코드·설계서 v0.3·CLAUDE.md로 조치했다(worktree `laborconsult-gw2`, 브랜치 `fix/ai-gateway-check-gaps`, 미커밋). 재집계 **99.7%**(분석자 직접, gap-detector 재실행 없음)

## 1. 요약

| 항목 | 결과 |
|---|---|
| **Match Rate(Check)** | **93.0%** = (✅127 + ⚠️12×0.5) / 143 — gap-detector 값, 분석자 재집계 동일 |
| **Match Rate(Act 후)** | **99.7%** = (✅142 + ⚠️1×0.5) / 143 — §1.1 조치 뒤 분석자 재집계. 남은 ⚠️ 1건은 O8(V-9 토큰 만료 실측 미완) |
| 대조 항목 | 143개(분모). A 결정·경계 6 · B 모드 5 · C 클라이언트 9 · D 바인딩 6 · E 프록시 11 · F 슬러그 9 · G 카탈로그 7 · H Cohere 7 · I 인증 19 · J 경로 16 · K AppConfig 5 · L 환경·문서 6 · M 테스트 15 · N 배포·롤백 5 · O 검증기록 9 · P 범위·제약 8 |
| 일치 / 부분 / 미구현(Check → Act) | 127 / 12 / 4 → **142 / 1 / 0** |
| 분모 제외 | ➕ 설계에 없는 구현 14(§4) · N/A 8(Gemini 옵트인 미착수, §5) |
| 설계 사각(Match Rate 밖) | **Medium 3**(G-M1 자가치유 비용·G-M2 평가 스크립트 토큰 오송신·G-M3 관리자 목록 정렬) · Low 6(BS4~BS9) — §7. **Act에서 전부 조치**(§1.1) |
| 요청 경로 우회 | Gateway 모드에서 제공자 키로 조용히 가는 지점 **0건**(§7.1 전수) |
| 분석자 재실행 | main에서 `test_llm_transport.py` 20/20 · `test_llm_fallback.py` · `test_offline_units.py` 전부 통과(`.venv/bin/python`) |
| 판정 | Check 93.0% ≥ 90% → Act는 선택이었으나 Medium 3건이 프로덕션 비용·토큰 노출·관리 화면 계약에 닿아 실행. Act 후 99.7% → Report 가능 |

### 1.1 Act 조치(2026-10-28)

worktree `/Users/zealnutkim/DEV/laborconsult-gw2`, 브랜치 `fix/ai-gateway-check-gaps`(main `74aa04d` 기준, **미커밋**). 파일 11개 +307/−75. 테스트: `test_llm_transport.py` **25/25**(T13·T14·T15 + T1·T11 보강), `test_llm_fallback.py`(+`test_claude_known_no_force_models_skip_forced_attempt`), `test_model_settings.py` 26/26, `test_offline_units.py`, `test_pipeline_wiring.py` 전부 통과. 변이 검사 5/5(각 수정을 되돌리면 해당 테스트가 실패한다).

| ID | 조치 | 어디 | 판정 변화 |
|---|---|---|:-:|
| **G-M1** | 실측 모델(`claude-opus-5-5`·`claude-sonnet-5-5`·`claude-fable-5-1`)을 `_CLAUDE_TOOL_NO_FORCE_KNOWN`으로 **선등록** — 첫 호출부터 auto+지시, 콜드 인스턴스의 낭비 왕복 0. 목록 밖 모델은 종전처럼 실측으로 배운다. 모듈 docstring에 Gateway 200 경로 서술(BS9) | `llm_gateway.py`, 회귀 `test_llm_fallback.py::test_claude_known_no_force_models_skip_forced_attempt` | 사각 → 조치 |
| **G-M2** | `rerank_results(..., cohere_base_url=config.cohere_base_url)` 전달. AST 회귀 T13: `config.cohere_api_key`를 넘기는 모든 호출부(pipeline 2·eval 2)가 `cohere_base_url`을 넘긴다 | `eval_retrieval.py:134`, `eval_colloquial.py:112`, `test_llm_transport.py` T13 | 사각 → 조치 |
| **G-M3** | `catalog_models`의 `created`를 `/v1/models`의 `released`(출시일 epoch)로 채운다 — 실측: `created`는 전 모델 동일 상수(1755815280), `released`는 모델별(opus-5.5 1790035200·sonnet-5.5 1790553600·haiku-5.5 1791331200). `select_latest` 무변경으로 "최신 3개"가 성립 | `llm_transport.py`, T11 보강 | 사각 → 조치 |
| BS5 | `fetch_raw_models`가 contextvar 대신 `llm_transport.bound_token(config)`(바인딩 객체) 사용 | `model_settings.py`, `llm_transport.bound_token`, T14 | 사각 → 조치 |
| BS6 | `catalog()`가 네트워크를 **잠금 밖**에서 탄다. `/v1/models` 실패는 WARNING + 슬러그 표 유지 | `llm_transport.py`, T15 | 사각 → 조치 |
| BS7 | 미사용 `require_token()` 제거 | `gateway_auth.py` | 사각 → 조치 |
| BS8 | `check_env.py`의 `.env.vercel.local`을 저장소 루트 절대경로로 | `check_env.py` | 사각 → 조치 |
| BS4·BS9 | 문서화(설계서 §3·§4.1, docstring) | 설계 v0.3, `llm_gateway.py` | 사각 → 조치 |
| M1 | T1에 direct 클라이언트 원형(`_Bound` 아님)·SDK 기본 base_url 단언 추가 | `test_llm_transport.py` | ⚠️ → ✅ |
| A4·B3·C1·C7·E7·G6·H5 | 설계서 v0.3 서술 정정(§1 무변경 표·`transport_mode()`·`make_gateway_clients`·`_REQUIRED_KEYS` 분기·`GatewayUnsupportedError`·httpx·호출 지점 2곳) | 설계 v0.3 | ⚠️ → ✅ |
| F9·H7·I7 | 설계서에서 삭제(`from_slug`·`transport_warnings`·401 안내 — 각 사유 §8 4·5번) | 설계 v0.3 §2.5·§2.7·§3 | ❌ → ✅ |
| M15·O7 | §12에 L5(wage-01 Live 1건·P6 2건)·V-8(실배포 확인) 기록 | 설계 v0.3 §12 | ❌/⚠️ → ✅ |
| O8 | V-9 토큰 만료 실측은 **미완** — 설계 §13 ⑥ 후속으로 기록 | 설계 v0.3 | ⚠️ 유지 |
| N2·L6 | CLAUDE.md Deployment 증거에 `check_llm_fallback.py` ✅·배포 ID, Commands에 `LLM_TRANSPORT=gateway uvicorn …`, Key Conventions ⑥·⑦ 추가, 의도분석 항목에 Gateway 200 경로·선등록 | `CLAUDE.md` | ⚠️ → ✅ |
| X1~X14·N/A | 설계서 §3.2·§5에 `from_env()` 바인딩·`_unwrap`·`repr=False` 반영, Q1(b) 옵트인 항목 "미착수" 표기 | 설계 v0.3 | 분모 외 정리 |

재집계: ⚠️ 12건 중 11건이 ✅(O8 제외), ❌ 4건 전부 ✅ → ✅142 · ⚠️1 · ❌0 = **99.7%**. 변경은 전부 **설계가 정한 계약의 보강·정정**이고 전송 계층의 공개 표면(`bind`·`_Bound`·`to_slug`·`rerank_results` 시그니처)은 바뀌지 않았다. 배포 영향: G-M1 선등록은 프로덕션 콜드 첫 질문의 의도분석 왕복 1회를 없앤다(머지·배포 뒤 콜드 TTFT로 확인).

## 2. 결론

- 핵심 계약은 설계대로다: 요청별 바인딩(`bind`), SDK 경계 프록시(`_Bound`) 한 곳에서만 슬러그 변환, 정적 표 → 카탈로그 순, 미해결 모델은 `UnsupportedModelError`, 제공자 키 폴백 분기 없음, Cohere는 Gateway 호환 표면(`/v2/rerank`), Gemini 직접 호출 잔존(Q1 a). 테스트 ID T1~T12가 모두 구현돼 있다(20개 테스트).
- ❌ 4건은 전부 Low다 — `from_slug` 미구현(쓸 곳이 없어졌다), 재정렬 토큰 부재 경고·`transport_warnings` 미구현, 401 만료 안내 미구현, L5 Live 결과 미기록.
- ⚠️ 12건 대부분은 **설계서 서술이 낡은 것**이다(명칭 `make_clients`, 상수 `TRANSPORT`, 예외 클래스, 호출 지점 수, `llm_gateway.py` "무변경" 표기). 코드 수정이 필요한 것은 T1 단언 보강 1건이다.
- 설계 사각에서 Medium 3건이 나왔다. 셋 다 답변 본문의 정확성과는 무관하고, 비용·보조 경로·관리 화면 문제다(§7.2).

## 3. 항목별 대조

### A. 결정·변경 경계 (§0·§1)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| A1 | Q1(a) Gemini 직접 호출 유지 | `pipeline.py:571`, `llm_gateway.py:160`, `model_settings.py:257-264` | ✅ | |
| A2 | Q2 크레딧 확인 후 진행 | 설계 §12 머리말(잔액 기록) | ✅ | 잔액 >0이라 (a) 조건 해당 없음 |
| A3 | `_stream_*` 무변경 | `pipeline.py:461-513`(diff 없음) | ✅ | |
| A4 | `llm_gateway.py` 무변경(§1) | `llm_gateway.py:241-278`(+20행) | ⚠️ | V-1 편차 대응으로 바뀌었다. §12에는 있지만 §1 표가 낡았다 |
| A5 | case_match·citation_relevance·legal_rule_store·run_test_call 무변경 | diff 없음 | ✅ | |
| A6 | `requirements.txt` 무변경(SDK 핀) | diff 없음, `anthropic<1.0` 유지 | ✅ | |

### B. 모드·상수 (§2.1)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| B1 | `GATEWAY_URL` | `llm_transport.py:32` | ✅ | |
| B2 | `GATEWAY_OPENAI_URL` | `llm_transport.py:33` | ✅ | |
| B3 | 모듈 상수 `TRANSPORT`(기본 direct, 비정상값은 direct) | `llm_transport.py:72-74` `transport_mode()` | ⚠️ | 상수가 아니라 호출 시점 함수다(테스트 용이). §4.7의 `llm_transport.TRANSPORT` 참조도 실제로는 `config.transport` |
| B4 | `is_gateway(config)` | `llm_transport.py:77-78` | ✅ | |
| B5 | import 시 네트워크 없음 | 카탈로그 지연 로드 `:139` | ✅ | |

### C. 클라이언트 생성 (§2.2)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| C1 | `make_clients()`(두 모드) | `llm_transport.py:81-87` `make_gateway_clients()` + `config.py:161-165` | ⚠️ | gateway 전용 함수이고 direct는 `from_env` 안에 그대로다. 설계서 명칭 갱신 |
| C2 | gateway OpenAI(placeholder, `/v1`) | `llm_transport.py:85` | ✅ | |
| C3 | gateway Anthropic(placeholder, base) | `llm_transport.py:86` | ✅ | |
| C4 | direct 현행 유지 | `config.py:164-165` | ✅ | |
| C5 | placeholder 값 | `llm_transport.py:35` `_PLACEHOLDER_KEY` | ✅ | |
| C6 | gateway에서 OPENAI·ANTHROPIC 키 미참조 | `config.py:154,161-162` | ✅ | T2가 고정 |
| C7 | 키를 `_REQUIRED_KEYS`에서 제외 | `config.py:147` 유지, `:154` 지역 분기 | ⚠️ | 동작은 같다. 클래스 상수는 direct 목록으로 남아 있다 |
| C8 | COHERE_API_KEY 미참조 | `config.py:188` | ✅ | |
| C9 | `api_key` 인증(auth_token은 대안) | `llm_transport.py:246` | ✅ | V-2 |

### D. 요청별 바인딩 (§2.3)

| # | 설계 항목 | 구현 | 판정 |
|---|---|---|:-:|
| D1 | direct면 같은 객체 | `llm_transport.py:275-276` | ✅ |
| D2 | `current_token()`으로 토큰 획득 | `:277` | ✅ |
| D3 | `dataclasses.replace` + `_Bound` ×2 | `:278-281` | ✅ |
| D4 | `cohere_api_key=token`, `cohere_base_url=GATEWAY_URL` | `:282-283` | ✅ |
| D5 | 토큰 None이어도 바인딩 성공, 사용 시 `GatewayAuthError` | `:240-244` | ✅ |
| D6 | 연결 풀 공유 | 모듈 주석 `:9-10`, V-3 | ✅ |

### E. SDK 경계 프록시 (§2.4)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| E1 | `__repr__`에 토큰 없음 | `llm_transport.py:232-233` | ✅ | |
| E2 | 토큰 없으면 `GatewayAuthError` | `:240-244` | ✅ | |
| E3 | `with_options(api_key=token, **kw)` 사본 | `:245-246` | ✅ | 호출부가 넘긴 api_key는 제거(➕ X6) |
| E4 | messages(create·stream) | `:251-253` | ✅ | |
| E5 | chat.completions(create) | `:255-257` `_Chat` | ✅ | |
| E6 | embeddings(create) | `:259-261` | ✅ | |
| E7 | `models` 접근 시 `GatewayAuthError` | `:263-266` `GatewayUnsupportedError` | ⚠️ | 예외 클래스가 다르다(의미상 더 정확). 설계서 갱신 |
| E8 | `model=`만 슬러그로 변환 | `:204-207` | ✅ | T3가 나머지 kwargs 바이트 동일 확인 |
| E9 | stream 결과 그대로 반환 | `:207` | ✅ | |
| E10 | with_options 없이 접근하면 자동 1회 삽입 | `:248-249` | ✅ | |
| E11 | `_available` 참 유지 | `llm_gateway.py:84-88` | ✅ | |

### F. 슬러그 매핑 (§2.5)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| F1 | `/`가 있으면 그대로 | `llm_transport.py:96-97` | ✅ | |
| F2 | anthropic 정적 5종 | `:46-52` | ✅ | 표와 같다 |
| F3 | openai 정적 3종 | `:53-57` | ✅ | |
| F4 | cohere 정적 1종 | `:58-60` | ✅ | V-4: 카탈로그에 cohere provider가 없어 정적 표가 담당 |
| F5 | 정적 → 카탈로그 순서(v0.2) | `:98-103` | ✅ | |
| F6 | `provider==vendor ∧ providerModelId==model` | `:131-135` | ✅ | |
| F7 | `UnsupportedModelError(RuntimeError)` | `:64-65,104-105` | ✅ | |
| F8 | 하이픈→점 추측 변환 없음 | `:98-105` | ✅ | T5 |
| F9 | `from_slug(slug)` | 없음 | ❌ | 쓰는 곳이 없다 — 카탈로그가 providerModelId를 직접 주고 `metadata.llm.model`은 벤더 ID다. 설계서에서 삭제 권장 |

### G. 카탈로그 (§2.6)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| G1 | `/v1/models/catalog`, 10초 | `llm_transport.py:39,119` | ✅ | |
| G2 | Bearer 현재 토큰 | `:118` | ✅ | V-4: 인증 없이도 200 |
| G3 | 프로세스 내 1시간 캐시 | `:37,144` | ✅ | |
| G4 | 실패 시 WARNING 1줄 + 빈 목록 | `:151-153` | ✅ | 예외 타입명만 남긴다 |
| G5 | `/v1/models`의 type 병합 | `:122-124,173-177` | ✅ | |
| G6 | 기존 의존성만 사용(`requests`) | `:117` `httpx` | ⚠️ | httpx는 SDK를 통해 설치되는 간접 의존성이고 `pipeline.py`도 이미 쓴다. 설계서 갱신 |
| G7 | embedding·reranking은 텍스트 목록에서 제외 | `:176,183` | ✅ | |

### H. Cohere (§2.7)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| H1 | `rerank_client(api_key, base_url)` | `llm_transport.py:289-294` | ✅ | |
| H2 | `rerank_model(base_url, model)` | `:297-298` | ✅ | |
| H3 | `rerank_results(…, cohere_base_url=None, model=None)` | `rag.py:632-640` | ✅ | |
| H4 | 내부 `ClientV2`·모델 교체 | `rag.py:687,705` | ✅ | |
| H5 | 호출부 "3지점(정상·wider·폴백)"에 전달 | `pipeline.py:3798,3833`(2지점) | ⚠️ | 실제 호출은 2지점이고 둘 다 전달한다. 무키 폴백은 rerank를 부르지 않는다. 설계서 서술 오류 |
| H6 | 토큰 없으면 재정렬 생략 | `rag.py:683-684`, `pipeline.py:3797` | ✅ | |
| H7 | 경고 1회 + `metadata.llm.transport_warnings=rerank_no_token` | 없음 | ❌ | 저장소 전체 grep 0건 |

### I. 인증 (§3·§3.1~3.3)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| I1 | `HEADER` | `gateway_auth.py:19` | ✅ | |
| I2 | ContextVar | `:21` | ✅ | |
| I3 | `GatewayAuthError(RuntimeError)` | `:24` | ✅ | |
| I4 | capture: 헤더 없으면 None으로 set | `:28-36` | ✅ | |
| I5 | release | `:39-44` | ✅ | ValueError 보호 추가(➕) |
| I6 | 우선순위 헤더 → VERCEL_OIDC_TOKEN → AI_GATEWAY_API_KEY | `:52-57` | ✅ | |
| I7 | 만료 401 시 "vercel env pull" 안내 | 없음 | ❌ | 안내는 토큰 **부재**(`GatewayAuthError`)에만 붙는다(`llm_transport.py:243`, `gateway_auth.py:65`, `check_env.py:57`) |
| I8 | AI_GATEWAY_API_KEY는 마지막 폴백 | `:56` | ✅ | |
| I9 | `_security_headers`에서 capture + try/finally release | `api/index.py:70-74` | ✅ | |
| I10 | 새 미들웨어 추가 없음 | `api/index.py:62` | ✅ | |
| I11 | 엔드포인트·SSE에서 contextvar가 보임 | T7 | ✅ | |
| I12 | `get_config()`가 `bind(_config)` 반환 | `api/index.py:108-117` | ✅ | |
| I13 | `config_factory=get_config`로 자동 바인딩 | `api/index.py:601-604` | ✅ | |
| I14 | PineconeEvidence가 바인딩 객체를 씀 | `api/index.py:590-592` | ✅ | |
| I15 | 스레드에는 객체로 토큰 전달 | T10 | ✅ | |
| I16 | 로그·예외·repr·metadata에 토큰 없음 | `config.py:130-134`(repr=False), `llm_transport.py:153` | ✅ | T8 |
| I17 | check_env는 설정 여부만 표시 | `check_env.py:45-67` | ✅ | |
| I18 | 기존 `val[:8]` 앞부분 출력 제거 | `check_env.py:4,46-49` | ✅ | |
| I19 | `.env.vercel.local`은 gitignore 대상 | `.gitignore` 무변경(`.env*`) | ✅ | |

### J. 경로별 변경 (§4)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| J1 | Claude 호출 무변경, 프록시 경유 | `pipeline.py:461-470` | ✅ | |
| J2 | 강제 tool_choice 편차 대응(200 + 도구 미호출) | `llm_gateway.py:241-278` | ✅ | §12 V-1 기록. refusal 분기는 추가(➕ X10) |
| J3 | 모델·설정을 바꿔 맞추지 않음 | 재시도 로직만 수정 | ✅ | |
| J4 | OpenAI 무변경 | `pipeline.py:497-513` | ✅ | |
| J5 | 임베딩 5곳 프록시 경유 | `rag.py:167,248`, `case_match.py:90`, `citation_relevance.py:101`, `legal_rule_store.py:179` | ✅ | |
| J6 | `fetch_raw_models` 맨 앞 gateway 분기 | `model_settings.py:245-248` | ✅ | claude·openai 한정(Q1a와 일관) |
| J7 | 반환 형식 `{id(벤더ID), label, created:None}` | `llm_transport.py:181,185` | ✅ | |
| J8 | ID 순 정렬 + dedupe·LIST_LIMIT | `model_settings.py:228-230` | ✅ | 설계대로다. 그러나 사각 G-M3 |
| J9 | Gemini 목록은 현행 분기 | `model_settings.py:257-264` | ✅ | |
| J10 | run_test_call 무변경 | `api/model_settings.py:69` | ✅ | |
| J11 | 저장 게이트(HMAC) 무변경 | `model_settings.py:270-289` | ✅ | |
| J12 | Gemini 3함수 직접 호출 | `pipeline.py:571`, `llm_gateway.py:160` | ✅ | |
| J13 | provider_chain: Gemini는 키가 있을 때만 | `llm_gateway.py:102` | ✅ | |
| J14 | `metadata.llm.transport` | `pipeline.py:755-756,4482-4483` | ✅ | 값 출처는 `config.transport`(B3) |
| J15 | `llm_outcome … transport=` | `pipeline.py:4484-4489` | ✅ | |
| J16 | `check_llm_fallback.py` 무변경 | diff 없음 | ✅ | |

### K. AppConfig (§5)

| # | 설계 항목 | 구현 | 판정 |
|---|---|---|:-:|
| K1 | `transport` 필드, 기본 "direct" | `config.py:139` | ✅ |
| K2 | `cohere_base_url` 필드 | `config.py:140` | ✅ |
| K3 | gateway 필수 키는 PINECONE만 | `config.py:154` | ✅ |
| K4 | `gemini_api_key`는 그대로 | `config.py:182` | ✅ |
| K5 | `.env.vercel.local`을 `override=False`로 로드 | `config.py:19-20`(절대경로) | ✅ |

### L. 환경변수·문서 (§6)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| L1 | `.env.example` LLM_TRANSPORT(값 없음) | `.env.example:21-27` | ✅ | |
| L2 | VERCEL_OIDC_TOKEN | `.env.example:28-30` | ✅ | |
| L3 | AI_GATEWAY_API_KEY | `.env.example:31` | ✅ | |
| L4 | check_env 모드별 필수 키 | `check_env.py:18-19,43` | ✅ | |
| L5 | 제공자 키를 "삭제 후보"로 표시 | `check_env.py:58-63` | ✅ | |
| L6 | 로컬 실행 절차(link·pull·인라인 `LLM_TRANSPORT=gateway uvicorn`) | `CLAUDE.md:211`(link·pull만) | ⚠️ | 인라인 Gateway 실행 명령이 Commands에 없다 |

### M. 테스트 (§7)

| # | 설계 항목 | 구현 | 판정 | 비고 |
|---|---|---|:-:|---|
| M1 | T1 direct 동작 동일 + SDK 원형 + 기본 base_url | `test_llm_transport.py:98-112` | ⚠️ | bind 동일성·모드 기본값은 단언한다. 원형 클래스·기본 base_url은 단언하지 않는다 |
| M2 | T2 SENTINEL 키 미사용, Gateway base_url | `:115-143` | ✅ | |
| M3 | T3 프록시 변환·kwargs 동일·stream 그대로 | `:146-198` | ✅ | |
| M4 | T4 바인딩 성공, 호출 시 오류 | `:201-210` | ✅ | |
| M5 | T5 미해결 모델 오류, 추측 변환 없음 | `:213-230` | ✅ | |
| M6 | T6 상류는 벤더 ID, `supports_effort` 참 | `:233-247` | ✅ | |
| M7 | T7 미들웨어 헤더 유무, `/api/health` 200 | `:250-284` | ✅ | |
| M8 | T8 repr·예외·로그에 토큰 없음 | `:287-312` | ✅ | |
| M9 | T9 Cohere gateway·direct 인자 | `:315-342` | ✅ | |
| M10 | T10 스레드풀에서도 토큰 사용 | `:345-359` | ✅ | |
| M11 | T11 관리자 목록은 카탈로그, models.list 미호출 | `:362-379` | ✅ | |
| M12 | T12 Gemini 키 조건 | `:382-395` | ✅ | (a)만 해당. 옵트인은 N/A |
| M13 | CI 등록 | `.github/workflows/tests.yml:58-59` | ✅ | |
| M14 | L0 credits·catalog | 설계 §12 머리말·V-4 | ✅ | |
| M15 | L5 전 경로 1질문(`eval_consultation --live`, gateway) | 기록 없음 | ❌ | 실행했다면(Do 중 wage-01 로컬 평가 성공) §12에 적고, 프로덕션 P6로 대체했다면 그 사실을 적어야 한다 |

추가 회귀 `test_llm_fallback.py:964`(`…accepted_without_tool_use_falls_back_to_auto`)가 `main()`(`:1063`)에 등록돼 있다(✅).

### N. 배포·롤백 (§8·§9) vs CLAUDE.md Deployment

| # | 설계 항목 | CLAUDE.md | 판정 | 비고 |
|---|---|---|:-:|---|
| N1 | P5: env 변경 → 재배포 → `vercel inspect --wait` → 확인 | env → 재배포 → inspect READY → `metadata.llm.transport` | ✅ | |
| N2 | P7 증거: 대시보드·credits 차액·metadata·`check_llm_fallback.py`·배포 ID | 앞의 셋만 | ⚠️ | 폴백 감시 결과와 배포 ID가 빠졌다 |
| N3 | 롤백 A: env direct + 재배포 3~5분, 키 7일 유지 | 같음 | ✅ | |
| N4 | 롤백 B: 이전 배포 승격(즉시) | 같음 | ✅ | |
| N5 | 복귀 창 뒤 삭제는 사용자 승인, 제공자 측 키 폐기 금지 | "폐기하지 않는다" + `check_env.py:61` | ✅ | |

### O. 검증 기록 (§12)

| # | 항목 | 기록 | 판정 | 비고 |
|---|---|---|:-:|---|
| O1 | V-1 | 스트리밍·effort·thinking 통과, 강제 tool_choice 편차와 대응 | ✅ | |
| O2 | V-2 | anthropic 0.120.2 copy 인자 | ✅ | |
| O3 | V-3 | 두 SDK 연결 풀 공유 | ✅ | |
| O4 | V-4 | 카탈로그 공개 200, 필드 확정 | ✅ | |
| O5 | V-5 | Cohere 상위 5 동일, 점수 차 ≤0.0003(= L2) | ✅ | |
| O6 | V-6 | gpt-6-sol 스트리밍·함수 호출 | ✅ | |
| O7 | V-8 | T7 통과만 기록 | ⚠️ | 방법란의 "로컬 uvicorn 1회" 결과가 없다 |
| O8 | V-9 | 토큰 1개 기록, 만료 동작 "확인 예정" | ⚠️ | 미완료(12시간 경과 후 1회) |
| O9 | L1 | 코사인 0.999999 ×3, 1536차원 | ✅ | |

### P. 범위 밖·CLAUDE.md 갱신안·Plan 제약 (§13·§14)

| # | 항목 | 구현 | 판정 |
|---|---|---|:-:|
| P1 | Pinecone 삭제·재색인 없음 | diff에 해당 없음 | ✅ |
| P2 | 오프라인 경로 인증 불변 | 수집·Actions 무변경 | ✅ |
| P3 | Env 항목 LLM_TRANSPORT | `CLAUDE.md:210` | ✅ |
| P4 | Env 항목 VERCEL_OIDC_TOKEN | `CLAUDE.md:211` | ✅ |
| P5 | Env 항목 AI_GATEWAY_API_KEY | `CLAUDE.md:212` | ✅ |
| P6 | "gateway 필수 키는 PINECONE만" 문구 | `CLAUDE.md:210` | ✅ |
| P7 | Key Conventions 항목(bind·전역 금지·경계 변환·미해결 오류·우회 없음·Cohere 표면) | `CLAUDE.md:933` | ✅ |
| P8 | 잔존 직접 호출(Gemini) 명시(Plan 제약) | `CLAUDE.md:210`, `.env.example:26`, `llm_transport.py:16-17` | ✅ |

## 4. 설계에 없는 구현 (➕ — 설계서 v0.3에 반영)

| # | 구현 | 위치 | 평가 |
|---|---|---|---|
| X1 | `from_env()`가 환경 토큰으로 `bind(config)`를 반환(CLI·평가용) | `config.py:201-204` | 필요한 추가. §3.2·§5에 없다 → 사각 G-M2의 원인 |
| X2 | AppConfig 비밀 필드 `repr=False` | `config.py:131-134` | §3.3 취지 |
| X3 | `_unwrap()`: 이중 바인딩 해제 | `llm_transport.py:269-270,280-281` | X1 때문에 필요 |
| X4 | 카탈로그 실패 캐시 60초(`CATALOG_FAIL_TTL`) | `:38,146-147` | 장애 시 매번 10초 대기 방지 |
| X5 | `GatewayUnsupportedError` | `:68-69` | E7 |
| X6 | `with_options`가 호출부 api_key를 제거 | `:245` | 우회 방지 강화 |
| X7 | `_Bound.base_url` 속성 | `:235-237` | T2 단언용 |
| X8 | 빈 모델명 → `UnsupportedModelError` | `:94-95` | |
| X9 | `request_token()`·`require_token()` | `gateway_auth.py:47-67` | `require_token`은 미사용(BS7) |
| X10 | refusal이면 NO_FORCE에 기억하지 않음 | `llm_gateway.py:269-275` | CodeRabbit #145 반영 |
| X11 | check_env가 `.env.vercel.local`을 로드 | `check_env.py:15` | 상대경로(BS8) |
| X12 | `MODES`·`VENDOR_OF_PROVIDER` | `llm_transport.py:34,42` | |
| X13 | `catalog_models`가 정적 표 모델을 보강 | `:182-185` | 카탈로그가 비어도 저장값 해석 가능 |
| X14 | 테스트 8개 추가(12 ID → 20 테스트) | `test_llm_transport.py` | 다시 바인딩, 직접 접근 자동 삽입, models 거부, 카탈로그 폴백, get_config 전역 불변 등 |

## 5. 대상 외 (N/A — 분모 제외, 설계서 정리 필요)

Q1(b) Gemini 옵트인은 "사용자가 슬러그를 정했을 때만 Do"라는 조건이 충족되지 않아 착수하지 않았다(사용자 결정 "모두 권장한 대로" = Gemini 직접 유지). 코드 grep 결과 `GATEWAY_GEMINI_MODEL`·`gateway_gemini_model` 0건. 설계서에서 "미착수(조건부)"로 표기하거나 §13 후속으로 옮긴다: §0 Q1(b) · §4.6(b) · §5 `gateway_gemini_model` · §6.1 `GATEWAY_GEMINI_MODEL` · §7.1 T12 후반 · §12 V-7 · §14 Env. §8 P2~P7 실행 결과는 설계서가 아니라 Report 대상이다.

## 6. §12·§8·§9 점검 요약

- V-1~V-6·L1은 수치와 함께 기록됐다. V-7은 사유(옵트인 미착수)로 미실시. V-8은 uvicorn 실행분 미기록, V-9는 만료 확인이 남았다.
- L5(전 경로 1질문 Live)는 §7.2에 계획만 있고 §12에 결과가 없다.
- §8·§9 절차는 CLAUDE.md Deployment 항목과 일치한다. 차이는 증거 목록에서 `check_llm_fallback.py` 결과·배포 ID가 빠진 것 하나다.

## 7. 설계 사각 점검 (변경이 닿는 경로 전수)

### 7.1 SDK 호출·제공자 키 읽기 지점 (`api/` + `app/`)

| 지점 | 형태 | Gateway 모드 경로 | 판정 |
|---|---|---|---|
| `app/config.py:164-165` | `OpenAI(...)`·`Anthropic(...)` + 제공자 키 | direct 분기에서만 | 안전 |
| `app/config.py:147,188` | `_REQUIRED_KEYS`·`COHERE_API_KEY` | gateway에서 읽지 않음 | 안전 |
| `app/config.py:182` | `GEMINI_API_KEY` | 두 모드 공통(Q1a) | 잔존 직접(의도) |
| `llm_transport.py:85-86` | placeholder 클라이언트 | 바인딩 밖으로 노출 없음 | 안전 |
| `llm_transport.py:293-294` | `cohere.ClientV2` | `base_url`이 있으면 Gateway | 안전 |
| `pipeline.py:461-463` | `with_options().messages.stream` | `_Bound` | 안전 |
| `pipeline.py:497-503` | `with_options().chat.completions.create` | `_Bound` | 안전 |
| `llm_gateway.py:144,151,250-278,295-304` | 텍스트·도구 호출 | `_Bound` | 안전 |
| `rag.py:167,248`, `case_match.py:90`, `citation_relevance.py:101` | `embeddings.create` | `_Bound` | 안전 |
| `legal_rule_store.py:179` | `self.openai.with_options().embeddings` | `api/index.py:592`에서 바인딩 객체 주입 | 안전 |
| `model_settings.py:250,255` | `models.list` | gateway 분기(`:246`)가 먼저 반환. 도달해도 `GatewayUnsupportedError`(fail-closed) | 안전 |
| `pipeline.py:571`, `llm_gateway.py:160`, `model_settings.py:261` | `genai.configure` | Gemini 직접 | 잔존 직접(의도) |
| 스레드: `self_rag.py:88`, `rag.py:259,323`, `pipeline.py:552` | 넘겨받은 config 사용 | 바인딩 객체 | 안전 |
| `get_config()` 호출 | `api/index.py` 엔드포인트 본문만 | 요청 컨텍스트 | 안전 |

결론: 요청 경로에서 Gateway를 조용히 우회해 제공자 키로 가는 지점은 **0건**이다. `_Bound` 표면 밖의 SDK 속성(`.beta` 등)·`.api_key` 직접 접근도 grep 0건.

### 7.2 사각 목록

| ID | 심각도 | 내용 | 근거 | 분석자 확인 |
|---|:-:|---|---|---|
| G-M1 | Medium | 강제 tool_choice 자가치유는 강제 호출이 **응답을 돌려줘야** 동작한다. V-1에서 by-name 강제 호출은 `max_tokens`까지 생성했다. 프로덕션 의도분석은 `INTENT_TIMEOUT=12s`, 강제 호출에는 effort가 없다. 생성이 12초를 넘으면 타임아웃 예외(400 판정 아님)로 올라가 기억되지 않고 매 질문 12초 낭비 + OpenAI 폴백이 될 수 있다. 응답이 와도 **콜드 인스턴스마다** 낭비 왕복 1회가 생긴다 | `llm_gateway.py:252-258`, `analyzer.py:285-289` | 코드 구조 확인. 프로덕션 P6 2건은 `intent_provider` None(의도분석 Claude) → 그 두 요청에서는 타임아웃 안에 자가치유됐다. 다만 콜드 TTFT 43.1초는 이 낭비 왕복을 포함한다. "모델별 첫 1회"는 실제로 "인스턴스별 첫 1회"다 |
| G-M2 | Medium | Gateway 모드로 평가 스크립트를 돌리면 `from_env()`가 환경 토큰을 `cohere_api_key`에 넣는데(X1) `rerank_results`를 `cohere_base_url` 없이 부르므로 **OIDC 토큰이 Cohere 자체 호스트로 Bearer 송신**된다(제3자 노출). 결과는 401이고 코사인 정렬로 조용히 폴백한다 | `eval_retrieval.py:134`, `eval_colloquial.py:112` | 두 호출부 확인. `eval_corpus_mix.py:129`는 `os.getenv("COHERE_API_KEY")`를 직접 써서 해당 없음. 프로덕션 경로(`pipeline.py` 2지점)는 `cohere_base_url`을 넘긴다. 발동 조건은 로컬 `LLM_TRANSPORT=gateway` + 토큰 존재(CLAUDE.md가 금지하는 구성) |
| G-M3 | Medium | Gateway 모드에서 `catalog_models`가 `created=None`을 주므로 `select_latest`가 `(0, id)` 역순, 즉 **ID 역순 상위 3개**를 고른다. Claude는 sonnet 계열만 남고 opus는 현재값일 때만 보인다. CLAUDE.md 계약 "벤더별 최신 3개"가 깨진다. 설계 §4.5가 "ID 순"으로 정한 것 자체가 사각 | `model_settings.py:228`, `llm_transport.py:181,185` | `sorted(by_id, key=(created or 0, id), reverse=True)` 확인. 답변 경로 무관, 관리 화면 목록만 |
| BS4 | Low | 토큰이 없어 Claude·OpenAI가 `GatewayAuthError`로 실패하면 체인이 Gemini 직접(제공자 키)으로 넘어간다. Q1a의 결과이고 `metadata.llm`에 폴백으로 남지만, "인증 실패 시 제공자 키 사용 금지" 제약과의 관계가 설계서에 없다 | `llm_gateway.py:102`, `pipeline.py:571` | Gemini는 Gateway 대상이 아니라 "제공자 키 몰래 사용"은 아니다. 문서화 필요 |
| BS5 | Low | `fetch_raw_models`가 바인딩 객체가 아니라 contextvar(`current_token()`)를 다시 읽는다. sync 엔드포인트의 컨텍스트 복사와 공개 카탈로그(V-4) 덕에 동작할 뿐, "바인딩 시점에 객체에 고정" 규칙과 어긋난다 | `model_settings.py:248` | |
| BS6 | Low | `catalog()`가 잠금을 쥔 채 네트워크 2회(최대 20초)를 탄다. 정적 표에 없는 모델(`OPENAI_CHAT_MODEL` env 값 등)이면 답변 경로에서도 대기한다. `/v1/models`가 실패하면 카탈로그 성공분까지 버린다 | `llm_transport.py:116-154` | |
| BS7 | Low | `require_token()` 미사용, 오류 문구가 `_Bound.with_options`와 중복 | `gateway_auth.py:60-67`, `llm_transport.py:241-244` | |
| BS8 | Low | `check_env.py`는 `.env.vercel.local`을 cwd 상대경로, `config.py`는 절대경로로 읽는다 | `check_env.py:15`, `config.py:19` | |
| BS9 | Low | `llm_gateway` 모듈 docstring은 400 경로만 설명한다(Gateway 200 경로는 인라인 주석에만) | `llm_gateway.py:22-25` | |

## 8. Gap 목록(심각도순)과 조치

| 순위 | ID | 심각도 | 내용 | 조치(코드 / 설계서) |
|:-:|---|:-:|---|---|
| 1 | G-M1 | Medium | 자가치유가 타임아웃에 기대고, 콜드 인스턴스마다 낭비 왕복 | **코드**: 강제를 거절하는 5.5 세대(opus-5-5·sonnet-5-5·fable 5.1 계열)를 `_CLAUDE_TOOL_NO_FORCE`에 정적으로 미리 넣는다(CLAUDE.md "haiku-5-5만 받는다"가 근거). 또는 강제 호출에 짧은 별도 타임아웃을 주고 타임아웃도 같은 신호로 본다. **확인**: 프로덕션 대화 `metadata.llm.intent_provider` 부재·`llm_outcome intent=` 로그. **설계서** §12 V-1 "모델별 첫 1회" → "인스턴스별 첫 1회" |
| 2 | G-M2 | Medium | 평가 스크립트의 토큰 오송신 | **코드**: 두 호출에 `cohere_base_url=config.cohere_base_url` 추가. 오프라인 테스트로 "config를 받는 `rerank_results` 호출부는 `cohere_base_url`을 넘긴다"를 AST 검사로 고정 |
| 3 | G-M3 | Medium | 관리자 목록이 최신 3개가 아니다 | **코드**: gateway 분기 전용 정렬 키(Gemini 분기처럼 버전 숫자 기준, 정식 > preview) 또는 카탈로그·`/v1/models`에 날짜가 있으면 `created` 채움. **설계서** §4.5 갱신 |
| 4 | H7 | Low | `rerank_no_token` 경고·기록 미구현 | **설계서 삭제 권장**: 토큰이 없으면 임베딩·LLM이 먼저 `GatewayAuthError`로 실패해 기록할 대화가 남지 않는다. 남긴다면 `rag.rerank_results` 진입부 WARNING 1줄 |
| 5 | I7 | Low | 401 만료 안내 미구현 | **설계서**: 로컬 전용이므로 "check_env 안내로 대체"로 갱신. 또는 **코드**로 `llm_gateway`·`_stream_answer` 예외 로그에 AuthenticationError일 때 재pull 힌트 |
| 6 | M15 | Low | L5 결과 미기록 | **설계서·Report**: Do 중 로컬 `eval_consultation --live --case wage-01` 성공 1건과 프로덕션 P6 2건을 기록 |
| 7 | O7·O8 | Low | V-8 uvicorn, V-9 만료 미확인 | **설계서**: 결과 기록. V-9는 12시간 경과 후 1회 확인 |
| 8 | M1 | Low | T1 단언 범위 부족 | **코드(테스트)**: direct `from_env()`의 클라이언트가 `_Bound`가 아니고 base_url이 SDK 기본값인지 단언 추가 |
| 9 | N2·L6 | Low | CLAUDE.md 증거 목록·로컬 실행 명령 | **CLAUDE.md**: Deployment 증거에 `check_llm_fallback.py` 결과·배포 ID, Commands에 `LLM_TRANSPORT=gateway uvicorn …` 추가 |
| 10 | BS4~BS9 | Low | §7.2 참조 | BS5·BS6·BS7·BS8은 **코드**(토큰을 바인딩 객체에서, 잠금 밖 fetch, 미사용 함수 제거, 절대경로). BS4·BS9는 **문서** |
| 11 | A4·B3·C1·C7·E7·F9·G6·H5 | Low | 설계서 서술이 낡음 | **설계서**: §1 무변경 표에서 `llm_gateway.py` 제외, `transport_mode()`·`config.transport`, `make_gateway_clients`, `_REQUIRED_KEYS` 분기, `GatewayUnsupportedError`, `from_slug` 삭제, httpx, 호출 지점 2곳 |
| 12 | X1~X14·N/A | Low | 설계에 없는 구현·옵트인 미착수 | **설계서**: §3·§5에 X1~X4·X10 반영, 옵트인 항목 "미착수(조건부)" 표기 |

## 9. 권장 조치 요약·다음 단계

**코드(우선순위순)** — 후속 PR 1건으로 묶을 수 있다
1. `app/core/llm_gateway.py`: 5.5 세대를 `_CLAUDE_TOOL_NO_FORCE`에 미리 넣거나 강제 호출 타임아웃 분리(G-M1).
2. `eval_retrieval.py:134`, `eval_colloquial.py:112`: `cohere_base_url` 전달 + 호출부 AST 회귀(G-M2).
3. `app/core/model_settings.py::select_latest`: gateway 목록 정렬 키(G-M3).
4. Low: T1 단언 보강, `fetch_raw_models` 토큰 출처, 카탈로그 잠금 범위, `require_token` 제거, check_env 경로.

**설계서(v0.3)** — §1·§2.1·§2.2·§2.4·§2.5·§2.6·§2.7·§4.5·§4.7 서술 정정, §3.2·§5에 X1과 G-M2 위험 추가, §2.7 `transport_warnings` 방침 결정, 옵트인 "미착수" 표기, §12에 V-8·V-9·L5 결과.

**CLAUDE.md** — Deployment 증거 목록 보강, Commands에 로컬 Gateway 인라인 실행 명령, (G-M1을 고치면) 의도분석 항목에 Gateway 200+미호출 편차 연결.

**다음 단계** — Match Rate 93.0% ≥ 90%이므로 `/pdca report ai-gateway-oidc-migration` 가능. CLAUDE.md Key Conventions대로 Match Rate는 "설계대로 만들었는가"만 답하고, 이미 프로덕션에 전환된 상태이므로 G-M1은 프로덕션 대화 metadata로 계속 관측(폴백 감시 `intent_fallback` 신호가 잡는다)하고 G-M2·G-M3은 후속 PR로 추적한다. Report에 넣을 것: 잔존 직접 호출(Gemini 3곳 + `fetch_raw_models` gemini 분기), 삭제 후보 키 3종(복귀 창 7일 뒤 사용자 승인), 크레딧 전후 차액, P2~P7 실행 증거, 기존 감시 사각("전 제공자 실패는 미저장")에 Gateway 장애가 들어간다는 점.

## Version History

| 버전 | 날짜 | 변경 | 작성 |
|---|---|---|---|
| 1.0 | 2026-10-28 | 최초 Gap 분석(main 74aa04d, 설계 v0.2 대비). gap-detector 143항목 + 분석자 재검증(Medium 3·❌ 4·main 테스트 재실행) | gap-detector · Claude |
| 1.1 | 2026-10-28 | Act 조치 기록(§1.1) — Medium 3·Low 8 코드/설계 v0.3/CLAUDE.md, 테스트 25/25·변이 5/5, 재집계 99.7% | Claude |
