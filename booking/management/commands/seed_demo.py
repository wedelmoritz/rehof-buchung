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

    def _wipe(self):
        """Löscht alle Nutzer-/Buchungs-/Hofladen-Daten in sicherer Reihenfolge
        (Fremdschlüssel mit PROTECT zuerst entkoppeln)."""
        from shop.models import (
            Invoice, LineItem, Product, ProductGroup, ShopConfig)
        from booking.models import (
            LotteryRun, Notification, Share, SwapRequest, WaitlistEntry)
        LineItem.objects.all().delete()
        Invoice.objects.all().delete()
        Product.objects.all().delete()
        ProductGroup.objects.all().delete()
        ShopConfig.objects.all().delete()
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
        User.objects.filter(is_superuser=False).delete()
        Quarter.objects.all().delete()
        EquivalenceClass.objects.all().delete()

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(20270524)

        if opts["reset"] or opts["wipe"]:
            if not self._confirm_destroy(opts):
                return
            self.stdout.write("Lösche vorhandene Daten …")
            self._wipe()
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
                wishlist_open=date.today() - timedelta(days=3),
                wishlist_close=date.today() + timedelta(days=14),
                draw_at=timezone.now() + timedelta(days=15),
                status=BookingPeriod.WISHES_OPEN,
            ),
        )

        # Zufällige Wünsche – mit Häufung auf "Pfingst"-Wochen, um Kollisionen
        # zu erzeugen (Pfingsten next_year grob Ende Mai/Anfang Juni).
        hot_anchors = [
            date(next_year, 5, 22), date(next_year, 5, 29), date(next_year, 6, 5),
        ]
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
