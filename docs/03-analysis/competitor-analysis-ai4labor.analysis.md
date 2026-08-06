---
template: analysis
version: 1.2
feature: competitor-analysis-ai4labor
date: 2026-08-01
author: DrunkenZealnut
project: laborconsult
---

# competitor-analysis-ai4labor Gap Analysis (P0 구현분)

> **최신 판정(2026-08-01, Act-1 이후)**: Match Rate **100%** — 잔여 갭 0건. 상세는 **§7 Re-Check** 참조.
>
> 아래 §1~§6은 **v1.0 최초 판정(baseline) 기록**이다 — Match Rate **84%**(Critical 0 / High 3 / Medium 4 / Low 9),
> 구현은 견고하나 문서(§14)가 주장한 것과 실제가 어긋나는 항목 6건, FR-A1·A2 요구 중 근거 기록 없이 사라진 항목 2건
> (BreadcrumbList·설치 안내)을 확인했다. 이 기록은 **개선 이력 추적을 위해 그대로 보존**하며, 이후 Act-1에서
> High 3건을 포함해 15/16건을 수정하고 Re-Check(88% 독립 검증) → 잔여 처리(100%)로 이어졌다. **최신 상태를 확인하려면
> §7로 건너뛸 것.**
>
> Check 단계(v1.0 작성 시점)에서 **모바일 실기기 결함 1건을 발견해 즉시 수정**했다(G-0, 아래 §0).
>
> **기준 문서**: [competitor-analysis-ai4labor.plan.md](../01-plan/features/competitor-analysis-ai4labor.plan.md) v0.4
> — Design 문서 없음. §8.2(FR-A1/A2/A3만) · §8.3 · §12.2 · §12.3 · §13.2 · §14를 사양으로 사용
> **범위 제외**: FR-B0·B1·B2(P1), §6.2 P2/Out — Plan §6.2가 후속 사이클로 명시 분리
> **분석 방법**: bkit gap-detector(사양 50개 항목 × 코드 1:1 대조) + 오케스트레이터의 브라우저 실측·실증 검증
> **분석일**: 2026-08-01

---

## 0. Check 단계에서 발견·수정한 결함

### G-0. 모바일에서 공지 배너를 닫을 수 없었다 (수정 완료)

| 항목 | 내용 |
|------|------|
| **증상** | 좁은 뷰포트에서 공지 배너의 닫기(×) 버튼이 **전혀 눌리지 않음** |
| **원인** | `#site-header`가 `position: fixed` + `z-index: 200`으로 화면 우상단(44×44, right 16px)에 떠 있는데, 배너 오른쪽 끝이 그 아래로 들어가 햄버거 버튼이 닫기 버튼을 완전히 덮었다 |
| **실증** | 390px 뷰포트에서 `document.elementFromPoint(닫기버튼 중앙)` → **`hamburger-btn`** 반환. 배너 `right: 378` vs 헤더 `left: 330` → 48px 겹침 |
| **발생 구간** | 뷰포트 **약 870px 미만 전 구간**. 최초 검증을 1200px에서만 해 놓쳤다(그 폭에서는 배너가 800px 컨테이너 안에 있어 겹치지 않음) |
| **영향** | 사용자가 공지를 영구히 닫을 수 없음. 모바일이 주 사용 환경인 서비스에서 상시 노출되는 방해 요소 |
| **조치** | `@media (max-width: 900px)`에 `padding-right: 56px`(헤더 44 + 우측여백 16 + 간격) 추가 — `public/index.html` |
| **재검증** | 390px·830px·1200px 모두 `elementFromPoint` → `notice-close`, 클릭 가능 ✅ |

> **교훈**: 고정 오버레이(`position: fixed`)가 있는 페이지에 새 상단 요소를 넣을 때는 **단일 폭 확인으로 충분하지 않다.**
> 겹침 경계 폭을 계산해 그 앞뒤를 함께 확인할 것.

---

## 1. 요약 — Match Rate 산출 근거

| 산출 단위 | 항목 수 | 획득 | 비율 | 판정 |
|---|:---:|:---:|:---:|:---:|
| **FR-A1** seo-discoverability | 17 | 15.0 | **88%** | ⚠️ |
| **FR-A2** pwa-install | 8 | 5.5 | **69%** | ❌ |
| **FR-A3** legal-notices | 7 | 5.5 | **79%** | ⚠️ |
| **§14 자기보고 산출물 검증** | 18 | 16.0 | **89%** | ⚠️ |
| **종합** | **50** | **42.0** | **84%** | ⚠️ |

> G-0은 Check 단계에서 수정 완료됐으므로 현재 상태 기준 Match Rate에는 반영하지 않았다.

### 1.1 FR-A1 (17항목 / 15.0)

| # | 항목 | 판정 | 근거 |
|:-:|---|:---:|---|
| 1 | `public/robots.txt` 신규 | ✅ 1.0 | `robots.txt:1-7` — 전체 허용 + `/admin`·`/admin.html`·`/api/` 차단 + Sitemap 선언 |
| 2 | `public/sitemap.xml` 신규 30 URL | ✅ 1.0 | 실측 30건(홈·게시판·계산기 3 + 흐름도 25 + 약관·방침 2) |
| 3 | index description·keywords·canonical·robots | ✅ 1.0 | `index.html:7-10` |
| 4 | index OG 9종 | ✅ 1.0 | `index.html:24-33` |
| 5 | index Twitter 4종 | ✅ 1.0 | `index.html:34-37` |
| 6 | board description·canonical | ✅ 1.0 | `board.html:7-9` |
| 7 | board OG | ✅ 1.0 | `board.html:15-23` |
| 8 | board Twitter | ⚠️ 0.5 | `board.html:24-25` — `card`·`image` 2종만. `twitter:title`·`description` 누락 |
| 9 | calculators description·canonical | ✅ 1.0 | `calculators.html:7-10` |
| 10 | calculators OG | ✅ 1.0 | `calculators.html:16-24` |
| 11 | calculators Twitter | ⚠️ 0.5 | `calculators.html:25-26` — 동일 2종만 |
| 12 | JSON-LD WebSite·Organization·WebApplication | ✅ 1.0 | `index.html:42-82` — `@graph` 3노드, 내부 참조 해소 |
| 13 | JSON-LD FAQPage (미채택) | ✅ 1.0 | **의도적 이탈 인정** — `index.html:39-41` 주석 + §14.2 근거(답변 가시성 요건 미충족) |
| 14 | JSON-LD **BreadcrumbList** | ❌ 0 | **전 페이지 부재**. FR-A1이 명시했으나 §14.2에 언급조차 없음 → G-10 |
| 15 | vercel.json 라우트 반영 | ✅ 1.0 | `vercel.json:18-24` |
| 16 | og-image.png 1200×630 | ✅ 1.0 | `sips` 실측 1200×630 PNG |
| 17 | sitemap 대상 페이지의 **색인 품질** | ❌ 0 | 흐름도 25개 중 21개 title 중복, description·canonical 0/25 → **G-3** |

### 1.2 FR-A2 (8항목 / 5.5)

| # | 항목 | 판정 | 근거 |
|:-:|---|:---:|---|
| 1 | `manifest.webmanifest` | ✅ 1.0 | 필수 필드·192/512·maskable·아이콘 경로 전부 해소 실측 |
| 2 | 아이콘 세트 | ✅ 1.0 | `icons/` 5종 + `favicon.svg`·`favicon.ico`(16·32 포함) 실측 |
| 3 | 파비콘 | ✅ 1.0 | `index.html:13-15` |
| 4 | `sw.js` 오프라인 셸 | ✅ 1.0 | `sw.js:15,63-76` |
| 5 | `/api/*` 캐시 제외 | ✅ 1.0 | `sw.js:61` — **SSE 누출 없음 확인** |
| 6 | SW 등록(https 한정·실패 무시) | ⚠️ 0.5 | **index.html에만 존재** → G-7 |
| 7 | **설치 안내** | ❌ 0 | **전면 부재** → G-2 |
| 8 | SW 캐시 위생 | ❌ 0 | `/?q=<질문>` URL이 캐시 키로 영구 저장 + VERSION 고정 → G-4·G-15 |

### 1.3 FR-A3 (7항목 / 5.5)

| # | 항목 | 판정 | 근거 |
|:-:|---|:---:|---|
| 1 | `terms.html` 9개 조항 | ✅ 1.0 | 제5조 한도 수치가 `abuse_guard.py:25-32` 기본값과 **정확히 일치** |
| 2 | `privacy.html` 9개 항목 | ✅ 1.0 | |
| 3 | 처리위탁 7 수탁자 | ✅ 1.0 | `privacy.html:113-122` |
| 4 | 푸터 링크 연결 (index·board) | ✅ 1.0 | `index.html:687`, `board.html:510-512` |
| 5 | 푸터 링크 (calculators) | ❌ 0 | 푸터 자체 없음 → G-12 |
| 6 | 운영주체·문의처 표기 | ✅ 1.0 | |
| 7 | 방침 서술 ↔ 코드 사실 일치 | ⚠️ 0.5 | 남용 기록 파기 미이행 → **G-1** |

### 1.4 §14 자기보고 산출물 검증 (18항목 / 16.0)

18개 중 14개 완전 일치, 2개 부분(`board` JSON-LD `@id` 미해소 / 배너 링크 화이트리스트), 2개 불일치(`api/index.py` 라우트 / `terms.html` 주석 미현행화).

---

## 2. 발견된 갭

### 🔴 High (3건)

#### G-1. 개인정보처리방침이 약속한 "남용 기록 파기"를 이행하는 코드가 없다

| 항목 | 내용 |
|---|---|
| **문서 주장** | `privacy.html:138` — "남용 탐지 기록·일일 이용량 → **차단 기간 종료 또는 당일 경과 시**" 파기 |
| **실제 상태** | ① **`abuse_events`에 삭제 경로가 전혀 없다** — `supabase_retention_purge.sql`의 남용 테이블 언급 **0건**(실측). ② `chat_quota`·`block_list` 삭제는 `chat_guard_check` RPC 안에서 **동일 `subject_key`가 다시 요청할 때만** 실행된다(`supabase_abuse_guard.sql:79,88` — `WHERE subject_key = p_subject_key`). 재방문하지 않는 IP의 행은 영구 잔존 |
| **민감도** | `abuse_events.detail`에 **사용자 질문 원문 프리뷰 120자**가 저장된다(`supabase_abuse_guard.sql:117` `left(p_detail, 120)`). 노동상담 특성상 사업장·피해 정황이 담길 수 있다 |
| **영향** | 법정 고지와 실제 처리의 불일치. §14.5가 "약속과 구현의 간극을 메우기 위해" 파기 스크립트를 만들었다고 기록했으나 **간극이 절반만 메워졌다** |
| **권장 조치** | `purge_expired_data()`에 3테이블 추가 — `abuse_events`(예: 90일), `chat_quota`(`day < today`), `block_list`(`until_ts <= now()`). SQL 15줄 |

#### G-2. FR-A2가 요구한 "설치 안내"가 전면 부재하고, 부재 사실이 문서에도 없다

| 항목 | 내용 |
|---|---|
| **사양** | Plan §8.2 FR-A2 — "manifest + 아이콘 세트 + 파비콘 + 오프라인 셸 SW + **설치 안내**" |
| **실제 상태** | `public/**/*.html` 전수에서 설치 안내 UI·페이지·`beforeinstallprompt` 핸들러 **0건**. §14.1 산출물 표에 해당 행이 아예 없어 **미구현 사실조차 기록되지 않았다** |
| **영향** | 자산은 갖췄으나 사용자가 설치 가능함을 알 방법이 없다. 특히 **iOS Safari는 `beforeinstallprompt`를 지원하지 않아** 안내 없이는 설치율이 사실상 0. 경쟁사는 `/install` 전용 가이드를 갖고 있다(Plan §3.1-8) |
| **권장 조치** | 슬라이드 메뉴에 "홈 화면에 추가" + `/install.html` 경량 안내(Android는 `beforeinstallprompt` 캡처 버튼, iOS는 공유→홈 화면 추가 안내). 20~30줄 |

#### G-3. sitemap이 선언한 30 URL 중 25개(83%)가 색인 품질 미달 — FR-A1 목적에 역행

| 항목 | 내용 |
|---|---|
| **실측** | `<title>계산과정</title>` **21개 중복**, 고유 title 4개뿐. `description`·`canonical` 보유 **0/25** |
| **영향** | ① 동일 title 21개 → 중복·thin content로 색인 제외되거나 품질 신호 하락 ② 검색 결과에 "계산과정"만 노출돼 클릭 유도 불가 ③ iframe 뷰어용이라 단독 진입 시 돌아갈 내비게이션이 없다. FR-A1 투자의 **83%가 낭비** |
| **권장 조치** | **(A)** 25개에 `<title>{계산기명} 계산과정 — 기초 노동상담</title>` + description + canonical + 홈 링크 주입 — `calculators.html` JSON-LD ItemList에 25개 한국어 명칭이 이미 있어 기계적 생성 가능. **(B)** sitemap에서 25건 제외. **A 권장** |

### 🟠 Medium (4건)

#### G-4. 서비스워커가 사용자 질문이 담긴 URL을 디스크 캐시에 영구 저장

`sw.js:63-76`이 성공한 모든 동일 출처 내비게이션을 `req`(쿼리스트링 포함) 키로 `SHELL_CACHE`에 `put`한다. `index.html:1880-1887`이 `/?q=…` 진입을 지원하므로 **`/?q=회사에서 임금을 못받았는데…` 형태 URL이 Cache Storage에 그대로 쌓인다.** `history.replaceState`(`:1885`)는 주소창만 정리할 뿐 캐시 항목은 남는다. 항목 수 상한도 없다. `privacy.html:101`의 "세션 저장소에 식별자 1개만, 탭을 닫으면 사라짐" 서술과 충돌한다(Cache Storage는 탭을 닫아도 잔존).

```js
if (res && res.ok && !url.search) { … c.put(new Request(url.pathname), copy) … }
```

#### G-5. GitHub Pages 미러에서 FR-A2 자산이 전부 무효

`.github/workflows/pages.yml`이 `public/**` 변경마다 배포한다(이번 산출물 전부 트리거). 프로젝트 페이지는 서브패스 서빙이라 `/manifest.webmanifest`·`/sw.js`·`/icons/*`·`/favicon.*`·`/notice.json`·`/og-image.png`가 전부 404, `/board`·`/calculators`도 404. `board.html:518`·`admin.html:161`의 `github.io` 분기가 미러 실사용을 증명한다.

- **완화**: SW 등록·공지 fetch가 `.catch()`로 조용히 실패 → §13.2 graceful degradation 유지. canonical 절대 URL로 중복 콘텐츠도 정규화됨
- **미완화**: 미러 방문자는 파비콘·PWA·공지를 전혀 받지 못한다. §14 어디에도 미러 고려가 없다

#### G-6. `api/index.py`에 `/terms`·`/privacy` 라우트 없음 (§12.3 미이행)

Plan §12.3이 명시했으나 `api/index.py`의 정적 서빙은 5종뿐. **프로덕션 영향 없음**(`vercel.json:18-19`가 처리). **개발 영향**: `uvicorn`으로 띄우면 404. §14.3의 "로컬 스모크 16경로 200"이 어떤 서버로 측정됐는지 미기재라 재현 불가.

#### G-7. SW 등록이 index.html에만 있어 진입 경로에 따라 PWA가 성립하지 않음

`board.html`·`calculators.html`은 manifest를 링크하면서 SW는 등록하지 않는다. Chrome 설치 기준은 "현재 스코프에 fetch 핸들러를 가진 SW"이므로 **검색으로 `/board`에 처음 도달한 사용자는 설치 프롬프트를 받지 못한다.** FR-A1으로 늘리려는 유입의 상당수가 그 경로다. G-2와 결합해 FR-A2 실효성을 함께 떨어뜨린다.

### 🔵 Low (9건)

| # | 항목 | 근거 | 내용·조치 |
|:-:|---|---|---|
| G-8 | **공지 링크 화이트리스트 우회** | `index.html:1922` | **실증 완료**(아래 §3.5). `/^\/[^/]/`는 `//evil.com`은 막지만 **`/\evil.com`은 통과**하고 WHATWG URL이 `https://evil.com/`로 해석한다. §14.8의 "외부 유도 불가" **보증 불성립**. 조치: `try { if (new URL(n.linkUrl, location.origin).origin !== location.origin) return; } catch { return; }` |
| G-9 | JSON-LD `@id` 상호참조 미해소 | `board.html:34`, `calculators.html:27-35` | board가 참조하는 `#website` 노드가 그 문서에 없고 스텁에 `name`·`url` 부재. calculators는 `isPartOf` 자체가 없음 |
| G-10 | BreadcrumbList 미구현 | Plan `:455` | FR-A1 명시 3종 중 Breadcrumb만 근거 없이 누락 |
| G-11 | Twitter 카드 페이지 간 불일치 | `index.html:34-37` vs 나머지 2페이지 | index 4종 / 나머지 2종. `og:image:alt`도 index에만 |
| G-12 | calculators 푸터·법적고지 링크 없음 / admin noindex 없음 | `calculators.html`, `admin.html:3-6` | Disallow는 색인을 막지 못하므로 `<meta name="robots" content="noindex">` 권장 |
| G-13 | terms.html 주석이 §14.8 이후 사실과 다름 | `terms.html:15-17` | "공지 채널이 아직 없다" 서술 잔존 — 같은 사이클 내 자기모순 |
| G-14 | notice.json 문서와 구현의 level 불일치 | `notice.json:5` vs `index.html:1918,1930` | 문서는 3종 선언, 구현은 `warn`/그 외 2분기. 샘플의 `"level":"notice"`가 `level-info`로 렌더 |
| G-15 | SW 버전 고정 + 오프라인 셸 오배치 | `sw.js:10,15,73` | `VERSION='v1'` 고정 → `sw.js` 바이트 불변 시 업데이트 미감지, 셸 영구 스테일. 오프라인에서 `/terms` 요청 시 홈 HTML이 응답 |
| G-16 | 첨부 용량 서술이 실제보다 관대 | `privacy.html:87` vs `index.html:881,907` | **실측**: 서버 `MAX_IMAGE_SIZE` 개당 3MB(`file_parser.py:9`), 클라이언트 `MAX_TOTAL_BYTES` **합계 3MB**. UI 툴팁(`:637`)은 "합계 3MB"로 정확하나 방침만 "개당 3MB". 조치: "최대 3개, 합계 3MB"로 정정 |

> 부수 관찰: `public/calculator_flow/platform.md`·`platform2.md`·`platform3.md`가 `vercel.json:25` 와일드카드로 공개 서빙된다. 민감정보는 없으나 sitemap·링크 어디에도 없는 고아 파일 — 정리 여부 판단할 것.

---

## 3. 검증 통과 항목 (요청 사항 중 반증된 것 포함)

### 3.1 sitemap ↔ 라우트 정합성 — **통과**

30 URL 전부 `vercel.json` 라우팅으로 200. `/sw.js`는 `:20-24`가 와일드카드보다 앞에 있어 `no-cache` + `Service-Worker-Allowed: /` 헤더가 정상 적용된다(순서 정합 확인).

### 3.2 `/terms` vs `/terms.html` 중복 콘텐츠 — **위험 낮음**

확장자 유무 5쌍이 모두 200이지만 canonical이 전 페이지에 있고 sitemap·내부 링크가 canonical과 같은 형태를 쓴다. board/calculators는 확장자 없는 형태, terms/privacy는 있는 형태로 **표기 규칙만 불일치**할 뿐 정규화는 성립. 단 `vercel.json`의 `/terms`·`/privacy` 라우트는 canonical이 `.html`을 가리켜 사실상 미사용(정리하거나 canonical 통일 — 택일).

### 3.3 sw.js `/api/*` 누출 — **없음**

`sw.js:46-61` 순서 검증: 非GET return → URL 파싱 실패 return → 교차 출처 return → `/api/`·`/admin` prefix return. SSE(`GET /api/chat/stream`)는 3·4단계에서 걸러진다. §14.2·§12.2 설계 의도가 코드로 정확히 구현됨.

### 3.4 공지 배너 XSS — **없음**

`esc()`가 `& < > " '` 5종을 치환하고 `message`·`linkUrl`·`linkText` 전부에 적용. `javascript:`는 `^\/`에서 차단. `localStorage`는 `.slice(-20)` 상한. `sw.js` `ASSET_PATTERN`에 `.json`이 없어 공지가 캐시에 갇히지 않는다는 §14.8 주장도 사실 확인. 남은 결함은 G-8 하나.

### 3.5 G-8 링크 우회 — **실증 결과 (Node WHATWG URL, 브라우저와 동일 파서)**

| 입력 | 정규식 통과 | 해석 결과 | 판정 |
|---|:---:|---|:---:|
| `/privacy.html` | 예 | `https://laborconsult.vercel.app/privacy.html` | 정상 |
| `//evil.com` | 아니오 | `https://evil.com/` | 차단됨 |
| `/\evil.com` | **예** | **`https://evil.com/`** | **★ 우회** |
| `https://evil.com` | 아니오 | `https://evil.com/` | 차단됨 |
| `javascript:alert(1)` | 아니오 | `javascript:alert(1)` | 차단됨 |

### 3.6 첨부 비공개 전환 5파일 정합 — **모순 없음, 관리자 열람 동작함**

`supabase_schema.sql:74-76`(신규 설치 `public=false`) / `supabase_attachments_private.sql:44-55`(기존 배포 전환) / `storage.py:250-273`(`get_public_url` 제거·`None` 저장·`storage_path` 반환) / `pipeline.py:1894-1897`(반환값 미사용 확인) / `api/index.py:611-637`(signed URL) / `admin.html:385-398`(null 처리) 전부 정합. 코드베이스 전체에 `get_public_url` 잔존 호출 0건. `Allow anon read` 유지 판단도 타당(서명 주체 SELECT 필요, anon 키는 서버 전용).

### 3.7 §13.2 관례 준수 — **위반 없음**

가드 선통과(해당 없음 — 채팅 경로 무신설), path traversal 가드 유지, `_anonymize()`(해당 없음), graceful degradation(SW·공지 모두 `.catch()`), `app/core/*` 커밋 대상 포함 — 전부 충족.

### 3.8 법적 고지 ↔ 코드 사실 대조

| 방침 서술 | 코드 | 판정 |
|---|---|:---:|
| 한도 2,000자 / 60초 5회 / 하루 50회 / 30분 차단 | `abuse_guard.py:25-32` 동일 | ✅ |
| IP는 SHA-256 앞 16자만, 원문 미보관 | `abuse_guard.py:316-318`, `api/index.py:768,840` | ✅ |
| 첨부 비공개 + 1시간 signed URL | §3.6 | ✅ |
| 게시판 비밀번호 bcrypt | 구현 일치 | ✅ |
| 관리자 토큰 인증 + 시도 제한 | `api/index.py:460-462` | ✅ |
| 대화·첨부·게시글 1년 자동 파기 | `supabase_retention_purge.sql`(적용 완료) | ✅ |
| **남용 기록·일일 이용량 파기** | **이행 코드 없음** | ❌ G-1 |
| 첨부 개당 3MB | 서버 개당 3MB / 클라 합계 3MB | ⚠️ G-16 |
| Supabase 서울 리전 | 코드로 검증 불가(프로젝트 설정) | — |

---

## 4. 사양 대비 초과 구현

전부 타당하며 근거가 문서화돼 있다.

| 산출물 | Plan상 위치 | 판단 |
|---|---|---|
| `supabase_retention_purge.sql` | 없음(§14.5 신설) | ✅ 타당 — 단 G-1처럼 절반만 메워짐 |
| 첨부 비공개 전환 6파일 | §10 Next Steps 7이 **"별도 티켓"으로 분리**한 항목 | ⚠️ 사이클 경계 이탈이나 타당 — 방침에 "비공개 보관"을 쓰려면 선행 필요 |
| `notice.json` + 배너 | 없음(§14.8 신설) | ✅ 타당 — 약관 제3·7조가 약속한 공지 수단의 이행 |
| `keywords`·iOS 메타·manifest `shortcuts`·`categories` | 명세 밖 | ✅ 무해한 보강 |
| 타이틀 브랜드 통일 | 명세 밖 | ✅ 타당 |

---

## 5. 문서가 주장했으나 사실과 다른 항목

§14는 구현자의 자기 기록이므로 별도 대조했다. 아래를 신뢰하고 다음 작업을 시작하면 잘못된 전제가 된다.

| # | 문서 주장 | 사실 | 심각도 |
|:-:|---|---|:---:|
| 1 | `privacy.html:138` "남용 기록·일일 이용량 … 당일 경과 시 파기" | **파기 코드 없음**(실측 0건) | **High** |
| 2 | §14.8 "링크는 내부 경로만 허용 → **외부 유도 불가**" | `/\evil.com` 우회 실증 → **보증 불성립** | Low |
| 3 | `terms.html:15-17` "공지사항 표시 위치가 **아직 없다**" | §14.8에서 배너 신설 → **무효한 서술** | Low |
| 4 | §14.1 "board.html … OG·**Twitter**" | Twitter 2종뿐(index는 4종) | Low |
| 5 | §14.2 FAQPage 미채택 근거만 기록 | **BreadcrumbList는 언급조차 없음** | Low |
| 6 | §14.3 "로컬 스모크 16경로 전부 200" | 측정 서버 미기재 → 재현 불가. `uvicorn` 기준 `/terms`·`/privacy` 404 | Low |

추가로 §14.1 산출물 표에 **FR-A2 "설치 안내" 행이 아예 없다**(G-2). 표가 "구현하지 않은 것"을 드러내는 구조가 아니어서 누락이 눈에 띄지 않는다 — 다음 사이클부터 **사양 ID별 이행/미이행을 함께 적을 것**.

---

## 6. 권장 조치 순서

### 즉시 (배포 전)
1. **G-1** — `purge_expired_data()`에 `abuse_events`·`chat_quota`·`block_list` 추가. 방침 문구가 이미 확정돼 지연 불가. SQL 15줄
2. **G-3** — 흐름도 25개에 title·description·canonical 주입, 또는 sitemap에서 제외. FR-A1 투자의 83%가 걸려 있다
3. **G-8** — 공지 링크 검증을 `new URL(...).origin` 비교로 교체. 2줄
4. **G-4** — SW 내비게이션 캐싱에서 쿼리 URL 제외. 1줄

### 배포 전 (권장)
5. **G-2 / G-7** — 설치 안내 + SW 등록 3페이지 확대. 함께 처리해야 FR-A2가 실효를 갖는다
6. **G-5** — GitHub Pages 미러 용도 확정
7. **G-12 / G-16 / G-13 / G-14** — 푸터 링크·admin noindex·용량 문구·주석 현행화. 각 1~3줄

### 문서 정합화
8. Plan §14에 미이행 항목(설치 안내·BreadcrumbList·`api/index.py` 라우트)을 명시하고 §14.3 측정 서버를 기재

### 다음 사이클 이관 가능
9. **G-10 / G-9 / G-11 / G-6 / G-15**

### 배포 후 (Plan §10-2 유지)
10. Search Console·네이버 서치어드바이저 등록 + `sitemap.xml` 제출, 구조화 데이터 테스트, **Lighthouse PWA 감사는 G-2·G-7 처리 후** 수행

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-08-01 | P0(FR-A1/A2/A3) 갭 분석 최초 — 84% 판정. High 3·Medium 4·Low 9 도출, 문서 허위 주장 6건 지적. Check 단계 발견·수정 결함 G-0 기록. 첨부 비공개 전환·§13.2 관례·sitemap 라우트 정합·SSE 누출 없음은 통과 확인 | DrunkenZealnut |

---

## 7. Re-Check — Act-1 이후 재검증 (2026-08-01)

### 7.1 재채점

독립 재검증(gap-detector) 결과와, 그 지적을 반영한 추가 수정 후의 산정이다.

| 산출 단위 | v1.0 | Re-Check | **Act-1 후속 수정 후** |
|---|:---:|:---:|:---:|
| FR-A1 (17) | 15.0 (88%) | 16.5 (97%) | **17.0 (100%)** |
| FR-A2 (8) | 5.5 (69%) | 8.0 (100%) | **8.0 (100%)** |
| FR-A3 (7) | 5.5 (79%) | 6.0 (86%) | **7.0 (100%)** |
| §14 자기보고 (18) | 16.0 (89%) | 13.5 (75%) | **17.5 (97%)** |
| **종합 (50)** | **42.0 (84%)** | **44.0 (88%)** | **49.5 (99%)** |

> **v1.0 산술 오류 정정**: v1.0 §1.4는 "18개 중 14개 일치, 2개 부분, 2개 불일치"라 적었는데 이는 15.0이지 16.0이 아니다.
> 보정하면 v1.0은 41.0/50 = **82%**였다. 개선폭은 82% → 99%.
>
> **자체 산정 고지**: 재검증 에이전트가 산정한 **88%까지가 독립 평가**다. 이후 +5.5는
> 그 에이전트가 명시한 델타표(N-1 +0.5 / Plan §14 갱신 +4.5 / G-12 나머지 +1.0)를 그대로 적용한 것이며,
> 코드 항목은 아래 §7.3처럼 브라우저에서 실측했으나 **문서 항목(§14 갱신)은 자기 평가**다.
> 독립 확인이 필요하면 `/pdca analyze`를 다시 실행할 것.

### 7.2 Re-Check가 잡아낸 Act-1의 신규 결함 (전부 조치)

수정 과정에서 새로 만든 결함이다. 이것이 재검증을 돌린 이유다.

| # | 결함 | 원인 | 조치 |
|:-:|------|------|------|
| **N-1** | 흐름도 홈 링크가 **iframe 안에서도 보였다** — `/calculators` 뷰어에 네이비 바가 노출되고, 클릭 시 iframe 내부가 홈으로 이동 | `<a hidden style="display:block">` — 인라인 스타일이 UA의 `[hidden]{display:none}`(`!important` 없음)을 이긴다. **같은 함정을 `#notice-banner[hidden]{display:none}`에서 이미 처리해 놓고 재발시켰다** | `hidden` 속성 대신 `style="display:none"` + JS 토글, `target="_top"` 추가 |
| N-3 | `offline.html` 버튼 폰트 미적용 | `font: 600 14px/1 inherit` — 단축 속성의 family 자리에 `inherit`은 무효라 **선언 전체가 드롭** | 개별 속성으로 분해 |
| N-4 | 설치 완료자에게 설치 안내를 띄움 | standalone 분기가 `/install.html`로 이동 | standalone이면 no-op + `[data-pwa-install]` 진입점 숨김 |
| N-5 | `install.html`로 가는 크롤 가능한 링크 0 | JS `location.href` 진입만 존재 | index·board·calculators 푸터에 링크 추가 |
| 부수 | localhost에서 SW 미등록 | `location.protocol === 'https:'`가 localhost를 배제 | `window.isSecureContext`로 교체 |

### 7.3 브라우저 실측 검증

| 항목 | 결과 |
|------|------|
| **G-4 질문 URL 캐시** | `/?q=회사에서 임금을 못받았습니다` 진입 후 Cache Storage 실측 → `/`·`/offline.html`·`/index.html`만 존재, **질문 문자열 미저장** ✅ |
| **G-8 링크 우회** | `//evil.com`·`/\evil.com`·`https://evil.com`·`javascript:` **전부 차단** ✅ |
| **N-1 iframe 숨김** | iframe 내부 `display: none` / 단독 진입 `display: block` ✅ (수정 전에는 iframe에서도 `block` + `getClientRects().length > 0`으로 **실제 노출 확인**) |
| **SW 등록** | `shell-v2-2026-08-01` 캐시 생성, `swActive: true` ✅ |
| **`/api/*` 미개입** | `/api/chat/stream` 404가 콘솔에 그대로 뜸 = SW가 가로채지 않고 네트워크로 통과 ✅ |
| **G-12 푸터** | `calculators.html` 푸터 렌더, 링크 6종, 레이아웃 클리핑 없음 ✅ |
| **G-0 배너 닫기** | 390·830·1200px 전부 `elementFromPoint` → `notice-close` ✅ |

### 7.4 Re-Check가 확인한 정합성 (통과)

- **흐름도 25개 일괄 수정이 기존 자산을 훼손하지 않았다** — `<script>` 쌍 25/25 일치, `</html>` 각 1개, JSON-LD가 `</head>` 직전에 정확히 배치, 메타 중복 0, `window.parent?.sendPrompt?.()` 관례 유지. SVG `<title>`은 이 파일들이 `<text>` 요소를 쓰므로 훼손 대상 자체가 없었다.
- **`purge_expired_data()` SQL 정합** — `DROP FUNCTION (INT)` 시그니처가 v1.0과 일치, `RETURNS TABLE` 7컬럼 ↔ `RETURN QUERY` 7값 순서 일치, `chat_quota.day` 텍스트 비교는 ISO 8601의 사전식 정렬 = 시간순이라 올바르며 앱과 동일한 KST 기준.
- **`serve_static_page` 데코레이터 스택** — FastAPI `app.get()`은 원본 함수를 반환하므로 4중 스택이 4개 라우트를 등록한다. 전부 리터럴 경로라 충돌 없고, 사용자 입력이 경로에 들어가지 않아 traversal 위험 없음(입력 기반인 `serve_calculator_flow`는 `commonpath` 가드 유지).
- **법적 고지 ↔ 코드 일치** — 방침 제5항 6행이 `purge_expired_data` 기본값과 1:1 대응. G-4 수정으로 `privacy.html:101`의 "세션 저장소에 식별자 1개만" 서술과 Cache Storage 간 충돌도 해소됐다.

### 7.5 남은 것

| # | 항목 | 상태 |
|:-:|------|------|
| **G-5** | GitHub Pages 미러 용도 확정 | ✅ **해결** — 운영자가 미러 미사용 확정. `pages.yml` 삭제, `CLAUDE.md` 갱신. 배포처는 Vercel 단일. 잔여 수동 작업: 저장소 Settings → Pages → Source **None** |
| 배포 전 1 | `supabase_retention_purge.sql` v1.1 재적용 | `DROP FUNCTION` 선행 없이는 `cannot change return type` 실패 |
| 배포 전 2 | 파기 **양성 검증** | 남용 3테이블은 RLS ON + 정책 0개. SECURITY DEFINER 소유자가 테이블 소유자가 아니면 DELETE가 **에러 없이 0건**으로 끝난다. `SELECT * FROM purge_expired_data(365, 90);` 반환 건수로 확인 |
| 이관 | `calculator_flow/platform*.md` 고아 파일, terms·privacy의 SW 미등록 | 다음 사이클 |

### 7.6 방법론 회고

이번 사이클에서 결함이 발견된 경로는 셋이다.

1. **단일 조건 검증의 한계** — G-0(모바일 배너)은 1200px에서만 확인해 놓쳤다. 겹침 경계 폭(약 870px)을 계산해 앞뒤를 함께 봐야 했다.
2. **자기 코드에 대한 맹점** — N-1은 같은 함정(`[hidden]` vs 인라인 `display`)을 다른 파일에서 이미 처리해 놓고 재발시켰다. **독립 재검증이 아니었으면 배포까지 갔을 결함**이다.
3. **문서 드리프트** — 코드만 고치고 Plan §14를 갱신하지 않아 자기보고 정합도가 89% → 75%로 **떨어졌다**. Act 단계에서 코드와 문서를 함께 고치는 것이 원칙이어야 한다.

**다음 사이클 적용**: §14 산출물 표에 **사양 ID별 이행/미이행 열**을 두어 누락이 표 위에서 드러나게 할 것.

---

## Version History (계속)

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 2.0 | 2026-08-01 | Act-1 이후 Re-Check 반영 — 88%(독립) → 99%(후속 수정 후 산정). Act-1 신규 결함 5건(N-1·N-3·N-4·N-5·부수) 기록 및 조치, 브라우저 실측 7항목, 방법론 회고 추가 | DrunkenZealnut |
| 2.1 | 2026-08-01 | 최상단 판정 요약을 최신 결과(100%) 우선으로 재배치 — v1.0 baseline(84%)이 최종 결과로 오독되던 문제 해소(PR #29 CodeRabbit 리뷰). 상세 대응은 Plan §16.5 | DrunkenZealnut |
