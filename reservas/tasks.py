from django.core.mail import send_mail
from .email_utils import send_templated_email

def enviar_correo_async(subject, message, from_email, recipient_list, **kwargs):
    """
    Wrapper asíncrono para send_mail de Django.
    """
    send_mail(subject, message, from_email, recipient_list, **kwargs)

def enviar_correo_templated_async(subject, template_name, context, to_email, from_email=None):
    """
    Wrapper asíncrono para send_templated_email.
    """
    send_templated_email(subject, template_name, context, to_email, from_email)
