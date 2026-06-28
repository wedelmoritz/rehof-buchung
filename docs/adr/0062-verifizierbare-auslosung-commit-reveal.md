# 0062 – Verifizierbare Auslosung (Commit-Reveal des Seeds)

## Status

Accepted (2026-06-28)

> **Fachlicher Bezug:** Losverfahren siehe [Fachkonzept – Losverfahren](../FACHKONZEPT.md).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest.

## Kontext

Das Losverfahren ist bereits **über einen Seed reproduzierbar** und statistisch als
fair nachgewiesen (Monte-Carlo, Chi-Quadrat, Wilson-KI – Seite „Fairness-Nachweis").
Eine Lücke blieb: Mitglieder müssen darauf **vertrauen**, dass die Verwaltung den
Seed nicht *nach* Sichtung der Wünsche zu Gunsten einzelner wählt („seed grinding").
Ziel: dieses Vertrauen durch ein **nachprüfbares** Verfahren ersetzen – passend zur
Leitlinie Transparenz/Gemeinschaft und zum schlanken, Django-freien Kern.

## Entscheidung

Ein **Commit-Reveal**-Verfahren um den vorhandenen Seed (Stand der Technik bei
„provably fair"-Systemen), **rein intern** erzeugt (kein externer Beacon – bewusst,
um Outbound-Abrufe/Ausfallpfade zu vermeiden):

1. **Commit (vor der Ziehung):** Sobald die Wünsche öffnen, erzeugt
   `services.ensure_seed_commit` einen **kryptografisch sicheren** Seed
   (`secrets.randbits(63)`, passt in `BigInteger`) und veröffentlicht **nur dessen
   SHA-256-Prüfsumme** (`BookingPeriod.seed_commit`, `seed_committed_at`). Der Seed
   selbst bleibt geheim. Ausgelöst vom Cron (`run_due_lotteries`) beim Erreichen von
   `wishes_open`; `run_period_lottery` stellt den Commit zusätzlich sicher (Fallback).
2. **Ziehung:** Es wird **immer der committete Seed** genutzt – ein abweichend
   übergebener Seed greift nur, solange noch keiner committet ist (sonst passte die
   Prüfsumme nicht). Im Backend sind `seed`/`seed_commit` **read-only**.
3. **Reveal (nach bestätigter Ziehung):** Der Seed wird offengelegt (Ergebnisseite).
   Jede:r bildet `SHA-256(seed)` und vergleicht mit der zuvor veröffentlichten
   Prüfsumme; mit Seed + eingereichten Wünschen lässt sich die Ziehung über das
   offene `booking/lottery.py` exakt reproduzieren.

**Reine Logik:** `lottery.seed_commitment(seed)` / `verify_commitment(seed, commit)`
(Django-frei, in `tests/` getestet). **Verifikation:** `services.verify_period_lottery`
(prüft Prüfsumme **und** reproduziert die Zuteilungen aus dem Karma-Schnappschuss +
Lostopf) und das Kommando `manage.py verify_lottery <id> | --all`.
**UI (schlank, kein JS):** veröffentlichte Prüfsumme auf der Wunschliste (eingeklappt)
und auf der Ergebnisseite (`<details>`), Erklär-Abschnitt 3 auf „Fairness-Nachweis".

## Betrachtete Alternativen

- **Externer Zufalls-Beacon (drand/NIST) beimischen:** stärkerer Unparteilichkeits-
  Beweis, aber Outbound-Abruf + Ausfall-/Verfügbarkeits-Handling. Für eine schlanke,
  selbst gehostete App bewusst verworfen (kann später additiv ergänzt werden).
- **Mitglied-beigesteuerter Seed-Teil:** mehr Prozess/Abstimmung; später möglich.
- **Inputs (Parteien/Wünsche) vollständig snapshotten:** maximale Offline-Replay-
  Fähigkeit, aber zusätzlicher Speicher/Redundanz. Wir reproduzieren stattdessen aus
  dem `karma_snapshot` + dem nach Wunschschluss unveränderlichen Lostopf (read-only).
- **Salt/Pepper am Commit:** Bei 63-Bit-CSPRNG-Seed ist ein Preimage praktisch
  unmöglich; und ein früher bekannter Seed schadet wegen der **Strategiesicherheit**
  nicht (ehrliche Wünsche bleiben optimal). Daher unnötig.

## Konsequenzen

**Positiv**
- Nachprüfbar, dass der Seed **vor** den Einträgen feststand – ersetzt Vertrauen
  durch Mathematik; stärkt Transparenz & Gemeinschaftsvertrauen.
- Kein neuer externer Dienst, keine neue Abhängigkeit (`hashlib`/`secrets` aus der
  Stdlib); zwei kleine Felder + read-only im Backend.

**Negativ / Grenzen**
- Der Commit muss **vor** den Einträgen erfolgen (beim Öffnen der Wünsche). Eine
  manuell „von Hand" angelegte Periode, deren Wünsche schon offen sind, committet
  spätestens beim nächsten Cron-Lauf – im engen Fenster davor wäre die Garantie
  schwächer (dokumentiert; der Cron läuft alle 15 Min).
- Voll-Reproduktion setzt voraus, dass der Lostopf nach Wunschschluss unverändert
  bleibt (gilt im normalen Ablauf). Ein späterer Input-Snapshot wäre die natürliche
  Härtung.
