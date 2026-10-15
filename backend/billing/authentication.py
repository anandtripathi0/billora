"""One indexed account lookup with request-local tenant relations."""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied as AuthenticationDenied
from .timing import span

class TenantBackend(ModelBackend):
    def accounts(self):
        return get_user_model().objects.select_related('membership__business__settings')

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None: return None
        user = self.accounts().filter(email__iexact=username).first() if '@' in username else self.accounts().filter(username=username).first()
        with span('password_ms'):
            if user is None:
                # Preserve Django's password-work defense against user enumeration.
                get_user_model()().set_password(password)
            elif user.check_password(password) and self.user_can_authenticate(user):
                return user
        # The legacy backend is retained for loading old sessions, not a second
        # password check or an alternative path around this authentication rule.
        raise AuthenticationDenied()

    def get_user(self, user_id):
        try: user = self.accounts().get(pk=user_id)
        except get_user_model().DoesNotExist: return None
        return user if self.user_can_authenticate(user) else None

class CSRFSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        try: return super().enforce_csrf(request)
        except PermissionDenied:
            raise PermissionDenied('Your security token expired. Please try again.', code='csrf_failed')

def csrf_failure(request, reason=''):
    return JsonResponse({'detail':'Your security token expired. Please try again.', 'code':'csrf_failed'}, status=403)
