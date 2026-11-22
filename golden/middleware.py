import secrets

from django.conf import settings

from .security import proxy_confiavel


class TrustedProxyHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not proxy_confiavel(request.META.get("REMOTE_ADDR")):
            for header in (
                "HTTP_X_FORWARDED_FOR",
                "HTTP_X_FORWARDED_PROTO",
                "HTTP_X_FORWARDED_HOST",
                "HTTP_X_REAL_IP",
            ):
                request.META.pop(header, None)
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nonce = secrets.token_urlsafe(18)
        request.csp_nonce = nonce
        response = self.get_response(request)
        if not settings.DEBUG:
            response["Content-Security-Policy"] = "; ".join((
                "default-src 'self'",
                f"script-src 'self' 'nonce-{nonce}' https://cdnjs.cloudflare.com",
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
                "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com",
                "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com",
                "connect-src 'self' https://viacep.com.br",
                "object-src 'none'",
                "base-uri 'self'",
                "frame-ancestors 'none'",
                "form-action 'self'",
                "upgrade-insecure-requests",
            ))
        return response
