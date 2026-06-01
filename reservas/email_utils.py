import re
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

try:
    from premailer import transform
except ImportError:
    transform = lambda html: html


def send_templated_email(subject, template_name, context, to_email, from_email=None):
    """Renderiza plantillas HTML y envía un email multipart (HTML + plaintext fallback).

    Preferimos una plantilla HTML (`template_name + '.html'`) y generamos
    automáticamente la versión de texto con `strip_tags()` para clientes
    que no muestren HTML. Esto asegura consistencia visual con la app.

    Args:
        subject (str): Asunto del correo.
        template_name (str): Ruta base de la plantilla (sin extensión).
        context (dict): Contexto para renderizar la plantilla.
        to_email (str): Dirección del destinatario.
        from_email (str|None): Dirección remitente. Si None usa `settings.DEFAULT_FROM_EMAIL`.
    """
    from_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)

    html = None
    txt = None

    # Preferir HTML
    try:
        html = render_to_string(f"{template_name}.html", context)
        if html:
            # Extrae las definiciones de variables en el HTML (--variable: valor;)
            css_vars = dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);', html))
            
            # Reemplaza todos los var(--variable) o var(--variable, fallback) con su valor real
            for var_name, var_value in css_vars.items():
                pattern = rf'var\(\s*{var_name}(?:\s*,\s*[^)]+)?\s*\)'
                html = re.sub(pattern, var_value.strip(), html)

            html = transform(html)  # Convierte las clases CSS a estilos inline automáticamente
    except Exception:
        html = None

    if html:
        txt = strip_tags(html)
    else:
        # Fallback: attempt to render a plain-text template if present
        try:
            txt = render_to_string(f"{template_name}.txt", context)
        except Exception:
            txt = ""

    msg = EmailMultiAlternatives(subject=subject, body=txt or "", from_email=from_email, to=[to_email])
    if html:
        msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)
