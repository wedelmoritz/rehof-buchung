# 0109 – Security-Review-Nachträge (Voll-App): RBAC pro Aktion, Zahlungs-Guard, PII

## Status

Accepted (2026-07-20) · härtet [ADR 0100](0100-granulare-verwaltungsrollen-rbac.md) (RBAC),
[ADR 0017](0017-online-bezahlung-mollie-sandbox-default.md) (Mollie/Sandbox),
[ADR 0043](0043-dsgvo-datensparsamkeit-aufbewahrung-loeschung.md) (Datensparsamkeit).
**Umgesetzt (2026-07)** – Ergebnis eines vollständigen App-Security-Reviews.

## Kontext

Ein Security-Review über die gesamte App fand drei verifizierte Schwachstellen (der Rest
sauber: IDOR/Ownership, Magic-Links, Mollie-Webhook, XSS/SSTI, CSP, Config-Härtung).

## Entscheidung

**1) RBAC pro Aktion im Verwaltungs-Sammel-POST (Hoch).** `views._verw_post` verzweigte nur
auf `request.POST["action"]` **ohne** pro-Aktion-Rechteprüfung; erreichbar über den nur
bereichs-gegateten `dashboard`-POST (Capability „dashboard" = *irgendeine* Verwaltungsrolle,
`perm=None`). Damit konnte die schwächste Rolle (z. B. nur Hofladen) jede Aktion auslösen –
Kontoauszug-Import, Zahlungserinnerungen, Endreinigung bestätigen (löst Abrechnung aus),
Sperrzeiten, **Buchung stornieren + Ausgleichstage** (`apologize_block`). **Fix:** eine
`ACTION_PERM`-Map erzwingt je Aktion das konkrete Recht via `authz.user_can`
(`P_BUCHUNGEN`/`P_RECHNUNGEN`/`P_QUARTIERE`), sonst `PermissionDenied`. Superuser und die
Legacy-Rolle „Verwaltung" bleiben über `user_can` voll berechtigt (kein Bruch für Bestands-
Konten); nur **granulare** Rollen werden korrekt beschränkt.

**2) `payment_sandbox` prüft `is_sandbox` (Hoch/Mittel).** Die eingebaute TEST-Bezahlseite
rief `settle_payment` **ohne** `pay.is_sandbox`-Prüfung – im Echtbetrieb (Mollie-Key) ließ
sich mit dem eigenen `Payment`-Token die **echte** Rechnung ohne Zahlung auf „bezahlt"
setzen. **Fix:** `if not pay.is_sandbox: raise Http404` am Anfang der View.

**3) `member_search` ohne E-Mail (Mittel, DSGVO).** Das Empfänger-Typeahead gab `username`
zurück – der ist bei den meisten Konten die **E-Mail** (Selbstregistrierung/E-Mail-Wechsel).
Damit war der komplette Mitglieder-E-Mail-Verteiler für jedes eingeloggte Konto scrapebar.
**Fix:** `username` aus der JSON-Antwort entfernt (Anzeigename + echter Name genügen; die
Suche matcht serverseitig weiter auf E-Mail/Login). Das Frontend degradiert sauber.

## Architektur / Sicherheit

- Kleine, gezielte Diffs; keine Verhaltensänderung für legitime Rollen.
- **Defense in depth:** die Rechteprüfung sitzt jetzt am Sammel-Dispatcher, nicht nur an den
  Sub-Views; der Zahlungs-Guard schließt den TEST-Pfad im Echtbetrieb hart.
- Regressionstests in `booking/tests_security_rbac.py` (granulare Rolle → 403;
  Rechnungsrolle/Superuser erlaubt; Echt-Zahlung → 404; Suche ohne E-Mail).

## Nicht in diesem ADR (dokumentierte Restrisiken, niedrig)

`push_subscribe`-Endpoint-Übernahme (nicht erratbare Push-URLs), CAMT-DOCTYPE-Scan nur erste
4 KB (nur Verwaltung, 10-MB-Limit, keine externen Entities), Terminal-Roster mit PIN-Hashes
(bewusst, ADR 0053, starker Geräte-Token) – als Restrisiken vermerkt, hier nicht geändert.

## Konsequenzen

**Positiv** – Least Privilege (ADR 0100) ist nicht mehr aushebelbar; Zahlungs-Integrität
gegen den TEST-Pfad geschützt; kein E-Mail-Verteiler-Leak. Alles klein und getestet.

**Negativ / Grenzen** – die `ACTION_PERM`-Map muss bei neuen Verwaltungs-Aktionen
mitgepflegt werden (ein fehlender Eintrag = Aktion ohne Extra-Recht, nur bereichs-gegated);
Konvention: neue Aktion in `_verw_post` **immer** mit passendem `ACTION_PERM`-Eintrag.
