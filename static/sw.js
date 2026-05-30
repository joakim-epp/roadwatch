// Roadwatch service worker — offline-first PWA shell + map tile cache.
// Bump CACHE_VER to roll the shell cache when index.html or assets change.
const CACHE_VER = 'rw-v1';
const SHELL_CACHE = `${CACHE_VER}-shell`;
const TILE_CACHE = `${CACHE_VER}-tiles`;
const RUNTIME_CACHE = `${CACHE_VER}-runtime`;

const SHELL_URLS = [
  '/',
  '/static/index.html',
  '/static/manifest.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css',
  'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css',
  'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js',
  'https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js',
];

// Cap the tile cache so it doesn't grow unbounded.
const TILE_CACHE_MAX = 400;

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // Use addAll with allSettled-style fallback — if a CDN entry fails, don't abort install.
    await Promise.all(SHELL_URLS.map(u => cache.add(u).catch(() => {})));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => !k.startsWith(CACHE_VER)).map(k => caches.delete(k)));
    self.clients.claim();
  })());
});

function isTileRequest(url) {
  return /tile\.openstreetmap\.org/.test(url);
}

function isApiRequest(url) {
  return url.includes('/api/');
}

function isUploadRequest(url) {
  return url.includes('/uploads/');
}

async function trimCache(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length > max) {
    for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
  }
}

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = req.url;

  if (isApiRequest(url)) {
    // Network-first for API, fall back to cache for GETs only.
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (res.ok) {
          const cache = await caches.open(RUNTIME_CACHE);
          cache.put(req, res.clone());
        }
        return res;
      } catch {
        const cached = await caches.match(req);
        if (cached) return cached;
        return new Response(JSON.stringify({ detail: 'Offline' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    })());
    return;
  }

  if (isTileRequest(url)) {
    // Cache-first for map tiles.
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const res = await fetch(req);
        if (res.ok) {
          const cache = await caches.open(TILE_CACHE);
          cache.put(req, res.clone());
          trimCache(TILE_CACHE, TILE_CACHE_MAX);
        }
        return res;
      } catch {
        return new Response('', { status: 504 });
      }
    })());
    return;
  }

  if (isUploadRequest(url)) {
    // Cache-first for uploaded photos.
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const res = await fetch(req);
        if (res.ok) {
          const cache = await caches.open(RUNTIME_CACHE);
          cache.put(req, res.clone());
        }
        return res;
      } catch {
        return cached || new Response('', { status: 504 });
      }
    })());
    return;
  }

  // App shell: cache-first, fall back to network.
  event.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    try {
      const res = await fetch(req);
      if (res.ok && req.url.startsWith(self.location.origin)) {
        const cache = await caches.open(SHELL_CACHE);
        cache.put(req, res.clone());
      }
      return res;
    } catch {
      // Final fallback to index.html for SPA-like navigations.
      if (req.mode === 'navigate') return caches.match('/');
      return new Response('', { status: 504 });
    }
  })());
});
