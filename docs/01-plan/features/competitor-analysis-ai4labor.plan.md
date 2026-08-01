---
template: plan
version: 1.2
feature: competitor-analysis-ai4labor
date: 2026-08-01
author: DrunkenZealnut
project: laborconsult
---

# competitor-analysis-ai4labor Planning Document

> **Summary**: ai4labor.net의 공개 소스(Next.js 번들 40청크 1.6MB · SSR HTML · PWA 자산 · 응답 헤더)를 정적 분석한 결과, 이 서비스는 단독 사이트가 아니라 **(재)일환경건강센터가 운영하는 2사이트 제품군**(ai4labor.net 한국어 창구 + cweh-migrant.org 다국어 창구)이며, 경쟁 축이 우리와 **직교(orthogonal)**한다 — 그들은 *접근 경로의 폭*(채널·언어·도구·임베드·서류·기관연결), 우리는 *답변의 깊이*(60,174청크 RAG·28타입 계산엔진·인용검증). 본 사이클은 이 격차를 실측으로 확정하고, **우리 강점을 잠식하지 않으면서 저비용으로 회수 가능한 항목만** 선별해 로드맵화한다.
>
> **Project**: laborconsult
> **Version**: 1.0
> **Author**: DrunkenZealnut
> **Date**: 2026-08-01
> **Status**: Draft
> **분석 대상**: https://ai4labor.net (+ 자매 사이트 https://cweh-migrant.org)
> **분석 방법**: 공개 배포 자산의 **정적 분석 전용**. 서버 액션·LLM 호출 등 쓰기성 요청 미실시.

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 우리는 노동상담 AI 시장에서 **자기 위치를 실측 근거 없이** 개발해 왔다. 실제로 같은 문제를 푸는 ai4labor.net을 뜯어보니, 그들은 우리에게 **아예 없는 표면**(서류 생성 8종·위젯 임베드·PWA·위치기반 기관 지도·법령/판례/판정례/뉴스 통합검색·전문가 인계 폼)을 갖췄고, 우리는 그들에게 **아예 없는 심층**(28타입 임금계산 엔진 633 테스트케이스·60,174청크 RAG 코퍼스·인용 환각 검증·3단 LLM 폴백)을 갖췄다. 문제는 격차 자체가 아니라 **깊이의 전달 경로가 두 군데서 끊겨 있다**는 것이다 — (a) 프로덕션에 `robots.txt`·`sitemap.xml`·`manifest`가 전부 404이고 `<head>`에 meta description·og 태그가 하나도 없어 **검색으로 도달할 수 없고**, (b) 25개 "계산기" 페이지는 SVG 흐름도 열람 전용이라 **숫자를 넣어 계산해 볼 수 없다**(계산은 챗봇 대화로만 가능). 최대 강점을 만들어 놓고 아무도 만지지 못하는 상태다. |
| **Solution** | 격차를 3분류로 갈라 대응한다. ① **즉시 회수(P0)** — SEO/PWA/법적고지 기본기(sitemap·robots·meta·og·JSON-LD·manifest·파비콘·약관), 비용 거의 0, 우리 깊이를 검색에 노출. ② **선별 이식(P1)** — 계산기 직접 입력 UI(엔진 재사용), 서류 작성 도우미(진정서·구제신청서)와 기관 접수 링크, 위젯 임베드 1줄. 우리 RAG·계산 자산이 **그대로 재활용**되는 표면이라 한계비용이 낮다. ③ **의도적 비추격(Out)** — 다국어 34개 언어(정부 ai.moel.go.kr가 이미 점유), 인포그래픽 20편, 뉴스 애그리게이션, 계정 체계, 전문가 인계 네트워크. 상시 콘텐츠 운영 인력이나 오프라인 제휴가 필요한 항목은 재단형 조직의 구조적 강점이지 우리 강점이 아니다. |
| **Function/UX Effect** | 사용자는 (a) 검색·SNS 공유로 서비스에 **도달할 수 있게** 되고, (b) 챗봇을 거치지 않고도 **숫자를 넣어 바로 계산**할 수 있으며, (c) 상담 답변에서 끝나지 않고 **진정서/구제신청서 초안 → 노동포털·e-노동위 접수 경로**까지 이어지고, (d) 홈 화면 설치(PWA)로 재방문 마찰이 사라진다. 기존 챗봇·게시판·계산 엔진 동작은 변경 없음. |
| **Core Value** | **"가장 정확한 답"을 이미 만들어 놓은 자산의 도달률을 올리고, 답변을 행동(구제 절차)으로 전환**한다. 경쟁사를 모방해 얕아지는 대신, 그들이 검증해 준 **수요 있는 표면만** 골라 우리 깊이 위에 얹는다. |

---

## 1. Overview

### 1.1 Purpose

경쟁 서비스 ai4labor.net을 **추측이 아닌 공개 소스 실측**으로 해부해, laborconsult와의 기능·아키텍처·제품전략 차이를 확정한다. 결과물은 (a) 대조 매트릭스, (b) 우리의 우위/열위 판정, (c) 채택/비채택 결정과 근거다. 본 문서는 분석 리포트이자 후속 구현 사이클의 진입점이다.

### 1.2 조사 범위와 방법 (재현 가능하도록 명시)

| 항목 | 내용 |
|------|------|
| 수집 대상 | `https://ai4labor.net` 페이지 10종 SSR HTML, `/_next/static/chunks/*.js` **40개(총 1.6MB)**, `robots.txt`·`sitemap.xml`·`manifest.webmanifest`·`sw.js`·`firebase-messaging-sw.js`, 응답 헤더 |
| 추가 대상 | 홈 카드에서 외부 링크로 발견된 자매 사이트 `https://cweh-migrant.org` 페이지 9종 + 헤더 |
| 방법 | curl(브라우저 UA) GET 전용 + 로컬 정적 분석(정규식 문자열 추출, RSC flight payload 파싱, 키워드 전수 카운트) |
| **하지 않은 것** | 서버 액션 POST 호출, 챗봇 질의(LLM 비용 유발), 인증 우회, 취약점 스캔, 부하 유발 — **일절 없음** |
| 준법 메모 | 대상 `robots.txt`는 Cloudflare Managed content signals로 `search=yes, ai-train=no, use=reference` 선언 — 본 분석은 **reference 용도**이며 학습 데이터화하지 않는다. 또한 같은 파일에 **AI 크롤러 10종(`ClaudeBot`·`GPTBot`·`CCBot`·`Google-Extended` 등) `Disallow: /`** 지시가 있음을 수집 중 확인하고 **그 시점에 추가 요청을 중단**했다. 이하 내용은 중단 이전에 확보한 로컬 사본의 정적 분석 결과다. 재분석이 필요하면 이 지시를 먼저 검토할 것. |
| 한계 | 서버 코드·프롬프트 원문·LLM 모델명·Firestore 스키마는 비공개이므로 **번들에 남은 흔적으로부터의 추정**임을 각 항목에 표기 |

### 1.3 Related Documents

- 선행 사이클: `feature-roadmap-assessment.plan.md`(기능 우선순위 체계), `chatbot-security.plan.md`(공개 서비스 위협 모델 — 본 문서 §5.4의 캡차 비교 근거), `qna-board-page.plan.md`(공개 게시판)
- 운영 관례: `CLAUDE.md` — graceful degradation, `app/core/*` 커밋 필수, SSE 이벤트 규약, `_anonymize()` 적용 원칙
- 시장 자료: 고용노동부 「AI 노동법 상담」(ai.moel.go.kr, 34개 언어), 당근 AI노동상담(임금체불 진정서), labor.maum.ai

---

## 2. 실측 ① — ai4labor.net의 정체

### 2.1 단독 서비스가 아니다: 2사이트 제품군

홈의 "이주노동자상담" 카드는 내부 라우트가 아니라 **외부 링크**다.

```js
{href:"https://cweh-migrant.org", label:"이주노동자상담", external:!0, ...}   // app/page 청크
```

그리고 두 사이트의 응답 헤더가 동일하다.

| 지표 | ai4labor.net | cweh-migrant.org | 판정 |
|------|--------------|------------------|:----:|
| `x-fah-adapter` | `nextjs-14.0.21` | `nextjs-14.0.21` | 동일 |
| `server` | cloudflare | cloudflare | 동일 |
| `manifest.webmanifest` | name **"이주노동자 노동상담"** | name **"이주노동자 노동상담"** | **바이트 동일** |

ai4labor.net의 매니페스트 name이 사이트 브랜딩("AI노동상담")과 어긋나는 이유가 여기서 설명된다 — **자매 사이트 자산을 그대로 복사한 흔적**이다. 즉 ai4labor.net은 이주노동자 플랫폼에서 파생된 **한국어 일반 노동자용 창구**다.

**운영 주체 — 두 사이트의 표기가 다르다(주의)**

| | ai4labor.net | cweh-migrant.org |
|---|---|---|
| 푸터 표기 | `© Team Ai4labor` | **(재)일환경건강센터** |
| 연락처 | `Ai4labor@gmail.com`, 텔레그램 봇 `t.me/Ai4laborBot` | 043-904-7411 / 충북 청주시 흥덕구 직지대로 530 테크노S타워 동관 212호 |
| 신뢰 표식 | 팀 명의 + 이메일 | **법인명·주소·유선번호를 전 페이지 푸터에 상시 노출** |

→ 코드베이스·인프라·PWA 자산은 공유하나 **법적 주체 표기는 분리**돼 있다. 자매 사이트가 재단 명의로 신뢰를 확보하고, ai4labor.net은 팀 명의의 경량 브랜드로 운영되는 구조로 보인다(추정).

### 2.2 기술 스택 (헤더·번들 실측)

| 계층 | ai4labor.net | 근거 |
|------|--------------|------|
| 프레임워크 | **Next.js 15.5.9 App Router** | `window.next={version:"15.5.9",appDir:!0}` (헤더의 `nextjs-14.0.21`은 **어댑터 버전**이지 Next 버전이 아님) |
| React | 19.2.0-canary-0bdb9206-20250818 | 벤더 청크 버전 문자열 |
| 백엔드 호출 | **Server Actions 8종** (REST API 0건) | `createServerReference(id, …, "함수명")` — 함수명이 5번째 인자로 **평문 보존** |
| **응답 방식** | **스트리밍 없음** — 단발 `await` + 스켈레톤 | `EventSource`·`text/event-stream`·`createStreamableValue`·`useChat` **전부 0건**. `"Preparing Advice..."` 등 스켈레톤 문구 |
| 호스팅 | **Firebase App Hosting**(Google Cloud) | `x-fah-adapter`, `via: 1.1 google`, `x-cloud-trace-context` |
| CDN/보안 | **Cloudflare** 전면 | `server: cloudflare`, `cf-ray`, 기본 UA는 **403**(봇 필터) |
| 캐시 | ISR 프리렌더 | `x-nextjs-cache: HIT`, `x-nextjs-prerender: 1`, `stale-time: 300` |
| DB | **Firestore 클라이언트 직접 읽기·쓰기** | Firebase SDK **12.6.0**, `getFirestore/getAuth/getStorage` 3종만 초기화. `onSnapshot`, `setDoc`, `updateDoc` |
| 인증 | **실질 미사용** | `getAuth()` 인스턴스만 생성. `signIn*`·`onAuthStateChanged` 호출 **0건** → 공개 페이지 완전 익명 |
| UI | **shadcn/ui**(Radix + Tailwind + CVA + clsx/tailwind-merge) + lucide-react | `cn()=twMerge(clsx(…))`, `displayName="Button"/"Textarea"/"AccordionItem"` 등 원본 유지 |
| 폼 | **react-hook-form + zod**(@hookform/resolvers) | `useForm({resolver: zodResolver(schema)})` |
| 마크다운 | react-markdown(remark/rehype) | `remarkPlugins`/`rehypePlugins` |
| 상태관리 | **없음** — `useState` + sessionStorage | Redux/Zustand/Jotai/TanStack Query **0건** |
| 지도 | @react-google-maps/api | 키 클라이언트 하드코딩 + 하버사인 거리 정렬 |
| 이미지 | `next/image` **unoptimized** | `data-nimg="fill"`, `srcset` 없음 |
| PWA | **workbox precache SW 활성** | `/sw.js` 200 + `precacheAndRoute([…전 청크])` + 번들에 **workbox-window**(`navigator.serviceWorker`, `register()`) |
| 애널리틱스 | **Cloudflare Web Analytics만** | `static.cloudflareinsights.com/beacon.min.js`. GA/GTM/Clarity/픽셀 0건 |
| 폰트 | Pretendard Variable + Noto Color Emoji | jsdelivr `<link>` — **우리도 Pretendard를 동일하게 로드·적용 중**(`public/index.html:87` static 빌드 로드 → `:115` `--font-body` → `:126` `body`) |
| LLM | **클라이언트 직접 증거 0건**. 추정: Genkit + Gemini(확신도 중간~높음) | 모델명·`genkit`·`googleai` 문자열 없음. Firebase App Hosting + Firebase Studio 스캐폴드 조합의 표준 경로이고 타 벤더 흔적도 전무 |

**Firebase 프로젝트 2개**: 런타임 데이터는 `ai4labor-90463757-6c37a`(앱 코드가 `initializeApp`), `ai4labor04-16992028-e0ece`는 App Hosting 빌드가 `__FIREBASE_DEFAULTS__`로 주입한 백엔드 프로젝트다.

**출발점 추정(확신도 높음)**: Firebase Studio(구 Project IDX) 스캐폴드. 자동생성형 프로젝트 ID, 스캐폴드 고유의 `errorEmitter` + `FirebaseErrorListener`(`on("permission-error") → console.warn`), `next/image unoptimized` + shadcn 풀세트가 모두 기본값 그대로다.

### 2.3 품질 관리 상태의 단면

- `firebase-messaging-sw.js`가 서빙되지만 config가 `apiKey: "your-api-key"` **플레이스홀더 그대로** → FCM 푸시 미구성. 템플릿 파일이 정리되지 않고 배포됨.
- 매니페스트 name이 사이트 브랜딩과 불일치(§2.1).
- `/industrial-accidents`는 이미지가 **`placehold.co` 플레이스홀더 그대로**이고, 헤더·푸터 어디에도 링크되지 않은 **고아 페이지**다(sitemap에만 존재).
- `/support-organizations` 상단에 `"전국 지원 단체 데이터가 순차적으로 업데이트되고 있습니다."` 고정 공지 → 데이터 미완성.
- 내부 코드네임 `laboraid` 잔존, `/counselor`(상담사 전용 추정) 라우트가 robots.txt에 예약만 된 상태.

→ 이 진영은 **속도·표면 확장 우선, 마감 정밀도는 후순위**로 운영한다. 우리(PDCA·회귀 스위트·CodeRabbit 리뷰 루프)와 반대 성향이며, 이는 §6의 전략 판단에 직접 영향을 준다. 뒤집어 말하면 **표면을 빨리 늘리는 역량**은 우리가 배울 지점이다.

---

## 3. 실측 ② — 기능 전수 대조

### 3.1 사용자 표면(진입 경로) 대조

| # | 기능 | ai4labor.net | laborconsult | 근거 |
|:-:|------|:------------:|:------------:|------|
| 1 | 대화식 AI 상담 | ✅ `/chat` | ✅ `/` 인라인 채팅 | 양측 SSE/스트리밍 |
| 2 | **입력식(폼) 정밀 상담** | ✅ `/form-consult` — 2단계 분류 8×N + 업종 8 + 지역 17 | ❌ 없음 | 자유서술만 |
| 3 | **서류 작성 도우미** | ✅ `/petition-builder` — 3계열 **8종** + 접수 링크 | ❌ 없음 | — |
| 4 | **법령·판례·판정례·뉴스 통합검색 UI** | ✅ `/search` — 4버킷 결과 | ❌ 검색 UI 없음(챗봇 내부에서만 RAG 사용) | `d.statute/precedents/nlrcCases/news` |
| 5 | 우수 상담 사례 열람 | ✅ `/examples` (Firestore 문서) | ✅ 질문게시판(`/board`, `qa_conversations` 공개) | 양측 보유 |
| 6 | **위치기반 지원단체 지도** | ✅ `/support-organizations` (Google Maps + 현재위치) | △ 텍스트 연락처 매칭(노동위 14·고용센터 133·공단 63) → `contacts` SSE | 지도·거리순 없음 |
| 7 | **위젯 임베드(외부 사이트 배포)** | ✅ `/embed` + `/widget`, iframe 1줄 + postMessage 자동높이 | ❌ 없음 | `laboraid-resize` |
| 8 | **PWA 설치** | ✅ manifest + workbox SW + `/install` 가이드 | ❌ 없음 (manifest 404) | — |
| 9 | 산업재해 통계 리포트 | ✅ `/industrial-accidents` | ❌ 없음 | — |
| 10 | **임금 계산 엔진** | ❌ **0건** | ✅ **28 타입** / 9,512줄 | §3.3 |
| 10-b | 계산기 **입력 UI** | ❌ 없음 | △ **SVG 흐름도 열람 전용**(25페이지) — 숫자 입력→즉시 결과 위젯 **없음**, 계산은 챗봇 대화로만 | `public/calculator_flow/*.html` |
| 11 | 답변 내보내기(PDF/이메일/MD) | ❌ 0건(복사만) | ✅ 복사·PDF·마크다운·이메일(CAPTCHA 모달 + SMTP) | `public/index.html:1286-1289`, `/api/send-email` |
| 12 | 첨부파일 상담 | ✅ "증빙 서류 사진 첨부" 안내 | ✅ base64 첨부 + 파서 | 양측 보유 |
| 13 | 관리자 화면 | ✅ `/admin` + **`/counselor`(상담사 전용, 예약)** | ✅ `/admin` 통계·대화 (남용 화면은 API만) | robots.txt Disallow 목록 |
| 14 | 다국어 | ❌ **0건**(한국어 전용) | ❌ 없음 | 다국어는 자매 사이트 담당 |
| 15 | **답변 스트리밍** | ❌ 없음(단발 응답 + 스켈레톤) | ✅ SSE 10종 이벤트 실시간 | **우리 우위** |
| 16 | **답변 평가(별점)** | ✅ 1~5점, **5점 시 공개 사례로 자동 승격** | ❌ 없음 | 우리 결손 |
| 17 | 대화 맥락 유지 | △ 클라이언트 메모리만(새로고침 시 소실), 매 턴 전체 히스토리 재전송 | ✅ 서버 세션 6턴 + 요약 압축 + Supabase 스냅샷 | **우리 우위** |
| 18 | 알림 채널 | ✅ 텔레그램 봇 `t.me/Ai4laborBot` + 신규 상담 시 관리자 알림 | ❌ 없음 | 우리 결손(경량) |

### 3.2 부재 검증 — 키워드 전수 카운트

ai4labor.net 번들+HTML **1,861,349자 전수**에서:

| 키워드 | 출현 | 해석 |
|--------|:---:|------|
| 계산기 | **0** | 계산기 UI 자체가 없음 |
| 통상임금 / 평균임금 / 실업급여 / 4대보험 / 소득세 | **각 0** | 임금계산 도메인 미구현 |
| 퇴직금 5 · 주휴수당 2 · 최저임금 2 · 연차수당 1 | 소수 | 예시 질문·카테고리 라벨 수준 |
| 언어 / English / 번역 / i18n / 다국어 | **각 0** | 한국어 전용 확정 |
| PDF / 이메일 / 다운로드 / 인쇄 | **각 0** | 답변 내보내기 없음 |
| 평점 / 별점 / 피드백 | **각 0** | 명시적 평가 UI 없음(사례는 큐레이션 추정) |
| 임금체불 21 · 부당해고 28 · 산업재해 24 · 진정 27 · 구제신청 22 · 노동위원회 19 | 다수 | **분쟁·구제 절차 중심 편중** |

→ **결론**: ai4labor은 "얼마를 받아야 하는가(계산)"가 아니라 **"어디에 어떻게 신고할 것인가(절차)"**에 특화돼 있다. 우리와 정면충돌이 아니라 **상보 관계**다.

### 3.3 우리 자산 실측 (대조 기준값)

| 자산 | 수치 | 확인 방법 |
|------|:----:|-----------|
| 계산 타입 | **28종** / 패키지 9,512줄 | `registry.py:67-96` `CALC_TYPES` |
| 계산기 흐름도 | 25 페이지(계산기 24 + 의존관계 맵 1) | `ls public/calculator_flow/*.html` |
| 계산기 테스트 | CLI **116 케이스** + 배치 **500 케이스**(13유형 층화) + 골든 17 | `wage_calculator_cli.py:26`, `calculator_batch_test.py` |
| **BM25 코퍼스** | **60,174 청크** (15.7MB gz) | `data/bm25_corpus.json.gz` 개봉 집계 |
| — 구성 | Q&A 49,842 / 행정해석 6,828 / 판례 2,260 / 노무사상담 1,244 | `source_type` 집계 |
| Pinecone 네임스페이스 | 3개 (`laborlaw-v2` / `counsel` / `qa`) | `rag.py:17-19` |
| NLRC 판정사례 번들 | 360건 | `data/nlrc_cases.json` |
| 지식그래프 | 노드 72 / 엣지 78 | `data/graph_data.json` |
| 기관 연락처 | 노동위 14 / 고용센터 133 / 근로복지공단 63 = **210** | `labor_offices.py` 외 2 |
| API 엔드포인트 | 23개 | `grep -c '^@app\.' api/index.py` |
| CI 스위트 | 5종 / 총 60여 테스트(API 키 불요) | `.github/workflows/tests.yml` |
| 정적 페이지 | index 1,777줄 / board 958 / admin 465 / calculators 290 | `wc -l public/*.html` |

> **문서 갱신 필요**: `CLAUDE.md`는 계산 25종·CLI 32케이스·배치 102케이스·이메일 10건/분·SSE `text` 이벤트를 기재하나
> 실측은 각각 **28종 / 116 / 500 / 5건/분 / `text` 미존재**다. 별도 사이클에서 CLAUDE.md 정정 필요.

---

## 4. 실측 ③ — 아키텍처 대조

| 축 | ai4labor.net | laborconsult | 함의 |
|----|--------------|--------------|------|
| 런타임 | Next.js 15.5.9 SSR/ISR (Node) | FastAPI(Python) + 정적 HTML | 우리는 **계산·NLP 라이브러리 접근성**이 유리, 그들은 **렌더링·SEO**가 유리 |
| 백엔드 호출 | Server Actions 8종(RPC형) | REST + SSE 3경로 | 우리 SSE는 `session/status/meta/sources/contacts/chunk/replace/error/ping/done` **10종 이벤트** — 진행상황 투명성 우위 |
| **응답 UX** | **스트리밍 없음** — 단발 응답 + 스켈레톤 | 토큰 스트리밍 + 단계별 `status` | **우리 우위**. 장문 법률 답변에서 체감 대기시간 차이가 큼 |
| **대화 맥락** | 클라이언트 메모리만. 매 턴 전체 히스토리 재전송, 새로고침 시 소실. Firestore엔 **마지막 1쌍만** 저장 | 서버 세션 6턴 + 요약 압축(2KB) + Supabase 스냅샷 | **우리 우위**. 다만 그들 방식은 서버 상태가 없어 **서버리스에서 단순** |
| **데이터 경로** | 브라우저 → Firestore **직접 쓰기**(인증 없음, 문서에 작성자 식별자 필드 자체가 없음) | 서버 경유 + `_anonymize()` + guard 게이팅 | **우리 우위** |
| 지식 소스 | **라이브 조회형** — 법령/판례/판정례 + Google News RSS | **사전 색인형 RAG** — Pinecone Dense + BM25 하이브리드 + Cohere rerank + Self-RAG + GraphRAG | 그들은 **최신성**, 우리는 **재현성·근거 밀도** |
| 코퍼스 | 자체 코퍼스 흔적 없음(외부 API 의존 추정) | **60,174 청크** 자체 색인(Q&A 49,842·행정해석 6,828·판례 2,260·상담 1,244) | 우리 압도 |
| 계산 | 없음 → LLM 자연어 응답 의존 | 결정적 계산 엔진 **28 타입** + 633 테스트케이스(CLI 116·배치 500·골든 17) | **환각 위험 구조적 차이** |
| 인용 검증 | 흔적 없음 | `citation_validator.py` — 사건번호 환각 탐지 → `replace` 이벤트 | 우리 고유 |
| LLM | 단일 추정(Gemini 계열, 클라이언트 증거 없음) | Claude Sonnet 4.6 → OpenAI o3 → Gemini **3단 폴백** | 가용성 우위 |
| 저장 | Firestore 2컬렉션(`consultations`·`petition-drafts`) + `settings/site` CMS | Supabase(대화·세션 스냅샷·첨부·남용 이벤트·법령 캐시) | 우리가 더 조직화 |
| 콘텐츠 운영 | 홈 히어로 문구를 **Firestore 실시간 구독으로 CMS화** | 하드코딩 | 그들 우위(경량 CMS 발상) |
| 남용 방어 | **전부 클라이언트**(쿨다운·오프토픽 카운터·체크박스·허니팟) | **2단 서버 가드** — 입력검증·IP rate limit·일일 쿼터 RPC / 인젝션 정규식·스코프 게이트·유출 감지·저장 게이팅 | **우리 압도** (§5.6) |
| 배포 | Firebase App Hosting + **Cloudflare 앞단** | Vercel 서버리스 (CDN 방어 계층 없음) | **그들 우위** — 유일하게 명확히 뒤지는 인프라 축 |

**핵심 대비**: 그들의 지식은 **얇고 넓고 최신**, 우리 지식은 **두껍고 좁고 검증됨**. 뉴스 애그리게이션은 우리에게 없지만, 판례·행정해석 6만 문서 색인은 그들에게 없다.

---

## 5. 실측 ④ — 그들이 잘한 것 (구체 규격)

### 5.1 서류 작성 도우미 — "생성"이 아니라 "접수까지"

3계열 8종. 각 항목에 **입력 힌트**가 붙어 사용자가 무엇을 써야 할지 알려준다.

| 계열 | 서류 | 입력 힌트 |
|------|------|-----------|
| 고용노동부 진정 | 임금 및 퇴직금 체불 | 입사/퇴사일, 체불 금액 |
| | 근로조건 위반 | 계약과 다른 근무 내용 |
| | 직장 내 괴롭힘/성희롱 | 피해 상황·일시·행위자 |
| 노동위원회 구제신청 | 부당해고 구제신청 | 해고 통보 일시·방식 |
| | 부당노동행위 구제신청 | 노조 활동 탄압 상황 |
| | 차별 시정 신청 | 불합리한 차별 내용 |
| 근로감독 청원/익명제보 | 근로감독 청원서 | 법 위반 감독 요청 |
| | 법 위반 익명 제보 | 보편적 법 위반 제보 |

결정적인 부분은 마지막이다 — 서류 종류에 따라 접수처 딥링크가 분기한다.

```js
["PETITION_WAGE","PETITION_CONDITION","PETITION_HARASSMENT","PETITION_INSPECTION","REPORT_PUBLIC"].includes(selected)
  ? "https://labor.moel.go.kr"   // 고용노동부 노동포털 접수 바로가기
  : "https://www.nlrc.go.kr"     // e-노동위원회 구제신청 바로가기
```

문서를 만들어 주고 끝내지 않고 **실제 제출 창구로 넘긴다**. 상담→행동 전환의 마지막 1cm를 설계했다.

구현 상세(우리가 이식할 때 참고): 서버 액션 `runPetitionDraft({type, details})` → `{draft, tips[]}` 반환. 화면은 **"AI 생성 사건 경위서 초안"**으로 `draft`를 `whitespace-pre-wrap` 표시하고 `tips[]`를 "작성 및 제출 가이드" 불릿으로 붙인다. **내보내기는 클립보드 복사뿐 — PDF·DOCX 생성이 없다.** 우리는 이미 PDF·마크다운·이메일 경로를 갖고 있으므로 **이식하는 즉시 그들보다 나은 결과물**이 된다. 쿨다운은 15초(다른 페이지 5초)로, 가장 비싼 생성 작업임을 그들도 인지하고 있다.

### 5.2 입력식 상담 — 자유서술의 정보 결손을 폼으로 해결

2단계 분류(**대분류 8 → 소분류 32**, 아코디언 다이얼로그) + 업종 8 + 지역 17 + 최소 10자 + "육하원칙에 따라 자세히" 가이드.

- 대분류: 임금 및 퇴직금 / 근무시간 및 휴가 / 해고 및 인사조치 / 직장 내 괴롭힘 및 성희롱 / 산업재해(노동안전) / 근로계약 및 규칙 / 노조 및 권리구제 / 기타
- 소분류에 **"노란봉투법"**까지 포함 — 최신 이슈 반영 속도가 빠르다.
- zod 스키마에 **허니팟**(`honeypot: z.string().max(0).optional()`, hidden + `tabIndex:-1`)이 있어 자동 제출을 거른다. 이 페이지에만 존재.

우리의 `analyze_intent`는 같은 정보를 **LLM으로 추출**한다(Sonnet 1회 비용 + 누락 시 재질문). 그들은 **폼으로 강제 수집**해 LLM 호출 없이 확보하고, 클라이언트에서 프롬프트를 조립해 넘긴다.

```text
상담 분야: {대분류} ({소분류})
업종: {업종}
지역: {지역}

내용:
{본문}
```

정확도·비용 양면에서 배울 점이 있다. 다만 우리 강점(대화형·계산 연동)과 상충할 수 있어 §6.2에서 P2 보류로 둔다.

### 5.3 위젯 임베드 — 배포 채널을 남에게 맡기는 전략

```html
<iframe id="laboraid-iframe" src="https://ai4labor.net/widget" width="100%" height="160px"></iframe>
<script>window.addEventListener('message', e => {
  if (e.data?.type === 'laboraid-resize') iframe.style.height = e.data.height + 'px';
});</script>
```

노무법인·노조·시민단체 사이트가 이 한 줄을 붙이면 그들의 트래픽이 된다. 내부 코드네임 `laboraid`가 여기서 노출된다.

**중요 — 위젯은 AI를 호출하지 않는다.** 위젯 내부 코드는 제출 시 `window.open("/chat?q=" + encodeURIComponent(text), "_blank")`로 **본 사이트를 새 탭에 열 뿐**이다. 즉 이것은 임베드형 챗봇이 아니라 **유입 깔때기(lead-gen)**다. 위젯 쪽은 `ResizeObserver`로 높이만 부모에 통지한다.

```js
new ResizeObserver(es => { for (const t of es)
  window.parent.postMessage({type:"laboraid-resize", height: Math.ceil(t.target.getBoundingClientRect().height)}, "*"); });
```

우리에게 유리한 사실이다 — **LLM 비용이 전혀 늘지 않는 채널 확장**이며, 구현이 정적 페이지 1장 수준으로 끝난다. 다만 `postMessage`의 targetOrigin이 `"*"`이고 수신 측 origin 검증도 없어, 우리가 이식할 때는 **명시적 origin 지정과 검증을 넣어야 한다**.

### 5.4 답변 포맷 규약 — 렌더러에서 역산한 3단 스키마

클라이언트 파서 두 개가 서버 답변의 마크다운 구조를 그대로 드러낸다.

```js
// 요약 추출기
e.match(/### 📋\s*\*\*?귀하의 상황 요약\*\*?\n?([\s\S]*?)(?=### 💡|$)/i)
// Q&A 분리기
e.split(/### ❓\s*(?:\*\*)?같이 보면 좋은 정보(?:\*\*)?/i)
```

→ 재구성한 답변 스키마:

```markdown
### 📋 **귀하의 상황 요약**   ← /examples 목록 미리보기로 재사용(3줄 클램프)
### 💡 **답변**
### ❓ **같이 보면 좋은 정보**
**Q** … **A** …   ← 최대 3쌍만 아코디언 표시, 초과분 버림
```

정규식이 `**` 유무와 `Q:`/`**Q**`를 모두 허용하는 것으로 보아 **모델 출력이 결정적이지 않아 방어적으로 파싱**하고 있다. 우리도 답변 렌더러 회귀 테스트(`test_answer_renderer.js`)를 갖고 있으므로 동일한 문제를 인지하고 있으나, **"상황 요약" 섹션을 목록 미리보기로 재사용하는 설계**는 참고할 만하다.

### 5.5 스코프 게이트 — 우리와 같은 결론에 독립적으로 도달했다

서버 액션 반환값에 `laborRelatedStatus`가 실려 오고, 클라이언트가 4값으로 분기한다.

| 값 | 동작 |
|----|------|
| `"true"` | 정상 상담 → Firestore 저장 + 평점 UI |
| `"simple"` | 단순 질의 → `consultationField:"단순 질의"`로 태깅 후 저장 |
| `"false"` | **노동법 무관 → 저장하지 않음** + 오프토픽 카운터 +1 |
| `"search"` | 검색 의도 → `/search?q=…`로 자동 리다이렉트 |

우리 `chatbot-security` 사이클의 **스코프 게이트(analyzer 편승) + 저장 게이팅**과 사실상 동일한 설계다. 서로 다른 팀이 같은 결론에 도달했다는 것은 이 설계가 **공개 무료 LLM 서비스의 사실상 표준**임을 방증한다. 다만 그들의 `"search"` 분기 — **검색 의도를 감지해 검색 페이지로 넘기는 라우팅**은 우리에게 없는 발상이며, 우리 6만 청크 코퍼스에 검색 UI를 얹을 경우(§6.2 P2) 함께 검토할 가치가 있다.

### 5.6 남용 방어 — 우리 서버측 설계가 옳았음을 확인시켜 준다

| 계층 | ai4labor.net | laborconsult |
|------|--------------|--------------|
| 쿨다운 | 클라이언트 `useState` — `/chat`·`/form-consult`·`/search` 5초, `/petition-builder` **15초**, `/widget` 10초 | 서버 IP rate limit 5회/60초 |
| 오프토픽 대응 | 누적 3회 시 `"저는 로봇이 아닙니다"` **체크박스(순수 클라이언트 상태)** | 서버 스코프 게이트 + 저장 차단 |
| 봇 트랩 | `/form-consult`에만 zod 허니팟(`honeypot: z.string().max(0)`) | CAPTCHA(HMAC 서명, 게시판·이메일) |
| 일일 쿼터 | 없음 | Supabase RPC 원자 증가(기본 50/일) |
| 인젝션 방어 | 흔적 없음 | 정규식+가중치, 의도분석 이전 차단 |
| 앱 무결성 | **App Check 미적용**(`initializeAppCheck` 0건) | 해당 없음(서버 경유 구조) |
| 입력 길이 상한 | **없음**(`maxLength` 0건, zod `.max()` 없음) | 2,000자 제한 |
| 데이터 경로 | **브라우저가 Firestore에 직접 쓰기** — 방어선은 보안 규칙 단독 | 서버 경유 + `_anonymize()` |

**판정**: 그들의 방어는 전부 클라이언트 측이라 새로고침 한 번으로 초기화된다. 우리 2단 서버 가드(`chatbot-security`)는 이 대조로 **정당성이 확인**된다. 우리가 오히려 부족한 것은 **앞단 계층** 하나다 — 그들은 Cloudflare가 애플리케이션 이전에 봇을 거른다(우리 기본 UA 접근이 403된 것이 증거). Vercel 배포에는 이 계층이 없으므로 §12.2에서 재평가 대상으로 남긴다.

> 참고: 위 항목은 **우리 설계 검증 목적의 아키텍처 관찰**이다. 대상 서비스에 대한 어떤 형태의 시험·악용도 수행하지 않았고 계획하지도 않는다.

### 5.7 자매 플랫폼이 보여주는 "가능 범위"

cweh-migrant.org는 같은 코드베이스로 훨씬 넓은 표면에 도달했다 — 참고선으로 기록한다.

- **다국어 AI 상담**: 자동 언어감지 → 모국어 답변(베트남·캄보디아·태국·몽골·인도네시아·벵골어). 실제 벵골어·베트남어 상담 사례가 홈에 렌더링됨
- **스마트 체크리스트 18종**: 퇴직금 계산기, **E-7-4 비자 점수 자가진단**, 업종별 안전보건 가이드, 근골격계 예방, 성희롱 감수성 점검, 직장 내 괴롭힘 익명 진단, **표준근로계약서 작성 2종**, 사업주용 노무관리
- **인포그래픽 20+편**: 국가인권위 2024 실태조사, 산재 유족급여 사각지대, 외국인 취업자 100만 시대 고용동향, 전국 CSO 155곳 분포
- **재해조사 아카이브**: 산업안전보건공단 중대재해 원문 보고서 열람·지도 분포·다운로드
- **`/helpme`**: 검증된 노무사·변호사·의사가 직접 연락하는 제보 폼(가명 허용, 제3자 제보 허용, 사망사건 최우선) → **AI에서 사람으로의 에스컬레이션 경로**
- **`/news`**: 뉴스 애그리게이션(HTML 1.09MB), Google News RSS 기반
- **플로팅 퀵메뉴**: 구글 자동번역 · PWA 설치 · 글로벌 채팅 · **텔레그램 AI 상담 챗봇**
- `/login` `/register` 계정 체계

→ 이 진영의 전략은 "상담 1건"이 아니라 **권리 인식 → 자가진단 → 서류 → 기관 연결 → 전문가 인계**의 퍼널 전체를 도구·콘텐츠로 덮는 것이다. 경쟁 축이 **정확도가 아니라 접근 경로의 수**다.

---

## 6. 격차 판정 — 무엇을 하고 무엇을 하지 않을 것인가

### 6.1 우리가 명백히 앞선 것 (방어·강화 대상)

| 항목 | 격차 | 조치 |
|------|------|------|
| 임금 계산 정확도 | **28 타입 결정적 엔진 + 633 테스트케이스** vs **0** | 유지. 단 §6.2의 "입력 UI 부재"로 **가치 전달이 막혀 있음** |
| 지식 코퍼스 | 60,174 청크 하이브리드 RAG vs 라이브 API | 유지 |
| 인용 환각 검증 | `citation_validator` vs 흔적 없음 | 유지·마케팅 문구화 |
| LLM 가용성 | 3단 폴백 vs 단일 | 유지 |
| **답변 스트리밍** | SSE 토큰 스트리밍 + 단계별 status vs **스트리밍 전무**(스켈레톤) | 유지 — 장문 법률 답변에서 체감 차이가 가장 큰 축 |
| **대화 맥락** | 서버 세션 6턴+요약 vs 클라이언트 메모리(새로고침 소실) | 유지 |
| **데이터 경로** | 서버 경유 + 익명화 + 저장 게이팅 vs 브라우저→Firestore 직접 쓰기 | 유지 |
| 남용 방어 | **2단 서버 가드** vs 전부 클라이언트(새로고침 시 초기화) | 유지 + **CDN 앞단 계층만 보강 검토** |
| 답변 내보내기 | PDF·MD·이메일 vs 복사만 | 유지 — 서류 생성 이식 시 즉시 우위로 전환 |
| 개발 규율 | PDCA·회귀 스위트·CI vs 플레이스홀더·고아 페이지 배포 잔존 | 유지 |

### 6.2 우리가 뒤진 것 — 회수 우선순위

| 우선 | 격차 | 우리 상태(근거) | 회수 난도 | 판단 |
|:----:|------|-----------------|:---------:|------|
| **P0** | **검색 유입 0점** | `/robots.txt` **404**, `/sitemap.xml` **404**, `<head>`에 meta description·og·JSON-LD·canonical **전무**, `<title>`은 "기초 노동상담" 단독 | 낮음(정적 파일 + head 태그) | **즉시 채택** — 깊이를 만들어 놓고 도달 경로가 없는 상태 |
| **P0** | PWA·파비콘 부재 | `manifest` 404, SW 없음, **파비콘 파일조차 없음**(브라우저 탭 아이콘 미표시) | 낮음 | **채택** |
| **P0** | 약관·개인정보처리방침 미작성 | 푸터 링크가 `href="#"` 플레이스홀더(`index.html:574`). 운영주체 "청년노동자인권센터" 표기는 있으나 법적 고지 부재 | 낮음 | **채택** — 경쟁사는 전 페이지 푸터에 법인·주소·연락처 상시 노출(§2.1). 신뢰·준법 양면 |
| **P1** | **계산기 직접 입력 UI 부재** | 28 타입 엔진이 있으나 `public/calculator_flow/*`는 **SVG 흐름도 열람 전용**. 숫자 입력→즉시 결과 위젯이 없어 계산은 챗봇 대화로만 도달 | 중간(엔진 재사용, 폼만 신설) | **채택** — 우리 최대 강점의 전달 경로가 막힌 상태. 자매 사이트는 퇴직금·E-7-4 계산기를 **독립 도구**로 제공(§5.5) |
| **P1** | 서류 작성 도우미 | 없음 | 중간(프롬프트+템플릿, RAG 재활용) | **채택** — 상담→행동 전환의 마지막 구간 |
| **P1** | 위젯 임베드 | 없음 | 중간(경량 페이지 + postMessage + CORS/CSP) | **채택** — 배포 채널 확장 |
| **P2** | 입력식 폼 상담 | 자유서술만 | 중간 | **보류** — 우리 `analyze_intent`+재질문으로 부분 대체 중. 폼 강제수집의 비용 절감 효과를 별도 측정 후 결정 |
| **P2** | 통합검색 UI | 챗봇 내부에서만 RAG 사용 | 중간 | **보류** — 6만 문서 색인이 이미 있어 UI만 얹으면 되지만, 챗봇과 카니발라이제이션 우려 |
| **P2** | 위치기반 지도 | 텍스트 연락처(210개 기관) | 중간 | **보류** — 데이터는 이미 있음. 지도 API 비용·좌표 확보가 관건 |
| **P2** | **답변 평가(별점)** | 없음 — 답변 품질 피드백 루프 부재 | 낮음 | **보류→조기 검토 권장** — 그들은 5점 시 공개 사례 자동 승격. 우리는 이미 공개 게시판이 있으므로 **평점만 붙이면 큐레이션 자동화**. 단 자가부여 방지 서버 검증 필요 |
| **P2** | 관리자 알림 채널 | 없음 | 낮음 | **보류** — 그들은 신규 상담마다 텔레그램 fire-and-forget 알림. 운영 관측성 개선 |
| **P2** | 히어로 문구 CMS | 하드코딩 | 낮음 | **보류** — 그들은 Firestore `settings/site` 실시간 구독. 우리는 Supabase로 동일 구현 가능 |
| **P2** | CDN 앞단 봇 차단 | Vercel 단독 | 중간(비용) | **보류** — 유일하게 명확히 뒤지는 인프라 축(§4). 유입 증가 후 재평가 |
| **Out** | 다국어 34개 언어 | 없음 | 높음 | **비추격** — 정부 ai.moel.go.kr가 34개 언어로 이미 점유. 승산 없음 |
| **Out** | 인포그래픽·뉴스·아카이브 | 없음 | 높음(상시 운영 인력) | **비추격** — 재단형 조직의 구조적 강점 |
| **Out** | 전문가 인계(`/helpme`) | 없음 | 높음(오프라인 전문가 네트워크) | **비추격** — 제휴 없이는 불가 |
| **Out** | 계정 체계 | 없음(익명 설계) | 중간 | **비추격** — 익명성이 노동상담의 진입장벽을 낮추는 우리 설계 의도 |

**P0 SEO에 관한 추가 기회**: 그들의 SEO는 페이지별 title·description, OG/Twitter 풀세트(`og-image.jpg` 1200×630, `og:locale ko_KR`), 네이버·구글 사이트 인증, 키워드 메타, sitemap까지 갖췄지만 **JSON-LD 구조화 데이터는 0건**이다(`application/ld+json` 미검출). 우리는 이미 `FAQ_DATA` 20문항과 25개 계산기 페이지, 공개 게시판을 갖고 있으므로 `FAQPage`·`WebSite`·`BreadcrumbList` 구조화 데이터를 넣으면 **기본기를 따라잡는 동시에 한 칸 앞설 수 있다**. 우선 착수 근거를 하나 더 얻은 셈이다.

### 6.3 경쟁사와 무관하게 인벤토리 중 발견된 내부 결손 (기록용)

본 대조 작업 중 우리 코드에서 확인된, 경쟁 분석과는 별개로 처리해야 할 항목이다. 본 사이클 범위 밖이며 별도 티켓으로 넘긴다.

| 항목 | 실측 | 영향 |
|------|------|------|
| 관리자 남용 대시보드 **UI 미구현** | `/api/admin/abuse`·`/unblock` API는 존재하나 `admin.html`에 화면 없음(`grep abuse` 0건) | 가드가 fail-open이라 **조용히 실패**하는데 관측 화면이 없어 운영 검증 불가 |
| `board_posts` 스키마가 SQL 파일에 없음 | 전 `supabase_*.sql` grep 0건 — 수동 생성 추정 | 재구축·마이그레이션 시 재현 불가 |
| `CLAUDE.md` 수치 구정보 5건 | §3.3 각주 | 신규 작업자·에이전트가 잘못된 전제로 작업 |
| **첨부파일 버킷이 공개 상태** | `app/core/storage.py:254` `get_public_url()` 사용, `api/index.py:619` 주석이 "전환해도 동작하도록"이라 **전환이 아직 미완료**임을 시사 | 상담 첨부(급여명세서·근로계약서 등)의 URL이 공개 접근 가능. **P0 개인정보처리방침 작성 중 발견** — 방침에 "비공개 보관"을 쓸 수 없어 표기를 보류함 |

### 6.4 전략 결론

> **경쟁 축이 직교한다.** 그들은 *폭*(채널·언어·도구·콘텐츠)으로, 우리는 *깊이*(계산·코퍼스·검증)로 경쟁한다.
> 폭을 전면 추격하면 우리 깊이를 유지할 리소스가 사라지고, 정부 서비스(34개 언어·8.08억 예산)와의 정면충돌만 남는다.
> 따라서 본 사이클은 **"도달률(P0) + 행동 전환(P1)"에만 투자**하고, 콘텐츠·다국어·전문가 네트워크는 명시적으로 포기한다.

---

## 7. Scope

### 7.1 In Scope (본 분석 사이클)

- [x] ai4labor.net 공개 자산 정적 수집·해부 (페이지 10 / 청크 40 / PWA·SEO 자산)
- [x] 자매 사이트 cweh-migrant.org 식별 및 제품군 구조 규명
- [x] 기능 전수 대조 매트릭스 + 키워드 부재 검증
- [x] 아키텍처·지식 파이프라인 대조
- [x] 우리 자산 실측치 확보(계산기 25 / 코퍼스 60,174 / 엔드포인트 23 / 흐름도 25)
- [x] 격차 3분류(즉시회수·선별이식·비추격) 판정
- [ ] 후속 구현 사이클의 Plan 분리 발행 (§10 Next Steps)

### 7.2 Out of Scope

- ai4labor.net에 대한 **동적 테스트·서버액션 호출·부하·취약점 스캔** — 일절 수행하지 않음
- 경쟁사 콘텐츠·데이터의 복제 또는 재배포
- 본 사이클에서의 실제 기능 구현 (P0/P1은 각각 독립 PDCA 사이클로 분리)
- 다국어·인포그래픽·뉴스·전문가 인계·계정 체계 (§6.2 Out 판정)

---

## 8. Requirements

### 8.1 Functional Requirements (본 분석 사이클)

| ID | 요구사항 | 우선순위 | 상태 |
|----|----------|:--------:|:----:|
| FR-01 | ai4labor.net의 기술 스택을 응답 헤더·번들 근거로 확정 | High | ✅ 완료 (§2.2) |
| FR-02 | 페이지·기능 전수 목록화 및 우리 기능과 1:1 대조 | High | ✅ 완료 (§3.1) |
| FR-03 | "없음" 주장을 전수 카운트로 검증(추측 금지) | High | ✅ 완료 (§3.2) |
| FR-04 | 지식 파이프라인(라이브 조회 vs 사전 색인) 차이 규명 | High | ✅ 완료 (§4) |
| FR-05 | 그들의 우수 설계를 재현 가능한 규격 수준으로 기록 | Medium | ✅ 완료 (§5) |
| FR-06 | 격차를 채택/보류/비추격으로 판정하고 근거 명시 | High | ✅ 완료 (§6) |
| FR-07 | 후속 구현 사이클을 Plan 단위로 분해 | High | ✅ 완료 (§10) |

### 8.2 후속 구현 사이클의 요구사항 개요 (별도 Plan에서 상세화)

| ID | 사이클 | 핵심 요구 | 우선순위 |
|----|--------|-----------|:--------:|
| FR-A1 | `seo-discoverability` | `public/robots.txt`·`sitemap.xml` 추가, `index.html`/`board.html`/`calculators.html` `<head>`에 description·og·twitter·canonical 주입, vercel.json 라우트 반영. **JSON-LD(`FAQPage`·`WebSite`·`BreadcrumbList`)까지 넣어 경쟁사(JSON-LD 0건)를 넘어설 것** — FAQ 20문항(`FAQ_DATA`)이 그대로 재료 | P0 |
| FR-A2 | `pwa-install` | `manifest.webmanifest` + 아이콘 세트 + **파비콘** + 오프라인 셸 SW(정적 자산만 캐시, `/api/*` 제외) + 설치 안내 | P0 |
| FR-A3 | `legal-notices` | 이용약관·개인정보처리방침 작성 및 푸터 링크 연결(현재 `href="#"`), 운영주체·문의처 표기 정비 | P0 |
| FR-B0 | `calculator-input-ui` | 28 타입 엔진을 쓰는 **직접 입력 계산기 폼**. 흐름도 페이지에 입력 위젯 병설 또는 `/calculators` 확장. 기존 `WageCalculator.calculate()` 재사용, 결과는 챗봇과 동일 포맷 | P1 |
| FR-B1 | `document-builder` | 진정서·구제신청서·근로감독 청원 초안 생성. 기존 RAG·계산 결과를 근거로 삽입, 노동포털·e-노동위 접수 링크 연결, 면책 고지 강제 | P1 |
| FR-B2 | `embed-widget` | `/widget` 경량 페이지 + postMessage 높이 동기화(**targetOrigin 명시 + 수신 origin 검증** — 경쟁사는 `"*"`) + 임베드 코드 안내 페이지. 위젯은 **AI를 직접 호출하지 않고** `/?q=…`로 본 사이트를 새 탭에 열어 기존 `_guard_chat_request()` 경로를 그대로 태운다 → **LLM 비용 증가 0, 가드 변경 0** | P1 |

### 8.3 Non-Functional Requirements

| 범주 | 기준 | 측정 방법 |
|------|------|-----------|
| 준법성 | 경쟁사 자산 무단 복제 0건, 동적 호출 0건 | 본 문서 §1.2 수행 기록 |
| 재현성 | 모든 주장에 수집 명령·근거 문자열 첨부 | 문서 내 근거 열 |
| 무회귀 | 후속 구현이 기존 오프라인 스위트 4종 전부 통과 | `test_wage_golden`·`test_pipeline_wiring`·`test_offline_units`·`test_abuse_guard` |
| 성능 | SEO/PWA 추가가 초기 렌더에 영향 없음 | 정적 파일 추가만, `index.html` 증분 < 5KB |
| 보안 | 위젯 도입 시 기존 `_guard_chat_request()` 선통과 유지 | CLAUDE.md 규약 준수 검증 |

---

## 9. Success Criteria

### 9.1 Definition of Done (본 분석 사이클)

- [x] ai4labor.net 페이지·번들·PWA·SEO 자산 전수 수집
- [x] 기능 대조 매트릭스 14항목 작성, 각 항목 근거 명시
- [x] 부재 주장 7건을 전수 카운트로 검증
- [x] 우리 자산 실측치 6종 확보
- [x] 격차 12건을 채택/보류/비추격으로 판정
- [ ] 후속 P0/P1 Plan 4건 발행

### 9.2 Quality Criteria

- [x] 추측과 사실을 문장 단위로 분리 표기 (LLM 모델명 등 미확정 항목은 "추정" 명시)
- [x] 대상 서버에 쓰기·LLM 호출성 요청 0건
- [ ] 후속 구현 시 기존 CI 스위트 무회귀

---

## 10. Next Steps

1. [x] **P0 전량 구현 완료** (2026-08-01, §14 Do 실행 기록 참조) — FR-A1·A2·A3
2. [ ] **P0 배포 후 검증** — Search Console·네이버 서치어드바이저 사이트 등록, `sitemap.xml` 제출, 구조화 데이터 테스트, Lighthouse PWA 감사
3. [ ] **`/pdca plan calculator-input-ui`** (P1) — 최대 강점의 전달 경로 개통
4. [ ] **`/pdca plan document-builder`** (P1) — 상담→행동 전환. 기존 RAG·계산 자산 재활용
5. [ ] **`/pdca plan embed-widget`** (P1) — 배포 채널 확장. `/?q=` 진입점이 이미 있어(`index.html:1845-1850`) 구현 부담이 더 낮아짐
6. [ ] 보류 3건(입력식 폼·통합검색 UI·지도)은 P1 완료 후 효과 측정 결과로 재평가
7. [x] ~~별도 티켓: 첨부 버킷 비공개 전환~~ → **완료**(§14.7, 2026-08-01) — 6번 항목에서 분리해 이번 사이클 안에서 처리
8. [ ] 별도 티켓(미착수): `CLAUDE.md` 계산기 수치 정정(계산 28종·CLI 116·배치 500·이메일 5건/분 등, §3.3 참조 — 이번 사이클에서는 GitHub Pages 배포 절만 갱신함), 관리자 남용 대시보드 UI, `board_posts` 스키마 SQL화

---

## 14. Do 실행 기록 (2026-08-01)

계획 §8.2의 P0 3건을 이 사이클 안에서 구현했다. Design 문서 없이 진행한 근거: §8.2와 §12.3이 파일 단위까지 명세하고 있고, 산출물이 전부 **정적 자산 추가 + `<head>` 주입**이라 런타임 경로를 건드리지 않는다.

### 14.1 산출물

| FR | 파일 | 내용 |
|----|------|------|
| A1 | `public/robots.txt` (신규) | 전체 허용 + `/admin`·`/api/` 차단 + sitemap 선언 |
| A1 | `public/sitemap.xml` (신규) | **31 URL** — 홈·게시판·계산기 + 흐름도 25 + 약관·방침·설치안내 |
| A1 | `public/index.html` | description·keywords·canonical·robots·OG 9종·Twitter 4종 + **JSON-LD `@graph`(WebSite·Organization·WebApplication)** |
| A1 | `public/board.html` | canonical·OG·Twitter + JSON-LD `CollectionPage`. 타이틀 브랜드를 "노동OK"→"기초 노동상담"으로 통일 |
| A1 | `public/calculators.html` | description·canonical·OG + **JSON-LD `ItemList` 25건**(사이드바 링크에서 자동 추출). 타이틀 "AI 노동상담"→"기초 노동상담" |
| A1 | `public/og-image.png` (신규) | 1200×630 브랜드 공유 카드 |
| A2 | `public/manifest.webmanifest` (신규) | standalone, 테마 `#1B2A4A`, 아이콘 4종, 바로가기 2종 |
| A2 | `public/favicon.svg`·`favicon.ico`·`icons/` (신규) | 저울 마크(네이비+코퍼+크림) — 16·32·180·192·512 + maskable 512 |
| A2 | `public/sw.js` (신규) | 오프라인 셸. **`/api/*`·`/admin` 미개입**, 내비게이션 network-first, 정적 자산 cache-first |
| A2 | `public/index.html` | 아이콘·매니페스트 링크, theme-color, iOS 메타. **SW 등록은 Act-1에서 `/pwa.js`로 분리**(§16) |
| A3 | `public/terms.html` (신규) | 9개 조항. 답변의 법적 성격·금지 행위·이용 제한·책임 한계 |
| A3 | `public/privacy.html` (신규) | 9개 항목. **처리위탁 및 국외 이전 7개 수탁자 명시**, 게시판 공개 고지, IP 해시 처리 |
| A3 | `index.html`·`board.html` | 푸터 `href="#"` → 실제 링크 연결 |
| — | `vercel.json` | `/terms`·`/privacy`(+Act-1에서 `/install`) 라우트, `/sw.js`에 `no-cache` + `Service-Worker-Allowed: /` |

### 14.2 설계 판단 기록

- **FAQPage 구조화 데이터 미채택** — `FAQ_DATA` 20문항은 질문 프롬프트만 있고 답변이 페이지에 노출되지 않는다. 답변 가시성 요건을 못 맞추므로 넣지 않았다(`index.html` 주석에 근거 명시). 대신 `WebSite`+`Organization`+`WebApplication`, 계산기는 `ItemList`로 대체.
- **서비스워커 보수적 설계** — 상담 응답·SSE가 캐시로 오염되면 치명적이므로 `/api/*`를 아예 가로채지 않는다. 내비게이션은 network-first라 배포 즉시 최신 화면이 뜨고, 오프라인일 때만 캐시로 떨어진다.
- **개인정보처리방침에 "첨부파일 비공개 보관" 미표기** — §6.3의 버킷 공개 상태가 해소되지 않아 사실과 다른 표기를 피했다. 전환 완료 후 방침을 갱신할 것.

### 14.3 검증 결과

| 항목 | 결과 |
|------|------|
| JSON/XML 유효성 | `vercel.json`·`manifest.webmanifest`·`sitemap.xml` ✅ |
| JSON-LD 파싱 | 3개 페이지 전부 ✅ |
| HTML 구조 | 5개 페이지 태그 균형 ✅ |
| 인라인 JS 문법 | `node --check` ✅ (index 인라인 2블록, `sw.js`) |
| 로컬 HTTP 스모크 | `python3 -m http.server`(cwd=`public/`) 기준 16개 경로 전부 **200** + Content-Type 정상 ✅. 확장자 없는 경로(`/board`·`/terms` 등)는 이 서버로 확인할 수 없어 Act-1에서 `api/index.py`에 라우트를 추가했다(§16) |
| `test_answer_renderer.js` | **8/8 통과** — `index.html` 수정이 답변 렌더러에 무영향 ✅ |
| `test_wage_golden.py` | 전량 통과 ✅ |
| `test_pipeline_wiring`·`test_offline_units`·`test_abuse_guard` | **실행 불가** — 이 워크스페이스에 `anthropic`·`pydantic`·`jwt` 미설치. `git stash`로 변경을 되돌려도 동일하게 실패하므로 **본 작업과 무관한 선행 상태**. CI에서는 `requirements.txt` 설치 후 실행됨 |
| `index.html` 증분 | 84,419 → 89,132 바이트 (**+4.6KB**, NFR 상한 5KB 이내) ✅ |

### 14.4 운영자 확정 사항 반영 (2026-08-01)

| 항목 | 확정값 | 반영 위치 |
|------|--------|-----------|
| 개인정보 보호책임자 | **김창수 / 청년노동자인권센터 대표** | `privacy.html` 제8항 |
| 보유기간 | **1년** (대화·첨부·게시글) | `privacy.html` 제5항 |
| 데이터 리전 | **서울(대한민국)** | `privacy.html` 제3항 — Supabase를 국외 이전 목록에서 제외하고, 국외로 나가는 것은 **답변 생성용 질문·첨부에 한정**됨을 명시 |
| 변경 공지 방법 | **서비스 내 공지사항** | `terms.html` 제3·7조, `privacy.html` 제9항 |
| 이용 한도 | **공개** | `terms.html` 제5조에 표로 명시 — 질문 2,000자 / 60초당 5회 / 하루 50회 / 위반 누적 시 30분 차단 |

한도 수치는 `app/core/abuse_guard.py:25-32`의 기본값이며 전부 환경변수로 덮어쓸 수 있다. **운영값을 바꾸면 약관 문구도 함께 고쳐야 한다** — 이 의존 관계를 `terms.html` 상단 주석에 남겼다.

### 14.5 "1년 보유"를 이행할 수단 신설

방침이 자동 파기를 약속하는데 코드에는 파기 로직이 없었다. 약속과 구현의 간극을 메우기 위해 **`supabase_retention_purge.sql`**(신규)을 추가했다.

- `purge_expired_data(retention_days INT DEFAULT 365)` — SECURITY DEFINER, `anon`·`authenticated` 실행 권한 회수
- 삭제 순서가 중요하다: `qa_attachments → qa_conversations → qa_sessions`는 `ON DELETE CASCADE`로 묶여 있지만(`supabase_schema.sql:15,31`) **스토리지 객체는 CASCADE 대상이 아니다.** 따라서 `storage.objects`를 먼저 지운 뒤 대화를 삭제해 고아 파일을 남기지 않는다.
- `board_posts`는 스키마 파일이 없는 수동 생성 테이블(§6.3)이므로 `to_regclass` 로 존재할 때만 처리한다.
- 파일은 **미리보기(§2) → 수동 1회 실행(§3) → pg_cron 등록(§4)** 순서로만 진행하도록 구성했고, 실제 실행은 하지 않았다.
- **v1.1(Act-1)**: 남용 3테이블(`abuse_events` 90일 / `chat_quota` 지난 날짜 / `block_list` 만료분) 파기를 추가하고 `abuse_retention_days` 인자를 신설했다. 반환 컬럼이 4→7로 늘어 `CREATE OR REPLACE`로는 교체되지 않으므로 **`DROP FUNCTION IF EXISTS purge_expired_data(INT);` 선행이 필수**다(파일 §1 상단에 경고 기재).
- **v1.2(적용 중 발견)**: 운영자가 실행했을 때 `ERROR 42501: Direct deletion from storage tables is not allowed`로 실패했다. **Supabase가 `storage.objects` 직접 DELETE를 `protect_delete()` 트리거로 차단**한다 — SQL만으로 첨부파일을 지울 수 있다는 설계 전제가 틀렸다. 2단계 구조로 변경:
  - `purge_expired_data()`는 파일을 지우지 않고 경로를 **`storage_purge_queue`에 적재**(대화 행이 CASCADE로 사라지기 전에)
  - **`purge_storage_orphans.py`**(신규)가 `storage_purge_claim`/`storage_purge_mark` RPC로 큐를 읽어 Storage API로 실제 삭제. 5회까지 재시도, 멱등
  - 첫 반환 컬럼명을 `storage_objects_deleted` → **`storage_objects_queued`**로 변경(의미가 다르므로)
  - **두 축이 모두 돌아야** 방침 제5항이 이행된다. pg_cron만 돌리면 DB 행만 사라지고 파일은 남는다

### 14.6 배포 전 남은 일 — 3건 전부 해소 (2026-08-01)

| # | 항목 | 결정 | 처리 |
|:-:|------|------|------|
| 1 | 첨부 버킷 | **비공개** | §14.7 |
| 2 | 보유기간 파기 스크립트 | **재적용 필요**(운영 검증 대기) | §14.5 참조 — 이 표는 v1.0 시점 기록이며, 이후 v1.1(반환 컬럼 확장)·v1.2(스토리지 큐 방식으로 재설계, `purge_storage_orphans.py` 신설)로 두 차례 바뀌었다. **아직 아래 항목이 확인되지 않아 "적용 완료"로 단언할 수 없다**: ① `SELECT * FROM purge_expired_data(365, 90);` 7개 반환 건수가 §2 미리보기와 일치하는지 ② `cron.job_run_details`에 성공 실행 기록이 있는지 ③ `storage_purge_queue`가 실제로 소진되는지 ④ `purge_storage_orphans.py`가 service_role 키로 주기 실행되도록 구성됐는지(CodeRabbit 리뷰로 anon→service_role 전환, §16.1) |
| 3 | 공지 채널 | **배너 형식** | §14.8 |

남은 것은 커밋·배포(요청 시에만), 위 2번 항목의 운영 검증, 배포 후 Search Console·네이버 서치어드바이저에 사이트·`sitemap.xml` 등록이다.

### 14.7 첨부 버킷 비공개 전환

상담 첨부에는 급여명세서·근로계약서 등이 담기는데 버킷이 공개라 URL을 아는 사람이 인증 없이 내려받을 수 있었다.

| 파일 | 변경 |
|------|------|
| `supabase_attachments_private.sql` (신규) | 현황 확인 → 전환(`public = false` + 죽은 `public_url` NULL 처리) → 검증 → 되돌리기 4단 구성 |
| `supabase_schema.sql:71-79` | 신규 설치도 비공개로 생성되도록 `public` 기본값을 `false`로 수정 |
| `app/core/storage.py::upload_attachment` | `get_public_url()` 호출 제거, `public_url`을 항상 `None`으로 저장. 반환값을 `storage_path`로 변경(호출부는 반환값을 쓰지 않아 무영향 — `pipeline.py:1894`) |
| `api/index.py::admin_conversation_detail` | 주석을 현행화. 열람 경로가 1시간 만료 signed URL **단일**임을 명시 |
| `public/admin.html:390` | `public_url`이 `null`일 때 `href="null"`이 되던 것을 "링크 발급 실패" 표시로 대체 |
| `public/privacy.html` 제7항 | 첨부 접근통제 문구 추가 — 전환이 끝나 이제 사실에 부합 |

**SELECT 정책(`Allow anon read`)은 남겼다.** signed URL 발급은 서명 주체가 해당 객체를 SELECT할 수 있어야 동작한다. 이 anon 키는 서버(FastAPI)에만 있고 브라우저로 나가지 않으므로(`app/config.py:78`, `public/*.html`에 `SUPABASE` 문자열 0건) 정책을 남겨도 외부 노출 경로가 생기지 않는다. 버킷이 비공개인 이상 키 없는 직접 접근은 차단된다.

### 14.8 공지사항 배너

`terms.html` 제3·7조와 `privacy.html` 제9항이 약속한 "서비스 내 공지사항"의 실체.

- **`public/notice.json`** (신규) — 운영자가 이 파일만 고쳐 배포하면 배너가 바뀐다. 백엔드·DB 불필요. `notices` 배열이 비면 배너가 사라진다. 필드: `id`·`level`·`message`·`linkUrl`·`linkText`·`startsAt`·`endsAt`·`dismissible`
- **`public/index.html`** — 랜딩 상단에 `#notice-banner` 삽입 + CSS + 초기화 스크립트
- 동작: 표시 기간에 해당하고 아직 닫지 않은 **첫 공지 하나**만 노출. 닫기는 `localStorage`에 id를 기록(최근 20개)하므로 내용을 바꿀 때는 **id도 함께 바꿔야** 다시 뜬다
- 안전장치: 메시지·링크 전부 이스케이프, **링크는 실제 URL 파서로 해석한 origin이 자기 출처일 때만 허용**(초기 정규식 방식은 `/\evil.com` 우회가 실증되어 Act-1에서 교체 — §16), `fetch` 실패 시 조용히 건너뜀(CLAUDE.md graceful degradation)
- 서비스워커와의 관계: `sw.js`의 `ASSET_PATTERN`에 `.json`이 없고 내비게이션도 아니므로 **가로채지 않는다** — 공지는 항상 네트워크에서 최신본을 읽는다

### 14.9 추가 검증 (2026-08-01, 2차)

| 항목 | 결과 |
|------|------|
| Python 컴파일 | `app/core/storage.py`·`api/index.py` ✅ |
| HTML 구조 | `admin.html`·`terms.html`·`privacy.html` 태그 균형 ✅ |
| CSS 변수 | 배너·법적고지 페이지에서 참조하는 변수 전부 정의됨 ✅ |
| 인라인 JS 문법 | `node --check` ✅ |
| `notice.json` | JSON 유효 ✅ |
| **브라우저 실제 렌더** | Playwright — 배너 정상 표시 → 닫기 클릭 → **새로고침 후에도 숨김 유지** ✅ / `privacy.html` 표·콜아웃·타이포 정상 ✅ / **콘솔 오류·경고 0건** ✅ |
| 회귀 | `test_answer_renderer.js` **8/8**, `test_wage_golden.py` 전량 통과 ✅ |
| sitemap | 31 URL 유지(§14.1 — `install.html` 포함), `terms.html`·`privacy.html` 포함 ✅ |

---

## 11. Risks and Mitigation

| 위험 | 영향 | 가능성 | 완화 |
|------|:----:|:------:|------|
| 경쟁사 표면을 무분별 추격해 핵심(계산·RAG) 품질이 정체 | 높음 | 중간 | §6.2에서 **Out 판정 4건을 명시적으로 고정**. P0/P1 외 착수 금지 |
| 정적 분석 기반 추정을 사실로 오독 | 중간 | 중간 | "추정" 표기 강제(LLM 모델·Firestore 스키마·큐레이션 방식) |
| 위젯 도입이 남용 가드 우회 경로가 됨 | 높음 | 중간 | `/widget`도 `_guard_chat_request()` 선통과 + Origin 기반 쿼터. `embed-widget` Plan의 필수 요건으로 못박음 |
| 서류 생성 기능의 법적 책임 | 높음 | 낮음 | 면책 고지 강제(기존 관례), "초안" 표기, 접수 전 전문가 확인 권고 문구 |
| SEO 강화로 유입 증가 → LLM 비용 급증 | 중간 | 중간 | 기존 일일 쿼터·IP rate limit 유지, 유입 증가 구간에서 쿼터 임계 재조정 |
| 경쟁사 페이지 구조 변경으로 본 분석이 노후화 | 낮음 | 높음 | 수집 스냅샷·수집 일자(2026-08-01) 명시. 재분석 시 §1.2 절차 재실행 |

---

## 12. Architecture Considerations

### 12.1 Project Level Selection

| Level | 특성 | 권장 대상 | 선택 |
|-------|------|-----------|:----:|
| Starter | 단순 구조 | 정적 사이트 | ☐ |
| **Dynamic** | 기능별 모듈, BaaS 연동 | 백엔드 있는 웹앱 | ☑ |
| Enterprise | 엄격한 레이어 분리, DI | 고트래픽·복잡 아키텍처 | ☐ |

기존 프로젝트 레벨(Dynamic) 유지. 본 사이클은 아키텍처 변경을 유발하지 않는다.

### 12.2 Key Architectural Decisions

| 결정 | 옵션 | 선택 | 근거 |
|------|------|------|------|
| 프레임워크 전환 | Next.js 이관 / FastAPI 유지 | **FastAPI + 정적 HTML 유지** | 계산 엔진·RAG가 Python 자산. SEO는 정적 메타·sitemap으로 해결 가능하므로 전환 편익이 이관 비용을 넘지 못함 |
| SEO 구현 | SSR 도입 / 정적 메타 보강 | **정적 메타 보강** | 현재 페이지가 이미 정적 HTML. `<head>` 태그 + sitemap/robots만으로 색인 가능 |
| PWA | next-pwa / 수제 SW | **수제 경량 SW** | 정적 셸만 캐시. `/api/*`는 캐시 제외해 상담 응답 신선도 보장 |
| 서류 생성 | 신규 LLM 경로 / 기존 파이프라인 확장 | **기존 파이프라인 확장** | `analyze_intent` 결과·RAG 히트·계산 결과를 그대로 근거로 사용 |
| 위젯 동작 | 임베드 내 챗 실행 / **유입 깔때기** | **유입 깔때기** | 경쟁사 실측대로 위젯은 질문만 받아 본 사이트를 새 탭에 연다. LLM 호출이 위젯에서 발생하지 않아 **비용·가드·CORS 문제가 전부 사라진다** |
| 위젯 격리 | 별도 배포 / 동일 앱 라우트 | **동일 앱 라우트(`/widget`)** | 정적 페이지 1장. 별도 배포는 불필요 |
| CDN 방어 계층 | Cloudflare 도입 / Vercel 단독 | **재평가 대상** | 경쟁사는 앞단에서 봇을 차단(기본 UA 403). 유입 증가 후 비용 대비 효과 측정 |

### 12.3 영향 받는 모듈

```text
public/
├── index.html              # <head> 메타·og·JSON-LD 주입, Pretendard 실제 로드, 푸터 법적 링크 (P0)
├── board.html              # <head> 메타 (P0)
├── calculators.html        # <head> 메타 + 입력형 계산기 진입 (P0/P1)
├── robots.txt              # 신규 (P0)
├── sitemap.xml             # 신규 (P0)
├── manifest.webmanifest    # 신규 (P0)
├── favicon.ico + icons/    # 신규 — 파비콘 + PWA 아이콘 세트 (P0)
├── sw.js                   # 신규 — 정적 셸만 캐시, /api/* 제외 (P0)
├── terms.html              # 신규 — 이용약관 (P0)
├── privacy.html            # 신규 — 개인정보처리방침 (P0)
├── calculator_flow/*.html  # 흐름도 페이지에 입력 위젯 병설 (P1)
└── widget.html             # 신규 — 경량 임베드 챗 (P1)

api/index.py                # /widget·/terms·/privacy 라우트, 계산 폼 엔드포인트, 위젯 CORS·CSP (P0/P1)
app/core/                   # document_builder.py 신규 (P1) — 기존 pipeline 결과 재사용
wage_calculator/            # 변경 없음 — WageCalculator.calculate() 그대로 재사용 (P1)
vercel.json                 # 신규 정적 파일·라우트 반영 (P0)
```

---

## 13. Convention Prerequisites

### 13.1 기존 프로젝트 컨벤션 확인

- [x] `CLAUDE.md`에 코딩 컨벤션·운영 관례 존재
- [ ] `docs/01-plan/conventions.md` 부재 (본 사이클에서 불필요)
- [x] CI 워크플로 `.github/workflows/tests.yml` 존재
- [x] 오프라인 테스트 스위트 4종 존재

### 13.2 본 사이클에서 지켜야 할 관례

| 범주 | 규칙 |
|------|------|
| 신규 채팅 경로 | `/widget` 추가 시 `_guard_chat_request()`를 세션 생성·첨부 파싱보다 **먼저** 호출, `process_question(guard_ctx=...)` 전달 |
| 파일 서빙 | `os.path.commonpath` + 확장자 allowlist로 path traversal 방지 |
| 공개 응답 | 게시판·대화 노출은 `_anonymize()` 통과 필수 |
| Graceful degradation | 신규 기능은 실패 시 폴백 경로 필수(SW 미지원 브라우저, 지도 API 실패 등) |
| 커밋 | `app/core/*.py` 신규 모듈은 반드시 커밋(Vercel import 500 방지) |

### 13.3 필요 환경변수

| 변수 | 용도 | 범위 | 신규 |
|------|------|------|:----:|
| (없음) | P0(SEO/PWA/법적고지)는 환경변수 불요 | — | ☐ |
| (없음) | P1 위젯도 불요 — 유입 깔때기 구조라 서버 상태 없음 | — | ☐ |
| `GOOGLE_MAPS_API_KEY` | 지도 기반 기관 찾기 | Client | ☐ (P2 보류) |

> 경쟁사는 Google Maps 키를 클라이언트 번들에 하드코딩해 두었다. 우리가 P2로 지도를 도입한다면 **HTTP 리퍼러 제한 + API 제한을 반드시 건 상태로** 배포할 것.

---

---

## 16. Act-1 실행 기록 (2026-08-01) — Check 84% → Re-Check

`docs/03-analysis/competitor-analysis-ai4labor.analysis.md`의 갭 16건 중 **15건을 수정**했다. G-5(GitHub Pages 미러 용도)만 제품 결정이 필요해 보류했다.

### 16.1 추가·변경된 산출물 (§14.1 산출물 표에 없던 것)

| 파일 | 성격 | 내용 |
|------|------|------|
| `public/install.html` | 신규 | 기기별 PWA 설치 안내(iOS Safari / Android Chrome / 데스크톱). `beforeinstallprompt` 가능 시 즉시 설치 버튼 노출 |
| `public/pwa.js` | 신규 | SW 등록 + 설치 프롬프트 캡처. **index·board·calculators·install 4페이지가 공유**. 등록 조건은 `window.isSecureContext`(localhost 포함) |
| `public/offline.html` | 신규 | 오프라인 전용 화면. 이전에는 `/terms` 요청에 홈 HTML이 응답하던 문제 해소 |
| `public/calculator_flow/*.html` (25) | 수정 | 고유 title·description·canonical·robots·OG + `BreadcrumbList` + 단독 진입 전용 홈 링크 |
| `api/index.py::serve_static_page` | 신규 | `/board`·`/terms`·`/privacy`·`/install` — **로컬 uvicorn 개발용**. 프로덕션은 `vercel.json`이 선처리 |
| `supabase_retention_purge.sql` v1.1 | 수정 | §14.5 참조 |
| `public/calculators.html` | 수정 | 푸터 신설(운영주체·법적고지·설치 링크) |

### 16.2 갭별 조치

| Gap | 조치 | 검증 방법 |
|-----|------|-----------|
| G-1 | `purge_expired_data()`에 남용 3테이블 파기 추가, `privacy.html` 제5항 표를 6행으로 세분 | SQL 정합성 대조 |
| G-2·G-7 | `install.html` + `pwa.js` + 슬라이드 메뉴 항목, 4페이지 SW 등록 | 브라우저에서 SW 활성(`shell-v2-2026-08-01`) 확인 |
| G-3 | 흐름도 25개 메타 주입 | title 25/25 고유, canonical·description 25/25 |
| G-4 | SW 내비 캐시 키를 `url.pathname`으로 정규화 | **`/?q=회사에서 임금을…` 진입 후 Cache Storage 실측 — 질문 미저장 확인** |
| G-6 | `serve_static_page` 4라우트 | AST로 데코레이터·임포트 확인 |
| G-8 | 정규식 → `new URL(...).origin` 비교 | **`//evil.com`·`/\evil.com`·`https://evil.com`·`javascript:` 전부 차단 실증** |
| G-9·G-10·G-11 | `@graph` + `WebSite` 스텁, `BreadcrumbList` 27개소, Twitter 4종 | JSON-LD 28페이지 파싱 통과 |
| G-12 | `admin.html` noindex + `calculators.html` 푸터 | 브라우저에서 푸터 렌더·링크 6종 확인 |
| G-13·G-14·G-16 | 주석 현행화, `notice.json` level 2종, "합계 3MB" 정정 | 문자열 대조 |
| G-15 | `VERSION='v2-2026-08-01'` + `/offline.html` 분리 | 캐시 이름 실측 |
| G-0 | 모바일 배너 닫기 버튼 겹침 | 390·830·1200px `elementFromPoint` 확인 |
| **G-5** | **보류** — GitHub Pages 미러를 유지할지 폐기할지 제품 결정 필요 | — |

### 16.3 Re-Check가 새로 찾아낸 것 (Act-1이 만든 결함)

수정 과정에서 만든 결함을 재검증이 잡아냈고 모두 처리했다.

| # | 결함 | 원인 | 조치 |
|:-:|------|------|------|
| **N-1** | 흐름도 홈 링크가 **iframe 안에서도 보였다** | `<a hidden style="display:block">` — 인라인 스타일이 UA의 `[hidden]{display:none}`(`!important` 없음)을 이긴다. 같은 함정을 `#notice-banner[hidden]`에서는 이미 처리했으면서 여기서 재발 | `hidden` 속성 대신 `style="display:none"` + JS 토글, `target="_top"` 추가. **iframe `display:none` / 단독 `block` 실측 확인** |
| N-3 | `offline.html` 버튼 폰트 미적용 | `font: 600 14px/1 inherit` — 단축 속성의 family 자리에 `inherit`은 무효라 선언 전체가 드롭 | 개별 속성으로 분해 |
| N-4 | 설치 완료자에게 설치 안내를 띄움 | standalone 분기가 `/install.html`로 이동 | standalone이면 `promptInstall()` no-op + `[data-pwa-install]` 진입점 숨김 |
| N-5 | `install.html`로 가는 크롤 가능한 링크 0 | JS `location.href` 진입만 존재 | index·board·calculators 푸터에 링크 추가 |
| 부수 | localhost에서 SW 미등록 | `location.protocol === 'https:'` 판정이 localhost를 배제 | `window.isSecureContext`로 교체 |

### 16.4 배포 전 필수 (Re-Check 지적)

1. **`supabase_retention_purge.sql` v1.1 재적용** — `DROP FUNCTION` 선행 없이 실행하면 `cannot change return type of existing function`으로 실패한다.
2. **파기 양성 검증** — `abuse_events`·`chat_quota`·`block_list`는 RLS ON + 정책 0개다. SECURITY DEFINER 소유자가 테이블 소유자가 아니면 DELETE가 **에러 없이 0건**으로 끝난다(`chatbot-security`의 fail-open과 같은 함정). `SELECT * FROM purge_expired_data(365, 90);` 반환 건수로 확인할 것.
3. ~~**G-5 결정**~~ → **해결(2026-08-01)**: 운영자가 **미러 미사용**을 확정. `.github/workflows/pages.yml` 삭제로 GitHub Pages 배포를 중단했고 `CLAUDE.md` 배포 절도 갱신했다. **배포처는 Vercel 단일.** 이미 게시된 Pages 사이트는 워크플로 삭제만으로 내려가지 않으므로 **GitHub 저장소 Settings → Pages 에서 Source 를 None 으로** 바꿔야 완전히 종료된다. `public/*.html`의 `github.io` 분기는 비-Vercel 호스트용 폴백으로 무해해 그대로 두었다.

### 16.5 CodeRabbit 리뷰 대응 (PR #29, 2026-08-01)

PR 생성 시 자동 트리거된 리뷰가 actionable 12건을 남겼다. 전부 코드와 대조 검증한 뒤 대응했다.

**수정 완료(10건)**

| 지적 | 조치 |
|------|------|
| **`purge_storage_orphans.py`가 anon 키(`SUPABASE_KEY`)를 사용 — storage.objects에 DELETE 정책이 없어 삭제가 실패한다** | `SUPABASE_SERVICE_ROLE_KEY`로 교체. `.env.example` 추가, `storage_purge_claim`/`storage_purge_mark`의 anon·authenticated 실행 권한도 함께 회수(더 이상 필요 없어진 불필요한 공격 표면) |
| `api/index.py::serve_static_page`가 CLAUDE.md의 `commonpath`+`.html` allowlist 관례와 다른 패턴 | `serve_calculator_flow`와 동일한 검증 추가(현재 traversal 위험은 없으나 일관성·방어적 코딩) |
| `purge_storage_orphans.py` 마킹 실패가 조용히 무시됨(S110) | 실패 로그 추가 |
| `vercel.json`의 `/notice.json`이 CDN 캐시 제어 헤더 없이 일반 확장자 라우트로 처리됨 — 법적 고지 갱신 지연 위험 | `/sw.js`와 동일한 `no-cache, no-store, must-revalidate` 전용 라우트 추가 |
| `vercel.json`의 `/terms`·`/privacy`·`/install`(확장자 없이)이 sitemap·canonical·모든 내부 링크 어디서도 쓰이지 않는 죽은 라우트 | 3개 라우트 제거. `api/index.py::serve_static_page`도 `/board`만 남기도록 정합화(로컬 uvicorn 개발용 — 프로덕션은 vercel.json 우선) |
| 계산기 흐름도 25개 페이지에 `apple-touch-icon`·`manifest`·`twitter:*` 메타데이터 누락 | 25개 파일 전부에 추가 |
| 계산기 흐름도 24개 페이지가 "근로기준법 기준"으로 획일 표기 — EITC(조세특례제한법)·육아휴직급여(고용보험법)·퇴직금(근로자퇴직급여보장법) 등 실제로 다른 법이 적용됨 | 계산기별 정확한 준거 법령으로 교체(24개 파일) |
| `privacy.html` HTML 주석에 내부 파일 경로·함수명 노출(공개 소스에서 그대로 보임) | 의존관계 정보를 `CLAUDE.md`로 이관, 주석은 참조 안내로 축소. 동일 패턴이던 `terms.html`도 함께 정리 |
| `privacy.html` head 메타데이터가 board·install·calculators와 패턴 불일치(apple-touch-icon·완전한 og/twitter·JSON-LD 없음) | 동일 패턴으로 통일(`WebSite`+`BreadcrumbList`). `terms.html`도 일관성 있게 동일 적용 |
| Plan 문서 markdown fenced block 2곳에 언어 식별자 없음(MD040) | `text` 지정 |

**문서 정확성 수정(4건 — Plan/Analysis 자기보고 오류)**

| 지적 | 조치 |
|------|------|
| §10 Next Steps가 이미 완료된 "첨부 버킷 비공개 전환"(§14.7)을 미완료로 표시 | 완료 처리하고 6번 항목에서 분리. 나머지(CLAUDE.md 계산기 수치 정정·관리자 대시보드·board_posts SQL화)는 실제로 미착수 상태임을 확인해 유지 |
| §14.6이 파기 스크립트를 "적용 완료"로 단언 — 이후 v1.1·v1.2로 두 차례 재설계됐고 최신판 실제 적용 여부는 미확인 | "재적용 필요(운영 검증 대기)"로 낮추고, 완료로 표기하려면 확인해야 할 4개 항목(반환 건수·cron 실행 이력·큐 소진·주기 실행 구성)을 명시 |
| §14.9가 정정 전 "30 URL"을 그대로 인용 | 31로 수정 |
| `analysis.md` 최상단이 v1.0 판정(84%)만 보여줘 Re-Check(100%)를 못 보고 오해하기 쉬움 | 최신 판정을 최상단에 배치하고, 기존 §1~§6은 "baseline 기록"임을 명시 |

**검증 후 스킵(2건 — 근거 명시)**

| 지적 | 스킵 사유 |
|------|-----------|
| `index.html`의 `innerHTML` 대입을 `textContent`+DOM API로 교체(정적분석 경고) | CodeRabbit 스스로 "💤 Low value"로 표시했고 XSS 위험이 낮다고 인정(모든 동적 값이 `esc()` 이스케이프 + origin 검증 완료). 렌더러 전체를 DOM API로 재작성하는 리스크가 방어 이득보다 크다 |
| Plan 문서 front matter `version: 1.2`와 `Version History`(0.1~0.5) 불일치 | 이 프로젝트의 모든 plan 문서가 `template: plan\nversion: 1.2`를 템플릿 스키마 버전으로 공유한다(`plan.template.md` 정의) — 문서 개정 이력과는 별개 필드다. 이 문서만 바꾸면 40여 개 다른 plan 문서와의 관례에서 벗어난다 |

**범위 밖으로 분류(1건 — 별도 과제)**

| 지적 | 사유 |
|------|------|
| `app/core/storage.py::upload_attachment`이 Storage 업로드 성공 후 `qa_attachments` INSERT 실패 시 고아 파일을 남길 수 있음(outbox 패턴 등 실패 원자성 보장 필요) | 유효한 지적이나 이번 PR이 새로 만든 문제가 아니라 **기존 코드의 사전 존재 아키텍처 이슈**다. 해결에는 pending-metadata outbox + 조정(reconciliation) 메커니즘이 필요해 SEO/PWA/법적고지 P0 범위를 크게 벗어난다. 별도 사이클로 이관 — 현재는 `purge_expired_data()`의 파기 큐 적재 로직이 `qa_attachments` 조인 기준이라 이런 고아 파일을 찾지 못한다는 점도 함께 기록해 둔다 |

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-08-01 | 최초 작성 — ai4labor.net 정적 분석 및 격차 판정 | DrunkenZealnut |
| 0.2 | 2026-08-01 | Do 단계 실행 — P0(FR-A1/A2/A3) 구현 완료, §14 실행 기록 추가. Pretendard 오기 정정, 첨부 버킷 공개 상태를 §6.3에 추가 | DrunkenZealnut |
| 0.3 | 2026-08-01 | 운영자 확정값(보호책임자·보유기간 1년·서울 리전·공지사항·한도 공개) 반영, `supabase_retention_purge.sql` 신설(§14.5) | DrunkenZealnut |
| 0.4 | 2026-08-01 | 배포 전 잔여 3건 해소 — 첨부 버킷 비공개 전환(§14.7), 공지사항 배너 신설(§14.8), 파기 스크립트 적용 확인. 브라우저 렌더 검증 추가(§14.9) | DrunkenZealnut |
| 0.5 | 2026-08-01 | Check(84%) → Act-1 갭 수정 → Re-Check. §14 stale 행 현행화, §16 Act-1 실행 기록 추가 | DrunkenZealnut |
| 0.6 | 2026-08-01 | PR #29 CodeRabbit 리뷰 대응(§16.5) — purge 스크립트 anon→service_role 키 전환(가장 중요), 흐름도 25개 법령 오기·메타데이터 누락 수정, 죽은 라우트 정리, privacy/terms 내부정보 노출 제거, §10·§14.6·§14.9 stale 서술 정정 | DrunkenZealnut |
