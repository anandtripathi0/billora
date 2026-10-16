import hashlib
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.db import transaction, IntegrityError, connection
from django.middleware.csrf import get_token
from django.utils import timezone
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
from .validation import mobile as normalize_mobile

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
        if action == 'register': require_feature('REGISTRATION_ENABLED')
        if action in ['login', 'register']:
            rate_limit(action + ':service', request.META.get('REMOTE_ADDR', ''), limit=300)
            mobile = normalize_mobile(request.data.get('mobile', ''))
            rate_limit(action, mobile, limit=10)
        if action == 'register':
            serializer = RegisterSerializer(data=request.data); serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            with span('password_ms'):
                user = User(username=f'account-{uuid.uuid4().hex}', mobile=data['mobile'], login_mobile=data['mobile'])
                user.set_password(data['password'])
            try:
                with transaction.atomic():
                    user.save()
                    business = Business.objects.create(name=data['store_name'], mobile=data['mobile'])
                    BusinessSettings.objects.create(business=business)
                    Membership.objects.create(user=user, business=business, role='owner')
                    audit(user, business, 'account.registered', user.pk)
            except IntegrityError: raise ValidationError('An account already uses this mobile number. Sign in or contact support.')
            login(request, user, backend='billing.authentication.TenantBackend')
            return Response({**me_data(user), 'csrfToken':get_token(request)}, status=201)
        if action == 'login':
            password = request.data.get('password', '')
            if not isinstance(password, str) or len(password) > 128: raise ValidationError('Invalid mobile number or password.')
            user = authenticate(request, mobile=mobile, password=password)
            if not user: return Response({'detail': 'Invalid mobile number or password. For an older account, contact your administrator to link your login mobile.'}, status=400)
            if user.must_change_password and user.password_reset_at and user.password_reset_at < timezone.now() - timedelta(hours=24):
                return Response({'detail': 'Your temporary password has expired. Contact your administrator.'}, status=400)
            membership = getattr(user, 'membership', None)
            if membership and not membership.business.is_active: return Response({'detail': 'Your business is suspended.'}, status=403)
            login(request, user)
            audit(user, membership.business if membership else None, 'auth.login', user.pk)
            return Response({**me_data(user), 'csrfToken':get_token(request)})
        if action == 'logout':
            logout(request); return Response({'detail': 'Signed out.', 'csrfToken':get_token(request)})
        if action in ['forgot-password', 'reset-password']:
            return Response({'detail': 'Forgot your password? Contact Billora Support/Admin to reset your password.'}, status=410)
        return Response({'detail': 'Unknown authentication action.'}, status=404)

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True); serializer.save()
        return Response(me_data(request.user))
    def post(self, request):
        rate_limit('change-password', str(request.user.pk))
        password = request.data.get('password', '')
        current = request.data.get('old_password', '')
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise ValidationError('Use a new password between 10 and 128 characters.')
        if password != request.data.get('confirm_password'):
            raise ValidationError('New passwords do not match.')
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if not isinstance(current, str) or not user.check_password(current):
                raise ValidationError('Current password is incorrect.')
            if user.must_change_password and user.password_reset_at and user.password_reset_at < timezone.now() - timedelta(hours=24):
                raise ValidationError('Your temporary password has expired. Contact your administrator.')
            if user.check_password(password): raise ValidationError('Choose a different new password.')
            validate_password(password, user)
            user.set_password(password)
            user.must_change_password = False
            user.password_reset_at = None
            user.save(update_fields=['password', 'must_change_password', 'password_reset_at'])
            audit(user, getattr(getattr(user, 'membership', None), 'business', None), 'auth.password_changed', user.pk)
        update_session_auth_hash(request, user)
        return Response({'detail': 'Password changed. Other sessions have been signed out.', 'csrfToken': get_token(request)})
