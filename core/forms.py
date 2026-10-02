"""Day 2 forms + Day 3 pickup/profile forms — server-side validation only."""
import datetime

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from waste.models import EwasteSubmission, PickupRequest


class RegisterForm(UserCreationForm):
    """Username + email + password x2. Password hashing handled by Django."""

    email = forms.EmailField(required=True, help_text='We never share your email.')

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email


class ProfileForm(forms.Form):
    """Optional profile details collected at registration."""

    full_name = forms.CharField(max_length=100, required=False)
    phone = forms.CharField(max_length=20, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=False)
    city = forms.CharField(max_length=100, required=False)


class EwasteSubmissionForm(forms.ModelForm):
    """E-waste declaration — user/status/verification are set server-side.

    Day 7: adds submission_method + bin/pickup/session routing. The bin is
    chosen from real SmartBins (dropdown/QR/map) — never a typed raw PK —
    and resolved to the SmartBin object in clean().
    """

    submission_method = forms.ChoiceField(
        choices=EwasteSubmission.SubmissionMethod.choices,
        initial=EwasteSubmission.SubmissionMethod.SMART_BIN,
        required=False,  # missing (e.g. legacy post) defaults to PICKUP below
        widget=forms.RadioSelect,
    )
    bin_id = forms.CharField(
        max_length=30, required=False,
        help_text='SmartBin ID, e.g. ECO-BIN-007 (pick from list, map or QR).',
    )
    pickup_request = forms.ModelChoiceField(
        queryset=PickupRequest.objects.none(), required=False,
        help_text='Optional: ride along with one of your pickup requests.',
    )
    session_token = forms.CharField(
        max_length=64, required=False, widget=forms.HiddenInput,
    )

    class Meta:
        model = EwasteSubmission
        fields = ('category', 'quantity', 'estimated_weight', 'condition', 'description')
        widgets = {
            'category': forms.Select(attrs={'class': 'input'}),
            'quantity': forms.NumberInput(attrs={'class': 'input', 'min': 1, 'max': 1000}),
            'estimated_weight': forms.NumberInput(
                attrs={'class': 'input', 'min': 0.01, 'max': 10000, 'step': 0.1}
            ),
            'condition': forms.Select(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Pickup choices are ALWAYS scoped to the owner (never all pickups).
        if user is not None and getattr(user, 'is_authenticated', False):
            self.fields['pickup_request'].queryset = PickupRequest.objects.filter(
                user=user
            ).exclude(status=PickupRequest.Status.CANCELLED).order_by('-created_at')
        for name in ('category', 'quantity', 'estimated_weight',
                     'condition', 'description'):
            self.fields[name].widget.attrs.setdefault('class', 'input')
        self.fields['submission_method'].widget.attrs.setdefault('class', 'method-radio')
        self.fields['bin_id'].widget.attrs.setdefault('class', 'input')

    def clean_bin_id(self):
        return (self.cleaned_data.get('bin_id') or '').strip()

    def clean(self):
        cleaned = super().clean()
        # Legacy/partial posts without the method radio fall back to PICKUP.
        method = cleaned.get('submission_method') or EwasteSubmission.SubmissionMethod.PICKUP
        cleaned['submission_method'] = method
        bin_id = (cleaned.get('bin_id') or '').strip()
        if method == EwasteSubmission.SubmissionMethod.SMART_BIN:
            if not bin_id:
                self.add_error('bin_id', 'Choose a SmartBin (list, map or QR scan).')
                return cleaned
            from bins.models import SmartBin
            try:
                cleaned['smart_bin'] = SmartBin.objects.get(bin_id=bin_id)
            except SmartBin.DoesNotExist:
                self.add_error(
                    'bin_id', f'Unknown SmartBin {bin_id!r} — pick one from the map.')
        else:
            cleaned['smart_bin'] = None
        return cleaned

    def clean_quantity(self):
        qty = self.cleaned_data['quantity']
        if qty < 1 or qty > 1000:
            raise forms.ValidationError('Quantity must be between 1 and 1000.')
        return qty

    def clean_estimated_weight(self):
        weight = self.cleaned_data['estimated_weight']
        if weight <= 0 or weight > 10000:
            raise forms.ValidationError('Weight must be between 0.01 and 10000 kg.')
        return weight


class PickupRequestForm(forms.ModelForm):
    """Doorstep pickup request — user and status are set server-side."""

    class Meta:
        model = PickupRequest
        fields = (
            'pickup_address', 'city', 'e_waste_category', 'estimated_weight',
            'preferred_date', 'preferred_time', 'additional_notes',
        )
        widgets = {
            'pickup_address': forms.Textarea(attrs={'class': 'input', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'input'}),
            'e_waste_category': forms.Select(attrs={'class': 'input'}),
            'estimated_weight': forms.NumberInput(
                attrs={'class': 'input', 'min': 0.1, 'max': 10000, 'step': 0.1}
            ),
            'preferred_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'preferred_time': forms.TextInput(attrs={'class': 'input'}),
            'additional_notes': forms.Textarea(attrs={'class': 'input', 'rows': 2}),
        }

    def clean_estimated_weight(self):
        weight = self.cleaned_data['estimated_weight']
        if weight <= 0 or weight > 10000:
            raise forms.ValidationError('Weight must be between 0.1 and 10000 kg.')
        return weight

    def clean_preferred_date(self):
        date = self.cleaned_data['preferred_date']
        if date < datetime.date.today():
            raise forms.ValidationError('Preferred date cannot be in the past.')
        return date
