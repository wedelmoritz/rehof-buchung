"""
Django-Integrationstests für die DB-Logik rund um Buchungszeiträume und
Tage-Übertragung.

Lauf:  python manage.py test booking
(Diese Tests brauchen Django + DB; die reine Algorithmus-Logik wird separat
unter tests/ mit pytest geprüft.)
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from booking.models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass,
    Member, Membership, NightTransfer, Quarter, SeasonRule, Share, Wish,
)
from booking.services import (
    book_spontaneous, run_period_lottery, transfer_nights,
)
from booking import services as svc

YEAR = date.today().year


def make_member(name, nights=50, wish=25, **kwargs):
    """Legt einen Nutzer als Voll-Mitglied an (eigener Anteil mit `nights` Tagen)."""
    u = User.objects.create_user(username=name, password="x" * 12)
    m = Member.objects.create(user=u, display_name=name, **kwargs)
    ms = Membership.objects.create(
        eg_number=f"EG-{name}", label=name,
        annual_night_budget=nights, wish_night_budget=wish)
    Share.objects.create(membership=ms, member=m,
                         night_budget=nights, wish_night_budget=wish)
    return m


def release_period(name, start, end, active=True):
    """Legt die (globale) Periode an, die den Zeitraum zur freien Buchung
    freigibt (Status „Freie Bebuchbarkeit“; bei active=False „Unterbrochen“ =
    gesperrt). Pro Jahr gibt es genau eine Periode."""
    return BookingPeriod.objects.create(
        name=name, target_year=start.year, start=start, end=end,
        status=BookingPeriod.FREE_BOOKING if active else BookingPeriod.SUSPENDED,
    )


class BaseData(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="Test")
        self.q1 = Quarter.objects.create(
            name="Q1", eq_class=self.cls, min_occupancy=1, max_occupancy=4)
        self.q2 = Quarter.objects.create(
            name="Q2", eq_class=self.cls, min_occupancy=1, max_occupancy=4)
        self.q3 = Quarter.objects.create(
            name="Q3", eq_class=self.cls, min_occupancy=1, max_occupancy=4)
        self.alice = make_member("alice")
        self.bob = make_member("bob")
        # Spontan-Vorausfrist in den Alt-Tests aus (sie buchen bewusst nah/
        # vergangen); die Frist hat eine eigene Testklasse. ADR 0075.
        p = BookingPolicy.get_solo()
        p.min_lead_days = 0
        p.save(update_fields=["min_lead_days"])


class BookingWindowTests(BaseData):
    def test_keine_buchung_ohne_freigeschalteten_zeitraum(self):
        """Ohne Buchungszeitraum ist Spontanbuchung gesperrt."""
        start = date(YEAR, 6, 1)
        alloc, err = book_spontaneous(self.alice, self.q1, start,
                                      start + timedelta(days=3))
        self.assertIsNone(alloc)
        self.assertIn("freigeschaltet", err)

    def test_buchung_im_globalen_zeitraum(self):
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
        start = date(YEAR, 6, 1)
        alloc, err = book_spontaneous(self.alice, self.q1, start,
                                      start + timedelta(days=3))
        self.assertIsNotNone(alloc, err)
        self.assertEqual(alloc.nights, 3)

    def test_teilmengen_einschraenkung(self):
        """Global Jan–Dez, aber Q1 hat eine Quartier-Saison (nur Juni). Buchung
        von Q1 im Mai scheitert, im Juni klappt sie; Q2 (keine Saison) klappt
        auch im Mai. (Quartiersspezifische Grenzen kommen jetzt aus der
        Quartier-Saison, nicht mehr aus einer eigenen Periode.)"""
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
        self.q1.season_start_month = 6
        self.q1.season_start_day = 1
        self.q1.season_end_month = 6
        self.q1.season_end_day = 30
        self.q1.save()

        # Q1 im Mai: gesperrt
        may = date(YEAR, 5, 10)
        alloc, err = book_spontaneous(self.alice, self.q1, may,
                                      may + timedelta(days=3))
        self.assertIsNone(alloc)

        # Q1 im Juni: frei
        jun = date(YEAR, 6, 10)
        alloc, err = book_spontaneous(self.alice, self.q1, jun,
                                      jun + timedelta(days=3))
        self.assertIsNotNone(alloc, err)

        # Q2 im Mai: frei (keine Einschränkung)
        alloc2, err2 = book_spontaneous(self.bob, self.q2, may,
                                        may + timedelta(days=3))
        self.assertIsNotNone(alloc2, err2)

    def test_gesperrtes_fenster_blockt(self):
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1),
                       active=False)  # gesperrt (Status „Unterbrochen“)
        start = date(YEAR, 6, 1)
        alloc, err = book_spontaneous(self.alice, self.q1, start,
                                      start + timedelta(days=3))
        self.assertIsNone(alloc)

    def test_doppelbuchung_wird_verhindert(self):
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
        start = date(YEAR, 6, 1)
        a1, _ = book_spontaneous(self.alice, self.q1, start,
                                 start + timedelta(days=3))
        self.assertIsNotNone(a1)
        # Bob will denselben Zeitraum -> belegt
        a2, err = book_spontaneous(self.bob, self.q1, start,
                                   start + timedelta(days=3))
        self.assertIsNone(a2)
        self.assertIn("belegt", err)


class UnavailableQuartersTests(BaseData):
    """B6/ADR 0092: nicht-buchbare Quartiere werden mit Grund ausgewiesen."""

    def test_saison_gibt_grund_mit_zeitraum(self):
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
        # Q1 nur im Juni buchbar.
        self.q1.season_start_month, self.q1.season_start_day = 6, 1
        self.q1.season_end_month, self.q1.season_end_day = 6, 30
        self.q1.save()
        may = date(YEAR, 5, 10)
        rows = svc.unavailable_quarters_for_range(may, may + timedelta(days=3))
        by_q = {q.id: reason for q, reason in rows}
        self.assertIn(self.q1.id, by_q)                 # Q1 wegen Saison ausgegraut
        self.assertIn("saisonal", by_q[self.q1.id].lower())
        self.assertIn("01.06.", by_q[self.q1.id])       # Saison-Zeitraum im Text
        self.assertNotIn(self.q2.id, by_q)              # Q2 ganzjährig -> nicht hier

    def test_nicht_freigeschaltet_gibt_grund(self):
        # Keine Periode freigegeben -> alle aktiven Quartiere nicht verfügbar.
        may = date(YEAR, 5, 10)
        rows = svc.unavailable_quarters_for_range(may, may + timedelta(days=3))
        reasons = {reason for _q, reason in rows}
        self.assertTrue(any("freigeschaltet" in r for r in reasons))


class NightTransferTests(BaseData):
    def setUp(self):
        super().setUp()
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1))

    def test_uebertragung_aendert_budgets(self):
        self.assertEqual(self.alice.nights_remaining_in_year(YEAR), 50)
        self.assertEqual(self.bob.nights_remaining_in_year(YEAR), 50)
        t, err = transfer_nights(self.alice, self.bob, 10, YEAR)
        self.assertIsNotNone(t, err)
        self.assertEqual(self.alice.nights_remaining_in_year(YEAR), 40)
        self.assertEqual(self.bob.nights_remaining_in_year(YEAR), 60)

    def test_kann_nicht_mehr_uebertragen_als_verfuegbar(self):
        t, err = transfer_nights(self.alice, self.bob, 60, YEAR)
        self.assertIsNone(t)
        self.assertIn("Nicht genügend", err)

    def test_uebertragung_an_sich_selbst_unzulaessig(self):
        t, err = transfer_nights(self.alice, self.alice, 5, YEAR)
        self.assertIsNone(t)

    def test_empfaenger_kann_mehr_buchen(self):
        # Bob bekommt 10 Tage -> kann 60 statt 50 buchen
        transfer_nights(self.alice, self.bob, 10, YEAR)
        # eine 55-Nächte-Buchung wäre ohne Übertragung unmöglich, mit möglich
        start = date(YEAR, 1, 2)
        alloc, err = book_spontaneous(self.bob, self.q1, start,
                                      start + timedelta(days=55))
        self.assertIsNotNone(alloc, err)

    def test_kein_uebertrag_ins_folgejahr(self):
        """Tage gelten je Kalenderjahr frisch; eine Buchung im Vorjahr
        beeinflusst das Folgejahr nicht."""
        # Buchung im laufenden Jahr verbraucht Tage in YEAR …
        start = date(YEAR, 1, 2)
        alloc, err = book_spontaneous(self.alice, self.q1, start,
                                      start + timedelta(days=10))
        self.assertIsNotNone(alloc, err)
        self.assertEqual(self.alice.nights_remaining_in_year(YEAR), 40)
        # … aber im Folgejahr stehen wieder volle 50 zur Verfügung.
        self.assertEqual(self.alice.nights_remaining_in_year(YEAR + 1), 50)


class LotteryWindowIndependenceTests(BaseData):
    def test_losung_vergibt_folgejahr_ohne_freigeschalteten_zeitraum(self):
        """Das Losverfahren vergibt das nächste Jahr, obwohl dafür KEIN
        Buchungszeitraum freigeschaltet ist (Zeitlogik: Losung im Sommer
        fürs Folgejahr)."""
        next_year = YEAR + 1
        period = BookingPeriod.objects.create(
            name="Losung", target_year=next_year,
            start=date(next_year, 1, 1), end=date(next_year + 1, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)
        s = date(next_year, 5, 24)
        Wish.objects.create(period=period, member=self.alice, priority=1,
                            quarter=self.q1, start=s, end=s + timedelta(days=5),
                            submitted=True)
        Wish.objects.create(period=period, member=self.bob, priority=1,
                            quarter=self.q1, start=s, end=s + timedelta(days=5),
                            submitted=True)
        # KEINE freigeschaltete Periode fürs Folgejahr (nur Wunsch-Phase)
        self.assertEqual(
            BookingPeriod.objects.filter(
                status=BookingPeriod.FREE_BOOKING).count(), 0)

        run = run_period_lottery(period, seed=1)
        allocs = Allocation.objects.filter(period=period, source="lottery")
        # Beide bekommen etwas (Q1 + Ausweich Q2), trotz fehlender Freischaltung
        self.assertEqual(allocs.count(), 2)
        self.assertTrue(run.summary)


class SeasonRuleTests(BaseData):
    """Saison-Regeln (Mindestnächte, Parallel-Limit, Aufenthaltsdeckel) im
    Zusammenspiel mit der echten Buchung über den Service."""

    def setUp(self):
        super().setUp()
        # Ganzjährig freigeschaltet, damit nur die Saison-Regeln greifen
        release_period("global", date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
        # Standard-Mindestnächte 3
        p = BookingPolicy.get_solo()
        p.default_min_nights = 3
        p.save()

    def test_standard_mindestbuchung_3(self):
        start = date(YEAR, 6, 2)
        a, err = book_spontaneous(self.alice, self.q1, start,
                                  start + timedelta(days=2))  # 2 Nächte
        self.assertIsNone(a)
        self.assertIn("Mindestbuchung", err)
        a, err = book_spontaneous(self.alice, self.q1, start,
                                  start + timedelta(days=3))  # 3 Nächte ok
        self.assertIsNotNone(a, err)

    def test_juli_mindestens_7_naechte(self):
        SeasonRule.objects.create(
            name="Hochsaison", start_month=7, start_day=1, end_month=9, end_day=1,
            min_nights=7, active=True)
        start = date(YEAR, 7, 10)
        a, err = book_spontaneous(self.alice, self.q1, start,
                                  start + timedelta(days=5))  # 5 < 7
        self.assertIsNone(a)
        self.assertIn("7 Nächte", err)
        a, err = book_spontaneous(self.alice, self.q1, start,
                                  start + timedelta(days=7))
        self.assertIsNotNone(a, err)

    def test_max_zwei_parallele_einheiten_in_pfingsten(self):
        SeasonRule.objects.create(
            name="Pfingsten", start_month=5, start_day=22, end_month=5, end_day=27,
            max_parallel_units=2, active=True)
        s, e = date(YEAR, 5, 23), date(YEAR, 5, 26)
        a1, _ = book_spontaneous(self.alice, self.q1, s, e)
        a2, _ = book_spontaneous(self.alice, self.q2, s, e)
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)  # zwei parallel ok
        a3, err = book_spontaneous(self.alice, self.q3, s, e)
        self.assertIsNone(a3)  # dritte parallele Einheit -> abgelehnt
        self.assertIn("gleichzeitig", err)

    def test_sommerferien_deckel_14(self):
        SeasonRule.objects.create(
            name="Sommerferien BB", start_month=7, start_day=9,
            end_month=8, end_day=23, max_parallel_units=2, max_stay_nights=14,
            active=True)
        # 14 Nächte am Stück: ok
        a, err = book_spontaneous(self.alice, self.q1, date(YEAR, 7, 10),
                                  date(YEAR, 7, 24))
        self.assertIsNotNone(a, err)
        # eine weitere Nacht im Sommer -> Deckel überschritten
        a2, err = book_spontaneous(self.alice, self.q2, date(YEAR, 8, 1),
                                   date(YEAR, 8, 4))
        self.assertIsNone(a2)
        self.assertIn("je Partei", err)

    def test_sommerferien_eine_woche_zwei_einheiten(self):
        SeasonRule.objects.create(
            name="Sommerferien BB", start_month=7, start_day=9,
            end_month=8, end_day=23, max_parallel_units=2, max_stay_nights=14,
            active=True)
        # Woche 1 in Q1 (7 Nächte) + Woche 1 in Q2 parallel (7 Nächte) = 14: ok
        s, e = date(YEAR, 7, 10), date(YEAR, 7, 17)
        a1, err1 = book_spontaneous(self.alice, self.q1, s, e)
        a2, err2 = book_spontaneous(self.alice, self.q2, s, e)
        self.assertIsNotNone(a1, err1)
        self.assertIsNotNone(a2, err2)
        # dritte parallele Woche -> Parallel-Limit (2) verletzt
        a3, err3 = book_spontaneous(self.alice, self.q3, s, e)
        self.assertIsNone(a3)


class CalendarAndWishlistTests(BaseData):
    """Stornierung, Wunschlisten-Einreichung (Lostopf) und Reihenfolge."""

    def setUp(self):
        super().setUp()
        release_period("global", date(YEAR, 1, 1), date(YEAR + 2, 1, 1))
        self.period = BookingPeriod.objects.create(
            name="Losung", target_year=YEAR + 1,
            start=date(YEAR + 1, 1, 1), end=date(YEAR + 2, 1, 1),
            wishlist_open=date.today(), wishlist_close=date.today(),
            status=BookingPeriod.WISHES_OPEN)

    def test_stornierung_entfernt_zukuenftige_buchung(self):
        start = date(YEAR + 1, 3, 1)  # in der Zukunft
        a, err = book_spontaneous(self.alice, self.q1, start,
                                  start + timedelta(days=4))
        self.assertIsNotNone(a, err)
        ok, err = svc.cancel_allocation(self.alice, a.id)
        self.assertTrue(ok, err)
        self.assertFalse(Allocation.objects.filter(id=a.id).exists())

    def test_storno_nur_eigene_buchung(self):
        start = date(YEAR + 1, 3, 1)
        a, _ = book_spontaneous(self.alice, self.q1, start,
                                start + timedelta(days=4))
        ok, err = svc.cancel_allocation(self.bob, a.id)  # Bob ist nicht Eigentümer
        self.assertFalse(ok)

    def test_nur_eingereichte_wuensche_kommen_in_die_losung(self):
        s = date(YEAR + 1, 5, 24)
        # Alice reicht ein, Bob bleibt Entwurf
        svc.add_wish(self.alice, self.period, self.q1, s, s + timedelta(days=5))
        svc.add_wish(self.bob, self.period, self.q1, s, s + timedelta(days=5))
        svc.submit_wishlist(self.alice, self.period)
        run = run_period_lottery(self.period, seed=1)
        winners = set(
            Allocation.objects.filter(period=self.period, source="lottery")
            .values_list("member__display_name", flat=True))
        self.assertIn("alice", winners)
        self.assertNotIn("bob", winners)  # Entwurf nimmt nicht teil

    def test_losung_erzwingt_saison_parallel_limit_NICHT(self):
        """Charakterisierung des bekannten offenen Punkts (Roadmap): die Losung
        setzt Saison-Parallel-Limits (noch) NICHT durch – anders als die
        Spontanbuchung. Bricht dieser Test, wurde die Durchsetzung ergänzt und
        die Roadmap ist zu aktualisieren."""
        SeasonRule.objects.create(
            name="Pfingsten", start_month=5, start_day=22, end_month=5, end_day=27,
            max_parallel_units=2, active=True)
        s = date(YEAR + 1, 5, 23)
        e = s + timedelta(days=3)
        carol = make_member("carol")
        for m in (self.alice, self.bob, carol):
            svc.add_wish(m, self.period, self.q1, s, e)
            svc.submit_wishlist(m, self.period)
        run_period_lottery(self.period, seed=1)
        # Drei parallele Einheiten trotz max_parallel_units=2 → Limit nicht erzwungen.
        n = Allocation.objects.filter(period=self.period, source="lottery",
                                      start=s).count()
        self.assertEqual(n, 3)

    def test_wunsch_reihenfolge_aendern(self):
        s = date(YEAR + 1, 6, 1)
        w1, _ = svc.add_wish(self.alice, self.period, self.q1, s, s + timedelta(days=3))
        w2, _ = svc.add_wish(self.alice, self.period, self.q2, s, s + timedelta(days=3))
        self.assertEqual(w1.priority, 1)
        self.assertEqual(w2.priority, 2)
        # w2 nach oben
        svc.move_wish(self.alice, self.period, w2.id, "up")
        w1.refresh_from_db(); w2.refresh_from_db()
        self.assertEqual(w2.priority, 1)
        self.assertEqual(w1.priority, 2)
        # explizite Reihenfolge per Drag-and-Drop
        svc.reorder_wishes(self.alice, self.period, [str(w1.id), str(w2.id)])
        w1.refresh_from_db(); w2.refresh_from_db()
        self.assertEqual(w1.priority, 1)
        self.assertEqual(w2.priority, 2)

    def test_zuruckziehen_macht_wieder_bearbeitbar(self):
        s = date(YEAR + 1, 6, 1)
        svc.add_wish(self.alice, self.period, self.q1, s, s + timedelta(days=3))
        svc.submit_wishlist(self.alice, self.period)
        self.assertTrue(
            Wish.objects.filter(member=self.alice, submitted=True).exists())
        svc.withdraw_wishlist(self.alice, self.period)
        self.assertFalse(
            Wish.objects.filter(member=self.alice, submitted=True).exists())

    def test_kalender_zeigt_ferien_und_buchung(self):
        from booking.models import SchoolHoliday
        SchoolHoliday.objects.create(
            name="Sommerferien", start_month=7, start_day=9, end_month=8, end_day=23)
        start = date(YEAR, 7, 15)
        book_spontaneous(self.alice, self.q1, start, start + timedelta(days=4))
        cal = svc.build_member_calendar(self.alice, YEAR, 7)
        # Irgendein Tag im Juli trägt eine Ferien-Markierung und eine Buchung
        flat = [d for week in cal["weeks"] for d in week if d["in_month"]]
        self.assertTrue(any(d["holiday"] for d in flat))
        self.assertTrue(any(d["allocations"] for d in flat))
