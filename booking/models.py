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
    """Buchungsperiode = zusammengeführter Jahres-Zeitraum.

    Eine Periode durchläuft den gesamten Lebenszyklus eines Buchungsjahres:
    Wunsch-Einreichung → Auslosung → freie Bebuchbarkeit innerhalb des
    Zeitraums → Ende. Der `status` steuert, was gerade möglich ist; der
    Zeitraum [start, end) ist der buchbare Bereich (früher: BookingWindow).

    `applies_to_all` = True: der Zeitraum gilt für alle aktiven Quartiere.
    Sonst gilt er nur für die unter `quarters` gewählten – so lässt sich die
    freie Bebuchbarkeit auf einzelne Quartiere einschränken.
    """
    DRAFT = "draft"
    WISHES_OPEN = "wishes_open"
    LOTTERY_READY = "lottery_ready"
    LOTTERY_DONE = "lottery_done"
    FREE_BOOKING = "free_booking"
    ENDED = "ended"
    SUSPENDED = "suspended"
    STATUS = [
        (DRAFT, "Entwurf"),
        (WISHES_OPEN, "Für Wunsch-Einträge freigegeben"),
        (LOTTERY_READY, "Zur Auslosung freigegeben"),
        (LOTTERY_DONE, "Auslosung beendet"),
        (FREE_BOOKING, "Freie Bebuchbarkeit innerhalb Zeitraum"),
        (ENDED, "Beendet"),
        (SUSPENDED, "Unterbrochen"),
    ]
    name = models.CharField("Bezeichnung", max_length=120)
    target_year = models.PositiveIntegerField("Buchungsjahr")
    start = models.DateField("Zeitraum buchbar ab")
    end = models.DateField("Zeitraum buchbar bis (exkl.)")
    wishlist_open = models.DateField("Anmeldung ab", null=True, blank=True)
    wishlist_close = models.DateField("Anmeldung bis", null=True, blank=True)
    status = models.CharField("Status", max_length=20, choices=STATUS, default=DRAFT)
    applies_to_all = models.BooleanField("Gilt für alle Quartiere", default=True)
    quarters = models.ManyToManyField(
        Quarter, blank=True, related_name="booking_periods",
        verbose_name="Nur diese Quartiere (wenn nicht global)",
    )
    seed = models.BigIntegerField("Zufalls-Seed", null=True, blank=True)

    class Meta:
        verbose_name = "Buchungsperiode (Zeitraum)"
        verbose_name_plural = "Buchungsperioden (Zeiträume)"
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
    persons = models.PositiveIntegerField("Personen", default=1)
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


class UpcomingAllocation(Allocation):
    """Proxy auf Allocation für die Verwaltung: zeigt nur die anstehenden
    Buchungen (Abreise heute oder später), damit sich die Verwaltung darauf
    vorbereiten kann."""

    class Meta:
        proxy = True
        verbose_name = "Anstehende Buchung"
        verbose_name_plural = "Anstehende Buchungen"


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


class WaitlistEntry(models.Model):
    """Wunschzeitraum für die Spontanbuchung: ein Mitglied möchte ein bestimmtes
    Quartier in einem Zeitraum, der gerade belegt ist. Wird der Zeitraum frei,
    erhält das Mitglied eine Benachrichtigung. Die aktuell dort Buchenden sehen,
    dass jemand wartet."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="waitlist_entries",
        verbose_name="Mitglied",
    )
    quarter = models.ForeignKey(
        Quarter, on_delete=models.CASCADE, related_name="waitlist_entries",
        verbose_name="Quartier",
    )
    start = models.DateField("Anreise")
    end = models.DateField("Abreise (exkl.)")
    persons = models.PositiveIntegerField("Personen", default=1)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    fulfilled = models.BooleanField("Frei geworden / erledigt", default=False)
    notified_at = models.DateTimeField("Benachrichtigt am", null=True, blank=True)

    class Meta:
        verbose_name = "Wartelisten-Eintrag"
        verbose_name_plural = "Warteliste (Spontanbuchung)"
        ordering = ["start"]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def __str__(self) -> str:
        flag = " [erledigt]" if self.fulfilled else ""
        return f"{self.member} wartet auf {self.quarter} {self.start}–{self.end}{flag}"


class Notification(models.Model):
    """In-App-Benachrichtigung für ein Mitglied (E-Mail-Versand folgt später)."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="notifications",
        verbose_name="Mitglied",
    )
    message = models.CharField("Nachricht", max_length=255)
    url = models.CharField("Link", max_length=200, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    read = models.BooleanField("Gelesen", default=False)

    class Meta:
        verbose_name = "Benachrichtigung"
        verbose_name_plural = "Benachrichtigungen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.member}: {self.message}"


class BookingPolicy(models.Model):
    """Globale Buchungsregeln (eine Zeile). Saisonale Verschärfungen siehe
    SeasonRule."""
    default_min_nights = models.PositiveIntegerField(
        "Mindestnächte (Standard)", default=3,
        help_text="Gilt, wenn keine Saison-Regel etwas Strengeres vorgibt.",
    )

    class Meta:
        verbose_name = "Buchungsregeln"
        verbose_name_plural = "Buchungsregeln"

    def __str__(self) -> str:
        return "Buchungsregeln"

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
    policy = models.ForeignKey(
        BookingPolicy, on_delete=models.CASCADE, null=True, blank=True,
        related_name="season_rules", verbose_name="Regelwerk",
    )
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
    policy = models.ForeignKey(
        BookingPolicy, on_delete=models.CASCADE, null=True, blank=True,
        related_name="school_holidays", verbose_name="Regelwerk",
    )
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
