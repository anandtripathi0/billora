from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from . import models as m

admin.site.site_header = 'Billora Platform Administration'
admin.site.site_title = 'Billora Admin'
admin.site.register(m.User, UserAdmin)

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
