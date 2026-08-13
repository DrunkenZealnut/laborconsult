/* 기초 노동상담 — 오프라인 셸 서비스워커
 *
 * 설계 원칙 (docs/01-plan/features/competitor-analysis-ai4labor.plan.md §12.2)
 *  - `/api/*` 는 절대 가로채지 않는다. 상담 응답·SSE 스트림은 항상 네트워크 직결.
 *  - HTML(내비게이션)은 network-first — 배포 즉시 최신 화면이 보이고, 오프라인일 때만 캐시.
 *  - 정적 자산(아이콘·매니페스트)은 cache-first + 백그라운드 갱신.
 *  - 어떤 실패도 페이지를 막지 않는다(모든 경로에 네트워크 폴백).
 */

// 배포마다 올릴 것. 이 값이 그대로면 sw.js 바이트가 동일해 브라우저가 업데이트를
// 감지하지 못하고 셸 캐시가 영구히 낡은 상태로 남는다.
const VERSION = 'v6-2026-08-13';
const SHELL_CACHE = `shell-${VERSION}`;
const ASSET_CACHE = `asset-${VERSION}`;

// 오프라인에서도 최소한 열려야 하는 화면.
// 디자인 토큰을 함께 담는 이유: 오프라인 화면이 외부 스타일시트에 의존하므로
// 설치 시점에 확보하지 않으면 캐시가 차기 전까지 무스타일로 렌더된다.
const SHELL_URLS = ['/', '/board', '/calculators', '/offline.html', '/tokens.css'];

// css·js 포함 — 정적 스타일·스크립트도 cache-first 대상이다.
// 배포마다 VERSION 을 올려야 activate 가 낡은 캐시를 비운다.
const ASSET_PATTERN = /\.(?:css|js|png|svg|ico|webmanifest)$/i;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // 개별 실패가 설치 전체를 막지 않도록 하나씩 담는다
      .then((cache) => Promise.all(SHELL_URLS.map((url) => cache.add(url).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== SHELL_CACHE && k !== ASSET_CACHE).map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }

  // 동일 출처만 처리 — 폰트/CDN은 브라우저 기본 캐시에 맡긴다
  if (url.origin !== self.location.origin) return;

  // 상담 API·관리자 화면은 절대 캐시하지 않는다
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin')) return;

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          // 캐시 키에서 쿼리스트링을 떼어 낸다. `/?q=<질문>` 진입점(index.html의 ?q 처리)
          // 때문에 사용자의 상담 질문이 그대로 Cache Storage에 영구 저장되기 때문이다.
          // history.replaceState 는 주소창만 정리할 뿐 캐시 항목은 지우지 못한다.
          if (res && res.ok) {
            const copy = res.clone();
            caches
              .open(SHELL_CACHE)
              .then((c) => c.put(new Request(url.pathname), copy))
              .catch(() => {});
          }
          return res;
        })
        // 오프라인 폴백도 쿼리를 뗀 경로로 조회한다. 요청 경로에 해당하는 셸이 없으면
        // 홈이 아니라 전용 오프라인 화면을 보여 준다(/terms 요청에 홈 HTML이 응답하던 문제).
        .catch(() =>
          caches
            .match(new Request(url.pathname))
            .then((hit) => hit || caches.match('/offline.html'))
        )
    );
    return;
  }

  if (ASSET_PATTERN.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((hit) => {
        const network = fetch(req)
          .then((res) => {
            if (res && res.ok) {
              const copy = res.clone();
              caches.open(ASSET_CACHE).then((c) => c.put(req, copy)).catch(() => {});
            }
            return res;
          })
          .catch(() => hit);
        return hit || network;
      })
    );
  }
});
