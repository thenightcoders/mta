from django.contrib import admin
from .models import Stock, StockMovement, ExchangeRate

@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('currency', 'location', 'amount')
    list_filter = ('location', 'currency')
    search_fields = ('currency',)

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('type', 'stock', 'amount', 'destination_stock', 'get_transfer_rate', 'created_at', 'created_by')
    list_filter = ('type', 'created_by', 'created_at', 'stock__location', 'stock__currency', 'destination_stock__location')
    search_fields = ('created_by', 'reason')
    autocomplete_fields = ['stock', 'destination_stock']
    readonly_fields = ('created_at', 'created_by')

    def get_transfer_rate(self, obj):
        if obj.destination_stock:
            try:
                return obj.get_stock_transfer_rate()
            except:
                return "Aucun taux appliqué"
        return "-"
    get_transfer_rate.short_description = "Taux appliqué"

@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ('from_currency', 'to_currency', 'rate', 'created_at', 'defined_by')
    list_filter = ('from_currency', 'to_currency')
    search_fields = ('from_currency', 'to_currency')

admin.site.site_header = "Money Transfer Admin"
admin.site.site_title = "Gestion de Transferts"
admin.site.index_title = "Bienvenue dans l'espace d'administration"
