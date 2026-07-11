"""Füllt das laufende Kalenderjahr **dicht** mit Buchungen bestehender Mitglieder.

Test-/Demo-Werkzeug, um zu sehen, wie der Belegungsplan (BL-Kalender) bei hoher
Auslastung aussieht: die Quartiere werden Zeile für Zeile mit Aufenthalten belegt
(back-to-back, nur wenige Lücken), und zwar von Mitgliedern, die noch Tage-Budget
haben – so füllen die meisten Mitglieder ihr Kontingent voll aus, manche bis auf
wenige Tage.

**Zusätzlich** legt das Kommando – sofern nicht `--no-wishes` – für die
**Jahres-Losung des Folgejahres** genügend **sinnvolle Wünsche** an: ein Teil
irgendwohin verstreut, der größere Teil geballt auf die begehrten Zeiten (Ostern,
1. Mai, Himmelfahrt/Brückentag, Pfingsten, Sommer-/Herbstferien, Tag der Deutschen
Einheit, Weihnachten) und verlängerte Wochenenden. So gibt es realistische
Kollisionen für einen aussagekräftigen Los-Testlauf. Die dafür angelegte Periode
trägt die Marke `WISH_FILL_MARKER` im Namen (Aufräum-Anker).

**Regeltreu:** keine Doppelbelegung (Quartier + Mitglied nie gleichzeitig zweimal),
Quartier-Saison, Mindestnächte je Zeitraum und das Tage-Budget je Mitglied werden
eingehalten; Wünsche halten Saison + Mindestnächte ein und bleiben im halben
Wunsch-Budget des Mitglieds. Die angelegten Buchungen tragen die interne Notiz
`FILL_MARKER`, sodass `clear_filled_bookings` sie (und die Wunsch-Periode) gezielt
wieder entfernen kann.

    python manage.py fill_bookings              # laufendes Jahr + Wünsche fürs Folgejahr
    python manage.py fill_bookings --year 2026  # bestimmtes Jahr
    python manage.py fill_bookings --no-wishes  # nur Buchungen, keine Wünsche
    python manage.py clear_filled_bookings      # alles wieder entfernen
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking import services as svc
from booking.management.commands.seed_demo import _easter
from booking.models import (
    Allocation, BookingPeriod, ExternalBooking, Member, Quarter, QuarterBlock,
    Wish,
)

# Interne Markierung der Test-Füllung (BL-only Notiz) – Ansatzpunkt fürs Aufräumen.
FILL_MARKER = "Testfüllung (fill_bookings)"
# Marke im NAMEN der angelegten Wunsch-Periode – so kann clear_filled_bookings die
# Test-Wünsche (samt Periode) sicher wieder entfernen, ohne echte Losungsdaten
# anzufassen.
WISH_FILL_MARKER = "Testfüllung fill_bookings"

_LENGTHS = [2, 3, 3, 4, 4, 5, 7, 7, 10, 14]   # gewichtete Aufenthaltslängen
# Wunsch-Längen (Nächte): verlängerte Wochenenden häufig, ein paar lange Aufenthalte.
_WISH_LENGTHS = [2, 3, 3, 3, 4, 4, 5, 7, 7, 10, 14]


def _public_holidays(year: int) -> dict[str, date]:
    """Gesetzliche Feiertage in Brandenburg (Hof-Region) – feste + bewegliche
    (aus dem Osterdatum abgeleitet). Grundlage für die begehrten Wunsch-Fenster."""
    e = _easter(year)
    return {
        "Neujahr": date(year, 1, 1),
        "Karfreitag": e - timedelta(days=2),
        "Ostersonntag": e,
        "Ostermontag": e + timedelta(days=1),
        "Tag der Arbeit": date(year, 5, 1),
        "Christi Himmelfahrt": e + timedelta(days=39),
        "Pfingstsonntag": e + timedelta(days=49),
        "Pfingstmontag": e + timedelta(days=50),
        "Tag der Deutschen Einheit": date(year, 10, 3),
        "Reformationstag": date(year, 10, 31),
        "1. Weihnachtstag": date(year, 12, 25),
        "2. Weihnachtstag": date(year, 12, 26),
    }


def _wish_windows(year: int) -> list[tuple[str, date, date, int, int, int]]:
    """Begehrte Anreise-Fenster fürs Losjahr: (Name, frühester Anreisetag, spätester
    Anreisetag, min. Nächte, max. Nächte, Gewicht). Das Gewicht steuert, wie stark
    sich die Wünsche dort ballen."""
    H = _public_holidays(year)
    e = H["Ostersonntag"]
    return [
        # Ostern: Karfreitag bis kurz vor Ostermontag; gern die ganze Woche.
        ("Ostern", e - timedelta(days=3), e - timedelta(days=1), 3, 7, 4),
        # 1.-Mai-Wochenende.
        ("1. Mai", H["Tag der Arbeit"] - timedelta(days=3), H["Tag der Arbeit"], 2, 4, 2),
        # Himmelfahrt (Do) + Brückentag (Fr) → verlängertes Wochenende.
        ("Himmelfahrt", H["Christi Himmelfahrt"] - timedelta(days=1),
         H["Christi Himmelfahrt"], 3, 4, 3),
        # Pfingsten.
        ("Pfingsten", H["Pfingstsonntag"] - timedelta(days=2),
         H["Pfingstsonntag"], 3, 4, 3),
        # Sommerferien BB (grob Anfang Juli – Mitte August), lange Aufenthalte.
        ("Sommerferien", date(year, 7, 1), date(year, 8, 20), 7, 14, 5),
        # Herbstferien BB (grob Mitte Oktober).
        ("Herbstferien", date(year, 10, 13), date(year, 10, 25), 4, 7, 2),
        # Tag der Deutschen Einheit.
        ("Einheit", H["Tag der Deutschen Einheit"] - timedelta(days=3),
         H["Tag der Deutschen Einheit"], 2, 4, 2),
        # Weihnachten / Jahreswechsel.
        ("Weihnachten", date(year, 12, 21), date(year, 12, 29), 4, 7, 3),
    ]


def _random_friday(rng: random.Random, year: int) -> date:
    """Ein zufälliger Freitag (verlängertes Wochenende) außerhalb der Feiertags-
    Ballung – grob Februar bis November."""
    d = date(year, rng.randint(2, 11), rng.randint(1, 28))
    return d + timedelta(days=(4 - d.weekday()) % 7)   # nächster Freitag


class Command(BaseCommand):
    help = ("Füllt das laufende Kalenderjahr dicht mit Buchungen bestehender "
            "Mitglieder (Test/Demo). Rückgängig: clear_filled_bookings.")

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None,
                            help="Kalenderjahr (Default: laufendes Jahr).")
        parser.add_argument("--seed", type=int, default=20260705,
                            help="Zufalls-Seed (reproduzierbar).")
        parser.add_argument(
            "--leave-days", type=int, default=4,
            help="Manche Mitglieder behalten bis zu so viele Tage übrig "
                 "(bei ~30 %% der Mitglieder, Default 4).")
        parser.add_argument(
            "--no-wishes", action="store_true",
            help="KEINE Test-Wünsche für die Folgejahres-Losung anlegen.")
        parser.add_argument(
            "--wish-year", type=int, default=None,
            help="Losjahr für die Test-Wünsche (Default: Buchungsjahr + 1).")
        parser.add_argument(
            "--force-wishes", action="store_true",
            help="Wünsche auch anlegen, wenn für das Losjahr bereits eine ECHTE "
                 "(nicht als Testfüllung markierte) Periode existiert – Vorsicht: "
                 "diese Wünsche lassen sich dann nicht per clear_filled_bookings "
                 "entfernen.")

    def handle(self, *args, **opts):
        year = opts["year"] or date.today().year
        rng = random.Random(opts["seed"])
        y0, y1 = date(year, 1, 1), date(year, 12, 31)
        last = y1 + timedelta(days=1)                 # exklusive obere Grenze

        members = [m for m in Member.objects.filter(is_external=False)
                   .prefetch_related("shares")
                   if m.can_book and m.annual_night_budget > 0]
        quarters = list(Quarter.objects.filter(active=True))
        if not members or not quarters:
            self.stdout.write(self.style.WARNING(
                "Keine buchungsberechtigten Mitglieder oder aktiven Quartiere."))
            return

        # Belegung je Quartier + belegte Tage je Mitglied aus dem BESTAND aufbauen,
        # damit die Füllung nirgends kollidiert (in-memory statt DB-Abfrage je Test).
        occ: dict[int, set[date]] = defaultdict(set)
        mdays: dict[int, set[date]] = defaultdict(set)

        def _span(add, s, e):
            d = s
            while d < e:
                add(d)
                d += timedelta(days=1)

        for a in Allocation.objects.filter(start__lt=last, end__gt=y0):
            _span(occ[a.quarter_id].add, max(a.start, y0), min(a.end, last))
            _span(mdays[a.member_id].add, max(a.start, y0), min(a.end, last))
        for b in ExternalBooking.objects.filter(
                status=ExternalBooking.CONFIRMED, start__lt=last, end__gt=y0):
            _span(occ[b.quarter_id].add, max(b.start, y0), min(b.end, last))
        for qb in QuarterBlock.objects.filter(start__lt=last, end__gt=y0):
            _span(occ[qb.quarter_id].add, max(qb.start, y0), min(qb.end, last))

        remaining = {m.id: m.nights_remaining_in_year(year) for m in members}
        # ~30 % der Mitglieder behalten ein paar Tage übrig (realistischer Rest).
        keep = {m.id: (rng.randint(1, max(1, opts["leave_days"]))
                       if rng.random() < 0.3 else 0) for m in members}

        def q_free(qid, s, e):
            d = s
            while d < e:
                if d in occ[qid]:
                    return False
                d += timedelta(days=1)
            return True

        def m_free(mid, s, e):
            d = s
            while d < e:
                if d in mdays[mid]:
                    return False
                d += timedelta(days=1)
            return True

        def free_span(qid, s):
            """Länge des freien Blocks im Quartier ab `s` bis zur nächsten belegten
            Nacht bzw. bis Jahresende."""
            n, d = 0, s
            while d < last and d not in occ[qid]:
                n += 1
                d += timedelta(days=1)
            return n

        created = nights = 0
        # Jedes Quartier von vorn nach hinten dicht belegen (back-to-back). So
        # entsteht hohe Auslastung UND die Budgets werden aufgebraucht.
        for q in quarters:
            cursor = y0
            while cursor < last:
                if cursor in occ[q.id]:               # schon belegt → weiter
                    cursor += timedelta(days=1)
                    continue
                span = free_span(q.id, cursor)
                if span < 2:                          # zu kleine Lücke → lassen
                    cursor += timedelta(days=span or 1)
                    continue
                pool = [m for m in members
                        if remaining[m.id] - keep[m.id] >= 2
                        and m_free(m.id, cursor, cursor + timedelta(days=2))]
                rng.shuffle(pool)
                placed = False
                for m in pool:
                    budget = remaining[m.id] - keep[m.id]
                    length = min(budget, span, rng.choice(_LENGTHS))
                    if length < 2:
                        continue
                    end = cursor + timedelta(days=length)
                    # Saison + Mindestnächte für diesen Zeitraum einhalten.
                    if not svc._in_season_range(q, cursor, end):
                        continue
                    need = svc.min_nights_for_range(cursor, end)
                    if length < need:
                        if need <= min(budget, span):
                            length = need
                            end = cursor + timedelta(days=length)
                        else:
                            continue
                    if not m_free(m.id, cursor, end):
                        continue
                    lo = q.min_occupancy or 1
                    hi = max(lo, q.max_occupancy or lo)
                    Allocation.objects.create(
                        member=m, quarter=q, start=cursor, end=end,
                        persons=rng.randint(lo, hi), source="spontaneous",
                        provisional=False, internal_note=FILL_MARKER,
                        membership=m.membership_for())
                    _span(occ[q.id].add, cursor, end)
                    _span(mdays[m.id].add, cursor, end)
                    remaining[m.id] -= length
                    created += 1
                    nights += length
                    cursor = end
                    placed = True
                    break
                if not placed:                        # niemand passte → 1 Tag Lücke
                    cursor += timedelta(days=1)

        full = sum(1 for m in members if remaining[m.id] <= keep[m.id])
        left = [remaining[m.id] for m in members if remaining[m.id] > keep[m.id]]
        self.stdout.write(self.style.SUCCESS(
            f"{created} Buchungen ({nights} Nächte) im Jahr {year} angelegt."))
        self.stdout.write(
            f"{full}/{len(members)} Mitglieder haben ihr Budget (bis auf Rest) "
            f"ausgeschöpft.")
        if left:
            self.stdout.write(
                f"Bei {len(left)} Mitgliedern blieben noch Tage übrig "
                f"(im Schnitt {sum(left) / len(left):.1f}, max {max(left)}) – "
                f"z. B. weil alle passenden Quartiere schon belegt waren.")
        if not opts["no_wishes"]:
            self._seed_wishes(rng, members, quarters, opts, booking_year=year)

        self.stdout.write(
            "BL-Kalender ansehen unter „Übersicht“/Verwaltung. Rückgängig: "
            "python manage.py clear_filled_bookings"
            + ("" if year == date.today().year else f" --year {year}"))

    def _seed_wishes(self, rng, members, quarters, opts, *, booking_year):
        """Legt für die Folgejahres-Losung genügend sinnvolle, eingereichte Wünsche
        an: ~60 % geballt auf die begehrten Feiertags-/Ferien-Fenster, ~20 % auf
        verlängerte Wochenenden, ~20 % verstreut. Saison + Mindestnächte werden
        gewahrt, jeder Wunsch bleibt im halben Wunsch-Budget des Mitglieds."""
        wish_year = opts["wish_year"] or (booking_year + 1)
        existing = BookingPeriod.objects.filter(target_year=wish_year).first()
        is_fill = bool(existing and WISH_FILL_MARKER in (existing.name or ""))
        if existing and not is_fill and not opts["force_wishes"]:
            self.stdout.write(self.style.WARNING(
                f"Für {wish_year} existiert bereits eine echte Periode "
                f"('{existing.name}') – Test-Wünsche werden NICHT ergänzt "
                f"(mit --force-wishes erzwingbar)."))
            return

        if existing:
            period = existing
            if is_fill:                       # eigene Test-Periode idempotent neu füllen
                Wish.objects.filter(period=period).delete()
        else:
            period = BookingPeriod.objects.create(
                name=f"Jahres-Losung {wish_year} ({WISH_FILL_MARKER})",
                target_year=wish_year,
                start=date(wish_year, 1, 1), end=date(wish_year + 1, 1, 1),
                wishlist_open=date.today(),
                wishlist_close=date.today() + timedelta(days=21),
                draw_at=timezone.now() + timedelta(days=22),
                status=BookingPeriod.WISHES_OPEN,
            )

        windows = _wish_windows(wish_year)
        weighted = [w for w in windows for _ in range(w[5])]   # Gewichtung
        now = timezone.now()
        y_end = date(wish_year + 1, 1, 1)
        created = wishers = 0
        for m in members:
            budget = max(2, m.wish_night_budget)
            remaining = budget
            seen: set[tuple] = set()
            prio = 0
            for _ in range(rng.randint(1, 4)):
                if remaining < 2:
                    break
                r = rng.random()
                if r < 0.60:                  # geballt auf begehrte Fenster
                    _, lo, hi, mn, mx, _w = rng.choice(weighted)
                    start = lo + timedelta(days=rng.randint(0, max(0, (hi - lo).days)))
                    length = rng.randint(mn, mx)
                elif r < 0.80:                # verlängertes Wochenende (Fr-Anreise)
                    start = _random_friday(rng, wish_year)
                    length = rng.choice([2, 3])
                else:                         # irgendwohin verstreut
                    start = date(wish_year, 1, 1) + timedelta(days=rng.randint(20, 330))
                    length = rng.choice(_WISH_LENGTHS)
                length = min(length, remaining)
                if length < 2:
                    continue
                end = start + timedelta(days=length)
                if end > y_end:               # nicht über das Losjahr hinaus
                    continue
                # ein in diesem Zeitraum saisonal buchbares Quartier wählen.
                q = next((c for c in rng.sample(quarters, len(quarters))
                          if svc._in_season_range(c, start, end)), None)
                if q is None:
                    continue
                # Mindestnächte je Zeitraum (Saison-Regel) wahren, sofern im Budget.
                need = svc.min_nights_for_range(start, end)
                if length < need:
                    if need <= remaining and start + timedelta(days=need) <= y_end:
                        length, end = need, start + timedelta(days=need)
                    else:
                        continue
                key = (q.id, start, end)
                if key in seen:
                    continue
                seen.add(key)
                prio += 1
                Wish.objects.create(
                    period=period, member=m, priority=prio, quarter=q,
                    start=start, end=end, added_at=now,
                    membership=m.membership_for(),
                )
                remaining -= length
                created += 1
            if prio:
                wishers += 1

        self.stdout.write(self.style.SUCCESS(
            f"{created} Wünsche von {wishers} Mitgliedern für die Losung "
            f"{wish_year} angelegt (Periode „{period.name}“, im Lostopf)."))
