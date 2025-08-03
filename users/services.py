import logging
import secrets
from typing import Any, Dict, Optional

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from email_service.services import (notify_admin_of_user_action, send_password_setup_email,
                                    send_user_notification_email)
from .models import UserActivity
from .utils import format_user_display_name, validate_user_permissions

User = get_user_model()
logger = logging.getLogger(__name__)


def get_manager_dashboard_data(user: User) -> Dict[str, Any]:
    """
    Get dashboard data for managers and superusers.

    Args:
        user: The requesting user

    Returns:
        dict: Dashboard context data

    Raises:
        PermissionError: If user doesn't have manager permissions
    """
    if not (user.is_superuser or user.is_manager()):
        raise PermissionError("Access denied to manager dashboard")

    # Import here to avoid circular imports
    try:
        from transfers.models import Transfer, CommissionDistribution
        from stock.models import Stock
    except ImportError:
        Transfer = None
        CommissionDistribution = None
        Stock = None

    # User stats based on permissions
    if user.is_superuser:
        total_agents = User.objects.filter(user_type='agent', is_active_user=True).count()
        total_managers = User.objects.filter(user_type='manager', is_active_user=True).count()
        recent_activities = UserActivity.objects.select_related('user').order_by('-timestamp')[:10]
    else:
        total_agents = User.objects.filter(
                user_type='agent', is_active_user=True, is_superuser=False
        ).count()
        total_managers = User.objects.filter(
                user_type='manager', is_active_user=True, is_superuser=False
        ).count()
        recent_activities = UserActivity.objects.filter(
                user__is_superuser=False
        ).select_related('user').order_by('-timestamp')[:10]

    context: Dict[str, Any] = {
        'total_agents': total_agents,
        'total_managers': total_managers,
        'recent_activities': recent_activities,
        'name': format_user_display_name(user)
    }

    # Transfer data
    if Transfer:
        context.update({
            'pending_transfers': Transfer.objects.filter(status='PENDING').count(),
            'validated_transfers': Transfer.objects.filter(status='VALIDATED').count(),
            'completed_transfers': Transfer.objects.filter(status='COMPLETED').count(),
            'recent_transfers': Transfer.objects.select_related('agent').order_by('-created_at')[:5],
        })

    # Stock data
    if Stock:
        context['stocks'] = Stock.objects.all()

    # Commission data
    if CommissionDistribution:
        from django.db.models import Sum
        total_commissions = CommissionDistribution.objects.aggregate(
                total_paid=Sum('total_commission'),
                total_to_agents=Sum('declaring_agent_amount'),
                total_to_managers=Sum('manager_amount')
        )
        recent_commissions = CommissionDistribution.objects.select_related(
                'transfer', 'agent', 'config_used'
        ).order_by('-created_at')[:5]

        context.update({
            'total_commissions': total_commissions,
            'recent_commissions': recent_commissions,
        })

    return context


def get_agent_dashboard_data(user: User) -> Dict[str, Any]:
    """
    Get dashboard data for agents.

    Args:
        user: The requesting user

    Returns:
        dict: Dashboard context data

    Raises:
        PermissionError: If user is not an agent
    """
    if not user.is_agent():
        raise PermissionError("Access denied to agent dashboard")

    try:
        from transfers.models import Transfer, CommissionDistribution
    except ImportError:
        Transfer = None
        CommissionDistribution = None

    # Basic activity data
    my_activities = UserActivity.objects.filter(user=user).order_by('-timestamp')[:10]

    context = {
        'my_activities': my_activities,
    }

    # Transfer data
    if Transfer:
        from django.db.models import Count, Q

        my_transfers = Transfer.objects.filter(agent=user).order_by('-created_at')[:10]
        my_transfer_stats = Transfer.objects.filter(agent=user).aggregate(
                pending=Count('id', filter=Q(status='PENDING')),
                validated=Count('id', filter=Q(status='VALIDATED')),
                completed=Count('id', filter=Q(status='COMPLETED')),
                total=Count('id')
        )

        context.update({
            'my_transfers': my_transfers,
            'my_transfer_stats': my_transfer_stats,
        })

    # Commission data
    if CommissionDistribution:
        from django.db.models import Sum

        my_commissions = CommissionDistribution.objects.filter(agent=user).select_related('transfer', 'config_used')
        total_commission_earned = my_commissions.aggregate(
                total=Sum('declaring_agent_amount')
        )['total'] or 0

        recent_commissions = my_commissions.order_by('-created_at')[:5]

        context.update({
            'total_commission_earned': total_commission_earned,
            'recent_commissions': recent_commissions,
        })

    return context


class UserCreationService:
    """
    Service for creating new users with proper validation and security.
    Handles password generation, validation, and atomic creation.
    """

    def __init__(self, creator):
        """
        Initialize service with the user who is creating the new user.

        Args:
            creator (User): The user performing the creation (must have permissions)
        """
        self.creator = creator

    @transaction.atomic
    def create_user(self, cleaned_data: Dict[str, Any], base_url: Optional[str] = None) -> User:
        """
        Create a new user with secure temporary password.

        Args:
            cleaned_data (dict): Validated form data
            base_url (str, optional): Base URL for email links

        Returns:
            User: The created user instance

        Raises:
            ValidationError: If user data doesn't validate
            PermissionError: If creator doesn't have permission
        """
        # Verify creator has permission to create users
        if not self.creator.can_manage_users():
            raise PermissionError(f"User {self.creator.username} cannot create users")

        # Validate that creator can create this user type
        user_type = cleaned_data.get('user_type')
        if user_type == 'manager' and not self.creator.is_superuser:
            raise PermissionError("Only superusers can create manager accounts")

        # Create user instance but don't save yet
        user = User(**cleaned_data)
        user.created_by = self.creator

        # Generate secure temporary password
        temp_password = self._generate_secure_password()
        user.set_password(temp_password)

        # Validate before saving
        user.full_clean()
        user.save()

        logger.info(f"User {user.username} ({user.user_type}) created successfully by {self.creator.username}")

        # Send password setup email if base_url provided
        if base_url:
            try:
                email_sent = send_password_setup_email(user.id, base_url)
                if not email_sent:
                    logger.warning(f"Password setup email failed for user {user.username}")
            except Exception as e:
                logger.error(f"Password setup email error for user {user.username}: {e}")

        # Notify admins of user creation
        try:
            notify_admin_of_user_action(
                    user_id=self.creator.id,
                    action='user_created',
                    details={
                        'created_user': user.username,
                        'user_type': user.user_type,
                        'email': user.email
                    }
            )
        except Exception as e:
            logger.error(f"Admin notification failed for user creation: {e}")

        return user

    def _generate_secure_password(self) -> str:
        """
        Generate a cryptographically secure temporary password.

        Returns:
            str: Secure random password
        """
        return secrets.token_urlsafe(12)


class UserUpdateService:
    """
    Service for updating existing users.
    Handles permissions and audit logging.
    """

    def __init__(self, updater):
        """
        Initialize service with the user performing the update.

        Args:
            updater (User): The user performing the update
        """
        self.updater = updater

    @transaction.atomic
    def update_user(self, user: User, cleaned_data: Dict[str, Any]) -> User:
        """
        Update an existing user with new data.

        Args:
            user (User): The user to update
            cleaned_data (dict): Validated form data

        Returns:
            User: The updated user instance

        Raises:
            PermissionError: If updater doesn't have permission
            ValidationError: If update data doesn't validate
        """
        # Check permissions
        validate_user_permissions(self.updater, user, 'update')

        # Track what's changing for audit purposes
        changed_fields = []
        old_values = {}

        for field, value in cleaned_data.items():
            if hasattr(user, field):
                old_value = getattr(user, field)
                if old_value != value:
                    changed_fields.append(field)
                    old_values[field] = old_value
                    setattr(user, field, value)

        if changed_fields:
            user.full_clean()
            user.save()

            logger.info(f"User {user.username} updated by {self.updater.username}, "
                        f"changed fields: {', '.join(changed_fields)}")

            # Send notification to user if profile was updated
            if any(field in ['first_name', 'last_name', 'email'] for field in changed_fields):
                try:
                    send_user_notification_email(user.id, 'profile_updated', {
                        'changed_fields': changed_fields,
                        'updated_by': self.updater.username
                    })
                except Exception as e:
                    logger.error(f"Profile update notification failed: {e}")

            # Notify admins of sensitive changes
            sensitive_fields = ['user_type', 'email', 'is_active_user']
            if any(field in sensitive_fields for field in changed_fields):
                try:
                    notify_admin_of_user_action(
                            user_id=self.updater.id,
                            action='user_updated',
                            details={
                                'target_user': user.username,
                                'changed_fields': changed_fields,
                                'old_values': old_values
                            }
                    )
                except Exception as e:
                    logger.error(f"Admin notification failed for user update: {e}")
        else:
            logger.info(f"User {user.username} update attempted by {self.updater.username} "
                        f"but no fields changed")

        return user

    def toggle_user_status(self, user: User) -> bool:
        """
        Toggle a user's active status.

        Args:
            user (User): The user whose status to toggle

        Returns:
            bool: New active status

        Raises:
            PermissionError: If updater doesn't have permission or tries to deactivate self
        """
        # Check permissions
        validate_user_permissions(self.updater, user, 'toggle_status')

        old_status = user.is_active_user
        user.is_active_user = not user.is_active_user
        user.save()

        status_text = 'activated' if user.is_active_user else 'deactivated'
        logger.info(f"User {user.username} {status_text} by {self.updater.username}")

        # Send notification to user
        try:
            notification_type = 'account_activated' if user.is_active_user else 'account_deactivated'
            send_user_notification_email(user.id, notification_type, {
                'changed_by': self.updater.username,
                'previous_status': 'active' if old_status else 'inactive'
            })
        except Exception as e:
            logger.error(f"User status notification failed: {e}")

        # Notify admins
        try:
            notify_admin_of_user_action(
                    user_id=self.updater.id,
                    action='user_status_changed',
                    details={
                        'target_user': user.username,
                        'new_status': 'active' if user.is_active_user else 'inactive',
                        'previous_status': 'active' if old_status else 'inactive'
                    }
            )
        except Exception as e:
            logger.error(f"Admin notification failed for status change: {e}")

        return user.is_active_user

    def delete_user(self, user: User) -> str:
        """
        Delete a user (with proper audit logging).

        Args:
            user (User): The user to delete

        Returns:
            str: Username of deleted user

        Raises:
            PermissionError: If deleter doesn't have permission
        """
        # Check permissions
        validate_user_permissions(self.updater, user, 'delete')

        username = user.username
        user_type = user.user_type
        user_email = user.email

        # Log before deletion
        logger.warning(f"User {username} ({user_type}) being deleted by {self.updater.username}")

        # Notify admins before deletion
        try:
            notify_admin_of_user_action(
                    user_id=self.updater.id,
                    action='user_deleted',
                    details={
                        'deleted_user': username,
                        'user_type': user_type,
                        'email': user_email
                    }
            )
        except Exception as e:
            logger.error(f"Admin notification failed for user deletion: {e}")

        # For financial apps, consider soft delete instead of hard delete
        # user.is_active_user = False
        # user.deleted_at = timezone.now()
        # user.deleted_by = self.updater
        # user.save()

        # Hard delete (be careful in production)
        with transaction.atomic():
            user.delete()

        logger.warning(f"User {username} ({user_type}) deleted by {self.updater.username}")
        return username


class PasswordResetService:
    """
    Service for handling password reset functionality.
    Used for new user setup and password recovery.
    """

    @staticmethod
    def generate_reset_token(user: User) -> tuple:
        """
        Generate a password reset token for a user.

        Args:
            user (User): The user to generate token for

        Returns:
            tuple: (token, uid) for password reset
        """
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        return token, uid

    @staticmethod
    def build_reset_link(request, token: str, uid: str) -> str:
        """
        Build a complete password reset URL.

        Args:
            request (HttpRequest): Current request for building absolute URI
            token (str): Reset token
            uid (str): Encoded user ID

        Returns:
            str: Complete reset URL
        """
        return request.build_absolute_uri(
                reverse('setup_password', kwargs={'uidb64': uid, 'token': token})
        )

    @staticmethod
    def validate_reset_token(uidb64: str, token: str) -> Optional[User]:
        """
        Validate a password reset token and return the user.

        Args:
            uidb64 (str): Base64 encoded user ID
            token (str): Reset token

        Returns:
            User or None: The user if token is valid, None otherwise
        """
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)

            if default_token_generator.check_token(user, token):
                return user
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            pass

        return None


class UserProfileService:
    """
    Service for handling user profile operations.
    """

    def __init__(self, user: User):
        """
        Initialize service with the user.

        Args:
            user (User): The user whose profile is being managed
        """
        self.user = user

    @transaction.atomic
    def update_profile(self, profile_data: Dict[str, Any], requesting_user: User = None) -> User:
        """
        Update user's own profile or allow managers to update profiles.

        Args:
            profile_data (dict): Profile data to update
            requesting_user (User, optional): User making the request (if different from profile owner)

        Returns:
            User: Updated user instance

        Raises:
            PermissionError: If requesting user doesn't have permission
        """
        # Determine who is making the update
        updater = requesting_user or self.user

        # Check permissions
        if updater != self.user and not updater.can_manage_users():
            raise PermissionError("Only managers can update other users' profiles")

        # Track changes
        changed_fields = []

        # Basic fields all users can update
        basic_fields = ['phone', 'location']
        for field in basic_fields:
            if field in profile_data:
                value = profile_data[field].strip() if profile_data[field] else ''
                if getattr(self.user, field) != value:
                    changed_fields.append(field)
                    setattr(self.user, field, value)

        # Additional fields only managers/superusers can update
        if updater.is_manager():
            manager_fields = ['first_name', 'last_name', 'email']
            for field in manager_fields:
                if field in profile_data:
                    value = profile_data[field].strip() if profile_data[field] else ''
                    if getattr(self.user, field) != value:
                        changed_fields.append(field)
                        setattr(self.user, field, value)

        # Save if there are changes
        if changed_fields:
            # Only validate the fields we're actually updating, not the entire model
            self.user.full_clean(exclude=[field for field in ['user_type'] if field not in changed_fields])
            self.user.save(update_fields=changed_fields)

            logger.info(f"Profile updated for {self.user.username} by {updater.username}, "
                        f"changed fields: {', '.join(changed_fields)}")

            # Send notification if email was changed
            if 'email' in changed_fields:
                try:
                    send_user_notification_email(self.user.id, 'profile_updated', {
                        'changed_fields': changed_fields,
                        'updated_by': updater.username,
                        'email_changed': True
                    })
                except Exception as e:
                    logger.error(f"Profile update notification failed: {e}")

        return self.user


class UserSearchService:
    """
    Service for searching and filtering users.
    """

    def __init__(self, requesting_user: User):
        """
        Initialize service with the requesting user.

        Args:
            requesting_user (User): User performing the search
        """
        self.requesting_user = requesting_user

    def search_users(self, query: str = '', user_type: str = '',
                     active_only: bool = True, limit: int = 50) -> Dict[str, Any]:
        """
        Search users with filters.

        Args:
            query (str): Search query for username, email, name
            user_type (str): Filter by user type
            active_only (bool): Include only active users
            limit (int): Maximum results to return

        Returns:
            dict: Search results with users and metadata
        """
        from .utils import get_filtered_users
        from django.db.models import Q

        # Start with permission-filtered queryset
        queryset = get_filtered_users(self.requesting_user)

        # Apply filters
        if user_type:
            queryset = queryset.filter(user_type=user_type)

        if active_only:
            queryset = queryset.filter(is_active_user=True)

        # Apply search query
        if query:
            queryset = queryset.filter(
                    Q(username__icontains=query) |
                    Q(email__icontains=query) |
                    Q(first_name__icontains=query) |
                    Q(last_name__icontains=query)
            )

        # Get total count before limiting
        total_count = queryset.count()

        # Apply limit and get results
        users = queryset[:limit]

        return {
            'users': users,
            'total_count': total_count,
            'showing_count': len(users),
            'has_more': total_count > limit,
            'query': query,
            'filters': {
                'user_type': user_type,
                'active_only': active_only
            }
        }

    def get_user_suggestions(self, partial_query: str, limit: int = 10) -> list:
        """
        Get user suggestions for autocomplete.

        Args:
            partial_query (str): Partial search query
            limit (int): Maximum suggestions to return

        Returns:
            list: List of user suggestions
        """
        from .utils import get_filtered_users
        from django.db.models import Q

        if len(partial_query) < 2:
            return []

        queryset = get_filtered_users(self.requesting_user).filter(
                is_active_user=True
        ).filter(
                Q(username__icontains=partial_query) |
                Q(first_name__icontains=partial_query) |
                Q(last_name__icontains=partial_query)
        )[:limit]

        suggestions = []
        for user in queryset:
            suggestions.append({
                'id': user.id,
                'username': user.username,
                'display_name': f"{user.get_full_name()} ({user.username})" if user.get_full_name() else user.username,
                'user_type': user.user_type,
                'email': user.email
            })

        return suggestions
