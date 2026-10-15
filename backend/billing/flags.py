from rest_framework.exceptions import PermissionDenied
from .models import FeatureFlag

def require_feature(key):
    if not FeatureFlag.objects.filter(key=key, enabled=True).exists():
        raise PermissionDenied('This feature is temporarily disabled by the platform administrator.')
