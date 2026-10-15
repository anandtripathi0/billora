from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.exceptions import PermissionDenied

def tenant(request):
    membership = getattr(request.user, 'membership', None)
    if not membership: raise PermissionDenied('A business membership is required.')
    if not membership.business.is_active: raise PermissionDenied('Your business is suspended. Contact the platform administrator.')
    return membership.business

class TenantPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated: return False
        tenant(request)
        if request.method in SAFE_METHODS: return True
        return request.user.membership.role in getattr(view, 'write_roles', ['owner', 'manager', 'cashier'])

class SuperAdminPermission(BasePermission):
    def has_permission(self, request, view): return request.user.is_authenticated and request.user.is_superuser
