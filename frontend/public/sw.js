/* Runs on browser Push events, including when no MathPilot window is open. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

self.addEventListener('push', event => {
  event.waitUntil((async () => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch { /* display safe fallback */ }
    const tag = data.tag || 'mathpilot-reminder';
    // Persistent per-delivery dedup; the same tag also replaces a visible notification.
    const cache = await caches.open('mathpilot-push-receipts-v1');
    const key = new Request(new URL('/__push_seen/' + encodeURIComponent(tag), self.location.origin));
    if (!await cache.match(key)) {
      await self.registration.showNotification(data.title || 'MathPilot 学习提醒', {
        body: data.body || '你有一条新的学习提醒', tag, renotify: false,
        data: { url: '/' },
      });
      await cache.put(key, new Response('displayed'));
      const keys = await cache.keys();
      for (const old of keys.slice(0, Math.max(0, keys.length - 500))) await cache.delete(old);
    }
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    if (data.receipt_url && data.receipt_token) {
      // Endpoint is supplied inside encrypted server push, not read from page storage.
      const url = new URL(data.receipt_url);
      if (url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname))) {
        for (let i = 0; i < 3; i++) {
          try {
            const response = await fetch(url, { method: 'POST', headers: {'Content-Type':'application/json'},
              body: JSON.stringify({token:data.receipt_token, open_windows:windows.length}) });
            if (response.ok) break;
          } catch { /* OS may terminate worker; provider acceptance is not display proof. */ }
          await new Promise(resolve => setTimeout(resolve, 1000 * (i+1)));
        }
      }
    }
  })());
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({type:'window', includeUncontrolled:true});
    if (windows.length) return windows[0].focus();
    return self.clients.openWindow('/');
  })());
});
