"""
Vistas misceláneas y de configuración global.

Contiene:
    - configuracion_global() — panel de configuración (días de anticipación, feriados).
    - api_calcular_distancia() — endpoint JSON para OSRM.
    - preview_email() — utilidad de desarrollo para plantillas de email.
"""

from datetime import datetime, date

from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.conf import settings

from ..models import ConfiguracionGlobal, Feriado
from ..forms import ConfiguracionGlobalForm
from ._base import get_usuario_sesion, login_requerido, admin_requerido


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GLOBAL
# ══════════════════════════════════════════════════════════════════════════════


@login_requerido
@admin_requerido
def configuracion_global(request):
    """
    Vista para administrar las configuraciones globales del sistema.
    Permite modificar días de anticipación y gestionar los feriados.
    """
    usuario = get_usuario_sesion(request)
    config = ConfiguracionGlobal.get_solo()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_feriado":
            fecha_str = request.POST.get("fecha_feriado")
            descripcion = request.POST.get("descripcion_feriado", "").strip()
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                    if not Feriado.objects.filter(fecha=fecha).exists():
                        Feriado.objects.create(fecha=fecha, descripcion=descripcion)
                        messages.success(request, f"Feriado del {fecha.strftime('%d/%m/%Y')} agregado correctamente.")
                    else:
                        messages.error(request, "Ya existe un feriado en esa fecha.")
                except ValueError:
                    messages.error(request, "Formato de fecha inválido.")
            else:
                messages.error(request, "La fecha es requerida.")
            return redirect("configuracion_global")

        elif action == "delete_feriado":
            feriado_id = request.POST.get("feriado_id")
            if feriado_id:
                Feriado.objects.filter(pk=feriado_id).delete()
                messages.success(request, "Feriado eliminado.")
            return redirect("configuracion_global")

        elif action == "upload_csv_feriados":
            csv_file = request.FILES.get("csv_feriados")
            if not csv_file:
                messages.error(request, "Debe seleccionar un archivo CSV.")
            elif not csv_file.name.endswith('.csv'):
                messages.error(request, "El archivo debe tener extensión .csv.")
            else:
                try:
                    import csv
                    from io import StringIO
                    decoded_file = csv_file.read().decode('utf-8', errors='ignore')
                    reader = csv.reader(StringIO(decoded_file), delimiter=',')
                    agregados = 0
                    repetidos = 0
                    errores = 0
                    for index, row in enumerate(reader):
                        # Asume formato: YYYY-MM-DD, Descripcion
                        if index == 0 and ("fecha" in str(row).lower() or "date" in str(row).lower()):
                            continue # saltar encabezado
                        if len(row) >= 1:
                            try:
                                fecha_str = row[0].strip()
                                if not fecha_str: continue
                                desc = row[1].strip() if len(row) > 1 else ""
                                fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                                feriado, created = Feriado.objects.get_or_create(
                                    fecha=fecha_obj,
                                    defaults={'descripcion': desc}
                                )
                                if created:
                                    agregados += 1
                                else:
                                    repetidos += 1
                            except ValueError:
                                errores += 1

                    if agregados > 0 and repetidos == 0:
                        msg = f"Se importaron {agregados} feriados exitosamente."
                        if errores > 0: msg += f" ({errores} errores de formato)."
                        messages.success(request, msg)
                    elif agregados > 0 and repetidos > 0:
                        msg = f"Se agregaron {agregados} fecha(s) nueva(s) correctamente, pero {repetidos} fecha(s) fue(ron) ignorada(s) porque ya estaba(n) registrada(s)."
                        if errores > 0: msg += f" ({errores} errores de formato)."
                        messages.warning(request, msg)
                    elif agregados == 0 and repetidos > 0:
                        msg = f"No se agregaron fechas nuevas. Las fechas del archivo ya estaban registradas."
                        if errores > 0: msg += f" ({errores} errores de formato)."
                        messages.error(request, msg)
                    else:
                        msg = "No se encontraron fechas válidas en el archivo CSV."
                        if errores > 0: msg += f" ({errores} filas ignoradas por error de formato)."
                        messages.error(request, msg)
                except Exception as e:
                    messages.error(request, f"Error al procesar el archivo CSV: {str(e)}")
            return redirect("configuracion_global")

        elif action == "sync_feriados":
            try:
                import holidays
                anio = date.today().year

                # Se agregan los de Argentina en general, y los de Chaco ('H')
                ar_holidays = holidays.AR(subdiv='H', years=anio)
                agregados = 0
                repetidos = 0
                for dt, name in ar_holidays.items():
                    feriado, created = Feriado.objects.get_or_create(
                        fecha=dt,
                        defaults={'descripcion': name}
                    )
                    if created:
                        agregados += 1
                    else:
                        repetidos += 1

                if agregados > 0 and repetidos == 0:
                    messages.success(request, f"Se sincronizaron los feriados del año {anio} exitosamente. Se agregaron {agregados} feriados nuevos.")
                elif agregados > 0 and repetidos > 0:
                    messages.warning(request, f"Se agregaron {agregados} feriados nuevos del {anio}, pero {repetidos} ya estaban registrados.")
                elif agregados == 0 and repetidos > 0:
                    messages.error(request, f"No se agregaron feriados nuevos del {anio}. Todos ya estaban registrados en el sistema.")
                else:
                    messages.error(request, f"No se encontraron feriados para el año {anio}.")
            except Exception as e:
                messages.error(request, f"Error al sincronizar feriados: {str(e)}")
            return redirect("configuracion_global")

        else:
            form = ConfiguracionGlobalForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                messages.success(request, "La configuración se actualizó correctamente.")
                return redirect("configuracion_global")
    else:
        form = ConfiguracionGlobalForm(instance=config)

    feriados = Feriado.objects.filter(fecha__year__gte=date.today().year).order_by("fecha")

    return render(request, "reservas/admin/configuracion.html", {
        "form": form,
        "usuario": usuario,
        "feriados": feriados,
    })


# ══════════════════════════════════════════════════════════════════════════════
# API AUXILIAR
# ══════════════════════════════════════════════════════════════════════════════


@login_requerido
def api_calcular_distancia(request):
    """
    API endpoint para calcular la distancia desde UTN FRRE al destino dado.
    """
    from ..utils.services import calcular_distancia_y_tiempo_osrm
    destino = request.GET.get("q", "")
    if not destino:
        return JsonResponse({"distancia_est": 0.0, "duracion_segundos": 0.0})

    km, duracion = calcular_distancia_y_tiempo_osrm(destino)
    return JsonResponse({"distancia_est": km, "duracion_segundos": duracion})


# ══════════════════════════════════════════════════════════════════════════════
# UTILIDAD DE DESARROLLO: Previsualizador de Emails
# ══════════════════════════════════════════════════════════════════════════════


def preview_email(request, template_name):
    """
    Vista de desarrollo para renderizar y visualizar plantillas de correo en el navegador.
    Solo disponible si DEBUG es True (para seguridad en producción).
    """
    if not settings.DEBUG:
        from django.http import Http404
        raise Http404("Preview no disponible en producción.")

    from django.utils import timezone
    from datetime import timedelta

    class MockUser:
        nombre = "Juan"
        apellido = "Pérez"
        correo = "juan.perez@example.com"
        dni = "12345678"
        legajo = "L-999"

    class MockVehiculo:
        marca = "Toyota"
        modelo = "Corolla"
        patente = "AB 123 CD"

    class MockTicket:
        pk = 4059
        id_usuario = MockUser()
        id_vehiculo = MockVehiculo()
        destino = "Facultad de Ingeniería - UTN"
        hora_inicio = timezone.now()
        hora_fin = timezone.now() + timedelta(hours=3)
        observacion = "Este es un texto de ejemplo de una observación."
        distancia_est = 45.5
        cant_pasajeros = 3

    context = {
        "usuario": MockUser(),
        "ticket": MockTicket(),
        "url_sistema": "http://localhost:8000",
        "dias_anticipacion": 2,
        "dias_cancelacion": 1,
    }

    try:
        from django.shortcuts import render
        return render(request, f"reservas/emails/{template_name}.html", context)
    except Exception as e:
        from django.http import HttpResponse
        return HttpResponse(f"Error cargando plantilla '{template_name}': {e}", status=404)
