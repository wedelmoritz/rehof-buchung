# 0053 – Hofladen-Terminal vor Ort: offline-fähiger, token-authentifizierter Kiosk

## Status

Accepted (2026-06-27)

> **Fachlicher Bezug:** Rechnungen/Monatsrechnung siehe
> [Fachkonzept § 13](../FACHKONZEPT.md#13-rechnungen-zahlung--steuer); die
> Abwägung der Gesamt-Idee steht in [`HOFLADEN-KIOSK-KONZEPT.md`](../HOFLADEN-KIOSK-KONZEPT.md).
> Diese ADR hält die *technische* Umsetzung und ihre Abwägungen fest.

## Kontext

Externe Gäste (überwiegend 60+, oft ohne Smartphone) sollen den **Hofladen** vor Ort
nutzen. Im Laden gibt es **kein WLAN und kein Mobilfunknetz** – das Gerät ist während
des Betriebs **offline**. Es braucht also eine **einfache** Anmeldung am geteilten
Gerät, **Offline-Betrieb**, und es darf **keine** Mitglieder-/Rechnungsdaten preisgeben.
Bargeld wäre die Alternative, reaktiviert aber die bewusst vermiedene TSE-/Kassenpflicht
(ADR 0040) – also unerwünscht.

## Entscheidung

Ein eigener **Terminal-Modus** unter `/terminal/`: eine **eigenständige, offline-fähige
Kiosk-Seite**, die sich **nur mit einem Geräte-Token** gegenüber dem Server ausweist –
**kein** Mitglieder-Login, **keine** Django-Sitzung. Einzelne Gäste authentifizieren
sich **am Gerät** per **6-stelliger PIN**, nur um ihren Einkauf zuzuordnen.

**Token-Gate (offline-tauglich, im Backend änderbar).** `TerminalConfig` (Singleton):
`enabled`, `token` (langes Geheimnis, Admin-Aktion „neu erzeugen"), Idle-Timeout,
PIN-Sperrschwelle. Nur ein mit dem Token eingerichtetes Gerät darf die beiden
Token-Endpunkte nutzen:
- `POST /terminal/daten/` → **Roster** (terminalfähige Konten: Benutzername,
  Anzeigename, **PIN-Hash**) + **Katalog** + Einstellungen. Konstantzeit-Token-Vergleich.
- `POST /terminal/sync/` → reicht **offline erfasste Einkäufe** nach; bucht sie
  **idempotent** (`Purchase.terminal_ref`) auf die **Monatsrechnung** des Mitglieds.

Mehr bieten die Token-Endpunkte **nicht** – kein Zugriff auf Profil/IBAN/Adressen/
fremde Rechnungen/Zahlung/Backend. Das ist die zentrale Sicherheitsidee: die
Terminal-Schnittstelle **kann** nichts Sensibles, unabhängig davon, wer am Gerät steht.

**Offline-Betrieb.** Die Seite wird vom Service Worker vorgehalten (`/terminal/` im
Precache, ADR 0035). Beim Online-Sein lädt sie Roster+Katalog und legt sie in
`localStorage` ab; offline arbeitet sie damit weiter. Einkäufe wandern in eine
**lokale Warteschlange** und werden beim nächsten Online-Sein automatisch über
`/terminal/sync/` nachgereicht (idempotent → keine Doppelbuchung).

**PIN-Prüfung offline.** Die PIN wird **im Gerät** gegen den mitgelieferten
**Django-PBKDF2-Hash** geprüft (Web Crypto `PBKDF2-SHA256`, dasselbe Format
`pbkdf2_sha256$iter$salt$hash`). So braucht die Anmeldung keinen Server. Sperre nach
N Fehlversuchen (lokal), **Idle-Auto-Logout**.

**Keine Zahlung am Terminal.** Einkäufe laufen ausschließlich auf die **Monatsrechnung**
(ADR 0016). Das hält Kartendaten/PCI komplett draußen und entwertet eine geklaute PIN.

**Anlage & Freigabe nur im Normal-System.** Am Terminal kann man sich **nicht**
registrieren. Die Person registriert sich zuhause/per Handy, die **Verwaltung schaltet
frei** (`Member.terminal_enabled`), und die Person setzt **selbst** ihre PIN im Profil.
Ohne gesetzte PIN erscheint sie nicht in der Roster.

**UX für ältere Menschen:** große Schrift/Schaltflächen, hoher Kontrast, Emoji-Symbole,
wenige Schritte (Name antippen → PIN → Artikel antippen → bestätigen → fertig),
deutsche Klartext-Texte, automatischer Rücksprung/Logout.

## Betrachtete Alternativen

- **Mitglieder-Login (E-Mail/Passwort) am Gerät:** Hauptpasswort auf geteiltem Gerät –
  Schulterblick aufs *wichtige* Passwort, umständlich für 60+. PIN ist gerätegeeigneter
  und „wegwerfbar".
- **Server-seitige PIN-Prüfung:** scheitert am fehlenden Netz im Laden.
- **Reduzierte Django-Sitzung pro Gast** (Middleware-Whitelist): unnötig komplex – ohne
  Gäste-Sitzung gibt es nichts zu beschränken; die Token-Endpunkte bieten ohnehin nur
  Laden+Sync.
- **Bargeldkasse:** reaktiviert TSE-/Kassenpflicht (ADR 0040) – steuer-/kassenrechtlich
  aufwendiger, verworfen.
- **IP-Allowlist als Gate:** im Offline-Laden ohne stabile/erreichbare IP untauglich;
  Token ist offline-tauglich und im Backend rotierbar.

## Konsequenzen

**Positiv**
- Funktioniert **offline**; einfache, für Ältere bedienbare Oberfläche.
- **Kleiner Schadensradius:** die Schnittstelle gibt nur Laden+Roster+Sync her, keine
  PII/Zahlung; die PIN ist ein separates, geringwertiges Credential (kein Account-
  Übernahme-Risiko).
- Token im Backend **rotierbar** (bei Token-Leak sofort ungültig); idempotenter Sync.

**Negativ / Grenzen (wichtig, in `HOFLADEN-KIOSK-KONZEPT.md` ausführlich)**
- **Roster enthält PIN-Hashes + Namen auf dem Gerät.** Das ist die irreduzible
  Offline-Voraussetzung. Gegenmaßnahmen: nur terminalfähige Konten, Minimaldaten (keine
  PII), langsamer PBKDF2-Hash, **Pflicht zur Geräte-Härtung** (OS-Kiosk-Mode,
  **Festplatten-Verschlüsselung**, physische Sicherung, segmentiertes/keines Netz) –
  siehe Deployment-Runbook. Ohne diese Härtung ist der Modus **nicht** sicher.
- **Token-Rotation schützt nicht den physisch gestohlenen, dauerhaft offline
  betriebenen Apparat** (er kennt die Rotation nie) – dort tragen Festplatten-
  Verschlüsselung + physische Sicherung + der kleine Schadensradius.
- **Lokale PIN-Sperre ist umgehbar** (localStorage löschbar); akzeptabel, weil der
  Gewinn winzig ist (Lebensmittel auf eine Monatsrechnung, vom Opfer einsehbar).
- Eine serverseitige Anomalie-Erkennung der Sync-Buchungen ist nicht umgesetzt (offen).
