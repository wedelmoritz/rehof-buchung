/* Re:Hof Service Worker – PWA-Offline-Unterstützung.
   Strategie:
   - Navigationen (HTML): network-first → bei Offline aus dem Cache, sonst die
     Offline-Seite. So sieht man online immer frische, eingeloggte Inhalte und
     offline die zuletzt besuchten Seiten.
   - /static/-Dateien: cache-first (Logo, Icons, Manifest).
   - Nur GET wird behandelt; POST (Buchen etc.) läuft immer übers Netz. */
const CACHE = "rehof-v1";
const OFFLINE_URL = "/offline/";

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
        .catch(() => caches.match(req).then((hit) => hit || caches.match(OFFLINE_URL)))
    );
  }
});
