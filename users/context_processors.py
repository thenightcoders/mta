from django.conf import settings


def site_info(request):
    """Add site information to all templates"""
    site_name = getattr(settings, 'SITE_NAME', '').strip()
    if not site_name:
        site_name = "Transfer d'Argent"
        site_name_formal = 'Our Platform'
    else:
        site_name_formal = site_name

    return {
        'site_name': site_name,
        'site_name_formal': site_name_formal,
    }
