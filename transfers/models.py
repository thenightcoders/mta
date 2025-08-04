import random

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

User = get_user_model()

CURRENCY_CHOICES = [
    ('EUR', 'Euro'),
    ('BIF', 'Franc Burundais'),
    ('USD', 'Dollars'),
]

WITHDRAWAL_METHOD = [
    ('CASH', 'Cash'),
    ('LUMICASH', 'Lumicash'),
    ('ECOCASH', 'Ecocash'),
]

TRANSFER_STATUS = [
    ('DRAFT', 'Brouillon'),
    ('PENDING', 'En attente'),
    ('VALIDATED', 'Validé'),
    ('COMPLETED', 'Complété'),
    ('CANCELED', 'Annulé'),
]


def _generate_reference_id():
    """Generate unique reference ID in format NNNN-AAAA (numbers-letters)"""
    numbers = '23456789'  # Exclude 0,1 for clarity
    letters = 'ABCDEFGHJKLMNPQRSTUVWXYZ'  # Exclude I,O for clarity

    max_attempts = 100  # Safety net to avoid infinite loops
    attempts = 0

    while attempts < max_attempts:
        # 4 numbers + dash + 4 letters = 2M9L-XK7P format
        num_part = ''.join(random.choices(numbers, k=4))
        letter_part = ''.join(random.choices(letters, k=4))
        ref_id = f"{num_part}-{letter_part}"

        # Check uniqueness
        if not Transfer.objects.filter(reference_id=ref_id).exists():
            return ref_id

        attempts += 1

    # If we somehow can't generate a unique ID, raise an exception
    raise ValidationError("Unable to generate unique reference ID after 100 attempts")


class Transfer(models.Model):
    """
    Core transfer model representing money transfers from France/Belgium to Burundi
    """
    reference_id = models.CharField(max_length=9, unique=True, editable=False, verbose_name="Référence")
    beneficiary_name = models.CharField(max_length=100, verbose_name="Nom du bénéficiaire")
    beneficiary_phone = models.CharField(max_length=20, verbose_name="Téléphone du bénéficiaire")
    method = models.CharField(max_length=50, choices=WITHDRAWAL_METHOD, verbose_name="Méthode de retrait")
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='transfers_made', null=True,
                              verbose_name="Agent")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant")
    sent_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, verbose_name="Devise envoyée")
    received_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, verbose_name="Devise reçue")
    comment = models.TextField(blank=True, null=True, verbose_name="Commentaire")
    status = models.CharField(max_length=10, choices=TRANSFER_STATUS, default='DRAFT',
                              verbose_name="Statut")  # Changed default
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    # Validation fields
    validated_by = models.ForeignKey(
            User,
            null=True,
            blank=True,
            on_delete=models.SET_NULL,
            related_name='validated_transfers',
            verbose_name="Validé par"
    )
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Validé le")
    validation_comment = models.TextField(blank=True, null=True, verbose_name="Commentaire de validation")

    # Execution fields
    executed_by = models.ForeignKey(
            User,
            null=True,
            blank=True,
            on_delete=models.SET_NULL,
            related_name='executed_transfers',
            verbose_name="Exécuté par"
    )
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name="Exécuté le")
    execution_comment = models.TextField(blank=True, null=True, verbose_name="Commentaire d'exécution")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reference_id']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['agent', '-created_at']),
            models.Index(fields=['validated_by', '-created_at']),
        ]
        verbose_name = "Transfer"
        verbose_name_plural = "Transfers"

    def save(self, *args, **kwargs):
        if not self.reference_id:
            self.reference_id = _generate_reference_id()
        super().save(*args, **kwargs)

    def clean(self):
        """Validation rules for transfers"""
        if self.amount <= 0:
            raise ValidationError("Le montant doit être positif.")

        # Business rule validations
        if self.beneficiary_phone and not self.beneficiary_phone.startswith('+'):
            raise ValidationError(
                    _("Le numéro de téléphone doit commencer par +(indicatif téléphonique international: 257, 32, 33, etc."))

    def can_be_validated_by(self, user):
        """Check if the user can validate this transfer"""
        return user.is_manager() and self.status == 'PENDING'

    def can_be_executed_by(self, user):
        """Check if the user can execute this transfer"""
        return user.is_manager() and self.status == 'VALIDATED'

    def can_be_promoted_by(self, user):
        """Check if the user can promote transfer from DRAFT to PENDING"""
        # Agents can promote their own drafts, managers can promote any drafts
        if self.status != 'DRAFT':
            return False

        if user.is_manager():
            return True

        return self.agent == user

    def has_commission_config_available(self):
        """Check if commission config exists for this transfer"""
        return CommissionConfig.objects.filter(
                currency=self.sent_currency,
                min_amount__lte=self.amount,
                max_amount__gte=self.amount,
                active=True
        ).exists()

    def promote_to_pending(self, promoted_by=None):
        """Promote transfer from DRAFT to PENDING if commission config available"""
        if self.status != 'DRAFT':
            raise ValidationError(f"Cannot promote transfer with status {self.status}")

        if not self.has_commission_config_available():
            raise ValidationError(_("Aucune configration de commission dispo pour ce transfert"))

        # Get the commission config for this transfer
        commission_config = CommissionConfig.objects.filter(
                currency=self.sent_currency,
                min_amount__lte=self.amount,
                max_amount__gte=self.amount,
                active=True
        ).first()

        if not commission_config:
            raise ValidationError(_("Aucune configration de commission dispo pour ce transfert"))

        # Promote to PENDING
        self.status = 'PENDING'

        # Set the manager who will validate this transfer (based on commission config)
        # This ensures the commission calculation will work correctly later
        if not promoted_by and commission_config:
            # For auto-promotion, we need to set which manager this transfer will be assigned to
            # Use the manager who created the commission config
            pass  # Don't set validated_by yet, that happens during actual validation

        self.save()

        # IMPORTANT: Create commission distribution immediately when promoting to PENDING
        # This ensures auto-promoted transfers have commissions like manually created ones
        self._create_commission_distribution(commission_config)

    def _create_commission_distribution(self, commission_config):
        """
        Private method to create commission distribution for this transfer.
        Called during promotion to 'PENDING' to ensure commissions are set up.
        """
        # Avoid creating duplicate commissions
        if hasattr(self, 'commission') and self.commission:
            return

        # Calculate commission using the same logic as validation
        commission_data = CommissionDistribution.calculate_commission(self, commission_config)

        if commission_data:
            CommissionDistribution.objects.create(
                    transfer=self,
                    agent=self.agent,
                    config_used=commission_config,
                    **commission_data
            )

    def get_commission_rate(self):
        """Get the applicable commission rate for this transfer"""
        if self.status in ['DRAFT', 'PENDING']:
            return None

        commission = getattr(self, 'commission', None)
        if commission and commission.config_used:
            return commission.config_used.commission_amount  # Now it's amount, not rate
        return None

    def get_commission_amount(self):
        """Get the total commission amount for this transfer"""
        commission = getattr(self, 'commission', None)
        if commission:
            return commission.total_commission
        return None

    def __str__(self):
        return f"{self.reference_id} - {self.beneficiary_name} - {self.amount} {self.sent_currency} ({self.get_status_display()})"


class CommissionConfig(models.Model):
    """
    Commission configuration by managers for different amount ranges
    """
    manager = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Manager")
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant minimum")
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant maximum")
    commission_amount = models.DecimalField(max_digits=12, decimal_places=4,
                                            verbose_name="Montant de commission")  # Fixed amount in currency
    agent_share = models.DecimalField(max_digits=5, decimal_places=2,
                                      verbose_name="Part agent (%)")  # % of the commission
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, verbose_name="Devise")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    active = models.BooleanField(default=True, verbose_name="Actif")

    class Meta:
        constraints = [
            models.CheckConstraint(
                    check=Q(agent_share__gte=0) & Q(agent_share__lte=100),
                    name='valid_agent_share'
            ),
            models.CheckConstraint(
                    check=Q(commission_amount__gte=0.01),  # Minimum 0.01 commission
                    name='valid_commission_amount'
            ),
            models.CheckConstraint(
                    check=Q(min_amount__lte=models.F('max_amount')),
                    name='valid_amount_range'
            ),
            models.UniqueConstraint(
                    fields=['manager', 'min_amount', 'max_amount', 'currency'],
                    condition=Q(active=True),
                    name='unique_active_config_range'
            )
        ]
        ordering = ['currency', 'min_amount']
        verbose_name = "Configuration de Commission"
        verbose_name_plural = "Configurations de Commission"

    def clean(self):
        """Validation rules for commission config"""
        if self.agent_share < 0 or self.agent_share > 100:
            raise ValidationError("Part agent doit être entre 0 et 100%.")

        if self.commission_amount < 0.01:
            raise ValidationError("Le montant de commission doit être d'au moins 0.01")

        if self.min_amount > self.max_amount:
            raise ValidationError("Le montant minimum ne peut pas être supérieur au maximum.")

        if self.min_amount < 0:
            raise ValidationError("Le montant minimum ne peut pas être négatif.")

    @property
    def manager_share(self):
        """Calculate manager share percentage"""
        return 100 - self.agent_share

    def applies_to_transfer(self, transfer):
        """Check if this config applies to a transfer"""
        return (
                self.active and
                self.currency == transfer.sent_currency and
                self.min_amount <= transfer.amount <= self.max_amount
        )

    def __str__(self):
        return f"{self.commission_amount} {self.currency} pour [{self.min_amount}-{self.max_amount}] {self.currency} (Agent: {self.agent_share}%)"


class CommissionDistribution(models.Model):
    """
    Track commission distribution for each transfer
    """
    transfer = models.OneToOneField(Transfer, on_delete=models.CASCADE, related_name='commission',
                                    verbose_name="Transfer")
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commission_earnings', verbose_name="Agent")
    config_used = models.ForeignKey(CommissionConfig, on_delete=models.SET_NULL, null=True,
                                    verbose_name="Configuration utilisée")

    total_commission = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Commission totale")
    declaring_agent_amount = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Montant agent")
    manager_amount = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Montant manager")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['agent', '-created_at']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['transfer']),
        ]
        verbose_name = "Distribution de Commission"
        verbose_name_plural = "Distributions de Commission"

    def clean(self):
        """Validation for commission distribution"""
        if self.total_commission < 0:
            raise ValidationError("La commission totale ne peut pas être négative.")

        if self.declaring_agent_amount < 0:
            raise ValidationError("Le montant agent ne peut pas être négatif.")

        if self.manager_amount < 0:
            raise ValidationError("Le montant manager ne peut pas être négatif.")

        # Verify that agent + manager amounts equal total (within rounding tolerance)
        calculated_total = self.declaring_agent_amount + self.manager_amount
        if abs(calculated_total - self.total_commission) > 0.0001:  # Tighter tolerance for 4 decimals
            raise ValidationError(
                    f"La somme des parts ({calculated_total}) ne correspond pas au total ({self.total_commission})."
            )

    @classmethod
    def calculate_commission(cls, transfer, commission_config):
        """Calculate commission distribution for a transfer"""
        if not commission_config:
            return None

        # Use fixed commission amount (not percentage)
        total_commission = commission_config.commission_amount
        agent_amount = (total_commission * commission_config.agent_share) / 100 if not (
            transfer.agent.is_manager()) else 0
        manager_amount = total_commission - agent_amount

        return {
            'total_commission': round(total_commission, 4),
            'declaring_agent_amount': round(agent_amount, 4),
            'manager_amount': round(manager_amount, 4),
        }

    def save(self, *args, **kwargs):
        """Override save to run validation"""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Commission Transfer {self.transfer.reference_id} - Agent: {self.declaring_agent_amount}, Manager: {self.manager_amount}"
