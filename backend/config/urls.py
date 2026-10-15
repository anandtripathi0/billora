from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from billing.auth import AuthView, ProfileView
from billing import views as v
from billing import printing as p

router = DefaultRouter()
for prefix, view, basename in [
    ('products', v.ProductViewSet, 'products'), ('categories', v.CategoryViewSet, 'categories'),
    ('customers', v.CustomerViewSet, 'customers'), ('invoices', v.InvoiceViewSet, 'invoices'),
    ('payments', v.PaymentViewSet, 'payments'), ('admin/businesses', v.AdminBusinessViewSet, 'admin-businesses'),
    ('admin/plans', v.AdminPlanViewSet, 'admin-plans'), ('admin/flags', v.AdminFlagViewSet, 'admin-flags'),
    ('admin/audit', v.AdminAuditViewSet, 'admin-audit')]: router.register(prefix, view, basename=basename)
urlpatterns = [path('admin/', admin.site.urls), path('api/auth/<str:action>/', AuthView.as_view()),
    path('api/printing/devices/', p.DevicesView.as_view()), path('api/printing/jobs/', p.JobsView.as_view()),
    path('api/printing/jobs/<uuid:job_id>/', p.JobsView.as_view()), path('api/printing/agent/pair/', p.AgentPairView.as_view()),
    path('api/printing/agent/poll/', p.AgentPollView.as_view()), path('api/printing/agent/ack/', p.AgentAckView.as_view()),
    path('api/profile/', ProfileView.as_view()), path('api/settings/', v.SettingsView.as_view()),
    path('api/memberships/', v.MembershipView.as_view()), path('api/dashboard/', v.DashboardView.as_view()),
    path('api/reports/', v.ReportsView.as_view()), path('api/plans/', v.plans), path('api/health/', v.health),
    path('api/admin/overview/', v.AdminOverview.as_view()), path('api/shared/<str:token>/', v.shared_invoice),
    path('api/', include(router.urls))]
