# 0049 – Backend: fachliche Gliederung statt App-Gruppierung

## Status

Accepted (2026-06-27)

## Kontext

Das Django-Admin-Backend gruppiert Modelle standardmäßig nach **App** (`booking`,
`shop`, `auth`, `axes`). Für die Verwaltung ist das wenig hilfreich: zusammen-
gehörige Dinge liegen weit auseinander (z.B. „Buchungsperioden", „Wünsche" und
„Losdurchläufe" gehören fachlich zum Losverfahren, stehen aber im großen
`booking`-Block neben 20 anderen Modellen), und technische Logs mischen sich mit
Stammdaten. Gewünscht war eine **fachliche Gliederung** in wenige, klar benannte
Sektionen – schnell zugänglich, sowohl auf der Startseite als auch in der
Seitenleiste.

## Entscheidung

Eine **eigene Admin-Site** (`booking.admin_site.RehofAdminSite`) überschreibt
`get_app_list` und gruppiert **alle** registrierten Modelle in **fünf fachliche
Sektionen** (statt nach App):

1. **Benutzer & Mitglieder** – Benutzer, Gruppen, Mitglieds-Anteile, Tage-Übertragungen
2. **Quartiere & Buchungssystem** – Quartiere/Äquivalenzklassen, Buchungsregeln,
   Zuteilungen, Anstehende Buchungen, Warteliste, Wechselwünsche **und externe
   Gäste** (Gast/Externe Buchung/Einstellungen – sie buchen ebenfalls Quartiere)
3. **Losverfahren** – Buchungsperioden, Wünsche, Losdurchläufe, Fairness-Nachweis
4. **Hofladen** – Produkte/Gruppen, Einkäufe/Positionen, Rechnungen, Online-Zahlungen,
   Kontoauszug-Import/Zahlungseingänge, Rechtliche & Zahlungs-Einstellungen
5. **Administratives & Logs** – Betriebs-Einstellungen, Benachrichtigungen, E-Mail-
   Ausgang, Beds24-Import, axes-Zugriffslogs

Mechanik (sauberer, native Django-Weg):

- `RehofAdminSite.get_app_list` nimmt die berechtigungsgefilterte Standardliste,
  indexiert die Modelle nach `app_label.ModelName` und baut daraus die Sektionen
  in fester Reihenfolge (innerhalb jeder Sektion die wichtigsten zuerst). Ein
  **Sicherheitsnetz „Weitere"** fängt nicht eingeplante (z.B. neu registrierte)
  Modelle auf, damit nie etwas „verschwindet".
- Aktiviert über `booking.admin_apps.RehofAdminConfig` (`default_site`), in
  `INSTALLED_APPS` **statt** `django.contrib.admin`. Die Modell-Registrierungen
  (`@admin.register`) und `site_header`/`index_template` in `booking/admin.py`
  bleiben unverändert – sie greifen auf dieselbe (jetzt fachlich gegliederte) Site.
- Wird der Admin für eine **einzelne** App aufgerufen (`get_app_list(app_label=…)`),
  bleibt das Standardverhalten erhalten (keine Doppel-Logik).

## Betrachtete Alternativen

- **Fertig-Lösung (django-jazzmin / grappelli / admin-interface):** verworfen –
  schwere Fremd-Abhängigkeit gegen die Minimal-Linie des Projekts; das warme Theme
  (ADR aus base_site) + `get_app_list` genügen.
- **Modelle in eigene „Proxy-Apps" verschieben:** verworfen – invasiv (Migrationen,
  App-Labels) für reinen Anzeigezweck. `get_app_list` ändert nur die Darstellung.
- **Nur die Startseite umsortieren (Template):** verworfen – die **Seitenleiste**
  nutzt ebenfalls `get_app_list`; über die Site-Methode sind Index UND Sidebar
  konsistent gruppiert.
- **Sektion „Externe Gäste" als eigener 6. Punkt:** verworfen zugunsten der
  Einordnung unter „Quartiere & Buchungssystem" (Gäste buchen Quartiere); die fünf
  Sektionen bleiben übersichtlich.

## Konsequenzen

**Positiv**
- Schnell auffindbar: fachlich zusammengehörige Modelle stehen beieinander, in
  sinnvoller Reihenfolge – Startseite und Seitenleiste identisch.
- Keine Fremd-Abhängigkeit, kein Datenmodell-Eingriff; nur Darstellung.
- Robust: neue Modelle fallen automatisch in „Weitere" und gehen nicht verloren.

**Negativ / Grenzen**
- Die **Breadcrumb** auf Modellseiten zeigt weiterhin die technische App
  („Quartier-Buchung") statt der Sektion – bewusst nicht überschrieben (zu invasiv).
- Neue Modelle müssen für die saubere Einsortierung in `SECTIONS` ergänzt werden
  (sonst landen sie unter „Weitere").
