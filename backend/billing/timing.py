"""Request timings only: never record SQL, parameters, identities or URL queries."""
import json
import logging
import re
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from django.db import connections

logger = logging.getLogger('billora.performance')
current = ContextVar('billora_timing', default=None)
_seen = False
_lock = threading.Lock()
_started = time.perf_counter()

class SafeRequestLog(logging.Filter):
    """Django's normal access/error logs must not undo the timing log's privacy."""
    def filter(self, record):
        if record.name in {'django.server', 'django.request', 'django.security.csrf'}:
            request = getattr(record, 'request', None)
            match = getattr(request, 'resolver_match', None)
            record.msg = 'HTTP status=%s route=%s request_id=%s'
            record.args = (getattr(record, 'status_code', 'unknown'), getattr(match, 'route', None) or 'see_request_timing', getattr(request, 'billora_request_id', 'see_request_timing'))
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True

@contextmanager
def span(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        stats = current.get()
        if stats is not None:
            stats[name] = stats.get(name, 0) + (time.perf_counter() - start) * 1000

class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _seen
        if not request.path.startswith('/api/'):
            return self.get_response(request)
        start = time.perf_counter()
        with _lock:
            cold = not _seen
            _seen = True
        supplied = request.headers.get('X-Request-ID', '')
        request_id = supplied if re.fullmatch(r'[a-f0-9-]{36}', supplied) else str(uuid.uuid4())
        request.billora_request_id = request_id
        stats = {'db_ms': 0, 'db_queries': 0}
        token = current.set(stats)
        def execute(wrapped, sql, params, many, context):
            before = time.perf_counter()
            try:
                return wrapped(sql, params, many, context)
            finally:
                stats['db_ms'] += (time.perf_counter() - before) * 1000
                stats['db_queries'] += 1
        response = None
        try:
            with ExitStack() as stack:
                for connection in connections.all():
                    stack.enter_context(connection.execute_wrapper(execute))
                response = self.get_response(request)
            elapsed = (time.perf_counter() - start) * 1000
            response['X-Request-ID'] = request_id
            response['X-Worker-State'] = 'cold' if cold else 'warm'
            response['Server-Timing'] = f'app;dur={elapsed:.2f}, db;dur={stats["db_ms"]:.2f}, queries;desc="{stats["db_queries"]}"'
            return response
        finally:
            # Django's route template replaces customer IDs, sharing tokens, etc.
            match = getattr(request, 'resolver_match', None)
            route = getattr(match, 'route', None) or 'unmatched'
            if route == 'api/auth/<str:action>/' and match.kwargs.get('action') in {'csrf','login','register','logout','me','forgot-password','reset-password'}:
                route = 'api/auth/' + match.kwargs['action'] + '/'
            logger.info(json.dumps({'request_id': request_id, 'route': route, 'method': request.method,
                'status': response.status_code if response is not None else 500,
                'worker_state': 'cold' if cold else 'warm', 'worker_age_ms': round((start-_started)*1000, 2),
                'total_ms': round((time.perf_counter()-start)*1000, 2), **{k: round(v, 2) for k,v in stats.items()}}))
            current.reset(token)
