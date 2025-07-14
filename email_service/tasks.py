"""
Core email tasks for django-q2 async processing.
Contains only the task functions that are called by django-q2.
"""
import logging
from typing import List, Optional

from django.core.mail import EmailMessage, send_mail

from .utils import (get_email_from_address, has_required_email_settings, log_email_attempt, validate_email_data)

logger = logging.getLogger(__name__)


def send_email_task(recipient_list: List[str], subject: str, message: Optional[str] = None,
                    html_message: Optional[str] = None, from_email: Optional[str] = None,
                    attachments: Optional[List] = None) -> bool:
    """
    Core email sending task for django-q2.
    This function should ONLY be called by django-q2 or directly for synchronous sending.

    Args:
        recipient_list (List[str]): List of recipient email addresses
        subject (str): Email subject
        message (str, optional): Plain text message
        html_message (str, optional): HTML message content
        from_email (str, optional): Sender email address
        attachments (List, optional): List of email attachments

    Returns:
        bool: True if email sent successfully, False otherwise

    Raises:
        Exception: Re-raises email sending exceptions for django-q2 error handling
    """
    try:
        # Pre-flight checks
        if not has_required_email_settings():
            logger.error("Email settings not configured")
            log_email_attempt(recipient_list, subject, False, "Email settings not configured")
            return False

        # Validate email data
        is_valid, error_msg = validate_email_data(recipient_list, subject, message, html_message)
        if not is_valid:
            logger.error(f"Invalid email data: {error_msg}")
            log_email_attempt(recipient_list, subject, False, error_msg)
            return False

        # Set sender email
        from_email = from_email or get_email_from_address()

        # Send email based on content type
        if html_message:
            # Use EmailMessage for HTML content and attachments
            email = EmailMessage(
                    subject=subject,
                    body=html_message,
                    from_email=from_email,
                    to=recipient_list
            )
            email.content_subtype = "html"

            # Add attachments if provided
            if attachments:
                for attachment in attachments:
                    if isinstance(attachment, (list, tuple)) and len(attachment) >= 2:
                        # Standard Django attachment format: (filename, content, mimetype)
                        email.attach(*attachment)
                    else:
                        logger.warning(f"Skipping invalid attachment format: {attachment}")

            email.send(fail_silently=False)

        else:
            # Use simple send_mail for plain text
            send_mail(
                    subject=subject,
                    message=message or '',
                    from_email=from_email,
                    recipient_list=recipient_list,
                    fail_silently=False,
            )

        # Log success
        log_email_attempt(recipient_list, subject, True)
        return True

    except Exception as e:
        # Log failure
        error_msg = str(e)
        log_email_attempt(recipient_list, subject, False, error_msg)

        # Re-raise for django-q2 error handling
        logger.error(f"Email task failed: {error_msg}", exc_info=True)
        raise


def send_bulk_email_task(email_data_list: List[dict]) -> dict:
    """
    Send multiple emails in a single task.
    Useful for batch processing to reduce django-q2 task overhead.

    Args:
        email_data_list (List[dict]): List of email data dictionaries
            Each dict should contain: recipient_list, subject, message, html_message, etc.

    Returns:
        dict: Summary of results with success/failure counts
    """
    results = {
        'total': len(email_data_list),
        'success': 0,
        'failed': 0,
        'errors': []
    }

    logger.info(f"Starting bulk email task with {results['total']} emails")

    for i, email_data in enumerate(email_data_list):
        try:
            # Extract email parameters
            recipient_list = email_data.get('recipient_list', [])
            subject = email_data.get('subject', '')
            message = email_data.get('message')
            html_message = email_data.get('html_message')
            from_email = email_data.get('from_email')
            attachments = email_data.get('attachments')

            # Send individual email
            success = send_email_task(
                    recipient_list=recipient_list,
                    subject=subject,
                    message=message,
                    html_message=html_message,
                    from_email=from_email,
                    attachments=attachments
            )

            if success:
                results['success'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f"Email {i + 1}: Failed to send")

        except Exception as e:
            results['failed'] += 1
            error_msg = f"Email {i + 1}: {str(e)}"
            results['errors'].append(error_msg)
            logger.error(f"Bulk email task error: {error_msg}")

    logger.info(f"Bulk email task completed: {results['success']} success, {results['failed']} failed")
    return results


def send_template_email_task(recipient_list: List[str], subject: str, template_path: str,
                             context: dict, from_email: Optional[str] = None,
                             fallback_message: Optional[str] = None) -> bool:
    """
    Send email using a template with fallback to plain text.

    Args:
        recipient_list (List[str]): Recipients
        subject (str): Email subject
        template_path (str): Path to HTML email template
        context (dict): Template context variables
        from_email (str, optional): Sender email
        fallback_message (str, optional): Plain text fallback if template fails

    Returns:
        bool: True if email sent successfully
    """
    try:
        from .utils import render_email_template, create_fallback_message

        # Render HTML template
        html_message = render_email_template(template_path, context)

        # Create fallback message if template rendering failed
        if not html_message and not fallback_message:
            fallback_message = create_fallback_message(subject, context)

        # Send email
        return send_email_task(
                recipient_list=recipient_list,
                subject=subject,
                message=fallback_message,
                html_message=html_message,
                from_email=from_email
        )

    except Exception as e:
        logger.error(f"Template email task failed: {e}", exc_info=True)
        raise


def send_admin_notification_task(subject: str, message: str,
                                 notification_type: str = 'general',
                                 template_path: Optional[str] = None,
                                 context: Optional[dict] = None) -> bool:
    """
    Send notification email to all configured admins.

    Args:
        subject (str): Email subject
        message (str): Plain text message
        notification_type (str): Type of notification for categorization
        template_path (str, optional): HTML template path
        context (dict, optional): Template context

    Returns:
        bool: True if email sent successfully
    """
    try:
        from .utils import get_admin_email_list, render_email_template

        # Get admin emails
        admin_emails = get_admin_email_list()
        if not admin_emails:
            logger.warning("No admin emails configured, cannot send admin notification")
            return False

        # Prepare context for template
        if template_path and context:
            from django.utils import timezone
            template_context = {
                'notification_type': notification_type,
                'timestamp': timezone.now(),
                **context
            }
            html_message = render_email_template(template_path, template_context)
        else:
            html_message = None

        # Send email to admins
        return send_email_task(
                recipient_list=admin_emails,
                subject=f"[ADMIN] {subject}",
                message=message,
                html_message=html_message
        )

    except Exception as e:
        logger.error(f"Admin notification task failed: {e}", exc_info=True)
        raise


def send_password_reset_task(user_id: int, reset_link: str,
                             template_path: str = 'emails/password_reset.html') -> bool:
    """
    Send password reset email task.
    Separated from business logic for pure task execution.

    Args:
        user_id (int): User ID to send reset email to
        reset_link (str): Password reset link
        template_path (str): Email template path

    Returns:
        bool: True if email sent successfully
    """
    try:
        # Import here to avoid circular imports
        from django.contrib.auth import get_user_model
        from .utils import build_email_context

        User = get_user_model()

        # Get user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f"Cannot send password reset: User {user_id} does not exist")
            return False

        # Build email context
        context = build_email_context({
            'user': user,
            'reset_link': reset_link,
        })

        # Create subject
        from django.utils.translation import gettext_lazy as _
        subject = _("Reset Your Password - {site_name}").format(
                site_name=context['site_name_formal']
        )

        # Create fallback message
        fallback_message = _(
                "Hello {name},\n\n"
                "You requested a password reset. Please use the following link:\n"
                "{reset_link}\n\n"
                "If you didn't request this, please ignore this email.\n\n"
                "Best regards,\n{site_name}"
        ).format(
                name=user.get_full_name() or user.username,
                reset_link=reset_link,
                site_name=context['site_name_formal']
        )

        # Send email using template
        return send_template_email_task(
                recipient_list=[user.email],
                subject=subject,
                template_path=template_path,
                context=context,
                fallback_message=fallback_message
        )

    except Exception as e:
        logger.error(f"Password reset task failed for user {user_id}: {e}", exc_info=True)
        raise


def cleanup_failed_email_task(max_age_days: int = 7) -> dict:
    """
    Cleanup task for failed email records (if you're storing them).
    This is an example of how you might handle email cleanup.

    Args:
        max_age_days (int): Maximum age of failed emails to keep

    Returns:
        dict: Cleanup statistics
    """
    try:
        from django.utils import timezone
        from datetime import timedelta

        # This is just an example - you'd implement based on your email logging model
        cutoff_date = timezone.now() - timedelta(days=max_age_days)

        logger.info(f"Email cleanup task started: removing failed emails older than {cutoff_date}")

        # Example cleanup logic - replace with your actual model
        # failed_emails = FailedEmail.objects.filter(created_at__lt=cutoff_date)
        # deleted_count = failed_emails.count()
        # failed_emails.delete()

        deleted_count = 0  # Placeholder

        result = {
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat(),
            'success': True
        }

        logger.info(f"Email cleanup completed: deleted {deleted_count} failed email records")
        return result

    except Exception as e:
        logger.error(f"Email cleanup task failed: {e}", exc_info=True)
        return {
            'deleted_count': 0,
            'error': str(e),
            'success': False
        }
