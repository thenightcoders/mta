from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError


class User(AbstractUser):
    """
    Custom user model extending Django's AbstractUser
    """
    USER_TYPES = [
        ('agent', 'Agent'),
        ('manager', 'Manager'),
    ]

    user_type = models.CharField(max_length=10, choices=USER_TYPES)
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=100, blank=True, help_text="City/Region for future extensions")
    is_active_user = models.BooleanField(default=True, help_text="Business-level active status")
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='created_users')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """Validation rules for user creation"""
        super().clean()

        # Only managers can create users or superuser
        if self.created_by and not (self.created_by.user_type == 'manager' or self.created_by.is_superuser):
            raise ValidationError("Only managers can create user accounts")

    def is_manager(self):
        return self.user_type == 'manager'

    def is_agent(self):
        return self.user_type == 'agent'

    def can_manage_users(self):
        """Check if user can create/manage other users"""
        return self.is_manager() or self.is_superuser

    def can_see_all_data(self):
        """Check if user can see all system data"""
        return self.is_manager() or self.is_superuser

    def can_manage_transfers(self):
        """Check if user can validate/execute transfers"""
        return self.is_manager() or self.is_superuser

    def can_manage_stock(self):
        """Check if user can manage stock"""
        return self.is_manager() or self.is_superuser

    def can_manage_commissions(self):
        """Check if user can configure commissions"""
        return self.is_manager() or self.is_superuser

    def __str__(self):
        return f"{self.username} ({self.get_user_type_display()})"


class UserActivity(models.Model):
    """
    Track user activities for audit purposes
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=100)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]
        verbose_name = "User Activity"
        verbose_name_plural = "User Activities"

    def __str__(self):
        return f"{self.user.username} - {self.action} at {self.timestamp}"


def log_user_activity(user, action, details=None, request=None):
    """Helper function to log user activities"""
    activity_data = {
        'user': user,
        'action': action,
        'details': details or {},
    }

    if request:
        activity_data['ip_address'] = request.META.get('REMOTE_ADDR')

    UserActivity.objects.create(**activity_data)
