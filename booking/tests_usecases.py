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
    Member, Membership, Notification, Quarter, SeasonRule, Share, WaitlistEntry,
    Wish,
)
from booking import services as svc

NEXT_YEAR = date.today().year + 1


def make_member(name, nights=50, wish=25, **kwargs):
    """Nutzer als Voll-Mitglied (eigener Anteil mit `nights` Tagen)."""
    u = User.objects.create_user(username=name, password="x" * 12)
    m = Member.objects.create(user=u, display_name=name, **kwargs)
    ms = Membership.objects.create(
        eg_number=f"EG-{name}", label=name,
        annual_night_budget=nights, wish_night_budget=wish)
    Share.objects.create(membership=ms, member=m,
                         night_budget=nights, wish_night_budget=wish)
    return m


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
            name="Hochsaison Juli/August", start_month=7, start_day=1,
            end_month=9, end_day=1, min_nights=7, active=True)
        SeasonRule.objects.create(
            name="Sommerferien BB", start_month=7, start_day=9,
            end_month=8, end_day=23, max_parallel_units=2, max_stay_nights=14,
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
            name="Weihnachten/Silvester", start_month=12, start_day=23,
            end_month=1, end_day=3, max_parallel_units=2, active=True)

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


# --------------------------------------------------------------------------- #
# Use-Case 8: Klick-Buchung – Personenzahl, Ampel-Kalender, Warteliste
# --------------------------------------------------------------------------- #

class BuchungsFlowTests(UseCaseBase):
    def setUp(self):
        super().setUp()
        self.open_full_year_window(NEXT_YEAR)

    def test_personenzahl_wird_geprueft_und_gespeichert(self):
        s = date(NEXT_YEAR, 4, 1)
        e = s + timedelta(days=3)
        # k1 ist für 1–4 Personen ausgelegt -> 10 Personen werden abgelehnt
        a, err = svc.book_spontaneous(self.alice, self.k1, s, e, persons=10)
        self.assertIsNone(a)
        self.assertIn("Personen", err)
        # gültige Personenzahl wird übernommen
        a, err = svc.book_spontaneous(self.alice, self.k1, s, e, persons=3)
        self.assertIsNotNone(a, err)
        self.assertEqual(a.persons, 3)

    def test_warteliste_nur_bei_belegtem_quartier(self):
        s = date(NEXT_YEAR, 4, 10)
        e = s + timedelta(days=3)
        # frei -> Warteliste nicht nötig
        entry, err = svc.add_waitlist_entry(self.bob, self.k1, s, e, persons=2)
        self.assertIsNone(entry)
        self.assertIn("frei", err)

    def test_warteliste_benachrichtigt_bei_storno(self):
        s = date(NEXT_YEAR, 5, 5)
        e = s + timedelta(days=4)
        a, err = svc.book_spontaneous(self.alice, self.k1, s, e, persons=2)
        self.assertIsNotNone(a, err)
        # Bob möchte denselben (belegten) Zeitraum -> Warteliste
        entry, err = svc.add_waitlist_entry(self.bob, self.k1, s, e, persons=2)
        self.assertIsNotNone(entry, err)
        # Die Buchenden (Alice) sehen, dass jemand wartet
        waiters = svc.waiters_for_allocation(a)
        self.assertEqual([w.member for w in waiters], [self.bob])
        # Alice storniert -> Bob wird benachrichtigt, Eintrag erledigt
        ok, err = svc.cancel_allocation(self.alice, a.id)
        self.assertTrue(ok, err)
        entry.refresh_from_db()
        self.assertTrue(entry.fulfilled)
        self.assertEqual(
            Notification.objects.filter(member=self.bob, read=False).count(), 1)
        # … und Bob kann nun buchen
        b, err = svc.book_spontaneous(self.bob, self.k1, s, e, persons=2)
        self.assertIsNotNone(b, err)

    def test_ampel_kalender_zeigt_belegung(self):
        quarters = [self.k1, self.k2, self.k3, self.qa, self.qb]
        d = date(NEXT_YEAR, 6, 15)

        def level_for(day):
            cal = svc.build_booking_calendar(self.alice, day.year, day.month)
            for week in cal["weeks"]:
                for cell in week:
                    if cell["date"] == day:
                        return cell
            return None

        # Anfangs ist alles frei -> grün ("free"), free == total
        cell = level_for(d)
        self.assertEqual(cell["level"], "free")
        self.assertEqual(cell["free"], len(quarters))

        # Ein Quartier belegt (3 Nächte = Standard-Mindestbuchung) -> "many"
        a1, e1 = svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3))
        self.assertIsNotNone(a1, e1)
        self.assertEqual(level_for(d)["level"], "many")

        # Alle Quartiere am Tag d belegt -> nichts frei ("full")
        for q in quarters[1:]:
            ax, ex = svc.book_spontaneous(self.alice, q, d, d + timedelta(days=3))
            self.assertIsNotNone(ax, ex)
        cell = level_for(d)
        self.assertEqual(cell["level"], "full")
        self.assertEqual(cell["free"], 0)


# --------------------------------------------------------------------------- #
# Use-Case 9: Jährliche Regeln (Monat/Tag) und Quartier-Saison
# --------------------------------------------------------------------------- #

class JahresregelnUndQuartierSaisonTests(UseCaseBase):
    def test_quartier_saison_begrenzt_buchbarkeit(self):
        # k1 nur Mai–September buchbar (jährlich, ohne Jahr)
        self.k1.season_start_month, self.k1.season_start_day = 5, 1
        self.k1.season_end_month, self.k1.season_end_day = 9, 30
        self.k1.save()
        self.open_full_year_window(NEXT_YEAR)
        # Januar: außerhalb der Saison -> nicht buchbar
        a, err = svc.book_spontaneous(
            self.alice, self.k1, date(NEXT_YEAR, 1, 10),
            date(NEXT_YEAR, 1, 13))
        self.assertIsNone(a)
        self.assertIn("freigeschaltet", err)
        # Juni: innerhalb der Saison -> buchbar
        a, err = svc.book_spontaneous(
            self.alice, self.k1, date(NEXT_YEAR, 6, 10),
            date(NEXT_YEAR, 6, 13))
        self.assertIsNotNone(a, err)

    def test_schulferien_setzen_regel_durch(self):
        # Schulferien mit Parallel-Limit 2 (jährlich) wirken wie eine Saison-Regel
        from booking.models import SchoolHoliday
        SchoolHoliday.objects.create(
            name="Testferien", start_month=3, start_day=1, end_month=3, end_day=15,
            max_parallel_units=2, active=True)
        self.open_full_year_window(NEXT_YEAR)
        s, e = date(NEXT_YEAR, 3, 3), date(NEXT_YEAR, 3, 6)
        self.assertIsNotNone(svc.book_spontaneous(self.alice, self.k1, s, e)[0])
        self.assertIsNotNone(svc.book_spontaneous(self.alice, self.k2, s, e)[0])
        a3, err = svc.book_spontaneous(self.alice, self.k3, s, e)
        self.assertIsNone(a3)
        self.assertIn("gleichzeitig", err)

    def test_regel_gilt_jedes_jahr(self):
        # Eine Juli-Regel (min 7 Nächte) greift in mehreren Jahren gleich
        SeasonRule.objects.create(
            name="Hochsaison", start_month=7, start_day=1, end_month=9, end_day=1,
            min_nights=7, active=True)
        self.open_full_year_window(NEXT_YEAR)
        self.open_full_year_window(NEXT_YEAR + 1)
        for year in (NEXT_YEAR, NEXT_YEAR + 1):
            a, err = svc.book_spontaneous(
                self.alice, self.k1, date(year, 7, 10), date(year, 7, 14))  # 4 < 7
            self.assertIsNone(a, f"{year}: sollte an Mindestnächten scheitern")
            self.assertIn("7 Nächte", err)


# --------------------------------------------------------------------------- #
# Use-Case 10: Tages-Detail, Mindestnächte-Anzeige, Wechselwunsch
# --------------------------------------------------------------------------- #

class DetailUndWechselwunschTests(UseCaseBase):
    def setUp(self):
        super().setUp()
        self.open_full_year_window(NEXT_YEAR)

    def test_min_nights_for_range(self):
        SeasonRule.objects.create(
            name="Hochsaison", start_month=7, start_day=1, end_month=9, end_day=1,
            min_nights=7, active=True)
        # Standard (außerhalb Saison): 3 Nächte
        self.assertEqual(
            svc.min_nights_for_range(date(NEXT_YEAR, 3, 1), date(NEXT_YEAR, 3, 4)), 3)
        # In der Hochsaison: 7
        self.assertEqual(
            svc.min_nights_for_range(date(NEXT_YEAR, 7, 10), date(NEXT_YEAR, 7, 14)), 7)

    def test_day_detail_zeigt_belegt_und_frei(self):
        d = date(NEXT_YEAR, 4, 10)
        svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3), persons=2)
        detail = svc.day_detail(self.bob, d)
        belegte = [o["quarter"] for o in detail["occupied"]]
        self.assertIn("K1", belegte)
        self.assertEqual(detail["occupied"][0]["persons"], 2)
        # K2/K3 sind an dem Tag noch frei
        self.assertIn("K2", detail["free"])
        self.assertNotIn("K1", detail["free"])

    def test_wechselwunsch_anlegen_und_beantworten(self):
        d = date(NEXT_YEAR, 4, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3))
        b, _ = svc.book_spontaneous(self.bob, self.k2, d, d + timedelta(days=3))
        sr, err = svc.create_swap_request(self.alice, a, b, "Tauschen?")
        self.assertIsNotNone(sr, err)
        # Bob ist benachrichtigt und sieht den offenen Wunsch
        self.assertEqual(self.bob.notifications.filter(read=False).count(), 1)
        self.assertEqual(len(svc.pending_swaps_for(self.bob)), 1)
        # Bob stimmt zu -> Status gesetzt, Alice benachrichtigt
        ok, err = svc.respond_swap_request(self.bob, sr.id, accept=True)
        self.assertTrue(ok, err)
        sr.refresh_from_db()
        self.assertEqual(sr.status, "accepted")
        self.assertEqual(self.alice.notifications.filter(read=False).count(), 1)
        # Kein doppeltes Beantworten
        ok2, _ = svc.respond_swap_request(self.bob, sr.id, accept=False)
        self.assertFalse(ok2)


class WunschKalenderTests(UseCaseBase):
    def test_wunsch_ampel_und_zaehler(self):
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            status=BookingPeriod.WISHES_OPEN)
        s, e = date(NEXT_YEAR, 5, 10), date(NEXT_YEAR, 5, 14)
        for who in (self.alice, self.bob):
            svc.add_wish(who, period, self.k1, s, e)
            svc.submit_wishlist(who, period)
        # Zähler je Quartier
        counts = svc.quarter_wish_counts(period, s, e)
        self.assertEqual(counts[str(self.k1.id)], 2)
        # Ampel-Nachfrage am Tag + eigene Markierung
        cal = svc.build_wish_calendar(self.alice, period, NEXT_YEAR, 5)
        cell = next(c for wk in cal["weeks"] for c in wk if c["date"] == s)
        self.assertEqual(cell["demand"], 2)
        self.assertTrue(cell["own_sub"])


# --------------------------------------------------------------------------- #
# Use-Case 11: Tandem-Mitgliedschaften (fester Tage-Anteil je Nutzer)
# --------------------------------------------------------------------------- #

class TandemTests(UseCaseBase):
    def setUp(self):
        super().setUp()
        self.open_full_year_window(NEXT_YEAR)
        # Solo-Anteile von alice/bob entfernen und gemeinsamen Tandem-Anteil bilden
        Share.objects.filter(member__in=[self.alice, self.bob]).delete()
        self.share = Membership.objects.create(
            eg_number="VL-1", label="Tandem", kind=Membership.TEIL,
            annual_night_budget=50, wish_night_budget=25)
        for m in (self.alice, self.bob):
            Share.objects.create(membership=self.share, member=m,
                                 night_budget=25, wish_night_budget=12)

    def test_tandem_budgets_sind_getrennt(self):
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 25)
        # Alice bucht 20 Nächte aus ihrem 25er-Anteil
        a, err = svc.book_spontaneous(
            self.alice, self.k1, date(NEXT_YEAR, 3, 1), date(NEXT_YEAR, 3, 21))
        self.assertIsNotNone(a, err)
        self.assertEqual(self.alice.nights_remaining_in_year(NEXT_YEAR), 5)
        # Bobs Anteil bleibt unberührt
        self.assertEqual(self.bob.nights_remaining_in_year(NEXT_YEAR), 25)
        # Alice über ihren Anteil hinaus (10 > 5) -> abgelehnt
        a2, err2 = svc.book_spontaneous(
            self.alice, self.k2, date(NEXT_YEAR, 4, 1), date(NEXT_YEAR, 4, 11))
        self.assertIsNone(a2)
        self.assertIn("verfügbare Tage", err2)
        # Anteils-Eigenschaften
        self.assertTrue(self.share.is_tandem)
        self.assertEqual(self.share.allocated_budget, 50)
        self.assertEqual([p.id for p in self.alice.tandem_partners], [self.bob.id])

    def test_anteiliges_budget_bei_anlage_mitten_im_jahr(self):
        self.assertEqual(Membership.suggest_budget(50, date(2030, 1, 1)), 50)
        mid = Membership.suggest_budget(50, date(2030, 7, 1))
        self.assertLess(mid, 50)
        self.assertGreater(mid, 0)

    def test_nutzer_in_zwei_anteilen_summiert_kapazitaet(self):
        # carla bekommt einen eigenen + einen zweiten Anteil: 20 + 15 = 35
        Share.objects.filter(member=self.carla).delete()
        a1 = Membership.objects.create(eg_number="A1", annual_night_budget=20)
        a2 = Membership.objects.create(eg_number="A2", annual_night_budget=15)
        Share.objects.create(membership=a1, member=self.carla,
                             night_budget=20, wish_night_budget=10)
        Share.objects.create(membership=a2, member=self.carla,
                             night_budget=15, wish_night_budget=5)
        self.assertEqual(self.carla.annual_night_budget, 35)
        self.assertEqual(self.carla.wish_night_budget, 15)
        self.assertEqual(len(self.carla.memberships), 2)
