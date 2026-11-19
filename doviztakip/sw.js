const CACHE_NAME = 'doviz-altin-static-v1';
const STATIC_ASSETS = [
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png'
];

self.addEventListener('install', event => {
    event.waitUntil((async () => {
        const cache = await caches.open(CACHE_NAME);
        await cache.addAll(STATIC_ASSETS);
        await self.skipWaiting();
    })());
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys
            .filter(key => key.startsWith('doviz-altin-') && key !== CACHE_NAME)
            .map(key => caches.delete(key)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET') {
        return;
    }

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }

    if (request.mode === 'navigate') {
        event.respondWith((async () => {
            try {
                const response = await fetch(request);
                if (response.ok && url.pathname === '/') {
                    const cache = await caches.open(CACHE_NAME);
                    await cache.put(new URL('/', self.location).href, response.clone());
                }
                return response;
            } catch (error) {
                const cachedPage = await caches.match(new URL('/', self.location).href);
                if (cachedPage) {
                    return cachedPage;
                }
                throw error;
            }
        })());
        return;
    }

    if (
        url.pathname === '/altin-fiyatlari' ||
        url.pathname === '/api/doviz-kurlari' ||
        url.pathname === '/api/live-kurlar' ||
        url.pathname === '/api/trend' ||
        url.pathname === '/api/bist100' ||
        url.pathname === '/api/gecmis-kur' ||
        url.pathname === '/manifest.json' ||
        url.pathname === '/sw.js'
    ) {
        event.respondWith(fetch(request, { cache: 'no-store' }));
        return;
    }

    if (STATIC_ASSETS.includes(url.pathname)) {
        event.respondWith((async () => {
            const cached = await caches.match(request);
            return cached || fetch(request);
        })());
    }
});
