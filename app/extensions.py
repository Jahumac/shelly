"""Shared Flask extensions — imported by routes and initialised in create_app()."""

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    from flask import request

    def _client_ip():
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return get_remote_address()

    limiter = Limiter(
        key_func=_client_ip,
        default_limits=[],
        storage_uri="memory://",
    )
except ImportError:
    limiter = None
