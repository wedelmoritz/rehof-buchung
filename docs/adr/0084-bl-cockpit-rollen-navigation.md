# 0084 – BL-Cockpit: rollen-reine Navigation & Dashboard-Tabs statt getrennter Accounts

## Status

Accepted (2026-07-04)

> Tester-Feedback der Betriebsleitung (Sophie): #48, #49, #50, #58, #59, #74, #75, #43.

## Kontext

Die Verwaltungs-/Admin-Konten erlebten die App als „Mitglieder-Ansicht mit
Aufsätzen":

- **#48** Ein reines Verwaltungs-Konto (ohne Buchungs-Profil) sah die mitglieds-
  eigenen Menüpunkte (Buchen, Wunschliste, Meine Buchungen, Tage übertragen,
  Profil …), die für es **ins Leere liefen**.
- **#58** „Hofladen-Katalog pflegen" lag als loser roter Knopf oben rechts statt in
  der Navigation.
- **#59** Das Dashboard war **eine sehr lange Scroll-Seite** (Reinigung, Buchungen,
  Rechnungen, Kontoabgleich untereinander).
- **#43** Das Verwaltungs-Icon (Sonne) irritierte.
- **#49/#75** Wunsch nach „Verwaltung/Admin als **eigene Rolle/Accounts** statt
  Add-on auf dem Mitglieds-Account".

## Entscheidung

**Das Rollen-*Erlebnis* verbessern, ohne das Auth-Modell umzubauen** – die
Navigation rollenrein machen und das Dashboard zu einem Cockpit ordnen.

1. **Rollen-reine Navigation (#48):** Mitglieds-eigene Menüpunkte werden per
   `{% if user.member %}` nur mit Buchungs-Profil gezeigt – in Seitenleiste,
   mobiler Tab-Leiste **und** „Mehr"-Sheet. Ein reines Verwaltungs-Konto bekommt so
   eine schlanke Nav (Übersicht · Gemeinschaft · Hilfe · Verwaltung); am Handy tritt
   „Verwaltung" als Haupt-Tab an die Stelle der Mitglieds-Tabs. Verwaltung **plus**
   Mitglied sieht weiterhin alles.

2. **Dashboard-Tabs (#59):** Die vier langen operativen Abschnitte
   (Reinigung · Buchungen · Rechnungen · Kontoabgleich) sind jetzt **Tabs** – nur
   **einer** ist sichtbar. Umgesetzt **server-getrieben** über `?tab=` + `data-ajax`
   (wie die Rechnungs-Filter): der View liest `active_tab`, das Template rendert die
   nicht aktiven Panels mit `hidden`. **Kein Client-JS/State**, damit es nach Monat-/
   Filter-Reload erhalten bleibt und **CSP-konform** ist (die CSP ist nonce-basiert
   **ohne** `strict-dynamic`, d. h. nach einem AJAX-Swap neu erzeugte Skripte laufen
   nicht – die App arbeitet bewusst mit delegierten Handlern + Server-State). Der
   aktive Tab bleibt auch über POST-Aktionen (erinnern/senden/importieren) erhalten
   (Hidden-Feld `tab` + Redirect).

3. **Konsistente Aktionen (#58):** „Hofladen-Katalog pflegen" und „Beds24-Import"
   (nur Admin) sind in die Bereichsleiste des Dashboards gewandert; der lose Knopf
   oben rechts entfällt. „Backend (Admin)" erscheint nur noch für Admins.

4. **Icon (#43):** Das Verwaltungs-Icon ist ein Klemmbrett mit Haken statt einer
   Sonne (passt zu Freigaben/Reinigung/Buchungen).

## Bewusst NICHT: getrennte Accounts (#75/#49)

Getrennte Login-Accounts je Rolle würden **mehr Angriffsfläche** (weitere
Passwort-Silos) und Support-Aufwand schaffen, ohne das reale Problem (die
Navigation) zu lösen. Das bestehende Modell ist bereits sauber: **Admin =
Superuser**, **Verwaltung = Gruppe** (`booking/permissions.py`), serverseitig
geprüft. Die Entkopplung mehrerer Logins pro Mitglied bleibt ein separater, bewusst
zurückgestellter Umbau (ADR 0069). „Rolle" statt „Gruppe" (#74) bleibt eine reine
Beschriftungsfrage (Kandidat, hier noch nicht umgesetzt).

## Offen / Folgeschritte

- **#50** „Gast direkt einbuchen ohne Ansichtswechsel" (BL-Aktion im Cockpit) ist
  eine **neue Schreib-Fähigkeit** und wird gesondert entschieden/umgesetzt.
- **#65** Mitgliederliste mit Kontaktdaten für die BL (eigener Schritt).
- **#74** „Rolle" statt „Gruppe" (Beschriftung) als kosmetischer Folgeschritt.

## Konsequenzen

**Positiv** – reine Verwaltungs-Konten laufen nicht mehr ins Leere; das Dashboard
ist scanbar statt endlos; keine riskante Auth-Änderung; CSP-Modell unangetastet.
Rein Template-/View-seitig (keine Migration).

**Grenzen** – ohne JavaScript zeigt das Dashboard alle Panels (Progressive
Enhancement, Server rendert dennoch den aktiven Tab sichtbar); das ist bewusst der
robuste, CSP-treue Weg statt Client-Tabs.
