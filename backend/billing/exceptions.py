from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler

def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    response = exception_handler(exc, context)
    if response is not None and getattr(exc, 'get_codes', lambda: None)() == 'csrf_failed':
        response.data['code'] = 'csrf_failed'
    return response
