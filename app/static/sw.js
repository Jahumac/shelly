/**
 * Shelly — Service Worker
 *
 * Strategy:
 *  - App shell (HTML, CSS, JS, icons): Cache-first with background revalidation
 *  - Page navigations: Network-first with offline fallback
 *  - API calls: Network-first, cache response for offline reads
 *  - Images/fonts: Cache-first, long-lived
 */

const CACHE_NAME = 'shelly-v1.5.0';

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
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_SHELL);
    })
  );
  self.skipWaiting();
});

/* ── Activate: clean up old caches ────────────────────────────────────── */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
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

  /* Static assets: cache-first */
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  /* Page navigations: network-first with offline fallback */
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstPage(request));
    return;
  }

  /* API-style JSON calls: network-first, cache response */
  if (url.pathname.includes('/api/') || request.headers.get('Accept')?.includes('application/json')) {
    event.respondWith(networkFirstAPI(request));
    return;
  }

  /* Everything else: network-first */
  event.respondWith(networkFirstPage(request));
});

/* ── Strategies ───────────────────────────────────────────────────────── */

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    /* Revalidate in background */
    fetch(request)
      .then((response) => {
        if (response.ok) {
          caches.open(CACHE_NAME).then((cache) => cache.put(request, response));
        }
      })
      .catch(() => {});
    return cached;
  }
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirstPage(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;

    /* Return an offline fallback page */
    return new Response(offlineHTML(), {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }
}

async function networkFirstAPI(request) {
  const url = new URL(request.url);
  try {
    const response = await fetch(request);
    if (response.ok && url.pathname !== '/api/ping') {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    if (url.pathname === '/api/ping') {
      return new Response(JSON.stringify({ error: 'Offline' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'Offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
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
    .offline-card {
      max-width: 400px;
    }
    .offline-icon {
      font-size: 3rem;
      margin-bottom: 1rem;
      opacity: 0.6;
    }
    h1 {
      font-size: 1.5rem;
      margin-bottom: 0.5rem;
      color: #38bdf8;
    }
    p {
      color: #94a3b8;
      line-height: 1.6;
      margin-bottom: 1.5rem;
    }
    button {
      background: #38bdf8;
      color: #0f172a;
      border: none;
      padding: 0.75rem 2rem;
      border-radius: 999px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
    }
    button:hover { background: #7dd3fc; }
  </style>
</head>
<body>
  <div class="offline-card">
    <div class="offline-icon">🐢</div>
    <h1>Shelly's tucked in</h1>
    <p>Can't reach the server right now — even turtles need a break. Check your connection and try again. Pages you've visited before should still be cached.</p>
    <button onclick="location.reload()">Try Again</button>
  </div>
</body>
</html>`;
}
