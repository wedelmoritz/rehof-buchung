# 0052 – Konto-Einladung: Passwort selbst setzen statt Admin-Vergabe

## Status

Accepted (2026-06-27)

> **Fachlicher Bezug:** Rollen/Konten siehe [Fachkonzept § 14 – Rollen & Rechte](../FACHKONZEPT.md#14-rollen--rechte).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest.

## Kontext

Bisher mussten Admins beim Anlegen eines Benutzers im Backend selbst ein Passwort
vergeben und es der Person mitteilen – unsicher (Passwort im Klartext über einen
Nebenkanal), unbequem und gegen das Prinzip, dass nur die Person selbst ihr Passwort
kennt. Dasselbe gilt für die per Beds24-Migration angelegten Konten (ADR 0030): sie
entstanden mit einem unbrauchbaren Passwort und ohne Weg, eines zu setzen.

## Entscheidung

Vom Backend **oder** vom Import angelegte Benutzer **setzen ihr Passwort selbst**
über einen Einladungs-Link – Admins vergeben kein Passwort mehr.

- **Mechanik:** wiederverwendet Djangos Token-Mechanismus (`default_token_generator`
  + `urlsafe_base64_encode(user.pk)`), exakt wie der Passwort-Reset – nur mit eigener
  „Passwort setzen"-Sprache. Zwei Views auf Basis von `PasswordResetConfirmView` /
  `PasswordResetCompleteView` (`/passwort-setzen/<uidb64>/<token>/`,
  `/passwort-gesetzt/`), eigene Templates unter `registration/`.
- **Versand:** `services.send_account_invite(user)` baut den absoluten Link
  (`PUBLIC_BASE_URL`) und reiht die Mail über die Outbox ein (ADR 0027). Voraussetzung
  ist eine **E-Mail-Adresse** – sie ist daher beim Anlegen Pflicht.
- **Backend-`UserAdmin`:** ein schlankes `add_form` (`AdminUserInviteForm`) ohne
  Passwortfelder, nur Benutzername + (Pflicht-)E-Mail; `save_model` setzt ein
  unbrauchbares Passwort und verschickt die Einladung. Zusätzlich eine Admin-Aktion
  „Einladung (erneut) senden".
- **Beds24-Import:** `beds24_create_member` verschickt die Einladung automatisch,
  sobald eine E-Mail vorliegt (der Beds24-Export liefert sie i. d. R. mit).
- **Doppel-Mail vermieden:** Das „Konto freigeschaltet"-Signal an der `Member`-Anlage
  (ADR 0027) wird übersprungen, solange das Konto **kein** brauchbares Passwort hat –
  die Person bekommt zunächst die Einladung (sie kann sich ohnehin noch nicht anmelden).

## Betrachtete Alternativen

- **Admin vergibt Passwort weiter:** verworfen – unsicher (Klartext-Weitergabe) und
  gegen „nur die Person kennt ihr Passwort".
- **Eigener Token-/Einladungs-Mechanismus:** verworfen – Djangos Reset-Token ist
  erprobt, zeitlich begrenzt und an den Passwort-Hash gebunden (wird nach dem Setzen
  ungültig). Kein Grund, etwas Eigenes zu bauen.
- **Zufallspasswort + erzwungener Wechsel beim ersten Login:** verworfen – das
  Zufallspasswort müsste trotzdem zugestellt werden; der Token-Link ist direkter.

## Konsequenzen

**Positiv**
- Kein Passwort-Versand über Nebenkanäle; nur die Person setzt ihr Passwort.
- Ein einheitlicher Weg für Backend- **und** Import-Konten; greift dieselbe
  Outbox/`PUBLIC_BASE_URL`-Naht wie alle anderen Mails.
- E-Mail als Pflichtanker verbessert nebenbei die Datenqualität (eindeutiger Login).

**Negativ / Grenzen**
- **Ohne E-Mail keine Einladung:** Konten ohne Adresse müssen manuell nachbearbeitet
  werden (E-Mail nachtragen → Einladung erneut senden). Der Backend-Flow erzwingt die
  E-Mail daher.
- Der Link ist zeitlich begrenzt (Django-Default); abgelaufene Links erfordern ein
  erneutes Senden bzw. „Passwort vergessen".
- Eine öffentliche „Passwort vergessen"-Selbstbedienung ist (noch) nicht verdrahtet –
  abgelaufene Einladungen löst aktuell die Verwaltung per Admin-Aktion neu aus.
