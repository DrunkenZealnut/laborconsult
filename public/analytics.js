// Basic Vercel Web Analytics and free Speed Insights for static HTML.
// No form values, consultation text, or user identifiers are collected here.
(function () {
  if (window.__laborTelemetryInitialized) return;
  if (/^\/admin(?:\.html|\/|$)/i.test(location.pathname)) return;
  if (location.protocol !== 'https:') return;
  window.__laborTelemetryInitialized = true;

  function cleanUrl(value) {
    var url = new URL(value, location.origin);
    return url.origin + url.pathname;
  }
  function beforeSend(event) {
    try {
      // Native Analytics adds the external referrer after beforeSend.
      // Suppress a pageview rather than transmit referrer query/hash values.
      if (event.type === 'pageview' && document.referrer) {
        var referrerUrl = new URL(document.referrer);
        if (referrerUrl.origin !== location.origin &&
            (referrerUrl.search || referrerUrl.hash)) return null;
      }
      var cleaned = Object.assign({}, event);
      if (typeof cleaned.url === 'string') cleaned.url = cleanUrl(cleaned.url);
      if (typeof cleaned.referrer === 'string' && cleaned.referrer) {
        cleaned.referrer = cleanUrl(cleaned.referrer);
      }
      return cleaned;
    } catch (_) {
      return null;
    }
  }

  window.va = window.va || function () {
    (window.vaq = window.vaq || []).push(arguments);
  };
  window.si = window.si || function () {
    (window.siq = window.siq || []).push(arguments);
  };
  window.va('beforeSend', beforeSend);
  window.si('beforeSend', beforeSend);

  function loadScript(src) {
    if (document.head.querySelector('script[src="' + src + '"]')) return;
    var script = document.createElement('script');
    script.src = src;
    script.defer = true;
    document.head.appendChild(script);
  }
  loadScript('/_vercel/insights/script.js');
  loadScript('/_vercel/speed-insights/script.js');
})();
