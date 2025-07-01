import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models
from django.db.models import Count, Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_http_methods

from config import settings
from .forms import LoginForm, UserCreationForm, UserUpdateForm
from .models import User, UserActivity

logger = logging.getLogger(__name__)


def log_user_activity(user, action, details=None, request=None):
    """Helper function to log user activities"""
    activity_data = {
        'user': user,
        'action': action,
        'details': details or {},
    }

    if request:
        activity_data['ip_address'] = request.META.get('REMOTE_ADDR')

    UserActivity.objects.create(**activity_data)


def login_view(request):
    """Handle user login"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            user = authenticate(request, username=username, password=password)
            if user and user.is_active_user:
                login(request, user)

                # Redirect based on user type
                if user.is_superuser or user.is_manager():
                    return redirect('manager_dashboard')
                else:
                    return redirect('agent_dashboard')
            else:
                messages.error(request, 'Invalid credentials or inactive account')
    else:
        form = LoginForm()

    return render(request, 'users/login.html', {'form': form})


def logout_view(request):
    """Handle user logout"""
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, 'You have been logged out successfully')

    return redirect('login')


@login_required
def dashboard(request):
    """Main dashboard - redirect based on user type"""
    if request.user.is_superuser or request.user.is_manager():
        print("user is superuser or manager, redirecting to manager dashboard")
        return redirect('manager_dashboard')
    else:
        print("user is agent, redirecting to agent dashboard")
        return redirect('agent_dashboard')


@login_required
def manager_dashboard(request):
    """Dashboard for managers and superusers"""
    if not (request.user.is_superuser or request.user.is_manager()):
        return HttpResponseForbidden("Access denied")

    # Import here to avoid circular imports
    from transfers.models import Transfer, CommissionDistribution
    from stock.models import Stock

    # Get dashboard stats - hide superusers from managers
    if request.user.is_superuser:
        total_agents = User.objects.filter(user_type='agent', is_active_user=True).count()
        total_managers = User.objects.filter(user_type='manager', is_active_user=True).count()
        recent_activities = UserActivity.objects.select_related('user').order_by('-timestamp')[:15]
    else:
        # Managers see only regular users (no superusers)
        total_agents = User.objects.filter(user_type='agent', is_active_user=True, is_superuser=False).count()
        total_managers = User.objects.filter(user_type='manager', is_active_user=True, is_superuser=False).count()
        recent_activities = UserActivity.objects.filter(user__is_superuser=False).select_related('user').order_by(
                '-timestamp')[:15]

    # Transfer stats
    pending_transfers = Transfer.objects.filter(status='PENDING').count()
    validated_transfers = Transfer.objects.filter(status='VALIDATED').count()
    completed_transfers = Transfer.objects.filter(status='COMPLETED').count()

    # Recent transfers
    recent_transfers = Transfer.objects.select_related('agent').order_by('-created_at')[:5]

    # Stock summary
    stocks = Stock.objects.all()

    # Commission statistics
    total_commissions = CommissionDistribution.objects.aggregate(
            total_paid=Sum('total_commission'),
            total_to_agents=Sum('declaring_agent_amount'),
            total_to_managers=Sum('manager_amount')
    )

    # Recent commission distributions
    recent_commissions = CommissionDistribution.objects.select_related(
            'transfer', 'agent', 'config_used'
    ).order_by('-created_at')[:5]

    context = {
        'total_agents': total_agents,
        'total_managers': total_managers,
        'recent_activities': recent_activities,
        'pending_transfers': pending_transfers,
        'validated_transfers': validated_transfers,
        'completed_transfers': completed_transfers,
        'recent_transfers': recent_transfers,
        'stocks': stocks,
        'total_commissions': total_commissions,
        'recent_commissions': recent_commissions,
    }

    return render(request, 'users/manager_dashboard.html', context)


@login_required
def agent_dashboard(request):
    """Dashboard for agents"""
    if not request.user.is_agent():
        return HttpResponseForbidden("Access denied")

    # Import here to avoid circular imports
    from transfers.models import Transfer, CommissionDistribution

    # Agents can only see their own data
    my_activities = UserActivity.objects.filter(user=request.user).order_by('-timestamp')[:10]
    my_transfers = Transfer.objects.filter(agent=request.user).order_by('-created_at')[:10]

    # Transfer stats for this agent
    my_transfer_stats = Transfer.objects.filter(agent=request.user).aggregate(
            pending=Count('id', filter=Q(status='PENDING')),
            validated=Count('id', filter=Q(status='VALIDATED')),
            completed=Count('id', filter=Q(status='COMPLETED')),
            total=Count('id')
    )

    # Commission earnings for this agent
    my_commissions = CommissionDistribution.objects.filter(agent=request.user).select_related('transfer', 'config_used')
    total_commission_earned = my_commissions.aggregate(
            total=models.Sum('declaring_agent_amount')
    )['total'] or 0

    # Recent commission earnings
    recent_commissions = my_commissions.order_by('-created_at')[:5]

    context = {
        'my_activities': my_activities,
        'my_transfers': my_transfers,
        'my_transfer_stats': my_transfer_stats,
        'total_commission_earned': total_commission_earned,
        'recent_commissions': recent_commissions,
    }

    return render(request, 'users/agent_dashboard.html', context)


@login_required
def user_list(request):
    """List all users - managers only"""
    if not request.user.can_manage_users():
        return HttpResponseForbidden("Access denied")

    # Hide superusers from managers
    if request.user.is_superuser:
        users = User.objects.all().order_by('user_type', 'username')
    else:
        users = User.objects.filter(is_superuser=False).order_by('user_type', 'username')

    return render(request, 'users/user_list.html', {'users': users})


@login_required
def create_user(request):
    """Create new user - managers only"""
    if not request.user.can_manage_users():
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            logger.info(f"Creating user with form data: {form.cleaned_data}")

            user = form.save(commit=False)
            user.created_by = request.user
            # DON'T set unusable password - let them have a temp one
            user.set_password('TempPass123!')  # They'll change it via email link

            try:
                user.full_clean()
                user.save()
                logger.info(f"User {user.username} created successfully")

                # Generate password reset token
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                reset_link = request.build_absolute_uri(
                        reverse('setup_password', kwargs={'uidb64': uid, 'token': token})
                )

                logger.info(f"Generated reset link for {user.username}: {reset_link}")

                # Try sending email with proper error handling
                try:
                    # Import and use your context processor
                    from users.context_processors import site_info

                    # Get site context (pass None since we don't need request)
                    site_context = site_info(None)

                    # Render the email template
                    email_html = render_to_string('emails/password_setup.html', {
                        'user': user,
                        'reset_link': reset_link,
                        'support_email': settings.DEFAULT_FROM_EMAIL,
                        'site_name': site_context['site_name'],
                        'site_name_formal': site_context['site_name_formal'],
                    })

                    # Dynamic subject line
                    subject = f'Set Your Password - {site_context["site_name_formal"]}' if site_context[
                                                                                               'site_name_formal'] != 'Our Platform' else 'Set Your Password'

                    send_mail(
                            subject=subject,
                            message=f'Set your password here: {reset_link}',
                            html_message=email_html,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[user.email],
                            fail_silently=False,
                    )

                except Exception as email_error:
                    logger.error(f"Failed to send email to {user.email}: {email_error}")
                    # Don't fail the user creation just because email failed
                    messages.warning(request,
                                     f'User {user.username} created but email failed to send. '
                                     f'Please set their password manually.')

                # Log the activity
                log_user_activity(
                        request.user,
                        'user_created',
                        {'created_user': user.username, 'user_type': user.user_type},
                        request
                )

                messages.success(request, f'User {user.username} created successfully.')
                return redirect('user_list')

            except ValidationError as e:
                logger.error(f"Validation error creating user: {e}")
                for field, errors in e.message_dict.items():
                    if field == '__all__':
                        form.add_error(None, errors)
                    else:
                        for error in errors:
                            form.add_error(field, error)
            except Exception as e:
                logger.error(f"Unexpected error creating user: {e}")
                messages.error(request, f"Failed to create user: {e}")
        else:
            print(f"Form is not valid: {form.errors}")
            logger.warning(f"Form errors: {form.errors}")
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserCreationForm()

    return render(request, 'users/create_user.html', {'form': form})


def setup_password(request, uidb64, token):
    """Allow new users to set their password"""
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Password set successfully! You can now log in.')
                return redirect('login')
        else:
            form = SetPasswordForm(user)

        # Get site name from settings or use fallback
        site_name = getattr(settings, 'SITE_NAME', '').strip()
        if not site_name:
            site_name = 'our platform'
            site_name_formal = 'Our Platform'
        else:
            site_name_formal = site_name

        return render(request, 'users/setup_password.html', {
            'form': form,
            'user': user,
            'site_name': site_name,
            'site_name_formal': site_name_formal,
        })
    else:
        messages.error(request, 'Invalid or expired password setup link.')
        return redirect('login')


@login_required
def update_user(request, user_id):
    """Update user - managers only"""
    if not request.user.can_manage_users():
        return HttpResponseForbidden("Access denied")

    # Prevent managers from editing superusers
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, is_superuser=False)

    if request.method == 'POST':
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            updated_user = form.save()

            log_user_activity(
                    request.user,
                    'user_updated',
                    {'updated_user': updated_user.username},
                    request
            )

            messages.success(request, f'User {updated_user.username} updated successfully')
            return redirect('user_list')
    else:
        form = UserUpdateForm(instance=user)

    return render(request, 'users/update_user.html', {'form': form, 'user_obj': user})


@login_required
@require_http_methods(["POST"])
def toggle_user_status(request, user_id):
    """Toggle user active status - managers only"""
    print("Toggling user status for user ID:", user_id)
    if not request.user.can_manage_users():
        print("Access denied for user:", request.user.username)
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Prevent managers from toggling superuser status
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, is_superuser=False)

    # Don't allow managers to deactivate themselves
    if user == request.user:
        return JsonResponse({'error': 'Cannot deactivate your own account'}, status=400)

    # Toggle the active status
    print(f"Toggling user status for {user.username} (current status: {'active' if user.is_active_user else 'inactive'})")
    user.is_active_user = not user.is_active_user
    user.save()

    log_user_activity(
            request.user,
            'user_status_changed',
            {
                'target_user': user.username,
                'new_status': 'active' if user.is_active_user else 'inactive'
            },
            request
    )

    return JsonResponse({
        'success': True,
        'new_status': user.is_active_user,
        'status_text': 'Active' if user.is_active_user else 'Inactive'
    })


@login_required
def profile(request):
    """View/edit own profile"""
    if request.method == 'POST':
        # Basic fields all users can update
        phone = request.POST.get('phone', '').strip()
        location = request.POST.get('location', '').strip()

        request.user.phone = phone
        request.user.location = location

        # Additional fields only managers/superusers can update
        if request.user.is_manager() or request.user.is_superuser:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()

            if first_name:
                request.user.first_name = first_name
            if last_name:
                request.user.last_name = last_name
            if email:
                request.user.email = email

        request.user.save()

        log_user_activity(request.user, 'profile_updated', request=request)
        messages.success(request, 'Profile updated successfully')

        return redirect('profile')

    return render(request, 'users/profile.html')


@login_required
@require_http_methods(["POST"])
def delete_user(request, user_id):
    """Delete user - managers only"""
    print("Deleting user ID:", user_id)
    if not request.user.can_manage_users():
        print("Access denied for user:", request.user.username)
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Prevent managers from deleting superusers
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, is_superuser=False)

    # Don't allow managers to delete themselves
    if user == request.user:
        return JsonResponse({'error': 'Cannot delete your own account'}, status=400)

    username = user.username
    print(f"Deleting user: {username}")

    log_user_activity(
            request.user,
            'user_deleted',
            {
                'deleted_user': username,
                'user_type': user.user_type
            },
            request
    )

    user.delete()

    return JsonResponse({
        'success': True,
        'message': f'User {username} deleted successfully'
    })
