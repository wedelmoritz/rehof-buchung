"""Datenmodelle der Buchungs-App."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class EquivalenceClass(models.Model):
    """Gruppe gleichwertiger Quartiere (Wert-Entscheidung der Genossenschaft)."""
    name = models.CharField("Name", max_length=80, unique=True)

    class Meta:
        verbose_name = "Äquivalenzklasse"
        verbose_name_plural = "Äquivalenzklassen"

    def __str__(self) -> str:
        return self.name


class Quarter(models.Model):
    """Ein Quartier (Ferienunterkunft)."""
    name = models.CharField("Name", max_length=120, unique=True)
    size_sqm = models.PositiveIntegerField("Größe (m²)", default=0)
    min_occupancy = models.PositiveIntegerField("Min. Personen", default=1)
    max_occupancy = models.PositiveIntegerField("Max. Personen", default=2)
    eq_class = models.ForeignKey(
        EquivalenceClass, on_delete=models.PROTECT,
        related_name="quarters", verbose_name="Äquivalenzklasse",
    )
    description = models.TextField("Beschreibung", blank=True)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Quartier"
        verbose_name_plural = "Quartiere"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Member(models.Model):
    """Eine buchende Partei. Für die PoC 1:1 an einen Django-User gekoppelt
    (Cliquen lassen sich später ergänzen). Trägt den Ausgleichsfaktor und die
    Nächte-Budgets."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="member",
        verbose_name="Login-Konto",
    )
    display_name = models.CharField("Anzeigename", max_length=120)
    factor = models.FloatField("Ausgleichsfaktor", default=1.0)
    annual_night_budget = models.PositiveIntegerField("Nächte/Jahr", default=50)
    wish_night_budget = models.PositiveIntegerField(
        "Nächte über Wunschliste", default=25,
    )
    is_external = models.BooleanField("Externer Gast", default=False)

    class Meta:
        verbose_name = "Mitglied"
        verbose_name_plural = "Mitglieder"
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name

    def nights_used_in_year(self, year: int) -> int:
        total = 0
        for a in self.allocations.filter(start__year=year):
            total += (a.end - a.start).days
        return total

    def nights_received_in_year(self, year: int) -> int:
        return sum(t.nights for t in self.transfers_in.filter(year=year))

    def nights_given_in_year(self, year: int) -> int:
        return sum(t.nights for t in self.transfers_out.filter(year=year))

    def effective_annual_budget(self, year: int) -> int:
        """Jahreskontingent inkl. erhaltener/abgegebener Tage (kein Übertrag
        aus dem Vorjahr)."""
        return (
            self.annual_night_budget
            + self.nights_received_in_year(year)
            - self.nights_given_in_year(year)
        )

    def nights_remaining_in_year(self, year: int) -> int:
        return self.effective_annual_budget(year) - self.nights_used_in_year(year)


class BookingPeriod(models.Model):
    """Eine Jahres-Losung: Anmeldefenster + Ergebnis."""
    STATUS = [
        ("open", "Anmeldung offen"),
        ("drawn", "Ausgelost"),
        ("closed", "Abgeschlossen"),
    ]
    name = models.CharField("Bezeichnung", max_length=120)
    target_year = models.PositiveIntegerField("Buchungsjahr")
    wishlist_open = models.DateField("Anmeldung ab")
    wishlist_close = models.DateField("Anmeldung bis")
    status = models.CharField("Status", max_length=10, choices=STATUS, default="open")
    seed = models.BigIntegerField("Zufalls-Seed", null=True, blank=True)

    class Meta:
        verbose_name = "Buchungsperiode"
        verbose_name_plural = "Buchungsperioden"
        ordering = ["-target_year"]

    def __str__(self) -> str:
        return f"{self.name} ({self.target_year})"


class Wish(models.Model):
    """Ein Buchungswunsch eines Mitglieds in einer Periode."""
    period = models.ForeignKey(
        BookingPeriod, on_delete=models.CASCADE, related_name="wishes",
        verbose_name="Periode",
    )
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="wishes",
        verbose_name="Mitglied",
    )
    priority = models.PositiveIntegerField("Priorität (1 = höchste)", default=1)
    quarter = models.ForeignKey(
        Quarter, on_delete=models.CASCADE, related_name="wishes",
        verbose_name="Wunschquartier",
    )
    start = models.DateField("Anreise")
    end = models.DateField("Abreise (exkl.)")
    submitted = models.BooleanField("Im Lostopf", default=False)
    submitted_at = models.DateTimeField("Eingereicht am", null=True, blank=True)

    class Meta:
        verbose_name = "Wunsch"
        verbose_name_plural = "Wünsche"
        ordering = ["member", "priority"]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def __str__(self) -> str:
        flag = "" if self.submitted else " (Entwurf)"
        return f"{self.member} P{self.priority}: {self.quarter} {self.start}–{self.end}{flag}"


class Allocation(models.Model):
    """Eine zugeteilte/gebuchte Belegung (aus Losung, Spontan- oder Extern-Buchung)."""
    SOURCE = [
        ("lottery", "Losung"),
        ("spontaneous", "Spontanbuchung"),
        ("external", "Externe Buchung"),
    ]
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="allocations",
        verbose_name="Mitglied",
    )
    quarter = models.ForeignKey(
        Quarter, on_delete=models.PROTECT, related_name="allocations",
        verbose_name="Quartier",
    )
    start = models.DateField("Anreise")
    end = models.DateField("Abreise (exkl.)")
    source = models.CharField("Quelle", max_length=12, choices=SOURCE)
    period = models.ForeignKey(
        BookingPeriod, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="allocations", verbose_name="Periode",
    )
    via_substitution = models.BooleanField("Ausweichquartier", default=False)
    contested = models.BooleanField("Umkämpft", default=False)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Zuteilung"
        verbose_name_plural = "Zuteilungen"
        ordering = ["start"]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def __str__(self) -> str:
        return f"{self.member} @ {self.quarter} {self.start}–{self.end}"


class LotteryRun(models.Model):
    """Ein protokollierter Losdurchlauf (Audit)."""
    period = models.ForeignKey(
        BookingPeriod, on_delete=models.CASCADE, related_name="runs",
        verbose_name="Periode",
    )
    executed_at = models.DateTimeField("Durchgeführt", auto_now_add=True)
    seed = models.BigIntegerField("Seed")
    log_text = models.TextField("Protokoll", blank=True)
    summary = models.CharField("Zusammenfassung", max_length=255, blank=True)

    class Meta:
        verbose_name = "Losdurchlauf"
        verbose_name_plural = "Losdurchläufe"
        ordering = ["-executed_at"]

    def __str__(self) -> str:
        return f"Losung {self.period} @ {self.executed_at:%Y-%m-%d %H:%M}"


class BookingWindow(models.Model):
    """Ein vom Admin freigeschalteter Buchungszeitraum.

    `applies_to_all` = True: globales Fenster (alle Quartiere).
    Sonst gilt das Fenster nur für die unter `quarters` gewählten Quartiere –
    so lässt sich die globale Freigabe für einen Teil der Quartiere weiter
    einschränken. Über `active` wird freigeschaltet bzw. gesperrt.
    """
    name = models.CharField("Bezeichnung", max_length=120)
    start = models.DateField("Buchbar ab")
    end = models.DateField("Buchbar bis (exkl.)")
    applies_to_all = models.BooleanField("Gilt für alle Quartiere", default=True)
    quarters = models.ManyToManyField(
        Quarter, blank=True, related_name="booking_windows",
        verbose_name="Nur diese Quartiere (wenn nicht global)",
    )
    active = models.BooleanField("Freigeschaltet", default=True)

    class Meta:
        verbose_name = "Buchungszeitraum"
        verbose_name_plural = "Buchungszeiträume"
        ordering = ["-start"]

    def __str__(self) -> str:
        scope = "alle Quartiere" if self.applies_to_all else "Teilmenge"
        flag = "" if self.active else " [gesperrt]"
        return f"{self.name}: {self.start}–{self.end} ({scope}){flag}"


class NightTransfer(models.Model):
    """Übertragung von Tagen an ein anderes Mitglied innerhalb eines Jahres.
    (Ein Übertrag ins Folgejahr ist bewusst NICHT vorgesehen.)"""
    year = models.PositiveIntegerField("Jahr")
    from_member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="transfers_out",
        verbose_name="Von Mitglied",
    )
    to_member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="transfers_in",
        verbose_name="An Mitglied",
    )
    nights = models.PositiveIntegerField("Tage")
    note = models.CharField("Notiz", max_length=200, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Tage-Übertragung"
        verbose_name_plural = "Tage-Übertragungen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (f"{self.nights} Tage: {self.from_member} → {self.to_member} "
                f"({self.year})")


class BookingPolicy(models.Model):
    """Globale Buchungsregeln (eine Zeile). Saisonale Verschärfungen siehe
    SeasonRule."""
    default_min_nights = models.PositiveIntegerField(
        "Mindestnächte (Standard)", default=3,
        help_text="Gilt, wenn keine Saison-Regel etwas Strengeres vorgibt.",
    )

    class Meta:
        verbose_name = "Buchungsregel (global)"
        verbose_name_plural = "Buchungsregeln (global)"

    def __str__(self) -> str:
        return f"Standard-Mindestnächte: {self.default_min_nights}"

    @classmethod
    def get_solo(cls) -> "BookingPolicy":
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class SeasonRule(models.Model):
    """Saison-/Sonderzeitraum mit verschärften Regeln.

    Felder leer lassen = Regel greift nicht. So lassen sich Mindestnächte,
    Parallel-Limit und Aufenthaltsdeckel je Zeitraum frei kombinieren.
    """
    name = models.CharField("Bezeichnung", max_length=140)
    start = models.DateField("Von")
    end = models.DateField("Bis (exkl.)")
    min_nights = models.PositiveIntegerField(
        "Mindestnächte", null=True, blank=True,
        help_text="z.B. 7 für Juli/August. Leer = Standard.",
    )
    max_parallel_units = models.PositiveIntegerField(
        "Max. gleichzeitige Wohneinheiten", null=True, blank=True,
        help_text="z.B. 2 in Schulferien/an Feiertagen. Leer = unbegrenzt.",
    )
    max_stay_nights = models.PositiveIntegerField(
        "Max. Nächte je Partei (Deckel)", null=True, blank=True,
        help_text=("Einheiten-Nächte innerhalb des Zeitraums, z.B. 14 für die "
                   "BB-Sommerferien. Leer = kein Deckel."),
    )
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Saison-Regel"
        verbose_name_plural = "Saison-Regeln"
        ordering = ["start"]

    def __str__(self) -> str:
        parts = []
        if self.min_nights:
            parts.append(f"min {self.min_nights} N")
        if self.max_parallel_units is not None:
            parts.append(f"max {self.max_parallel_units} parallel")
        if self.max_stay_nights is not None:
            parts.append(f"Deckel {self.max_stay_nights} N")
        flag = "" if self.active else " [inaktiv]"
        return f"{self.name} ({self.start}–{self.end}; {', '.join(parts)}){flag}"


class SchoolHoliday(models.Model):
    """Schulferien zur Anzeige im Kalender (z.B. Berlin). Rein informativ –
    beeinflusst die Buchungsregeln nicht (die liegen in SeasonRule)."""
    name = models.CharField("Bezeichnung", max_length=140)
    start = models.DateField("Von")
    end = models.DateField("Bis (exkl.)")
    region = models.CharField("Region", max_length=40, default="Berlin")
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Schulferien"
        verbose_name_plural = "Schulferien"
        ordering = ["start"]

    def __str__(self) -> str:
        return f"{self.name} ({self.start}–{self.end}, {self.region})"
