# 0090 – Rundnachrichten an Rollen + Rollen-Empfänger-Export

## Status

Accepted (2026-07-05) · konkretisiert ADR 0087 (Punkt 5)

## Kontext

Die Betriebsleitung will **Ankündigungen/Losnachrichten** an ganze Rollen schicken
(alle aktiven / alle inkl. passive / Verwaltung / Admins). Zusätzlich sollen sich
Mitglieder per Mail an rollen-adressierte Verteiler wenden können.

## Entscheidung

**Zwei getrennte Fähigkeiten** (Analyse aus ADR 0087):

1. **Ausgehende Rundnachricht (App → Rolle), in der App gebaut.** Ein Werkzeug für
   Admin/Verwaltung (`verw_rundnachricht`, `/verwaltung/rundnachricht/`, `_staff_required`)
   schickt Betreff + Text an eine Zielgruppe. Mitglieder-Zielgruppen bekommen
   **In-App-`Notification` + E-Mail (Opt-in) + Push**; „bl"/„admins" **E-Mail**
   (+ In-App, falls Mitglieds-Profil). Über die **Outbox** (asynchron). Nutzertext wird
   **literal** verschickt (kein Template-Engine) → keine SSTI; `strip_controls` kappt
   Steuerzeichen/Länge. Service `services.broadcast_message(audience, subject, body)`.

2. **Eingehende Mail an Mitglieder-Verteiler: NICHT in der App** (Mailinglisten-Server
   = Spam/Spoof/Abuse-Last). Stattdessen **externe Verteilerlisten** beim Mailprovider.
   Die App liefert dafür einen **Empfänger-Export je Rolle** als CSV
   (`services.role_recipients` + CSV-Download auf derselben Seite), den die BL in die
   externe Gruppe importiert. So bleibt die Mitgliedschaft in der App führend, ohne
   Inbound-Verarbeitung.

Zielgruppen: `active_members` (buchungsberechtigt), `all_members` (inkl. passive),
`bl` (Rolle Verwaltung + Admins), `admins` (Superuser). Das Katalog-Ereignis
`announcement` (ADR 0089) hält die neutrale Betreff-Hülle.

## Konsequenzen

**Positiv** – BL kann Rollen gezielt erreichen (In-App + Mail + Push), ohne pro
Empfänger zu hantieren; die riskante Inbound-Verarbeitung entfällt zugunsten
bewährter externer Listen, die die App per Export aktuell hält.

**Grenzen** – die externe Liste muss (manuell/per Export) synchron gehalten werden;
bei sehr großer Mitgliederzahl wäre ein Provider-API-Sync der nächste Schritt.
