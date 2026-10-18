"""Read-only device event audit and explicit platform-admin device revocation."""
from django.contrib import admin, messages
from django.utils import timezone
from .models import MobileDevice, MobileOperation, MobileNumberRange
from .services import audit


class ReadOnlyMobileAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields if f.name not in (self.exclude or [])]


@admin.register(MobileDevice)
class MobileDeviceAdmin(ReadOnlyMobileAdmin):
    list_display = ['id', 'business', 'user', 'name', 'expires_at', 'revoked_at']
    exclude = ['token_digest', 'password_stamp']
    actions = ['revoke_devices']
    @admin.action(description='Revoke selected Android device sessions')
    def revoke_devices(self, request, queryset):
        if not request.user.is_superuser: return
        for device in queryset.filter(revoked_at__isnull=True):
            device.revoked_at = timezone.now(); device.save(update_fields=['revoked_at'])
            audit(request.user, device.business, 'mobile.admin_revoked', device.pk)
        self.message_user(request, 'Device sessions revoked. Offline devices detect this when they reconnect; local unlock remains bounded by device-session expiry.', messages.SUCCESS)


@admin.register(MobileOperation)
class MobileOperationAdmin(ReadOnlyMobileAdmin):
    list_display = ['operation_id', 'business', 'device', 'created_at']
    search_fields = ['operation_id']
    list_filter = ['business']
    actions = None


@admin.register(MobileNumberRange)
class MobileNumberRangeAdmin(ReadOnlyMobileAdmin):
    list_display = ['business', 'device', 'fiscal_year', 'start', 'end']
    actions = None
