from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
import threading

User = get_user_model()

# Thread-local storage for current user
_thread_locals = threading.local()


def set_current_user(user):
    """Set current user for signal handlers"""
    _thread_locals.user = user


def get_current_user():
    """Get current user from thread local storage"""
    return getattr(_thread_locals, 'user', None)


def get_current_request():
    """Get current request from thread local storage"""
    return getattr(_thread_locals, 'request', None)


# Simple middleware to capture current user
class ActivityLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set current user and request
        if hasattr(request, 'user') and request.user.is_authenticated:
            _thread_locals.user = request.user
            _thread_locals.request = request

        response = self.get_response(request)

        # Clean up
        if hasattr(_thread_locals, 'user'):
            delattr(_thread_locals, 'user')
        if hasattr(_thread_locals, 'request'):
            delattr(_thread_locals, 'request')

        return response


def safe_log_activity(action, details=None):
    """Safe logging that won't break if something goes wrong"""
    try:
        current_user = get_current_user()
        if not current_user:
            return

        # Import here to avoid circular imports and infinite loops
        from .models import UserActivity

        activity_data = {
            'user': current_user,
            'action': action,
            'details': details or {},
        }

        # Add IP if we have request
        request = get_current_request()
        if request:
            activity_data['ip_address'] = request.META.get('REMOTE_ADDR')

        UserActivity.objects.create(**activity_data)
    except Exception:
        # If logging fails, don't break the main operation
        # In production you might want to log this error somewhere
        pass


# Automatic logging for all important models
@receiver(post_save)
def log_model_saves(sender, instance, created, **kwargs):
    """Automatically log all model saves"""
    # Skip UserActivity to prevent infinite loops
    if sender._meta.label == 'users.UserActivity':
        return

    # Skip if no current user (like during migrations)
    if not get_current_user():
        return

    model_name = sender._meta.label.lower().replace('.', '_')
    action = f'{model_name}_{"created" if created else "updated"}'

    details = {
        'model': sender._meta.label,
        'object_id': instance.id,
        'created': created
    }

    # Add specific details for important models
    try:
        if hasattr(instance, 'username'):  # User
            details.update({
                'username': instance.username,
                'user_type': getattr(instance, 'user_type', 'unknown'),
                'name': f'{instance.first_name} {instance.last_name}'.strip() or instance.username
            })
        elif hasattr(instance, 'beneficiary_name'):  # Transfer
            details.update({
                'beneficiary_name': instance.beneficiary_name,
                'amount': str(instance.amount),
                'currency': instance.sent_currency,
                'status': instance.status,
                'agent': instance.agent.username if instance.agent else 'No agent'
            })
        elif hasattr(instance, 'currency') and hasattr(instance, 'location'):  # Stock
            details.update({
                'currency': instance.currency,
                'location': instance.location,
                'amount': str(instance.amount),
                'name': instance.name or 'Unnamed stock'
            })
        elif hasattr(instance, 'type') and hasattr(instance, 'stock'):  # StockMovement
            details.update({
                'movement_type': instance.type,
                'amount': str(instance.amount),
                'stock_currency': instance.stock.currency,
                'reason': instance.reason or 'No reason'
            })
        elif hasattr(instance, 'from_currency'):  # ExchangeRate
            details.update({
                'from_currency': instance.from_currency,
                'to_currency': instance.to_currency,
                'rate': str(instance.rate)
            })
        elif hasattr(instance, 'commission_rate'):  # CommissionConfig
            details.update({
                'currency': instance.currency,
                'commission_rate': str(instance.commission_rate),
                'agent_share': str(instance.agent_share),
                'active': instance.active
            })
        elif hasattr(instance, 'total_commission'):  # CommissionDistribution
            details.update({
                'transfer_id': instance.transfer.id,
                'total_commission': str(instance.total_commission),
                'agent_amount': str(instance.declaring_agent_amount),
                'agent': instance.agent.username
            })
    except Exception: # faut que j'enlève ça, faut jamais faire ça
        # If detail extraction fails, just log basic info
        pass

    safe_log_activity(action, details)


@receiver(post_delete)
def log_model_deletes(sender, instance, **kwargs):
    """Automatically log all model deletions"""
    # Skip UserActivity
    if sender._meta.label == 'users.UserActivity':
        return

    if not get_current_user():
        return

    model_name = sender._meta.label.lower().replace('.', '_')
    action = f'{model_name}_deleted'

    details = {
        'model': sender._meta.label,
        'deleted_object_id': instance.id
    }

    # Add identifying info about what was deleted
    try:
        if hasattr(instance, 'username'):
            details['username'] = instance.username
        elif hasattr(instance, 'beneficiary_name'):
            details['beneficiary_name'] = instance.beneficiary_name
        elif hasattr(instance, 'currency'):
            details['currency'] = instance.currency
    except Exception:
        pass

    safe_log_activity(action, details)
