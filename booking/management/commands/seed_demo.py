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
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from booking.models import (
    Allocation, BookingPeriod, BookingPolicy, EquivalenceClass,
    Member, NightTransfer, Quarter, SchoolHoliday, SeasonRule, Wish,
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
    help = "Legt Demo-Daten an (Quartiere, Mitglieder, Periode, Wünsche)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", help="Vorhandene Daten löschen.",
        )
        parser.add_argument(
            "--members", type=int, default=50, help="Anzahl Mitglieder.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(20270524)

        if opts["reset"]:
            self.stdout.write("Lösche vorhandene Daten …")
            Allocation.objects.all().delete()
            NightTransfer.objects.all().delete()
            Wish.objects.all().delete()
            SeasonRule.objects.all().delete()
            SchoolHoliday.objects.all().delete()
            BookingPolicy.objects.all().delete()
            BookingPeriod.objects.all().delete()
            Member.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Quarter.objects.all().delete()
            EquivalenceClass.objects.all().delete()

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
        self.stdout.write(self.style.SUCCESS(f"{len(members)} Mitglieder angelegt."))

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
        this_year = date.today().year
        global_period, _ = BookingPeriod.objects.get_or_create(
            name=f"Normalbuchung {this_year}",
            target_year=this_year,
            defaults=dict(
                start=date(this_year, 1, 1),
                end=date(this_year + 1, 1, 1),
                applies_to_all=True,
                status=BookingPeriod.FREE_BOOKING,
            ),
        )
        # Enger eingeschränkte Periode für eine Teilmenge: die Pfarrhäuser sind
        # nur in der wärmeren Jahreshälfte buchbar (Beispiel-Einschränkung).
        pfarr_period, _ = BookingPeriod.objects.get_or_create(
            name=f"Pfarrhäuser nur Sommerhalbjahr {this_year}",
            target_year=this_year,
            defaults=dict(
                start=date(this_year, 5, 1),
                end=date(this_year, 10, 1),
                applies_to_all=False,
                status=BookingPeriod.FREE_BOOKING,
            ),
        )
        pfarr_period.quarters.set(
            Quarter.objects.filter(name__startswith="Pfarrhaus")
        )
        self.stdout.write(self.style.SUCCESS(
            f"Freie-Bebuchbarkeit-Perioden angelegt: global {this_year} (alle "
            f"Quartiere) + Pfarrhäuser nur Mai–Sept."
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

        # Saison-Regeln für das LAUFENDE Jahr (Berlin/Brandenburg, real).
        # Hinweis: Termine verschieben sich jährlich und werden im Admin
        # gepflegt. Berlin und Brandenburg sind nahezu identisch.
        season_defs = [
            # (Name, von, bis(exkl.), min_nights, max_parallel, max_stay)
            (f"Hochsaison Juli/August {this_year}",
             date(this_year, 7, 1), date(this_year, 9, 1), 7, None, None),
            (f"Sommerferien Berlin/Brandenburg {this_year}",
             date(this_year, 7, 9), date(this_year, 8, 23), None, 2, 14),
            (f"Winterferien {this_year}",
             date(this_year, 2, 2), date(this_year, 2, 8), None, 2, None),
            (f"Osterferien/Ostern {this_year}",
             date(this_year, 3, 30), date(this_year, 4, 11), None, 2, None),
            (f"Himmelfahrt + Brückentag {this_year}",
             date(this_year, 5, 14), date(this_year, 5, 18), None, 2, None),
            (f"Pfingsten {this_year}",
             date(this_year, 5, 22), date(this_year, 5, 27), None, 2, None),
            (f"Herbstferien {this_year}",
             date(this_year, 10, 19), date(this_year, 11, 1), None, 2, None),
            (f"Weihnachten/Silvester {this_year}/{this_year + 1}",
             date(this_year, 12, 23), date(this_year + 1, 1, 3), None, 2, None),
        ]
        for name, s_from, s_to, mn, mp, ms in season_defs:
            SeasonRule.objects.get_or_create(
                name=name,
                defaults=dict(
                    policy=policy,
                    start=s_from, end=s_to, min_nights=mn,
                    max_parallel_units=mp, max_stay_nights=ms, active=True,
                ),
            )
        self.stdout.write(self.style.SUCCESS(
            f"Buchungsregeln angelegt: Standard-Mindestnächte 3, "
            f"{len(season_defs)} Saison-Regeln (Juli/Aug 7 Nächte, "
            f"Ferien/Feiertage max. 2 Einheiten, Sommerferien Deckel 14)."
        ))

        # Berliner Schulferien (Anzeige im Kalender) – 2026 und 2027, real.
        # end ist exklusiv (= erster Tag NACH den Ferien).
        holidays = [
            ("Winterferien", date(2026, 2, 2), date(2026, 2, 8)),
            ("Osterferien", date(2026, 3, 30), date(2026, 4, 11)),
            ("Pfingstferien (variabler Tag)", date(2026, 5, 15), date(2026, 5, 16)),
            ("Pfingstferien", date(2026, 5, 26), date(2026, 5, 27)),
            ("Sommerferien", date(2026, 7, 9), date(2026, 8, 23)),
            ("Herbstferien", date(2026, 10, 19), date(2026, 11, 1)),
            ("Weihnachtsferien", date(2026, 12, 23), date(2027, 1, 3)),
            ("Winterferien", date(2027, 2, 1), date(2027, 2, 7)),
            ("Osterferien", date(2027, 3, 22), date(2027, 4, 3)),
            ("Pfingstferien (variabler Tag)", date(2027, 5, 7), date(2027, 5, 8)),
            ("Pfingstferien", date(2027, 5, 18), date(2027, 5, 19)),
            ("Sommerferien", date(2027, 7, 1), date(2027, 8, 15)),
            ("Herbstferien", date(2027, 10, 11), date(2027, 10, 24)),
            ("Weihnachtsferien", date(2027, 12, 22), date(2028, 1, 1)),
        ]
        for name, h_from, h_to in holidays:
            SchoolHoliday.objects.get_or_create(
                name=f"{name} {h_from.year}", start=h_from, end=h_to,
                defaults=dict(policy=policy, region="Berlin", active=True),
            )
        self.stdout.write(self.style.SUCCESS(
            f"{len(holidays)} Berliner Schulferien-Zeiträume (2026/2027) angelegt."
        ))

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
