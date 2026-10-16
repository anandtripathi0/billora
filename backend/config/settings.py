import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')
load_dotenv(BASE_DIR / '.env')

def flag(name, default=False):
    return os.environ.get(name, str(default)).lower() == 'true'

DEBUG = flag('DEBUG')
TESTING = os.environ.get('DJANGO_SETTINGS_MODULE') == 'config.test_settings'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = 'development-only-change-before-deploying-billora'
    else:
        raise ImproperlyConfigured('Set DJANGO_SECRET_KEY before starting Billora.')
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,backend').split(',')
render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if render_host:
    ALLOWED_HOSTS.append(render_host)
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000').rstrip('/')
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', FRONTEND_URL).split(',')
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
CORS_ALLOW_CREDENTIALS = True
INSTALLED_APPS = [
    'billing.admin_config.BilloraAdminConfig', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'corsheaders', 'rest_framework', 'billing',
]
MIDDLEWARE = [
    'billing.timing.TimingMiddleware',
    'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True,
              'OPTIONS': {'context_processors': ['django.template.context_processors.request',
              'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
database_url = os.environ.get('DATABASE_URL', '')
if not database_url and not (DEBUG or TESTING):
    raise ImproperlyConfigured('DATABASE_URL must point to PostgreSQL.')
DATABASES = {'default': dj_database_url.parse(database_url or 'postgresql://billora:billora@localhost:5432/billora', conn_max_age=0)}
if DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise ImproperlyConfigured('Billora requires PostgreSQL. SQLite is only used by isolated unit tests.')
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
DATABASES['default'].setdefault('OPTIONS', {})['connect_timeout'] = 10
if flag('DB_POOL_ENABLED', True):
    # Reuse TLS connections across request threads, including the local shop server.
    DATABASES['default']['OPTIONS']['pool'] = {'min_size': 0, 'max_size': 5, 'timeout': 45, 'max_idle': 300}
if flag('DB_SSL_REQUIRE', not DEBUG and not TESTING):
    DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = 'require'
AUTH_USER_MODEL = 'billing.User'
# Keep existing ModelBackend sessions valid until they expire or sign in again.
AUTHENTICATION_BACKENDS = ['billing.authentication.TenantBackend', 'django.contrib.auth.backends.ModelBackend']
CSRF_FAILURE_VIEW = 'billing.authentication.csrf_failure'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher', 'django.contrib.auth.hashers.PBKDF2PasswordHasher']
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['billing.authentication.CSRFSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination', 'PAGE_SIZE': 25,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_FILTER_BACKENDS': ['rest_framework.filters.SearchFilter'],
    'EXCEPTION_HANDLER': 'billing.exceptions.api_exception_handler',
}
LANGUAGE_CODE = 'en-in'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG and not TESTING
CSRF_COOKIE_SECURE = not DEBUG and not TESTING
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = flag('SECURE_SSL_REDIRECT', not DEBUG and not TESTING)
SECURE_HSTS_SECONDS = 31536000 if not DEBUG and not TESTING else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
BILLING_ENABLED = flag('BILLING_ENABLED')
AUTOMATIC_WHATSAPP_ENABLED = False  # Deliberately unavailable until a verified provider + durable worker exist.
LOGGING = {'version': 1, 'disable_existing_loggers': False,
    'filters': {'safe_request': {'()':'billing.timing.SafeRequestLog'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'filters':['safe_request']}},
    'loggers': {name: {'handlers':['console'], 'level':'INFO', 'propagate':False}
        for name in ['django.server', 'django.request', 'django.security.csrf']},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')}}
