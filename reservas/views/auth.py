"""
Vistas de autenticación: registro, login y logout.

Épica 1:
    - HU 1.1: Registro de cuenta (registro)
    - HU 1.2: Inicio de sesión (login_view)
    - Logout (logout_view)
"""

from django.shortcuts import render, redirect
from django.contrib import messages

from ..models import Usuario, Cargo
from ..forms import RegistroForm, LoginForm
from ..utils.email_verification import crear_verificacion, enviar_correo_verificacion
from ._base import get_usuario_sesion


def registro(request):
    """
    Vista para registro de cuenta de usuario (HU 1.1).

    Captura datos de registro y crea un usuario con estado pendiente.
    ACTUALIZADO: ahora incluye verificación de correo electrónico como
    paso previo a la aprobación del administrador.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra formulario vacío.
            - POST: Procesa envío de datos.

    Returns:
        HttpResponse: Plantilla 'reservas/auth/registro.html' con formulario
            (GET) o redirige a verificar_correo tras éxito (POST).

    Proceso:
        1. GET: Renderiza RegistroForm vacío.
        2. POST (válido):
            a. Crea Usuario con correo_verificado=False, valido=False.
            b. Genera VerificacionCorreo (código 6 dígitos + token UUID).
            c. Envía email con ambos métodos al correo del usuario.
            d. Guarda PK en sesión (verificacion_uid).
            e. Redirige a verificar_correo.
        3. POST (inválido): Re-renderiza formulario con errores.

    Messages:
        - info:    Correo enviado exitosamente con código y enlace.
        - warning: No se pudo enviar el correo (SMTP error).
    """
    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            usuario = form.save()  # correo_verificado=False ya está en RegistroForm.save()

            # Si el usuario es Administrador (prioridad 0), no requerir verificación
            if usuario.id_cargo.prioridad == 0:
                usuario.correo_verificado = True
                usuario.save(update_fields=['correo_verificado'])
                messages.success(request, "Cuenta de administrador creada exitosamente. Tu cuenta ya está validada, podés iniciar sesión.")
                return redirect("login")

            # Generar código de 6 dígitos y token UUID simultáneamente
            verificacion = crear_verificacion(usuario)

            # Enviar correo con ambos métodos (código + enlace mágico)
            enviado = enviar_correo_verificacion(usuario, verificacion, request)

            # Guardar PK en sesión para que verificar_correo() sepa a quién verificar
            request.session["verificacion_uid"] = usuario.pk

            if enviado:
                messages.info(
                    request,
                    f"Te enviamos un correo a {usuario.correo} con un código de 6 dígitos "
                    "y un enlace de verificación. Revisá también la carpeta de spam.",
                )
            else:
                # SMTP falló: el usuario puede continuar y pedir reenvío desde la siguiente pantalla
                messages.warning(
                    request,
                    "Tu cuenta fue creada pero no pudimos enviar el correo de verificación. "
                    "Podés solicitar un reenvío desde la siguiente pantalla.",
                )

            return redirect("verificar_correo")
    else:
        form = RegistroForm()
    return render(request, "reservas/auth/registro.html", {"form": form})


def login_view(request):
    """
    Vista para inicio de sesión (HU 1.2).

    Valida credenciales contra la BD y establece sesión. Los usuarios
    pendientes de aprobación o rechazados ven mensajes específicos.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra formulario de login.
            - POST: Procesa credenciales.

    Returns:
        HttpResponse: Redirige a inicio tras login exitoso,
            o re-renderiza formulario con errores.

    Validaciones:
        1. Si usuario logueado: redirige a inicio.
        2. Si credenciales inválidas: "Correo o contraseña incorrectos."
        3. Si usuario rechazado: "Tu solicitud fue rechazada..."
        4. Si usuario pendiente: "Tu cuenta está pendiente de aprobación..."
        5. Si credenciales correctas y usuario válido: Sesión establecida.

    Sesión (set en request.session):
        - "usuario_id": PK del usuario.
        - "es_admin": bool (cargo.prioridad == 0).

    Messages:
        - error: Credenciales inválidas, rechazado.
        - warning: Pendiente de aprobación.
    """
    if request.session.get("usuario_id"):
        return redirect("inicio")

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            correo = form.cleaned_data["correo"]
            contrasena = form.cleaned_data["contrasena"]
            try:
                usuario = Usuario.objects.select_related("id_cargo").get(correo=correo)
            except Usuario.DoesNotExist:
                messages.error(request, "Correo o contraseña incorrectos.")
                return render(request, "reservas/auth/login.html", {"form": form})

            if not usuario.check_password(contrasena):
                messages.error(request, "Correo o contraseña incorrectos.")
                return render(request, "reservas/auth/login.html", {"form": form})

            # Verificación de correo: bloquear login si el usuario
            # completó el registro pero todavía no verificó su email.
            # Aplica solo si el campo correo_verificado existe en el modelo
            # (requiere haber corrido la migración correspondiente) y si no es Admin.
            if hasattr(usuario, 'correo_verificado') and not usuario.correo_verificado and usuario.id_cargo.prioridad != 0:
                request.session["verificacion_uid"] = usuario.pk
                messages.warning(
                    request,
                    "Primero debés verificar tu correo electrónico. "
                    "Revisá tu bandeja de entrada o solicitá un nuevo código.",
                )
                return redirect("verificar_correo")

            if usuario.rechazado:
                messages.error(request, "Tu solicitud de acceso fue rechazada. Contactá al administrador.")
                return render(request, "reservas/auth/login.html", {"form": form})

            if not usuario.valido:
                messages.warning(request, "Tu cuenta está pendiente de aprobación por un administrador.")
                return render(request, "reservas/auth/login.html", {"form": form})

            # Establecer sesión
            request.session["usuario_id"] = usuario.pk
            request.session["es_admin"] = (usuario.id_cargo.prioridad == 0)
            if usuario.id_cargo.nombre == Cargo.CHOFER:
                return redirect("chofer_dashboard")
            return redirect("inicio")
    else:
        form = LoginForm()
    return render(request, "reservas/auth/login.html", {"form": form})


def logout_view(request):
    """
    Vista para cierre de sesión.

    Elimina todos los datos de sesión y redirige a login.

    Args:
        request (HttpRequest): Objeto de solicitud.

    Returns:
        HttpResponseRedirect: Redirige a 'login'.

    Notes:
        Utiliza request.session.flush() para limpiar completamente la sesión
        (no solo request.session.clear() que mantiene la sesión vacía).
    """
    request.session.flush()
    return redirect("login")
