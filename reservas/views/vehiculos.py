"""
Vistas de gestión de vehículos (ABM).

Épica 6:
    - HU 6.1: listado_vehiculos() — listado de todos los vehículos.
    - HU 6.2: alta_vehiculo() — alta de nuevo vehículo.
    - HU 6.3: edicion_vehiculo() — edición de vehículo.
    - baja_temporal_vehiculo() — baja temporal por días.
    - levantar_baja_vehiculo() — levantamiento anticipado de baja.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from ..models import Vehiculo
from ..forms import VehiculoForm
from ._base import get_usuario_sesion, paginate_queryset, login_requerido, admin_requerido


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 6: ABM (ALTA, BAJA, MODIFICACIÓN) DE VEHÍCULOS
# ══════════════════════════════════════════════════════════════════════════════
# HU 6.1: Listado de vehículos
# HU 6.2: Alta de vehículo
# HU 6.3: Edición / baja de vehículo


@login_requerido
@admin_requerido
def listado_vehiculos(request):
    """
    Vista del listado de vehículos de los vehículos (HU 6.1).

    Muestra todos los vehículos (activos e inactivos) ordenados
    por marca y modelo. Desde aquí se puede navegar a crear o editar.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/vehiculos/listado_vehiculos.html' con:
            - vehiculos: QuerySet de todos los vehículos.
            - usuario: Instancia del usuario logueado (admin).
    """
    vehiculos_decano = Vehiculo.objects.filter(exclusivo_decanato=True).order_by("marca", "modelo")
    vehiculos_qs = Vehiculo.objects.filter(exclusivo_decanato=False).order_by("marca", "modelo")
    page_obj, pagination_query = paginate_queryset(request, vehiculos_qs)

    return render(request, "reservas/vehiculos/listado_vehiculos.html", {
        "vehiculos_decano": vehiculos_decano,
        "vehiculos": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_vehiculos": page_obj.paginator.count,
        "total_vehiculos_activos": vehiculos_qs.filter(activo=True).count(),
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def alta_vehiculo(request):
    """
    Vista para dar de alta un nuevo vehículo (HU 6.2).

    Captura datos de marca, modelo, capacidad y estado activo.
    La creación es inmediata sin validaciones adicionales.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra VehiculoForm vacío.
            - POST: Procesa creación de vehículo.

    Returns:
        HttpResponse: Plantilla 'reservas/vehiculos/form_vehiculo.html' con:
            - form: VehiculoForm.
            - titulo: "Agregar vehículo".
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST exitoso):
        - Redirect a listado_vehiculos.

    Messages (POST):
        - success: "Vehículo agregado a los vehículos."
    """
    if request.method == "POST":
        form = VehiculoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo agregado a los vehículos.")
            return redirect("listado_vehiculos")
    else:
        form = VehiculoForm()
    return render(request, "reservas/vehiculos/form_vehiculo.html", {
        "form": form,
        "titulo": "Agregar vehículo",
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def edicion_vehiculo(request, vehiculo_id):
    """
    Vista para editar o dar de baja un vehículo (HU 6.3).

    Permite modificar marca, modelo, capacidad y estado (activo/inactivo).
    Cambiar a inactivo impide que aparezca en formularios de reserva.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra VehiculoForm pre-poblado.
            - POST: Procesa actualización.
        vehiculo_id (int): PK del vehículo.

    Returns:
        HttpResponse: Plantilla 'reservas/vehiculos/form_vehiculo.html' con:
            - form: VehiculoForm pre-poblado.
            - titulo: "Editar vehículo: {marca} {modelo}".
            - vehiculo: Instancia del vehículo.
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST exitoso):
        - Redirect a listado_vehiculos.

    Messages (POST):
        - success: "Vehículo actualizado."

    Raises:
        Http404: Si el vehículo no existe.

    Notas:
        - No hay "eliminación" física, solo cambiar activo=False.
        - Los tickets existentes permanecen (PROTECT en ForeignKey).
    """
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)
    if request.method == "POST":
        form = VehiculoForm(request.POST, instance=vehiculo)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo actualizado.")
            return redirect("listado_vehiculos")
    else:
        form = VehiculoForm(instance=vehiculo)
    return render(request, "reservas/vehiculos/form_vehiculo.html", {
        "form": form,
        "titulo": f"Editar vehículo: {vehiculo}",
        "vehiculo": vehiculo,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def baja_temporal_vehiculo(request, vehiculo_id):
    """
    Vista POST para dar de baja temporalmente a un vehículo por X días.
    Utiliza el servicio `dar_baja_temporal_vehiculo` para manejar cancelaciones y reasignaciones.
    """
    if request.method != "POST":
        return redirect("edicion_vehiculo", vehiculo_id=vehiculo_id)

    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)

    try:
        dias = int(request.POST.get("dias_baja", 0))
        if dias <= 0:
            messages.error(request, "La cantidad de días debe ser mayor a 0.")
            return redirect("edicion_vehiculo", vehiculo_id=vehiculo_id)
    except ValueError:
        messages.error(request, "Cantidad de días inválida.")
        return redirect("edicion_vehiculo", vehiculo_id=vehiculo_id)

    usuario_admin = get_usuario_sesion(request)
    from ..utils.services import dar_baja_temporal_vehiculo

    resultado = dar_baja_temporal_vehiculo(vehiculo, dias, usuario_admin)

    inactivo_str = resultado["inactivo_hasta"].strftime('%d/%m/%Y')
    msg = f"Vehículo dado de baja temporalmente hasta el {inactivo_str}. "
    msg += f"Tickets afectados: {resultado['total_afectados']} "
    msg += f"({resultado['reasignados']} reasignados, {resultado['cancelados']} cancelados)."

    messages.success(request, msg)
    return redirect("listado_vehiculos")


@login_requerido
@admin_requerido
def levantar_baja_vehiculo(request, vehiculo_id):
    """
    Vista POST para levantar la baja temporal de un vehículo de forma anticipada.
    """
    if request.method != "POST":
        return redirect("edicion_vehiculo", vehiculo_id=vehiculo_id)

    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)

    if not vehiculo.esta_en_baja_temporal():
        messages.info(request, "El vehículo no se encuentra actualmente en baja temporal.")
        return redirect("edicion_vehiculo", vehiculo_id=vehiculo_id)

    vehiculo.inactivo_hasta = None
    vehiculo.save(update_fields=["inactivo_hasta"])

    messages.success(request, "Baja temporal levantada. El vehículo vuelve a estar disponible.")
    return redirect("listado_vehiculos")
