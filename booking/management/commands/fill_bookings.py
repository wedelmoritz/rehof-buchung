"""Füllt das laufende Kalenderjahr **dicht** mit Buchungen bestehender Mitglieder.

Test-/Demo-Werkzeug, um zu sehen, wie der Belegungsplan (BL-Kalender) bei hoher
Auslastung aussieht: die Quartiere werden Zeile für Zeile mit Aufenthalten belegt
(back-to-back, nur wenige Lücken), und zwar von Mitgliedern, die noch Tage-Budget
haben – so füllen die meisten Mitglieder ihr Kontingent voll aus, manche bis auf
wenige Tage.

**Regeltreu:** keine Doppelbelegung (Quartier + Mitglied nie gleichzeitig zweimal),
Quartier-Saison, Mindestnächte je Zeitraum und das Tage-Budget je Mitglied werden
eingehalten. Die angelegten Buchungen tragen die interne Notiz `FILL_MARKER`, sodass
`clear_filled_bookings` sie gezielt wieder entfernen kann.

    python manage.py fill_bookings              # laufendes Jahr, voll
    python manage.py fill_bookings --year 2026  # bestimmtes Jahr
    python manage.py clear_filled_bookings      # alles wieder entfernen
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from booking import services as svc
from booking.models import (
    Allocation, ExternalBooking, Member, Quarter, QuarterBlock,
)

# Interne Markierung der Test-Füllung (BL-only Notiz) – Ansatzpunkt fürs Aufräumen.
FILL_MARKER = "Testfüllung (fill_bookings)"

_LENGTHS = [2, 3, 3, 4, 4, 5, 7, 7, 10, 14]   # gewichtete Aufenthaltslängen


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
        self.stdout.write(
            "BL-Kalender ansehen unter „Übersicht“/Verwaltung. Rückgängig: "
            "python manage.py clear_filled_bookings"
            + ("" if year == date.today().year else f" --year {year}"))
