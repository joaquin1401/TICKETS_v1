from django.core.mail import send_mail
from .email_utils import send_templated_email

import logging
logger = logging.getLogger(__name__)

def enviar_correo_async(subject, message, from_email, recipient_list, **kwargs):
    """
    Wrapper asíncrono para send_mail de Django.
    """
    try:
        send_mail(subject, message, from_email, recipient_list, **kwargs)
    except Exception as e:
        logger.error(f"Fallo al enviar_correo_async a {recipient_list}: {e}")

def enviar_correo_templated_async(subject, template_name, context, to_email, from_email=None):
    """
    Wrapper asíncrono para send_templated_email.
    """
    try:
        send_templated_email(subject, template_name, context, to_email, from_email)
    except Exception as e:
        logger.error(f"Fallo al enviar_correo_templated_async a {to_email}: {e}")
