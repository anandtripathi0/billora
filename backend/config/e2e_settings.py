import os
if os.environ.get('BILLORA_E2E_ONLY') != 'true':
    raise RuntimeError('This test-only configuration requires BILLORA_E2E_ONLY=true.')
os.environ.setdefault('DEBUG','true')
from .settings import *
TESTING = True
DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR / '.e2e.sqlite3'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
STORAGES = {'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}
