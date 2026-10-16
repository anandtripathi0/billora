import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from rest_framework.exceptions import ValidationError

def mobile(value):
    digits = re.sub(r'[\s()+-]', '', str(value))
    if len(digits) == 10:
        digits = '91' + digits
    if not re.fullmatch(r'91[6-9][0-9]{9}', digits):
        raise ValidationError('Enter a valid Indian mobile number.')
    return '+' + digits

def gstin(value):
    value = value.strip().upper()
    if value and not re.fullmatch(r'\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]', value):
        raise ValidationError('Enter a valid 15-character GSTIN.')
    return value

def state(value):
    if not re.fullmatch(r'\d{2}', value) or not 1 <= int(value) <= 38:
        raise ValidationError('Use a two-digit Indian state/UT code (01–38).')
    return value

def timezone_name(value):
    try: ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError): raise ValidationError('Unknown timezone.')
    return value
