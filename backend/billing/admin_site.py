from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from rest_framework.exceptions import Throttled


class PlatformLoginForm(AdminAuthenticationForm):
    def clean(self):
        from .auth import rate_limit
        try:
            rate_limit('platform-login:service', self.request.META.get('REMOTE_ADDR', ''), limit=300)
            rate_limit('platform-login', str(self.cleaned_data.get('username', '')).strip().casefold()[:254])
        except Throttled:
            raise ValidationError('Too many administrator sign-in attempts. Try again later.')
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser or user.must_change_password:
            raise ValidationError('Use an authorized platform administrator account with a personal password.')


class PlatformAdminSite(AdminSite):
    login_form = PlatformLoginForm
    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser and not request.user.must_change_password
