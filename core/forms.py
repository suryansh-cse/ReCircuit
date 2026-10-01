"""Day 2 forms — server-side validation only (never trust client alone)."""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from waste.models import EwasteSubmission


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
    """E-waste declaration — user and status are set server-side."""

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
