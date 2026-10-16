from django.contrib.admin.apps import AdminConfig


class BilloraAdminConfig(AdminConfig):
    default_site = 'billing.admin_site.PlatformAdminSite'
