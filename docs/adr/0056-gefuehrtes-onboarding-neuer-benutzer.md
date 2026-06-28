# 0056 – Geführtes Onboarding neuer Benutzer im Backend

## Status

Accepted (2026-06-28)

> Baut auf der „Neue Benutzer“-Erkennung (`users_without_membership`, E-Mail an die
> Verwaltung) und dem persistenten Backend-Navigator (ADR 0055) auf.

## Kontext

Neue Konten (Selbstregistrierung oder Einladung) sind erst nutzbar, wenn die
Verwaltung sie zuordnet. Bisher musste man dafür das **volle Benutzer-Formular**
öffnen, das Mitglieds-Profil ausfüllen **und** separat unter „Mitglieds-Anteile“
einen `Share` anlegen – viele Schritte, leicht unklar. Gewünscht: eine **geführte
Seite mit wenigen Klicks**, die ein Konto entweder **als Mitglied** (kann buchen)
oder **nur für den Hofladen/das Terminal** zuordnet, und unbekannte Konten
**deaktivieren/löschen** kann.

## Entscheidung

Eine eigene, geführte Backend-Seite **„Neue Benutzer (Zuordnung)“** als Proxy-Modell
`PendingUser` (Proxy auf `auth.User`), registriert unter **Benutzer & Mitglieder**
(erste Position). Sie listet nur Konten **ohne Mitglieds-Anteil**
(`services.users_without_membership`) und bietet pro Konto drei Wege als einfache
Karten-Formulare:

1. **Als Mitglied** – `services.onboard_as_member`: stellt das Mitglieds-Profil
   sicher und legt einen `Share` (Tage-/Wunsch-Anteil) an einem **bestehenden ODER
   neuen** Mitglieds-Anteil an. Anzeigename + Budgets sind vorbefüllt
   (`Membership.suggest_budget`). Danach kann die Person buchen.
2. **Nur Hofladen/Terminal** – `services.onboard_as_terminal`: stellt ein
   Mitglieds-Profil als **Hofladen-Gast** (`is_external=True`, `terminal_enabled=True`)
   sicher. Die Person darf am Vor-Ort-Terminal auf die Monatsrechnung einkaufen
   (PIN setzt sie selbst), erscheint aber **nicht** in Losung/Mitgliedersuche und
   gilt nicht als Buchungs-Mitglied.
3. **Unbekannt?** – `services.deactivate_account` (Login sperren, reversibel) oder
   **löschen** (mit Rückfrage).

Nach jeder Aktion verschwindet das Konto aus der Liste (es hat dann einen `Share`
oder ist external/inaktiv/gelöscht). Die bestehende **E-Mail-Benachrichtigung** an
die Verwaltung und das **„Neue Benutzer“-Panel** auf der Startseite bleiben; das
Panel verlinkt jetzt auf diese geführte Seite.

**Warum `is_external` für „nur Hofladen/Terminal“.** Das Flag bedeutet bereits
„kein Buchungs-Mitglied“ (ausgeschlossen aus Losung – `lottery_ops` – und
Mitgliedersuche – `forms`/`views`) und schließt das Konto aus
`users_without_membership` aus. Ein Hofladen-Gast mit Login passt genau hierauf;
ein zusätzliches Flag wäre Redundanz.

**Bewusst ohne JavaScript** (außer der Lösch-Rückfrage): Die „neuer Anteil“-Wahl
ist ein normales `<select>` + ein immer sichtbares Bezeichnungsfeld. So funktioniert
die Seite auch beim **pjax-Laden** (ADR 0055), ohne Skripte nachzuziehen. Die
Formulare senden per **POST** (voller Reload, Django-`messages`) – der Navigator
bleibt durch das server-gerenderte `pretitle` erhalten.

## Konsequenzen

**Positiv**
- Zuordnung in **wenigen Klicks**, klar geführt; kein Pflicht-Umweg über zwei
  getrennte Admin-Bereiche.
- Reine Logik in testbaren Service-Funktionen (`onboard_as_member`/
  `onboard_as_terminal`/`deactivate_account`), die View bleibt dünn.
- Unbekannte Konten lassen sich direkt deaktivieren/löschen.

**Negativ / Grenzen**
- „Nur Hofladen/Terminal“ nutzt `is_external` – semantisch „externer Gast mit
  Login“. Wer das später feiner trennen will, müsste ein eigenes Feld einführen.
- Die Budgets sind Vorschläge (anteilig nach Datum); die Feinheiten (Tandem-
  Aufteilung über mehrere Nutzer) laufen weiter über den `Mitglieds-Anteil`-Bereich.
- Proxy-Modell erzeugt eine (schemafreie) Migration für Berechtigungen.
