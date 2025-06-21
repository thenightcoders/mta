from django import forms
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm
from .models import User


class LoginForm(forms.Form):
    """Simple login form"""
    username = forms.CharField(
            max_length=150,
            widget=forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username',
                'autofocus': True
            })
    )
    password = forms.CharField(
            widget=forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Password'
            })
    )


class UserCreationForm(BaseUserCreationForm):
    """Form for creating new users"""

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'user_type',
                  'phone', 'location', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

        # Make some fields required
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True

        # Add placeholders
        self.fields['username'].widget.attrs['placeholder'] = 'Username'
        self.fields['first_name'].widget.attrs['placeholder'] = 'First Name'
        self.fields['last_name'].widget.attrs['placeholder'] = 'Last Name'
        self.fields['email'].widget.attrs['placeholder'] = 'Email'
        self.fields['phone'].widget.attrs['placeholder'] = 'Phone Number'
        self.fields['location'].widget.attrs['placeholder'] = 'City/Region'


class UserUpdateForm(forms.ModelForm):
    """Form for updating existing users"""

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'user_type', 'phone', 'location')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

        # Make some fields required
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
