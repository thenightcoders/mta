from django.urls import path
from . import views

urlpatterns = [
    # Stock management
    path('', views.stock_list, name='stock_list'),
    path('create/', views.create_stock, name='create_stock'),
    path('<int:stock_id>/', views.stock_detail, name='stock_detail'),
    path('<int:stock_id>/movement/', views.create_stock_movement, name='create_stock_movement'),
    path('movements/', views.stock_movements, name='stock_movements'),
    path('deposit/', views.money_deposit, name='deposit'),
    # Exchange rates
    path('rates/', views.exchange_rate_list, name='exchange_rate_list'),
    path('rates/create/', views.create_exchange_rate, name='create_exchange_rate'),
]
