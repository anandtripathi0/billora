"""Local profiling only; refuses to touch the application's database."""
import re
from .settings import *

name = os.environ.get('BILLORA_PERF_DATABASE', '')
if not re.fullmatch(r'billora_perf_[a-f0-9]{12}', name):
    raise RuntimeError('BILLORA_PERF_DATABASE must name an isolated billora_perf_<12 hex> database.')
DATABASES['default']['NAME'] = name
DEBUG = False
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CSRF_TRUSTED_ORIGINS = ['http://localhost:3100', 'http://localhost:3000', 'http://testserver']
FRONTEND_URL = 'http://localhost:3100'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
