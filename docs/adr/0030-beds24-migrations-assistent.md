# 0030 – Beds24-Migrations-Assistent: einmaliger CSV-Import mit manuellem Abgleich

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 12 – Externe Gäste](../FACHKONZEPT.md#12-externe-gäste)
> (Migration bestehender Buchungen). Diese ADR hält die *technische* Entscheidung und
> ihre Abwägungen fest; die Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Beim Umzug vom bisherigen System (Beds24) müssen bestehende Buchungen übernommen
werden. Gäste haben ihre Namen bei Beds24 frei eingetippt – ein exakter Abgleich mit
den Mitgliedern/Quartieren ist nicht möglich. Falsch zugeordnete Buchungen wären
schädlich, deshalb darf nichts blind automatisch übernommen werden.

## Entscheidung

Ein **Assistent** (`beds24_import`, `/verwaltung/beds24-import/`, **nur Admin**) mit
CSV-Upload, Vorschlägen und **manueller** Bestätigung.

- **Reine Logik** in `booking/beds24.py` (Django-frei, testbar `tests/test_beds24.py`):
  flexibles CSV-Parsen (`parse_csv`, Header-Stichwörter) + unscharfer Namensabgleich
  (`name_score`, `rank_candidates`).
- **Service** `services.beds24_stage` (parst, legt `Beds24Import`/`Beds24ImportRow`
  an, hängt Vorschläge Mitglied/Quartier an), `beds24_apply` (übernimmt abgeglichene
  Zeilen als `Allocation`, Quelle **„import“**, **ohne** Rechnung – diese Buchungen
  sind bereits bezahlt; idempotent/dedupe), `beds24_create_member` (legt für nicht
  zuordenbare Gäste ein Mitglied + Anteil an).
- **Abschaltbar:** über `OpsConfig.beds24_import_enabled` – ausgeschaltet ist der
  Assistent im Dashboard ausgeblendet und gesperrt (auch für Admins), da er nur beim
  Umzug gebraucht wird und echte Buchungen anlegt.

## Betrachtete Alternativen

- **Automatischer Voll-Import:** Fehlzuordnungen bei frei getippten Namen → falsche
  Buchungen; verworfen.
- **Beds24-API-Anbindung:** dauerhafte Kopplung an ein System, das gerade abgelöst
  wird – unnötiger Aufwand für eine Einmal-Migration.
- **Reiner manueller Nachbau:** zu fehleranfällig/aufwendig bei vielen Buchungen.

## Konsequenzen

**Positiv**
- Sichere Übernahme mit menschlicher Kontrolle; idempotent/dedupliziert.
- Nach dem Umzug abschaltbar → keine dauerhafte Angriffs-/Fehlfläche.

**Negativ**
- Manueller Abgleich kostet Zeit (einmalig, gewollt).
- Importierte Buchungen tragen bewusst **keine** Rechnung – diese Annahme („bereits
  bezahlt“) muss beim Umzug stimmen.
