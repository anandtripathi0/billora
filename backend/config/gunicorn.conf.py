import os
bind = '0.0.0.0:' + os.environ.get('PORT', '8000')
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = 2
timeout = 90
accesslog = '-'
errorlog = '-'
# Route templates are logged by TimingMiddleware. Never log raw URL queries,
# sharing tokens, Cookie/Authorization headers, or request bodies here.
access_log_format = '%({x-request-id}o)s %(m)s %(s)s %(L)s'
