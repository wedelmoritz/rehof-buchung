# 0060 – Performance & Skalierung für >100 gleichzeitige Nutzer (Sicherheit vor Tempo)

## Status

Accepted (2026-06-28)

## Kontext

Ziel: viele gleichzeitige Nutzer (>100), möglichst wenige DB-Zugriffe – Buchungen
und Hofladen, aber auch Dashboard und Backend. **Sicherheit (Vertraulichkeit,
Integrität, korrekter Zugriff) hat ausdrücklich Vorrang vor Effizienz.** Eine
Messung der Query-Last (`CaptureQueriesContext`) zeigte zwei Hotspots: die
Startseite (165 Queries, durch die neue Wochen-Agenda) und das Backend
„Mitglieds-Anteile" (111, N+1).

## Entscheidung (Maßnahmen, priorisiert)

**P0/P1 – echte Gleichzeitigkeit & Integrität**
- **Startseiten-N+1 entzerrt** (Vorab-Fix): `week_agenda` 146→4 Queries, Übersicht
  165→23 – die Seite, die jeder zuerst sieht.
- **Gunicorn `gthread` + Threads:** gleichzeitige Requests ≈ workers×threads (statt
  3 sync-Slots); per Env steuerbar. DB-Verbindungsbudget (workers×threads ≤
  `max_connections`, sonst PgBouncer) dokumentiert.
- **`CONN_HEALTH_CHECKS=True`** zu den persistenten Verbindungen (conn_max_age).
- **Rechnungsnummer konfliktfrei:** `_next_number` sperrt die Singleton-Konfig-Zeile
  → gleichzeitige Checkouts erzeugen keine doppelte Nummer mehr (vorher
  `IntegrityError`; der `unique`-Constraint bleibt als Sicherung).
- **Redis empfohlen für Prod** (Cache + Sessions + Axes – bereits implementiert,
  Env-Schalter): nimmt die DB-Session-Schreiblast raus; serverseitig, kein
  Vertraulichkeitsverlust.

**P2 – DB-Last senken**
- **Backend-N+1 behoben:** Mitglieds-Anteile 111→14 (prefetch shares +
  Count-Annotation), Rechnungen 41→18 (select_related Empfänger + prefetch
  Positionen).
- **`shop.LineItem`-Composite-Index** `(member, purchase, invoice)` für die
  Hofladen-Filter (Warenkorb/offene Posten/Monatsabrechnung).
- **Geteilter Belegungs-Cache** (`_occupied_days_by_quarter`): **nur mit Redis**
  aktiv (LocMem ist pro Worker → stale); per **Signal** nach jeder
  Buchungsänderung (Allocation/ExternalBooking, `on_commit`) invalidiert + kurze
  TTL. Es werden **nur ohnehin allgemein sichtbare** Belegungsdaten gecacht.

**P3 – Feinschliff & Absicherung**
- Große Felder nicht in Admin-Listen laden (`OutboxEmail.body/html/attachment`,
  `BankTransaction.raw` via `defer()`).
- k6-Szenario `loadtest/shop_rush.js` (Hofladen-Schreibpfade unter Last).
- **Optionaler** PostgreSQL-`EXCLUDE`-Constraint gegen überlappende Buchungen
  **dokumentiert** (nicht eingespielt – Postgres-spezifisch, von der SQLite-Suite
  nicht testbar, nur Teil-Abdeckung über die bereits korrekte Sperre).

## Sicherheits-Leitplanken (Vorrang)
- **Zeilensperren/Constraints** bei Buchung & Checkout bleiben – Korrektheit >
  Tempo. Die Buchung prüft IMMER frisch unter Sperre; der Belegungs-Cache ist reine
  Anzeige-Beschleunigung.
- **Kein Cache** berechtigungspflichtiger/personenbezogener Daten über Nutzer
  hinweg; geteilter Cache nur für allgemein sichtbare Daten + Invalidierung; **keine
  Geheimnisse** im Cache.
- Axes/Brute-Force, gehärtete Cookies, Transaktions-Integrität unverändert
  (Redis-Sessions bleiben serverseitig).

## Konsequenzen
- Startseite 165→23, Mitglieds-Anteile 111→14, Rechnungen 41→18; echte
  Parallelität über Threads; ein realer Concurrency-Bug (Rechnungsnummer) behoben.
- Der Belegungs-Cache wirkt erst mit Redis (bewusst – sonst Cross-Worker-Stale).
- Restpunkte (PgBouncer, EXCLUDE-Constraint) sind dokumentiert und bei Bedarf
  zuschaltbar.
