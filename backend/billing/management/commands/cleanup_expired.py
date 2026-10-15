from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.management import call_command
from billing.models import RateLimit, SharingToken

class Command(BaseCommand):
    help = 'Remove expired rate-limit buckets, old expired sharing tokens and expired sessions.'
    def handle(self, *args, **kwargs):
        RateLimit.objects.filter(reset_at__lt=timezone.now()).delete()
        SharingToken.objects.filter(expires_at__lt=timezone.now()-timedelta(days=30)).delete()
        call_command('clearsessions')
        self.stdout.write('Expired transient records removed. Invoice and audit records preserved.')
