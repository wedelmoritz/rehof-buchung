"""Seed-Daten für die PoC.

Legt die echten 10 Quartiere mit einer VORGESCHLAGENEN Äquivalenzklassen-
Einteilung an (von der Genossenschaft zu bestätigen), dazu ~50 Fake-Mitglieder
und eine offene Buchungsperiode mit zufälligen Wünschen. Danach ist die App
sofort vorführbar – inklusive einer durchführbaren Losung.

Aufruf:  python manage.py seed_demo
         python manage.py seed_demo --reset   (vorher leeren)
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from booking.models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass,
    Member, Membership, NightTransfer, Quarter, SchoolHoliday, SeasonRule,
    Share, Wish,
)

# Die 10 echten Quartiere mit der von der Genossenschaft bestätigten
# Äquivalenzklassen-Einteilung.
QUARTERS = [
    # name, m², min, max, Klasse
    ("Scheunen Studio",      52, 2, 5, "Mittel"),
    ("Stallgebäude Nord",    65, 2, 5, "Mittel"),
    ("Stallgebäude Süd",     44, 2, 4, "Klein-Stall"),
    ("Stallgebäude West",    40, 2, 3, "Klein-Stall"),
    ("Gartenhaus Salix",     46, 2, 3, "Gartenhaus"),
    ("Gartenhaus Lupulus",   33, 2, 3, "Gartenhaus"),
    ("Gartenhaus Spinosa",   40, 2, 3, "Gartenhaus"),
    ("Pfarrhaus Nord",       74, 4, 6, "Pfarrhaus"),
    ("Pfarrhaus Süd",        68, 4, 6, "Pfarrhaus"),
    ("Hofgebäude",           54, 2, 4, "Mittel"),
]

VORNAMEN = [
    "Anna", "Ben", "Carla", "David", "Eva", "Finn", "Greta", "Hannes", "Ida",
    "Jonas", "Klara", "Leon", "Mia", "Noah", "Olga", "Paul", "Rosa", "Sven",
    "Tara", "Ulf", "Vera", "Wanda", "Xaver", "Yara", "Zoe", "Lars", "Nina",
    "Timo", "Lena", "Felix", "Marie", "Jan", "Sophie", "Tom", "Lea", "Max",
    "Emma", "Erik", "Lina", "Moritz", "Verena", "Ole", "Levi", "Jodie", "Tony",
    "Lisbeth", "Karl", "Frieda", "Bruno", "Mara",
]


def _easter(year: int) -> date:
    """Ostersonntag (Gregorianischer Algorithmus nach Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _holiday_anchors(year: int) -> list[date]:
    """Typische Ballungs-Anreisetage: Ostern, Himmelfahrt, Pfingsten, Berliner
    Sommerferien (Anfang Juli) und Weihnachten – jeweils als Anreisedatum."""
    easter = _easter(year)
    return [
        easter - timedelta(days=2),            # Karfreitag (Osterwochenende)
        easter + timedelta(days=39),           # Christi Himmelfahrt
        easter + timedelta(days=49),           # Pfingstsonntag
        date(year, 7, 10),                     # Berliner Sommerferien (grob)
        date(year, 7, 24),                     # Sommerferien, 2. Welle
        date(year, 12, 23),                    # Weihnachten
    ]


class Command(BaseCommand):
    help = ("Legt Demo-/Testdaten an (Quartiere, Nutzer inkl. Tandems, Periode, "
            "Wünsche, Hofladen). Mit --reset/--wipe werden vorhandene Daten "
            "vorher gelöscht.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="ALLE Daten löschen und Demo-Daten neu anlegen.")
        parser.add_argument(
            "--wipe", action="store_true",
            help="NUR ALLE Daten löschen (keine neuen anlegen).")
        parser.add_argument(
            "--yes", action="store_true",
            help="Sicherheitsabfrage beim Löschen überspringen (für Docker/Cron).")
        parser.add_argument(
            "--members", type=int, default=50, help="Anzahl Nutzer.")
        parser.add_argument(
            "--tandems", type=int, default=2,
            help="Anzahl Zweier-Tandems (teilen sich je einen Anteil 25/25).")
        parser.add_argument(
            "--testdata", action="store_true",
            help="Großes Test-Szenario: KOMPLETTER Wipe (inkl. Superuser) und "
                 "befüllt die DB mit Test-Nutzern (admin/verwaltung/test), 50 "
                 "wild buchenden Mitgliedern, offener Wunsch-Losung mit Feiertags-"
                 "Ballung, offenen Hofladen-Rechnungen und 15 externen Buchungen.")

    def _confirm_destroy(self, opts):
        """Definitive Warnung vor dem Löschen. --yes überspringt; ohne TTY und
        ohne --yes wird abgebrochen (Schutz vor versehentlichem Löschen)."""
        if opts["yes"]:
            return True
        self.stderr.write(self.style.WARNING(
            "\n!!! ACHTUNG: Dies LÖSCHT UNWIDERRUFLICH alle Nutzer, Buchungen, "
            "Anteile, Wünsche, Hofladen-Käufe und Rechnungen !!!"))
        if not sys.stdin.isatty():
            self.stderr.write(self.style.ERROR(
                "Nicht-interaktiv ohne --yes: abgebrochen. (Im Docker per "
                "Umgebungsvariable bzw. --yes ausführen.)"))
            return False
        answer = input("Zum Bestätigen 'LÖSCHEN' eingeben: ").strip()
        if answer != "LÖSCHEN":
            self.stdout.write("Abgebrochen.")
            return False
        return True

    def _wipe(self, full=False):
        """Löscht alle Nutzer-/Buchungs-/Hofladen-Daten in sicherer Reihenfolge
        (Fremdschlüssel mit PROTECT zuerst entkoppeln). `full=True` entfernt auch
        Superuser (für ein vollständig frisches Test-Szenario)."""
        from shop.models import (
            Invoice, LineItem, Product, ProductGroup, Purchase, ShopConfig)
        from booking.models import (
            ExternalBooking, Guest, LotteryRun, Notification, OutboxEmail,
            Share, SwapRequest, WaitlistEntry)
        ExternalBooking.objects.all().delete()
        LineItem.objects.all().delete()
        Invoice.objects.all().delete()
        Purchase.objects.all().delete()
        Guest.objects.all().delete()
        Product.objects.all().delete()
        ProductGroup.objects.all().delete()
        ShopConfig.objects.all().delete()
        OutboxEmail.objects.all().delete()
        SwapRequest.objects.all().delete()
        Notification.objects.all().delete()
        WaitlistEntry.objects.all().delete()
        LotteryRun.objects.all().delete()
        Allocation.objects.all().delete()
        NightTransfer.objects.all().delete()
        Wish.objects.all().delete()
        BookingPeriod.objects.all().delete()
        SeasonRule.objects.all().delete()
        SchoolHoliday.objects.all().delete()
        BookingPolicy.objects.all().delete()
        Share.objects.all().delete()
        Member.objects.all().delete()
        Membership.objects.all().delete()
        if full:
            User.objects.all().delete()
        else:
            User.objects.filter(is_superuser=False).delete()
        Quarter.objects.all().delete()
        EquivalenceClass.objects.all().delete()

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(20270524)

        if opts["reset"] or opts["wipe"] or opts["testdata"]:
            if not self._confirm_destroy(opts):
                return
            self.stdout.write("Lösche vorhandene Daten …")
            self._wipe(full=opts["testdata"])
            if opts["wipe"]:
                self.stdout.write(self.style.SUCCESS("Alle Daten gelöscht."))
                return

        # Äquivalenzklassen + Quartiere
        classes: dict[str, EquivalenceClass] = {}
        for *_rest, cls_name in QUARTERS:
            if cls_name not in classes:
                classes[cls_name], _ = EquivalenceClass.objects.get_or_create(
                    name=cls_name,
                )
        quarters = []
        for name, sqm, mn, mx, cls_name in QUARTERS:
            q, _ = Quarter.objects.get_or_create(
                name=name,
                defaults=dict(
                    size_sqm=sqm, min_occupancy=mn, max_occupancy=mx,
                    eq_class=classes[cls_name],
                ),
            )
            quarters.append(q)
        self.stdout.write(self.style.SUCCESS(
            f"{len(quarters)} Quartiere in {len(classes)} Klassen angelegt."
        ))

        # Mitglieder (Fake)
        n = opts["members"]
        members = []
        used = set()
        for i in range(n):
            base = rng.choice(VORNAMEN)
            uname = f"{base.lower()}{i}"
            if uname in used:
                continue
            used.add(uname)
            user, created = User.objects.get_or_create(
                username=uname,
                defaults=dict(email=f"{uname}@example.org", first_name=base),
            )
            if created:
                user.set_password("demo12345")  # nur Demo!
                user.save()
            m, _ = Member.objects.get_or_create(
                user=user,
                defaults=dict(
                    display_name=f"{base} ({uname})",
                    factor=rng.choice([1.0, 1.0, 1.0, 1.1, 1.2, 1.3]),
                ),
            )
            members.append(m)

        # Mitglieds-Anteile: einige Zweier-Tandems (ein Anteil, 50 Tage fair
        # geteilt = je 25), der Rest Voll-Mitglieder (eigener Anteil, 50 Tage).
        # Budget eines Nutzers = Summe seiner Anteile.
        n_tandems = max(0, min(opts["tandems"], len(members) // 2))
        assigned = set()
        for t in range(n_tandems):
            pair = members[2 * t:2 * t + 2]
            tandem = Membership.objects.create(
                eg_number=f"VL-T{t + 1:03d}", label=f"Tandem-Demo {t + 1}",
                kind=Membership.TEIL, annual_night_budget=50, wish_night_budget=25)
            for m in pair:
                Share.objects.create(membership=tandem, member=m,
                                     night_budget=25, wish_night_budget=12)
                assigned.add(m.id)
        for idx, m in enumerate(members, start=1):
            if m.id in assigned:
                continue
            ms = Membership.objects.create(
                eg_number=f"VL-{1000 + idx}", label=m.display_name,
                kind=Membership.VOLL, annual_night_budget=50, wish_night_budget=25)
            Share.objects.create(membership=ms, member=m,
                                 night_budget=50, wish_night_budget=25)
        self.stdout.write(self.style.SUCCESS(
            f"{len(members)} Nutzer angelegt ({n_tandems} Zweier-Tandem(s) 25/25, "
            f"Rest Voll-Mitglieder 50)."))

        # Buchungsperiode fürs nächste Jahr – Wunsch-Einträge freigegeben.
        next_year = date.today().year + 1
        period, _ = BookingPeriod.objects.get_or_create(
            name=f"Jahres-Losung {next_year}",
            target_year=next_year,
            defaults=dict(
                start=date(next_year, 1, 1),
                end=date(next_year + 1, 1, 1),
                wishlist_open=date.today(),
                wishlist_close=date.today() + timedelta(days=21),  # 3 Wochen offen
                draw_at=timezone.now() + timedelta(days=22),
                status=BookingPeriod.WISHES_OPEN,
            ),
        )

        # Zufällige Wünsche – mit Häufung auf den typischen Feiertagen/Ferien
        # (Ostern, Himmelfahrt, Pfingsten, Sommerferien, Weihnachten), um realistische
        # Kollisionen zu erzeugen.
        hot_anchors = _holiday_anchors(next_year)
        cool_anchors = [
            date(next_year, 3, 1) + timedelta(days=rng.randint(0, 200))
            for _ in range(8)
        ]
        Wish.objects.filter(period=period).delete()
        wish_count = 0
        for m in members:
            n_wishes = rng.randint(1, 3)
            for prio in range(1, n_wishes + 1):
                # 60% der Wünsche zielen auf heiße Wochen -> viele Konflikte
                if rng.random() < 0.6:
                    start = rng.choice(hot_anchors)
                else:
                    start = rng.choice(cool_anchors)
                length = rng.choice([3, 4, 7])
                q = rng.choice(quarters)
                Wish.objects.create(
                    period=period, member=m, priority=prio, quarter=q,
                    start=start, end=start + timedelta(days=length),
                    submitted=True,  # in der Demo bereits im Lostopf
                )
                wish_count += 1
        self.stdout.write(self.style.SUCCESS(
            f"{wish_count} Wünsche in Periode '{period}' angelegt (im Lostopf)."
        ))

        # Freie Bebuchbarkeit: das LAUFENDE Jahr ist als Periode freigegeben
        # (Status „Freie Bebuchbarkeit“). Das nächste Jahr (Los-Ziel) bewusst
        # NICHT – so wird die Zeitlogik sichtbar: Losung im Sommer fürs Folgejahr,
        # normale Buchung nur im bereits freigeschalteten laufenden Jahr.
        # Pro Jahr gibt es GENAU EINE (globale) Periode.
        this_year = date.today().year
        global_period, _ = BookingPeriod.objects.get_or_create(
            name=f"Normalbuchung {this_year}",
            target_year=this_year,
            defaults=dict(
                start=date(this_year, 1, 1),
                end=date(this_year + 1, 1, 1),
                status=BookingPeriod.FREE_BOOKING,
            ),
        )
        # Quartiersspezifische Einschränkung über die Quartier-Saison statt über
        # eine eigene Periode: Pfarrhäuser nur im Sommerhalbjahr (Mai–Sept).
        Quarter.objects.filter(name__startswith="Pfarrhaus").update(
            season_start_month=5, season_start_day=1,
            season_end_month=9, season_end_day=30,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Freie-Bebuchbarkeit-Periode angelegt: global {this_year} (alle "
            f"Quartiere); Pfarrhäuser saisonal nur Mai–Sept."
        ))

        # Externe Gäste (Demo): Regeln aktiv (nur Mo–Do), ein paar Quartiere mit
        # Preis freigeben – damit /extern/ sofort testbar ist.
        from booking.models import ExternalConfig, QuarterPrice
        from decimal import Decimal as _D
        cfg, _ = ExternalConfig.objects.get_or_create(id=1)
        cfg.active = True
        cfg.allowed_weekdays = "0,1,2,3"   # Mo–Do (Wochenenden Mitgliedern vorbehalten)
        cfg.min_nights = 2
        cfg.lead_days = 1
        cfg.cleaning_fee = _D("60.00")
        cfg.deposit_percent = 20           # 20 % Anzahlung (Demo)
        cfg.free_cancel_days = 30
        cfg.partial_cancel_days = 7
        cfg.partial_refund_percent = 50
        cfg.late_fee = _D("15.00")
        cfg.save()
        for i, q in enumerate(Quarter.objects.order_by("name")[:3]):
            q.external_bookable = True
            q.price_per_night = _D("80.00") + _D("10.00") * i
            q.save(update_fields=["external_bookable", "price_per_night"])
            # Sommer-Hochsaison-Preis (Juli/August) als Demo-Saisonpreis.
            QuarterPrice.objects.get_or_create(
                quarter=q, label="Sommer", start_month=7, start_day=1,
                end_month=8, end_day=31,
                defaults={"price_per_night": _D("120.00") + _D("10.00") * i})
        self.stdout.write(self.style.SUCCESS(
            "Externe Gäste: Regeln aktiv (Mo–Do), 3 Quartiere mit Preis + "
            "Sommer-Saisonpreis, Anzahlung/Storno gesetzt."
        ))

        # Beispielhafte Tage-Übertragungen zwischen Mitgliedern (laufendes Jahr)
        if len(members) >= 4:
            NightTransfer.objects.get_or_create(
                from_member=members[0], to_member=members[1], year=this_year,
                defaults=dict(nights=5, note="Beispiel-Übertragung"),
            )
            NightTransfer.objects.get_or_create(
                from_member=members[2], to_member=members[3], year=this_year,
                defaults=dict(nights=3, note="Beispiel-Übertragung"),
            )
            self.stdout.write(self.style.SUCCESS(
                "2 Beispiel-Tage-Übertragungen angelegt."
            ))

        # Globale Buchungsregel: Standard-Mindestbuchung 3 Nächte.
        policy = BookingPolicy.get_solo()
        policy.default_min_nights = 3
        policy.save()

        # Saison-Regeln – jährlich wiederkehrend (ohne Jahr), Monat/Tag.
        season_defs = [
            # (Name, von(M,T), bis exkl.(M,T), min_nights, max_parallel, max_stay)
            ("Hochsaison Juli/August", (7, 1), (9, 1), 7, None, None),
            ("Sommerferien Berlin/Brandenburg", (7, 9), (8, 23), None, 2, 14),
            ("Himmelfahrt + Brückentag", (5, 14), (5, 18), None, 2, None),
            ("Pfingsten", (5, 22), (5, 27), None, 2, None),
            ("Weihnachten/Silvester", (12, 23), (1, 3), None, 2, None),
        ]
        for name, (sm, sd), (em, ed), mn, mp, ms in season_defs:
            SeasonRule.objects.get_or_create(
                name=name,
                defaults=dict(
                    policy=policy,
                    start_month=sm, start_day=sd, end_month=em, end_day=ed,
                    min_nights=mn, max_parallel_units=mp, max_stay_nights=ms,
                    active=True,
                ),
            )
        self.stdout.write(self.style.SUCCESS(
            f"Buchungsregeln angelegt: Standard-Mindestnächte 3, "
            f"{len(season_defs)} jährliche Saison-Regeln."
        ))

        # Berliner Schulferien – jährlich wiederkehrend (Monat/Tag). Einige
        # tragen zugleich eine Regel (max. 2 parallele Einheiten in der Zeit).
        holidays = [
            # (Name, von(M,T), bis exkl.(M,T), max_parallel)
            ("Winterferien", (2, 2), (2, 8), 2),
            ("Osterferien", (3, 30), (4, 11), 2),
            ("Sommerferien", (7, 9), (8, 23), 2),
            ("Herbstferien", (10, 19), (11, 1), 2),
            ("Weihnachtsferien", (12, 23), (1, 3), 2),
        ]
        for name, (sm, sd), (em, ed), mp in holidays:
            SchoolHoliday.objects.get_or_create(
                name=name,
                defaults=dict(
                    policy=policy, region="Berlin", active=True,
                    start_month=sm, start_day=sd, end_month=em, end_day=ed,
                    max_parallel_units=mp,
                ),
            )
        self.stdout.write(self.style.SUCCESS(
            f"{len(holidays)} jährliche Berliner Schulferien angelegt."
        ))

        # Hofladen-Katalog (Gruppen, Produkte, Genossenschafts-Stammdaten)
        call_command("seed_shop")

        # Großes Test-Szenario (Test-Nutzer, Buchungen, Rechnungen, Externe)
        if opts["testdata"]:
            self._seed_testdata(rng, members, quarters, period, this_year)

        self.stdout.write(self.style.WARNING(
            "\nLogin-Demodaten: Benutzername wie 'anna0', Passwort 'demo12345'.\n"
            "Losung starten: im Admin unter „Buchungsperioden (Zeiträume)“ -> "
            "Aktion 'Losung durchführen'.\n"
            "Zeiträume & Status verwalten: im Admin unter „Buchungsperioden "
            "(Zeiträume)“ (Status „Freie Bebuchbarkeit“ schaltet die normale "
            "Buchung frei).\n"
            "Buchungsregeln (global + Saison + Schulferien): im Admin unter "
            "„Buchungsregeln“."
        ))

    # ----------------------------------------------------------------- #
    # Großes Test-Szenario (--testdata)
    # ----------------------------------------------------------------- #
    def _seed_testdata(self, rng, members, quarters, period, this_year):
        """Befüllt die DB realistisch: benannte Test-Nutzer, wilde Buchungen im
        laufenden Jahr, offene Hofladen-Rechnungen und 15 externe Buchungen.
        Die Losung wird bewusst NICHT durchgeführt (das tun die Test-Nutzer)."""
        from booking import services as svc
        from shop import services as shopsvc
        from shop.models import Invoice, Product

        # 1) Benannte Test-Konten ------------------------------------------------
        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults=dict(email="admin@example.org", is_staff=True,
                          is_superuser=True, first_name="Admin"))
        admin.set_password("admin12345"); admin.save()

        # Verwaltung = Dashboard-Rolle (Gruppe „Verwaltung"), KEIN Django-Backend.
        from booking.permissions import ensure_verwaltung_group
        verw, _ = User.objects.get_or_create(
            username="verwaltung",
            defaults=dict(email="verwaltung@example.org", is_staff=False,
                          first_name="Verwaltung"))
        verw.set_password("verwaltung12345"); verw.is_staff = False; verw.save()
        verw.groups.add(ensure_verwaltung_group())

        test_user, _ = User.objects.get_or_create(
            username="test",
            defaults=dict(email="test@example.org", first_name="Test"))
        test_user.set_password("test12345"); test_user.save()
        test_member, _ = Member.objects.get_or_create(
            user=test_user, defaults=dict(display_name="Testnutzende (test)"))
        if not Share.objects.filter(member=test_member).exists():
            ms = Membership.objects.create(
                eg_number="VL-TEST", label="Testnutzende",
                kind=Membership.VOLL, annual_night_budget=50, wish_night_budget=25)
            Share.objects.create(membership=ms, member=test_member,
                                 night_budget=50, wish_night_budget=25)
        members = list(members) + [test_member]

        # Hofladen-Terminal vor Ort (ADR 0053): aktivieren + ein paar Konten
        # freischalten und mit einer Test-PIN versehen, damit das Terminal direkt
        # ausprobierbar ist (Geräte-Token: TESTTOKEN123).
        from booking.models import TerminalConfig
        tcfg = TerminalConfig.get_solo()
        tcfg.enabled = True
        tcfg.token = "TESTTOKEN123"
        tcfg.save()
        for tm in [test_member] + members[:5]:
            tm.terminal_enabled = True
            tm.set_terminal_pin("135790")
            tm.save(update_fields=["terminal_enabled", "terminal_pin"])
        # Auch die Testnutzenden wünschen mit (Feiertags-Ballung).
        if not Wish.objects.filter(period=period, member=test_member).exists():
            for prio, start in enumerate(_holiday_anchors(period.target_year)[:2], 1):
                Wish.objects.create(
                    period=period, member=test_member, priority=prio,
                    quarter=rng.choice(quarters), start=start,
                    end=start + timedelta(days=rng.choice([3, 4, 7])),
                    submitted=True)
        self.stdout.write(self.style.SUCCESS(
            "Test-Konten: admin/admin12345 (Admin/Superuser, volles Backend), "
            "verwaltung/verwaltung12345 (Verwaltung-Gruppe, nur Dashboard), "
            "test/test12345 (Mitglied)."))

        # 2) Wilde Buchungen im laufenden Jahr -----------------------------------
        n_alloc = 0
        attempts = 0
        while n_alloc < 60 and attempts < 600:
            attempts += 1
            m = rng.choice(members)
            q = rng.choice(quarters)
            month = rng.randint(1, 12)
            day = rng.randint(1, 28)
            start = date(this_year, month, day)
            end = start + timedelta(days=rng.choice([2, 3, 3, 4, 7]))
            if not svc._in_season_range(q, start, end):
                continue
            if not svc.quarter_is_free(q, start, end):
                continue
            Allocation.objects.create(
                member=m, quarter=q, start=start, end=end,
                persons=rng.randint(1, q.max_occupancy), source="spontaneous",
                provisional=False)
            n_alloc += 1
        self.stdout.write(self.style.SUCCESS(
            f"{n_alloc} wilde Buchungen im laufenden Jahr {this_year} angelegt."))

        # 3) Offene Hofladen-Rechnungen ------------------------------------------
        wares = list(Product.objects.filter(kind="ware"))
        n_inv = 0
        if wares:
            for m in rng.sample(members, min(12, len(members))):
                for _ in range(rng.randint(1, 3)):
                    shopsvc.add_item(m, rng.choice(wares), rng.randint(1, 4))
                shopsvc.checkout(m)
                inv, _err = shopsvc.generate_invoice_now(m)
                if inv:
                    n_inv += 1
                    # Etwa jede dritte Rechnung überfällig (für Mahnwesen/Dashboard).
                    if n_inv % 3 == 0:
                        inv.due_date = date.today() - timedelta(days=rng.randint(5, 40))
                        inv.save(update_fields=["due_date"])
        self.stdout.write(self.style.SUCCESS(
            f"{n_inv} offene Hofladen-Rechnungen angelegt (≈⅓ überfällig)."))

        # 4) 15 externe Buchungen (nur Mo–Fr: Anreise Mo, Abreise Fr) ------------
        ext_quarters = list(Quarter.objects.filter(external_bookable=True))
        names = ["Familie Müller", "Lena Gast", "P. Schmidt", "Café Nord",
                 "Team Retreat", "Anja & Tom", "Wandergruppe", "Oma Erna",
                 "Studio B", "Yoga-Kreis", "Klaus Extern", "Reisegruppe Süd",
                 "Birte Hansen", "Hoffreunde", "Tina & Co"]
        n_ext, ext_attempts = 0, 0
        # Nächster Montag ab heute+lead.
        d0 = date.today() + timedelta(days=2)
        while d0.weekday() != 0:
            d0 += timedelta(days=1)
        while n_ext < 15 and ext_attempts < 200 and ext_quarters:
            mon = d0 + timedelta(weeks=ext_attempts // max(1, len(ext_quarters)))
            q = ext_quarters[ext_attempts % len(ext_quarters)]
            ext_attempts += 1
            fri = mon + timedelta(days=4)   # Mo→Fr = 4 Nächte (Mo,Di,Mi,Do)
            booking, _err = svc.create_external_booking(
                q, mon, fri, rng.randint(1, q.max_occupancy),
                name=names[n_ext % len(names)],
                email=f"gast{n_ext}@example.org", city="Berlin")
            if booking:
                n_ext += 1
        self.stdout.write(self.style.SUCCESS(
            f"{n_ext} externe Buchungen (Mo–Fr) angelegt."))

        # 5) Einige Rechnungen per Online-Zahldienst (Mollie-Sandbox) begleichen,
        #    damit die Verwaltungsseite „online bezahlt“ befüllt ist.
        from shop import payments as pay_svc
        from shop.models import Invoice as _Invoice
        n_online = 0
        candidates = list(_Invoice.objects.filter(payment_method="")
                          .order_by("?")[:8])
        for inv in candidates:
            if inv.items.exists() and inv.is_payable:
                pay_svc.settle_payment(pay_svc.start_payment(inv))
                n_online += 1
        self.stdout.write(self.style.SUCCESS(
            f"{n_online} Rechnungen per Online-Zahldienst (Test) beglichen."))
