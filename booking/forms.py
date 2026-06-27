"""Formulare."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from . import validation as V
from .models import Member, Wish


def _check(error: str | None) -> None:
    """Hebt eine Plausibilitäts-Prüfung (Fehlertext|None) in eine ValidationError."""
    if error:
        raise forms.ValidationError(error)


class RegistrationForm(UserCreationForm):
    """Selbstregistrierung: E-Mail + Name + Passwort. Es entsteht nur ein
    Login-Konto – das Buchungs-Profil (Member) und die Tage-Anteile vergibt
    ausschließlich die Verwaltung. Bis dahin sieht der Nutzer nichts."""
    email = forms.EmailField(label="E-Mail", required=True)
    # max_length passt zu User.first_name (30), wohin der Name gespeichert wird.
    name = forms.CharField(label="Dein Name", max_length=30)

    class Meta:
        model = User
        fields = ("email",)

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists() or \
                User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(
                "Mit dieser E-Mail gibt es bereits ein Konto.")
        return email

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        _check(V.name_error(name, field="Name"))
        return name

    def save(self, commit=True):
        user = super().save(commit=False)
        # Benutzername = E-Mail (Anmeldung wahlweise per E-Mail oder Benutzername)
        user.username = self.cleaned_data["email"]
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["name"]
        if commit:
            user.save()
        return user


def validate_iban(value: str) -> str:
    """IBAN-Prüfung (Format + Länge + Mod-97); liefert die normalisierte IBAN.
    Leer ist erlaubt. Dünne Django-Hülle um die reine Logik in ``validation``."""
    _check(V.iban_error(value, required=False))
    return V.normalize_iban(value)


class ProfileForm(forms.ModelForm):
    """Selbstpflege der Profil-/Rechnungsdaten durch das Mitglied. Alle Felder sind
    optional – wird eines ausgefüllt, muss es grundlegend plausibel sein."""
    class Meta:
        model = Member
        fields = ["legal_name", "street", "zip_code", "city", "iban",
                  "membership_number", "email_opt_in"]

    def clean_legal_name(self):
        v = (self.cleaned_data.get("legal_name") or "").strip()
        if v:
            _check(V.name_error(v, field="Name", max_len=160))
        return v

    def clean_street(self):
        v = (self.cleaned_data.get("street") or "").strip()
        _check(V.street_error(v, required=False))
        return v

    def clean_zip_code(self):
        v = (self.cleaned_data.get("zip_code") or "").strip()
        _check(V.plz_error(v, required=False))
        return v

    def clean_city(self):
        v = (self.cleaned_data.get("city") or "").strip()
        _check(V.city_error(v, required=False))
        return v

    def clean_membership_number(self):
        v = (self.cleaned_data.get("membership_number") or "").strip()
        _check(V.membership_number_error(v))
        return v

    def clean_iban(self):
        return validate_iban(self.cleaned_data.get("iban", ""))


class WishForm(forms.ModelForm):
    class Meta:
        model = Wish
        # priority wird vom Service automatisch vergeben (ans Ende der Liste),
        # darf also NICHT Pflichtfeld des Formulars sein.
        fields = ["quarter", "start", "end"]
        widgets = {
            "start": forms.DateInput(attrs={"type": "date"}),
            "end": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start"), cleaned.get("end")
        if start and end and end <= start:
            raise forms.ValidationError("Abreise muss nach der Anreise liegen.")
        return cleaned


class TransferForm(forms.Form):
    """Tage an ein anderes Mitglied übertragen."""
    to_member = forms.ModelChoiceField(
        queryset=Member.objects.none(), label="An Mitglied",
    )
    nights = forms.IntegerField(min_value=1, label="Anzahl Tage")
    note = forms.CharField(required=False, max_length=200, label="Notiz")

    def __init__(self, *args, exclude_member=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Member.objects.filter(is_external=False)
        if exclude_member is not None:
            qs = qs.exclude(id=exclude_member.id)
        self.fields["to_member"].queryset = qs.order_by("display_name")

    def clean_note(self):
        # Freitext: Steuerzeichen entfernen, Länge begrenzen (Ausgabe escapt Django).
        return V.strip_controls(self.cleaned_data.get("note", ""), max_len=200)
