"""
Email utility functions.
Contains helper functions for email configuration, validation, and template rendering.
"""
import logging
import os
import re
from typing import Dict, Any, Optional, Tuple
from django.conf import settings
from django.template import loader
from django.template.loader import render_to_string
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def has_required_email_settings():
    """Check if all required email settings are configured and warn if any are missing."""
    from django.conf import settings as s
    required_settings = [
        'EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD'
    ]
    missing_settings = [
        setting_name for setting_name in required_settings if not hasattr(s, setting_name)
    ]

    if missing_settings:
        missing_settings_str = ", ".join(missing_settings)
        logger.warning(f"Warning: The following settings are missing in settings.py: {missing_settings_str}. "
                       "Email functionality will be disabled.")
        return False

    # Check if EMAIL_HOST is not the default value
    if os.environ.get('EMAIL_HOST') == 'smtp.example.com':
        logger.warning(
                "EMAIL_HOST is set to the default value 'smtp.example.com'. "
                "Please update it with your actual SMTP server in the .env file."
        )
        return False
    return True


def validate_email_format(email: str) -> bool:
    """
    Validate email address format using regex.

    Args:
        email (str): Email address to validate

    Returns:
        bool: True if email format is valid
    """
    if not email or not isinstance(email, str):
        return False

    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def validate_recipient_list(recipient_list) -> Tuple[bool, str]:
    """
    Validate a list of email recipients.

    Args:
        recipient_list: List of email addresses or single email

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not recipient_list:
        return False, "Recipient list cannot be empty"

    # Handle single email as string
    if isinstance(recipient_list, str):
        recipient_list = [recipient_list]

    # Check if it's a list
    if not isinstance(recipient_list, (list, tuple)):
        return False, "Recipients must be a list or string"

    # Validate each email
    invalid_emails = []
    for email in recipient_list:
        if not validate_email_format(email):
            invalid_emails.append(email)

    if invalid_emails:
        return False, f"Invalid email addresses: {', '.join(invalid_emails)}"

    return True, ""


def get_site_info() -> Dict[str, str]:
    """
    Get site information for email templates.

    Returns:
        Dict containing site_name and site_name_formal
    """
    site_name = getattr(settings, 'SITE_NAME', '').strip()

    if not site_name:
        # Fallback values
        site_name = "Transfer d'Argent"
        site_name_formal = 'Our Platform'
    else:
        site_name_formal = site_name

    return {
        'site_name': site_name,
        'site_name_formal': site_name_formal,
    }


def render_email_template(template_path: str, context: Dict[str, Any]) -> Optional[str]:
    """
    Render an email template with the given context.

    Args:
        template_path (str): Path to the email template
        context (Dict): Context variables for the template

    Returns:
        str or None: Rendered template content, None if rendering fails
    """
    if not template_path:
        return None

    try:
        return render_to_string(template_path, context)
    except Exception as e:
        logger.warning(f"Could not render email template '{template_path}': {e}")
        return None


def build_email_context(base_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Build a standard email context with site information and common variables.

    Args:
        base_context (Dict, optional): Additional context to merge

    Returns:
        Dict: Complete email context
    """
    context = {
        'support_email': getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
        **get_site_info()
    }

    if base_context:
        context.update(base_context)

    return context


def check_django_q_availability() -> bool:
    """
    Check if django-q2 is available and properly configured.

    Returns:
        bool: True if django-q2 can be used for async tasks
    """
    try:
        from django_q.tasks import async_task
        from django_q.conf import Conf

        # Check if Q cluster is configured
        if not getattr(settings, 'Q_CLUSTER', None):
            logger.debug("Q_CLUSTER not configured")
            return False

        return True

    except ImportError:
        logger.debug("django-q2 not installed")
        return False
    except Exception as e:
        logger.warning(f"django-q2 availability check failed: {e}")
        return False


def should_use_async_email() -> bool:
    """
    Determine if async email sending should be used.

    Returns:
        bool: True if async email should be used
    """
    # Check user preference
    use_async = getattr(settings, 'USE_DJANGO_Q_FOR_EMAILS', False)
    if not use_async:
        return False

    # Check if django-q2 is available
    return check_django_q_availability()


def get_email_from_address() -> str:
    """
    Get the FROM email address for outgoing emails.

    Returns:
        str: Email address to use as sender

    Raises:
        ImproperlyConfigured: If DEFAULT_FROM_EMAIL is not set
    """
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    if not from_email:
        raise ImproperlyConfigured("DEFAULT_FROM_EMAIL setting is required")
    return from_email


def get_admin_email_list() -> list:
    """
    Get list of admin email addresses from Django settings.

    Returns:
        list: List of admin email addresses
    """
    admins = getattr(settings, 'ADMINS', [])
    return [email for name, email in admins if email]


def log_email_attempt(recipient_list, subject: str, success: bool, error_msg: str = None):
    """
    Log email sending attempts for debugging and monitoring.

    Args:
        recipient_list: List of recipients
        subject (str): Email subject
        success (bool): Whether sending was successful
        error_msg (str, optional): Error message if sending failed
    """
    recipient_count = len(recipient_list) if isinstance(recipient_list, (list, tuple)) else 1
    status = "SUCCESS" if success else "FAILED"

    log_msg = f"Email {status}: '{subject}' to {recipient_count} recipients"
    if success:
        logger.info(log_msg)
    else:
        logger.error(f"{log_msg} - Error: {error_msg}")


def validate_email_data(recipient_list, subject: str, message: str = None,
                        html_message: str = None) -> Tuple[bool, str]:
    """
    Validate all required email data before sending.

    Args:
        recipient_list: Email recipients
        subject (str): Email subject
        message (str, optional): Plain text message
        html_message (str, optional): HTML message

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    # Validate recipients
    valid_recipients, error_msg = validate_recipient_list(recipient_list)
    if not valid_recipients:
        return False, error_msg

    # Validate subject
    if not subject or not subject.strip():
        return False, "Email subject is required"

    # Validate that we have some message content
    if not message and not html_message:
        return False, "Either plain text message or HTML message is required"

    return True, ""


def create_fallback_message(subject: str, template_context: Dict[str, Any] = None) -> str:
    """
    Create a fallback plain text message when HTML template rendering fails.

    Args:
        subject (str): Email subject
        template_context (Dict, optional): Template context for extracting info

    Returns:
        str: Plain text fallback message
    """
    site_info = get_site_info()
    message_parts = [
        f"Hello,",
        f"",
        f"You have received this message from {site_info['site_name_formal']}.",
        f"Subject: {subject}",
        f"",
    ]

    # Add user-specific info if available
    if template_context and 'user' in template_context:
        user = template_context['user']
        if hasattr(user, 'get_full_name'):
            name = user.get_full_name() or user.username
            message_parts[0] = f"Hello {name},"

    # Add link if available
    if template_context and 'reset_link' in template_context:
        message_parts.extend([
            f"Please use the following link:",
            f"{template_context['reset_link']}",
            f"",
        ])

    message_parts.extend([
        f"If you have questions, please contact us at {get_email_from_address()}.",
        f"",
        f"Best regards,",
        f"{site_info['site_name_formal']} Team"
    ])

    return "\n".join(message_parts)


def get_email_template_path(template_name: str, base_path: str = 'emails') -> str:
    """
    Build the full path to an email template.

    Args:
        template_name (str): Name of the template file
        base_path (str): Base directory for email templates

    Returns:
        str: Full template path
    """
    if not template_name.endswith('.html'):
        template_name += '.html'

    return f"{base_path}/{template_name}"


def is_development_environment() -> bool:
    """
    Check if we're running in a development environment.

    Returns:
        bool: True if in development
    """
    return getattr(settings, 'DEBUG', False) or 'console' in getattr(settings, 'EMAIL_BACKEND', '').lower()
