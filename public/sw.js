const CACHE_VERSION = "pwa-v6-yczz-icon-20260403";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const DATA_CACHE = `${CACHE_VERSION}-data`;
const SHELL_URLS = [
  "./",
  "./?source=pwa",
  "./index.html",
  "./manifest.webmanifest?v=yczz-v20260403",
  "./icons/yczz-v20260403-favicon-64.png",
  "./icons/yczz-v20260403-192.png",
  "./icons/yczz-v20260403-512.png",
  "./icons/yczz-v20260403-maskable-512.png",
  "./icons/yczz-v20260403-apple-touch-180.png"
];
const DATA_URLS = [
  "./data/dashboard.json",
  "./data/origin-search-index.json",
  "./data/market-search-index.json",
  "./data/hotspot-search-index.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    Promise.all([
      caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)),
      caches.open(DATA_CACHE).then((cache) => cache.addAll(DATA_URLS))
    ])
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => ![SHELL_CACHE, DATA_CACHE].includes(key))
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    throw error;
  }
}

async function navigationResponse(request) {
  try {
    return await networkFirst(request, SHELL_CACHE);
  } catch (error) {
    const cache = await caches.open(SHELL_CACHE);
    return cache.match("./index.html");
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cached) {
    return cached;
  }

  const networkResponse = await networkPromise;
  if (networkResponse) {
    return networkResponse;
  }

  throw new Error(`Unable to resolve request: ${request.url}`);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/downloads/") || url.pathname.endsWith(".apk")) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(navigationResponse(request));
    return;
  }

  if (
    url.pathname.endsWith("/data/dashboard.json") ||
    url.pathname.endsWith("/data/origin-search-index.json") ||
    url.pathname.endsWith("/data/market-search-index.json") ||
    url.pathname.endsWith("/data/hotspot-search-index.json")
  ) {
    event.respondWith(networkFirst(request, DATA_CACHE));
    return;
  }

  event.respondWith(staleWhileRevalidate(request, SHELL_CACHE));
});
