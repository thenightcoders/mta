from django import forms
from .models import Stock, StockMovement, ExchangeRate, MOVEMENT_TYPES


class StockForm(forms.ModelForm):
    """Form for creating stocks"""

    class Meta:
        model = Stock
        fields = ['name', 'currency', 'location', 'amount']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

        # Make some fields required
        self.fields['currency'].required = True
        self.fields['location'].required = True
        self.fields['amount'].required = True

        # Add placeholders
        self.fields['name'].widget.attrs['placeholder'] = 'Optional stock name'
        self.fields['amount'].widget.attrs['placeholder'] = '0.00'
        self.fields['amount'].widget.attrs['step'] = '0.01'
        self.fields['amount'].widget.attrs['min'] = '0'


class StockMovementForm(forms.ModelForm):
    """Form for creating stock movements"""

    class Meta:
        model = StockMovement
        fields = ['type', 'amount', 'reason', 'destination_stock', 'custom_exchange_rate']

    def __init__(self, *args, **kwargs):
        self.stock = kwargs.pop('stock', None)
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

        # Make some fields required
        self.fields['type'].required = True
        self.fields['amount'].required = True

        # Add placeholders
        self.fields['amount'].widget.attrs['placeholder'] = '0.00'
        self.fields['amount'].widget.attrs['step'] = '0.01'
        self.fields['amount'].widget.attrs['min'] = '0.01'
        self.fields['reason'].widget.attrs['placeholder'] = 'Optional reason for this movement'
        self.fields['reason'].widget.attrs['rows'] = 3
        self.fields['custom_exchange_rate'].widget.attrs['placeholder'] = 'Only for currency transfers'
        self.fields['custom_exchange_rate'].widget.attrs['step'] = '0.0001'

        # Filter destination stock to exclude current stock and same currency
        if self.stock:
            self.fields['destination_stock'].queryset = Stock.objects.exclude(id=self.stock.id)

            # Add help text about current balance
            self.fields['amount'].help_text = f'Current balance: {self.stock.amount} {self.stock.currency}'

    def _post_clean(self):
        """Override to skip model validation during form validation"""
        # Skip calling the parent's _post_clean to avoid model validation issues
        # We'll validate manually in our clean() method
        pass

    def clean(self):
        cleaned_data = super().clean()
        movement_type = cleaned_data.get('type')
        destination_stock = cleaned_data.get('destination_stock')
        amount = cleaned_data.get('amount')

        # Validate amount is positive
        if amount and amount <= 0:
            raise forms.ValidationError("Amount must be positive.")

        # If there's a destination, ensure it's an OUT movement
        if destination_stock and movement_type != 'OUT':
            raise forms.ValidationError("Transfers to another stock must be of type 'OUT'")

        # Validate destination stock is different from source
        if destination_stock and self.stock and destination_stock == self.stock:
            raise forms.ValidationError("Destination stock must be different from source stock.")

        # Check if there's enough balance for OUT movements
        if self.stock and movement_type == 'OUT' and amount:
            if amount > self.stock.amount:
                raise forms.ValidationError(
                        f"Insufficient balance. Current balance: {self.stock.amount} {self.stock.currency}, "
                        f"requested: {amount} {self.stock.currency}"
                )

        # Check exchange rate requirements for different currencies
        if (self.stock and destination_stock and
                self.stock.currency != destination_stock.currency and
                not cleaned_data.get('custom_exchange_rate')):

            # Check if there's an available exchange rate
            from .models import ExchangeRate
            rate_exists = ExchangeRate.objects.filter(
                    from_currency=self.stock.currency,
                    to_currency=destination_stock.currency
            ).exists()

            if not rate_exists:
                raise forms.ValidationError(
                        f"No exchange rate found for {self.stock.currency} → {destination_stock.currency}. "
                        "Please provide a custom exchange rate."
                )

    def clean_amount(self):
        """Clean and validate amount field"""
        amount = self.cleaned_data.get('amount')
        if amount is None:
            raise forms.ValidationError("Amount is required.")
        if amount <= 0:
            raise forms.ValidationError("Amount must be positive.")
        return amount


class ExchangeRateForm(forms.ModelForm):
    """Form for creating exchange rates"""

    class Meta:
        model = ExchangeRate
        fields = ['from_currency', 'to_currency', 'rate']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

        # Make all fields required
        for field in self.fields.values():
            field.required = True

        # Add placeholders
        self.fields['rate'].widget.attrs['placeholder'] = '0.0000'
        self.fields['rate'].widget.attrs['step'] = '0.0001'
        self.fields['rate'].widget.attrs['min'] = '0.0001'

    def clean(self):
        cleaned_data = super().clean()
        from_currency = cleaned_data.get('from_currency')
        to_currency = cleaned_data.get('to_currency')

        if from_currency == to_currency:
            raise forms.ValidationError("From and to currencies must be different")

        return cleaned_data

    def clean_amount(self):
        """Clean and validate amount field"""
        amount = self.cleaned_data.get('amount')
        if amount is None:
            raise forms.ValidationError("Amount is required.")
        if amount <= 0:
            raise forms.ValidationError("Amount must be positive.")
        return amount


class StockFilterForm(forms.Form):
    """Form for filtering stock movements"""
    stock = forms.ModelChoiceField(
            queryset=Stock.objects.all(),
            required=False,
            empty_label="All Stocks",
            widget=forms.Select(attrs={'class': 'form-select'})
    )

    type = forms.ChoiceField(
            choices=[('', 'All Types')] + MOVEMENT_TYPES,
            required=False,
            widget=forms.Select(attrs={'class': 'form-select'})
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

class MoneyDepositForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ['stock', 'amount', 'reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('amount') and cleaned_data['amount'] <= 0:
            self.add_error('amount', "Le montant doit être supérieur à zéro.")