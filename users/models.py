import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


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
            raise ValidationError(_("Only managers can create user accounts"))

    def is_manager(self):
        return self.user_type == 'manager' or self.is_superuser

    def is_agent(self):
        return self.user_type == 'agent'

    def can_manage_users(self):
        """Check if user can create/manage other users"""
        return self.is_manager()

    def can_see_all_data(self):
        """Check if user can see all system data"""
        return self.is_manager()

    def can_manage_transfers(self):
        """Check if user can validate/execute transfers"""
        return self.is_manager()

    def can_manage_stock(self):
        """Check if user can manage stock"""
        return self.is_manager()

    def can_manage_commissions(self):
        """Check if the user can configure commissions"""
        return self.is_manager()

    def get_user_type_display(self) -> str:
        """
        Get a human-readable display of the user's type.
        """
        # Return the user type label based on the choices defined in USER_TYPES
        # if user.is_superuser, return "Admin" else, "Unknown"
        user_type = dict(self.USER_TYPES).get(self.user_type, "Unknown")
        if self.is_superuser:
            return "Admin"
        return user_type

    def format_user_display_name(self) -> str:
        """Format a user's display name consistently across the app."""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        else:
            return self.username

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
        verbose_name = _("User Activity")
        verbose_name_plural = _("User Activities")

    def __str__(self):
        return f"{self.user.username} - {self.action} at {self.timestamp}"


def log_user_activity(user, action: str, details: Optional[Dict[str, Any]] = None,
                      request=None) -> Optional[UserActivity]:
    try:
        activity_data = {
            'user': user,
            'action': action,
            'details': details or {},
        }

        if request:
            activity_data['ip_address'] = request.META.get('REMOTE_ADDR')

        activity = UserActivity.objects.create(**activity_data)
        logger.debug(f"Logged activity: {user.username} - {action}")
        return activity

    except Exception as e:
        # Log the failure but don't break the main operation
        logger.error(f"Failed to log activity '{action}' for user {user.username}: {e}", exc_info=True)
        return None


def log_user_activity_direct(user, action: str, details: Optional[Dict[str, Any]] = None) -> Optional[UserActivity]:
    """
    Direct logging without request context.
    Used by signals and background tasks where no request is available.

    Args:
        user (User): The user performing the action
        action (str): Action identifier
        details (dict, optional): Additional context data

    Returns:
        UserActivity: The created activity record, or None if creation failed
    """
    try:
        activity = UserActivity.objects.create(
                user=user,
                action=action,
                details=details or {}
        )
        logger.debug(f"Logged direct activity: {user.username} - {action}")
        return activity

    except Exception as e:
        logger.error(f"Failed to log direct activity '{action}' for user {user.username}: {e}", exc_info=True)
        return None


def cleanup_old_activities(days: int = 60) -> int:
    """
    Clean up old user activities to prevent database bloat.

    Args:
        days (int): Age threshold in days

    Returns:
        int: Number of activities deleted
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=days)

        # Delete old activities
        deleted_count, _ = UserActivity.objects.filter(
                timestamp__lt=cutoff_date
        ).delete()

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old user activities (older than {days} days)")

        return deleted_count

    except Exception as e:
        logger.error(f"Failed to cleanup old activities: {e}", exc_info=True)
        return 0
