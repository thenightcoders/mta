from django.urls import path

from . import views

urlpatterns = [
    # Transfer management
    path('', views.transfer_list, name='transfer_list'),
    path('create/', views.create_transfer, name='create_transfer'),
    path('<int:transfer_id>/', views.transfer_detail, name='transfer_detail'),
    path('<int:transfer_id>/validate/', views.validate_transfer, name='validate_transfer'),
    path('<int:transfer_id>/execute/', views.execute_transfer, name='execute_transfer'),
    path('pending/', views.pending_transfers, name='pending_transfers'),

    # Commission configuration
    path('commissions/', views.commission_config_list, name='commission_config_list'),
    path('commissions/create/', views.create_commission_config, name='create_commission_config'),
    path('commissions/<int:config_id>/toggle/', views.toggle_commission_config, name='toggle_commission_config'),
    path('commissions/<int:config_id>/update/', views.update_commission_config, name='update_commission_config'),

    # Commission preview (AJAX)
    path('commission-preview/', views.get_commission_preview, name='commission_preview'),

    # Earnings
    path('commissions/overview/', views.commissions_overview, name='commissions_overview'),
    path('commissions/clear/', views.clear_commissions, name='clear_commissions'),

    # draft transfers
    path('drafts/', views.draft_transfers, name='draft_transfers'),
    path('<int:transfer_id>/promote/', views.promote_draft_transfer, name='promote_draft_transfer'),
    # Check promotable transfers before showing modal
    path('check-promotable-config/<int:config_id>/', views.check_promotable_transfers, name='check_promotable_transfers'),
    # Manual bulk promotion for when auto-promotion fails
    path('bulk-promote-config/<int:config_id>/', views.bulk_promote_by_config, name='bulk_promote_by_config'),

]
