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
from .models import CURRENCY_CHOICES, Stock, StockMovement, ExchangeRate
from .forms import StockForm, StockMovementForm, ExchangeRateForm, MoneyDepositForm
from users.models import log_user_activity


@login_required
def stock_list(request):
    """List all stocks - managers and superusers only"""
    if not request.user.is_manager():
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
    if not request.user.is_manager():
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
    if not request.user.is_manager():
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
    if not request.user.is_manager():
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
def money_deposit(request):                           # same logic as create_stock_movement, can be optimized
    """ Declare Money deposit into a specified Stock """
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        form = MoneyDepositForm(request.POST)
        if form.is_valid():
            deposit = form.save(commit=False)
            deposit.type = 'IN'                 # it's a deposit
            deposit.created_by = request.user
            deposit.save()

            messages.success(request, "Dépôt enregistré avec succès.")
            return redirect('dashboard')
        else:
            messages.error(request, "Erreur dans le formulaire.")
    else:
        form = MoneyDepositForm()

    return render(request, 'stock/deposit.html', {'form': form})


@login_required
def exchange_rate_list(request):
    """List all exchange rates - managers and superusers only"""
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    # 5 latest rates sorted by the newest first (for display purposes)
    rates = ExchangeRate.objects.filter().order_by('-created_at')[:5]
    # sort by active status
    rates = sorted(rates, key=lambda x: (not x.active, x.created_at), reverse=False)

    # Get the latest active rates only (using the model method)
    latest_rates = ExchangeRate.get_current_rates_for_agent()

    context = {
        'rates': rates,
        'latest_rates': latest_rates,
    }

    return render(request, 'stock/exchange_rate_list.html', context)


@login_required
def stock_movements(request):
    """List all stock movements - managers and superusers only"""
    if not request.user.is_manager():
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


@login_required
def create_exchange_rate(request):
    """Create new exchange rate - managers and superusers only"""
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        form = ExchangeRateForm(request.POST)
        if form.is_valid():
            try:
                # Let's get the latest rate for this currency pair first
                old_rate = ExchangeRate.objects.filter(
                        from_currency=form.cleaned_data['from_currency'],
                        to_currency=form.cleaned_data['to_currency'],
                        active=True
                ).first()

                # Then let's create NEW rate - PRESERVES HISTORY
                new_rate = ExchangeRate(
                        from_currency=form.cleaned_data['from_currency'],
                        to_currency=form.cleaned_data['to_currency'],
                        rate=form.cleaned_data['rate'],
                        defined_by=request.user,
                        active=True
                )
                new_rate.save()

                # Deactivating old rate
                old_rate.active = False
                old_rate.save()

                log_user_activity(
                        request.user,
                        'exchange_rate_created',
                        {
                            'rate_id': new_rate.id,
                            'from_currency': new_rate.from_currency,
                            'to_currency': new_rate.to_currency,
                            'rate': str(new_rate.rate),
                            'conversion_example': f'1 {new_rate.from_currency} = {new_rate.rate} {new_rate.to_currency}'
                        },
                        request
                )

                messages.success(request,
                                 f'Exchange rate {new_rate.from_currency} → {new_rate.to_currency}: {new_rate.rate} created successfully')
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
def update_exchange_rate(request, rate_id):
    """Update existing exchange rate - managers and superusers only"""
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    rate = get_object_or_404(ExchangeRate, id=rate_id)

    if request.method == 'POST':
        form = ExchangeRateForm(request.POST, instance=rate)
        if form.is_valid():
            try:
                # Let's get the latest rate for this currency pair first
                old_rate = ExchangeRate.objects.filter(
                        from_currency=form.cleaned_data['from_currency'],
                        to_currency=form.cleaned_data['to_currency'],
                        active=True
                ).first()

                # Then let's create NEW rate - PRESERVES HISTORY
                new_rate = ExchangeRate(
                        from_currency=form.cleaned_data['from_currency'],
                        to_currency=form.cleaned_data['to_currency'],
                        rate=form.cleaned_data['rate'],
                        defined_by=request.user,
                        active=True
                )
                new_rate.save()

                # Deactivating old rate
                old_rate.active = False
                old_rate.save()

                log_user_activity(
                        request.user,
                        'exchange_rate_updated',
                        {
                            'rate_id': new_rate.id,
                            'from_currency': new_rate.from_currency,
                            'to_currency': new_rate.to_currency,
                            'new_rate': str(new_rate.rate),
                            'previous_rate': str(rate.rate) if rate.rate != new_rate.rate else 'unchanged'
                        },
                        request
                )

                messages.success(request,
                                f'Exchange rate {new_rate.from_currency} → {new_rate.to_currency} updated to {new_rate.rate}')
                return redirect('exchange_rate_list')

            except ValidationError as e:
                messages.error(request, str(e))
                log_user_activity(
                    request.user,
                    'exchange_rate_update_failed',
                    {'error': str(e), 'rate_id': rate_id},
                    request
                )
    else:
        form = ExchangeRateForm(instance=rate)

    context = {
        'form': form,
        'rate': rate,
        'is_update': True,
    }

    return render(request, 'stock/update_exchange_rate.html', context)


@login_required
@require_http_methods(["POST"])
def toggle_exchange_rate_active(request, rate_id):
    """Toggle exchange rate active status - managers and superusers only"""
    if not request.user.is_manager():
        return JsonResponse({'error': 'Access denied'}, status=403)

    rate = get_object_or_404(ExchangeRate, id=rate_id)

    # Toggle active status (assuming we add an 'active' field to ExchangeRate model)
    rate.active = not getattr(rate, 'active', True)
    rate.save()

    log_user_activity(
            request.user,
            'exchange_rate_toggled',
            {
                'rate_id': rate.id,
                'from_currency': rate.from_currency,
                'to_currency': rate.to_currency,
                'new_status': 'active' if rate.active else 'inactive'
            },
            request
    )

    return JsonResponse({
        'success': True,
        'new_status': rate.active,
        'status_text': 'Active' if rate.active else 'Inactive'
    })


@login_required
@require_http_methods(["POST"])
def delete_exchange_rate(request, rate_id):
    """Delete exchange rate - superusers only"""
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Access denied - superuser required'}, status=403)

    rate = get_object_or_404(ExchangeRate, id=rate_id)

    # Store info for logging before deletion
    rate_info = {
        'rate_id': rate.id,
        'from_currency': rate.from_currency,
        'to_currency': rate.to_currency,
        'rate': str(rate.rate)
    }

    rate.delete()

    log_user_activity(
            request.user,
            'exchange_rate_deleted',
            rate_info,
            request
    )

    messages.success(request, f'Exchange rate {rate_info["from_currency"]} → {rate_info["to_currency"]} deleted permanently')

    return JsonResponse({'success': True})


@login_required
def exchange_rate_history(request, from_currency, to_currency):
    """View historical exchange rates for a currency pair"""
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    rates = ExchangeRate.objects.filter(
        from_currency=from_currency,
        to_currency=to_currency
    ).order_by('-created_at')

    # Get latest rate for context
    latest_rate = rates.first()

    context = {
        'rates': rates,
        'from_currency': from_currency,
        'to_currency': to_currency,
        'latest_rate': latest_rate,
        'currency_choices': CURRENCY_CHOICES,
    }

    return render(request, 'stock/exchange_rate_history.html', context)
