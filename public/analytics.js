// Vercel Web Analytics initialization
// Uses the vanilla JavaScript inject function for static HTML pages
(function() {
  // Dynamically import and inject Vercel Analytics
  import('https://cdn.jsdelivr.net/npm/@vercel/analytics@1/dist/index.mjs')
    .then(({ inject }) => {
      inject();
    })
    .catch(err => {
      // Silently fail if analytics cannot be loaded
      console.debug('Analytics initialization skipped:', err.message);
    });
})();
