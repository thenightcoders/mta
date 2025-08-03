import logging
from typing import Any, Dict, List, Optional

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .tasks import (send_admin_notification_task, send_template_email_task)
from .utils import (build_email_context, get_email_template_path, has_required_email_settings, should_use_async_email)

logger = logging.getLogger(__name__)

# Check django-q2 availability once at module load
try:
    from django_q.tasks import async_task

    DJANGO_Q_AVAILABLE = True
except ImportError:
    async_task = None
    DJANGO_Q_AVAILABLE = False


def send_password_setup_email(user_id: int, base_url: str) -> bool:
    """
    Send a password setup email to a new user.
    This is the main function that other apps will call.

    Args:
        user_id (int): ID of the user to send email to
        base_url (str): Base URL for building the reset link

    Returns:
        bool: True if email was sent/queued successfully
    """
    try:
        if not has_required_email_settings():
            logger.warning(f"Email not configured, cannot send setup email to user {user_id}")
            return False

        # Import here to avoid circular imports
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Get user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f"Cannot send password setup email: User {user_id} does not exist")
            return False

        # Generate reset token and link
        from users.services import PasswordResetService
        token, uid = PasswordResetService.generate_reset_token(user)
        reset_link = f"{base_url.rstrip('/')}/setup-password/{uid}/{token}/"

        # Build email context
        context = build_email_context({
            'user': user,
            'reset_link': reset_link,
        })

        # Create subject
        subject = _("Set Your Password - {site_name}").format(
                site_name=context['site_name_formal']
        )

        # Template path
        template_path = get_email_template_path('password_setup')

        # Create fallback message
        fallback_message = _(
                "Hello {name},\n\n"
                "Welcome to {site_name}! Please set your password using the link below:\n"
                "{reset_link}\n\n"
                "This link will expire in 24 hours for security reasons.\n\n"
                "If you have any questions, contact us at {support_email}.\n\n"
                "Best regards,\n{site_name} Team"
        ).format(
                name=user.get_full_name() or user.username,
                site_name=context['site_name_formal'],
                reset_link=reset_link,
                support_email=context['support_email']
        )

        # Send email (async if available, sync otherwise)
        if should_use_async_email():
            async_task(
                    'email.tasks.send_template_email_task',
                    recipient_list=[user.email],
                    subject=subject,
                    template_path=template_path,
                    context=context,
                    fallback_message=fallback_message
            )
            logger.info(f"Password setup email queued for user {user.username} ({user.email})")
        else:
            success = send_template_email_task(
                    recipient_list=[user.email],
                    subject=subject,
                    template_path=template_path,
                    context=context,
                    fallback_message=fallback_message
            )
            if success:
                logger.info(f"Password setup email sent to user {user.username} ({user.email})")
            else:
                logger.error(f"Password setup email failed for user {user.username}")
                return False

        return True

    except Exception as e:
        logger.error(f"Password setup email service failed for user {user_id}: {e}", exc_info=True)
        return False


def send_user_notification_email(user_id: int, notification_type: str,
                                 context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Send various notification emails to users.

    Args:
        user_id (int): ID of the user to notify
        notification_type (str): Type of notification
        context (dict, optional): Additional context for the email

    Returns:
        bool: True if email was sent/queued successfully
    """
    try:
        if not has_required_email_settings():
            logger.warning(f"Email not configured, cannot send notification to user {user_id}")
            return False

        # Import here to avoid circular imports
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Get user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f"Cannot send notification: User {user_id} does not exist")
            return False

        # Build email context
        email_context = build_email_context({
            'user': user,
            'notification_type': notification_type,
            'timestamp': timezone.now(),
        })
        if context:
            email_context.update(context)

        # Define notification configurations
        notification_configs = {
            'account_activated': {
                'subject_key': 'account_activated_subject',
                'template': 'account_activated',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Your account has been activated! You can now log in to {site_name}.\n\n"
                        "If you have any questions, contact us at {support_email}.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },
            'account_deactivated': {
                'subject_key': 'account_deactivated_subject',
                'template': 'account_deactivated',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Your account has been deactivated. If you believe this is an error, "
                        "please contact us at {support_email}.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },
            'profile_updated': {
                'subject_key': 'profile_updated_subject',
                'template': 'profile_updated',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Your profile has been updated successfully.\n\n"
                        "If you didn't make these changes, please contact us immediately at {support_email}.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },
            'password_changed': {
                'subject_key': 'password_changed_subject',
                'template': 'password_changed',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Your password has been changed successfully.\n\n"
                        "If you didn't make this change, please contact us immediately at {support_email}.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },
            'transfer_status_change': {
                'subject_key': 'transfer_status_subject',
                'template': 'transfer_status_change',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Your transfer status has been updated.\n\n"
                        "Transfer Details:\n"
                        "Reference: {transfer_reference}\n"
                        "Status: {transfer_status}\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },
            'draft_transfer_created': {
                'subject_key': 'draft_transfer_subject',
                'template': 'draft_transfer_notification',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "A new draft transfer requires your attention:\n\n"
                        "Reference: {transfer_reference}\n"
                        "Amount: {transfer_amount} {transfer_currency}\n"
                        "Beneficiary: {beneficiary_name}\n"
                        "Agent: {agent_name}\n"
                        "Created: {created_at}\n\n"
                        "No commission configuration matches this amount ({missing_range}). "
                        "Please configure appropriate commissions to enable automatic processing.\n\n"
                        "Log in to the platform to configure commissions.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },

            'transfers_auto_promoted': {
                'subject_key': 'auto_promotion_subject',
                'template': 'auto_promotion_notification',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Great news! {promoted_count} of your draft transfers have been automatically "
                        "promoted to 'Pending' thanks to a new commission configuration.\n\n"
                        "Configuration: {config_currency} [{config_range}] - Commission: {commission_amount}\n"
                        "Configured by: {manager_name}\n\n"
                        "Your transfers are now pending validation by a manager.\n\n"
                        "Log in to see the updated status.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            },

            'transfer_manually_promoted': {
                'subject_key': 'manual_promotion_subject',
                'template': 'manual_promotion_notification',
                'fallback_message': _(
                        "Hello {name},\n\n"
                        "Your draft transfer has been manually promoted to 'Pending':\n\n"
                        "Reference: {transfer_reference}\n"
                        "Amount: {transfer_amount} {transfer_currency}\n"
                        "Beneficiary: {beneficiary_name}\n"
                        "Promoted by: {promoted_by_name} ({promoted_by_role})\n\n"
                        "Your transfer is now pending validation.\n\n"
                        "Best regards,\n{site_name} Team"
                )
            }
        }

        if notification_type not in notification_configs:
            logger.error(f"Unknown notification type: {notification_type}")
            return False

        config = notification_configs[notification_type]

        # Create subject based on notification type
        subject_templates = {
            'account_activated_subject': _("Account Activated - {site_name}"),
            'account_deactivated_subject': _("Account Deactivated - {site_name}"),
            'profile_updated_subject': _("Profile Updated - {site_name}"),
            'password_changed_subject': _("Password Changed - {site_name}"),
            'transfer_status_subject': _("Transfer Update - {site_name}"),
        }

        subject = subject_templates[config['subject_key']].format(
                site_name=email_context['site_name_formal']
        )

        # Get the template path
        template_path = get_email_template_path(config['template'])

        # Create a fallback message
        fallback_message = config['fallback_message'].format(
                name=user.get_full_name() or user.username,
                site_name=email_context['site_name_formal'],
                support_email=email_context['support_email'],
                **email_context
        )

        # Send email
        if should_use_async_email():
            async_task(
                    'email.tasks.send_template_email_task',
                    recipient_list=[user.email],
                    subject=subject,
                    template_path=template_path,
                    context=email_context,
                    fallback_message=fallback_message
            )
            logger.info(f"Notification email ({notification_type}) queued for user {user.username}")
        else:
            success = send_template_email_task(
                    recipient_list=[user.email],
                    subject=subject,
                    template_path=template_path,
                    context=email_context,
                    fallback_message=fallback_message
            )
            if success:
                logger.info(f"Notification email ({notification_type}) sent to user {user.username}")
            else:
                logger.error(f"Notification email ({notification_type}) failed for user {user.username}")
                return False

        return True

    except Exception as e:
        logger.error(f"User notification email service failed for user {user_id}: {e}", exc_info=True)
        return False


def send_admin_notification(subject: str, message: str, notification_type: str = 'general',
                            context: Optional[Dict[str, Any]] = None,
                            user_id: Optional[int] = None) -> bool:
    """
    Send a notification email to admins about important system events.
    """
    try:
        if not has_required_email_settings():
            logger.warning("Email not configured, cannot send admin notification")
            return False

        # Build context
        notification_context = build_email_context({
            'message': message,
            'notification_type': notification_type,
            'timestamp': timezone.now(),
        })

        # Add user info if provided
        if user_id:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(id=user_id)
                notification_context['related_user'] = user
                notification_context['user_info'] = {
                    'username': user.username,
                    'email': user.email,
                    'user_type': getattr(user, 'user_type', 'unknown'),
                    'full_name': user.get_full_name() or 'N/A'
                }
            except Exception as e:
                logger.warning(f"Could not fetch user {user_id} for admin notification: {e}")

        if context:
            notification_context.update(context)

        # Template path for admin notifications
        template_path = get_email_template_path(f'admin_{notification_type}', 'emails/admin')

        # Send notification
        if should_use_async_email():
            async_task(
                    'email.tasks.send_admin_notification_task',
                    subject=subject,
                    message=message,
                    notification_type=notification_type,
                    template_path=template_path,
                    context=notification_context
            )
            logger.info(f"Admin notification ({notification_type}) queued: {subject}")
        else:
            success = send_admin_notification_task(
                    subject=subject,
                    message=message,
                    notification_type=notification_type,
                    template_path=template_path,
                    context=notification_context
            )
            if success:
                logger.info(f"Admin notification ({notification_type}) sent: {subject}")
            else:
                logger.error(f"Admin notification ({notification_type}) failed: {subject}")
                return False

        return True

    except Exception as e:
        logger.error(f"Admin notification service failed: {e}", exc_info=True)
        return False


def send_bulk_user_emails(email_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send multiple emails to users in a batch.
    Useful for newsletters, announcements, etc.
    """
    try:
        if not has_required_email_settings():
            logger.warning("Email not configured, cannot send bulk emails")
            return {'success': 0, 'failed': len(email_list), 'total': len(email_list)}

        results = {
            'total': len(email_list),
            'success': 0,
            'failed': 0,
            'errors': []
        }

        # Process each email
        for i, email_config in enumerate(email_list):
            try:
                user_id = email_config.get('user_id')
                notification_type = email_config.get('notification_type', 'general')
                context = email_config.get('context', {})

                success = send_user_notification_email(user_id, notification_type, context)

                if success:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Email {i + 1}: Failed to send to user {user_id}")

            except Exception as e:
                results['failed'] += 1
                error_msg = f"Email {i + 1}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(f"Bulk email error: {error_msg}")

        logger.info(f"Bulk email completed: {results['success']} success, {results['failed']} failed")
        return results

    except Exception as e:
        logger.error(f"Bulk email service failed: {e}", exc_info=True)
        return {
            'total': len(email_list) if email_list else 0,
            'success': 0,
            'failed': len(email_list) if email_list else 0,
            'errors': [str(e)]
        }


def send_transfer_notification_email(user_id: int, transfer_id: int,
                                     status_change: str, context: Optional[Dict] = None) -> bool:
    """
    Send transfer-related notification emails.
    Specific to the money transfer business logic.
    """
    try:
        # Build transfer-specific context
        transfer_context = {
            'transfer_id': transfer_id,
            'status_change': status_change,
        }
        if context:
            transfer_context.update(context)

        # Add transfer reference and details if available
        try:
            # Import here to avoid circular imports
            from transfers.models import Transfer
            transfer = Transfer.objects.get(id=transfer_id)
            transfer_context.update({
                'transfer_reference': getattr(transfer, 'reference', f'T{transfer_id}'),
                'transfer_status': getattr(transfer, 'status', 'unknown'),
                'transfer_amount': getattr(transfer, 'amount', 'N/A'),
                'transfer_currency': getattr(transfer, 'sent_currency', 'N/A'),
                'beneficiary_name': getattr(transfer, 'beneficiary_name', 'N/A'),
            })
        except Exception as e:
            logger.warning(f"Could not fetch transfer {transfer_id} details: {e}")

        # Send notification using the general notification system
        return send_user_notification_email(
                user_id=user_id,
                notification_type='transfer_status_change',
                context=transfer_context
        )

    except Exception as e:
        logger.error(f"Transfer notification email failed for user {user_id}, transfer {transfer_id}: {e}",
                     exc_info=True)
        return False


def notify_admin_of_user_action(user_id: int, action: str, details: Optional[Dict] = None) -> bool:
    """
    Notify admins of important user actions.
    Used for security alerts, suspicious activity, etc.
    """
    try:
        # Get user info
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.get(id=user_id)
            user_info = f"{user.username} ({user.get_full_name() or 'No name'})"
        except User.DoesNotExist:
            user_info = f"User ID {user_id} (not found)"

        subject = f"User Action Alert: {action}"
        message = f"User {user_info} performed action: {action}"

        if details:
            message += f"\n\nDetails:\n"
            for key, value in details.items():
                message += f"- {key}: {value}\n"

        # Add timestamp
        message += f"\nTimestamp: {timezone.now().isoformat()}"

        return send_admin_notification(
                subject=subject,
                message=message,
                notification_type='user_action',
                context={
                    'user_id': user_id,
                    'action': action,
                    'details': details or {}
                },
                user_id=user_id
        )

    except Exception as e:
        logger.error(f"Admin user action notification failed: {e}", exc_info=True)
        return False


def send_system_alert_email(alert_type: str, message: str, severity: str = 'medium',
                            context: Optional[Dict] = None) -> bool:
    """
    Send system alerts to admins for technical issues, security concerns, etc.
    """
    try:
        subject = f"[{severity.upper()}] System Alert: {alert_type}"

        alert_message = f"System Alert: {alert_type}\n"
        alert_message += f"Severity: {severity}\n"
        alert_message += f"Time: {timezone.now().isoformat()}\n\n"
        alert_message += f"Message: {message}\n"

        if context:
            alert_message += f"\nAdditional Context:\n"
            for key, value in context.items():
                alert_message += f"- {key}: {value}\n"

        return send_admin_notification(
                subject=subject,
                message=alert_message,
                notification_type='system_alert',
                context={
                    'alert_type': alert_type,
                    'severity': severity,
                    'alert_message': message,
                    'context': context or {}
                }
        )

    except Exception as e:
        logger.error(f"System alert email failed: {e}", exc_info=True)
        return False


def notify_managers_of_draft_transfer(transfer_id: int, agent_id: int) -> Dict[str, Any]:
    """
    Notify all managers when an agent creates a draft transfer due to missing commission config.
    Uses existing bulk email infrastructure.
    """
    try:
        if not has_required_email_settings():
            logger.warning("Email not configured, cannot send draft transfer notifications")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': ['Email not configured']}

        # Import here to avoid circular imports
        from django.contrib.auth import get_user_model
        from transfers.models import Transfer

        User = get_user_model()

        # Get transfer and agent details
        try:
            transfer = Transfer.objects.select_related('agent').get(id=transfer_id)
            agent = User.objects.get(id=agent_id)
        except (Transfer.DoesNotExist, User.DoesNotExist) as e:
            logger.error(f"Draft transfer notification failed: {e}")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': [str(e)]}

        # Get all active managers
        managers = User.objects.filter(user_type='MANAGER', is_active=True).exclude(email='')

        if not managers.exists():
            logger.warning("No active managers found to notify about draft transfer")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': ['No managers to notify']}

        # Prepare an email list using the existing bulk email system
        email_list = []
        for manager in managers:
            email_list.append({
                'user_id': manager.id,
                'notification_type': 'draft_transfer_created',
                'context': {
                    'transfer_reference': transfer.reference_id,
                    'transfer_amount': str(transfer.amount),
                    'transfer_currency': transfer.sent_currency,
                    'beneficiary_name': transfer.beneficiary_name,
                    'agent_name': agent.get_full_name() or agent.username,
                    'agent_username': agent.username,
                    'missing_range': f"{transfer.amount} {transfer.sent_currency}",
                    'created_at': transfer.created_at.strftime('%d/%m/%Y %H:%M')
                }
            })

        # Use the existing bulk email function
        results = send_bulk_user_emails(email_list)

        logger.info(f"Draft transfer notification completed: {results['success']} success, {results['failed']} failed")
        return results

    except Exception as e:
        logger.error(f"Draft transfer notification service failed: {e}", exc_info=True)
        return {'success': 0, 'failed': 1, 'total': 1, 'errors': [str(e)]}


def notify_agents_of_auto_promotion(promoted_transfers: list, commission_config_id: int) -> Dict[str, Any]:
    """
    Notify agents when their draft transfers are auto-promoted due to new commission config.
    Uses existing bulk email infrastructure.
    """
    try:
        if not has_required_email_settings():
            logger.warning("Email not configured, cannot send auto-promotion notifications")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': ['Email not configured']}

        # Import here to avoid circular imports
        from django.contrib.auth import get_user_model
        from transfers.models import CommissionConfig

        User = get_user_model()

        # Get commission config details
        try:
            config = CommissionConfig.objects.select_related('manager').get(id=commission_config_id)
        except CommissionConfig.DoesNotExist:
            logger.error(f"Commission config {commission_config_id} not found for auto-promotion notification")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': ['Commission config not found']}

        # Group transfers by agent
        agent_transfers = {}
        for transfer_data in promoted_transfers:
            agent_username = transfer_data.get('agent')
            if agent_username and agent_username != 'No agent':
                if agent_username not in agent_transfers:
                    agent_transfers[agent_username] = []
                agent_transfers[agent_username].append(transfer_data)

        if not agent_transfers:
            logger.info("No agents to notify for auto-promotion")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': []}

        # Prepare an email list using the existing bulk email system
        email_list = []
        for agent_username, transfers in agent_transfers.items():
            try:
                agent = User.objects.get(username=agent_username, is_active=True)
                if agent.email:
                    email_list.append({
                        'user_id': agent.id,
                        'notification_type': 'transfers_auto_promoted',
                        'context': {
                            'promoted_count': len(transfers),
                            'config_currency': config.currency,
                            'config_range': f"{config.min_amount} - {config.max_amount}",
                            'commission_amount': str(config.commission_amount),
                            'manager_name': config.manager.get_full_name() or config.manager.username
                        }
                    })
                else:
                    logger.warning(f"Agent {agent_username} has no email address for auto-promotion notification")
            except User.DoesNotExist:
                logger.warning(f"Agent {agent_username} not found for auto-promotion notification")

        if not email_list:
            logger.warning("No agents with email addresses found for auto-promotion notification")
            return {'success': 0, 'failed': 0, 'total': 0, 'errors': ['No agents with emails']}

        # Use the existing bulk email function
        results = send_bulk_user_emails(email_list)

        logger.info(f"Auto-promotion notification completed: {results['success']} success, {results['failed']} failed")
        return results

    except Exception as e:
        logger.error(f"Auto-promotion notification service failed: {e}", exc_info=True)
        return {'success': 0, 'failed': 1, 'total': 1, 'errors': [str(e)]}


def notify_agent_of_manual_promotion(transfer_id: int, promoted_by_user_id: int) -> bool:
    """
    Notify the agent when their draft transfer is manually promoted by a manager.
    Uses existing single email infrastructure.
    """
    try:
        if not has_required_email_settings():
            logger.warning("Email not configured, cannot send manual promotion notification")
            return False

        # Import here to avoid circular imports
        from django.contrib.auth import get_user_model
        from transfers.models import Transfer

        User = get_user_model()

        # Get transfer and user details
        try:
            transfer = Transfer.objects.select_related('agent').get(id=transfer_id)
            promoted_by = User.objects.get(id=promoted_by_user_id)
        except (Transfer.DoesNotExist, User.DoesNotExist) as e:
            logger.error(f"Manual promotion notification failed: {e}")
            return False

        # Only notify if agent has email
        if not transfer.agent or not transfer.agent.email:
            logger.info(f"No agent email for manual promotion notification of transfer {transfer_id}")
            return True  # Not an error, just no email to send

        # Use existing single email function
        return send_user_notification_email(
                user_id=transfer.agent.id,
                notification_type='transfer_manually_promoted',
                context={
                    'transfer_reference': transfer.reference_id,
                    'transfer_amount': str(transfer.amount),
                    'transfer_currency': transfer.sent_currency,
                    'beneficiary_name': transfer.beneficiary_name,
                    'promoted_by_name': promoted_by.get_full_name() or promoted_by.username,
                    'promoted_by_role': 'Manager' if promoted_by.is_manager() else 'Superuser'
                }
        )

    except Exception as e:
        logger.error(f"Manual promotion notification failed for transfer {transfer_id}: {e}", exc_info=True)
        return False
