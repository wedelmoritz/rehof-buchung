# 0044 – Web-Push (mobil) und gezieltes Offline-Verhalten

## Status

Accepted (2026-06-27)

## Kontext

Die App ist eine PWA (ADR 0035) – installierbar, mit Service Worker und
network-first-Offline-Fallback. Zwei Lücken blieben:

1. **Benachrichtigungen erreichen das Handy nur, wenn die App offen ist.** Wichtige
   Ereignisse (Losergebnis, Wartelisten-Platz frei, Rechnung) gibt es als In-App-
   `Notification` und E-Mail, aber kein Push aufs Gerät bei geschlossener App.
2. **Offline pauschal:** Der Service Worker lieferte offline die zuletzt besuchte
   Seite aus dem Cache – auch für **Buchen/Wunsch**, wo veraltete Verfügbarkeiten
   gefährlich sind (man könnte auf Basis alter „frei"-Stände buchen wollen).

## Entscheidung

**Web-Push** über das Standard-Web-Push-Protokoll (VAPID), gekoppelt an die
**bestehenden In-App-Benachrichtigungen**:

- Modell `PushSubscription` (ein Abo je Browser/Gerät, am `Member`).
- Ein **`post_save`-Signal auf `Notification`** stellt jede neue Benachrichtigung
  zusätzlich als Push zu – zentral, statt an jeder Notification-Quelle. Der Versand
  läuft über `transaction.on_commit` (kein Netz-Call in offener Transaktion) und ist
  **best-effort** (`services.send_web_push`, pywebpush): Fehler eines Geräts kippen
  weder den Request noch andere Zustellungen; tote Abos (404/410) werden entfernt.
- **VAPID-Schlüssel via Env** (`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/
  `VAPID_ADMIN_EMAIL`). **Ohne Schlüssel ist Push aus** (`settings.PUSH_ENABLED`) –
  kein Zwang, analog zum Mollie-Sandbox-Default (ADR 0017). Erzeugung per
  `python manage.py vapid_keys`.
- Client: Service-Worker-`push`/`notificationclick`; Opt-in-Knopf im Profil
  („Benachrichtigungen aktivieren", `window.__rehofPush`); An-/Abmeldung gegen
  `push_subscribe`/`push_unsubscribe`.

**Gezieltes Offline-Verhalten** im Service Worker (`rehof-v2`):

- **Buchen/Wunsch** (`/buchen/`, `/wunschliste/`, `/extern/buchen/`): offline **keine**
  Cache-Kopie, sondern eine klare Seite „Buchen braucht eine Verbindung". So bucht
  niemand auf Basis veralteter Verfügbarkeiten.
- **Alles andere** (Übersicht, **Hofladen-Katalog**, Meine Buchungen, Rechnungen,
  Profil, Hilfe): network-first → Cache-Fallback, also offline durchblätterbar
  (zuletzt geladener Stand).
- **Offline-Warenkorb (Hofladen):** Der Warenkorb lässt sich **ohne Netz befüllen und
  bearbeiten** (vor Ort im Hofladen). „+ Warenkorb" landet offline in einem lokalen
  Korb (`localStorage`, Engine `window.__offlineCart` in `base.html`); ein Panel
  „Offline-Warenkorb" auf der Hofladen-Seite zeigt die Artikel mit Mengen-/Lösch-
  Bearbeitung. **Beim Wiederverbinden** (`online`-Event oder beim nächsten Online-
  Aufruf) werden die Positionen automatisch über den bestehenden `add`-Endpoint an
  den Server-Warenkorb übertragen und der lokale Korb geleert. **Nur der Checkout**
  (Einkauf bestätigen, Rechnung, Bezahlen) bleibt netzpflichtig – „Zur Kasse" ist
  offline bzw. bei noch nicht übertragenem Offline-Korb gesperrt (Hinweis-Toast,
  vorher synchronisieren). Rein clientseitig, keine Server-Änderung.
- **Andere schreibende Aktionen offline** (POST: Buchen, Wunsch, Checkout) werden
  schon im Browser abgefangen: der AJAX-Layer zeigt einen Hinweis-Toast „Offline –
  diese Aktion braucht eine Internetverbindung." statt eines stillen Fehlschlags.

## Betrachtete Alternativen

- **Push über einen Dienst (Firebase/OneSignal):** verworfen – Fremd-Abhängigkeit und
  Datenabfluss; das offene Web-Push-Protokoll mit VAPID genügt und bleibt in der
  eigenen Hand.
- **Push entkoppelt über eine Outbox** (wie E-Mail, ADR 0027): erwogen, aber für die
  Größe unnötig. `on_commit` + best-effort reicht; eine spätere Auslagerung in eine
  Push-Outbox bleibt möglich (dokumentierte Grenze).
- **Eigene „Push-aktiviert"-Einstellung am Member:** verworfen – das Vorhandensein
  eines `PushSubscription` IST der Opt-in; die E-Mail-Abschaltung (`email_opt_in`)
  bleibt davon unberührt.
- **Offline alles aus dem Cache (auch Buchen):** verworfen – Verfügbarkeiten sind
  zeitkritisch; ein veralteter Kalender lädt zu Fehlbuchungen ein.
- **Hofladen-Checkout offline:** verworfen – Rechnungsstellung/Bezahlung brauchen das
  Netz und sind verbindlich. Der **Warenkorb** dagegen ist offline befüllbar und wird
  beim Wiederverbinden synchronisiert (vor Ort einkaufen, später abrechnen).
- **Offline-Korb serverseitig pro Gerät spiegeln:** verworfen – unnötige Server-/
  Modell-Komplexität; ein lokaler `localStorage`-Korb mit Replay über den vorhandenen
  `add`-Endpoint genügt. Grenze: rein lokal, nicht geräteübergreifend, und das
  Mengen-Editieren am Server-Korb bleibt offline gesperrt (nur der lokale Korb ist
  offline bearbeitbar).

## Konsequenzen

**Positiv**
- Wichtige Hinweise erreichen das Handy auch bei geschlossener App.
- Eine zentrale Naht (Notification-Signal) deckt alle Benachrichtigungs-Quellen ab.
- Offline klar und sicher: lesbarer Katalog, aber keine Buchung auf altem Stand.

**Negativ / offen (TBD)**
- **Synchroner Best-effort-Versand** (on_commit): bei vielen Abos/langsamem Push-Dienst
  minimale Zusatzlatenz nach dem Commit; eine Push-Outbox wäre der nächste Schritt.
- **iOS:** Web-Push gibt es erst ab installierter PWA (iOS 16.4+); der Profil-Knopf
  weist darauf hin, ist aber von Browser/OS abhängig.
- **Abo-Aufbewahrung:** tote Abos werden beim Versand entfernt; bei der Anonymisierung
  (ADR 0043) werden die Abos des Mitglieds gelöscht. Eine Token-/Endpoint-Rotation ist
  nicht nötig (der Browser erneuert das Abo selbst).
- `pywebpush` ist eine neue Abhängigkeit (nur genutzt, wenn VAPID-Keys gesetzt sind).
