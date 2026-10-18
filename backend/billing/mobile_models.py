"""Additive native-device sync tables. Existing financial records remain authoritative."""
import uuid
from django.db import models


class MobileDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey('Business', on_delete=models.PROTECT)
    user = models.ForeignKey('User', on_delete=models.PROTECT)
    name = models.CharField(max_length=80)
    token_digest = models.CharField(max_length=64, unique=True)
    password_stamp = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MobileMapping(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    local_id = models.UUIDField()
    server_id = models.CharField(max_length=64)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'kind', 'local_id'], name='mobile_local_identity'),
                       models.UniqueConstraint(fields=['business', 'kind', 'server_id'], name='mobile_server_identity')]


class MobileOperation(models.Model):
    business = models.ForeignKey('Business', on_delete=models.PROTECT)
    device = models.ForeignKey(MobileDevice, on_delete=models.PROTECT)
    operation_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    payload = models.JSONField()  # Immutable original event, including rejected financial events.
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'operation_id'], name='mobile_operation_once')]


class MobileRecord(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    local_id = models.UUIDField()
    version = models.CharField(max_length=64)
    deleted = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'kind', 'local_id'], name='mobile_current_record')]


class MobileChange(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    local_id = models.UUIDField()
    version = models.CharField(max_length=64)
    data = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=['business', 'id'], name='mobile_change_cursor')]


class MobileNumberRange(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey('Business', on_delete=models.PROTECT)
    device = models.ForeignKey(MobileDevice, on_delete=models.PROTECT)
    fiscal_year = models.PositiveIntegerField()
    start = models.PositiveBigIntegerField()
    end = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
