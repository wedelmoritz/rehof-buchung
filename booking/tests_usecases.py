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
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
        # Spontan-Vorausfrist hier aus (Use-Cases buchen mit festen Daten, teils
        # nah an „heute"); eigene Tests prüfen Frist + Lückenfüllung. ADR 0075.
        from .models import BookingPolicy
        p = BookingPolicy.get_solo()
        p.min_lead_days = 0
        p.save(update_fields=["min_lead_days"])

    def open_full_year_window(self, year):
        """Globale Freigabe fürs ganze Jahr (Periode im Status „Freie
        Bebuchbarkeit“, für die normale Buchung)."""
        return BookingPeriod.objects.create(
            name=f"global {year}", target_year=year, start=date(year, 1, 1),
            end=date(year + 1, 1, 1),
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
            status=BookingPeriod.FREE_BOOKING)
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


class LosungTransparenzTests(UseCaseBase):
    def test_benachrichtigung_zeigt_gewinn_verlust_und_karma(self):
        """Zwei Mitglieder wollen dasselbe Einzelquartier im selben Zeitraum:
        eine:r gewinnt, die:der andere verliert echt. Beide bekommen eine
        Benachrichtigung; der Verlierer sieht den Karma-Anstieg, der Gewinner
        seinen Gewinn."""
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s = date(NEXT_YEAR, 5, 24)
        e = s + timedelta(days=5)
        svc.add_wish(self.alice, period, self.qa, s, e)
        svc.add_wish(self.bob, period, self.qa, s, e)
        svc.submit_wishlist(self.alice, period)
        svc.submit_wishlist(self.bob, period)

        run = svc.run_period_lottery(period, seed=1)

        # Vor der Bestätigung: unbestätigt, KEINE Benachrichtigungen.
        url = reverse("period_result", args=[period.id])
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.LOTTERY_REVIEW)
        self.assertEqual(Notification.objects.filter(url=url).count(), 0)

        # Bestätigen → veröffentlicht, beide Teilnehmer benachrichtigt.
        svc.confirm_lottery(run)
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.LOTTERY_DONE)
        notes = list(Notification.objects.filter(url=url))
        self.assertEqual(len(notes), 2)

        losers = [n for n in notes if "diesmal nicht geklappt" in n.detail]
        winners = [n for n in notes if "Du hast bekommen" in n.detail]
        self.assertEqual(len(losers), 1)
        self.assertEqual(len(winners), 1)

        loser_note = losers[0]
        self.assertIn("Ausgleichsfaktor um +0.1", loser_note.detail)
        loser = loser_note.member
        loser.refresh_from_db()
        self.assertGreater(loser.factor, 1.0)


# --------------------------------------------------------------------------- #
# Use-Case 6: Nur eingereichte Wünsche + Idempotenz der Losung
# --------------------------------------------------------------------------- #

class LosungEinreichungUndIdempotenzTests(UseCaseBase):
    def test_exakter_doppelwunsch_abgelehnt(self):
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s = date(NEXT_YEAR, 6, 7)
        e = s + timedelta(days=4)
        w1, err1 = svc.add_wish(self.alice, period, self.k1, s, e)
        self.assertIsNotNone(w1, err1)
        # Exakt gleicher Wunsch → abgelehnt (#2a)
        w2, err2 = svc.add_wish(self.alice, period, self.k1, s, e)
        self.assertIsNone(w2)
        self.assertIn("schon eingetragen", err2)
        # Nur überlappender Zeitraum bleibt bewusst erlaubt
        w3, err3 = svc.add_wish(self.alice, period, self.k1,
                                s + timedelta(days=1), e + timedelta(days=1))
        self.assertIsNotNone(w3, err3)

    def test_wunsch_obergrenze_konfigurierbar(self):
        """Optionale Obergrenze je Periode (#5, ADR 0078): 0 = unbegrenzt (Default),
        gesetzt greift sie server-seitig beim Eintragen."""
        from booking.models import BookingPolicy
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        pol = BookingPolicy.get_solo()
        pol.max_wishes_per_period = 2
        pol.save(update_fields=["max_wishes_per_period"])
        s = date(NEXT_YEAR, 6, 7)
        w1, e1 = svc.add_wish(self.alice, period, self.k1, s, s + timedelta(days=4))
        w2, e2 = svc.add_wish(self.alice, period, self.k2, s, s + timedelta(days=4))
        self.assertIsNotNone(w1, e1)
        self.assertIsNotNone(w2, e2)
        # Dritter Wunsch → abgelehnt (Grenze erreicht)
        w3, e3 = svc.add_wish(self.alice, period, self.k3, s, s + timedelta(days=4))
        self.assertIsNone(w3)
        self.assertIn("höchstens 2", e3)
        # 0 = unbegrenzt: Grenze aufheben, dann geht der dritte wieder
        pol.max_wishes_per_period = 0
        pol.save(update_fields=["max_wishes_per_period"])
        w3b, e3b = svc.add_wish(self.alice, period, self.k3, s, s + timedelta(days=4))
        self.assertIsNotNone(w3b, e3b)

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
        # Strikter Modus: kleinere Unterkünfte NICHT zulassen (ADR 0076).
        p = BookingPolicy.get_solo()
        p.allow_undersized_units = False
        p.save(update_fields=["allow_undersized_units"])
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

    def test_kalender_markiert_anreise_und_abreise(self):
        s = date(NEXT_YEAR, 6, 10)
        e = date(NEXT_YEAR, 6, 13)
        cal = svc.build_booking_calendar(self.alice, s.year, s.month,
                                         sel_start=s, sel_end=e)
        cells = {c["date"]: c for week in cal["weeks"] for c in week if c["in_month"]}
        self.assertTrue(cells[s]["is_start"])
        self.assertTrue(cells[e]["is_end"])
        self.assertFalse(cells[e]["is_start"])
        # Die Nächte dazwischen sind im Band, der Abreisetag (exklusiv) nicht.
        self.assertTrue(cells[s + timedelta(days=1)]["in_range"])
        self.assertFalse(cells[e]["in_range"])

    def test_belegungs_timeline_balken(self):
        s = date(NEXT_YEAR, 6, 5)
        e = date(NEXT_YEAR, 6, 8)
        b, err = svc.book_spontaneous(self.alice, self.k1, s, e, persons=2)
        self.assertIsNotNone(b, err)
        tl = svc.build_occupancy_timeline(self.alice, NEXT_YEAR, 6)
        row = next(r for r in tl["rows"] if r["quarter"].id == self.k1.id)
        self.assertEqual(len(row["bars"]), 1)
        bar = row["bars"][0]
        self.assertEqual(bar["col"], 5)     # 5. Tag des Monats
        self.assertEqual(bar["span"], 3)    # 3 Nächte
        self.assertTrue(bar["mine"])

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
        # Bob stimmt zu -> Tausch wird SOFORT ausgeführt (Quartiere wechseln)
        ok, err = svc.respond_swap_request(self.bob, sr.id, accept=True)
        self.assertTrue(ok, err)
        sr.refresh_from_db()
        self.assertEqual(sr.status, "accepted")
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.quarter, self.k2)     # Alice ist jetzt in K2
        self.assertEqual(b.quarter, self.k1)     # Bob ist jetzt in K1
        self.assertEqual(a.start, d)             # Zeitraum unverändert
        self.assertEqual(self.alice.notifications.filter(read=False).count(), 1)
        # Kein doppeltes Beantworten
        ok2, _ = svc.respond_swap_request(self.bob, sr.id, accept=False)
        self.assertFalse(ok2)

    def test_tausch_nur_bei_gleichem_zeitraum(self):
        d = date(NEXT_YEAR, 4, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3))
        # Bob hat einen anderen (nur überlappenden) Zeitraum → kein Tausch möglich.
        b, _ = svc.book_spontaneous(self.bob, self.k2, d + timedelta(days=1),
                                    d + timedelta(days=4))
        sr, err = svc.create_swap_request(self.alice, a, b)
        self.assertIsNone(sr)
        self.assertIn("gleichem Zeitraum", err)

    def test_my_bookings_rendert_tausch_und_belegung(self):
        d = date(NEXT_YEAR, 4, 10)
        svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3))
        svc.book_spontaneous(self.bob, self.k2, d, d + timedelta(days=3))
        self.client.force_login(self.alice.user)
        r = self.client.get(reverse("my_bookings"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Wer ist zur gleichen Zeit da")
        self.assertContains(r, "Unterkunft mit jemandem tauschen")
        self.assertContains(r, "Tausch anfragen")     # Bob ist exakter Kandidat
        self.assertContains(r, self.bob.display_name)

    def test_tausch_opt_out_blockt_anfrage(self):
        """Opt-out je Mitglied (#8/ADR 0078): wer keine Tausch-Anfragen möchte,
        kann nicht angefragt werden und erscheint nicht als exakter Kandidat."""
        d = date(NEXT_YEAR, 4, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3))
        b, _ = svc.book_spontaneous(self.bob, self.k2, d, d + timedelta(days=3))
        self.bob.accept_swap_requests = False
        self.bob.save(update_fields=["accept_swap_requests"])
        # Server-seitig abgelehnt
        sr, err = svc.create_swap_request(self.alice, a, b)
        self.assertIsNone(sr)
        self.assertIn("keine Tausch-Anfragen", err)
        # Und Bob taucht in Alices my_bookings nicht als Tausch-Kandidat auf
        self.client.force_login(self.alice.user)
        r = self.client.get(reverse("my_bookings"))
        self.assertNotContains(r, "Tausch anfragen")

    def test_tausch_hinfaellig_wenn_zeitraum_geaendert(self):
        d = date(NEXT_YEAR, 4, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, d, d + timedelta(days=3))
        b, _ = svc.book_spontaneous(self.bob, self.k2, d, d + timedelta(days=3))
        sr, _ = svc.create_swap_request(self.alice, a, b)
        # Alice verlängert ihre Buchung → Zeitraum stimmt nicht mehr überein.
        svc.adjust_allocation(self.alice, a.id, d, d + timedelta(days=4))
        ok, err = svc.respond_swap_request(self.bob, sr.id, accept=True)
        self.assertFalse(ok)
        self.assertIn("nicht mehr möglich", err)


class TerminierteLosungTests(UseCaseBase):
    def _period(self, draw_at, status=BookingPeriod.WISHES_OPEN):
        return BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            status=status, draw_at=draw_at)

    def test_faellige_losung_laeuft_automatisch(self):
        period = self._period(timezone.now() - timedelta(hours=1))
        s = date(NEXT_YEAR, 5, 24)
        svc.add_wish(self.alice, period, self.qa, s, s + timedelta(days=5))
        svc.submit_wishlist(self.alice, period)
        call_command("run_due_lotteries")
        period.refresh_from_db()
        # Nach dem Lauf nur „zur Prüfung“ – die Veröffentlichung ist manuell.
        self.assertEqual(period.status, BookingPeriod.LOTTERY_REVIEW)
        self.assertIsNotNone(period.seed)
        self.assertEqual(
            Allocation.objects.filter(period=period, source="lottery").count(), 1)

    def test_zukuenftige_losung_bleibt_offen(self):
        period = self._period(timezone.now() + timedelta(days=2))
        call_command("run_due_lotteries")
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.WISHES_OPEN)

    def test_status_folgt_terminen_vorwaerts(self):
        """Erreicht „Wünsche ab“, schaltet der Cron den Entwurf auf
        „Wünsche offen“ – aber nie zurück."""
        today = date.today()
        period = BookingPeriod.objects.create(
            name="Auto", target_year=NEXT_YEAR,
            wishlist_open=today - timedelta(days=1),
            wishlist_close=today + timedelta(days=5),
            draw_at=timezone.now() + timedelta(days=10),
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            status=BookingPeriod.DRAFT)
        call_command("run_due_lotteries")
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.WISHES_OPEN)

    def test_unterbrochen_wird_nicht_geschaltet(self):
        today = date.today()
        period = BookingPeriod.objects.create(
            name="Pause", target_year=NEXT_YEAR,
            wishlist_open=today - timedelta(days=1),
            wishlist_close=today + timedelta(days=5),
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            status=BookingPeriod.SUSPENDED)
        call_command("run_due_lotteries")
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.SUSPENDED)

    def test_scheduler_once_laeuft_durch(self):
        """Der Scheduler-Einzeldurchlauf (Cron) führt fällige Losungen aus und
        ruft die Monatsrechnung – ohne zu crashen, auch ohne Daten."""
        period = self._period(timezone.now() - timedelta(hours=1))
        s = date(NEXT_YEAR, 5, 24)
        svc.add_wish(self.alice, period, self.qa, s, s + timedelta(days=5))
        svc.submit_wishlist(self.alice, period)
        call_command("run_scheduler", once=True)
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.LOTTERY_REVIEW)

    def test_buchbar_ab_oeffnet_freie_buchung(self):
        """Ist „buchbar ab“ erreicht (und die Losung gelaufen), steht die Periode
        auf „Freie Bebuchbarkeit“."""
        today = date.today()
        y = today.year
        period = BookingPeriod.objects.create(
            name="Jetzt", target_year=y,
            start=date(y, 1, 1), end=date(y + 1, 1, 1),
            draw_at=timezone.now() - timedelta(days=1),
            status=BookingPeriod.DRAFT)
        call_command("run_due_lotteries")       # Losung läuft → Prüfzustand
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.LOTTERY_REVIEW)
        svc.confirm_lottery(period.runs.first())  # bestätigen → veröffentlicht
        call_command("run_due_lotteries")       # „buchbar ab“ erreicht → frei
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.FREE_BOOKING)


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

    def test_buchung_traegt_mitglieds_anteil(self):
        """Eine Spontanbuchung wird dem (eindeutigen) Mitglieds-Anteil zugerechnet."""
        a, err = svc.book_spontaneous(
            self.alice, self.k1, date(NEXT_YEAR, 3, 1), date(NEXT_YEAR, 3, 8))
        self.assertIsNotNone(a, err)
        self.assertEqual(a.membership_id, self.share.id)

    def test_parallel_limit_gilt_auf_vollen_anteil(self):
        """Das Parallel-Limit zählt über den VOLLEN Anteil inkl. Tandem-Partner
        (ADR 0066): bucht alice eine Einheit, darf bob (gleicher Anteil) im selben
        Zeitraum KEINE zweite Einheit buchen – ein fremdes Mitglied dagegen schon."""
        BookingPolicy.get_solo()
        SeasonRule.objects.create(
            name="Limit 1", start_month=1, start_day=1, end_month=12, end_day=31,
            max_parallel_units=1, active=True)
        s, e = date(NEXT_YEAR, 3, 1), date(NEXT_YEAR, 3, 8)
        a, err = svc.book_spontaneous(self.alice, self.k1, s, e)
        self.assertIsNotNone(a, err)
        # bob (gleicher Anteil) – überlappende zweite Einheit: blockiert
        b, berr = svc.book_spontaneous(self.bob, self.k2, s, e)
        self.assertIsNone(b)
        self.assertIn("gleichzeitig", berr)
        # carla (eigener Anteil) – nicht betroffen, bucht parallel
        c, cerr = svc.book_spontaneous(self.carla, self.k3, s, e)
        self.assertIsNotNone(c, cerr)

    def test_losung_poolt_tandem_partner_und_setzt_anteil(self):
        """In der Losung teilen sich Tandem-Partner das Parallel-Limit ihres
        Anteils (ADR 0066): je ein überlappender Wunsch auf verschiedene
        Einzelquartiere → nur EINE Einheit wird zugeteilt; der Gewinn trägt den
        Anteil, der Wunsch ebenso."""
        BookingPolicy.get_solo()
        SeasonRule.objects.create(
            name="Limit 1", start_month=1, start_day=1, end_month=12, end_day=31,
            max_parallel_units=1, active=True)
        yr = NEXT_YEAR + 1
        period = BookingPeriod.objects.create(
            name="Losung", target_year=yr,
            start=date(yr, 1, 1), end=date(yr + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s, e = date(yr, 5, 10), date(yr, 5, 15)
        svc.add_wish(self.alice, period, self.qa, s, e)
        svc.add_wish(self.bob, period, self.qb, s, e)
        svc.submit_wishlist(self.alice, period)
        svc.submit_wishlist(self.bob, period)
        # Beide Wünsche tragen den gemeinsamen Anteil.
        self.assertEqual(
            set(Wish.objects.filter(period=period)
                .values_list("membership_id", flat=True)),
            {self.share.id})
        svc.run_period_lottery(period, seed=1)
        allocs = Allocation.objects.filter(period=period, source="lottery")
        self.assertEqual(allocs.count(), 1)          # gepoolt über den Anteil
        self.assertEqual(allocs.first().membership_id, self.share.id)


class AutoAnteilTests(UseCaseBase):
    """Ein buchendes Mitglied ist nach dem Anlegen IMMER mit einem Mitglieds-Anteil
    verknüpft – fehlt einer, wird automatisch ein voller Anteil angelegt (ADR 0068).
    Tandems bleiben möglich (bewusstes Aufteilen am Anteil)."""

    def test_legt_vollen_anteil_an_und_macht_buchbar(self):
        u = User.objects.create_user("neu", "neu@e.org", "x" * 12)
        m = Member.objects.create(user=u, display_name="Neu")
        self.assertFalse(m.shares.exists())
        share = svc.ensure_personal_membership(m)
        self.assertIsNotNone(share)
        self.assertEqual(m.shares.count(), 1)
        self.assertEqual(share.membership.kind, Membership.VOLL)
        self.assertEqual(share.membership.annual_night_budget, 50)
        self.assertEqual(share.night_budget, 50)         # voller Anteil = 50 Tage
        self.assertEqual(share.wish_night_budget, 25)
        # „Mitglied" und „Mitglieds-Anteil" sind jetzt verknüpft -> buchbar
        self.assertEqual(m.nights_remaining_in_year(NEXT_YEAR), 50)
        self.assertEqual([ms.id for ms in m.memberships], [share.membership_id])

    def test_idempotent_und_ueberspringt_tandem_und_extern(self):
        # alice hat schon einen Anteil (UseCaseBase) -> kein zweiter
        self.assertIsNone(svc.ensure_personal_membership(self.alice))
        self.assertEqual(self.alice.shares.count(), 1)
        # Hofladen-Gast (extern) bekommt KEINEN Buchungs-Anteil
        ug = User.objects.create_user("gast", "g@e.org", "x" * 12)
        mg = Member.objects.create(user=ug, display_name="Gast", is_external=True)
        self.assertIsNone(svc.ensure_personal_membership(mg))
        self.assertFalse(mg.shares.exists())

    def test_wunsch_budget_ist_immer_haelfte_der_tage(self):
        """Wunsch-Budget = genau die Hälfte der Tage, abgerundet (ADR 0073)."""
        for nights, expect in [(50, 25), (25, 12), (35, 17), (1, 0)]:
            m = make_member(f"m{nights}", nights=nights)
            self.assertEqual(m.annual_night_budget, nights)
            self.assertEqual(m.wish_night_budget, expect)


class BuchungBestaetigungTests(UseCaseBase):
    """Buchen ist zweistufig: erst Bestätigungsseite, erst „confirm“ bucht –
    inklusive Begleitung und optionaler Endreinigung."""

    def setUp(self):
        super().setUp()
        self.open_full_year_window(NEXT_YEAR)
        from shop.models import Product, ProductGroup
        g = ProductGroup.objects.create(name="Dienstleistungen")
        self.clean = Product.objects.create(
            group=g, name="Endreinigung", price="45.00", unit="portion",
            vat_rate=19, kind="dienstleistung", needs_date=True,
            book_with_stay=True)
        self.s = date(NEXT_YEAR, 4, 6)
        self.e = date(NEXT_YEAR, 4, 13)  # 7 Nächte (über jeden Mindestaufenthalt)

    def _client(self):
        from django.test import Client
        c = Client()
        c.force_login(self.alice.user)
        return c

    def test_get_zeigt_seite_ohne_zu_buchen(self):
        c = self._client()
        r = c.get(reverse("book_confirm"), {
            "quarter": self.k1.id, "start": self.s.isoformat(),
            "end": self.e.isoformat(), "persons": 2})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "K1")
        self.assertEqual(Allocation.objects.count(), 0)  # noch nichts gebucht

    def test_confirm_bucht_mit_begleitung_und_endreinigung(self):
        from shop.models import LineItem
        c = self._client()
        r = c.post(reverse("book_confirm"), {
            "action": "confirm", "quarter": self.k1.id,
            "start": self.s.isoformat(), "end": self.e.isoformat(),
            "persons": 2, "companions": "Familie Muster",
            f"service_{self.clean.id}": "on"})
        a = Allocation.objects.get()
        self.assertEqual(a.companions, "Familie Muster")
        self.assertEqual(a.persons, 2)
        # Endreinigung als offene Hofladen-Position mit Abreise-Termin
        li = LineItem.objects.get(member=self.alice, product=self.clean)
        self.assertEqual(li.service_date, self.e)

    def test_endreinigung_an_gesperrtem_abreisetag_nicht_mitgebucht(self):
        from shop.models import LineItem
        self.clean.unavailable_weekdays = str(self.e.weekday())
        self.clean.save()
        c = self._client()
        c.post(reverse("book_confirm"), {
            "action": "confirm", "quarter": self.k1.id,
            "start": self.s.isoformat(), "end": self.e.isoformat(),
            "persons": 2, f"service_{self.clean.id}": "on"})
        # Buchung entsteht, Endreinigung aber NICHT (Wochentag gesperrt)
        self.assertEqual(Allocation.objects.count(), 1)
        self.assertEqual(LineItem.objects.filter(product=self.clean).count(), 0)


class WunschSaisonTests(UseCaseBase):
    """Der GESAMTE Wunschzeitraum muss innerhalb der Quartier-Saison liegen –
    sonst könnte ein Losgewinn eine Buchung außerhalb der Saison erzeugen."""

    def setUp(self):
        super().setUp()
        # qa nur im 1. Halbjahr buchbar (Saison 1.1.–30.6.)
        self.qa.season_start_month, self.qa.season_start_day = 1, 1
        self.qa.season_end_month, self.qa.season_end_day = 6, 30
        self.qa.save()
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def test_wunsch_ueber_saisongrenze_abgelehnt(self):
        # Start in Saison (28.6.), Ende außerhalb (3.7.) -> abgelehnt
        w, err = svc.add_wish(self.alice, self.period, self.qa,
                              date(NEXT_YEAR, 6, 28), date(NEXT_YEAR, 7, 3))
        self.assertIsNone(w)
        self.assertIn("Saison", err)
        # vollständig in Saison -> ok
        w2, err2 = svc.add_wish(self.alice, self.period, self.qa,
                                date(NEXT_YEAR, 6, 20), date(NEXT_YEAR, 6, 25))
        self.assertIsNotNone(w2, err2)

    def test_losung_ueberspringt_wunsch_ausserhalb_saison(self):
        # Direkt (unter Umgehung von add_wish) einen Alt-Wunsch außerhalb der
        # Saison einreichen – die Losung darf ihn nicht zuteilen.
        Wish.objects.create(
            member=self.alice, period=self.period, quarter=self.qa,
            start=date(NEXT_YEAR, 6, 28), end=date(NEXT_YEAR, 7, 3),
            priority=1, submitted=True)
        svc.run_period_lottery(self.period, seed=1)
        self.assertEqual(
            Allocation.objects.filter(period=self.period, source="lottery").count(),
            0)

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
        # Wunsch-Budget = Hälfte der Tage, abgerundet (35 // 2 = 17), ADR 0073
        self.assertEqual(self.carla.wish_night_budget, 17)
        self.assertEqual(len(self.carla.memberships), 2)


# --------------------------------------------------------------------------- #
# Use-Case: Losung bestätigen / zurücknehmen (Review-Workflow)
# --------------------------------------------------------------------------- #

class LosungBestaetigungTests(UseCaseBase):
    def _period(self):
        return BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def _two_rivals(self, period):
        s = date(NEXT_YEAR, 5, 24)
        e = s + timedelta(days=4)
        svc.add_wish(self.alice, period, self.qa, s, e)
        svc.add_wish(self.bob, period, self.qa, s, e)
        svc.submit_wishlist(self.alice, period)
        svc.submit_wishlist(self.bob, period)
        return s, e

    def test_unbestaetigt_ist_unsichtbar_aber_blockiert(self):
        period = self._period()
        s, e = self._two_rivals(period)
        svc.run_period_lottery(period, seed=1)

        # Für Mitglieder unsichtbar (keine nicht-provisorische eigene Buchung) …
        visible = (self.alice.allocations.filter(provisional=False).count()
                   + self.bob.allocations.filter(provisional=False).count())
        self.assertEqual(visible, 0)
        # … existiert aber provisorisch und blockiert die Verfügbarkeit.
        self.assertEqual(
            Allocation.objects.filter(period=period, source="lottery").count(), 1)
        self.assertFalse(svc.quarter_is_free(self.qa, s, e))
        # Keine Benachrichtigung vor der Bestätigung.
        url = reverse("period_result", args=[period.id])
        self.assertEqual(Notification.objects.filter(url=url).count(), 0)

    def test_bestaetigen_macht_sichtbar_und_benachrichtigt_idempotent(self):
        period = self._period()
        self._two_rivals(period)
        run = svc.run_period_lottery(period, seed=1)
        svc.confirm_lottery(run)

        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.LOTTERY_DONE)
        self.assertEqual(
            Allocation.objects.filter(
                period=period, source="lottery", provisional=False).count(), 1)
        url = reverse("period_result", args=[period.id])
        n = Notification.objects.filter(url=url).count()
        self.assertEqual(n, 2)
        # Erneutes Bestätigen ändert nichts (idempotent).
        svc.confirm_lottery(run)
        self.assertEqual(Notification.objects.filter(url=url).count(), 2)
        # Nach Bestätigung ist Zurücknehmen gesperrt.
        run.refresh_from_db()
        ok, err = svc.rollback_lottery(run)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_zuruecknehmen_stellt_zustand_wieder_her(self):
        period = self._period()
        self._two_rivals(period)
        run = svc.run_period_lottery(period, seed=1)
        self.alice.refresh_from_db(); self.bob.refresh_from_db()
        self.assertGreater(max(self.alice.factor, self.bob.factor), 1.0)

        ok, err = svc.rollback_lottery(run)
        self.assertTrue(ok, err)
        self.alice.refresh_from_db(); self.bob.refresh_from_db()
        self.assertEqual(self.alice.factor, 1.0)
        self.assertEqual(self.bob.factor, 1.0)
        self.assertEqual(
            Allocation.objects.filter(period=period, source="lottery").count(), 0)
        period.refresh_from_db()
        self.assertEqual(period.status, BookingPeriod.LOTTERY_READY)
        self.assertEqual(period.runs.count(), 0)

    def test_rerun_summiert_karma_nicht_auf(self):
        period = self._period()
        self._two_rivals(period)
        svc.run_period_lottery(period, seed=1)
        self.alice.refresh_from_db(); self.bob.refresh_from_db()
        loser = self.alice if self.alice.factor > self.bob.factor else self.bob
        self.assertAlmostEqual(loser.factor, 1.1, places=5)
        # Erneuter Lauf (gleicher Seed) darf das Karma NICHT aufsummieren.
        svc.run_period_lottery(period, seed=1)
        loser.refresh_from_db()
        self.assertAlmostEqual(loser.factor, 1.1, places=5)


# --------------------------------------------------------------------------- #
# Use-Case: Verifizierbare Auslosung (Commit-Reveal, ADR 0062)
# --------------------------------------------------------------------------- #

class LosungVerifizierbarkeitTests(UseCaseBase):
    def _period(self):
        return BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def _two_rivals(self, period):
        s = date(NEXT_YEAR, 5, 24); e = s + timedelta(days=4)
        svc.add_wish(self.alice, period, self.qa, s, e)
        svc.add_wish(self.bob, period, self.qa, s, e)
        svc.submit_wishlist(self.alice, period)
        svc.submit_wishlist(self.bob, period)

    def test_commit_vorab_und_passt_zum_seed(self):
        period = self._period()
        # Commit beim Öffnen der Wünsche (vor der Ziehung) – idempotent.
        svc.ensure_seed_commit(period)
        commit1 = period.seed_commit
        self.assertTrue(commit1)
        self.assertIsNotNone(period.seed_committed_at)
        svc.ensure_seed_commit(period)
        self.assertEqual(period.seed_commit, commit1)  # idempotent
        # Die Prüfsumme passt zum (geheimen) Seed.
        from booking import lottery as L
        self.assertTrue(L.verify_commitment(period.seed, period.seed_commit))

    def test_ziehung_nutzt_committeten_seed(self):
        period = self._period()
        svc.ensure_seed_commit(period)
        committed = period.seed
        self._two_rivals(period)
        # Ein abweichend übergebener Seed darf den Commit NICHT aushebeln.
        run = svc.run_period_lottery(period, seed=committed + 999)
        period.refresh_from_db()
        self.assertEqual(period.seed, committed)
        self.assertEqual(run.seed, committed)

    def test_verify_period_lottery_und_command(self):
        period = self._period()
        self._two_rivals(period)
        svc.run_period_lottery(period, seed=7)
        rep = svc.verify_period_lottery(period)
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(rep["commit_ok"])
        self.assertTrue(rep["replay_ok"])
        # Das Kommando läuft fehlerfrei (Exit 0 = keine Exception).
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("verify_lottery", str(period.id), stdout=out)
        self.assertIn("reproduzierbar", out.getvalue())

    def test_commit_rechtzeitigkeit_wird_gemeldet(self):
        period = self._period()
        svc.ensure_seed_commit(period)          # committet heute (= wishlist_close)
        self._two_rivals(period)
        svc.run_period_lottery(period, seed=7)
        self.assertTrue(svc.verify_period_lottery(period)["commit_timely"])
        # Künstlich „spät": Wunschschluss VOR dem Commit-Zeitpunkt.
        period.wishlist_close = date.today() - timedelta(days=2)
        period.save(update_fields=["wishlist_close"])
        self.assertFalse(svc.verify_period_lottery(period)["commit_timely"])

    def test_admin_save_committet_seed_bei_wuenschen_offen(self):
        from django.contrib import admin as djadmin
        from booking.admin import BookingPeriodAdmin
        period = BookingPeriod(
            name="P", target_year=NEXT_YEAR + 5,
            start=date(NEXT_YEAR + 5, 1, 1), end=date(NEXT_YEAR + 6, 1, 1),
            status=BookingPeriod.WISHES_OPEN)
        BookingPeriodAdmin(BookingPeriod, djadmin.site).save_model(
            None, period, None, False)
        self.assertTrue(period.seed_commit)
        self.assertIsNotNone(period.seed_committed_at)


# --------------------------------------------------------------------------- #
# Use-Case: Losergebnis-Erklärung (warum bekommen / nicht bekommen, P2.6)
# --------------------------------------------------------------------------- #

class LosErgebnisErklaerungTests(UseCaseBase):
    def test_erklaerung_nennt_konkurrenz_und_belegung(self):
        period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s = date(NEXT_YEAR, 5, 24); e = s + timedelta(days=4)
        svc.add_wish(self.alice, period, self.qa, s, e)
        svc.add_wish(self.bob, period, self.qa, s, e)
        svc.submit_wishlist(self.alice, period)
        svc.submit_wishlist(self.bob, period)
        run = svc.run_period_lottery(period, seed=1)
        svc.confirm_lottery(run)
        url = reverse("period_result", args=[period.id])
        texts = " ".join(n.detail for n in Notification.objects.filter(url=url))
        # Gewinner: „sehr beliebt"-/Los-Hinweis; Verlierer: Gruppe-komplett-belegt.
        self.assertIn("sehr beliebt", texts)
        self.assertIn("gleichwertige Quartiersgruppe belegt", texts)


# --------------------------------------------------------------------------- #
# Use-Case: Wunsch-Koordination – unverbindliche Ausweich-Hinweise (P2.4)
# --------------------------------------------------------------------------- #

class WunschKoordinationTests(UseCaseBase):
    def _period(self):
        return BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def test_hinweis_auf_weniger_umkaempften_zeitraum(self):
        period = self._period()
        # Drei kurze Wünsche ballen sich auf EINEN Tag (s). Eine Verschiebung um
        # +2 Tage entgeht der Ballung → weniger Konkurrenz.
        s = date(NEXT_YEAR, 5, 10); e = s + timedelta(days=1)
        for m in (self.alice, self.bob, self.carla):
            Wish.objects.create(member=m, period=period, quarter=self.qa,
                                start=s, end=e, priority=1, submitted=True)
        decon = svc.wish_deconfliction(period, s, e)
        qid = str(self.qa.id)
        self.assertIn(qid, decon)
        self.assertEqual(decon[qid]["base"], 3)
        self.assertEqual(decon[qid]["best"]["count"], 0)
        self.assertNotEqual(decon[qid]["best"]["shift"], 0)

    def test_kein_hinweis_ohne_konkurrenz(self):
        period = self._period()
        s = date(NEXT_YEAR, 5, 10); e = s + timedelta(days=3)
        self.assertEqual(svc.wish_deconfliction(period, s, e), {})

    def test_wish_alternatives_zeitraum_und_gleichwertiges_quartier(self):
        """Je Wunsch: ist die Unterkunft im Zeitraum umkämpft, zeigt der Hinweis
        BEIDE Auswege – ein anderer Zeitraum für dieselbe Unterkunft UND ein
        gleichwertiges Quartier zur gleichen Zeit. Eigene Wünsche zählen nicht."""
        period = self._period()
        s = date(NEXT_YEAR, 5, 10); e = s + timedelta(days=1)   # 1 Nacht
        # Konkurrenz ANDERER Mitglieder auf k1 im selben Zeitraum
        for m in (self.bob, self.carla):
            Wish.objects.create(member=m, period=period, quarter=self.k1,
                                start=s, end=e, priority=1, submitted=True)
        # Alice' eigener (noch änderbarer) Wunsch auf k1
        aw = Wish.objects.create(member=self.alice, period=period, quarter=self.k1,
                                 start=s, end=e, priority=1, submitted=False)
        alts = svc.wish_alternatives(period, self.alice, [aw])
        self.assertIn(aw.id, alts)
        a = alts[aw.id]
        self.assertEqual(a["base"], 2)                       # zwei fremde Wünsche
        # gleichwertiges Quartier (k2/k3, gleiche Klasse) frei zur gleichen Zeit
        self.assertIsNotNone(a["quarter"])
        self.assertEqual(a["quarter"]["count"], 0)
        self.assertIn(a["quarter"]["quarter_id"], [self.k2.id, self.k3.id])
        # anderer Zeitraum derselben Unterkunft mit weniger Konflikten
        self.assertIsNotNone(a["time"])
        self.assertLess(a["time"]["count"], 2)

    def test_wish_alternatives_eigene_wuensche_zaehlen_nicht(self):
        """Nur fremde Wünsche sind „Konflikte"; ohne fremde Konkurrenz kein Hinweis."""
        period = self._period()
        s = date(NEXT_YEAR, 5, 10); e = s + timedelta(days=2)
        aw = Wish.objects.create(member=self.alice, period=period, quarter=self.qa,
                                 start=s, end=e, priority=1, submitted=False)
        # zweiter eigener Wunsch auf dasselbe Quartier/Zeit (eingereicht) – zählt NICHT
        Wish.objects.create(member=self.alice, period=period, quarter=self.qa,
                            start=s, end=e, priority=2, submitted=True)
        self.assertEqual(svc.wish_alternatives(period, self.alice, [aw]), {})


# --------------------------------------------------------------------------- #
# Use-Case: Danke für eine Tage-Übertragung (Wertschätzung, P2.7)
# --------------------------------------------------------------------------- #

class DankeFuerUebertragungTests(UseCaseBase):
    def test_danke_benachrichtigt_schenkende_idempotent(self):
        from booking.models import Notification
        t, err = svc.transfer_nights(self.alice, self.bob, 3, date.today().year)
        self.assertIsNotNone(t, err)
        n0 = Notification.objects.filter(member=self.alice).count()
        ok, err = svc.thank_for_transfer(self.bob, t.id)
        self.assertTrue(ok, err)
        self.assertEqual(Notification.objects.filter(member=self.alice).count(), n0 + 1)
        t.refresh_from_db()
        self.assertIsNotNone(t.thanked_at)
        # Zweites Danke ist gesperrt (idempotent).
        ok2, err2 = svc.thank_for_transfer(self.bob, t.id)
        self.assertFalse(ok2)
        self.assertEqual(Notification.objects.filter(member=self.alice).count(), n0 + 1)

    def test_nur_empfaenger_darf_danken(self):
        t, _ = svc.transfer_nights(self.alice, self.bob, 2, date.today().year)
        # carla war nicht beteiligt → darf nicht danken.
        ok, err = svc.thank_for_transfer(self.carla, t.id)
        self.assertFalse(ok)


# --------------------------------------------------------------------------- #
# Use-Case: Buchung anpassen (verlängern/verkürzen) + Wechselwunsch-Gruppen
# --------------------------------------------------------------------------- #

class BuchungAnpassenTests(UseCaseBase):
    def setUp(self):
        super().setUp()
        self.open_full_year_window(NEXT_YEAR)

    def test_verlaengern_wenn_frei(self):
        s = date(NEXT_YEAR, 6, 10)
        a, err = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=3))
        self.assertIsNotNone(a, err)
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=5))
        self.assertTrue(ok, err)
        a.refresh_from_db()
        self.assertEqual((a.end - a.start).days, 5)

    def test_verlaengern_blockiert_wenn_belegt(self):
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=3))
        svc.book_spontaneous(self.bob, self.k1, s + timedelta(days=3),
                             s + timedelta(days=6))
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=5))
        self.assertFalse(ok)

    def test_verkuerzen_meldet_allen_und_haelt_mindestnaechte(self):
        p = BookingPolicy.get_solo(); p.default_min_nights = 3; p.save()
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=7))
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=4))
        self.assertTrue(ok, err)
        a.refresh_from_db()
        self.assertEqual((a.end - a.start).days, 4)
        self.assertTrue(Notification.objects.filter(
            member=self.bob, message__icontains="Spontan frei").exists())
        # Wer verkürzt, bekommt selbst KEINE „spontan frei"-Meldung.
        self.assertFalse(Notification.objects.filter(
            member=self.alice, message__icontains="Spontan frei").exists())

    def test_verkuerzen_unter_mindestnaechte_blockiert(self):
        p = BookingPolicy.get_solo(); p.default_min_nights = 3; p.save()
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=5))
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=2))
        self.assertFalse(ok)
        self.assertIn("Mindestaufenthalt", err)

    def test_verkuerzen_zu_kurzfristig_blockiert(self):
        today = date.today()
        a = Allocation.objects.create(
            member=self.alice, quarter=self.k1, start=today + timedelta(days=3),
            end=today + timedelta(days=10), persons=1, source="spontaneous",
            provisional=False)
        ok, err = svc.adjust_allocation(
            self.alice, a.id, a.start, today + timedelta(days=6))
        self.assertFalse(ok)
        self.assertIn("Woche", err)

    def test_concurrent_split_exakt_vs_ueberlappend(self):
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=4))
        svc.book_spontaneous(self.bob, self.k2, s, s + timedelta(days=4))
        svc.book_spontaneous(self.carla, self.k3, s + timedelta(days=2),
                             s + timedelta(days=6))
        split = svc.concurrent_split(a)
        self.assertEqual([c.member.display_name for c in split["exact"]], ["bob"])
        self.assertEqual([c.member.display_name for c in split["overlap"]], ["carla"])

    def test_unterkunft_wechseln_meldet_altes_frei(self):
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=4))
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=4),
                                        new_quarter=self.k2)
        self.assertTrue(ok, err)
        a.refresh_from_db()
        self.assertEqual(a.quarter_id, self.k2.id)
        self.assertTrue(Notification.objects.filter(
            member=self.bob, message__icontains="Spontan frei").exists())

    def test_wechsel_auf_belegtes_quartier_blockiert(self):
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=4))
        svc.book_spontaneous(self.bob, self.k2, s, s + timedelta(days=4))
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=4),
                                        new_quarter=self.k2)
        self.assertFalse(ok)

    def test_personenzahl_aendern(self):
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=4),
                                    persons=2)
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=4),
                                        new_persons=3)
        self.assertTrue(ok, err)
        a.refresh_from_db()
        self.assertEqual(a.persons, 3)

    def test_personenzahl_ueber_max_blockiert(self):
        # Strikter Modus: kleinere Unterkünfte NICHT zulassen (ADR 0076).
        p = BookingPolicy.get_solo()
        p.allow_undersized_units = False
        p.save(update_fields=["allow_undersized_units"])
        s = date(NEXT_YEAR, 6, 10)
        a, _ = svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=4),
                                    persons=2)
        ok, err = svc.adjust_allocation(self.alice, a.id, s, s + timedelta(days=4),
                                        new_persons=99)
        self.assertFalse(ok)

    def test_freie_alternativen_listen(self):
        s = date(NEXT_YEAR, 6, 10)
        svc.book_spontaneous(self.alice, self.k1, s, s + timedelta(days=4))
        free = svc.free_quarters_for(s, s + timedelta(days=4), 2,
                                     exclude_id=self.k1.id)
        ids = {q.id for q in free}
        self.assertIn(self.k2.id, ids)
        self.assertNotIn(self.k1.id, ids)


# --------------------------------------------------------------------------- #
# Use-Case 15: Saison-Regeln greifen für die Wunschliste/Losung
#   (Beschluss: nur beim Eintragen/Einreichen prüfen, Los-Algorithmus unverändert)
# --------------------------------------------------------------------------- #

class WunschSaisonRegelnTests(UseCaseBase):
    """Die konfigurierten Saison-Mindestnächte werden beim Eintragen UND beim
    Einreichen der Wunschliste erzwungen – ein Losgewinn kann so nicht an einer
    Regel scheitern."""

    def setUp(self):
        super().setUp()
        SeasonRule.objects.create(
            name="Hochsaison", start_month=7, start_day=1, end_month=9, end_day=1,
            min_nights=7, active=True)
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def test_kurzer_wunsch_in_hochsaison_wird_abgelehnt(self):
        w, err = svc.add_wish(self.alice, self.period, self.qa,
                              date(NEXT_YEAR, 7, 10), date(NEXT_YEAR, 7, 14))  # 4<7
        self.assertIsNone(w)
        self.assertIn("7 Nächte", err)

    def test_langer_wunsch_in_hochsaison_ok(self):
        w, err = svc.add_wish(self.alice, self.period, self.qa,
                              date(NEXT_YEAR, 7, 10), date(NEXT_YEAR, 7, 17))  # 7
        self.assertIsNotNone(w, err)

    def test_wunsch_ausserhalb_saison_unveraendert(self):
        # Außerhalb der Saison gilt nur der Standard (3 Nächte)
        w, err = svc.add_wish(self.alice, self.period, self.qa,
                              date(NEXT_YEAR, 5, 10), date(NEXT_YEAR, 5, 14))  # 4
        self.assertIsNotNone(w, err)

    def test_einreichen_blockt_regelverletzenden_altwunsch(self):
        """Wunsch direkt angelegt (Regel danach ergänzt) -> Einreichen blockt alle."""
        from booking.models import Wish
        Wish.objects.create(
            member=self.alice, period=self.period, quarter=self.qa,
            start=date(NEXT_YEAR, 7, 10), end=date(NEXT_YEAR, 7, 14),
            priority=1, submitted=False)
        n, err = svc.submit_wishlist(self.alice, self.period)
        self.assertEqual(n, 0)
        self.assertIn("7 Nächte", err or "")
        self.assertFalse(Wish.objects.filter(
            member=self.alice, period=self.period, submitted=True).exists())

    def test_einreichen_ok_wenn_alle_wuensche_regelkonform(self):
        svc.add_wish(self.alice, self.period, self.qa,
                     date(NEXT_YEAR, 7, 10), date(NEXT_YEAR, 7, 17))  # 7 Nächte
        n, err = svc.submit_wishlist(self.alice, self.period)
        self.assertIsNone(err)
        self.assertEqual(n, 1)


# --------------------------------------------------------------------------- #
# Use-Case 16: Parallel-Limit/Aufenthaltsdeckel greifen auch in der LOSUNG
#   (Beschluss: gedeckelter Wunsch wird übersprungen – kein Verlust, kein Karma)
# --------------------------------------------------------------------------- #

class LosungDeckelTests(UseCaseBase):
    """Die Saison-Regeln über mehrere Buchungen (max. gleichzeitige Einheiten,
    Aufenthaltsdeckel) werden jetzt auch im Los-Algorithmus erzwungen."""

    def setUp(self):
        super().setUp()
        SeasonRule.objects.create(
            name="Sommerferien BB", start_month=7, start_day=1, end_month=9, end_day=1,
            max_parallel_units=2, max_stay_nights=14, active=True)
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def test_parallel_limit_in_losung_ueberspringt_ohne_karma(self):
        # Drei gleichzeitige Einheiten gewünscht -> Losung teilt nur zwei zu.
        s, e = date(NEXT_YEAR, 7, 13), date(NEXT_YEAR, 7, 20)  # 7 Nächte
        for q in (self.k1, self.k2, self.k3):
            svc.add_wish(self.alice, self.period, q, s, e)
        n, err = svc.submit_wishlist(self.alice, self.period)
        self.assertIsNone(err)
        svc.run_period_lottery(self.period, seed=1)
        allocs = Allocation.objects.filter(period=self.period, member=self.alice)
        self.assertEqual(allocs.count(), 2)        # Parallel-Limit 2
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.factor, 1.0)   # kein Verlust -> kein Karma

    def test_aufenthaltsdeckel_in_losung(self):
        # Drei nicht-überlappende Sommerwochen, Deckel 14 Nächte -> zwei Wochen ok.
        weeks = [(date(NEXT_YEAR, 7, 1), date(NEXT_YEAR, 7, 8)),
                 (date(NEXT_YEAR, 7, 8), date(NEXT_YEAR, 7, 15)),
                 (date(NEXT_YEAR, 7, 15), date(NEXT_YEAR, 7, 22))]
        for (s, e) in weeks:
            svc.add_wish(self.alice, self.period, self.k1, s, e)
        svc.submit_wishlist(self.alice, self.period)
        svc.run_period_lottery(self.period, seed=1)
        allocs = Allocation.objects.filter(period=self.period, member=self.alice)
        self.assertEqual(allocs.count(), 2)        # 14-Nächte-Deckel
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.factor, 1.0)


class LosungDeckelReihenfolgeTests(UseCaseBase):
    """Ein wegen Deckel übersprungener Wunsch übergeht die Partei NICHT: in
    derselben Losung wird der nächste (niedrigere) Wunsch derselben Partei geprüft
    und ggf. zugeteilt."""

    def setUp(self):
        super().setUp()
        SeasonRule.objects.create(
            name="Nur eine Einheit", start_month=7, start_day=1, end_month=9,
            end_day=1, max_parallel_units=1, active=True)
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=NEXT_YEAR,
            start=date(NEXT_YEAR, 1, 1), end=date(NEXT_YEAR + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def test_naechste_prioritaet_wird_in_derselben_losung_zugeteilt(self):
        wa = (date(NEXT_YEAR, 7, 6), date(NEXT_YEAR, 7, 13))   # Woche A
        wc = (date(NEXT_YEAR, 7, 20), date(NEXT_YEAR, 7, 27))  # Woche C (separat)
        svc.add_wish(self.alice, self.period, self.k1, *wa)   # Prio 1 (Woche A)
        svc.add_wish(self.alice, self.period, self.k2, *wa)   # Prio 2 (Woche A -> Deckel)
        svc.add_wish(self.alice, self.period, self.k3, *wc)   # Prio 3 (Woche C)
        svc.submit_wishlist(self.alice, self.period)
        svc.run_period_lottery(self.period, seed=1)
        allocs = list(Allocation.objects.filter(period=self.period, member=self.alice))
        quarters = {a.quarter_id for a in allocs}
        # Prio 1 + Prio 3 zugeteilt; Prio 2 (überlappend, Parallel-Limit 1) übersprungen
        self.assertEqual(len(allocs), 2)
        self.assertIn(self.k1.id, quarters)
        self.assertIn(self.k3.id, quarters)
        self.assertNotIn(self.k2.id, quarters)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.factor, 1.0)   # kein Verlust -> kein Karma


class DatenAufbewahrungTests(UseCaseBase):
    """DSGVO: das Aufräum-Kommando löscht/pseudonymisiert abgelaufene Daten
    anhand der RETENTION_*-Fristen; Rechnungsbezug bleibt unangetastet."""

    def _backdate(self, qs, **fields):
        # auto_now_add-Felder lassen sich nur per UPDATE in die Vergangenheit setzen.
        qs.update(**fields)

    def test_cleanup_loescht_abgelaufenes_und_behaelt_frisches(self):
        from booking.models import OutboxEmail, Beds24Import
        from shop.models import BankImport, BankTransaction
        now = timezone.now()
        old = now - timedelta(days=400)
        recent = now - timedelta(days=5)

        # OutboxEmail: alt+versendet -> weg, frisch -> bleibt, unversendet alt -> bleibt
        e_old = OutboxEmail.objects.create(to_email="a@x.de", subject="s", body="b")
        OutboxEmail.objects.filter(pk=e_old.pk).update(sent_at=old)
        e_new = OutboxEmail.objects.create(to_email="b@x.de", subject="s", body="b")
        OutboxEmail.objects.filter(pk=e_new.pk).update(sent_at=recent)
        e_unsent = OutboxEmail.objects.create(to_email="c@x.de", subject="s", body="b")
        OutboxEmail.objects.filter(pk=e_unsent.pk).update(created_at=old)

        # Notification: alt -> weg, frisch -> bleibt
        n_old = Notification.objects.create(member=self.alice, message="alt")
        Notification.objects.filter(pk=n_old.pk).update(created_at=old)
        n_new = Notification.objects.create(member=self.bob, message="neu")

        # BankTransaction.raw: alt -> Rohzeile geleert, strukturierte Felder bleiben
        bt = BankTransaction.objects.create(
            amount=10, purpose="HL-2020-01-001", fingerprint="fp1", raw="ROH;ZEILE")
        BankTransaction.objects.filter(pk=bt.pk).update(imported_at=old)

        # Beds24Import: alt -> weg
        b = Beds24Import.objects.create(filename="b.csv")
        Beds24Import.objects.filter(pk=b.pk).update(created_at=old)

        # BankImport: alt -> weg
        bi = BankImport.objects.create(filename="k.csv")
        BankImport.objects.filter(pk=bi.pk).update(created_at=old)

        # WaitlistEntry: erfüllt+alt -> weg, offen+alt -> bleibt
        w_done = WaitlistEntry.objects.create(
            member=self.alice, quarter=self.k1, start=date(2020, 1, 1),
            end=date(2020, 1, 5), fulfilled=True)
        WaitlistEntry.objects.filter(pk=w_done.pk).update(created_at=old)
        w_open = WaitlistEntry.objects.create(
            member=self.bob, quarter=self.k1, start=date(2020, 1, 1),
            end=date(2020, 1, 5), fulfilled=False)
        WaitlistEntry.objects.filter(pk=w_open.pk).update(created_at=old)

        # Wish einer längst beendeten Periode -> weg
        old_period = BookingPeriod.objects.create(
            name="alt", target_year=now.year - 3,
            start=date(now.year - 3, 1, 1), end=date(now.year - 2, 1, 1),
            status=BookingPeriod.ENDED)
        Wish.objects.create(member=self.alice, period=old_period, quarter=self.k1,
                            start=date(now.year - 3, 6, 1), end=date(now.year - 3, 6, 5))

        counts = svc.run_data_retention(now=now)

        self.assertFalse(OutboxEmail.objects.filter(pk=e_old.pk).exists())
        self.assertTrue(OutboxEmail.objects.filter(pk=e_new.pk).exists())
        self.assertTrue(OutboxEmail.objects.filter(pk=e_unsent.pk).exists())
        self.assertFalse(Notification.objects.filter(pk=n_old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=n_new.pk).exists())
        bt.refresh_from_db()
        self.assertEqual(bt.raw, "")            # Rohzeile geleert
        self.assertEqual(bt.purpose, "HL-2020-01-001")  # struktur bleibt
        self.assertFalse(Beds24Import.objects.filter(pk=b.pk).exists())
        self.assertFalse(BankImport.objects.filter(pk=bi.pk).exists())
        self.assertFalse(WaitlistEntry.objects.filter(pk=w_done.pk).exists())
        self.assertTrue(WaitlistEntry.objects.filter(pk=w_open.pk).exists())
        self.assertEqual(Wish.objects.filter(period=old_period).count(), 0)
        self.assertGreaterEqual(counts["outbox_emails"], 1)

    def test_cleanup_ist_idempotent(self):
        # Zweiter Lauf ohne abgelaufene Daten ändert nichts und wirft nicht.
        first = svc.run_data_retention()
        second = svc.run_data_retention()
        self.assertIsInstance(first, dict)
        self.assertIsInstance(second, dict)


class MitgliedAnonymisierenTests(UseCaseBase):
    """Recht auf Löschung (Art. 17): PII entfernen, Rechnungen erhalten."""

    def test_anonymisieren_entfernt_pii_und_behaelt_rechnung(self):
        from shop.models import Invoice
        m = make_member("dora")
        m.legal_name = "Dora Vollname"
        m.street = "Hofweg 1"; m.zip_code = "12345"; m.city = "Dorf"
        m.iban = "DE02120300000000202051"
        m.save()
        self.open_full_year_window(date.today().year)
        alloc = Allocation.objects.create(
            member=m, quarter=self.k1, start=date.today(),
            end=date.today() + timedelta(days=3), source="spontaneous",
            companions="Oma und Opa")
        Notification.objects.create(member=m, message="hallo")
        # Eine Rechnung (Snapshot) muss erhalten bleiben.
        inv = Invoice.objects.create(
            member=m, number="HL-2024-01-001", year=2024, month=1,
            recipient_name="Dora Vollname", recipient_address="Hofweg 1\n12345 Dorf")

        svc.anonymize_member(m)

        m.refresh_from_db()
        self.assertEqual(m.legal_name, "")
        self.assertEqual(m.iban, "")
        self.assertEqual(m.street, "")
        self.assertTrue(m.display_name.startswith("Anonymisiert"))
        alloc.refresh_from_db()
        self.assertEqual(alloc.companions, "")          # Freitext-PII geleert
        self.assertEqual(Notification.objects.filter(member=m).count(), 0)
        # Login deaktiviert + de-personalisiert
        m.user.refresh_from_db()
        self.assertFalse(m.user.is_active)
        self.assertEqual(m.user.email, "")
        self.assertTrue(m.user.username.startswith("geloescht_"))
        self.assertFalse(m.user.has_usable_password())
        # Rechnung + Snapshot bleiben (10-Jahres-Pflicht)
        inv.refresh_from_db()
        self.assertEqual(inv.recipient_name, "Dora Vollname")
        self.assertEqual(inv.recipient_address, "Hofweg 1\n12345 Dorf")

    def test_admin_aktion_mit_rueckfrage_anonymisiert(self):
        """Die Admin-Aktion zeigt erst eine Rückfrage und anonymisiert nach
        Bestätigung (confirm)."""
        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        admin = User.objects.create_superuser("root", "root@example.org", "x" * 12)
        self.client.force_login(admin)
        m = make_member("ed")
        m.legal_name = "Ed Voll"; m.iban = "DE02120300000000202051"; m.save()
        url = reverse("admin:auth_user_changelist")
        # 1) Ohne confirm -> Zwischenseite (Rückfrage), noch nichts geändert
        resp = self.client.post(url, {
            "action": "anonymize_selected",
            ACTION_CHECKBOX_NAME: [str(m.user_id)]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "wirklich anonymisieren")
        m.refresh_from_db()
        self.assertEqual(m.legal_name, "Ed Voll")     # unverändert
        # 2) Mit confirm -> anonymisiert
        resp = self.client.post(url, {
            "action": "anonymize_selected", "confirm": "1",
            ACTION_CHECKBOX_NAME: [str(m.user_id)]}, follow=True)
        m.refresh_from_db()
        self.assertEqual(m.legal_name, "")
        self.assertEqual(m.iban, "")


class WebPushTests(UseCaseBase):
    """Web-Push-Abo speichern/entfernen und sicheres Verhalten ohne VAPID-Keys."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice.user)

    def _sub(self, endpoint="https://push.example/abc"):
        import json
        return self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"endpoint": endpoint,
                             "keys": {"p256dh": "KEYDATA", "auth": "AUTHSECRET"}}),
            content_type="application/json")

    def test_abo_anlegen_und_aktualisieren(self):
        from booking.models import PushSubscription
        r = self._sub()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(member=self.alice).count(), 1)
        # gleicher Endpoint -> Update statt Duplikat
        r2 = self._sub()
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(member=self.alice).count(), 1)

    def test_abmelden_entfernt_abo(self):
        import json
        from booking.models import PushSubscription
        self._sub("https://push.example/xyz")
        r = self.client.post(
            reverse("push_unsubscribe"),
            data=json.dumps({"endpoint": "https://push.example/xyz"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_ungueltige_daten_abgelehnt(self):
        import json
        r = self.client.post(reverse("push_subscribe"),
                             data=json.dumps({"foo": "bar"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_send_web_push_ohne_keys_ist_geraeuschlos(self):
        # Ohne VAPID-Keys (Default in Tests) tut der Versand nichts und wirft nicht.
        from booking.models import PushSubscription, Notification
        PushSubscription.objects.create(
            member=self.alice, endpoint="https://push.example/1",
            p256dh="k", auth="a")
        self.assertEqual(svc.send_web_push(self.alice, "T", "B", "/"), 0)
        # Auch das Anlegen einer Benachrichtigung (Signal) bleibt fehlerfrei.
        Notification.objects.create(member=self.alice, message="hallo")


class AdminBuchungsregelnTests(UseCaseBase):
    """Domänenregeln greifen auch bei manueller Pflege (Allocation.clean):
    keine Doppelbuchung – weder per full_clean noch über den Django-Admin."""

    def test_ueberlappende_zuteilung_wird_abgelehnt(self):
        from django.core.exceptions import ValidationError
        Allocation.objects.create(
            member=self.alice, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 1), end=date(2026, 7, 8))
        clash = Allocation(
            member=self.bob, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 5), end=date(2026, 7, 10))
        with self.assertRaises(ValidationError):
            clash.full_clean()

    def test_nicht_ueberlappende_zuteilung_ist_ok(self):
        Allocation.objects.create(
            member=self.alice, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 1), end=date(2026, 7, 8))
        ok = Allocation(
            member=self.bob, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 8), end=date(2026, 7, 12))   # Anschluss, kein Overlap
        ok.full_clean()   # darf NICHT werfen

    def test_bestehende_zuteilung_bearbeiten_kein_selbstkonflikt(self):
        a = Allocation.objects.create(
            member=self.alice, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 1), end=date(2026, 7, 8))
        a.persons = 3
        a.full_clean()   # sich selbst nicht als Konflikt werten

    def test_ungueltiger_zeitraum_wird_abgelehnt(self):
        from django.core.exceptions import ValidationError
        a = Allocation(
            member=self.alice, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 8), end=date(2026, 7, 1))
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_personenzahl_ausserhalb_quartiersrahmen_abgelehnt(self):
        from django.core.exceptions import ValidationError
        # Strikter Modus: kleinere Unterkünfte NICHT zulassen (ADR 0076).
        p = BookingPolicy.get_solo()
        p.allow_undersized_units = False
        p.save(update_fields=["allow_undersized_units"])
        a = Allocation(
            member=self.alice, quarter=self.k1, persons=99, source="spontaneous",
            start=date(2026, 7, 1), end=date(2026, 7, 8))
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_admin_lehnt_doppelbuchung_ab(self):
        admin = User.objects.create_superuser("root2", "root2@example.org", "x" * 12)
        self.client.force_login(admin)
        Allocation.objects.create(
            member=self.alice, quarter=self.k1, persons=2, source="spontaneous",
            start=date(2026, 7, 1), end=date(2026, 7, 8))
        resp = self.client.post("/admin/booking/allocation/add/", {
            "member": self.bob.user.member.id, "quarter": self.k1.id,
            "start": "2026-07-05", "end": "2026-07-10",
            "persons": "2", "source": "spontaneous", "companions": "",
            "_save": "Sichern",
        })
        self.assertEqual(resp.status_code, 200)   # Formular mit Fehler, kein Redirect
        self.assertEqual(
            Allocation.objects.filter(member=self.bob, quarter=self.k1).count(), 0)


# --------------------------------------------------------------------------- #
# Use-Case: „Diese Woche"-Agenda der Übersicht (ADR 0059)
# --------------------------------------------------------------------------- #

class WochenAgendaTests(UseCaseBase):
    def test_agenda_bucketet_anreise_abreise_und_zaehlt_frei(self):
        """week_agenda ordnet An-/Abreisen dem richtigen Tag zu und zählt freie
        Quartiere pro Tag."""
        self.open_full_year_window(NEXT_YEAR)
        start = date(NEXT_YEAR, 5, 4)            # ein fester Wochentag
        end = start + timedelta(days=3)
        a, err = svc.book_spontaneous(self.alice, self.k1, start, end)
        self.assertIsNotNone(a, err)

        agenda = svc.week_agenda(self.alice, start, 7)
        self.assertEqual(len(agenda), 7)
        # Tag 0 = Anreise alice -> K1; als „heute" (start) markiert
        day0 = agenda[0]
        self.assertTrue(day0["is_today"])
        self.assertEqual(len(day0["arrivals"]), 1)
        self.assertEqual(day0["arrivals"][0]["quarter"], "K1")
        self.assertTrue(day0["arrivals"][0]["mine"])
        self.assertEqual(day0["departures"], [])
        # während der Buchung ist K1 belegt -> ein Quartier weniger frei
        total_q = 5
        self.assertEqual(day0["free_count"], total_q - 1)
        # Abreisetag (Tag 3) trägt die Abreise, K1 wieder frei
        day3 = agenda[3]
        self.assertEqual(len(day3["departures"]), 1)
        self.assertEqual(day3["arrivals"], [])
        self.assertEqual(day3["free_count"], total_q)


# --------------------------------------------------------------------------- #
# Use-Case: Belegungs-Cache korrekt invalidiert (ADR 0060)
# --------------------------------------------------------------------------- #

class BelegungsCacheTests(UseCaseBase):
    def test_cache_zeigt_buchung_erst_nach_invalidierung(self):
        """Mit aktivem (geteiltem) Cache liefert _occupied_days_by_quarter erst
        nach Versions-Bump die neue Buchung – die Invalidierung greift."""
        from unittest.mock import patch
        from django.core.cache import cache
        from booking.services import slots
        cache.clear()
        first, last = date(NEXT_YEAR, 7, 1), date(NEXT_YEAR, 7, 31)
        with patch.object(slots, "_occ_cache_on", return_value=True):
            occ0 = slots._occupied_days_by_quarter(first, last)
            self.assertEqual(sum(len(v) for v in occ0.values()), 0)   # nichts belegt → gecacht
            self.open_full_year_window(NEXT_YEAR)
            svc.book_spontaneous(self.alice, self.k1,
                                 date(NEXT_YEAR, 7, 10), date(NEXT_YEAR, 7, 13))
            # ohne Invalidierung weiterhin der alte (leere) Stand aus dem Cache
            self.assertEqual(
                sum(len(v) for v in slots._occupied_days_by_quarter(first, last).values()), 0)
            slots.bump_occupancy_version()
            # nach Bump wird neu gerechnet → 3 belegte Nächte sichtbar
            self.assertEqual(
                sum(len(v) for v in slots._occupied_days_by_quarter(first, last).values()), 3)
        cache.clear()
