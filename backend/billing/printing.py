"""HTTPS pull queue. Printer credentials never enter frontend JavaScript."""
import hashlib
import secrets
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from . import models as m
from .permissions import TenantPermission, tenant
from .auth import rate_limit
from .services import upi_uri, audit
from .pdf import qr_data

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def receipt_data(invoice):
    uri = upi_uri(invoice)
    return {
        'id': str(invoice.pk), 'number': invoice.number, 'date': str(invoice.date), 'revision': invoice.revision,
        'business': {k: invoice.business_snapshot.get(k, '') for k in ['name','mobile','address','gstin','invoice_footer','upi_id','upi_payee_name']},
        'customer': {key: invoice.customer_snapshot.get(key, '') for key in ['name', 'mobile']}, 'status': invoice.status, 'cancellation_reason': invoice.cancellation_reason,
        'items': [{'price_includes_tax':item.price_includes_tax, **{k: str(getattr(item, k)) for k in ['description','quantity','unit','unit_price','subtotal','discount','cgst','sgst','igst','total']}} for item in invoice.items.order_by('pk')],
        **{k: str(getattr(invoice, k)) for k in ['subtotal','discount','cgst','sgst','igst','total','paid_amount','balance']},
        'refunded': str(invoice.paid_amount if invoice.cancelled_at else 0),
        'upi_uri': uri, 'qr_image': qr_data(uri),
    }

def device_data(device):
    return {'id': str(device.pk), 'name': device.name, 'width': device.width, 'paired': bool(device.token_digest),
        'online': bool(device.last_seen and device.last_seen > timezone.now()-timedelta(seconds=20)), 'last_seen': device.last_seen}

def job_data(job):
    return {'id': str(job.pk), 'invoice': str(job.invoice_id), 'device': str(job.device_id), 'width': job.width,
            'status': job.status, 'detail': job.detail}

def expire_jobs(business):
    m.PrintJob.objects.filter(business=business, status='processing', claimed_at__lt=timezone.now()-timedelta(minutes=2)).update(
        status='uncertain', detail='Agent acknowledgement missing. Check the paper before requesting another copy.')
    m.PrintJob.objects.filter(business=business, status='queued', created_at__lt=timezone.now()-timedelta(seconds=30)).update(
        status='failed', detail='Agent did not collect the job within 30 seconds. No receipt was sent.')

class DeviceInput(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    width = serializers.ChoiceField(choices=[58,80], default=80)

class UnpairInput(serializers.Serializer):
    id = serializers.UUIDField()

class DevicesView(APIView):
    permission_classes = [TenantPermission]
    write_roles = ['owner','manager']
    def get(self, request):
        return Response([device_data(d) for d in m.PrintDevice.objects.filter(business=tenant(request), is_active=True).order_by('created_at')])
    def post(self, request):
        rate_limit('printer-pair-create', str(request.user.pk), limit=10, seconds=600)
        data = DeviceInput(data=request.data); data.is_valid(raise_exception=True)
        code = secrets.token_urlsafe(24)
        device = m.PrintDevice.objects.create(business=tenant(request), pairing_digest=digest(code), pairing_expires_at=timezone.now()+timedelta(minutes=10), **data.validated_data)
        audit(request.user, tenant(request), 'printer.pairing_created', device.pk)
        return Response({**device_data(device), 'pairing_code': code, 'expires_at': device.pairing_expires_at}, status=201)
    def delete(self, request):
        data=UnpairInput(data=request.data); data.is_valid(raise_exception=True)
        with transaction.atomic():
            business = m.Business.objects.select_for_update().get(pk=tenant(request).pk)
            device = get_object_or_404(m.PrintDevice, pk=data.validated_data['id'], business=business)
            device.is_active=False; device.token_digest=''; device.pairing_digest=''; device.save()
            m.PrintJob.objects.filter(device=device, status='queued').update(status='cancelled', detail='Printer unpaired.')
            audit(request.user, business, 'printer.unpaired', device.pk)
        return Response({'detail':'Printer unpaired. A job already sent to the printer cannot be recalled.'})

class PairInput(serializers.Serializer):
    code = serializers.CharField(max_length=100)

class AgentPairView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    def post(self, request):
        # Pairing is a high-entropy, expiring one-use capability, exchanged only by the CLI.
        if request.headers.get('Origin'): raise AuthenticationFailed('Pair from the local agent, not a website.')
        rate_limit('printer-pair', request.META.get('REMOTE_ADDR',''), limit=30, seconds=600)
        data=PairInput(data=request.data); data.is_valid(raise_exception=True)
        with transaction.atomic():
            device = get_object_or_404(m.PrintDevice.objects.select_for_update(), pairing_digest=digest(data.validated_data['code']),
                pairing_expires_at__gt=timezone.now(), is_active=True, business__is_active=True)
            token=secrets.token_urlsafe(48)
            device.token_digest=digest(token); device.pairing_digest=''; device.save()
        return Response({'device_id':str(device.pk), 'token':token, 'width':device.width})

class AgentAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if request.headers.get('Origin'): raise AuthenticationFailed('Browser requests are not accepted by the agent API.')
        header=request.headers.get('Authorization','')
        if not header.startswith('Bearer ') or len(header)>150: raise AuthenticationFailed('Agent token required.')
        device=m.PrintDevice.objects.filter(token_digest=digest(header[7:]), is_active=True, business__is_active=True).first()
        if not device: raise AuthenticationFailed('Printer has been unpaired or its token is invalid.')
        return (None, device)
    def authenticate_header(self, request): return 'Bearer'

class JobInput(serializers.Serializer):
    invoice=serializers.UUIDField()
    device=serializers.UUIDField()
    idempotency_key=serializers.UUIDField()
    width=serializers.ChoiceField(choices=[58,80])

class JobsView(APIView):
    permission_classes=[TenantPermission]
    def get(self, request, job_id):
        business=tenant(request); expire_jobs(business)
        return Response(job_data(get_object_or_404(m.PrintJob, pk=job_id, business=business)))
    def post(self, request):
        data=JobInput(data=request.data); data.is_valid(raise_exception=True); d=data.validated_data
        with transaction.atomic():
            business=m.Business.objects.select_for_update().get(pk=tenant(request).pk)
            expire_jobs(business)
            existing=m.PrintJob.objects.filter(business=business, idempotency_key=d['idempotency_key']).first()
            if existing:
                if (existing.invoice_id,existing.device_id,existing.width)!=(d['invoice'],d['device'],d['width']): raise ValidationError('Print key already used for another job.')
                return Response(job_data(existing))
            invoice=get_object_or_404(m.Invoice, pk=d['invoice'], business=business)
            device=get_object_or_404(m.PrintDevice, pk=d['device'], business=business, is_active=True)
            if invoice.cancelled_at: raise ValidationError('Use browser printing for cancelled invoice records.')
            if not device_data(device)['online']: return Response({'detail':'Local agent is offline. Start it or use browser printing.'}, status=503)
            job=m.PrintJob.objects.create(business=business, invoice=invoice, device=device, idempotency_key=d['idempotency_key'], width=d['width'])
            audit(request.user,business,'print.queued',job.pk)
        return Response(job_data(job), status=201)

class AgentPollView(APIView):
    authentication_classes=[AgentAuthentication]
    permission_classes=[AllowAny]
    def post(self, request):
        device=request.auth
        with transaction.atomic():
            get_object_or_404(m.Business.objects.select_for_update(), pk=device.business_id, is_active=True)
            device=get_object_or_404(m.PrintDevice.objects.select_for_update(), pk=device.pk, is_active=True)
            device.last_seen=timezone.now(); device.save(update_fields=['last_seen'])
            expire_jobs(device.business_id)
            # An unacknowledged job is never automatically sent to the printer a second time.
            job=m.PrintJob.objects.filter(device=device,status='queued').select_related('invoice').order_by('created_at').first()
            if not job: return Response({'job':None})
            if job.invoice.cancelled_at:
                job.status='cancelled'; job.save(update_fields=['status']); return Response({'job':None})
            receipt=receipt_data(job.invoice)
            job.status='processing'; job.claimed_at=timezone.now(); job.save(update_fields=['status','claimed_at'])
            return Response({'job':{**job_data(job), 'receipt':receipt}})

class AckInput(serializers.Serializer):
    job=serializers.UUIDField()
    status=serializers.ChoiceField(choices=['spooled','failed','uncertain'])
    detail=serializers.CharField(max_length=300, allow_blank=True, default='')

class AgentAckView(APIView):
    authentication_classes=[AgentAuthentication]
    permission_classes=[AllowAny]
    def post(self, request):
        data=AckInput(data=request.data); data.is_valid(raise_exception=True); d=data.validated_data
        with transaction.atomic():
            job=get_object_or_404(m.PrintJob.objects.select_for_update(), pk=d['job'], device=request.auth)
            if job.status in ['processing','uncertain']:
                job.status=d['status']; job.detail=d['detail']; job.finished_at=timezone.now(); job.save()
        return Response(job_data(job))
