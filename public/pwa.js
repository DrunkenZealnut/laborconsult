/* PWA 공통 스크립트 — index / board / calculators 에서 공유
 *
 * 하는 일 두 가지.
 *  1) 서비스워커 등록. 페이지마다 등록해야 하는 이유: Chrome의 설치 조건은
 *     "현재 스코프를 제어하는 fetch 핸들러 SW"라서, 검색으로 /board 에 처음
 *     도달한 사용자는 index를 거치지 않아 설치 프롬프트를 받지 못한다.
 *  2) beforeinstallprompt 를 붙잡아 두었다가 사용자가 원할 때 띄운다.
 *     iOS Safari 는 이 이벤트를 지원하지 않으므로 /install.html 안내로 보낸다.
 *
 * 어떤 실패도 페이지 동작을 막지 않는다.
 */
(function () {
  'use strict';

  // isSecureContext 로 판단한다. `location.protocol === 'https:'` 로 하면
  // http://localhost 가 빠져 로컬에서 PWA 동작을 확인할 수 없다(브라우저는
  // localhost 를 보안 컨텍스트로 취급해 서비스워커를 허용한다).
  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {});
    });
  }

  var deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;
    document.documentElement.setAttribute('data-installable', 'true');
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    document.documentElement.removeAttribute('data-installable');
    try { localStorage.setItem('pwaInstalled', '1'); } catch (_) {}
  });

  /** 이미 홈 화면/앱 창에서 실행 중인가 */
  window.isPwaStandalone = function () {
    return (
      (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
      window.navigator.standalone === true
    );
  };

  /**
   * 설치 실행. 네이티브 프롬프트를 쓸 수 있으면 띄우고,
   * 아니면(주로 iOS Safari·Firefox) 수동 설치 안내 페이지로 보낸다.
   */
  window.promptInstall = function () {
    // 이미 앱으로 실행 중이면 설치를 권할 이유가 없다(아래에서 진입점도 감춘다).
    if (window.isPwaStandalone()) return;
    if (deferredPrompt) {
      var p = deferredPrompt;
      deferredPrompt = null;
      p.prompt();
      if (p.userChoice && p.userChoice.catch) p.userChoice.catch(function () {});
      return;
    }
    location.href = '/install.html';
  };

  // 이미 설치·실행 중이면 설치 진입점을 감춘다.
  window.addEventListener('DOMContentLoaded', function () {
    if (!window.isPwaStandalone()) return;
    var nodes = document.querySelectorAll('[data-pwa-install]');
    for (var i = 0; i < nodes.length; i++) nodes[i].style.display = 'none';
  });
})();
