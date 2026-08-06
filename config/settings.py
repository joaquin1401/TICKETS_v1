"""
settings.py — Configuración del proyecto Django con PostgreSQL.
Copiá este archivo como base y ajustá las variables de entorno.
"""

from pathlib import Path
import os
import sys
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Carga las variables de entorno desde el archivo .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Seguridad ────────────────────────────────────────────────────────────────
SECRET_KEY_INSEGURA = "cambia-esto-en-produccion"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", SECRET_KEY_INSEGURA)
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost 127.0.0.1").split()

# Con DEBUG=False no arrancamos con la clave de ejemplo. Es la clave que firma
# sesiones, tokens de recuperación de contraseña y CSRF: si es la del repo,
# cualquiera puede falsificarlos. Antes el fallback se aplicaba en silencio y
# se podía desplegar sin enterarse.
if not DEBUG and SECRET_KEY == SECRET_KEY_INSEGURA:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY no está configurada (o quedó con el valor de ejemplo) "
        "y DEBUG=False. Generá una con:\n"
        "  python -c \"from django.core.management.utils import get_random_secret_key; "
        "print(get_random_secret_key())\""
    )

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
    # Sirve los archivos de STATIC_ROOT en producción. Con DEBUG=False Django
    # no los sirve solo, así que sin esto el CSS y las imágenes dan 404 detrás
    # de gunicorn. Debe ir inmediatamente después de SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
USE_TZ = True

# ── Estáticos ────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise comprime los estáticos y les agrega un hash en el nombre para
# poder cachearlos indefinidamente. Requiere correr collectstatic en el build.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Política de contraseñas ──────────────────────────────────────────────────
# El modelo Usuario es propio (no hereda de AbstractBaseUser), así que estos
# validadores NO se aplican solos: los invocan explícitamente los formularios
# que fijan contraseña (RegistroForm, AdminCrearUsuarioForm, NuevaContrasenaForm).
AUTH_PASSWORD_VALIDATORS = [
    {
        # Los atributos por defecto (username/first_name/last_name/email) no
        # existen en Usuario; se mapean a los propios del modelo.
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("nombre", "apellido", "correo")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

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


# ── Logging ──────────────────────────────────────────────────────────────────
# Sin esta configuración, los logger.error()/warning() de la app no tienen
# ningún handler asociado y se pierden: quedaban invisibles justamente los
# fallos de envío de correo y de cálculo de distancia, que son los que más
# necesitamos ver en producción.
# Se escribe a stdout, que es lo que esperan Render/Heroku/Docker/systemd.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        # Logs de la propia app (reservas.utils.services, reservas.signals, ...)
        "reservas": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Los 500 con DEBUG=False sólo se ven por acá.
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}


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