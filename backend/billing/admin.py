from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from .admin_accounts import AccountAssistanceForm
from rest_framework.exceptions import Throttled
from . import models as m

admin.site.site_header = 'Billora Platform Administration'
admin.site.site_title = 'Billora Admin'
@admin.register(m.User)
class PlatformUserAdmin(UserAdmin):
    list_display = ['username', 'login_mobile', 'is_active', 'must_change_password', 'account_assistance']
    search_fields = ['username', 'email', 'mobile', 'login_mobile', 'membership__business__name']
    fieldsets = UserAdmin.fieldsets + (('Billora login', {'fields': ('mobile', 'login_mobile', 'legacy_mobile_candidate', 'must_change_password', 'password_reset_at', 'account_assistance')}),)
    readonly_fields = ['password', 'mobile', 'login_mobile', 'legacy_mobile_candidate', 'must_change_password', 'password_reset_at', 'account_assistance']
    def has_module_permission(self, request): return request.user.is_superuser and not request.user.must_change_password
    def has_view_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_change_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_add_permission(self, request): return self.has_module_permission(request)
    def has_delete_permission(self, request, obj=None): return False
    @admin.display(description='Account assistance')
    def account_assistance(self, obj):
        if not obj.pk: return 'Save the account first.'
        return format_html('<a href="{}">Verify mobile / reset password</a>', reverse('admin:billing_user_assist', args=[obj.pk]))
    def get_urls(self):
        return [path('<path:object_id>/assist/', self.admin_site.admin_view(self.assist), name='billing_user_assist')] + super().get_urls()
    def user_change_password(self, request, id, form_url=''):
        if not self.has_change_permission(request): raise PermissionDenied
        return redirect('admin:billing_user_assist', object_id=id)
    @method_decorator(sensitive_post_parameters('admin_password', 'temporary_password', 'confirm_password'))
    def assist(self, request, object_id):
        if not self.has_change_permission(request): raise PermissionDenied
        target = get_object_or_404(m.User, pk=object_id)
        from .auth import rate_limit
        if request.method == 'POST':
            try: rate_limit('admin-assistance', str(request.user.pk), limit=10)
            except Throttled:
                return TemplateResponse(request, 'admin/billing/account_assistance.html', {**self.admin_site.each_context(request), 'title':'Please wait before trying again', 'target':target}, status=429)
        form = AccountAssistanceForm(request.POST or None, actor=request.user, target=target)
        if request.method == 'POST' and form.is_valid():
            try: form.save()
            except IntegrityError: form.add_error(None, 'That login number was assigned to another account. No changes were saved.')
            else:
                self.message_user(request, 'Account updated and audited. Deliver any temporary password privately after verification; it expires in 24 hours and must be replaced at first sign-in.', level=messages.SUCCESS)
                return redirect('admin:billing_user_change', object_id=target.pk)
        return TemplateResponse(request, 'admin/billing/account_assistance.html', {**self.admin_site.each_context(request), 'title':'Verified account assistance', 'target':target, 'form':form})

@admin.register(m.Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    search_fields = ['name']
    readonly_fields = ['next_invoice_number']

for model in [m.BusinessSettings, m.Membership, m.Category, m.Product, m.Customer, m.SubscriptionPlan, m.Subscription, m.FeatureFlag]:
    admin.site.register(model)

class ImmutableAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

for model in [m.Invoice, m.InvoiceItem, m.Payment, m.SharingToken, m.MessageLog, m.AuditLog, m.SubscriptionPayment]:
    admin.site.register(model, ImmutableAdmin)
from . import mobile_admin  # noqa: F401 - register native device audit views
