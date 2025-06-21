from django import forms
from .models import Transfer, CommissionConfig, TRANSFER_STATUS


class TransferForm(forms.ModelForm):
    """Form for creating transfers"""

    class Meta:
        model = Transfer
        fields = ['beneficiary_name', 'beneficiary_phone', 'method', 'amount',
                  'sent_currency', 'received_currency', 'comment']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

        # Make some fields required
        self.fields['beneficiary_name'].required = True
        self.fields['beneficiary_phone'].required = True
        self.fields['amount'].required = True

        # Add placeholders
        self.fields['beneficiary_name'].widget.attrs['placeholder'] = 'Beneficiary Full Name'
        self.fields['beneficiary_phone'].widget.attrs['placeholder'] = '+257XXXXXXXX'
        self.fields['amount'].widget.attrs['placeholder'] = '0.00'
        self.fields['comment'].widget.attrs['placeholder'] = 'Optional comments...'
        self.fields['comment'].widget.attrs['rows'] = 3


class TransferValidationForm(forms.Form):
    """Form for validating/rejecting transfers"""
    action = forms.ChoiceField(
            choices=[('validate', 'Validate'), ('reject', 'Reject')],
            widget=forms.RadioSelect,
            required=True
    )
    comment = forms.CharField(
            widget=forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional comment...'
            }),
            required=False
    )


class CommissionConfigForm(forms.ModelForm):
    """Form for creating commission configurations"""

    class Meta:
        model = CommissionConfig
        fields = ['currency', 'min_amount', 'max_amount', 'commission_rate', 'agent_share', 'active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'

        # Add placeholders and help text
        self.fields['min_amount'].widget.attrs['placeholder'] = '0.00'
        self.fields['max_amount'].widget.attrs['placeholder'] = '1000.00'
        self.fields['commission_rate'].widget.attrs['placeholder'] = '6.00'
        self.fields['agent_share'].widget.attrs['placeholder'] = '50.00'

        # Add step for decimal fields
        self.fields['min_amount'].widget.attrs['step'] = '0.01'
        self.fields['max_amount'].widget.attrs['step'] = '0.01'
        self.fields['commission_rate'].widget.attrs['step'] = '0.01'
        self.fields['agent_share'].widget.attrs['step'] = '0.01'


class TransferFilterForm(forms.Form):
    """Form for filtering transfers"""
    status = forms.ChoiceField(
            choices=[('', 'All Statuses')] + TRANSFER_STATUS,
            required=False,
            widget=forms.Select(attrs={'class': 'form-select'})
    )

    agent = forms.CharField(
            required=False,
            widget=forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Agent username...'
            })
    )

    date_from = forms.DateField(
            required=False,
            widget=forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            })
    )

    date_to = forms.DateField(
            required=False,
            widget=forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            })
    )
