from rest_framework.test import APIClient


class HTTPSAPIClient(APIClient):
    """Match HTTPS requests forwarded by the production TLS proxy, including workers."""

    def __init__(self, *args, **defaults):
        defaults.setdefault('HTTP_X_FORWARDED_PROTO', 'https')
        super().__init__(*args, **defaults)
