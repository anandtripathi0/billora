import hashlib
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import MobileDevice
from .auth import rate_limit
from .serializers import BusinessSerializer
from .validation import mobile
from .services import audit


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class DeviceAuthentication(BaseAuthentication):
    def authenticate_header(self, request): return 'Bearer'
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b'bearer':
            raise AuthenticationFailed('Activate this device online.')
        try: token = parts[1].decode('ascii')
        except UnicodeDecodeError: raise AuthenticationFailed('Invalid device session.')
        device = MobileDevice.objects.select_related('user__membership__business__settings').filter(token_digest=digest(token)).first()
        if not device or device.revoked_at or device.expires_at <= timezone.now():
            raise AuthenticationFailed('Device session expired or revoked. Sign in online; pending bills remain on this device.')
        user = device.user
        membership = getattr(user, 'membership', None)
        if (not user.is_active or user.must_change_password or not membership or
            membership.business_id != device.business_id or not membership.business.is_active or
            not secrets.compare_digest(device.password_stamp, user.get_session_auth_hash())):
            raise AuthenticationFailed('Device authorization changed. Sign in again online.')
        return user, device


class DeviceLogin(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    def post(self, request):
        if not settings.DEBUG and not settings.TESTING and not request.is_secure():
            raise PermissionDenied('HTTPS is required.')
        number = mobile(request.data.get('mobile', ''))
        rate_limit('mobile-login:ip', request.META.get('REMOTE_ADDR', ''), 100)
        rate_limit('mobile-login', number, 10)
        password = request.data.get('password', '')
        if not isinstance(password, str) or not 1 <= len(password) <= 128: raise ValidationError('Invalid credentials.')
        user = authenticate(request, mobile=number, password=password)
        if not user: raise AuthenticationFailed('Invalid mobile number or password.')
        member = getattr(user, 'membership', None)
        if user.must_change_password:
            raise PermissionDenied('Change your temporary password on the Billora website before activating a phone.')
        if not member or not member.business.is_active: raise PermissionDenied('Active business membership required.')
        raw = secrets.token_urlsafe(48)
        device_id = request.data.get('device_id')
        device = None
        if device_id:
            from uuid import UUID
            try: device_id = UUID(str(device_id))
            except ValueError: raise ValidationError('Invalid device identity.')
            device = MobileDevice.objects.filter(pk=device_id, user=user, business=member.business).first()
            if not device: raise PermissionDenied('This local database belongs to a different account.')
        values = dict(token_digest=digest(raw), password_stamp=user.get_session_auth_hash(),
                      expires_at=timezone.now() + timedelta(days=30), revoked_at=None)
        if device:
            for key, value in values.items(): setattr(device, key, value)
            device.save(update_fields=list(values))
        else:
            name = str(request.data.get('name', 'Android phone')).strip()[:80]
            device = MobileDevice.objects.create(user=user, business=member.business, name=name, **values)
        audit(user, member.business, 'mobile.activated', device.pk)
        return Response({'token': raw, 'device_id': str(device.pk), 'user_id': user.pk,
                         'business': BusinessSerializer(member.business).data, 'role': member.role,
                         'expires_at': device.expires_at.isoformat()})


class DeviceSessions(APIView):
    authentication_classes = [DeviceAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        return Response(list(MobileDevice.objects.filter(user=request.user, business=request.auth.business_id)
                             .values('id', 'name', 'expires_at', 'revoked_at')))
    def post(self, request):
        device_id = request.data.get('device_id', str(request.auth.pk))
        from uuid import UUID
        try: device_id = UUID(str(device_id))
        except ValueError: raise ValidationError('Invalid device identity.')
        changed = MobileDevice.objects.filter(pk=device_id, user=request.user, business=request.auth.business_id).update(revoked_at=timezone.now())
        if not changed: raise ValidationError('Device not found.')
        audit(request.user, request.user.membership.business, 'mobile.revoked', device_id)
        return Response({'revoked': True})
