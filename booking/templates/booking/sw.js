/* Re:Hof Service Worker – PWA-Offline-Unterstützung + Web-Push.
   Strategie:
   - Navigationen (HTML): network-first → bei Offline aus dem Cache, sonst die
     Offline-Seite. So sieht man online immer frische, eingeloggte Inhalte und
     offline die zuletzt besuchten Seiten (z.B. den Hofladen-Katalog).
   - BUCHEN/WUNSCH offline: KEINE veralteten Verfügbarkeiten ausliefern – statt
     der Cache-Kopie eine klare „dafür brauchst du Verbindung“-Seite zeigen.
   - /static/-Dateien: cache-first (Logo, Icons, Manifest).
   - Nur GET wird behandelt; POST (Buchen etc.) läuft immer übers Netz.
   - Push: zeigt die Benachrichtigung an; Klick öffnet die mitgelieferte URL. */
const CACHE = "rehof-v2";
const OFFLINE_URL = "/offline/";
// Pfade, deren Inhalt zeit-/zustandskritisch ist (Verfügbarkeiten) – hier offline
// NICHT die Cache-Kopie zeigen, sondern den Buchen-Offline-Hinweis.
const BOOKING_PREFIXES = ["/buchen/", "/wunschliste/", "/extern/buchen/"];

function isBookingPath(pathname) {
  return BOOKING_PREFIXES.some((p) => pathname.startsWith(p));
}

function bookingOfflineResponse() {
  const html = `<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Offline – Re:Hof</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#faf5ee;color:#3c352f;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.box{text-align:center;padding:2rem 1.5rem;max-width:22rem}h1{font-size:1.3rem;margin:.4rem 0}
p{color:#8c8175}button{margin-top:1.2rem;font:inherit;font-weight:600;cursor:pointer;border:0;
border-radius:10px;background:#c9805d;color:#fff;padding:.6rem 1.2rem}</style></head>
<body><div class="box"><h1>Buchen braucht eine Verbindung</h1>
<p>Für Buchungen und Wünsche müssen die freien Zeiten aktuell geladen werden.
Bitte verbinde dich wieder mit dem Internet.</p>
<button onclick="location.reload()">Erneut versuchen</button></div></body></html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.add(OFFLINE_URL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Statische Dateien: erst Cache, dann Netz (und nachladen).
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req).then((hit) =>
        hit || fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
      )
    );
    return;
  }

  // Seiten-Navigationen: erst Netz, dann Cache, dann Offline-Seite.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => {
          // Buchen/Wunsch: keine veralteten Verfügbarkeiten – eigener Hinweis.
          if (isBookingPath(url.pathname)) return bookingOfflineResponse();
          return caches.match(req).then((hit) => hit || caches.match(OFFLINE_URL));
        })
    );
  }
});

// --- Web-Push ---------------------------------------------------------------
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const title = data.title || "Re:Hof";
  const options = {
    body: data.body || "",
    data: { url: data.url || "/" },
    icon: "/static/booking/icons/icon-192.png",
    badge: "/static/booking/icons/icon-192.png",
    tag: data.tag || undefined,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cls) => {
      for (const c of cls) {
        if ("focus" in c) { c.navigate(target); return c.focus(); }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
