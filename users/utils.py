import logging

from django.db.models import QuerySet

from .models import User

logger = logging.getLogger(__name__)


def get_filtered_users(requesting_user) -> QuerySet:
    """
    Get users filtered based on requesting user's permissions.

    Args:
        requesting_user (User): The user requesting the user list

    Returns:
        QuerySet: Filtered user queryset
    """
    if not requesting_user.can_manage_users():
        # Return empty queryset if user can't manage users
        return User.objects.none()

    if requesting_user.is_superuser:
        # Superusers see all users
        return User.objects.all().order_by('user_type', 'username')
    else:
        # Regular managers don't see superusers
        return User.objects.filter(is_superuser=False).order_by('user_type', 'username')


def validate_user_permissions(requesting_user, target_user, action: str) -> bool:
    """
    Validate if requesting user can perform an action on target user.

    Args:
        requesting_user (User): User trying to perform the action
        target_user (User): User being acted upon
        action (str): Action being performed ('update', 'delete', 'toggle_status')

    Returns:
        bool: True if action is allowed

    Raises:
        PermissionError: If action is not allowed with specific reason
    """
    # Check basic management permission
    if not requesting_user.can_manage_users():
        raise PermissionError(f"User {requesting_user.username} cannot manage users")

    # Prevent non-superusers from acting on superusers
    if target_user.is_superuser and not requesting_user.is_superuser:
        raise PermissionError("Only superusers can manage other superusers")

    # Prevent users from acting on themselves for certain actions
    if target_user == requesting_user and action in ['delete', 'toggle_status']:
        action_verb = 'delete' if action == 'delete' else 'deactivate'
        raise PermissionError(f"Cannot {action_verb} your own account")

    return True


def get_client_ip(request) -> str:
    """
    Get the real client IP address from request.
    Handles proxy headers and load balancers.

    Args:
        request (HttpRequest): Django request object

    Returns:
        str: Client IP address
    """
    # Check for IP in common proxy headers
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Take the first IP in the chain (original client)
        ip = x_forwarded_for.split(',')[0].strip()
        return ip

    # Check other common headers
    x_real_ip = request.META.get('HTTP_X_REAL_IP')
    if x_real_ip:
        return x_real_ip.strip()

    # Check Cloudflare header
    cf_connecting_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf_connecting_ip:
        return cf_connecting_ip.strip()

    # Fall back to REMOTE_ADDR
    return request.META.get('REMOTE_ADDR', 'unknown')


def format_user_display_name(user) -> str:
    """
    Format a user's display name consistently across the app.

    Args:
        user (User): User instance

    Returns:
        str: Formatted display name
    """
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.last_name:
        return user.last_name
    else:
        return user.username
