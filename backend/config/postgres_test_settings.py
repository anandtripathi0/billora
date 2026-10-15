"""Real PostgreSQL concurrency tests in a uniquely named disposable database."""
import os
import re
from .settings import *

name = os.environ.get('BILLORA_TEST_DATABASE', '')
if not re.fullmatch(r'billora_test_[a-f0-9]{12}', name):
    raise RuntimeError('Set BILLORA_TEST_DATABASE to billora_test_ plus 12 random hex characters.')
TESTING = True
DATABASES['default']['TEST'] = {'NAME': name}
DATABASES['default']['OPTIONS'].pop('pool', None)  # Disposable databases must release every connection on teardown.
# Neon transaction pooling retains server connections after test clients close,
# preventing Django's DROP DATABASE cleanup. Use its matching direct endpoint
# only for these disposable tests; normal app traffic continues using the pool.
host = DATABASES['default']['HOST']
if host.endswith('.neon.tech') and '-pooler.' in host:
    DATABASES['default']['HOST'] = host.replace('-pooler.', '.', 1)
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
