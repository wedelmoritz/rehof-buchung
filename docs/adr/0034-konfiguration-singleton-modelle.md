# 0034 – Konfiguration über Singleton-Modelle

## Status

Accepted (2026-06-26)

## Kontext

Viele Betriebs-Einstellungen sind global und einmalig: Genossenschaftsdaten, Regeln
für externe Gäste, Empfänger der Verwaltungs-Mails, Regelwerk-Defaults,
Fairness-Parameter. Sie sollen **im laufenden Betrieb** (ohne Deploy) änderbar sein,
zugleich aber **genau einmal** existieren und einfach abrufbar bleiben.

## Entscheidung

Solche Einstellungen werden als **Singleton-Modelle** mit einheitlichem Zugriff
`get_solo()` umgesetzt – statt in `settings.py`/Env.

- Beispiele: `shop.ShopConfig` (Genossenschaftsdaten + Mollie, ADR 0016/0017),
  `ExternalConfig` (`models.py:860`, ADR 0023), `OpsConfig` (`models.py` mit
  `get_solo` `:631`, Verwaltungs-Mails + Beds24-Schalter), `BookingPolicy`
  (`get_solo` `:737`, ADR 0009), `FairnessSimConfig` (`get_solo` `:1025`, ADR 0031).
- `get_solo()` liefert die eine Instanz oder legt sie an – robuster Zugriff ohne
  „existiert noch nicht“-Sonderfälle.
- Bedient im Backend (Admin) bzw. teils im Dashboard – die Werte sind so für die
  Verwaltung pflegbar, ohne Code/Env anzufassen.

## Betrachtete Alternativen

- **Werte in `settings.py`/Umgebungsvariablen:** nur per Deploy/Neustart änderbar;
  nicht für die Verwaltung zugänglich.
- **Eine generische Key/Value-Settings-Tabelle:** verliert Typisierung,
  Validierung und Admin-Komfort der Felder.
- **Mehrere Zeilen ohne Singleton-Garantie:** Mehrdeutigkeit, welcher Datensatz gilt.

## Konsequenzen

**Positiv**
- Betriebs-Einstellungen im laufenden Betrieb pflegbar, typisiert, validiert, mit
  Admin-Oberfläche.
- Einheitlicher, fehlerarmer Zugriff über `get_solo()`.

**Negativ**
- Die „genau eine Instanz“-Invariante liegt in der Anwendung (kein DB-Constraint).
- Konfiguration ist über mehrere Singletons verteilt – die Zuständigkeit muss klar
  dokumentiert bleiben.
