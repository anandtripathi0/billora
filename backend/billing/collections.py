"""Independent correlated aggregates avoid invoice x payment join multiplication."""
from decimal import Decimal
from django.db.models import OuterRef, Subquery, Sum, Count, Max, DecimalField, IntegerField, F
from django.db.models.functions import Coalesce
from .models import Invoice, Payment, Refund

def customer_totals(customers):
    invoices = Invoice.objects.filter(customer_id=OuterRef('pk'), business_id=OuterRef('business_id'), cancelled_at__isnull=True).order_by().values('customer_id')
    payments = Payment.objects.filter(invoice__customer_id=OuterRef('pk'), business_id=OuterRef('business_id')).order_by().values('invoice__customer_id')
    refunds = Refund.objects.filter(invoice__customer_id=OuterRef('pk'), business_id=OuterRef('business_id')).order_by().values('invoice__customer_id')
    def amount(qs, field):
        return Coalesce(Subquery(qs.annotate(value=Sum(field)).values('value')[:1]), Decimal(0), output_field=DecimalField(max_digits=18, decimal_places=2))
    return customers.annotate(
        purchases=amount(invoices, 'total'), gross_payments=amount(payments, 'amount'), refunds=amount(refunds, 'amount'),
        order_count=Coalesce(Subquery(invoices.annotate(value=Count('pk')).values('value')[:1]), 0, output_field=IntegerField()),
        last_purchase=Subquery(invoices.annotate(value=Max('date')).values('value')[:1]),
    ).annotate(payments_received=F('gross_payments')-F('refunds')).annotate(outstanding=F('purchases')-F('payments_received'))
