/**
 * Shelly — Service Worker
 *
 * Two separate caches:
 *  STATIC_CACHE — app shell (CSS, JS, icons). Versioned — bumped when
 *                 static files change. Old static caches are deleted on activate.
 *  PAGE_CACHE   — HTML pages and API responses. Never wiped, so cached
 *                 pages survive app updates and are always available offline.
 *
 * Strategies:
 *  Static assets  → cache-first (serve instantly, revalidate in background)
 *  Page navigations → network-first, fall back to PAGE_CACHE, then offline HTML
 *  API calls      → network-first, fall back to PAGE_CACHE
 */

const STATIC_CACHE = 'shelly-static-v1.7.0';
const PAGE_CACHE   = 'shelly-pages';

/* App shell files to pre-cache on install */
const APP_SHELL = [
  '/static/css/styles.css',
  '/static/js/charts.js',
  '/static/manifest.json',
  '/static/icons/icon-180.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

/* ── Install: pre-cache the app shell ─────────────────────────────────── */
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

/* ── Activate: clean up old STATIC caches only, never touch PAGE_CACHE ── */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith('shelly-static-') && key !== STATIC_CACHE)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

/* ── Fetch: route requests through appropriate strategy ───────────────── */
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  /* Only handle same-origin GET requests */
  if (request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  /* Static assets: cache-first, revalidate in background */
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  /* API ping: network-only, return offline JSON if unreachable */
  if (url.pathname === '/api/ping') {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(JSON.stringify({ error: 'Offline' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    );
    return;
  }

  /* API calls: network-first, cache for offline reads */
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, PAGE_CACHE));
    return;
  }

  /* Page navigations and everything else: network-first with offline fallback */
  event.respondWith(networkFirstPage(request));
});

/* ── Strategies ───────────────────────────────────────────────────────── */

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    /* Revalidate in background so next load gets fresh file */
    fetch(request)
      .then((response) => {
        if (response.ok) {
          caches.open(STATIC_CACHE).then((cache) => cache.put(request, response));
        }
      })
      .catch(() => {});
    return cached;
  }
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request, { ignoreVary: true });
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'Offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function networkFirstPage(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(PAGE_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cache = await caches.open(PAGE_CACHE);
    const cached = await cache.match(request, { ignoreVary: true });
    if (cached) return cached;

    return new Response(offlineHTML(), {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }
}

/* ── Offline fallback HTML ────────────────────────────────────────────── */
function offlineHTML() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f172a">
  <title>Offline · Shelly</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: Inter, system-ui, -apple-system, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 2rem;
    }
    .offline-card { max-width: 400px; }
    .offline-icon { font-size: 3rem; margin-bottom: 1rem; opacity: 0.6; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #38bdf8; }
    p { color: #94a3b8; line-height: 1.6; margin-bottom: 1.5rem; }
    button {
      background: #38bdf8; color: #0f172a; border: none;
      padding: 0.75rem 2rem; border-radius: 999px;
      font-size: 0.95rem; font-weight: 600; cursor: pointer;
    }
    button:hover { background: #7dd3fc; }
  </style>
</head>
<body>
  <div class="offline-card">
    <div class="offline-icon">🐢</div>
    <h1>Shelly's tucked in</h1>
    <p>You're offline and this page hasn't been cached yet. Open the app while connected first, then it'll work offline.</p>
    <button onclick="location.reload()">Try Again</button>
  </div>
</body>
</html>`;
}
