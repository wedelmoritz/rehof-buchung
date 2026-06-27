"""Datenmodelle der Buchungs-App."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

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
    accessible = models.BooleanField(
        "Barrierearm/-frei", default=False,
        help_text="Quartier ist barrierearm bzw. barrierefrei erreichbar.",
    )
    # Externe Gäste (siehe docs/EXTERNE-GAESTE.md)
    external_bookable = models.BooleanField(
        "Für externe Gäste buchbar", default=False,
        help_text="Wenn aktiv, können externe Gäste dieses Quartier (im Rahmen der "
                  "Externen-Regeln) buchen.")
    price_per_night = models.DecimalField(
        "Preis/Nacht für Externe (brutto)", max_digits=8, decimal_places=2, default=0,
        help_text="Bruttopreis pro Nacht für externe Gäste (Beherbergung, 7 % USt).")
    # Jährlich wiederkehrender Buchbarkeitszeitraum (ohne Jahr). Leer = ganzjährig.
    season_start_month = models.PositiveSmallIntegerField(
        "Buchbar ab (Monat)", null=True, blank=True)
    season_start_day = models.PositiveSmallIntegerField(
        "Buchbar ab (Tag)", null=True, blank=True)
    season_end_month = models.PositiveSmallIntegerField(
        "Buchbar bis einschl. (Monat)", null=True, blank=True)
    season_end_day = models.PositiveSmallIntegerField(
        "Buchbar bis einschl. (Tag)", null=True, blank=True)

    class Meta:
        verbose_name = "Quartier"
        verbose_name_plural = "Quartiere"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def has_season(self) -> bool:
        return bool(self.season_start_month and self.season_start_day
                    and self.season_end_month and self.season_end_day)

    def bookable_on(self, day) -> bool:
        """Ist das Quartier am `day` grundsätzlich (saisonal) buchbar?
        Ohne gesetzte Saison: ganzjährig. Die Saison gilt jedes Jahr;
        läuft sie über den Jahreswechsel, wird das berücksichtigt."""
        if not self.has_season:
            return True
        md = (day.month, day.day)
        s = (self.season_start_month, self.season_start_day)
        e = (self.season_end_month, self.season_end_day)
        if s <= e:
            return s <= md <= e
        return md >= s or md <= e

    def price_for_night(self, day) -> Decimal:
        """Bruttopreis für die Übernachtung, die am `day` beginnt. Greift eine
        saisonale `QuarterPrice`-Regel, gilt deren Preis; sonst der Basispreis."""
        for p in self.prices.all():
            if p.covers(day):
                return p.price_per_night
        return self.price_per_night or Decimal("0")


class QuarterPrice(models.Model):
    """Saisonaler Übernachtungspreis für externe Gäste (jährlich wiederkehrend,
    ohne Jahr – wie `SeasonRule`/`Quarter.season_*`). Fällt eine Nacht in den
    Zeitraum, gilt dieser Preis; sonst der Basispreis `Quarter.price_per_night`.
    So lassen sich z. B. Hoch-/Nebensaison-Preise je Quartier hinterlegen."""
    quarter = models.ForeignKey(
        Quarter, on_delete=models.CASCADE, related_name="prices",
        verbose_name="Quartier")
    label = models.CharField("Bezeichnung", max_length=80, blank=True,
                             help_text="z. B. „Hochsaison“ (nur zur Anzeige).")
    start_month = models.PositiveSmallIntegerField("Von (Monat)")
    start_day = models.PositiveSmallIntegerField("Von (Tag)")
    end_month = models.PositiveSmallIntegerField("Bis einschl. (Monat)")
    end_day = models.PositiveSmallIntegerField("Bis einschl. (Tag)")
    price_per_night = models.DecimalField(
        "Preis/Nacht (brutto)", max_digits=8, decimal_places=2, default=0,
        help_text="Bruttopreis pro Nacht in diesem Zeitraum (Beherbergung, 7 % USt).")

    class Meta:
        verbose_name = "Saisonpreis"
        verbose_name_plural = "Saisonpreise"
        ordering = ["quarter", "start_month", "start_day"]

    def __str__(self) -> str:
        return f"{self.label or 'Saisonpreis'} ({self.price_per_night} €)"

    def covers(self, day) -> bool:
        """Liegt `day` im (jährlich wiederkehrenden) Preiszeitraum?"""
        md = (day.month, day.day)
        s = (self.start_month, self.start_day)
        e = (self.end_month, self.end_day)
        if s <= e:
            return s <= md <= e
        return md >= s or md <= e


class Membership(models.Model):
    """Ein „Mitglied“ im Sinne der Genossenschaft = ein Anteil mit genau einer
    Vielleben-eG-Nummer. Voll-Mitglied = ein Nutzer (voller Anteil); Teil-
    Mitglied (Tandem) = mehrere Nutzer, deren Tage-Anteile zusammen das
    Gesamtbudget ergeben. Ein Nutzer kann mehreren Anteilen angehören und
    erhält dann die Summe der Anteile (siehe `Share`)."""
    VOLL, TEIL = "voll", "teil"
    KIND = [(VOLL, "Voll-Mitglied"), (TEIL, "Teil-Mitglied (Tandem)")]
    eg_number = models.CharField("Vielleben eG-Nummer", max_length=40, blank=True)
    label = models.CharField("Bezeichnung", max_length=120, blank=True)
    kind = models.CharField("Art", max_length=4, choices=KIND, default=VOLL)
    annual_night_budget = models.PositiveIntegerField(
        "Tage/Jahr (gesamt)", default=50,
        help_text="Gesamtkontingent des Anteils; wird auf die Nutzer aufgeteilt.",
    )
    wish_night_budget = models.PositiveIntegerField(
        "Wunsch-Tage (gesamt)", default=25,
    )
    created_on = models.DateField("Angelegt am", default=date.today)

    class Meta:
        verbose_name = "Mitglieds-Anteil"
        verbose_name_plural = "Mitglieds-Anteile"
        ordering = ["eg_number", "label"]

    def __str__(self) -> str:
        if self.label and self.eg_number:
            return f"{self.label} ({self.eg_number})"
        return self.label or self.eg_number or f"Anteil {self.pk}"

    @property
    def is_tandem(self) -> bool:
        return self.shares.count() > 1

    @property
    def allocated_budget(self) -> int:
        """Summe der an die Nutzer vergebenen Tage-Anteile."""
        return sum(s.night_budget for s in self.shares.all())

    @staticmethod
    def suggest_budget(full_budget: int = 50, on: date | None = None) -> int:
        """Anteiliges Tagebudget für das Anlagejahr: bei Anlage mitten im Jahr
        anteilig weniger (Rest des Kalenderjahres)."""
        on = on or date.today()
        year_start, year_end = date(on.year, 1, 1), date(on.year, 12, 31)
        days_left = (year_end - on).days + 1
        total_days = (year_end - year_start).days + 1
        return max(1, round(full_budget * days_left / total_days))


class Member(models.Model):
    """Das Buchungs-Subjekt eines Nutzers (Konto). Buchungen, Wünsche, Losung und
    Ausgleichsfaktor hängen hier. Das Tage- und Wunsch-Budget ergibt sich als
    **Summe der Anteile** (`Share`) über alle Mitglieds-Anteile des Nutzers."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="member",
        verbose_name="Login-Konto",
    )
    display_name = models.CharField("Anzeigename", max_length=120)
    factor = models.FloatField("Ausgleichsfaktor", default=1.0)
    is_external = models.BooleanField("Externer Gast", default=False)
    email_opt_in = models.BooleanField(
        "E-Mail-Benachrichtigungen", default=True,
        help_text="Wenn aus, bekommt das Mitglied keine E-Mails (In-App-Hinweise "
                  "bleiben).")
    # Profil-/Rechnungsdaten (vom Nutzer selbst pflegbar; nur eigene Sicht)
    legal_name = models.CharField("Vollständiger Name", max_length=160, blank=True)
    street = models.CharField("Straße & Nr.", max_length=160, blank=True)
    zip_code = models.CharField("PLZ", max_length=10, blank=True)
    city = models.CharField("Ort", max_length=120, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)

    class Meta:
        verbose_name = "Nutzer-Konto"
        verbose_name_plural = "Nutzer-Konten"
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name

    @property
    def annual_night_budget(self) -> int:
        """Summe der Tage-Anteile über alle Mitglieds-Anteile des Nutzers."""
        return sum(s.night_budget for s in self.shares.all())

    @property
    def wish_night_budget(self) -> int:
        return sum(s.wish_night_budget for s in self.shares.all())

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

    @property
    def memberships(self):
        """Alle Mitglieds-Anteile, denen der Nutzer angehört."""
        return [s.membership for s in self.shares.select_related("membership")]

    @property
    def tandem_partners(self):
        """Andere Nutzer, die mit diesem Nutzer einen Anteil teilen."""
        mids = [s.membership_id for s in self.shares.all()]
        if not mids:
            return []
        return list(
            Member.objects.filter(shares__membership_id__in=mids)
            .exclude(pk=self.pk).distinct()
        )


class Share(models.Model):
    """Tage-Anteil eines Nutzers an einem Mitglieds-Anteil. Über mehrere Shares
    kann ein Nutzer mehreren Anteilen (z.B. zwei Tandems) angehören; sein Budget
    ist die Summe. Halbe Tage gibt es nicht (ganze Zahlen)."""
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="shares",
        verbose_name="Mitglieds-Anteil",
    )
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="shares",
        verbose_name="Nutzer",
    )
    night_budget = models.PositiveIntegerField("Tage-Anteil", default=0)
    wish_night_budget = models.PositiveIntegerField("Wunsch-Tage-Anteil", default=0)

    class Meta:
        verbose_name = "Tage-Anteil"
        verbose_name_plural = "Tage-Anteile"
        unique_together = ("membership", "member")

    def __str__(self) -> str:
        return f"{self.member} @ {self.membership}: {self.night_budget} Tage"


class BookingPeriod(models.Model):
    """Buchungsperiode = genau EIN Zeitraum pro Buchungsjahr (`target_year`
    eindeutig).

    Eine Periode durchläuft den gesamten Lebenszyklus eines Buchungsjahres:
    Wunsch-Einreichung → Auslosung → freie Bebuchbarkeit innerhalb des
    Zeitraums → Ende. Der `status` steuert, was gerade möglich ist; der
    Zeitraum [start, end) ist der buchbare Bereich.

    Der Status wird normalerweise aus den eingestellten Terminen abgeleitet
    (`compute_status`) und vom Kommando `run_due_lotteries` (Cron) automatisch
    vorwärts geschaltet – inkl. der fälligen Auslosung. `suspended` pausiert
    eine Periode manuell.

    Eine quartiersspezifische Einschränkung gibt es bewusst NICHT mehr: einzelne
    Quartiere werden über ihren eigenen jährlichen Saison-Zeitraum begrenzt
    (`Quarter.season_*`).
    """
    DRAFT = "draft"
    WISHES_OPEN = "wishes_open"
    LOTTERY_READY = "lottery_ready"
    LOTTERY_REVIEW = "lottery_review"
    LOTTERY_DONE = "lottery_done"
    FREE_BOOKING = "free_booking"
    ENDED = "ended"
    SUSPENDED = "suspended"
    STATUS = [
        (DRAFT, "Entwurf"),
        (WISHES_OPEN, "Für Wunsch-Einträge freigegeben"),
        (LOTTERY_READY, "Zur Auslosung freigegeben"),
        (LOTTERY_REVIEW, "Auslosung zur Prüfung (unbestätigt)"),
        (LOTTERY_DONE, "Auslosung bestätigt/veröffentlicht"),
        (FREE_BOOKING, "Freie Bebuchbarkeit innerhalb Zeitraum"),
        (ENDED, "Beendet"),
        (SUSPENDED, "Unterbrochen"),
    ]
    # Reihenfolge des Lebenszyklus (für die automatische Vorwärts-Schaltung).
    # LOTTERY_REVIEW → LOTTERY_DONE ist bewusst MANUELL (Bestätigung), siehe
    # services.confirm_lottery / run_due_lotteries.
    LIFECYCLE = [DRAFT, WISHES_OPEN, LOTTERY_READY, LOTTERY_REVIEW,
                 LOTTERY_DONE, FREE_BOOKING, ENDED]

    name = models.CharField("Bezeichnung", max_length=120)
    target_year = models.PositiveIntegerField("Buchungsjahr", unique=True)
    start = models.DateField(
        "Zeitraum buchbar ab",
        help_text="Ab wann der Zeitraum frei bebuchbar ist (darf vor dem 1.1. "
                  "des Buchungsjahres liegen).")
    end = models.DateField("Zeitraum buchbar bis (exkl.)")
    wishlist_open = models.DateField("Wünsche ab", null=True, blank=True)
    wishlist_close = models.DateField("Wünsche bis", null=True, blank=True)
    draw_at = models.DateTimeField(
        "Losung am", null=True, blank=True,
        help_text="Terminierte Auslosung; läuft per Cron automatisch (siehe "
                  "Management-Kommando run_due_lotteries).",
    )
    status = models.CharField("Status", max_length=20, choices=STATUS, default=DRAFT)
    seed = models.BigIntegerField("Zufalls-Seed", null=True, blank=True)

    class Meta:
        verbose_name = "Buchungsperiode (Jahr)"
        verbose_name_plural = "Buchungsperioden (je Jahr eine)"
        ordering = ["-target_year"]

    def __str__(self) -> str:
        return f"{self.name} ({self.target_year})"

    def compute_status(self, now) -> str:
        """Leitet den Status aus den eingestellten Terminen ab. `suspended` ist
        eine manuelle Sperre und wird hier NICHT berücksichtigt."""
        today = now.date() if hasattr(now, "date") else now
        if self.end and today >= self.end:
            return self.ENDED
        if self.start and today >= self.start:
            return self.FREE_BOOKING
        if self.draw_at and now >= self.draw_at:
            # Nach dem Losungstermin nur bis „zur Prüfung“ – die Veröffentlichung
            # (LOTTERY_DONE) erfolgt manuell über die Bestätigung.
            return self.LOTTERY_REVIEW
        if self.wishlist_close and today >= self.wishlist_close:
            return self.LOTTERY_READY
        if self.wishlist_open and today >= self.wishlist_open:
            return self.WISHES_OPEN
        return self.DRAFT

    @property
    def status_rank(self) -> int:
        return self.LIFECYCLE.index(self.status) if self.status in self.LIFECYCLE else -1


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
        indexes = [
            models.Index(fields=["period", "submitted"]),
            models.Index(fields=["member", "period"]),
        ]

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
        ("import", "Beds24-Import"),
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
    companions = models.CharField(
        "Begleitung", max_length=255, blank=True,
        help_text="Mit wem reise ich an (frei eintragbar).")
    source = models.CharField("Quelle", max_length=12, choices=SOURCE)
    period = models.ForeignKey(
        BookingPeriod, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="allocations", verbose_name="Periode",
    )
    via_substitution = models.BooleanField("Ausweichquartier", default=False)
    contested = models.BooleanField("Umkämpft", default=False)
    # Provisorische Los-Zuteilung: existiert (blockiert die Verfügbarkeit), ist
    # aber für Mitglieder unsichtbar, bis die Losung bestätigt wird.
    provisional = models.BooleanField("Vorläufig (unbestätigt)", default=False)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Zuteilung"
        verbose_name_plural = "Zuteilungen"
        ordering = ["start"]
        indexes = [
            # Überlappungs-/Belegungsprüfung je Quartier (quarter_is_free) und
            # Kalenderaufbau – die mit Abstand häufigsten Abfragen.
            models.Index(fields=["quarter", "start", "end"]),
            models.Index(fields=["start", "end"]),
            models.Index(fields=["member", "start"]),
        ]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def clean(self):
        """Domänenregeln auch bei manueller Pflege erzwingen (Django-Admin nutzt
        `full_clean`): gültiger Zeitraum, Personenzahl im Quartiers-Rahmen und –
        am wichtigsten – KEINE Überschneidung mit einer anderen Zuteilung oder
        einer bestätigten externen Buchung im selben Quartier. So lässt sich auch
        im Backend keine Doppelbuchung anlegen."""
        from django.core.exceptions import ValidationError
        errors = {}
        if self.start and self.end and self.end <= self.start:
            errors["end"] = "Die Abreise muss nach der Anreise liegen."
        if self.quarter_id and self.start and self.end and self.end > self.start:
            if self.persons and not (
                    self.quarter.min_occupancy <= self.persons
                    <= self.quarter.max_occupancy):
                errors["persons"] = (
                    f"{self.quarter.name} ist für {self.quarter.min_occupancy}–"
                    f"{self.quarter.max_occupancy} Personen ausgelegt.")
            clash = Allocation.objects.filter(
                quarter_id=self.quarter_id, start__lt=self.end, end__gt=self.start)
            if self.pk:
                clash = clash.exclude(pk=self.pk)
            other = clash.select_related("member").first()
            if other:
                errors["quarter"] = (
                    f"Überschneidung: „{self.quarter}“ ist von {other.start} bis "
                    f"{other.end} bereits {other.member} zugeteilt.")
            elif ExternalBooking.objects.filter(
                    quarter_id=self.quarter_id,
                    status=ExternalBooking.CONFIRMED,
                    start__lt=self.end, end__gt=self.start).exists():
                errors["quarter"] = (
                    "Überschneidung mit einer bestätigten externen Buchung in "
                    "diesem Zeitraum.")
        if errors:
            raise ValidationError(errors)

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
    # Bestätigungs-Workflow: ein Lauf ist zunächst unbestätigt (Ergebnis für
    # Mitglieder unsichtbar, keine Benachrichtigungen). Erst die Bestätigung
    # veröffentlicht ihn; danach ist er nicht mehr rücknehmbar.
    confirmed = models.BooleanField("Bestätigt/veröffentlicht", default=False)
    confirmed_at = models.DateTimeField("Bestätigt am", null=True, blank=True)
    # Faktor-Stände VOR dem Lauf (für ein sauberes Rückgängigmachen) und die
    # vorbereiteten, noch nicht zugestellten Benachrichtigungen.
    karma_snapshot = models.JSONField("Karma vor dem Lauf", default=dict, blank=True)
    notices = models.JSONField("Vorbereitete Benachrichtigungen", default=list, blank=True)
    # Kennzahlen des Laufs (für die Verwaltungs-Statistik).
    n_allocations = models.PositiveIntegerField("Erfüllte Wünsche (Zuteilungen)",
                                                default=0)
    n_losses = models.PositiveIntegerField("Nicht erfüllte Wünsche (Verluste)",
                                           default=0)

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
        indexes = [
            models.Index(fields=["quarter", "fulfilled"]),
        ]

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
    detail = models.TextField("Details", blank=True)
    url = models.CharField("Link", max_length=200, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    read = models.BooleanField("Gelesen", default=False)

    class Meta:
        verbose_name = "Benachrichtigung"
        verbose_name_plural = "Benachrichtigungen"
        ordering = ["-created_at"]
        indexes = [
            # unread_notifications (member + read) auf jeder Seite.
            models.Index(fields=["member", "read"]),
        ]

    def __str__(self) -> str:
        return f"{self.member}: {self.message}"


class PushSubscription(models.Model):
    """Web-Push-Abo eines Mitglieds (ein Eintrag je Browser/Gerät). Speichert den
    vom Browser gelieferten Endpoint + Schlüssel; der Versand läuft über
    `services.send_web_push` (nur wenn VAPID-Schlüssel gesetzt sind)."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="push_subscriptions",
        verbose_name="Mitglied")
    endpoint = models.TextField("Endpoint", unique=True)
    p256dh = models.CharField("Schlüssel (p256dh)", max_length=200)
    auth = models.CharField("Auth-Secret", max_length=100)
    user_agent = models.CharField("Gerät/Browser", max_length=300, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Push-Abo"
        verbose_name_plural = "Push-Abos"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Push-Abo {self.member} ({self.endpoint[:40]}…)"


class OpsConfig(models.Model):
    """Betriebs-Einstellungen der Verwaltung (Singleton): Empfänger der
    Verwaltungs-Mails (anstehende Buchungen) und der Reinigungsliste."""
    admin_emails = models.CharField(
        "Verwaltung – E-Mail(s)", max_length=400, blank=True,
        help_text="Komma-getrennt. Empfänger der Übersicht über anstehende "
                  "Buchungen.")
    cleaning_emails = models.CharField(
        "Reinigungsteam – E-Mail(s)", max_length=400, blank=True,
        help_text="Komma-getrennt. Empfänger der Putzliste. Leer = wie Verwaltung.")
    notify_day = models.PositiveSmallIntegerField(
        "Monats-Mail am Tag", default=25,
        help_text="An diesem Tag des Monats geht die Übersicht der Buchungen des "
                  "Folgemonats automatisch an die Verwaltung.")
    last_admin_notice = models.DateField(
        "Zuletzt benachrichtigt am", null=True, blank=True, editable=False)
    beds24_import_enabled = models.BooleanField(
        "Beds24-Import anzeigen", default=True,
        help_text="Der Beds24-Migrations-Assistent wird i. d. R. nur EINMALIG "
                  "gebraucht. Nach dem Umzug hier ausschalten, dann ist er im "
                  "Dashboard ausgeblendet und gesperrt.")

    class Meta:
        verbose_name = "Betriebs-Einstellungen"
        verbose_name_plural = "Betriebs-Einstellungen"

    def __str__(self) -> str:
        return "Betriebs-Einstellungen"

    @classmethod
    def get_solo(cls) -> "OpsConfig":
        return cls.objects.first() or cls.objects.create()

    @staticmethod
    def _parse(raw: str) -> list[str]:
        import re
        return [e for e in re.split(r"[,;\s]+", raw or "") if "@" in e]

    def admin_list(self) -> list[str]:
        return self._parse(self.admin_emails)

    def cleaning_list(self) -> list[str]:
        return self._parse(self.cleaning_emails) or self.admin_list()


class OutboxEmail(models.Model):
    """Ausgehende E-Mail in der Warteschlange. Das Versenden ist vom Request
    entkoppelt (wichtig für Massenmails): das Kommando `send_outbox` – vom
    Scheduler regelmäßig aufgerufen – arbeitet die offenen Mails ab."""
    to_email = models.EmailField("Empfänger")
    subject = models.CharField("Betreff", max_length=200)
    body = models.TextField("Text")
    html_body = models.TextField("HTML", blank=True)
    member = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="emails", verbose_name="Mitglied")
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    sent_at = models.DateTimeField("Versendet am", null=True, blank=True)
    attempts = models.PositiveIntegerField("Versuche", default=0)
    last_error = models.CharField("Letzter Fehler", max_length=300, blank=True)
    # Optionaler Datei-Anhang (z.B. Rechnungs-PDF). Inhalt liegt in der DB –
    # für kleine Dateien (PDFs) völlig ausreichend.
    attachment = models.BinaryField("Anhang", null=True, blank=True, editable=False)
    attachment_name = models.CharField("Anhang-Dateiname", max_length=120, blank=True)
    attachment_mime = models.CharField(
        "Anhang-Typ", max_length=80, blank=True, default="application/octet-stream")

    class Meta:
        verbose_name = "E-Mail (Ausgang)"
        verbose_name_plural = "E-Mails (Ausgang)"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["sent_at", "attempts"])]

    def __str__(self) -> str:
        return f"{self.to_email}: {self.subject}"


class SwapRequest(models.Model):
    """Wechselwunsch: ein Mitglied möchte mit einem anderen, das im selben
    Zeitraum da ist, das Quartier tauschen. Das Gegenüber kann zustimmen oder
    ablehnen; beide werden per Notification informiert. Die tatsächliche
    Umbuchung stimmen die Beteiligten anschließend miteinander/mit der
    Verwaltung ab."""
    PENDING, ACCEPTED, DECLINED = "pending", "accepted", "declined"
    STATUS = [
        (PENDING, "Offen"),
        (ACCEPTED, "Angenommen"),
        (DECLINED, "Abgelehnt"),
    ]
    from_member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="swap_requests_sent",
        verbose_name="Von Mitglied",
    )
    to_member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="swap_requests_received",
        verbose_name="An Mitglied",
    )
    from_allocation = models.ForeignKey(
        "Allocation", on_delete=models.CASCADE, related_name="swap_from",
        verbose_name="Eigene Buchung",
    )
    to_allocation = models.ForeignKey(
        "Allocation", on_delete=models.CASCADE, related_name="swap_to",
        verbose_name="Gewünschte Buchung",
    )
    message = models.TextField("Nachricht", blank=True)
    status = models.CharField("Status", max_length=10, choices=STATUS, default=PENDING)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    responded_at = models.DateTimeField("Beantwortet am", null=True, blank=True)

    class Meta:
        verbose_name = "Wechselwunsch"
        verbose_name_plural = "Wechselwünsche"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (f"{self.from_member} → {self.to_member} "
                f"({self.get_status_display()})")


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
    start_month = models.PositiveSmallIntegerField("Von (Monat)")
    start_day = models.PositiveSmallIntegerField("Von (Tag)")
    end_month = models.PositiveSmallIntegerField("Bis exkl. (Monat)")
    end_day = models.PositiveSmallIntegerField("Bis exkl. (Tag)")
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
        ordering = ["start_month", "start_day"]

    def __str__(self) -> str:
        parts = []
        if self.min_nights:
            parts.append(f"min {self.min_nights} N")
        if self.max_parallel_units is not None:
            parts.append(f"max {self.max_parallel_units} parallel")
        if self.max_stay_nights is not None:
            parts.append(f"Deckel {self.max_stay_nights} N")
        flag = "" if self.active else " [inaktiv]"
        return (f"{self.name} ({self.start_day}.{self.start_month}.–"
                f"{self.end_day}.{self.end_month}.; {', '.join(parts)}){flag}")


class SchoolHoliday(models.Model):
    """Schulferien (z.B. Berlin) – jährlich wiederkehrend. Werden im Kalender
    angezeigt UND können, wenn aktiv, in ihrem Zeitraum Buchungsregeln
    durchsetzen (wie eine Saison-Regel). Leere Regelfelder = nur Anzeige."""
    policy = models.ForeignKey(
        BookingPolicy, on_delete=models.CASCADE, null=True, blank=True,
        related_name="school_holidays", verbose_name="Regelwerk",
    )
    name = models.CharField("Bezeichnung", max_length=140)
    start_month = models.PositiveSmallIntegerField("Von (Monat)")
    start_day = models.PositiveSmallIntegerField("Von (Tag)")
    end_month = models.PositiveSmallIntegerField("Bis exkl. (Monat)")
    end_day = models.PositiveSmallIntegerField("Bis exkl. (Tag)")
    region = models.CharField("Region", max_length=40, default="Berlin")
    min_nights = models.PositiveIntegerField(
        "Mindestnächte", null=True, blank=True,
        help_text="Leer = keine Mindestnächte-Regel in diesem Zeitraum.",
    )
    max_parallel_units = models.PositiveIntegerField(
        "Max. gleichzeitige Wohneinheiten", null=True, blank=True,
        help_text="Leer = unbegrenzt.",
    )
    max_stay_nights = models.PositiveIntegerField(
        "Max. Nächte je Partei (Deckel)", null=True, blank=True,
        help_text="Leer = kein Deckel.",
    )
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Schulferien"
        verbose_name_plural = "Schulferien"
        ordering = ["start_month", "start_day"]

    def __str__(self) -> str:
        return (f"{self.name} ({self.start_day}.{self.start_month}.–"
                f"{self.end_day}.{self.end_month}., {self.region})")


# --------------------------------------------------------------------------- #
# Externe Gäste (siehe docs/EXTERNE-GAESTE.md)
# --------------------------------------------------------------------------- #

class Guest(models.Model):
    """Ein externer Gast (kein Login). Bucht über den öffentlichen Bereich;
    Verwaltung der eigenen Buchung später per Magic-Link (Token)."""
    name = models.CharField("Name", max_length=160)
    email = models.EmailField("E-Mail")
    street = models.CharField("Straße & Nr.", max_length=160, blank=True)
    zip_code = models.CharField("PLZ", max_length=12, blank=True)
    city = models.CharField("Ort", max_length=120, blank=True)
    country = models.CharField("Land", max_length=2, default="DE")
    token = models.UUIDField("Verwaltungs-Token", default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Externer Gast"
        verbose_name_plural = "Externe Gäste"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    @property
    def address(self) -> str:
        line2 = f"{self.zip_code} {self.city}".strip()
        return "\n".join(p for p in [self.street, line2] if p.strip())


class ExternalConfig(models.Model):
    """Regeln & Konditionen für externe Gäste (Singleton). Steuert, WANN externe
    Gäste grundsätzlich buchen dürfen – unabhängig von der konkreten Belegung."""
    active = models.BooleanField(
        "Buchung für Externe aktiv", default=False,
        help_text="Globaler Schalter. Aus = externe Buchung gesperrt.")
    allowed_weekdays = models.CharField(
        "Erlaubte Übernachtungs-Wochentage", max_length=20, blank=True, default="",
        help_text="Komma-getrennt 0=Mo … 6=So. Jede Nacht muss auf einen dieser "
                  "Wochentage fallen. Beispiel „0,1,2,3“ = Mo–Do (Anreise So–Mi, "
                  "Abreise bis Do). Leer = alle Wochentage.")
    min_nights_follow_internal = models.BooleanField(
        "Mindestaufenthalt wie intern", default=True,
        help_text="An (Standard): Externe haben denselben Mindestaufenthalt wie "
                  "Mitglieder – inkl. Saison-Mindestnächte (z. B. 7 im Sommer). "
                  "Aus: stattdessen gilt der eigene feste Wert unten.")
    min_nights = models.PositiveSmallIntegerField(
        "Eigener Mindestaufenthalt (Nächte)", default=2,
        help_text="Nur wirksam, wenn „Mindestaufenthalt wie intern“ AUS ist. "
                  "Darf von den internen Vorgaben abweichen (höher oder niedriger; "
                  "ohne Saison-Verschärfung).")
    max_nights = models.PositiveSmallIntegerField(
        "Höchstnächte (0 = unbegrenzt)", default=0)
    lead_days = models.PositiveSmallIntegerField(
        "Vorlauf (Tage)", default=1,
        help_text="Frühestens so viele Tage vor Anreise buchbar.")
    horizon_days = models.PositiveSmallIntegerField(
        "Vorausbuchung (Tage, 0 = unbegrenzt)", default=365)
    cleaning_fee = models.DecimalField(
        "Endreinigung (brutto)", max_digits=8, decimal_places=2, default=0)
    cleaning_vat = models.PositiveSmallIntegerField("MwSt Reinigung", default=19)
    stay_vat = models.PositiveSmallIntegerField("MwSt Beherbergung", default=7)
    payment_term_days = models.PositiveSmallIntegerField("Zahlungsziel (Tage)", default=14)
    # Anzahlung (Naht für den Bezahlprozess: heute nur informativ ausgewiesen).
    deposit_percent = models.PositiveSmallIntegerField(
        "Anzahlung in % (0 = keine)", default=0,
        help_text="Anteil des Gesamtbetrags, der als Anzahlung fällig ist.")
    # Stornobedingungen (Refund-Staffel nach Vorlauf zur Anreise).
    free_cancel_days = models.PositiveSmallIntegerField(
        "Kostenlose Stornofrist (Tage vor Anreise)", default=30,
        help_text="Bis so viele Tage vor Anreise volle Erstattung.")
    partial_cancel_days = models.PositiveSmallIntegerField(
        "Teil-Storno-Frist (Tage vor Anreise)", default=7,
        help_text="Bis so viele Tage vor Anreise teilweise Erstattung.")
    partial_refund_percent = models.PositiveSmallIntegerField(
        "Erstattung im Teil-Storno-Fenster (%)", default=50)
    late_fee = models.DecimalField(
        "Säumniszuschlag (brutto)", max_digits=8, decimal_places=2, default=0,
        help_text="Pauschale bei verspäteter Zahlung (mit der Mahnung fällig).")
    terms = models.TextField(
        "Stornobedingungen (Anzeigetext)", blank=True,
        help_text="Wird Gästen bei der Buchung und im Magic-Link angezeigt. "
                  "Leer = aus den Fristen automatisch erzeugter Text.")

    class Meta:
        verbose_name = "Externe-Gäste-Einstellungen"
        verbose_name_plural = "Externe-Gäste-Einstellungen"

    def __str__(self) -> str:
        return "Externe-Gäste-Einstellungen"

    @classmethod
    def get_solo(cls) -> "ExternalConfig":
        return cls.objects.first() or cls.objects.create()

    @property
    def allowed_weekday_set(self) -> set[int]:
        return {int(x) for x in self.allowed_weekdays.split(",") if x.strip().isdigit()}

    @property
    def cancellation_text(self) -> str:
        """Anzeige-Text der Stornobedingungen (eigener Text oder aus Fristen)."""
        if self.terms.strip():
            return self.terms.strip()
        parts = [f"Bis {self.free_cancel_days} Tage vor Anreise kostenlos stornierbar "
                 "(volle Erstattung)."]
        if self.partial_refund_percent and self.partial_cancel_days < self.free_cancel_days:
            parts.append(
                f"Bis {self.partial_cancel_days} Tage vorher Erstattung von "
                f"{self.partial_refund_percent} %.")
        parts.append("Danach bzw. bei Nichtanreise keine Erstattung.")
        return " ".join(parts)

    def deposit_for(self, total) -> Decimal:
        """Anzahlungsbetrag (brutto) für einen Gesamtbetrag."""
        if not self.deposit_percent:
            return Decimal("0")
        cents = (Decimal(total) * Decimal(self.deposit_percent) / Decimal(100))
        return cents.quantize(Decimal("0.01"))


class ExternalBooking(models.Model):
    """Eine Buchung eines externen Gastes. Blockiert (wenn bestätigt) die
    Verfügbarkeit; abgerechnet wird über eine `shop.Invoice` (Rechnung wie im
    Hofladen). Status `pending` ist als Naht für den späteren Online-Bezahlprozess
    vorgesehen (Hold bis Zahlungseingang)."""
    PENDING, CONFIRMED, CANCELLED = "pending", "confirmed", "cancelled"
    STATUS = [
        (PENDING, "Reserviert (Zahlung offen)"),
        (CONFIRMED, "Bestätigt"),
        (CANCELLED, "Storniert"),
    ]
    guest = models.ForeignKey(
        Guest, on_delete=models.CASCADE, related_name="bookings", verbose_name="Gast")
    quarter = models.ForeignKey(
        Quarter, on_delete=models.PROTECT, related_name="external_bookings",
        verbose_name="Quartier")
    start = models.DateField("Anreise")
    end = models.DateField("Abreise (exkl.)")
    persons = models.PositiveIntegerField("Personen", default=1)
    status = models.CharField("Status", max_length=10, choices=STATUS, default=CONFIRMED)
    total_gross = models.DecimalField("Betrag (brutto)", max_digits=10,
                                      decimal_places=2, default=0)
    invoice = models.ForeignKey(
        "shop.Invoice", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="external_booking", verbose_name="Rechnung")
    # Naht für den Online-Bezahlprozess (Hold bis Zahlungseingang).
    hold_expires_at = models.DateTimeField("Reservierung gültig bis", null=True, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    confirmed_at = models.DateTimeField("Bestätigt am", null=True, blank=True)
    cancelled_at = models.DateTimeField("Storniert am", null=True, blank=True)

    class Meta:
        verbose_name = "Externe Buchung"
        verbose_name_plural = "Externe Buchungen"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["quarter", "start", "end"]),
                   models.Index(fields=["status", "start"])]

    def __str__(self) -> str:
        return f"{self.guest.name} @ {self.quarter} {self.start}–{self.end}"

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def blocks_availability(self, now=None) -> bool:
        """Bestätigt → blockiert; reserviert → blockiert, solange der Hold gilt."""
        if self.status == self.CONFIRMED:
            return True
        if self.status == self.PENDING:
            from django.utils import timezone
            now = now or timezone.now()
            return self.hold_expires_at is None or self.hold_expires_at > now
        return False


class FairnessSimConfig(models.Model):
    """Einstellungen + letztes Ergebnis des statistischen Fairness-Nachweises
    (Monte-Carlo-Simulation des Losverfahrens). Singleton; im Backend
    konfiguriert und per Admin-Aktion gestartet, Ergebnis auf der Login-Seite
    `/losung-fairness/`. Reine Logik in `booking/fairness.py`."""
    n_users = models.PositiveSmallIntegerField(
        "Nutzer (gleich gestellt)", default=10,
        help_text="Anzahl gleich gestellter Parteien (alle Karma 1,0).")
    n_items = models.PositiveSmallIntegerField(
        "Knappe Quartiere / Wünsche je Nutzer", default=4,
        help_text="Anzahl umkämpfter Quartiere im selben Zeitraum (Knappheit "
                  "M < Nutzer). Jeder Nutzer wünscht alle.")
    n_runs = models.PositiveIntegerField(
        "Anzahl Lose-Durchläufe", default=2000,
        help_text="Wie viele Ziehungen mit unterschiedlichem Seed gemittelt "
                  "werden (mehr = engere Konfidenzintervalle).")
    last_result = models.JSONField("Letztes Ergebnis", null=True, blank=True)
    last_run_at = models.DateTimeField("Zuletzt berechnet", null=True, blank=True)

    class Meta:
        verbose_name = "Fairness-Nachweis"
        verbose_name_plural = "Fairness-Nachweis"

    def __str__(self) -> str:
        return "Fairness-Nachweis (Losverfahren)"

    @classmethod
    def get_solo(cls) -> "FairnessSimConfig":
        return cls.objects.first() or cls.objects.create()


class Beds24Import(models.Model):
    """Ein Lauf des Beds24-Migrations-Assistenten (CSV-Upload). Hält Eckdaten;
    die einzelnen Buchungszeilen stehen als `Beds24ImportRow` zum manuellen
    Abgleich (Mitglied/Quartier zuordnen → als Buchung übernehmen)."""
    created_at = models.DateTimeField("Hochgeladen am", auto_now_add=True)
    filename = models.CharField("Datei", max_length=200, blank=True)
    n_rows = models.PositiveIntegerField("Zeilen gesamt", default=0)
    n_imported = models.PositiveIntegerField("Übernommen", default=0)

    class Meta:
        verbose_name = "Beds24-Import"
        verbose_name_plural = "Beds24-Importe"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Beds24-Import {self.created_at:%d.%m.%Y %H:%M} ({self.filename})"


class Beds24ImportRow(models.Model):
    """Eine Buchungszeile aus dem Beds24-CSV im Abgleich. `suggested_member`/
    `suggested_quarter` sind die automatischen Vorschläge; `chosen_*` setzt die
    Verwaltung beim manuellen Abgleich. Beim Übernehmen entsteht `allocation`."""
    PENDING, IMPORTED, SKIPPED = "pending", "imported", "skipped"
    STATUS = [(PENDING, "Offen"), (IMPORTED, "Übernommen"), (SKIPPED, "Übersprungen")]

    batch = models.ForeignKey(Beds24Import, on_delete=models.CASCADE,
                              related_name="rows", verbose_name="Import")
    guest_name = models.CharField("Gastname (Beds24)", max_length=200)
    email = models.EmailField("E-Mail (Beds24)", blank=True)
    arrival = models.DateField("Anreise", null=True, blank=True)
    departure = models.DateField("Abreise", null=True, blank=True)
    unit = models.CharField("Unit/Quartier (Beds24)", max_length=200, blank=True)
    persons = models.PositiveIntegerField("Personen", default=1)
    ref = models.CharField("Referenz", max_length=80, blank=True)
    raw = models.JSONField("Originalzeile", default=dict, blank=True)

    suggested_member = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Vorschlag Mitglied")
    suggested_score = models.FloatField("Treffergüte", default=0.0)
    # Wie der Vorschlag zustande kam – bestimmt die Ampel und die Vorauswahl:
    #   email  = eindeutiger E-Mail-Treffer (🟢 sicher, vorausgewählt)
    #   name   = ein guter Namens-Treffer (🟡 prüfen, vorgeschlagen)
    #   multi  = mehrere mögliche Namens-Treffer (🟡 prüfen, NICHT vorausgewählt)
    #   ""     = kein Treffer (🔴)
    EMAIL, NAME, MULTI = "email", "name", "multi"
    match_kind = models.CharField("Treffer-Art", max_length=10, blank=True)
    suggested_quarter = models.ForeignKey(
        Quarter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Vorschlag Quartier")
    chosen_member = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Mitglied")
    chosen_quarter = models.ForeignKey(
        Quarter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Quartier")
    status = models.CharField("Status", max_length=10, choices=STATUS, default=PENDING)
    allocation = models.ForeignKey(
        "Allocation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Erzeugte Buchung")
    note = models.CharField("Hinweis", max_length=200, blank=True)

    class Meta:
        verbose_name = "Beds24-Buchungszeile"
        verbose_name_plural = "Beds24-Buchungszeilen"
        ordering = ["arrival", "id"]

    def __str__(self) -> str:
        return f"{self.guest_name} {self.arrival}–{self.departure}"

    @property
    def nights(self) -> int:
        if self.arrival and self.departure:
            return max(0, (self.departure - self.arrival).days)
        return 0

    @property
    def valid(self) -> bool:
        return bool(self.guest_name and self.arrival and self.departure
                    and self.departure > self.arrival)
