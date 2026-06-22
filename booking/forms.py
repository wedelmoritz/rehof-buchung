"""Formulare."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Member, Wish


class RegistrationForm(UserCreationForm):
    """Selbstregistrierung: E-Mail + Name + Passwort. Es entsteht nur ein
    Login-Konto – das Buchungs-Profil (Member) und die Tage-Anteile vergibt
    ausschließlich die Verwaltung. Bis dahin sieht der Nutzer nichts."""
    email = forms.EmailField(label="E-Mail", required=True)
    name = forms.CharField(label="Dein Name", max_length=150)

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
    """Einfache IBAN-Prüfung (Format + Mod-97). Leer ist erlaubt."""
    iban = (value or "").replace(" ", "").upper()
    if not iban:
        return ""
    if not (15 <= len(iban) <= 34) or not iban[:2].isalpha() or not iban[2:4].isdigit():
        raise forms.ValidationError("Ungültige IBAN.")
    rearr = iban[4:] + iban[:4]
    digits = "".join(str(int(c, 36)) for c in rearr)
    if int(digits) % 97 != 1:
        raise forms.ValidationError("Ungültige IBAN (Prüfsumme).")
    return iban


class ProfileForm(forms.ModelForm):
    """Selbstpflege der Profil-/Rechnungsdaten durch das Mitglied."""
    class Meta:
        model = Member
        fields = ["legal_name", "street", "zip_code", "city", "iban",
                  "membership_number", "email_opt_in"]

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
