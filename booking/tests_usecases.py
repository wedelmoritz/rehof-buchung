"""
Tiefgreifende Use-Case-Tests (Integration, DB-Ebene).

Jeder Test erzählt einen realistischen Ablauf und prüft das Zusammenspiel
mehrerer Funktionen. Sie sind bewusst DETERMINISTISCH gehalten, damit sie
zuverlässig grün sind und als Vorlage zum Erweitern dienen.

Lauf:  python manage.py test booking
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from booking.models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass,
    Member, Quarter, SeasonRule, Wish,
)
from booking import services as svc

NEXT_YEAR = date.today().year + 1


def make_member(name, **kwargs):
    u = User.objects.create_user(username=name, password="x" * 12)
    return Member.objects.create(user=u, display_name=name, **kwargs)


class UseCaseBase(TestCase):
    """Gemeinsame Stammdaten: zwei Äquivalenzklassen, mehrere Quartiere,
    einige Mitglieder. Buchungszeiträume/Regeln legt jeder Test selbst an,
    damit die Szenarien isoliert und gut lesbar bleiben."""

    def setUp(self):
        self.cls_klein = EquivalenceClass.objects.create(name="Klein")
        self.cls_solo = EquivalenceClass.objects.create(name="Solo")
        # Drei gleichwertige "kleine" Quartiere
        self.k1 = Quarter.objects.create(name="K1", eq_class=self.cls_klein,
                                         min_occupancy=1, max_occupancy=4)
        self.k2 = Quarter.objects.create(name="K2", eq_class=self.cls_klein,
                                         min_occupancy=1, max_occupancy=4)
        self.k3 = Quarter.objects.create(name="K3", eq_class=self.cls_klein,
                                         min_occupancy=1, max_occupancy=4)
        # Zwei Einzel-Quartiere ohne Gleichwertige (eigene Klassen)
        self.cls_a = EquivalenceClass.objects.create(name="A")
        self.cls_b = EquivalenceClass.objects.create(name="B")
        self.qa = Quarter.objects.create(name="QA", eq_class=self.cls_a,
                                         min_occupancy=1, max_occupancy=4)
        self.qb = Quarter.objects.create(name="QB", eq_class=self.cls_b,
                                         min_occupancy=1, max_occupancy=4)
        self.alice = make_member("alice")
        self.bob = make_member("bob")
        self.carla = make_member("carla")

    def open_full_year_window(self, year):
        """Globale Freigabe fürs ganze Jahr (Periode im Status „Freie
        Bebuchbarkeit“, für die normale Buchung)."""
        return BookingPeriod.objects.create(
            name=f"global {year}", target_year=year, start=date(year, 1, 1),
            end=date(year + 1, 1, 1), applies_to_all=True,
            status=BookingPeriod.FREE_BOOKING)


# --------------------------------------------------------------------------- #
# Use-Case 1: Buchungslebenszyklus inkl. Storno
# --------------------------------------------------------------------------- #

class BuchungslebenszyklusTests(UseCaseBase):
    def test_buchen_belegt_slot_und_tage_storno_gibt_frei(self):
        """Buchen reduziert die Tage und belegt das Quartier; Stornieren gibt
        beides wieder frei – auch für andere Mitglieder."""
        self.open_full_year_window(NEXT_YEAR)
        start = date(NEXT_YEAR, 4, 1)
        end = start + timedelta(days=5)

        # Vorher: volle Tage, Quartier frei
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 50)
        self.assertTrue(svc.quarter_is_free(self.k1, start, end))

        a, err = svc.book_spontaneous(self.alice, self.k1, start, end)
        self.assertIsNotNone(a, err)
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 45)
        self.assertFalse(svc.quarter_is_free(self.k1, start, end))

        # Anderes Mitglied kann denselben Slot nicht buchen
        b, err_b = svc.book_spontaneous(self.bob, self.k1, start, end)
        self.assertIsNone(b)

        # Storno gibt Tage und Slot frei
        ok, err_c = svc.cancel_allocation(self.alice, a.id)
        self.assertTrue(ok, err_c)
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 50)
        self.assertTrue(svc.quarter_is_free(self.k1, start, end))

        # Jetzt kann Bob buchen
        b2, err_b2 = svc.book_spontaneous(self.bob, self.k1, start, end)
        self.assertIsNotNone(b2, err_b2)


# --------------------------------------------------------------------------- #
# Use-Case 2: Budget-Grenze und Tage-Übertragung
# --------------------------------------------------------------------------- #

class BudgetUndUebertragungTests(UseCaseBase):
    def test_jahresbudget_grenze_und_uebertragung_hebt_sie(self):
        """50 Tage sind das Jahresbudget; darüber hinaus wird abgelehnt. Eine
        Übertragung von einem anderen Mitglied schafft neuen Spielraum."""
        self.open_full_year_window(NEXT_YEAR)

        # Alice bucht 50 Nächte am Stück (Jan–Feb, keine Saison-Regeln aktiv)
        s1 = date(NEXT_YEAR, 1, 2)
        a, err = svc.book_spontaneous(self.alice, self.qa, s1, s1 + timedelta(days=50))
        self.assertIsNotNone(a, err)
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 0)

        # Die nächste Buchung (anderes Quartier) scheitert am Budget
        s2 = date(NEXT_YEAR, 6, 1)
        b, err_b = svc.book_spontaneous(self.alice, self.qb, s2, s2 + timedelta(days=4))
        self.assertIsNone(b)
        self.assertIn("verfügbare Tage", err_b)

        # Bob überträgt 10 Tage -> Alice hat wieder Spielraum
        t, err_t = svc.transfer_nights(self.bob, self.alice, 10, NEXT_YEAR)
        self.assertIsNotNone(t, err_t)
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 10)

        c, err_c = svc.book_spontaneous(self.alice, self.qb, s2, s2 + timedelta(days=4))
        self.assertIsNotNone(c, err_c)
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 6)


# --------------------------------------------------------------------------- #
# Use-Case 3: Alle Sommer-Regeln zusammen (Mindestnächte + Parallel + Deckel)
# --------------------------------------------------------------------------- #

class SommerRegelnZusammenTests(UseCaseBase):
    def setUp(self):
        super().setUp()
        self.open_full_year_window(NEXT_YEAR)
        BookingPolicy.get_solo()  # Standard-Mindestnächte 3
        SeasonRule.objects.create(
            name="Hochsaison Juli/August", start=date(NEXT_YEAR, 7, 1),
            end=date(NEXT_YEAR, 9, 1), min_nights=7, active=True)
        SeasonRule.objects.create(
            name="Sommerferien BB", start=date(NEXT_YEAR, 7, 9),
            end=date(NEXT_YEAR, 8, 23), max_parallel_units=2, max_stay_nights=14,
            active=True)

    def test_eine_woche_zwei_einheiten_ok_dritte_nicht(self):
        s, e = date(NEXT_YEAR, 7, 13), date(NEXT_YEAR, 7, 20)  # 7 Nächte
        a1, e1 = svc.book_spontaneous(self.alice, self.k1, s, e)
        a2, e2 = svc.book_spontaneous(self.alice, self.k2, s, e)
        self.assertIsNotNone(a1, e1)
        self.assertIsNotNone(a2, e2)  # zwei Einheiten parallel: ok (14 Nächte)
        a3, e3 = svc.book_spontaneous(self.alice, self.k3, s, e)
        self.assertIsNone(a3)  # dritte Einheit: Parallel-Limit (2)
        self.assertIn("gleichzeitig", e3)

    def test_mindestnaechte_in_hochsaison(self):
        # frisches Mitglied ohne Sommerbuchungen -> isolierter Mindestnächte-Test
        s = date(NEXT_YEAR, 7, 20)
        a, err = svc.book_spontaneous(self.bob, self.k1, s, s + timedelta(days=5))
        self.assertIsNone(a)
        self.assertIn("7 Nächte", err)

    def test_deckel_14_naechte_je_partei(self):
        # 14 Nächte am Stück: ok; eine weitere Sommernacht: Deckel überschritten
        a, err = svc.book_spontaneous(self.carla, self.k1, date(NEXT_YEAR, 7, 13),
                                      date(NEXT_YEAR, 7, 27))
        self.assertIsNotNone(a, err)
        a2, err2 = svc.book_spontaneous(self.carla, self.k2, date(NEXT_YEAR, 8, 1),
                                        date(NEXT_YEAR, 8, 8))
        self.assertIsNone(a2)
        self.assertIn("je Partei", err2)


# --------------------------------------------------------------------------- #
# Use-Case 4: Jahreswechsel – Weihnachten/Silvester über die Jahresgrenze
# --------------------------------------------------------------------------- #

class JahreswechselTests(UseCaseBase):
    def test_parallel_limit_gilt_ueber_die_jahresgrenze(self):
        """Eine Buchung über Silvester und das Parallel-Limit im
        Weihnachts-Zeitraum müssen über die Jahresgrenze hinweg korrekt greifen."""
        # Freie Bebuchbarkeit Dez–Mitte Januar
        BookingPeriod.objects.create(
            name="Jahreswechsel", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 12, 1), end=date(NEXT_YEAR + 1, 1, 15),
            applies_to_all=True, status=BookingPeriod.FREE_BOOKING)
        BookingPolicy.get_solo()
        SeasonRule.objects.create(
            name="Weihnachten/Silvester", start=date(NEXT_YEAR, 12, 23),
            end=date(NEXT_YEAR + 1, 1, 3), max_parallel_units=2, active=True)

        s, e = date(NEXT_YEAR, 12, 28), date(NEXT_YEAR + 1, 1, 2)  # über den Jahreswechsel
        a1, e1 = svc.book_spontaneous(self.alice, self.k1, s, e)
        a2, e2 = svc.book_spontaneous(self.alice, self.k2, s, e)
        self.assertIsNotNone(a1, e1)
        self.assertIsNotNone(a2, e2)
        a3, e3 = svc.book_spontaneous(self.alice, self.k3, s, e)
        self.assertIsNone(a3)  # dritte Einheit über Silvester -> abgelehnt
        self.assertIn("gleichzeitig", e3)


# --------------------------------------------------------------------------- #
# Use-Case 5: Losverfahren – Priorität entscheidet (ordnungsunabhängig)
# --------------------------------------------------------------------------- #

class LosungPrioritaetTests(UseCaseBase):
    def test_prioritaet_und_runden_prinzip_bestimmen_zuteilung(self):
        """Alice will QA (Prio 1) und QB (Prio 2); Bob will nur QB (Prio 1),
        selber Zeitraum. QA und QB sind Einzelquartiere. Unabhängig von der
        ausgelosten Reihenfolge muss gelten: Alice bekommt QA, Bob bekommt QB –
        Bobs Erstwunsch schlägt Alices Zweitwunsch (Runden-Prinzip)."""
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s = date(NEXT_YEAR, 5, 24)
        e = s + timedelta(days=5)
        svc.add_wish(self.alice, period, self.qa, s, e)   # Prio 1
        svc.add_wish(self.alice, period, self.qb, s, e)   # Prio 2
        svc.add_wish(self.bob, period, self.qb, s, e)     # Prio 1
        svc.submit_wishlist(self.alice, period)
        svc.submit_wishlist(self.bob, period)

        # Über alle Seeds stabil prüfen
        for seed in range(8):
            Allocation.objects.filter(period=period, source="lottery").delete()
            svc.run_period_lottery(period, seed=seed)
            allocs = {
                a.member.display_name: a.quarter.name
                for a in Allocation.objects.filter(period=period, source="lottery")
            }
            self.assertEqual(allocs.get("alice"), "QA", f"seed={seed}")
            self.assertEqual(allocs.get("bob"), "QB", f"seed={seed}")


# --------------------------------------------------------------------------- #
# Use-Case 6: Nur eingereichte Wünsche + Idempotenz der Losung
# --------------------------------------------------------------------------- #

class LosungEinreichungUndIdempotenzTests(UseCaseBase):
    def test_entwuerfe_nehmen_nicht_teil_und_rerun_ist_idempotent(self):
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s = date(NEXT_YEAR, 6, 7)
        e = s + timedelta(days=4)
        # Alice reicht ein, Bob bleibt Entwurf
        svc.add_wish(self.alice, period, self.k1, s, e)
        svc.add_wish(self.bob, period, self.k1, s, e)
        svc.submit_wishlist(self.alice, period)

        svc.run_period_lottery(period, seed=5)
        first = sorted(
            (a.member.display_name, a.quarter.name, a.start, a.end)
            for a in Allocation.objects.filter(period=period, source="lottery"))
        names = {x[0] for x in first}
        self.assertIn("alice", names)
        self.assertNotIn("bob", names)  # Entwurf nimmt nicht teil

        # Re-Run mit gleichem Seed: gleiches Ergebnis, keine Doppelzuteilung
        svc.run_period_lottery(period, seed=5)
        second = sorted(
            (a.member.display_name, a.quarter.name, a.start, a.end)
            for a in Allocation.objects.filter(period=period, source="lottery"))
        self.assertEqual(first, second)
        self.assertEqual(
            Allocation.objects.filter(period=period, source="lottery").count(),
            len(first))


# --------------------------------------------------------------------------- #
# Use-Case 7: Karma wirkt persistent über mehrere Losungen
# --------------------------------------------------------------------------- #

class KarmaPersistenzTests(UseCaseBase):
    def test_verlierer_sammeln_faktor_ueber_die_jahre(self):
        """Drei Mitglieder, ein einzelnes Quartier, derselbe knappe Zeitraum –
        je Losung gewinnt genau eine Partei, zwei verlieren echt. Die Verlierer
        sammeln Karma; die Faktoren werden korrekt in der DB fortgeschrieben."""
        members = [self.alice, self.bob, self.carla]

        def run_year(year, seed):
            period = BookingPeriod.objects.create(
                name=f"Losung {year}", target_year=year,
                start=date(year, 1, 1), end=date(year + 1, 1, 1),
                wishlist_open=date.today(), wishlist_close=date.today(),
                status=BookingPeriod.WISHES_OPEN)
            s = date(year, 5, 24)
            e = s + timedelta(days=5)
            for m in members:
                svc.add_wish(m, period, self.qa, s, e)
                svc.submit_wishlist(m, period)
            svc.run_period_lottery(period, seed=seed)
            return period

        # Jahr 1
        run_year(NEXT_YEAR, seed=1)
        for m in members:
            m.refresh_from_db()
        factors = sorted(m.factor for m in members)
        # Genau ein Gewinner (umkämpft -> Reset auf 1.0), zwei Verlierer (+0.1)
        self.assertEqual(factors, [1.0, 1.1, 1.1])
        # Summe stieg um 0.2 gegenüber Start (3 x 1.0)
        self.assertAlmostEqual(sum(m.factor for m in members), 3.2, places=6)

        # Jahr 2: erneut genau ein Gewinner, zwei Verlierer
        run_year(NEXT_YEAR + 1, seed=2)
        for m in members:
            m.refresh_from_db()
        # Es gibt weiterhin genau einen zurückgesetzten Gewinner (Faktor 1.0)
        self.assertEqual(sum(1 for m in members if abs(m.factor - 1.0) < 1e-9), 1)
        # Alle Faktoren bleiben im erlaubten Rahmen [1.0, 1.5]
        for m in members:
            self.assertGreaterEqual(m.factor, 1.0)
            self.assertLessEqual(m.factor, 1.5)
        # Mindestens ein Verlierer hat nun einen Faktor > 1.1 (Karma akkumuliert)
        self.assertTrue(any(m.factor > 1.1 + 1e-9 for m in members))
