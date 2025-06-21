from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserActivity


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # The forms to add and change user instances
    list_display = ('username', 'email', 'first_name', 'last_name', 'user_type', 'is_active_user', 'created_at')
    list_filter = ('user_type', 'is_active_user', 'is_staff', 'is_superuser', 'created_at')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)

    # Add the custom fields to the fieldsets
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Custom Fields', {
            'fields': ('user_type', 'phone', 'location', 'is_active_user', 'created_by')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # Add the custom fields to the add_fieldsets
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Custom Fields', {
            'fields': ('user_type', 'phone', 'location', 'is_active_user', 'created_by')
        }),
    )

    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'timestamp', 'ip_address')
    list_filter = ('action', 'timestamp', 'user__user_type')
    search_fields = ('user__username', 'action', 'ip_address')
    readonly_fields = ('user', 'action', 'details', 'ip_address', 'timestamp')
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        # Don't allow adding activities manually
        return False

    def has_change_permission(self, request, obj=None):
        # Don't allow changing activities
        return False
