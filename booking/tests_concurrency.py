"""Korrektheit unter Gleichzeitigkeit (Race-Tests für die Spontanbuchung).

Diese Tests beweisen, dass die Buchung auch dann konsistent bleibt, wenn VIELE
Mitglieder im selben Moment buchen – insbesondere **denselben** Slot. Tragende
Mechanik ist die Zeilensperre `SELECT … FOR UPDATE` auf der Quartier-Zeile in
`services.book_spontaneous` (in `transaction.atomic`).

Wichtig: echte Nebenläufigkeit braucht ECHTE Verbindungen + COMMITs, daher
`TransactionTestCase` (nicht `TestCase`) und **mehrere Threads**. Auf SQLite ist
`SELECT FOR UPDATE` wirkungslos und parallele Schreibzugriffe werden ohnehin
serialisiert – die Sperre lässt sich dort nicht sinnvoll prüfen. Die Tests
überspringen deshalb alles außer PostgreSQL (läuft im CI-Integrationsjob).
"""
from __future__ import annotations

import threading
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import TransactionTestCase

from booking import services as svc
from booking.models import (
    Allocation, BookingPeriod, EquivalenceClass, Member, Membership, Quarter,
    Share,
)

YEAR = date.today().year + 1


def _member(name):
    u = User.objects.create_user(username=name, password="x" * 12)
    m = Member.objects.create(user=u, display_name=name)
    ms = Membership.objects.create(eg_number=f"EG-{name}", label=name,
                                   annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=m, night_budget=50,
                         wish_night_budget=25)
    return m


class BookingRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Race-Test braucht PostgreSQL (Zeilensperre).")
        self.eq = EquivalenceClass.objects.create(name="K")
        BookingPeriod.objects.create(
            name="frei", target_year=YEAR, start=date(YEAR, 1, 1),
            end=date(YEAR + 1, 1, 1), status=BookingPeriod.FREE_BOOKING)

    def _run_parallel(self, calls):
        """Führt `calls` (Liste von 0-arg-Funktionen) gleichzeitig aus. Jeder
        Thread schließt seine DB-Verbindung sauber. Liefert die Ergebnisliste."""
        results = [None] * len(calls)
        barrier = threading.Barrier(len(calls))

        def worker(i, fn):
            barrier.wait()                       # alle zugleich losschicken
            try:
                results[i] = fn()
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i, fn))
                   for i, fn in enumerate(calls)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_gleicher_slot_genau_ein_gewinner(self):
        """20 Mitglieder buchen GLEICHZEITIG dasselbe Quartier + Datum →
        genau EINE Buchung entsteht, kein Doppel; die anderen werden sauber
        abgewiesen (kein Crash)."""
        q = Quarter.objects.create(name="Hütte", eq_class=self.eq,
                                   min_occupancy=1, max_occupancy=4)
        members = [_member(f"m{i}") for i in range(20)]
        s, e = date(YEAR, 6, 10), date(YEAR, 6, 14)

        def book(m):
            return lambda: svc.book_spontaneous(m, q, s, e, persons=2)

        results = self._run_parallel([book(m) for m in members])
        wins = [r for r in results if r and r[0] is not None]
        # Genau ein Gewinner, kein Fehler-Crash bei den anderen.
        self.assertEqual(len(wins), 1, f"erwartet 1 Gewinner, war {len(wins)}")
        self.assertEqual(
            Allocation.objects.filter(quarter=q, start=s, end=e).count(), 1)
        # Alle anderen bekamen (None, Fehlertext) – kein Exception-Leak.
        losers = [r for r in results if not (r and r[0] is not None)]
        self.assertTrue(all(r is not None and r[1] for r in losers))

    def test_verschiedene_quartiere_keine_falsche_blockade(self):
        """Buchen 10 Mitglieder GLEICHZEITIG je ein EIGENES freies Quartier
        (gleicher Zeitraum), gelingen ALLE – die Sperre serialisiert nicht
        fälschlich über Quartiere hinweg."""
        quarters = [Quarter.objects.create(name=f"Q{i}", eq_class=self.eq,
                                           min_occupancy=1, max_occupancy=4)
                    for i in range(10)]
        members = [_member(f"u{i}") for i in range(10)]
        s, e = date(YEAR, 7, 1), date(YEAR, 7, 5)

        def book(m, q):
            return lambda: svc.book_spontaneous(m, q, s, e, persons=1)

        results = self._run_parallel(
            [book(m, q) for m, q in zip(members, quarters)])
        wins = [r for r in results if r and r[0] is not None]
        self.assertEqual(len(wins), 10, f"erwartet 10 Buchungen, war {len(wins)}")
        self.assertEqual(Allocation.objects.count(), 10)
