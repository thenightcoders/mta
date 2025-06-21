from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()

CURRENCY_CHOICES = [
    ('EUR', 'Euro'),
    ('BIF', 'Franc Burundais'),
    ('USD', 'Dollars'),
]

LOCATION_CHOICES = [
    ('EUROPE', 'Europe'),
    ('BURUNDI', 'Burundi'),
]

MOVEMENT_TYPES = [
    ('IN', 'Entrée'),
    ('OUT', 'Sortie'),
]


class Stock(models.Model):
    """
    Represents a stock of money in a specific currency at a specific location
    """
    name = models.CharField(max_length=100, blank=True, null=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    location = models.CharField(max_length=10, choices=LOCATION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                    fields=['currency', 'location'],
                    name='unique_stock_per_currency_location'
            )
        ]
        ordering = ['currency', 'location']
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"

    def is_europe_stock(self):
        return self.location == 'EUROPE'

    def clean(self):
        """Validation for stock"""
        if self.amount < 0:
            raise ValidationError("Stock amount cannot be negative")

    def __str__(self):
        base = self.location
        if self.name:
            base = self.name
        return f"{base} - {self.amount} {self.currency}"


class StockMovement(models.Model):
    """
    Tracks all stock movements - deposits, withdrawals, and transfers
    """
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='movements')
    type = models.CharField(max_length=10, choices=MOVEMENT_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=250, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    # Optional for transfers from one stock to another
    destination_stock = models.ForeignKey(
            Stock, null=True, blank=True, on_delete=models.SET_NULL,
            related_name='incoming_transfers'
    )
    custom_exchange_rate = models.DecimalField(
            max_digits=10, decimal_places=4, null=True, blank=True
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stock', '-created_at']),
            models.Index(fields=['type', '-created_at']),
            models.Index(fields=['created_by', '-created_at']),
        ]
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"

    def get_stock_transfer_rate(self):
        """Get exchange rate for stock transfers"""
        if not self.destination_stock:
            return None

        if self.stock.currency == self.destination_stock.currency:
            return 1  # No exchange needed

        # Use custom rate if set
        if self.custom_exchange_rate:
            return self.custom_exchange_rate

        # Otherwise, get latest known rate
        rate = ExchangeRate.objects.filter(
                from_currency=self.stock.currency,
                to_currency=self.destination_stock.currency
        ).order_by('-created_at').first()

        if not rate:
            raise ValidationError("Aucun taux de change défini pour cette conversion.")

        return rate.rate

    def clean(self):
        """Validation rules for stock movements"""
        # Check if amount is set and valid
        if self.amount is None:
            raise ValidationError("Amount is required.")

        if self.amount <= 0:
            raise ValidationError("Le montant doit être positif.")

        # Enforce OUT if there's a destination
        if self.destination_stock and self.type != 'OUT':
            raise ValidationError("Les transferts doivent être de type 'OUT'")

        # Check balance only if stock is set (to avoid issues during form validation)
        if self.stock and self.type == 'OUT' and self.amount > self.stock.amount:
            raise ValidationError("Solde insuffisant pour cette transaction")

        if self.destination_stock:
            if self.stock and self.destination_stock == self.stock:
                raise ValidationError("La destination des fonds doit être différente de la source.")

            # Check if exchange rate is available for different currencies
            if self.stock and self.stock.currency != self.destination_stock.currency:
                try:
                    self.get_stock_transfer_rate()
                except ValidationError:
                    if not self.custom_exchange_rate:
                        raise ValidationError("Un taux de change est requis si les devises diffèrent.")

    def save(self, *args, **kwargs):
        """Override save to update stock balances"""
        self.full_clean()  # Run validation

        # Calculate the changes before saving
        if self.type == 'IN':
            stock_change = self.amount
        elif self.type == 'OUT':
            stock_change = -self.amount
        else:
            stock_change = 0

        # Handle destination stock for transfers
        destination_change = 0
        if self.destination_stock:
            rate_value = self.get_stock_transfer_rate()
            destination_change = self.amount * rate_value

        # Update stock balances
        self.stock.amount += stock_change
        self.stock.save()

        if self.destination_stock:
            self.destination_stock.amount += destination_change
            self.destination_stock.save()

        super().save(*args, **kwargs)

    def __str__(self):
        base = f"{self.get_type_display()} de {self.amount} {self.stock.currency}"
        if self.destination_stock:
            base += f" vers {self.destination_stock.location} en {self.destination_stock.currency}"
        return base


class ExchangeRate(models.Model):
    """
    Historical exchange rates between currencies
    """
    from_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    to_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    defined_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['from_currency', 'to_currency', '-created_at']),
        ]
        verbose_name = "Exchange Rate"
        verbose_name_plural = "Exchange Rates"

    def clean(self):
        """Validation for exchange rates"""
        if self.rate <= 0:
            raise ValidationError("Le taux de change doit être positif.")

        if self.from_currency == self.to_currency:
            raise ValidationError("Les devises source et destination doivent être différentes.")

    def __str__(self):
        return f"{self.from_currency} → {self.to_currency}: {self.rate} (le {self.created_at.strftime('%d/%m/%Y')})"
