"""Datenmodelle der Buchungs-App."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Group, User
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
    # Reihenfolge im Belegungsplan (an beds24 angelehnt, #38). Default 0 = wie bisher
    # alphabetisch; die Verwaltung vergibt die gewohnte beds24-Reihenfolge im Backend.
    sort_order = models.PositiveIntegerField(
        "Reihenfolge (Belegungsplan)", default=0,
        help_text="Sortierung im Belegungsplan – kleiner = weiter oben (an beds24 "
                  "angelehnt). Gleiche Werte werden alphabetisch gereiht.")
    # Optionale Zielauslastung für das statische Ampel-System im Dashboard.
    target_occupancy = models.PositiveSmallIntegerField(
        "Ziel-Auslastung (%)", null=True, blank=True,
        help_text="Optionale Zielauslastung in Prozent. Ist sie gesetzt, zeigt das "
                  "Dashboard je Quartier eine Ampel (🔴/🟡/🟢). Leer = keine Ampel.")
    # Zählt diese Einheit in die Auslastungs-Quote (Gemeinschaft/Dashboard)? Camping-
    # und Gemeinschaftsflächen bewusst NICHT einbeziehen (ADR 0096).
    count_in_occupancy = models.BooleanField(
        "In Auslastungs-Quote einbeziehen", default=True,
        help_text="Aus, wenn diese Fläche NICHT in die Auslastungs-Statistik zählen "
                  "soll (z. B. Camping- oder Gemeinschaftsflächen). Buchbar bleibt sie "
                  "trotzdem.")
    # Organisatorische Gruppierung + sanfte Gruppen-Empfehlung (ADR 0075).
    building = models.CharField(
        "Gebäude", max_length=80, blank=True, default="",
        help_text="Organisatorische Gruppierung, z. B. „Stallgebäude“ (nur Anzeige).")
    prefer_for_groups = models.BooleanField(
        "Für Gruppen zuerst anbieten", default=False,
        help_text="Diese Wohneinheit wird Gruppen (große Personenzahl) zuerst "
                  "empfohlen – z. B. die Wohnungen des Stallgebäudes. Keine harte "
                  "Sperre, nur Reihenfolge/Hinweis.")
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
        # sort_order zuerst (Belegungsplan-Reihenfolge, #38); bei Gleichstand
        # (Default 0 für alle) fällt es auf die bisherige Namens-Sortierung zurück.
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def has_season(self) -> bool:
        return bool(self.season_start_month and self.season_start_day
                    and self.season_end_month and self.season_end_day)

    @property
    def season_label(self) -> str:
        """Menschenlesbarer Saison-Zeitraum ohne Jahr (z. B. „01.05.–30.09.“).
        Leer, wenn das Quartier ganzjährig buchbar ist."""
        if not self.has_season:
            return ""
        return (f"{self.season_start_day:02d}.{self.season_start_month:02d}."
                f"–{self.season_end_day:02d}.{self.season_end_month:02d}.")

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
    accept_swap_requests = models.BooleanField(
        "Tausch-Anfragen erlauben", default=True,
        help_text="Wenn aus, erscheint das Mitglied für andere nicht als "
                  "Tausch-Partner und kann keine Tausch-Anfrage erhalten (ADR 0078). "
                  "Die reine Anzeige „wer ist zur gleichen Zeit da“ bleibt.")
    coordination_hide_phone = models.BooleanField(
        "Telefon für Absprachen verbergen", default=False,
        help_text="In der Entzerrungsphase vor der Losung sehen Mitglieder mit einem "
                  "überlappenden Wunsch Name + Kontakt, damit sie sich privat absprechen "
                  "können (Standard: sichtbar, ADR 0101). Wenn AN, wird die "
                  "Telefonnummer dort NICHT gezeigt (der Name bleibt sichtbar).")
    coordination_hide_email = models.BooleanField(
        "E-Mail für Absprachen verbergen", default=False,
        help_text="Wie oben, aber für die E-Mail-Adresse. Wenn AN, wird die E-Mail in "
                  "der Entzerrungsphase NICHT gezeigt (der Name bleibt sichtbar).")
    # Profil-/Rechnungsdaten (vom Nutzer selbst pflegbar; nur eigene Sicht)
    legal_name = models.CharField("Vollständiger Name", max_length=160, blank=True)
    phone = models.CharField(
        "Telefon", max_length=40, blank=True,
        help_text="Für Rückfragen der Betriebsleitung (im Profil selbst änderbar).")
    street = models.CharField("Straße & Nr.", max_length=160, blank=True)
    zip_code = models.CharField("PLZ", max_length=10, blank=True)
    city = models.CharField("Ort", max_length=120, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    # Hofladen-Terminal (ADR 0053): standardmäßig für alle an; das Mitglied vergibt
    # selbst eine 6-stellige PIN (gehasht) – ERST damit landet das Konto in der
    # Terminal-Roster. Wer nicht teilnehmen will, schaltet es im Profil aus (dann ist
    # auch eine evtl. gesetzte PIN inaktiv).
    terminal_enabled = models.BooleanField("Hofladen-Terminal erlaubt", default=True)
    terminal_pin = models.CharField("Terminal-PIN (gehasht)", max_length=128, blank=True)
    # Mitgliedsstatus (datumsgesteuert, ADR 0087). Leer = aktiv. Ab `passive_from`
    # gilt „passiv" (Login/Hofladen an, KEINE neuen Buchungen/Wünsche, bestehende
    # bleiben). Ab `excluded_from` gilt „ausgeschieden" (Login deaktiviert; ein
    # täglicher Scheduler-Schritt setzt dann User.is_active=False).
    passive_from = models.DateField(
        "Passiv ab", null=True, blank=True,
        help_text="Ab diesem Datum kann das Mitglied nicht mehr buchen "
                  "(Hofladen/Login bleiben). Leer = aktiv.")
    excluded_from = models.DateField(
        "Ausgeschieden ab", null=True, blank=True,
        help_text="Ab diesem Datum ist das Konto deaktiviert (Login aus). "
                  "Bestehende Buchungen nach diesem Datum müssen vorher gelöst werden.")

    def set_terminal_pin(self, pin: str) -> None:
        from django.contrib.auth.hashers import make_password
        self.terminal_pin = make_password(pin, hasher="pbkdf2_sha256")

    def check_terminal_pin(self, pin: str) -> bool:
        from django.contrib.auth.hashers import check_password
        return bool(self.terminal_pin) and check_password(pin, self.terminal_pin)

    @property
    def terminal_ready(self) -> bool:
        return self.terminal_enabled and bool(self.terminal_pin)

    def status_on(self, on_date=None) -> str:
        """Effektiver Mitgliedsstatus zu einem Stichtag: ``'active'`` · ``'passive'``
        · ``'excluded'`` (datumsgesteuert, ADR 0087)."""
        from datetime import date as _date
        d = on_date or _date.today()
        if self.excluded_from and d >= self.excluded_from:
            return "excluded"
        if self.passive_from and d >= self.passive_from:
            return "passive"
        return "active"

    @property
    def status(self) -> str:
        return self.status_on()

    @property
    def can_book(self) -> bool:
        """Nur aktive Mitglieder dürfen neu buchen / Wünsche eintragen."""
        return self.status == "active"

    @classmethod
    def active_members(cls, on_date=None, base=None):
        """Queryset der zum Stichtag **aktiven** Mitglieder (nicht passiv/ausgeschieden,
        ADR 0087) – DB-seitig, z. B. als Empfänger:innen einer Tage-Übertragung. `base`
        erlaubt eine Vorfilterung (z. B. `is_external=False`)."""
        from datetime import date as _date
        d = on_date or _date.today()
        qs = cls.objects.all() if base is None else base
        return qs.exclude(excluded_from__lte=d).exclude(passive_from__lte=d)

    @property
    def is_passive(self) -> bool:
        return self.status == "passive"

    @property
    def has_bookings(self) -> bool:
        """Ob (aktuell oder historisch) Buchungen bestehen – steuert, ob passive
        Mitglieder „Meine Buchungen"/„Übersicht" in der Navigation sehen."""
        return self.allocations.filter(provisional=False).exists()

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
        """Wunsch-Budget für die Losung = **genau die Hälfte** der Jahres-Tage des
        Mitglieds, **abgerundet** (50→25, 25→12, …). Wird IMMER aus dem Tage-Budget
        abgeleitet – nicht je Anteil gespeichert (ADR 0073)."""
        return self.annual_night_budget // 2

    def nights_used_in_year(self, year: int) -> int:
        # Nur bestätigte Buchungen zählen als „gebucht" – vorläufige (unbestätigte
        # Losungs-)Zuteilungen sind für das Mitglied unsichtbar und würden die
        # Anzeige verfälschen (Feedback #9).
        total = 0
        for a in self.allocations.filter(start__year=year, provisional=False):
            total += (a.end - a.start).days
        return total

    def nights_received_in_year(self, year: int) -> int:
        return sum(t.nights for t in self.transfers_in.filter(year=year))

    def nights_given_in_year(self, year: int) -> int:
        return sum(t.nights for t in self.transfers_out.filter(year=year))

    def pool_received_in_year(self, year: int) -> int:
        """Aus dem Solidaritäts-Pool entnommene Tage (P2.5)."""
        return sum(e.nights for e in self.pool_entries.filter(
            year=year, kind="withdraw"))

    def pool_donated_in_year(self, year: int) -> int:
        """In den Solidaritäts-Pool gespendete Tage (P2.5)."""
        return sum(e.nights for e in self.pool_entries.filter(
            year=year, kind="donate"))

    def pool_net_in_year(self, year: int) -> int:
        """Netto-Wirkung des Pools aufs Budget (Entnahmen − Spenden) in EINER
        Aggregat-Abfrage – für den heißen Budget-Pfad (ADR 0060/0064)."""
        from django.db.models import Sum
        rows = (self.pool_entries.filter(year=year)
                .values("kind").annotate(s=Sum("nights")))
        by = {r["kind"]: r["s"] or 0 for r in rows}
        return by.get("withdraw", 0) - by.get("donate", 0)

    def forfeited_nights_in_year(self, year: int) -> int:
        """Kurzfristig verwirkte Tage des Jahres (ADR 0088), die (noch) NICHT von
        anderen Mitgliedern neu gebucht wurden – sie mindern das Jahreskontingent."""
        return sum(f.effective for f in self.forfeits.filter(year=year)
                   .select_related("quarter"))

    def compensation_days_in_year(self, year: int) -> int:
        """Von der Verwaltung gewährte Ausgleichs-Tage (ADR 0097, dringende
        Sperrung ohne Ersatz-Unterkunft) – additiv zum Budget."""
        from django.db.models import Sum
        return self.compensations.filter(year=year).aggregate(
            s=Sum("days"))["s"] or 0

    def effective_annual_budget(self, year: int) -> int:
        """Jahreskontingent inkl. erhaltener/abgegebener Tage, Pool-Spenden/-Entnahmen
        und Ausgleichs-Tagen (kein Übertrag aus dem Vorjahr) – abzüglich kurzfristig
        verwirkter Tage (ADR 0088/0097)."""
        return (
            self.annual_night_budget
            + self.nights_received_in_year(year)
            - self.nights_given_in_year(year)
            + self.pool_net_in_year(year)
            + self.compensation_days_in_year(year)
            - self.forfeited_nights_in_year(year)
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

    def membership_for(self, membership_id=None):
        """Der Mitglieds-Anteil, dem eine Buchung/ein Wunsch zugerechnet wird –
        damit die Buchungsregeln (Parallel-Limit/Aufenthaltsdeckel) auf den
        VOLLEN Anteil (inkl. Tandem-Partner) wirken.

        Bei genau einem Anteil dieser; bei mehreren (Mehrfach-Tandem) der explizit
        gewählte (sofern dem Nutzer zugeordnet) bzw. – ohne Wahl – deterministisch
        der größte Anteil (Tage-Anteil, dann id). None, wenn der Nutzer keinem
        Anteil angehört (z.B. externer Gast)."""
        shares = list(self.shares.select_related("membership"))
        if not shares:
            return None
        if membership_id not in (None, ""):
            for s in shares:
                if s.membership_id == int(membership_id):
                    return s.membership
        shares.sort(key=lambda s: (-s.night_budget, s.membership_id))
        return shares[0].membership


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
    WISHES_REVIEW = "wishes_review"
    LOTTERY_READY = "lottery_ready"
    LOTTERY_REVIEW = "lottery_review"
    LOTTERY_DONE = "lottery_done"
    FREE_BOOKING = "free_booking"
    ENDED = "ended"
    SUSPENDED = "suspended"
    STATUS = [
        (DRAFT, "Entwurf"),
        (WISHES_OPEN, "Für Wunsch-Einträge freigegeben"),
        (WISHES_REVIEW, "Entzerrungsphase (Frist vorbei, anpassen möglich)"),
        (LOTTERY_READY, "Zur Auslosung freigegeben"),
        (LOTTERY_REVIEW, "Auslosung zur Prüfung (unbestätigt)"),
        (LOTTERY_DONE, "Auslosung bestätigt/veröffentlicht"),
        (FREE_BOOKING, "Freie Bebuchbarkeit innerhalb Zeitraum"),
        (ENDED, "Beendet"),
        (SUSPENDED, "Unterbrochen"),
    ]
    # Freeze: die ANGEZEIGTE Nachfrage/Prognose friert 24 h vor der Losung ein
    # (ADR 0101). Bewusst fest, nicht pro Nutzer konfigurierbar. Edits zählen
    # weiter bis draw_at – nur die Sichtbarkeit endet früher.
    FREEZE_HOURS = 24
    # Reihenfolge des Lebenszyklus (für die automatische Vorwärts-Schaltung).
    # WISHES_REVIEW liegt zwischen Wunsch-Einreichung und Auslosung (ADR 0101).
    # LOTTERY_READY bleibt als Rollback-Ziel (nach zurückgenommener Losung wieder
    # ziehbar); LOTTERY_REVIEW → LOTTERY_DONE ist bewusst MANUELL (Bestätigung).
    LIFECYCLE = [DRAFT, WISHES_OPEN, WISHES_REVIEW, LOTTERY_READY, LOTTERY_REVIEW,
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
    review_days = models.PositiveSmallIntegerField(
        "Entzerrungsphase (Tage vor Losung)", null=True, blank=True,
        help_text="Überschreibt für diese Periode die Länge der Entzerrungsphase "
                  "(ADR 0101). Leer = Vorgabe aus den Buchungsrichtlinien.")
    # Nachfrage-Snapshots (ADR 0101): vom Scheduler festgehalten – „review_open" als
    # „vor"-Stand (Export) und „frozen" als eingefrorene Anzeige der letzten Stunden.
    demand_snapshot = models.JSONField("Nachfrage-Snapshots", default=dict, blank=True)
    status = models.CharField("Status", max_length=20, choices=STATUS, default=DRAFT)
    seed = models.BigIntegerField("Zufalls-Seed", null=True, blank=True)
    # Verifizierbarkeit (Commit-Reveal, ADR 0062): Die Prüfsumme des Seeds wird
    # VOR der Ziehung veröffentlicht (sobald die Wünsche öffnen), der Seed selbst
    # erst NACH der bestätigten Ziehung offengelegt. So ist belegbar, dass der Seed
    # vorab feststand (lottery.seed_commitment / verify_commitment).
    seed_commit = models.CharField("Seed-Prüfsumme (SHA-256)", max_length=64, blank=True)
    seed_committed_at = models.DateTimeField(
        "Prüfsumme veröffentlicht am", null=True, blank=True)
    # Erinnerung an noch nicht eingereichte Wünsche (ADR 0080): zweistufig kurz vor
    # dem Losdatum. Hier wird nur der Zeitpunkt des jeweiligen Batch-Versands
    # vermerkt (Idempotenz – jede Stufe genau einmal je Periode).
    wish_reminder1_at = models.DateTimeField(
        "1. Wunsch-Erinnerung versendet am", null=True, blank=True)
    wish_reminder2_at = models.DateTimeField(
        "2. Wunsch-Erinnerung versendet am", null=True, blank=True)
    bl_reminder_at = models.DateField(
        "Verwaltungs-Erinnerung (Losung steht an) am", null=True, blank=True)

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
        # Entzerrungsphase (ADR 0101): ab der Einreiche-Frist (`review_open`) bis zur
        # Losung; der Teilnehmerkreis steht fest, Teilnehmer können noch anpassen.
        ro = self.review_open
        if ro and today >= ro:
            return self.WISHES_REVIEW
        if self.wishlist_open and today >= self.wishlist_open:
            return self.WISHES_OPEN
        return self.DRAFT

    @property
    def status_rank(self) -> int:
        return self.LIFECYCLE.index(self.status) if self.status in self.LIFECYCLE else -1

    @property
    def effective_review_days(self) -> int:
        """Länge der Entzerrungsphase (ADR 0101): Periode-Override oder Vorgabe aus
        den Buchungsrichtlinien (Default 7)."""
        if self.review_days is not None:
            return self.review_days
        return BookingPolicy.get_solo().review_days

    @property
    def review_open(self):
        """Beginn der Entzerrungsphase = **Einreiche-Frist** (ADR 0101). Bevorzugt der
        explizit gesetzte `wishlist_close`; sonst abgeleitet als „Losdatum −
        Entzerrungstage“. None, wenn weder Termin noch Losdatum gesetzt sind."""
        if self.wishlist_close:
            return self.wishlist_close
        if self.draw_at:
            return (self.draw_at - timedelta(days=self.effective_review_days)).date()
        return None

    @property
    def freeze_start(self):
        """Zeitpunkt, ab dem die ANGEZEIGTE Nachfrage/Prognose einfriert
        (`draw_at − FREEZE_HOURS`, ADR 0101). None ohne Losdatum. Edits zählen
        weiter bis `draw_at`; nur die Sichtbarkeit endet früher."""
        if self.draw_at:
            return self.draw_at - timedelta(hours=self.FREEZE_HOURS)
        return None

    def display_frozen(self, now) -> bool:
        """Ob die Anzeige der Nachfrage/Prognose gerade eingefroren ist (in den
        letzten `FREEZE_HOURS` vor der Losung)."""
        fs = self.freeze_start
        return bool(fs and self.draw_at and fs <= now < self.draw_at)

    def in_wishes_review(self, now) -> bool:
        """Ob die Periode gerade in der Entzerrungsphase ist (nach `review_open`,
        vor `draw_at`)."""
        today = now.date() if hasattr(now, "date") else now
        ro = self.review_open
        return bool(ro and today >= ro and self.draw_at and now < self.draw_at)

    @property
    def submission_deadline(self):
        """Letzter Tag, an dem Wünsche **eingereicht** werden können (danach steht der
        Teilnehmerkreis fest): der Beginn der Entzerrungsphase `review_open`.
        None, wenn kein Termin gesetzt ist. Grundlage für Anzeige + Erinnerung."""
        return self.review_open


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
    # Mitglieds-Anteil, dem der Wunsch (und ein evtl. Losgewinn) zugerechnet wird –
    # damit das Parallel-Limit/der Aufenthaltsdeckel in der Losung auf den vollen
    # Anteil inkl. Tandem-Partner wirkt (ADR 0066). Null = nicht zugeordnet.
    membership = models.ForeignKey(
        "Membership", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wishes", verbose_name="Mitglieds-Anteil",
    )
    priority = models.PositiveIntegerField("Priorität (1 = höchste)", default=1)
    quarter = models.ForeignKey(
        Quarter, on_delete=models.CASCADE, related_name="wishes",
        verbose_name="Wunschquartier",
    )
    start = models.DateField("Anreise")
    end = models.DateField("Abreise (exkl.)")
    # Wünsche sind ab dem Eintragen verbindlich und nehmen an der Losung teil (kein
    # Entwurf/„Einreichen" mehr, wie beim Buchen). `added_at` = wann aufgenommen.
    added_at = models.DateTimeField("Aufgenommen am", null=True, blank=True)
    # Audit: wer den Wunsch stellvertretend eingetragen hat (Verwaltung, ADR 0101).
    # Leer, wenn das Mitglied den Wunsch selbst angelegt hat.
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Nachgetragen von (Verwaltung)")

    class Meta:
        verbose_name = "Wunsch"
        verbose_name_plural = "Wünsche"
        ordering = ["member", "priority"]
        indexes = [
            models.Index(fields=["period"]),
            models.Index(fields=["member", "period"]),
        ]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def __str__(self) -> str:
        return f"{self.member} P{self.priority}: {self.quarter} {self.start}–{self.end}"


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
    # Mitglieds-Anteil, dem die Buchung zugerechnet wird (für die Buchungsregeln
    # auf den vollen Anteil inkl. Tandem-Partner, ADR 0066). Null = nicht
    # zugeordnet (externer Gast oder Altbuchung ohne eindeutigen Anteil).
    membership = models.ForeignKey(
        "Membership", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="allocations", verbose_name="Mitglieds-Anteil",
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
    special_requests = models.CharField(
        "Besonderheiten", max_length=255, blank=True,
        help_text="Optional: Hund, Kinder, Zustellbett o. Ä. – für die "
                  "Vorbereitung durch das Team (#62/#68).")
    internal_note = models.CharField(
        "Interne Notiz (nur Team/BL)", max_length=500, blank=True,
        help_text="Nur für Betriebsleitung/Team – wird dem Mitglied NICHT "
                  "angezeigt (#84).")
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
    # Aus der Losung entstandene Buchung, deren Details (Personen/Begleitung/
    # Besonderheiten/Endreinigung) das Mitglied noch nachtragen soll. Beim
    # Spontan-/Extern-/Import-Buchen sind die Angaben schon vollständig → False.
    details_pending = models.BooleanField(
        "Details nachzutragen", default=False,
        help_text="Los-Buchung, bei der das Mitglied Personen/Begleitung/"
                  "Besonderheiten/Endreinigung noch ergänzen soll.")
    # Idempotenz-Marke der 4-Wochen-Erinnerung (nur einmal je Buchung erinnern).
    details_reminded_on = models.DateField(
        "Vervollständigung erinnert am", null=True, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    # Audit: wer die Buchung im Backend angelegt/zuletzt geändert hat (ADR 0094).
    # Leer, wenn das Mitglied selbst über die App gebucht hat.
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Angelegt/geändert von (Verwaltung)")

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

    @property
    def by_management(self) -> bool:
        """True, wenn ein Verwaltungs-/Admin-Konto die Buchung im Backend angelegt
        hat (nicht das Mitglied selbst) – für den Hinweis in „Meine Buchungen“."""
        return bool(self.created_by_id and self.created_by_id != self.member.user_id)

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
            if self.persons:
                # Personenzahl außerhalb des ausgelegten Rahmens (zu viele ODER zu
                # wenige) ist erlaubt, wenn die Richtlinie es zulässt (ADR 0076,
                # z. B. wenn nichts Passendes mehr frei ist) – sonst Fehler.
                outside = not (self.quarter.min_occupancy <= self.persons
                               <= self.quarter.max_occupancy)
                if outside and not BookingPolicy.get_solo().allow_undersized_units:
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


class PendingUser(User):
    """Proxy auf User für die **geführte Erst-Zuordnung** neuer Konten (Onboarding).
    Eigene Admin-Seite „Neue Benutzer (Zuordnung)": Konten ohne Mitglieds-Anteil
    mit wenigen Klicks einem Anteil (Mitglied) ODER dem Hofladen-Terminal zuordnen –
    oder (unbekannt) deaktivieren/löschen (ADR 0056)."""

    class Meta:
        proxy = True
        verbose_name = "Neuer Benutzer (Zuordnung)"
        verbose_name_plural = "Neue Benutzer (Zuordnung)"


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
    # Anonymer Losergebnis-Rückblick (ADR 0102): beim Lauf vorberechnet, erst nach
    # Bestätigung im Gemeinschaftsspiegel gezeigt. Leer bei Altläufen.
    retrospective = models.JSONField("Rückblick (anonym)", default=dict, blank=True)

    class Meta:
        verbose_name = "Losdurchlauf"
        verbose_name_plural = "Losdurchläufe"
        ordering = ["-executed_at"]

    def __str__(self) -> str:
        return f"Losung {self.period} @ {self.executed_at:%Y-%m-%d %H:%M}"


class CancellationLog(models.Model):
    """Kurzer Nachweis einer **stornierten** Buchung (#30/ADR 0082). Die Buchung
    selbst wird beim Stornieren gelöscht (gibt Verfügbarkeit + Tage sofort frei);
    dieser Eintrag hält für die Mitglieds-Ansicht („Meine Buchungen“) fest, DASS und
    WAS storniert wurde – zur Sicherheit, dass die Buchung wirklich raus ist. Bewusst
    nur ein schlanker Snapshot (kein Soft-Delete → Belegungs-/Regel-Abfragen bleiben
    unberührt). DSGVO: wird nach Frist von der Aufbewahrung gelöscht."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="cancellations",
        verbose_name="Mitglied")
    quarter_name = models.CharField("Quartier", max_length=120)
    start = models.DateField("Anreise")
    end = models.DateField("Abreise")
    persons = models.PositiveIntegerField("Personen", default=1)
    source = models.CharField("Quelle", max_length=12, blank=True)
    cancelled_at = models.DateTimeField("Storniert am", auto_now_add=True)

    class Meta:
        verbose_name = "Stornierte Buchung (Nachweis)"
        verbose_name_plural = "Stornierte Buchungen (Nachweis)"
        ordering = ["-cancelled_at"]
        indexes = [models.Index(fields=["member", "cancelled_at"])]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def __str__(self) -> str:
        return f"{self.quarter_name} {self.start}–{self.end} (storniert)"


class QuarterBlock(models.Model):
    """Sperrzeitraum je Quartier für **Reinigung/Reparatur** (#61/ADR 0086). Ein
    Block macht das Quartier im Zeitraum [start, end) **nicht buchbar** (wie eine
    Belegung – geprüft in `quarter_is_free`/`find_gaps`/Belegungs-Tage) und wird im
    Belegungsplan angezeigt. Bewusst schlank: kein Mitglied, keine Rechnung."""
    quarter = models.ForeignKey(
        "Quarter", on_delete=models.CASCADE, related_name="blocks",
        verbose_name="Quartier")
    start = models.DateField("Von (Anreisesperre ab)")
    end = models.DateField("Bis (exklusiv – erster wieder freier Tag)")
    reason = models.CharField("Grund", max_length=200, blank=True,
                              help_text="z. B. Renovierung, Wasserschaden, Grundreinigung.")
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Sperrzeit (Reinigung/Reparatur)"
        verbose_name_plural = "Sperrzeiten (Reinigung/Reparatur)"
        ordering = ["start", "quarter__sort_order"]
        indexes = [models.Index(fields=["quarter", "start", "end"])]

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.start and self.end and self.end <= self.start:
            raise ValidationError({"end": "Das Bis-Datum muss nach dem Von-Datum liegen."})

    def __str__(self) -> str:
        return f"{self.quarter} gesperrt {self.start}–{self.end}"


class RelocationRequest(models.Model):
    """Umbuchungs-Anfrage der Verwaltung an ein Mitglied (ADR 0097): Muss ein Quartier
    **dringend gesperrt** werden (z. B. Wasserrohrbruch), während dort eine Buchung
    liegt, schlägt die BL dem Mitglied eine **andere freie Unterkunft** für denselben
    Zeitraum vor. Das Mitglied kann **annehmen** (Buchung zieht sofort um, unter Sperre
    geprüft) oder **ablehnen**. Ist die vorgeschlagene Unterkunft kleiner als die Gruppe
    (`undersized`), wird das dem Mitglied klar angezeigt."""
    PROPOSED, ACCEPTED, REJECTED, CANCELLED = "proposed", "accepted", "rejected", "cancelled"
    STATUS = [(PROPOSED, "Vorgeschlagen"), (ACCEPTED, "Angenommen"),
              (REJECTED, "Abgelehnt"), (CANCELLED, "Zurückgezogen")]
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="relocation_requests",
        verbose_name="Mitglied")
    allocation = models.ForeignKey(
        "Allocation", on_delete=models.CASCADE, related_name="relocation_requests",
        verbose_name="Betroffene Buchung")
    from_quarter = models.ForeignKey(
        "Quarter", on_delete=models.PROTECT, related_name="+",
        verbose_name="Bisherige (gesperrte) Unterkunft")
    to_quarter = models.ForeignKey(
        "Quarter", on_delete=models.PROTECT, related_name="+",
        verbose_name="Vorgeschlagene Unterkunft")
    undersized = models.BooleanField(
        "Kleiner als die Gruppe", default=False,
        help_text="Die vorgeschlagene Unterkunft ist kleiner als die Personenzahl "
                  "der Buchung – dem Mitglied wird das ausdrücklich mitgeteilt.")
    reason = models.CharField("Grund der Sperrung", max_length=300, blank=True)
    status = models.CharField("Status", max_length=10, choices=STATUS, default=PROPOSED)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    responded_at = models.DateTimeField("Beantwortet am", null=True, blank=True)

    class Meta:
        verbose_name = "Umbuchungs-Anfrage"
        verbose_name_plural = "Umbuchungs-Anfragen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.member} → {self.to_quarter} ({self.get_status_display()})"


class CompensationGrant(models.Model):
    """**Ausgleichs-Tage** (ADR 0097): Muss die Verwaltung eine Buchung wegen einer
    dringenden Sperrung stornieren und kann keine passende Ersatz-Unterkunft
    bereitstellen, kann sie dem Mitglied – je nach Schwere – **bis zu
    `BookingPolicy.max_compensation_days` zusätzliche Tage** gutschreiben. Fließt additiv
    ins `Member.effective_annual_budget` (wie erhaltene Übertragungen)."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="compensations",
        verbose_name="Mitglied")
    year = models.PositiveIntegerField("Jahr")
    days = models.PositiveSmallIntegerField("Ausgleichs-Tage")
    reason = models.CharField("Grund", max_length=300, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Gewährt von")

    class Meta:
        verbose_name = "Ausgleichs-Tage"
        verbose_name_plural = "Ausgleichs-Tage"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.member}: +{self.days} Tage ({self.year})"


class ForfeitedNights(models.Model):
    """**Kurzfrist-Verwirkung** von Tagen (ADR 0088): storniert/verkürzt ein Mitglied
    eine Buchung, deren Anreise ≤ `BookingPolicy.short_notice_days` entfernt ist,
    verfallen die betroffenen Nächte für das Jahr – sie werden weiter vom
    `effective_annual_budget` abgezogen. Bucht ein **anderes** Mitglied den frei
    gewordenen Zeitraum (im selben Quartier) ganz/teilweise neu, wird der gedeckte
    Anteil **dynamisch** wieder freigegeben (`Member.forfeited_nights_in_year` zählt
    die noch nicht anderweitig gebuchten Nächte). Bewusst additiv – kein Soft-Delete
    der Buchung (die bleibt storniert)."""
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="forfeits",
        verbose_name="Mitglied")
    year = models.PositiveIntegerField("Jahr")
    quarter = models.ForeignKey(
        "Quarter", on_delete=models.SET_NULL, null=True, related_name="forfeits",
        verbose_name="Quartier (frei geworden)")
    start = models.DateField("Von")
    end = models.DateField("Bis (exkl.)")
    nights = models.PositiveIntegerField("Verwirkte Nächte")
    reason = models.CharField("Anlass", max_length=20, default="cancel",
                              help_text="cancel = Storno · shorten = Verkürzung")
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Kurzfrist-Verwirkung (Tage)"
        verbose_name_plural = "Kurzfrist-Verwirkungen (Tage)"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["member", "year"])]

    def covered_by_others(self) -> int:
        """Wie viele der verwirkten Nächte inzwischen von **anderen** Mitgliedern im
        selben Quartier/Zeitraum (neu) gebucht sind (deckt die Verwirkung ab)."""
        if self.quarter_id is None:
            return 0
        covered = 0
        for s, e in Allocation.objects.filter(
                quarter_id=self.quarter_id, start__lt=self.end, end__gt=self.start,
                provisional=False).exclude(member_id=self.member_id
                                           ).values_list("start", "end"):
            lo, hi = max(s, self.start), min(e, self.end)
            if hi > lo:
                covered += (hi - lo).days
        return min(self.nights, covered)

    @property
    def effective(self) -> int:
        """Tatsächlich (noch) verwirkte Nächte = angelegt − von anderen gedeckt."""
        return max(0, self.nights - self.covered_by_others())

    def __str__(self) -> str:
        return f"{self.member} verwirkt {self.nights} Nächte ({self.year})"


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
    # P2.7: ein „Danke" der empfangenden Person an die schenkende – idempotent
    # (genau einmal je Übertragung), rein als private Wertschätzung.
    thanked_at = models.DateTimeField("Bedankt am", null=True, blank=True)

    class Meta:
        verbose_name = "Tage-Übertragung"
        verbose_name_plural = "Tage-Übertragungen"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (f"{self.nights} Tage: {self.from_member} → {self.to_member} "
                f"({self.year})")


class DayPoolEntry(models.Model):
    """Solidaritäts-/Schenkungs-Pool für Tage (P2.5, ADR 0064): Mitglieder spenden
    ungenutzte Tage in einen gemeinsamen Topf; wer (fast) kein Budget mehr hat, kann
    daraus – gedeckelt – entnehmen. Eine Zeile je Spende/Entnahme (transparentes,
    nachvollziehbares Protokoll). Der Topf-Stand eines Jahres = Σ Spenden − Σ Entnahmen.
    Spenden/Entnahmen wirken über `Member.effective_annual_budget`."""
    DONATE = "donate"
    WITHDRAW = "withdraw"
    KIND = [(DONATE, "Spende in den Pool"), (WITHDRAW, "Entnahme aus dem Pool")]

    year = models.PositiveIntegerField("Jahr")
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="pool_entries",
        verbose_name="Mitglied")
    kind = models.CharField("Art", max_length=10, choices=KIND)
    nights = models.PositiveIntegerField("Tage")
    note = models.CharField("Notiz", max_length=200, blank=True)
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Tage-Pool-Buchung"
        verbose_name_plural = "Tage-Pool-Buchungen"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["year", "kind"])]

    def __str__(self) -> str:
        sign = "+" if self.kind == self.DONATE else "−"
        return f"{sign}{self.nights} Tage: {self.member} ({self.year})"


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


class NotificationSetting(models.Model):
    """Betriebs-Einstellung je Benachrichtigungs-Ereignis (ADR 0089): an/aus,
    Empfänger, Frequenz/Tag, PDF-Anhang, Vorlauf. Die **Vorlagen** (Text) stehen im
    Code-Katalog (`booking/notify_catalog.py`); hier nur die im Backend änderbaren
    Betriebs-Parameter. Wird je Ereignis **lazy** mit den Katalog-Defaults angelegt."""
    IMMEDIATE, EVENT, DAILY, WEEKLY, MONTHLY = (
        "immediate", "event", "daily", "weekly", "monthly")
    FREQUENCY = [(IMMEDIATE, "sofort (bei jedem Ereignis)"),
                 (EVENT, "ereignisbezogen (mit Vorlauf)"),
                 (DAILY, "täglich"), (WEEKLY, "wöchentlich"), (MONTHLY, "monatlich")]

    event_key = models.CharField("Ereignis", max_length=60, unique=True)
    enabled = models.BooleanField("Aktiv", default=True)
    recipients = models.CharField(
        "Empfänger (kommagetrennt, leer = Verwaltungs-Adressen)", max_length=400,
        blank=True)
    frequency = models.CharField("Frequenz", max_length=10, choices=FREQUENCY,
                                 default=WEEKLY)
    weekday = models.PositiveSmallIntegerField(
        "Wochentag (0=Mo … 6=So, bei wöchentlich)", default=0)
    day_of_month = models.PositiveSmallIntegerField(
        "Tag im Monat (bei monatlich)", default=1)
    attach_pdf = models.BooleanField("PDF anhängen (wo verfügbar)", default=False)
    lead_days = models.PositiveSmallIntegerField("Vorlauf (Tage)", default=7)
    last_run_on = models.DateField("Zuletzt gelaufen am", null=True, blank=True)

    class Meta:
        verbose_name = "Benachrichtigungs-Einstellung"
        verbose_name_plural = "Benachrichtigungs-Einstellungen"
        ordering = ["event_key"]

    @classmethod
    def for_event(cls, key: str) -> "NotificationSetting":
        """Einstellung zum Ereignis holen/anlegen (Defaults aus dem Katalog)."""
        from .notify_catalog import EVENTS
        obj = cls.objects.filter(event_key=key).first()
        if obj is not None:
            return obj
        d = (EVENTS.get(key) or {}).get("defaults", {})
        return cls.objects.create(
            event_key=key,
            frequency=d.get("frequency", cls.WEEKLY),
            weekday=d.get("weekday", 0),
            day_of_month=d.get("day_of_month", 1),
            attach_pdf=d.get("attach_pdf", False),
            lead_days=d.get("lead_days", 7))

    def recipient_list(self) -> list[str]:
        """Empfänger-Adressen: explizit gesetzte, sonst die Verwaltungs-Adressen."""
        raw = [e.strip() for e in (self.recipients or "").split(",") if e.strip()]
        if raw:
            return raw
        return OpsConfig.get_solo().admin_list()

    def due_today(self, today) -> bool:
        """Ist eine geplante Benachrichtigung heute fällig (Frequenz + Idempotenz)?"""
        if not self.enabled:
            return False
        if self.last_run_on == today:
            return False
        if self.frequency == self.DAILY:
            return True
        if self.frequency == self.WEEKLY:
            return today.weekday() == self.weekday
        if self.frequency == self.MONTHLY:
            return today.day == self.day_of_month
        return False   # immediate/event laufen nicht über den Zeitplan

    def label(self) -> str:
        from .notify_catalog import EVENTS
        return (EVENTS.get(self.event_key) or {}).get("label", self.event_key)

    def __str__(self) -> str:
        return self.label()


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
    nl_learning_enabled = models.BooleanField(
        "NL-Parser lernen lassen", default=False,
        help_text="Opt-in (ADR 0113): pseudonymisiert erfassen, welche Kurz-Eingaben "
                  "der Parser nicht verstand und was die Person danach wählte, um "
                  "Vorschläge (Aliase/Reihung) zur BESTÄTIGUNG anzubieten. Aus = es "
                  "wird nichts gesammelt. Braucht zusätzlich das Env-Geheimnis "
                  "NL_LEARN_SALT.")
    # Kontaktformular-Routing (ADR 0091): welche Kategorie an welche Adresse. Leer =
    # Verwaltungs-Adressen. Idealerweise Rollen-Aliase (bl@… / dev@…).
    contact_email_bl = models.CharField(
        "Kontakt – Buchung/Reinigung/Allgemein", max_length=400, blank=True,
        help_text="Empfänger für Kontakt-Anliegen zu Buchung, Endreinigung, "
                  "allgemeine Fragen. Leer = Verwaltungs-Adressen.")
    contact_email_tech = models.CharField(
        "Kontakt – App-Problem/Bug", max_length=400, blank=True,
        help_text="Empfänger für technische Probleme (Bug/App). Leer = "
                  "Verwaltungs-Adressen.")

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

    def contact_list(self, category: str) -> list[str]:
        """Empfänger fürs Kontaktformular je Kategorie (leer = Verwaltung)."""
        raw = self.contact_email_tech if category == "bug" else self.contact_email_bl
        return self._parse(raw) or self.admin_list()


class TerminalConfig(models.Model):
    """Hofladen-Terminal vor Ort (Singleton, ADR 0053). Das **Token** ist das
    Geräte-Gate: nur ein damit eingerichtetes Gerät darf die Roster (freigeschaltete
    Mitglieder + PIN-Hash) laden und Einkäufe abgeben. Im Backend änderbar – bei
    Geräteverlust **neu erzeugen**, dann ist das alte Token sofort ungültig."""
    enabled = models.BooleanField(
        "Terminal aktiv", default=False,
        help_text="Schaltet den Vor-Ort-Terminal-Modus frei. Aus = Roster/Sync "
                  "verweigert.")
    token = models.CharField(
        "Geräte-Token", max_length=64, blank=True,
        help_text="Langes Geheimnis, das im Terminal-Gerät hinterlegt wird. Bei "
                  "Verlust/Diebstahl neu erzeugen (Aktion im Backend).")
    idle_timeout_seconds = models.PositiveIntegerField(
        "Auto-Abmeldung nach (Sekunden)", default=120,
        help_text="Nach so vielen Sekunden ohne Aktion wird am Terminal automatisch "
                  "abgemeldet.")
    max_pin_attempts = models.PositiveSmallIntegerField(
        "PIN-Sperre nach Fehlversuchen", default=5)

    class Meta:
        verbose_name = "Hofladen-Terminal-Einstellungen"
        verbose_name_plural = "Hofladen-Terminal-Einstellungen"

    def __str__(self) -> str:
        return "Hofladen-Terminal-Einstellungen"

    @classmethod
    def get_solo(cls) -> "TerminalConfig":
        return cls.objects.first() or cls.objects.create()

    @staticmethod
    def new_token() -> str:
        import secrets
        return secrets.token_urlsafe(32)

    def regenerate(self) -> None:
        self.token = self.new_token()
        self.save(update_fields=["token"])


class OutboxEmail(models.Model):
    """Ausgehende E-Mail in der Warteschlange. Das Versenden ist vom Request
    entkoppelt (wichtig für Massenmails): das Kommando `send_outbox` – vom
    Scheduler regelmäßig aufgerufen – arbeitet die offenen Mails ab."""
    to_email = models.EmailField("Empfänger")
    subject = models.CharField("Betreff", max_length=200)
    body = models.TextField("Text")
    html_body = models.TextField("HTML", blank=True)
    reply_to = models.EmailField("Antwort an", blank=True)
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
    """Unterkunfts-Tausch: ein Mitglied möchte mit einem anderen, das im **exakt
    gleichen Zeitraum** in einer anderen Unterkunft ist, das Quartier tauschen
    (ADR 0077). Das Gegenüber kann zustimmen oder ablehnen. **Bei Zustimmung wird
    der Tausch sofort ausgeführt** – beide Buchungen wechseln die Unterkunft (der
    Zeitraum bleibt identisch, daher immer konfliktfrei); beide werden per
    Notification informiert."""
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
    # Bezugsgröße der Winter-/Wochenend-Richtwerte (rein für die Anzeige):
    #  - pro Mitglied: jede Person bekommt den vollen Wert.
    #  - pro vollem Anteil: der Wert gilt für 50 Tage; wer nur einen Teil hält
    #    (Tandem/Trio), bekommt anteilig nach seinem Tage-Budget weniger.
    BASIS_MEMBER = "member"
    BASIS_SHARE = "share"
    GUIDELINE_BASIS = [
        (BASIS_MEMBER, "pro Mitglied (jede Person der volle Wert)"),
        (BASIS_SHARE, "pro vollem Anteil (Tandem/Trio anteilig nach Tagen)"),
    ]

    default_min_nights = models.PositiveIntegerField(
        "Mindestnächte (Standard)", default=3,
        help_text="Gilt, wenn keine Saison-Regel etwas Strengeres vorgibt.",
    )
    min_lead_days = models.PositiveIntegerField(
        "Spontan-Vorausfrist (Tage)", default=7,
        help_text="Spontanbuchungen müssen mindestens so viele Tage vor der "
                  "Anreise erfolgen. Lückenfüllende Buchungen sind ausgenommen. "
                  "0 = keine Frist.",
    )
    allow_gap_fill = models.BooleanField(
        "Lücken unter Mindestnächte füllen", default=True,
        help_text="Füllt eine Buchung eine freie Lücke vollständig aus (schließt "
                  "beidseitig an Belegungen/Zeitraum-Grenzen an), entfällt die "
                  "Mindestnächte-Regel und die Vorausfrist.",
    )
    group_min_persons = models.PositiveIntegerField(
        "Gruppe ab Personen", default=6,
        help_text="Ab dieser Personenzahl gilt eine Buchung als Gruppe – dann "
                  "werden Gruppen-Wohneinheiten (z. B. Stallgebäude) zuerst "
                  "angezeigt. Nur Reihenfolge/Hinweis, keine Sperre.",
    )
    winter_guideline_nights = models.PositiveIntegerField(
        "Richtwert MINDEST-Tage Okt–März (pro vollem Anteil)", default=20,
        help_text="Orientierung (kein Limit): so viele Tage sollten MINDESTENS ins "
                  "Winterhalbjahr Okt–März fallen, damit sich die Buchungen übers "
                  "Jahr verteilen. Gilt pro vollem Anteil (50 Tage); bei Teil-/"
                  "Tandem-Anteilen anteilig weniger. Kein Maximum.",
    )
    max_weekends_per_year = models.PositiveIntegerField(
        "Richtwert HÖCHST-Wochenenden/Jahr", default=9,
        help_text="Orientierung (kein Limit): so viele Wochenenden je Mitglied und "
                  "Jahr sind fair (bei voller Gemeinschaft). Beim Buchen wird ein "
                  "Hinweis angezeigt, wenn man sich diesem Höchstwert nähert.",
    )
    guideline_basis = models.CharField(
        "Richtwert-Berechnung (Winter & Wochenenden)", max_length=8,
        choices=GUIDELINE_BASIS, default=BASIS_SHARE,
        help_text="Bezugsgröße für die BEIDEN Richtwerte oben (Winter-Tage und "
                  "Höchst-Wochenenden). „pro Mitglied“: jede Person bekommt den vollen "
                  "Wert. „pro vollem Anteil“: der Wert gilt für einen vollen Anteil "
                  "(50 Tage); wer nur einen Teil hält (Tandem/Trio), bekommt anteilig "
                  "nach seinem Tage-Budget weniger. Reine Anzeige – kein Limit.",
    )
    max_wishes_per_period = models.PositiveIntegerField(
        "Max. Wünsche je Periode (0 = unbegrenzt)", default=0,
        help_text="Obergrenze für die Anzahl der Wünsche, die ein Mitglied je "
                  "Losungs-Periode eintragen darf. 0 = unbegrenzt (Standard – bewusst, "
                  "damit Rückfall-Wünsche möglich bleiben). Nur setzen, wenn die "
                  "Delegation eine Begrenzung beschließt (ADR 0078).",
    )
    allow_undersized_units = models.BooleanField(
        "Personenzahl außerhalb des Rahmens zulassen", default=True,
        help_text="Erlaubt, eine Unterkunft auch für MEHR oder WENIGER Personen zu "
                  "buchen, als sie ausgelegt ist (z. B. wenn nichts Passendes mehr "
                  "frei ist). Die Buchung wird dann deutlich gekennzeichnet "
                  "(„kleiner als eure Gruppe“ bzw. „größer als nötig“).",
    )
    wish_reminder_lead1 = models.PositiveSmallIntegerField(
        "1. Wunsch-Erinnerung (Tage vor Frist)", default=7,
        help_text="So viele Tage VOR dem Einreiche-Schluss (Losdatum) werden "
                  "Mitglieder erinnert, die noch keinen Wunsch eingereicht haben. "
                  "0 = diese Stufe aus (ADR 0080).",
    )
    wish_reminder_lead2 = models.PositiveSmallIntegerField(
        "2. Wunsch-Erinnerung (Tage vor Frist)", default=2,
        help_text="Zweite, dringlichere Erinnerung so viele Tage vor dem Schluss. "
                  "Sollte kleiner als die erste sein. 0 = diese Stufe aus (ADR 0080).",
    )
    review_days = models.PositiveSmallIntegerField(
        "Entzerrungsphase (Tage vor der Losung)", default=7,
        help_text="Länge der Entzerrungs-/Review-Phase VOR der Losung (ADR 0101): "
                  "Ab „Losdatum − diese Tage“ beginnt die Entzerrungsphase; "
                  "Mitglieder können ihre Wünsche noch anpassen und sehen die "
                  "Nachfrage. Je Periode überschreibbar.",
    )
    er_decision_lock_days = models.PositiveSmallIntegerField(
        "Endreinigung: Frist zum Revidieren (Tage vor Anreise)", default=7,
        help_text="Die Betriebsleitung kann eine Endreinigungs-Entscheidung "
                  "(bestätigt/abgelehnt) bis zu so viele Tage VOR der Anreise noch "
                  "ändern; danach ist sie fest, damit sich das Mitglied darauf "
                  "einstellen kann. 0 = jederzeit änderbar (kein Lock). ADR 0081.",
    )
    short_notice_days = models.PositiveSmallIntegerField(
        "Kurzfrist-Grenze für Storno/Verkürzen (Tage vor Anreise)", default=14,
        help_text="Storniert oder verkürzt ein Mitglied eine Buchung, deren Anreise "
                  "höchstens so viele Tage entfernt ist, VERFALLEN die betroffenen "
                  "Tage – außer ein anderes Mitglied bucht den frei gewordenen "
                  "Zeitraum (ganz/teilweise) neu. Alle Mitglieder werden dann in der "
                  "App informiert (ohne Mail). Bei mehr Vorlauf gibt es die Tage "
                  "normal zurück. ADR 0088.",
    )
    block_min_notice_days = models.PositiveSmallIntegerField(
        "Sperrzeit: Vorlauf für Absprache mit Mitgliedern (Tage)", default=14,
        help_text="Eine Sperrzeit über eine bestehende Buchung ist regulär nur mit "
                  "diesem Mindestvorlauf möglich (damit sich die Mitglieder darauf "
                  "einlassen können). Startet die Sperrung früher, greift der "
                  "**dringende** Workflow (Wasserrohrbruch o. Ä.) mit Umbuchung/"
                  "Ausgleich. ADR 0097.",
    )
    max_compensation_days = models.PositiveSmallIntegerField(
        "Max. Ausgleichs-Tage bei dringender Sperrung", default=2,
        help_text="Kann die Verwaltung bei einer dringenden Sperrung keine passende "
                  "Ersatz-Unterkunft bereitstellen, darf sie dem Mitglied bis zu so "
                  "viele zusätzliche Tage gutschreiben (je nach Schwere). ADR 0097.",
    )
    pool_eligible_remaining = models.PositiveSmallIntegerField(
        "Solidaritäts-Pool: Entnahme erst ab Rest-Budget ≤", default=5,
        help_text="Aus dem Solidaritäts-Pool darf ein Mitglied erst entnehmen, wenn "
                  "sein Jahresbudget bis auf höchstens so viele Tage aufgebraucht ist "
                  "(Bedarfs-Signal). ADR 0064/0099.",
    )
    pool_withdraw_cap = models.PositiveSmallIntegerField(
        "Solidaritäts-Pool: Höchst-Entnahme je Mitglied/Jahr", default=10,
        help_text="Mehr als so viele Tage darf ein Mitglied pro Jahr nicht aus dem "
                  "Pool entnehmen. ADR 0064/0099.",
    )
    pool_withdraw_from_month = models.PositiveSmallIntegerField(
        "Solidaritäts-Pool: Entnahme erst ab Monat (1–12; 0 = ganzjährig)", default=9,
        help_text="Zeit-Riegel gegen „schnell verbrauchen, dann nachladen“: Entnahmen "
                  "sind erst ab diesem Monat möglich (Default 9 = ab September). "
                  "0 = ganzjährig (kein Riegel). ADR 0099.",
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


class Rolle(Group):
    """Nur ein anderer NAME für Djangos Gruppe (ADR 0087): im Backend heißt das
    Konzept „Rolle" (z. B. die Rolle „Verwaltung"), nicht „Gruppe". Reines
    Proxy-Modell – kein Datenumbau, keine Migration nötig; die zugrunde liegende
    `auth.Group` bleibt unverändert."""
    class Meta:
        proxy = True
        verbose_name = "Rolle"
        verbose_name_plural = "Rollen"


class VerwaltungAccess(models.Model):
    """Träger der Verwaltungs-**Capabilities** (ADR 0100). `managed=False` → **keine
    Tabelle**; das Modell existiert nur, um seine `permissions` zu registrieren.
    Diese Rechte bündeln die Rollen-Gruppen (idempotent geseedet über
    `manage.py sync_roles`); die Registry + Durchsetzung liegen in `booking.authz`.
    So lebt Least Privilege in den Permissions, die Ergonomie in den Rollen."""
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("access_buchungen",    "Verwaltung: Buchungen/Reinigung/Sperrzeiten"),
            ("book_for_member",     "Verwaltung: Buchungen für Mitglieder anlegen/ändern"),
            ("export_wishes",       "Verwaltung: Wunsch-Export (Entzerrungsphase)"),
            ("add_wish_for_member", "Verwaltung: Wunsch für Mitglied nachtragen"),
            ("access_mitglieder",   "Verwaltung: Mitglieder freischalten/zuordnen"),
            ("access_quartiere",    "Verwaltung: Quartiere/Sperrzeiten"),
            ("access_rechnungen",   "Verwaltung: Rechnungen/Kontoabgleich"),
            ("access_hofladen",     "Verwaltung: Hofladen-Katalog"),
            ("send_broadcast",      "Verwaltung: Rundnachricht senden"),
        ]


class NlInteraction(models.Model):
    """Pseudonymisiertes Lern-Signal für den NL-Parser (ADR 0113, Batch NL-L1).

    Je Kurz-Eingabe EIN Datensatz: ein **Pseudonym** (HMAC(member_id, NL_LEARN_SALT),
    ohne Geheimnis nicht umkehrbar), die vom Parser **nicht aufgelösten** normalisierten
    Tokens (KEIN Freitext-Satz, kein Klartext an die Person gebunden) und – nach der
    späteren Wahl – das **Ergebnis** (gewähltes Quartier/Startmonat, ob der Vorschlag
    überstimmt wurde). Getrennt von Buchungs-/Identitätsdaten; nur bei aktivem Opt-in
    (`OpsConfig.nl_learning_enabled`); kurze Aufbewahrung (`cleanup_data`). Diese Daten
    speisen den Lerner (NL-L2), der daraus Vorschläge zur BESTÄTIGUNG macht."""
    WISH, BOOKING = "wish", "booking"
    KIND = [(WISH, "Wunsch"), (BOOKING, "Buchung")]

    created_at = models.DateTimeField("Erfasst", auto_now_add=True)
    pseudonym = models.CharField("Pseudonym (HMAC)", max_length=64, db_index=True)
    kind = models.CharField("Art", max_length=8, choices=KIND)
    # Was der Parser NICHT verstand (normalisierte Einzel-Tokens, gedeckelt) + was er vorschlug.
    unresolved = models.JSONField("Nicht aufgelöste Tokens", default=list, blank=True)
    proposed_quarter_id = models.IntegerField("Vorschlag Quartier-ID", null=True, blank=True)
    proposed_month = models.PositiveSmallIntegerField("Vorschlag Monat", null=True, blank=True)
    suggestion_shown = models.BooleanField("Vorschlag angezeigt", default=False)
    # Ergebnis – nach der späteren Wahl angehängt (Korrektur-Signal).
    outcome_at = models.DateTimeField("Ergebnis erfasst", null=True, blank=True)
    chosen_quarter_id = models.IntegerField("Gewählt Quartier-ID", null=True, blank=True)
    chosen_month = models.PositiveSmallIntegerField("Gewählt Monat", null=True, blank=True)
    overridden = models.BooleanField("Vorschlag überstimmt", null=True, blank=True)

    class Meta:
        verbose_name = "NL-Lern-Signal"
        verbose_name_plural = "NL-Lern-Signale"
        indexes = [
            models.Index(fields=["kind", "created_at"]),
            models.Index(fields=["pseudonym", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.created_at:%Y-%m-%d} · {self.pseudonym[:8]}…"
