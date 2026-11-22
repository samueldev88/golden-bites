import ipaddress
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:  # python-dotenv é opcional
    pass


def _lista(nome, padrao=""):
    return [v.strip() for v in os.environ.get(nome, padrao).split(",") if v.strip()]


DEBUG = os.environ.get("DEBUG", "0").strip() == "1"
SECRET_KEY = os.environ.get("SECRET_KEY") or (
    "dev-only-unsafe-key-do-not-use-in-production" if DEBUG else ""
)
if not DEBUG and (
    SECRET_KEY.startswith(("dev-", "troque-")) or len(SECRET_KEY) < 50
):
    raise ImproperlyConfigured("Defina uma SECRET_KEY aleatória e exclusiva, com pelo menos 50 caracteres.")
ALLOWED_HOSTS = _lista("ALLOWED_HOSTS", "127.0.0.1,localhost")
if not DEBUG and (
    not ALLOWED_HOSTS
    or "*" in ALLOWED_HOSTS
    or all(host in {"127.0.0.1", "localhost"} for host in ALLOWED_HOSTS)
):
    raise ImproperlyConfigured("Defina ALLOWED_HOSTS com o domínio público do site.")
CSRF_TRUSTED_ORIGINS = _lista("CSRF_TRUSTED_ORIGINS")
if not DEBUG and any(not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("Em produção, CSRF_TRUSTED_ORIGINS deve conter somente origens HTTPS.")
TRUSTED_PROXY_IPS = _lista("TRUSTED_PROXY_IPS")
for _proxy in TRUSTED_PROXY_IPS:
    try:
        ipaddress.ip_network(_proxy, strict=False)
    except ValueError as erro:
        raise ImproperlyConfigured(f"TRUSTED_PROXY_IPS contém um endereço inválido: {_proxy}") from erro
TRUST_PROXY_SSL = os.environ.get("TRUST_PROXY_SSL", "0") == "1"
if TRUST_PROXY_SSL and not TRUSTED_PROXY_IPS:
    raise ImproperlyConfigured("Configure TRUSTED_PROXY_IPS antes de confiar no cabeçalho HTTPS do proxy.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalogo",
    "carrinho",
    "entregas",
    "pedidos",
    "fidelidade",
    "financeiro",
    "painel",
]

MIDDLEWARE = [
    "maison.middleware.TrustedProxyHeadersMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "maison.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "maison.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "catalogo.context_processors.loja",
            ],
        },
    },
]

WSGI_APPLICATION = "maison.wsgi.application"

# SQLite em produção só com opt-in explícito (ex.: PythonAnywhere com pouco tráfego).
# Com várias instâncias ou muita concorrência, prefira PostgreSQL via DATABASE_URL.
PERMITIR_SQLITE = os.environ.get("PERMITIR_SQLITE", "0") == "1"


def _banco_dados(url=None, debug=None, permitir_sqlite=None):
    debug = DEBUG if debug is None else debug
    permitir_sqlite = PERMITIR_SQLITE if permitir_sqlite is None else permitir_sqlite
    sqlite_ok = debug or permitir_sqlite
    url = (os.environ.get("DATABASE_URL", "") if url is None else url).strip()
    if not url:
        if not sqlite_ok:
            raise ImproperlyConfigured(
                "Configure DATABASE_URL com um PostgreSQL persistente em produção "
                "(ou defina PERMITIR_SQLITE=1 para usar SQLite conscientemente)."
            )
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 20},
        }

    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        if not sqlite_ok:
            raise ImproperlyConfigured(
                "SQLite é permitido somente em desenvolvimento ou com PERMITIR_SQLITE=1; "
                "use PostgreSQL em produção."
            )
        caminho = unquote(parsed.path.lstrip("/")) or ":memory:"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:" if caminho == ":memory:" else BASE_DIR / caminho,
            "OPTIONS": {"timeout": 20},
        }

    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
        raise ImproperlyConfigured("DATABASE_URL deve ser uma URL válida de PostgreSQL.")
    try:
        porta = parsed.port
    except ValueError as erro:
        raise ImproperlyConfigured("DATABASE_URL contém uma porta inválida.") from erro
    parametros = parse_qs(parsed.query)
    sslmode = parametros.get("sslmode", [os.environ.get("DATABASE_SSLMODE", "require")])[0]
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": porta or 5432,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": sslmode},
    }


DATABASES = {"default": _banco_dados()}

# Exige: python manage.py createcachetable (uma vez, depois do migrate)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 100000},
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# O OpenStreetMap exige o Referer para liberar os mapas (o padrão do Django o esconde de outros sites)
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

LOGIN_URL = "painel:login"
LOGIN_REDIRECT_URL = "painel:dashboard"

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # carrinho dura 30 dias

# Mercado Pago
MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
MP_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "")
SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8000" if DEBUG else "")
if not DEBUG and not SITE_URL.lower().startswith("https://"):
    raise ImproperlyConfigured("Defina SITE_URL com a URL HTTPS pública do site.")

# Cookies e cabeçalhos de segurança
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True  # o JavaScript do site lê o token do HTML, não do cookie
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if TRUST_PROXY_SSL else None
# Atrás de proxy sem SECURE_PROXY_SSL_HEADER, o redirect do Django causa loop infinito.
# No PythonAnywhere deixe 0 e ative "Force HTTPS" na aba Web. Em outros hosts, defina 1.
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
SECURE_HSTS_PRELOAD = False

DATA_UPLOAD_MAX_NUMBER_FILES = 12