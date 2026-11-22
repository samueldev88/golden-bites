from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .middleware import ContentSecurityPolicyMiddleware, TrustedProxyHeadersMiddleware
from .settings import _banco_dados


class SecurityMiddlewareTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    def test_content_security_policy_uses_a_per_response_nonce(self):
        request = RequestFactory().get("/")
        middleware = ContentSecurityPolicyMiddleware(lambda request: HttpResponse())

        response = middleware(request)

        self.assertIn(f"'nonce-{request.csp_nonce}'", response["Content-Security-Policy"])
        self.assertIn("object-src 'none'", response["Content-Security-Policy"])

    @override_settings(TRUSTED_PROXY_IPS=[])
    def test_forwarded_headers_are_removed_from_untrusted_sources(self):
        request = RequestFactory().get(
            "/",
            HTTP_X_FORWARDED_FOR="198.51.100.10",
            HTTP_X_FORWARDED_PROTO="https",
        )
        middleware = TrustedProxyHeadersMiddleware(
            lambda req: HttpResponse(
                f"{req.META.get('HTTP_X_FORWARDED_FOR', '')}|"
                f"{req.META.get('HTTP_X_FORWARDED_PROTO', '')}"
            )
        )

        response = middleware(request)

        self.assertEqual(response.content, b"|")


class DatabaseConfigurationTests(SimpleTestCase):
    def test_production_requires_a_persistent_database_url(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DATABASE_URL"):
            _banco_dados("", debug=False)

    def test_production_rejects_sqlite(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "SQLite"):
            _banco_dados("sqlite:///db.sqlite3", debug=False)

    def test_postgresql_url_enables_ssl_and_health_checks(self):
        banco = _banco_dados(
            "postgresql://app:password@db.example/golden?sslmode=verify-full",
            debug=False,
        )

        self.assertEqual(banco["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(banco["OPTIONS"], {"sslmode": "verify-full"})
        self.assertTrue(banco["CONN_HEALTH_CHECKS"])
