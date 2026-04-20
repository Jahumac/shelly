"""Shared Flask extensions — imported by routes and initialised in create_app()."""

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    from flask import request
    import os

    def _client_ip():
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return get_remote_address()

    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        strategy="fixed-window",
    )
except ImportError:
    limiter = None
