"""
Vistas de verificación de correo y recuperación de contraseña.

Épica 1 (extensión):
    - verificar_correo()
    - verificar_correo_enlace()
    - solicitar_recuperacion()
    - verificar_recuperacion()
    - verificar_recuperacion_enlace()
    - nueva_contrasena()
"""

from django.shortcuts import render, redirect
from django.contrib import messages

from ..models import Usuario
from ..forms import VerificacionCodigoForm
from ..utils.email_verification import (
    crear_verificacion,
    enviar_correo_verificacion,
    verificar_por_codigo,
    verificar_por_token,
)


def verificar_correo(request):
    """
    Vista del formulario de verificación de correo electrónico (extensión HU 1.1).

    Muestra el formulario de código de 6 dígitos y permite reenviar el email.
    Se llega aquí desde registro() o desde login_view() si el correo no fue
    verificado todavía.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET:  Muestra el formulario vacío con los dos tabs (código / enlace).
            - POST (sin accion):  Valida el código ingresado.
            - POST (accion="reenviar"): Regenera código/token y reenvía el correo.

    Returns:
        HttpResponse: Plantilla 'reservas/auth/verificar_correo.html' con:
            - form:   VerificacionCodigoForm (vacío o con errores).
            - correo: Email del usuario (para mostrarlo en pantalla).
        O redirect a login (verificación exitosa) o registro (sesión perdida).

    Protecciones:
        - Sin verificacion_uid en sesión → redirige al registro.
        - Usuario ya verificado → redirige al login con mensaje de éxito.

    Session:
        Lee:   request.session["verificacion_uid"]
        Borra: request.session["verificacion_uid"] al verificar exitosamente.
    """
    uid = request.session.get("verificacion_uid")
    if not uid:
        # Sesión perdida o acceso directo a la URL sin registrarse antes
        messages.error(request, "Sesión de verificación no encontrada. Registrate nuevamente.")
        return redirect("registro")

    try:
        usuario = Usuario.objects.get(pk=uid)
    except Usuario.DoesNotExist:
        return redirect("registro")

    # Si ya verificó (ej: abrió el enlace mágico en otra pestaña), ir al login
    if hasattr(usuario, 'correo_verificado') and usuario.correo_verificado:
        messages.success(request, "Tu correo ya fue verificado. Podés iniciar sesión.")
        return redirect("login")

    if request.method == "POST":
        accion = request.POST.get("accion")

        # ── Reenvío: elimina registro anterior y genera uno nuevo ──────────
        if accion == "reenviar":
            verificacion = crear_verificacion(usuario)
            enviado = enviar_correo_verificacion(usuario, verificacion, request)
            if enviado:
                messages.success(request, "Código reenviado. Revisá tu bandeja de entrada.")
            else:
                messages.error(request, "No se pudo enviar el correo. Intentá de nuevo en unos minutos.")
            return redirect("verificar_correo")

        # ── Validación del código ingresado ────────────────────────────────
        form = VerificacionCodigoForm(request.POST)
        if form.is_valid():
            codigo = form.cleaned_data["codigo"]
            resultado = verificar_por_codigo(usuario, codigo)

            if resultado.exito:
                # Limpiar sesión de verificación (ya no es necesaria)
                del request.session["verificacion_uid"]
                messages.success(
                    request,
                    "✓ Correo verificado correctamente. "
                    "Tu solicitud quedó pendiente de aprobación por un administrador.",
                )
                return redirect("login")
            else:
                # Código incorrecto, expirado o ya usado → mostrar mensaje descriptivo
                messages.error(request, resultado.mensaje)
    else:
        form = VerificacionCodigoForm()

    from ..models import VerificacionCorreo
    from django.utils import timezone
    try:
        verificacion = VerificacionCorreo.objects.get(usuario=usuario)
        tiempo_transcurrido = (timezone.now() - verificacion.creado_en).total_seconds()
        segundos_restantes = int(max(0, 30 * 60 - tiempo_transcurrido))
    except VerificacionCorreo.DoesNotExist:
        segundos_restantes = 0

    return render(request, "reservas/auth/verificar_correo.html", {
        "form": form,
        "correo": usuario.correo,
        "segundos_restantes": segundos_restantes,
    })


def verificar_correo_enlace(request, token):
    """
    Vista del enlace mágico de verificación (extensión HU 1.1).

    Se activa cuando el usuario hace clic en el botón del correo electrónico.
    El token llega como parámetro UUID, validado por el conversor <uuid:>
    en urls.py antes de llegar aquí (no llegan strings malformados).

    Flujo según resultado de verificar_por_token():
        OK:           limpia sesión → redirect login (éxito).
        EXPIRADO:     guarda uid en sesión → redirect verificar_correo (pedir reenvío).
        YA_USADO:     guarda uid en sesión → redirect verificar_correo (informar).
        INCORRECTO:   token no existe en BD → redirect login (error).

    Args:
        request (HttpRequest): Solo GET (el enlace del correo es siempre GET).
        token (uuid.UUID): Token UUID del enlace, ya validado por Django.

    Returns:
        HttpResponseRedirect: Redirect al login o a verificar_correo.
    """
    resultado, usuario = verificar_por_token(token)

    if resultado.exito:
        # Limpiar sesión de verificación si el usuario tenía el form abierto en paralelo
        request.session.pop("verificacion_uid", None)
        messages.success(
            request,
            "✓ Correo verificado correctamente. "
            "Tu solicitud quedó pendiente de aprobación por un administrador.",
        )

    else:
        # Guardar uid en sesión para que pueda pedir reenvío desde verificar_correo
        if usuario:
            request.session["verificacion_uid"] = usuario.pk

        messages.error(request, resultado.mensaje)

        # Si expiró o ya fue usado, mandarlo a la pantalla de verificación para reenviar
        if resultado.estado in (resultado.EXPIRADO, resultado.YA_USADO):
            return redirect("verificar_correo")

    return redirect("login")


# ══════════════════════════════════════════════════════════════════════════════
# Flujo de Recuperación de Contraseña
# ══════════════════════════════════════════════════════════════════════════════

def solicitar_recuperacion(request):
    from ..forms import SolicitarRecuperacionForm
    from ..utils.password_recovery import crear_recuperacion, enviar_correo_recuperacion

    if request.method == "POST":
        form = SolicitarRecuperacionForm(request.POST)
        if form.is_valid():
            correo = form.cleaned_data["correo"]
            try:
                usuario = Usuario.objects.get(correo=correo)
                recuperacion = crear_recuperacion(usuario)
                enviar_correo_recuperacion(usuario, recuperacion, request)
                request.session["recuperacion_uid"] = usuario.pk
                messages.info(request, "Te hemos enviado un correo con instrucciones para restablecer tu contraseña.")
                return redirect("verificar_recuperacion")
            except Usuario.DoesNotExist:
                # No revelar si el correo existe o no por seguridad,
                # solo mostrar el mismo mensaje de éxito.
                messages.info(request, "Si el correo está registrado, recibirás instrucciones en unos minutos.")
                return redirect("login")
    else:
        form = SolicitarRecuperacionForm()

    return render(request, "reservas/auth/solicitar_recuperacion.html", {"form": form})


def verificar_recuperacion(request):
    from ..forms import VerificarRecuperacionForm
    from ..utils.password_recovery import verificar_recuperacion_por_codigo, crear_recuperacion, enviar_correo_recuperacion
    from ..models import RecuperacionPassword
    from django.utils import timezone

    uid = request.session.get("recuperacion_uid")
    if not uid:
        messages.error(request, "Sesión de recuperación inválida o expirada.")
        return redirect("solicitar_recuperacion")

    try:
        usuario = Usuario.objects.get(pk=uid)
    except Usuario.DoesNotExist:
        return redirect("solicitar_recuperacion")

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "reenviar":
            recuperacion = crear_recuperacion(usuario)
            enviar_correo_recuperacion(usuario, recuperacion, request)
            messages.success(request, "Código reenviado. Revisá tu correo.")
            return redirect("verificar_recuperacion")

        form = VerificarRecuperacionForm(request.POST)
        if form.is_valid():
            codigo = form.cleaned_data["codigo"]
            resultado = verificar_recuperacion_por_codigo(usuario, codigo)

            if resultado.exito:
                request.session["can_reset_password"] = True
                messages.success(request, "Código verificado. Ahora podés ingresar tu nueva contraseña.")
                return redirect("nueva_contrasena")
            else:
                messages.error(request, resultado.mensaje)
    else:
        form = VerificarRecuperacionForm()

    try:
        recuperacion = RecuperacionPassword.objects.get(usuario=usuario)
        tiempo_transcurrido = (timezone.now() - recuperacion.creado_en).total_seconds()
        segundos_restantes = int(max(0, 30 * 60 - tiempo_transcurrido))
    except RecuperacionPassword.DoesNotExist:
        segundos_restantes = 0

    return render(request, "reservas/auth/verificar_recuperacion.html", {
        "form": form,
        "correo": usuario.correo,
        "segundos_restantes": segundos_restantes,
    })


def verificar_recuperacion_enlace(request, token):
    from ..utils.password_recovery import verificar_recuperacion_por_token

    resultado, usuario = verificar_recuperacion_por_token(token)

    if resultado.exito:
        request.session["recuperacion_uid"] = usuario.pk
        request.session["can_reset_password"] = True
        messages.success(request, "Enlace verificado. Ingresá tu nueva contraseña.")
        return redirect("nueva_contrasena")
    else:
        messages.error(request, resultado.mensaje)
        return redirect("login")


def nueva_contrasena(request):
    from ..forms import NuevaContrasenaForm
    from ..utils.password_recovery import consumir_recuperacion

    uid = request.session.get("recuperacion_uid")
    can_reset = request.session.get("can_reset_password")

    if not uid or not can_reset:
        messages.error(request, "No tenés permiso para cambiar la contraseña en este momento.")
        return redirect("solicitar_recuperacion")

    try:
        usuario = Usuario.objects.get(pk=uid)
    except Usuario.DoesNotExist:
        return redirect("solicitar_recuperacion")

    if request.method == "POST":
        form = NuevaContrasenaForm(request.POST)
        if form.is_valid():
            usuario.set_password(form.cleaned_data["contrasena_nueva"])
            usuario.save(update_fields=["contrasena"])
            consumir_recuperacion(usuario)

            # Limpiar sesión
            request.session.pop("recuperacion_uid", None)
            request.session.pop("can_reset_password", None)

            messages.success(request, "Tu contraseña ha sido restablecida exitosamente. Ya podés iniciar sesión.")
            return redirect("login")
    else:
        form = NuevaContrasenaForm()

    return render(request, "reservas/auth/nueva_contrasena.html", {"form": form})
