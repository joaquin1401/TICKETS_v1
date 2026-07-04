"""
settings.py — Configuración del proyecto Django con PostgreSQL.
Copiá este archivo como base y ajustá las variables de entorno.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Seguridad ────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "cambia-esto-en-produccion")
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost 127.0.0.1").split()

# ── Apps ─────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_q",
    "reservas",                      # ← tu app
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"          # ajustá al nombre de tu carpeta de proyecto

# ── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ── Base de datos PostgreSQL ──────────────────────────────────────────────────
import sys
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

if TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME":     os.environ.get("DB_NAME"),
            "USER":     os.environ.get("DB_USER"),
            "PASSWORD": os.environ.get("DB_PASSWORD"),
            "HOST":     os.environ.get("DB_HOST"),
            "PORT":     os.environ.get("DB_PORT"),
        }
    }

# ── Internacionalización ─────────────────────────────────────────────────────
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = TESTING

# ── Estáticos ────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Sesiones ─────────────────────────────────────────────────────────────────
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 8     # 8 horas
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ── Mensajes ─────────────────────────────────────────────────────────────────
from django.contrib.messages import constants as messages_constants
MESSAGE_TAGS = {
    messages_constants.DEBUG:   "secondary",
    messages_constants.INFO:    "info",
    messages_constants.SUCCESS: "success",
    messages_constants.WARNING: "warning",
    messages_constants.ERROR:   "danger",
}
# ── Email ─────────────────────────────────────────────────────────────────
#Es la dirección que le aparecerá al usuario como "Remitente" cuando reciba el correo de verificación.
DEFAULT_FROM_EMAIL  = os.environ.get("EMAIL_HOST_USER", "")
# Es la URL base que se usará para construir los enlaces de verificación en los correos electrónicos. Asegúrate de ajustar esto según tu entorno (desarrollo, producción, etc.).
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
# Es la cuenta desde la cual salen los correos
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")

CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", str(not DEBUG)) == "True"
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", str(not DEBUG)) == "True"
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split()
# ── URL base para enlaces en emails ───────────────────────────────────────
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")


# ── Django Q2 (Tareas Asíncronas) ────────────────────────────────────────────
Q_CLUSTER = {
    'name': 'DjangORM',
    'workers': 4,
    'timeout': 90,
    'retry': 120,
    'queue_limit': 50,
    'bulk': 10,
    'orm': 'default'
}