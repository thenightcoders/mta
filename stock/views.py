from collections import OrderedDict

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, Count
from django.db import models
from django.utils import timezone
from .models import Stock, StockMovement, ExchangeRate
from .forms import StockForm, StockMovementForm, ExchangeRateForm
from users.models import log_user_activity


@login_required
def stock_list(request):
    """List all stocks - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    # Log stock list access
    log_user_activity(request.user, 'stock_list_accessed', {}, request)

    stocks = Stock.objects.all().order_by('currency', 'location')

    # Calculate total by currency
    stock_totals = Stock.objects.values('currency').annotate(
            total_amount=Sum('amount')
    ).order_by('currency')

    context = {
        'stocks': stocks,
        'stock_totals': stock_totals,
    }

    return render(request, 'stock/stock_list.html', context)


@login_required
def stock_detail(request, stock_id):
    """View stock details and movements"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    stock = get_object_or_404(Stock, id=stock_id)
    movements = StockMovement.objects.filter(stock=stock).order_by('-created_at')[:20]

    # Calculate movement stats
    movement_stats = StockMovement.objects.filter(stock=stock).aggregate(
            total_in=Sum('amount', filter=Q(type='IN')),
            total_out=Sum('amount', filter=Q(type='OUT')),
            movement_count=models.Count('id')
    )

    context = {
        'stock': stock,
        'movements': movements,
        'movement_stats': movement_stats,
    }

    return render(request, 'stock/stock_detail.html', context)


@login_required
def create_stock(request):
    """Create new stock - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        form = StockForm(request.POST)
        if form.is_valid():
            try:
                stock = form.save()

                log_user_activity(
                        request.user,
                        'stock_created',
                        {
                            'stock_id': stock.id,
                            'currency': stock.currency,
                            'location': stock.location,
                            'initial_amount': str(stock.amount),
                            'name': stock.name or 'No name'
                        },
                        request
                )

                messages.success(request, f'Stock {stock.currency} - {stock.location} created successfully')
                return redirect('stock_detail', stock_id=stock.id)

            except ValidationError as e:
                messages.error(request, str(e))
                log_user_activity(
                    request.user,
                    'stock_creation_failed',
                    {'error': str(e), 'form_data': form.cleaned_data},
                    request
                )
    else:
        form = StockForm()

    return render(request, 'stock/create_stock.html', {'form': form})


@login_required
def create_stock_movement(request, stock_id):
    """Create stock movement - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    stock = get_object_or_404(Stock, id=stock_id)

    if request.method == 'POST':
        form = StockMovementForm(request.POST, stock=stock)

        if form.is_valid():
            try:
                old_balance = stock.amount

                movement = StockMovement(
                        stock=stock,
                        type=form.cleaned_data['type'],
                        amount=form.cleaned_data['amount'],
                        reason=form.cleaned_data.get('reason', ''),
                        destination_stock=form.cleaned_data.get('destination_stock'),
                        custom_exchange_rate=form.cleaned_data.get('custom_exchange_rate'),
                        created_by=request.user
                )

                movement.full_clean()
                movement.save()

                log_user_activity(
                        request.user,
                        'stock_movement_created',
                        {
                            'movement_id': movement.id,
                            'stock_id': stock.id,
                            'stock_currency': stock.currency,
                            'stock_location': stock.location,
                            'movement_type': movement.type,
                            'amount': str(movement.amount),
                            'old_balance': str(old_balance),
                            'new_balance': str(stock.amount),
                            'destination_stock_id': movement.destination_stock.id if movement.destination_stock else None,
                            'destination_currency': movement.destination_stock.currency if movement.destination_stock else None,
                            'exchange_rate': str(
                                movement.custom_exchange_rate) if movement.custom_exchange_rate else None,
                            'reason': movement.reason or 'No reason provided'
                        },
                        request
                )

                messages.success(request,
                                 f'Stock movement recorded successfully. New balance: {stock.amount} {stock.currency}')
                return redirect('stock_detail', stock_id=stock.id)

            except ValidationError as e:
                log_user_activity(
                        request.user,
                        'stock_movement_failed',
                        {
                            'stock_id': stock.id,
                            'error': str(e),
                            'form_data': form.cleaned_data
                        },
                        request
                )
            except Exception as e:
                form.add_error(None, f"An error occurred: {str(e)}")
        else:
            log_user_activity(
                    request.user,
                    'stock_movement_form_invalid',
                    {
                        'stock_id': stock.id,
                        'form_errors': dict(form.errors),
                        'form_data': request.POST.dict()
                    },
                    request
        )
    else:
        form = StockMovementForm(stock=stock)


    context = {
        'form': form,
        'stock': stock,
    }

    return render(request, 'stock/create_stock_movement.html', context)


@login_required
def exchange_rate_list(request):
    """List all exchange rates - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    # All rates sorted by newest first (for display purposes)
    rates = ExchangeRate.objects.all().order_by('-created_at')

    # Get the latest exchange rate per (from_currency, to_currency) pair
    ordered_rates = ExchangeRate.objects.order_by(
        'from_currency', 'to_currency', '-created_at'
    ).only('from_currency', 'to_currency', 'created_at', 'rate')

    latest_rates = OrderedDict()
    for rate in ordered_rates:
        key = (rate.from_currency, rate.to_currency)
        if key not in latest_rates:
            latest_rates[key] = rate

    context = {
        'rates': rates,
        'latest_rates': latest_rates.values(),
    }

    return render(request, 'stock/exchange_rate_list.html', context)


@login_required
def create_exchange_rate(request):
    """Create new exchange rate - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        form = ExchangeRateForm(request.POST)
        if form.is_valid():
            try:
                rate = form.save(commit=False)
                rate.defined_by = request.user
                rate.save()

                log_user_activity(
                        request.user,
                        'exchange_rate_created',
                        {
                            'rate_id': rate.id,
                            'from_currency': rate.from_currency,
                            'to_currency': rate.to_currency,
                            'rate': str(rate.rate),
                            'conversion_example': f'1 {rate.from_currency} = {rate.rate} {rate.to_currency}'
                        },
                        request
                )

                messages.success(request,
                                 f'Exchange rate {rate.from_currency} → {rate.to_currency}: {rate.rate} created successfully')
                return redirect('exchange_rate_list')

            except ValidationError as e:
                messages.error(request, str(e))
                log_user_activity(
                    request.user,
                    'exchange_rate_creation_failed',
                    {'error': str(e), 'form_data': form.cleaned_data},
                    request
                )
    else:
        form = ExchangeRateForm()

    return render(request, 'stock/create_exchange_rate.html', {'form': form})


@login_required
def stock_movements(request):
    """List all stock movements - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    movements = StockMovement.objects.select_related('stock', 'created_by', 'destination_stock').order_by('-created_at')

    # Filter by stock if specified
    stock_id = request.GET.get('stock')
    if stock_id:
        movements = movements.filter(stock_id=stock_id)

    # Filter by type if specified
    movement_type = request.GET.get('type')
    if movement_type:
        movements = movements.filter(type=movement_type)

    movements = movements[:50]  # Limit to recent 50

    context = {
        'movements': movements,
        'stocks': Stock.objects.all(),
        'current_stock': stock_id,
        'current_type': movement_type,
    }

    return render(request, 'stock/stock_movements.html', context)
