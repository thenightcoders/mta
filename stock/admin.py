from django.contrib import admin
from .models import Stock, StockMovement, ExchangeRate


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('currency', 'location', 'amount', 'name', 'updated_at')
    list_filter = ('location', 'currency')
    search_fields = ('currency', 'name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('type', 'stock', 'amount', 'destination_stock', 'get_transfer_rate', 'created_at', 'created_by')
    list_filter = ('type', 'created_by', 'created_at', 'stock__location', 'stock__currency')
    search_fields = ('created_by__username', 'reason')
    autocomplete_fields = ['stock', 'destination_stock', 'created_by']
    readonly_fields = ('created_at',)

    def get_transfer_rate(self, obj):
        if obj.destination_stock:
            try:
                return obj.get_stock_transfer_rate()
            except:
                return "Aucun taux appliqué"
        return "-"
    get_transfer_rate.short_description = "Taux appliqué"

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ('from_currency', 'to_currency', 'rate', 'created_at', 'defined_by')
    list_filter = ('from_currency', 'to_currency', 'created_at')
    search_fields = ('from_currency', 'to_currency')
    readonly_fields = ('created_at',)

    def save_model(self, request, obj, form, change):
        if not obj.defined_by:
            obj.defined_by = request.user
        super().save_model(request, obj, form, change)
