import hashlib
import logging
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction, IntegrityError, connection
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, Throttled
from .models import User, Business, BusinessSettings, Membership, RateLimit
from .serializers import RegisterSerializer, UserSerializer, BusinessSerializer
from .services import audit
from .flags import require_feature
from .timing import span

def rate_limit(scope, identity, limit=10, seconds=900):
    key = hashlib.sha256(f'{scope}:{identity}'.encode()).hexdigest()
    if connection.vendor == 'postgresql':
        now = timezone.now()
        # Atomic upsert holds only this bucket's row lock for one statement.
        # The WHERE cap prevents concurrent attempts from exceeding the limit.
        with span('throttle_ms'), connection.cursor() as cursor:
            cursor.execute('''INSERT INTO billing_ratelimit (key, attempts, reset_at) VALUES (%s, 1, %s)
                ON CONFLICT (key) DO UPDATE SET
                attempts = CASE WHEN billing_ratelimit.reset_at <= %s THEN 1 ELSE billing_ratelimit.attempts + 1 END,
                reset_at = CASE WHEN billing_ratelimit.reset_at <= %s THEN EXCLUDED.reset_at ELSE billing_ratelimit.reset_at END
                WHERE billing_ratelimit.reset_at <= %s OR billing_ratelimit.attempts < %s
                RETURNING reset_at''', [key, now + timedelta(seconds=seconds), now, now, now, limit])
            if cursor.fetchone() is not None: return
            cursor.execute('SELECT reset_at FROM billing_ratelimit WHERE key = %s', [key])
            row = cursor.fetchone()
        raise Throttled(wait=max(1, int((row[0] - now).total_seconds())) if row else seconds)
    with transaction.atomic():
        row, _ = RateLimit.objects.get_or_create(key=key, defaults={'reset_at': timezone.now() + timedelta(seconds=seconds)})
        row = RateLimit.objects.select_for_update().get(pk=key)
        if row.reset_at <= timezone.now():
            row.attempts = 0; row.reset_at = timezone.now() + timedelta(seconds=seconds)
        if row.attempts >= limit: raise Throttled(wait=max(1, int((row.reset_at - timezone.now()).total_seconds())))
        row.attempts += 1; row.save()

def me_data(user):
    membership = getattr(user, 'membership', None)
    return {'user': UserSerializer(user).data,
        'business': BusinessSerializer(membership.business).data if membership else None,
        'role': membership.role if membership else 'superadmin',
        'billing_enabled': settings.BILLING_ENABLED, 'automatic_whatsapp_enabled': False}

@method_decorator(csrf_protect, name='dispatch')
class AuthView(APIView):
    permission_classes = [AllowAny]
    def get_authenticators(self):
        # Public bootstrap/auth actions do not need to deserialize an old session.
        if self.kwargs.get('action') in ['csrf', 'login', 'register', 'forgot-password', 'reset-password']:
            return []
        return super().get_authenticators()
    def get(self, request, action):
        if action == 'csrf': return Response({'csrfToken': get_token(request)})
        if action == 'me' and request.user.is_authenticated: return Response(me_data(request.user))
        return Response({'detail': 'Please sign in.'}, status=401)

    def post(self, request, action):
        email = str(request.data.get('email', '')).strip().lower()[:254]
        if action in ['login', 'register', 'forgot-password', 'reset-password']:
            identity = email if action != 'reset-password' else str(request.data.get('uid', ''))[:200]
            rate_limit(action, identity, limit=10)
            rate_limit(action + ':service', request.META.get('REMOTE_ADDR', ''), limit=300)
        if action == 'register':
            require_feature('REGISTRATION_ENABLED')
            serializer = RegisterSerializer(data=request.data); serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            with span('password_ms'):
                user = User(username=data['email'], email=data['email'], first_name=data['owner_name'], mobile=data['mobile'])
                user.set_password(data['password'])
            try:
                with transaction.atomic():
                    user.save()
                    business = Business.objects.create(name=data['business_name'], mobile=data['mobile'])
                    BusinessSettings.objects.create(business=business)
                    Membership.objects.create(user=user, business=business, role='owner')
                    audit(user, business, 'account.registered', user.pk)
            except IntegrityError: raise ValidationError('An account already uses this email.')
            login(request, user, backend='billing.authentication.TenantBackend')
            return Response({**me_data(user), 'csrfToken':get_token(request)}, status=201)
        if action == 'login':
            user = authenticate(request, username=email, password=request.data.get('password', ''))
            if not user: return Response({'detail': 'Invalid email or password.'}, status=400)
            membership = getattr(user, 'membership', None)
            if membership and not membership.business.is_active: return Response({'detail': 'Your business is suspended.'}, status=403)
            login(request, user)
            audit(user, membership.business if membership else None, 'auth.login', user.pk)
            return Response({**me_data(user), 'csrfToken':get_token(request)})
        if action == 'logout':
            logout(request); return Response({'detail': 'Signed out.', 'csrfToken':get_token(request)})
        if action == 'forgot-password':
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk)); token = default_token_generator.make_token(user)
                url = f'{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}'
                try:
                    send_mail('Reset your Billora password', f'Reset your password using this link within one hour:\n{url}\n\nIf you did not request this, ignore this email.', settings.DEFAULT_FROM_EMAIL, [user.email])
                except Exception:
                    logging.getLogger(__name__).error('Password reset email could not be sent; check SMTP configuration.')
            return Response({'detail': 'If this email is registered, a password reset link has been sent.'})
        if action == 'reset-password':
            try: user = User.objects.get(pk=urlsafe_base64_decode(request.data.get('uid', '')).decode(), is_active=True)
            except (ValueError, TypeError, OverflowError, UnicodeDecodeError, User.DoesNotExist): raise ValidationError('Invalid reset link.')
            if not default_token_generator.check_token(user, request.data.get('token', '')): raise ValidationError('This reset link is invalid or expired.')
            password = request.data.get('password', '')
            validate_password(password, user)
            user.set_password(password); user.save(update_fields=['password'])
            audit(user, getattr(getattr(user, 'membership', None), 'business', None), 'auth.password_reset')
            return Response({'detail': 'Password updated. You can sign in now.'})
        return Response({'detail': 'Unknown authentication action.'}, status=404)

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True); serializer.save()
        return Response(me_data(request.user))
    def post(self, request):
        rate_limit('change-password', str(request.user.pk))
        if not request.user.check_password(request.data.get('old_password', '')): raise ValidationError('Current password is incorrect.')
        password = request.data.get('password', '')
        validate_password(password, request.user)
        request.user.set_password(password); request.user.save(update_fields=['password'])
        update_session_auth_hash(request, request.user)
        return Response({'detail': 'Password changed.'})
