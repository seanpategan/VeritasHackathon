"""Gunicorn production config. The Flask development server must not be used in production."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = 60            # upstream calls have their own shorter timeouts
graceful_timeout = 20
keepalive = 5
max_requests = 1000     # recycle workers to bound memory from raster processing
max_requests_jitter = 100
accesslog = "-"
# Privacy: no client IP in access logs; request paths for /api/crop-at carry no coordinates (POST body).
access_log_format = '%(t)s "%(r)s" %(s)s %(b)s %(L)ss'
