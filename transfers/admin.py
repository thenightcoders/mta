from django.contrib import admin
from .models import Transfer, CommissionConfig, CommissionDistribution


class CommissionDistributionInline(admin.StackedInline):
    model = CommissionDistribution
    can_delete = False
    readonly_fields = ('total_commission', 'declaring_agent_amount', 'manager_amount', 'created_at')
    extra = 0


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    inlines = [CommissionDistributionInline]

    list_display = (
        'id', 'beneficiary_name', 'beneficiary_phone', 'amount',
        'sent_currency', 'received_currency', 'method', 'agent', 'status',
        'created_at'
    )

    list_filter = ('status', 'agent', 'sent_currency', 'received_currency', 'method', 'created_at')
    search_fields = ('beneficiary_name', 'beneficiary_phone', 'agent__username')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Transfer Details', {
            'fields': ('beneficiary_name', 'beneficiary_phone', 'method', 'amount',
                       'sent_currency', 'received_currency', 'comment')
        }),
        ('Agent & Status', {
            'fields': ('agent', 'status')
        }),
        ('Validation', {
            'fields': ('validated_by', 'validated_at', 'validation_comment'),
            'classes': ('collapse',)
        }),
        ('Execution', {
            'fields': ('executed_by', 'executed_at', 'execution_comment'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        # Auto-set validated_by and executed_by based on current user and status changes
        if not change:  # New object
            if not obj.agent:
                obj.agent = request.user

        super().save_model(request, obj, form, change)


@admin.register(CommissionConfig)
class CommissionConfigAdmin(admin.ModelAdmin):
    list_display = (
        'manager', 'currency', 'min_amount', 'max_amount',
        'commission_rate', 'agent_share', 'manager_share', 'active', 'created_at'
    )

    list_filter = ('currency', 'active', 'manager', 'created_at')
    search_fields = ('manager__username', 'manager__first_name', 'manager__last_name')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Basic Configuration', {
            'fields': ('manager', 'currency', 'min_amount', 'max_amount', 'active')
        }),
        ('Commission Rates', {
            'fields': ('commission_rate', 'agent_share'),
            'description': 'Commission rate is percentage of transfer amount. Agent share is percentage of total commission.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def manager_share(self, obj):
        return f"{obj.manager_share}%"

    manager_share.short_description = "Manager Share"

    def save_model(self, request, obj, form, change):
        if not obj.manager_id:
            obj.manager = request.user
        super().save_model(request, obj, form, change)


@admin.register(CommissionDistribution)
class CommissionDistributionAdmin(admin.ModelAdmin):
    list_display = (
        'transfer_id', 'get_transfer_beneficiary', 'agent', 'total_commission',
        'declaring_agent_amount', 'manager_amount', 'created_at'
    )

    list_filter = ('created_at', 'agent', 'config_used__currency')
    search_fields = (
        'transfer__beneficiary_name', 'transfer__id',
        'agent__username', 'agent__first_name', 'agent__last_name'
    )
    readonly_fields = ('created_at',)

    def get_transfer_beneficiary(self, obj):
        return obj.transfer.beneficiary_name

    get_transfer_beneficiary.short_description = "Beneficiary"

    def transfer_id(self, obj):
        return f"#{obj.transfer.id}"

    transfer_id.short_description = "Transfer"
