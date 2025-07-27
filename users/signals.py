import logging
import threading

from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

User = get_user_model()
logger = logging.getLogger(__name__)

# Thread-local storage for the current user and request context
_thread_locals = threading.local()


def set_current_user(user):
    """Set current-user for signal handlers - used in tests or special cases"""
    _thread_locals.user = user


def get_current_user():
    """Get current-user from thread local storage"""
    return getattr(_thread_locals, 'user', None)


def get_current_request():
    """Get current-request from thread local storage"""
    return getattr(_thread_locals, 'request', None)


class ActivityLoggingMiddleware:
    """
    Middleware to capture current-user and request for audit logging.
    Helpful for financial compliance - we need to know who did what.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Store current user and request in thread locals for signal access
        try:
            if hasattr(request, 'user') and request.user.is_authenticated:
                _thread_locals.user = request.user
                _thread_locals.request = request

            response = self.get_response(request)

        except Exception as e:
            # Log middleware errors but don't break the request
            logger.error(f"ActivityLoggingMiddleware error: {e}", exc_info=True)
            # Still process the request even if logging setup fails
            response = self.get_response(request)

        finally:
            # ALWAYS clean up thread locals to prevent memory leaks
            if hasattr(_thread_locals, 'user'):
                delattr(_thread_locals, 'user')
            if hasattr(_thread_locals, 'request'):
                delattr(_thread_locals, 'request')

        return response


def safe_log_activity(action, details=None):
    """
    Safe logging that won't break main operations if audit logging fails.
    In a financial app, the business operation must succeed even if logging fails.
    """
    try:
        current_user = get_current_user()
        if not current_user:
            # No user context - likely a system operation, migration, or test
            return

        # Import here to avoid circular imports and potential infinite loops
        from .models import UserActivity

        activity_data = {
            'user': current_user,
            'action': action,
            'details': details or {},
        }

        # Add an IP address if we have request context
        request = get_current_request()
        if request:
            activity_data['ip_address'] = request.META.get('REMOTE_ADDR')

        UserActivity.objects.create(**activity_data)

    except Exception as e:
        # NEVER let logging failures break business operations
        # But DO log the failure so we know our audit trail has gaps
        logger.error(f"Audit logging failed for action '{action}': {e}", exc_info=True)


def extract_model_details(instance):
    """
    Extract meaningful details from model instances for audit logging.
    Returns a dict with relevant information for each model type.
    """
    details = {
        'model': instance._meta.label,
        'object_id': getattr(instance, 'id', None),
    }

    try:
        # User model details
        if hasattr(instance, 'username'):
            details.update({
                'username': instance.username,
                'user_type': getattr(instance, 'user_type', 'unknown'),
                'name': f'{getattr(instance, "first_name", "")} {getattr(instance, "last_name", "")}'.strip() or instance.username,
                'email': getattr(instance, 'email', ''),
                'is_active': getattr(instance, 'is_active_user', None)
            })

        # Transfer model details - critical for financial audit
        elif hasattr(instance, 'beneficiary_name'):
            details.update({
                'beneficiary_name': instance.beneficiary_name,
                'amount': str(getattr(instance, 'amount', 0)),
                'currency': getattr(instance, 'sent_currency', 'unknown'),
                'status': getattr(instance, 'status', 'unknown'),
                'agent_username': getattr(instance.agent, 'username', 'No agent') if hasattr(instance,
                                                                                             'agent') and instance.agent else 'No agent',
                'reference': getattr(instance, 'reference', '')
            })

        # Stock model details - important for cash management
        elif hasattr(instance, 'currency') and hasattr(instance, 'location'):
            details.update({
                'currency': instance.currency,
                'location': instance.location,
                'amount': str(getattr(instance, 'amount', 0)),
                'name': getattr(instance, 'name', 'Unnamed stock')
            })

        # Stock movement details - cash flow tracking
        elif hasattr(instance, 'type') and hasattr(instance, 'stock'):
            details.update({
                'movement_type': instance.type,
                'amount': str(getattr(instance, 'amount', 0)),
                'stock_currency': getattr(instance.stock, 'currency', 'unknown'),
                'stock_location': getattr(instance.stock, 'location', 'unknown'),
                'reason': getattr(instance, 'reason', 'No reason provided')
            })

        # Exchange rate details - affects all calculations
        elif hasattr(instance, 'from_currency') and hasattr(instance, 'to_currency'):
            details.update({
                'from_currency': instance.from_currency,
                'to_currency': instance.to_currency,
                'rate': str(getattr(instance, 'rate', 0)),
                'active': getattr(instance, 'active', None)
            })

        # Commission configuration - affects profit calculations
        elif hasattr(instance, 'commission_amount'):
            details.update({
                'currency': getattr(instance, 'currency', 'unknown'),
                'commission_amount': str(instance.commission_amount),
                'agent_share': str(getattr(instance, 'agent_share', 0)),
                'manager_share': str(getattr(instance, 'manager_share', 0)),
                'active': getattr(instance, 'active', None)
            })

        # Commission distribution - actual payments made
        elif hasattr(instance, 'total_commission'):
            details.update({
                'transfer_id': getattr(instance.transfer, 'id', None) if hasattr(instance,
                                                                                 'transfer') and instance.transfer else None,
                'total_commission': str(instance.total_commission),
                'agent_amount': str(getattr(instance, 'declaring_agent_amount', 0)),
                'manager_amount': str(getattr(instance, 'manager_amount', 0)),
                'agent_username': getattr(instance.agent, 'username', 'unknown') if hasattr(instance,
                                                                                            'agent') and instance.agent else 'unknown'
            })

    except AttributeError as e:
        # Specific handling for missing attributes
        logger.warning(f"Missing attribute while extracting details for {instance._meta.label}: {e}")
        details['extraction_error'] = f"Missing attribute: {e}"

    except Exception as e:
        # Log any other errors in detail extraction
        logger.error(f"Unexpected error extracting details for {instance._meta.label}: {e}", exc_info=True)
        details['extraction_error'] = f"Extraction failed: {e}"

    return details


@receiver(post_save)
def log_model_saves(sender, instance, created, **kwargs):
    """
    Automatically log all model saves for financial audit compliance.
    Every change to data needs to be tracked with user attribution.
    """
    # Skip UserActivity to prevent infinite loops
    if sender._meta.label == 'users.UserActivity':
        return

    # Skip if no current user (migrations, system operations, tests)
    current_user = get_current_user()
    if not current_user:
        return

    # Skip Django's built-in models that don't need business audit
    if sender._meta.label in ['sessions.Session', 'admin.LogEntry', 'contenttypes.ContentType']:
        return

    try:
        model_name = sender._meta.label.lower().replace('.', '_')
        action = f'{model_name}_{"created" if created else "updated"}'

        # Extract relevant details based on model type
        details = extract_model_details(instance)
        details['created'] = created

        # Add change tracking for updates
        if not created and hasattr(instance, 'get_dirty_fields'):
            try:
                # If you have django-dirtyfields installed
                dirty_fields = instance.get_dirty_fields()
                if dirty_fields:
                    details['changed_fields'] = list(dirty_fields.keys())
            except Exception as e:
                logger.debug(f"Could not get dirty fields for {model_name}: {e}")

        safe_log_activity(action, details)

    except Exception as e:
        # Log the error but don't break the save operation
        logger.error(f"Error in post_save signal for {sender._meta.label}: {e}", exc_info=True)


@receiver(post_delete)
def log_model_deletes(sender, instance, **kwargs):
    """
    Automatically log all model deletions for financial audit compliance.
    Deletions are critical to track in financial systems.
    """
    # Skip UserActivity to prevent issues
    if sender._meta.label == 'users.UserActivity':
        return

    # Skip if no current user
    current_user = get_current_user()
    if not current_user:
        return

    # Skip Django's built-in models
    if sender._meta.label in ['sessions.Session', 'admin.LogEntry', 'contenttypes.ContentType']:
        return

    try:
        model_name = sender._meta.label.lower().replace('.', '_')
        action = f'{model_name}_deleted'

        # Extract details about what was deleted
        details = extract_model_details(instance)
        details['deleted_object_id'] = getattr(instance, 'id', None)

        # Add specific identifying information about deleted object
        if hasattr(instance, 'username'):
            details['deleted_username'] = instance.username
        elif hasattr(instance, 'beneficiary_name'):
            details['deleted_beneficiary'] = instance.beneficiary_name
        elif hasattr(instance, 'currency'):
            details['deleted_currency'] = instance.currency
        elif hasattr(instance, 'reference'):
            details['deleted_reference'] = getattr(instance, 'reference', '')

        safe_log_activity(action, details)

    except Exception as e:
        # Log the error but don't break the delete operation
        logger.error(f"Error in post_delete signal for {sender._meta.label}: {e}", exc_info=True)
