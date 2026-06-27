# 0029 – Kontoabgleich: Bank-Import (CSV/CAMT) mit automatischer Verbuchung

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 13 – Rechnungen, Zahlung & Steuer](../FACHKONZEPT.md#13-rechnungen-zahlung--steuer).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Überweisungen müssen den offenen Rechnungen zugeordnet werden. Manuelles Abhaken
ist mühsam und fehleranfällig. Banken liefern unterschiedliche Auszugsformate.
Datei-Uploads von außen sind ein Sicherheitsrisiko (XML-Entity-Expansion, große
Dateien).

## Entscheidung

Auszug-Upload mit **Parser je Format** und automatischer Verbuchung **eindeutiger**
Treffer, plus Upload-Härtung.

- **Parser** in `shop/bankimport.py` mit normalisiertem `ParsedTxn`: `parse_csv`
  (flexibel über Header-Stichwörter), `parse_camt` (CAMT.053-XML), Dispatch über
  `parse(data, fmt)`. MT940 ist über dieselbe Schnittstelle leicht ergänzbar.
- **Verbuchung** in `shop/reconcile.py`: `import_bank_statement` legt
  `BankImport`/`BankTransaction` an (Dedup über `fingerprint`) und verbucht
  **eindeutige** Treffer automatisch (Rechnungsnummer im Verwendungszweck + exakter
  Betrag) → `confirm_invoice` (Status `confirmed`) + In-App-/E-Mail-Benachrichtigung.
  Nicht eindeutige Eingänge bleiben offen (manuell in `BankTransactionAdmin`).
- **Härtung:** Upload auf **10 MB** begrenzt; der CAMT-Parser lehnt `DOCTYPE`/
  `ENTITY` ab (Schutz vor Entity-Expansion). Bedient im Dashboard (ADR 0018).

## Betrachtete Alternativen

- **Nur manuelle Zuordnung:** zu aufwendig bei vielen Rechnungen.
- **Automatik auch bei mehrdeutigen Treffern:** Risiko von Fehlverbuchungen; deshalb
  nur **eindeutige** Treffer automatisch.
- **Externe Banking-API/Aggregator:** zusätzliche Abhängigkeit/Kosten; CSV/CAMT-Export
  reicht für ein kleines Team.

## Konsequenzen

**Positiv**
- Routine-Eingänge werden automatisch verbucht und benachrichtigt.
- Formate erweiterbar (MT940) ohne Umbau; Dedup verhindert Doppelimporte.
- Gehärtete Uploads (Größe, XXE).

**Negativ**
- Mehrdeutige/abweichende Eingänge bleiben Handarbeit.
- Heuristik (Nummer + Betrag) muss zu den realen Verwendungszwecken passen.
