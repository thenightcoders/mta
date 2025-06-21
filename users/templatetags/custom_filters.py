# Create this file: users/templatetags/__init__.py (empty file)

# Create this file: users/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def replace_underscore(value):
    """Replace underscores with spaces"""
    return str(value).replace('_', ' ')

@register.filter
def get_activity_badge_class(user):
    """Get appropriate badge class for user type"""
    if user.is_superuser:
        return 'danger'
    elif user.is_manager():
        return 'success'
    else:
        return 'primary'

@register.filter
def get_activity_user_display(user):
    """Get appropriate user display for activity logs"""
    if user.is_superuser:
        return 'SUPER'
    else:
        return user.get_user_type_display()

@register.filter
def format_activity_detail(value, key):
    """Format activity detail values based on key type"""
    if key == 'transfer_id':
        return f'#{value}'
    elif key in ['amount', 'commission_amount'] and value != '0':
        return f'{value}'
    elif key in ['currency', 'sent_currency', 'received_currency']:
        return value
    elif key in ['new_status', 'status']:
        return value
    elif key == 'error':
        return str(value)[:50] + '...' if len(str(value)) > 50 else str(value)
    else:
        return str(value)[:30] + '...' if len(str(value)) > 30 else str(value)
