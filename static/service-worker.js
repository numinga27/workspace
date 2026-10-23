const CACHE_VERSION = 'v5';
const CACHE_NAME = `workspace-${CACHE_VERSION}`;

// ← Кэшируем ТОЛЬКО статику, НЕ HTML-страницы
const PRECACHE_URLS = [
  '/static/css/style.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable-512.png',
  '/static/manifest.json',
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

  // Пропускаем не-GET, чужие домены и API
  if (request.method !== 'GET') return;
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  // ============================================================
  //  HTML-страницы — network-first (всегда свежие данные)
  // ============================================================
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => {
          // Не кэшируем HTML — всегда свежие данные
          return response;
        })
        .catch(() => {
          // Если сети нет — показываем кэш (если есть)
          return caches.match(request);
        })
    );
    return;
  }

  // ============================================================
  //  Статика — cache-first
  // ============================================================
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          // Кэшируем только успешные ответы
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // ============================================================
  //  Всё остальное — network-only
  // ============================================================
  event.respondWith(fetch(request));
});


// ============================================================
//  PUSH-УВЕДОМЛЕНИЯ
// ============================================================
self.addEventListener('push', event => {
  if (!event.data) return;

  let data = {};
  try {
    data = event.data.json();
  } catch (e) {
    data = { title: 'Workspace', body: event.data.text() };
  }

  const title = data.title || 'Workspace';
  const options = {
    body: data.body || '',
    icon: data.icon || '/static/icons/icon-192.png',
    badge: data.badge || '/static/icons/icon-192.png',
    tag: data.tag || 'default',
    data: data.data || { url: data.url || '/' },
    vibrate: [200, 100, 200],
    requireInteraction: false,
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});


// ============================================================
//  КЛИК ПО УВЕДОМЛЕНИЮ
// ============================================================
self.addEventListener('notificationclick', event => {
  event.notification.close();

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      // Если PWA уже открыт — фокусируемся на нём
      for (const client of clientList) {
        if (client.url.includes(location.origin) && 'focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      // Иначе — открываем новое окно
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});