import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from .forms import LoginForm, UserCreationForm, UserUpdateForm
from .models import User, log_user_activity
from .services import (PasswordResetService, UserCreationService, UserProfileService,
                       UserSearchService, UserUpdateService, get_agent_dashboard_data, get_manager_dashboard_data)
from .utils import get_filtered_users

logger = logging.getLogger(__name__)


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

                # Log successful login
                log_user_activity(user, 'connexion_utilisateur', {
                    'methode': 'mdp',
                    'agent_utilise': request.META.get('HTTP_USER_AGENT', '')[:200]
                }, request)

                # Redirect to appropriate dashboard
                return redirect('dashboard')
            else:
                messages.error(request, _('Identifiants invalides ou compte inactif'))

                # Log failed login attempt
                if user:
                    log_user_activity(user, 'echec_connexion', {
                        'raison': 'compte_inactif'
                    }, request)

    else:
        form = LoginForm()

    return render(request, 'users/login.html', {'form': form})


def logout_view(request):
    """Handle user logout"""
    if request.user.is_authenticated:
        # Log logout before actually logging out
        log_user_activity(request.user, 'deconnexion_utilisateur', {}, request)
        logout(request)
        messages.info(request, _('Vous avez été déconnecté avec succès'))

    return redirect('login')


@login_required
def dashboard(request):
    """Main dashboard - redirect based on user type"""
    if request.user.is_superuser or request.user.is_manager():
        logger.info(f"User {request.user.username} redirected to manager dashboard")
        return redirect('manager_dashboard')
    else:
        logger.info(f"User {request.user.username} redirected to agent dashboard")
        return redirect('agent_dashboard')


@login_required
def manager_dashboard(request):
    """Dashboard for managers and superusers"""
    try:
        context = get_manager_dashboard_data(request.user)
        return render(request, 'users/manager_dashboard.html', context)
    except PermissionError as e:
        logger.warning(f"Dashboard access denied for {request.user.username}: {e}")
        return HttpResponseForbidden(_("Accès réfusé"))
    except Exception as e:
        logger.error(f"Manager dashboard error for {request.user.username}: {e}", exc_info=True)
        messages.error(request, _("Une erreur est survenue lors du chargement du tableau de bord"))
        return render(request, 'users/manager_dashboard.html', {})


@login_required
def agent_dashboard(request):
    """Dashboard for agents"""
    try:
        context = get_agent_dashboard_data(request.user)
        return render(request, 'users/agent_dashboard.html', context)
    except PermissionError as e:
        logger.warning(f"Agent dashboard access denied for {request.user.username}: {e}")
        return HttpResponseForbidden(_("Accès réfusé"))
    except Exception as e:
        logger.error(f"Agent dashboard error for {request.user.username}: {e}", exc_info=True)
        messages.error(request, _("Une erreur est survenue lors du chargement du tableau de bord"))
        return render(request, 'users/agent_dashboard.html', {})


@login_required
def user_list(request):
    """List users with search functionality"""
    if not request.user.can_manage_users():
        return HttpResponseForbidden(_("Accès réfusé"))

    # Handle search
    search_query = request.GET.get('q', '').strip()
    user_type_filter = request.GET.get('type', '').strip()

    if search_query or user_type_filter:
        # Use search service
        search_service = UserSearchService(request.user)
        search_results = search_service.search_users(
                query=search_query,
                user_type=user_type_filter,
                active_only=False,  # Show all users in the admin interface
                limit=100
        )
        users = search_results['users']
        total_count = search_results['total_count']

    else:
        # Get all users based on permissions
        users = get_filtered_users(request.user)
        total_count = users.count()

    context = {
        'users': users,
        'search_query': search_query,
        'user_type_filter': user_type_filter,
        'total_count': total_count,
        'user_types': User.USER_TYPES,
    }

    return render(request, 'users/user_list.html', context)


@login_required
def create_user(request):
    """Create the new user using UserCreationService"""
    if not request.user.can_manage_users():
        return HttpResponseForbidden(_("Accès réfusé"))

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            try:
                # Use service to create user
                service = UserCreationService(request.user)
                user = service.create_user(
                        form.cleaned_data,
                        base_url=request.build_absolute_uri('/')
                )

                # Log the creation
                log_user_activity(request.user, 'utilisateur_créé', {
                    'nouvel_utilisateur': user.username,
                    'type_d_utilisateur': user.user_type,
                    'email': user.email
                }, request)

                messages.success(request, _("L'utilisateur {username} a été créé avec succès").format(
                        username=user.username))
                return redirect('user_list')

            except ValidationError as e:
                for field, errors in e.message_dict.items():
                    form.add_error(field if field != '__all__' else None, str(errors))
            except PermissionError as e:
                logger.warning(f"User creation permission denied: {e}")
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"User creation failed: {e}", exc_info=True)
                messages.error(request, _("Échec de création de l'utilisateur"))
        else:
            messages.error(request, _("Veuillez corriger les erreurs ci-dessous"))
    else:
        form = UserCreationForm()

    return render(request, 'users/create_user.html', {'form': form})


def setup_password(request, uidb64, token):
    """Allow new users to set their password"""
    # Validate token and get user
    user = PasswordResetService.validate_reset_token(uidb64, token)

    if user is None:
        messages.error(request, _('Le lien de configuration du mot de passe est invalide ou a expiré.'))
        return redirect('login')

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()

            # Log password setup
            log_user_activity(user, 'mdp_configuré', {
                'méthode': 'lien_email'
            }, request)

            messages.success(request, _('Votre mot de passe a été configuré avec succès. Vous pouvez maintenant vous connecter.'))
            return redirect('login')
    else:
        form = SetPasswordForm(user)

    # Get site info for the template
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


@login_required
def update_user(request, user_id):
    """Update user using UserUpdateService"""
    if not request.user.can_manage_users():
        return HttpResponseForbidden(_("Accès réfusé"))

    # Get user based on permissions
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, is_superuser=False)

    if request.method == 'POST':
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            try:
                # Use service to update user
                service = UserUpdateService(request.user)
                updated_user = service.update_user(user, form.cleaned_data)

                # Log the update
                log_user_activity(request.user, 'utilisateur_modifié', {
                    'utilisateur_modifié': updated_user.username,
                    'type_utilisateur': updated_user.user_type
                }, request)

                messages.success(request, _("L'utilisateur {username} a été mis à jour.").format(
                        username=updated_user.username))
                return redirect('user_list')

            except PermissionError as e:
                logger.warning(f"User update permission denied: {e}")
                messages.error(request, str(e))
            except ValidationError as e:
                # Handle validation errors
                for field, errors in e.message_dict.items():
                    form.add_error(field if field != '__all__' else None, str(errors))
            except Exception as e:
                logger.error(f"User update failed: {e}", exc_info=True)
                messages.error(request, _("Échec de mise à jour de l'utilisateur"))
    else:
        form = UserUpdateForm(instance=user)

    return render(request, 'users/update_user.html', {'form': form, 'user_obj': user})


@login_required
@require_http_methods(["POST"])
def toggle_user_status(request, user_id):
    """Toggle user active status using UserUpdateService"""
    if not request.user.can_manage_users():
        return JsonResponse({'error': _('Accès réfusé')}, status=403)

    # Get user based on permissions
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, is_superuser=False)

    try:
        # Use service to toggle status
        service = UserUpdateService(request.user)
        new_status = service.toggle_user_status(user)

        # Log the action
        log_user_activity(request.user, 'statut_utilisateur_modifié', {
            'utilisateur_cible': user.username,
            'nouveau_statut': 'actif' if new_status else 'inactif'
        }, request)

        return JsonResponse({
            'success': True,
            'new_status': new_status,
            'status_text': 'Active' if new_status else 'Inactive'
        })

    except PermissionError as e:
        logger.warning(f"Status toggle permission denied: {e}")
        return JsonResponse({'error': str(e)}, status=403)
    except Exception as e:
        logger.error(f"Status toggle failed: {e}", exc_info=True)
        return JsonResponse({'error': _('Une erreur est survenue')}, status=500)


@login_required
@require_http_methods(["POST"])
def delete_user(request, user_id):
    """Delete user using UserUpdateService"""
    if not request.user.can_manage_users():
        return JsonResponse({'error': _('Accès réfusé')}, status=403)

    # Get user based on permissions
    if request.user.is_superuser:
        user = get_object_or_404(User, id=user_id)
    else:
        user = get_object_or_404(User, id=user_id, is_superuser=False)

    try:
        # Use service to delete user
        service = UserUpdateService(request.user)
        deleted_username = service.delete_user(user)

        # Log the deletion
        log_user_activity(request.user, 'suppression_d_utilisateur', {
            'utilisateur_supprimé': deleted_username,
        }, request)

        return JsonResponse({
            'success': True,
            'message': _("L'utilisateur {username} a été supprimé").format(
                    username=deleted_username)
        })

    except PermissionError as e:
        logger.warning(f"User deletion permission denied: {e}")
        return JsonResponse({'error': str(e)}, status=403)
    except Exception as e:
        logger.error(f"User deletion failed: {e}", exc_info=True)
        return JsonResponse({'error': _('Une erreur est survenue')}, status=500)


@login_required
def profile(request):
    """View/edit own profile using UserProfileService"""
    if request.method == 'POST':
        try:
            # Extract profile data from POST
            profile_data = {
                'phone': request.POST.get('phone', '').strip(),
                'location': request.POST.get('location', '').strip(),
            }

            # Additional fields for managers/superusers
            if request.user.is_manager():
                profile_data.update({
                    'first_name': request.POST.get('first_name', '').strip(),
                    'last_name': request.POST.get('last_name', '').strip(),
                    'email': request.POST.get('email', '').strip(),
                })

            # NOTE: No user_type handling here - users can't change their own type

            # Use service to update profile
            service = UserProfileService(request.user)
            service.update_profile(profile_data)

            # Log profile update
            log_user_activity(request.user, 'profil_modifié', {
                'champs_modifiés': list(profile_data.keys())
            }, request)

            messages.success(request, _('Profil mis à jour avec succès'))
            return redirect('profile')

        except Exception as e:
            logger.error(f"Profile update failed for {request.user.username}: {e}", exc_info=True)
            messages.error(request, _('Une erreur est survenue'))

    return render(request, 'users/profile.html')
