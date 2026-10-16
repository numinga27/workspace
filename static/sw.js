const CACHE_VERSION = 'v4';
const CACHE_NAME = `workspace-${CACHE_VERSION}`;

const PRECACHE_URLS = [
  '/',
  '/login',
  '/dashboard',
];

// ============================================================
//  INSTALL
// ============================================================
self.addEventListener('install', event => {
  console.log('[SW] Install');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
      .catch(err => console.warn('[SW] Precache failed:', err))
  );
});

// ============================================================
//  ACTIVATE
// ============================================================
self.addEventListener('activate', event => {
  console.log('[SW] Activate');
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(key => key.startsWith('workspace-') && key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// ============================================================
//  FETCH
// ============================================================
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  // Статика — cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
          }
          return response;
        });
      })
    );
    return;
  }

  // HTML — network-first, fallback в кэш
  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.status === 200) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => {
        return caches.match(request).then(cached => {
          if (cached) return cached;
          return caches.match('/login');
        });
      })
  );
});


// ============================================================
//  PUSH-УВЕДОМЛЕНИЯ
// ============================================================
self.addEventListener('push', event => {
  console.log('[SW] Push received');

  let data = {
    title: 'Workspace',
    body: 'Новое уведомление',
    url: '/',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
  };

  if (event.data) {
    try {
      const parsed = event.data.json();
      data = { ...data, ...parsed };
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: data.icon,
    badge: data.badge,
    tag: data.tag || undefined,
    data: {
      url: data.url || '/',
      ts: data.data?.ts || Date.now(),
    },
    vibrate: [200, 100, 200],
    requireInteraction: false,
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes(url) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
