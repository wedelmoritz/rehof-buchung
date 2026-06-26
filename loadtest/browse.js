// Lese-Last ("Stöbern"): viele Mitglieder browsen parallel Übersicht, Buchen-
// Kalender und Meine Buchungen. Misst Latenz/Durchsatz der leselastigen Seiten
// (Query-Performance, Session-DB-Last, Cache-Wirkung) – ohne den Zustand zu ändern.
//
// Start (vom Laptop):
//   k6 run -e BASE_URL=https://rehof.wedelparlow.de -e PASS=demo12345 \
//          -e MEMBERS=50 loadtest/browse.js
//
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = (__ENV.BASE_URL || 'https://rehof.wedelparlow.de').replace(/\/$/, '');
const PASS = __ENV.PASS || 'demo12345';        // Passwort der Demo-Mitglieder
const MEMBERS = parseInt(__ENV.MEMBERS || '50'); // anna0..anna{N-1} → hier generisch user{i}
const USER_PREFIX = __ENV.USER_PREFIX || 'anna'; // seed_demo legt Namen wie "anna0" an – ggf. anpassen

export const options = {
  // Stufenweise hochfahren bis der "Knick" (Latenz/Fehler) sichtbar wird.
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m',  target: 30 },
    { duration: '1m',  target: 60 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    // SLOs – hier justieren. Bricht eine Schwelle, ist der Lauf "rot".
    http_req_failed: ['rate<0.02'],                 // < 2 % Fehler
    'http_req_duration{page:overview}': ['p(95)<800'],
    'http_req_duration{page:book}': ['p(95)<1200'],
  },
};

const overviewT = new Trend('t_overview', true);

function loggedIn(__VU) {
  // Pro VU einmal einloggen; k6 hält Cookies je VU.
  const idx = (__VU - 1) % MEMBERS;
  const g = http.get(`${BASE}/login/`);
  const token = g.html().find('input[name=csrfmiddlewaretoken]').first().attr('value');
  const r = http.post(`${BASE}/login/`,
    { csrfmiddlewaretoken: token, username: `${USER_PREFIX}${idx}`, password: PASS },
    { headers: { Referer: `${BASE}/login/` } });
  return r.status === 200 || r.status === 302;
}

let didLogin = false;

export default function () {
  if (!didLogin) { didLogin = loggedIn(__VU); sleep(0.5); }

  const ov = http.get(`${BASE}/`, { tags: { page: 'overview' } });
  check(ov, { 'overview 200': (r) => r.status === 200 });
  overviewT.add(ov.timings.duration);
  sleep(Math.random() * 1.5 + 0.5);              // Think-Time

  http.get(`${BASE}/buchen/`, { tags: { page: 'book' } });
  sleep(Math.random() * 1.5 + 0.5);

  http.get(`${BASE}/meine-buchungen/`, { tags: { page: 'mybookings' } });
  sleep(Math.random() * 2 + 1);
}
