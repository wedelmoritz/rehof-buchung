// Buchungs-Ansturm auf DENSELBEN Slot: viele Mitglieder versuchen GLEICHZEITIG,
// dasselbe beliebte Quartier + Datum zu buchen. Misst die heiße Stelle:
// Zeilensperre (SELECT … FOR UPDATE), Latenz unter Contention, Fehlerrate.
//
// WICHTIG zur Korrektheit: Genau EINE Buchung darf entstehen. Das prüfst du nach
// dem Lauf auf dem Server (siehe loadtest/README.md, "Auswertung").
//
// Vorbereitung auf dem Server VOR JEDEM Lauf (Slot frei + Budgets zurück):
//   docker compose exec web python manage.py seed_demo --testdata --yes
//
// Start (vom Laptop) – QUARTER_ID/START/END an einen FREIEN Slot anpassen:
//   k6 run -e BASE_URL=https://rehof.wedelparlow.de -e PASS=demo12345 \
//          -e MEMBERS=50 -e QUARTER_ID=1 -e START=2026-08-10 -e END=2026-08-14 \
//          loadtest/booking_rush.js
//
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const BASE = (__ENV.BASE_URL || 'https://rehof.wedelparlow.de').replace(/\/$/, '');
const PASS = __ENV.PASS || 'demo12345';
const MEMBERS = parseInt(__ENV.MEMBERS || '50');
const USER_PREFIX = __ENV.USER_PREFIX || 'anna';
const Q = __ENV.QUARTER_ID || '1';
const START = __ENV.START || '2026-08-10';
const END = __ENV.END || '2026-08-14';
const PERSONS = __ENV.PERSONS || '2';

export const options = {
  scenarios: {
    // Echter "Ansturm": in kurzer Zeit viele gleichzeitige Versuche.
    rush: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '20s', target: 25 },
        { duration: '40s', target: 75 },
        { duration: '40s', target: 150 },   // hier wird die Sperre heiß
        { duration: '20s', target: 0 },
      ],
      gracefulStop: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    'http_req_duration{step:book}': ['p(95)<2000', 'p(99)<5000'],
  },
};

const bookProcessed = new Counter('book_processed');   // Versuch serverseitig verarbeitet
const bookConflict = new Counter('book_conflict');     // erkennbar abgewiesen (belegt/Budget)
const bookT = new Trend('t_book', true);

function login(idx) {
  const g = http.get(`${BASE}/login/`);
  const token = g.html().find('input[name=csrfmiddlewaretoken]').first().attr('value');
  const r = http.post(`${BASE}/login/`,
    { csrfmiddlewaretoken: token, username: `${USER_PREFIX}${idx}`, password: PASS },
    { headers: { Referer: `${BASE}/login/` } });
  return r.status === 200 || r.status === 302;
}

let ready = false;

export default function () {
  if (!ready) { ready = login((__VU - 1) % MEMBERS); sleep(0.3); }

  // Bestätigungsseite holen → frischer CSRF-Token (rotiert nach Login).
  const cp = http.get(
    `${BASE}/buchen/bestaetigen/?quarter=${Q}&start=${START}&end=${END}&persons=${PERSONS}`,
    { tags: { step: 'confirm_page' } });
  const token = cp.html().find('input[name=csrfmiddlewaretoken]').first().attr('value');

  // Verbindliche Buchung absenden – alle auf denselben Slot.
  const r = http.post(`${BASE}/buchen/bestaetigen/`, {
    csrfmiddlewaretoken: token, action: 'confirm',
    quarter: Q, start: START, end: END, persons: PERSONS, companions: '',
  }, { headers: { Referer: `${BASE}/buchen/bestaetigen/` }, tags: { step: 'book' } });

  bookT.add(r.timings.duration);
  check(r, { 'kein Serverfehler (5xx)': (res) => res.status < 500 });
  bookProcessed.add(1);
  // Heuristik: Hinweistext "belegt"/"frei"/"Tage" deutet auf saubere Absage hin.
  if (/belegt|nicht (mehr )?frei|Tage|Mindest/i.test(r.body || '')) bookConflict.add(1);

  sleep(0.5);
}
