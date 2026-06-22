"""Formulare."""
from __future__ import annotations

from django import forms

from .models import Member, Wish


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
