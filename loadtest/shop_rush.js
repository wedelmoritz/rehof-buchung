// Hofladen-Last: viele Mitglieder stöbern parallel im Katalog, legen in den
// Warenkorb und checken aus. Prüft die Schreib-Pfade des Hofladens unter
// Gleichzeitigkeit – insbesondere die gegen Doppelnummern gesperrte
// Rechnungsnummer-Vergabe (siehe shop.services._next_number) und die
// Warenkorb-Operationen.
//
// Start (NUR gegen die Test-Instanz):
//   k6 run -e BASE_URL=https://rehof.wedelparlow.de -e PASS=demo12345 \
//          -e MEMBERS=50 loadtest/shop_rush.js
//
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = (__ENV.BASE_URL || 'https://rehof.wedelparlow.de').replace(/\/$/, '');
const PASS = __ENV.PASS || 'demo12345';
const MEMBERS = parseInt(__ENV.MEMBERS || '50');
const USER_PREFIX = __ENV.USER_PREFIX || 'anna';

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m',  target: 40 },
    { duration: '1m',  target: 80 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.02'],                       // < 2 % Fehler
    'http_req_duration{page:shop}': ['p(95)<900'],
    'http_req_duration{op:checkout}': ['p(95)<1500'],
  },
};

const shopT = new Trend('t_shop', true);

function csrf(html) {
  return html.find('input[name=csrfmiddlewaretoken]').first().attr('value');
}

function login(vu) {
  const idx = (vu - 1) % MEMBERS;
  const g = http.get(`${BASE}/login/`);
  const r = http.post(`${BASE}/login/`,
    { csrfmiddlewaretoken: csrf(g.html()), username: `${USER_PREFIX}${idx}`, password: PASS },
    { headers: { Referer: `${BASE}/login/` } });
  return r.status === 200 || r.status === 302;
}

let didLogin = false;

export default function () {
  if (!didLogin) { didLogin = login(__VU); sleep(0.5); }

  // 1) Katalog ansehen
  const shop = http.get(`${BASE}/hofladen/`, { tags: { page: 'shop' } });
  check(shop, { 'shop 200': (r) => r.status === 200 });
  shopT.add(shop.timings.duration);
  const token = csrf(shop.html());

  // 2) erstes Produkt in den Warenkorb (Produkt-ID aus dem Formular lesen)
  const pid = shop.html().find('input[name=product]').first().attr('value');
  if (pid && token) {
    http.post(`${BASE}/hofladen/`,
      { csrfmiddlewaretoken: token, action: 'add', product: pid, quantity: '1' },
      { headers: { Referer: `${BASE}/hofladen/` }, tags: { op: 'add_cart' } });
    sleep(Math.random() * 1.5 + 0.5);

    // 3) ein Teil der VUs checkt aus (Warenkorb → bestätigter Einkauf)
    if (Math.random() < 0.3) {
      const s2 = http.get(`${BASE}/hofladen/`);
      http.post(`${BASE}/hofladen/`,
        { csrfmiddlewaretoken: csrf(s2.html()), action: 'checkout' },
        { headers: { Referer: `${BASE}/hofladen/` }, tags: { op: 'checkout' } });
    }
  }
  sleep(Math.random() * 2 + 1);                          // Think-Time
}
