from django.db import migrations

def seed(apps, schema_editor):
    Plan = apps.get_model('billing', 'SubscriptionPlan')
    for name, price, interval in [('Basic', '49.00', 'month'), ('Pro', '89.00', 'month'), ('Yearly', '399.00', 'year')]:
        Plan.objects.get_or_create(name=name, defaults={'price':price, 'interval':interval})
    Flag = apps.get_model('billing', 'FeatureFlag')
    for key, description in [('BILLING_ENABLED','Paid collection is not implemented; deployment flag is the source of truth.'), ('AUTOMATIC_WHATSAPP_ENABLED','Automatic messaging is disabled until provider and durable worker integration.')]:
        Flag.objects.get_or_create(key=key, defaults={'enabled':False,'description':description})

class Migration(migrations.Migration):
    dependencies = [('billing','0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
