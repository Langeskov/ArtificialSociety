/* v0.4.6 runtime patch
 *
 * The existing dashboard asks for the complete brief Agent snapshot every
 * 50 simulation ticks. That is useful as an update cadence, but at the default
 * UI speed it becomes an HTTP request about once per second and can amplify
 * browser/server load. Keep the existing app contract, but serve the repeated
 * requests from a short in-memory cache and refresh the cache in the background.
 */
(function () {
  'use strict';

  const originalFetch = window.fetch.bind(window);
  const CACHE_MS = 5000;
  const TARGET = '/api/society/';
  let cached = null;
  let cachedAt = 0;
  let lastUrl = null;
  let inFlight = null;

  function requestUrl(input) {
    if (typeof input === 'string') return input;
    if (input && typeof input.url === 'string') return input.url;
    return '';
  }

  function isAgentSnapshot(url) {
    return url.includes(TARGET) && url.includes('/agents?brief=true&limit=20000');
  }

  function responseFromData(data) {
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  async function fetchFresh(input, init) {
    if (inFlight) return inFlight;
    lastUrl = requestUrl(input);
    inFlight = originalFetch(input, init)
      .then(async (response) => {
        if (!response.ok) return response;
        const data = await response.json();
        cached = data;
        cachedAt = Date.now();
        return responseFromData(data);
      })
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  }

  window.fetch = async function (input, init) {
    const url = requestUrl(input);
    if (!isAgentSnapshot(url) || (init && init.method && init.method !== 'GET')) {
      return originalFetch(input, init);
    }

    if (cached && Date.now() - cachedAt < CACHE_MS) {
      return responseFromData(cached);
    }

    return fetchFresh(input, init);
  };

  // Background refresh keeps the 3D view reasonably fresh without allowing
  // the application to create a full-population request loop.
  setInterval(() => {
    if (document.visibilityState !== 'visible' || !lastUrl) return;
    if (Date.now() - cachedAt < CACHE_MS) return;
    fetchFresh(lastUrl).catch(() => {});
  }, CACHE_MS);
})();
