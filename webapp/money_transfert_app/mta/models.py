from django.db import models
from django.core.exceptions import ValidationError
from phonenumber_field.modelfields import PhoneNumberField
# from money_transfert_app import settings
from django.db.models import Q

from django.contrib.auth import get_user_model

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

User = get_user_model()

class Stock(models.Model):
    name = models.CharField(max_length=100, blank=True, null=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    location = models.CharField(max_length=10, choices=LOCATION_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['currency', 'location'], name='unique_stock_per_currency_location')
        ]

    def is_europe_stock(self):
        return self.location == 'EUROPE'

    def __str__(self):
        base = self.location
        if self.name:
            base = self.name
        return base
    
class StockMovement(models.Model):
    """
    Money can be transfered from one stock to another.
    Money can be injected
    Money can be withdrawn

    """
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='movements')
    type = models.CharField(max_length=10, choices=MOVEMENT_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=250, blank=True, null=True)
    created_at = models.DateTimeField(auto_now=True)
    # create_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    # Optional for transfers from one stock to another
    destination_stock = models.ForeignKey(Stock, null=True, blank=True, on_delete=models.SET_NULL, related_name='incoming_transfers')
    custom_exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Currency mismatch requires either custom or known rate
    def get_stock_transfer_rate(self): 
        if self.stock.currency == self.destination_stock.currency:
            return 1  # No exchange needed
    
        # Use custom rate if set
        if self.custom_exchange_rate:
            rate_value = self.custom_exchange_rate

        # Otherwise, get latest known rate
        else:
            rate = ExchangeRate.objects.filter(
                from_currency=self.stock.currency,
                to_currency=self.destination_stock.currency
            ).order_by('-created_at').first()

            if not rate:
                raise ValidationError("Aucun taux de change défini pour cette conversion.")
            rate_value = rate.rate
        return rate_value

                
                    
    def validation(self):
        if self.amount <= 0:
            raise ValidationError("Le montant doit être positif.")
        
        # Enforce OUT if there's a destination
        if self.destination_stock and self.type != 'OUT':
            raise ValidationError("Opération non autorisée")
                
        if self.type == 'OUT' and self.amount > self.stock.amount:
            raise ValidationError("Solde Insuffisant pour cette transaction")
        if self.destination_stock:
            if self.destination_stock == self.stock:
                raise ValidationError("La destination des fonds doit être différente de la source.")
            if self.stock.currency != self.destination_stock.currency and not self.get_stock_transfer_rate():
                raise ValidationError("Un taux de change est requis si les devises diffèrent.")
        if self.destination_stock:
            self.get_stock_transfer_rate()
                    
    def save(self, *args, **kwargs):
        # is_new = self._state.adding
        self.validation()
        
        # update the stock balance if a deposit/withdrawal or a tranfer is operated
        
        if self.type == 'IN':
            self.stock.amount += self.amount
        elif self.type == 'OUT':
            self.stock.amount -= self.amount
        if self.destination_stock:
            rate_value = self.get_stock_transfer_rate()
            incoming_amount = self.amount * rate_value
            # Explicitly update destination stock balance here
            self.destination_stock.amount += incoming_amount
            self.destination_stock.save()
                

        self.stock.save()

        super().save(*args, **kwargs)

    def __str__(self):
        base = f"{self.get_type_display()} de {self.amount} {self.stock.currency}"
        if self.destination_stock:
            base += f"vers {self.destination_stock.location} en {self.destination_stock.get_currency_display()}"
        return base
        

    
class ExchangeRate(models.Model):
    from_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    to_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    defined_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = ('from_currency', 'to_currency', 'created_at')

    def __str__(self):
        return f"{self.from_currency} → {self.to_currency}: {self.rate}"

WITHDRAWAL_METHOD = [
    ('CASH', 'Cash'),
    ('LUMICASH', 'Lumicash'),
    ('ECOCASH', 'Ecocash'),
]

TRANSFER_STATUS = [
    ('PENDING', 'En attente'),
    ('VALIDATED', 'Validé'),
    ('COMPLETED', 'Complété'),
    ('CANCELED', 'Annulé'),
]

class Transfer(models.Model):
    beneficiary_name = models.CharField(max_length=100)
    beneficiary_phone = models.CharField(max_length=20)
    method = models.CharField(max_length=50, choices=WITHDRAWAL_METHOD)
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='transfers_made', null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    sent_currency =  models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    received_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    comment = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=TRANSFER_STATUS, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    validated_by = models.ForeignKey(
    User,
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name='validated_transfers'
    )

    executed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='executed_transfers'
    )

    def __str__(self):
        return f"{self.beneficiary_name} - {self.amount} ({self.status}) opéré par {self.agent}"
    
class CommissionConfig(models.Model):
    manager = models.ForeignKey(User, on_delete=models.CASCADE)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)  # % on total
    agent_share = models.DecimalField(max_digits=5, decimal_places=2)  # % of the commission
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)
    def clean(self):
        if self.agent_share < 0 or self.agent_share > 100:
            raise ValidationError("Part agent invalide.")
        if self.commission_rate < 0 or self.commission_rate > 100:
            raise ValidationError("Commission totale invalide.")
    
    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(agent_share__gte=0) & Q(agent_share__lte=100), name='valid_agent_share'),
            models.UniqueConstraint(fields=['manager', 'min_amount', 'max_amount', 'currency', 'active'], name='unique_config_range')
        ]

    def __str__(self):
        return f"{self.commission_rate}% de commission pour [{self.min_amount} - {self.max_amount}] {self.currency} => (Agent: {self.agent_share}%)"
    
class CommissionDistribution(models.Model):
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE)
    agent = models.ForeignKey(User, models.CASCADE)
    config_used = models.ForeignKey(CommissionConfig, on_delete=models.SET_NULL, null=True)
    total_commission = models.DecimalField(max_digits=12, decimal_places=2)
    declaring_agent_amount = models.DecimalField(max_digits=12, decimal_places=2)
    manager_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)