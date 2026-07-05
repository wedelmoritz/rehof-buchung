# 0091 – In-App-Kontaktformular an Rollen-Adressen

## Status

Accepted (2026-07-05) · konkretisiert ADR 0087 (Punkt 6)

## Kontext

Mitglieder brauchen einen einfachen, sichtbaren Weg, die Betriebsleitung zu
erreichen (Frage zur Buchung, Endreinigung, allgemeine Sache, technisches Problem).
Ein Mailto-Link im Fuß war die Notlösung; er verrät die Adresse, öffnet ein externes
Mailprogramm und trägt keinen Kontext (wer schreibt, worum geht es).

## Entscheidung

**Ein In-App-Formular auf der Hilfe-Seite** (`#kontakt`), nur für eingeloggte
Mitglieder. Kategorie-Auswahl + Freitext → `views.contact_send`
(`/kontakt/senden/`, `@login_required` + `@require_POST` + `@ratelimit user 5/h`) →
`services.send_contact_message(user, category, message)`.

**Sicherheit (wie ADR 0089/0090):**

- **SSTI-frei:** der Nachrichtentext wird **literal** verschickt (kein Template-
  Engine), `strip_controls` kappt Steuerzeichen und Länge (4000).
- **Header-Injection:** `queue_email` verwirft Zeilenumbrüche im Betreff und im
  `reply_to`. Der Betreff ist eine **feste** Kategorie-Hülle („Re:Hof-Kontakt: …“),
  nicht vom Nutzer bestimmt.
- **Reply-To = Absender:** die BL antwortet direkt an die im Profil hinterlegte
  Adresse des Mitglieds (neues Feld `OutboxEmail.reply_to`; `send_outbox` setzt es).
- **Kein Inbound:** die App verschickt nur ausgehend (wie ADR 0090) – kein
  Mailserver-Empfang, keine Spam-/Relay-Last.

**Routing je Kategorie** über `OpsConfig.contact_list(category)`: `bug` geht an
`contact_email_tech`, alles andere an `contact_email_bl`; beide leer = die
Verwaltungs-Adressen (`admin_emails`). So kann die BL technische Anliegen an eine
eigene (Rollen-)Adresse leiten, ohne Code-Änderung.

Kategorien (`services.CONTACT_CATEGORIES`): Buchung/Wünsche · Endreinigung ·
Allgemeine Frage · Technisches Problem. Der Fuß-Link „Kontakt“ führt eingeloggte
Nutzer aufs Formular, anonyme weiter auf die konfigurierte Mailto-Adresse.

## Konsequenzen

**Positiv** – niederschwelliger, kontext-reicher Draht zur BL ohne externes
Mailprogramm; die Adresse bleibt verborgen; Anliegen landen rollenrichtig; die
bewährte Outbox trägt den Versand (asynchron, robust).

**Grenzen** – kein In-App-Postfach für Antworten (die BL antwortet per E-Mail an
Reply-To); bei Bedarf ließe sich später ein In-App-Verlauf ergänzen.
