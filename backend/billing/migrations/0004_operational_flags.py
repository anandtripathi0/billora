from django.db import migrations

def seed(apps, schema_editor):
    Flag=apps.get_model('billing','FeatureFlag')
    for key,description in [('REGISTRATION_ENABLED','Allow new businesses to register.'),('CSV_IMPORT_ENABLED','Allow product CSV imports.'),('INVOICE_SHARING_ENABLED','Allow creation of new invoice sharing links.')]:
        Flag.objects.get_or_create(key=key,defaults={'enabled':True,'description':description})

class Migration(migrations.Migration):
    dependencies=[('billing','0003_alter_user_username')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
