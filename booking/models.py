"""Datenmodelle der Buchungs-App."""
from __future__ import annotations

from datetime import date, timedelta

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
    membership_number = models.CharField(
        "Mitgliedsnummer (optional)", max_length=40, blank=True)

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
    # Reihenfolge des Lebenszyklus (für die automatische Vorwärts-Schaltung).
    LIFECYCLE = [DRAFT, WISHES_OPEN, LOTTERY_READY, LOTTERY_DONE,
                 FREE_BOOKING, ENDED]

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
            return self.LOTTERY_DONE
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
