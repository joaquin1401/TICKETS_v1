import re
file_path = "/home/blob/dev/active projects/TICKETS_v1/reservas/views.py"

with open(file_path, "r") as f:
    content = f.read()

# For reporte_analiticas_pdf:
import_statement = "from .chart_utils import generar_grafico_barras_horizontal, generar_grafico_torta\n    "
if "from .chart_utils import generar_grafico_barras_horizontal" not in content.split("def reporte_analiticas_pdf")[1]:
    content = content.replace("from weasyprint import HTML", "from weasyprint import HTML\n    from django.db.models import Sum\n    " + import_statement)

# We need to compute vehiculos_solicitudes and vehiculos_km since they are not in the PDF view right now.
# The PDF view only has top_usuarios and solicitudes_cargo.
pdf_new_logic = """
    top_usuarios = tickets_periodo.values(
        'id_usuario__nombre', 'id_usuario__apellido', 'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')[:10]

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_solicitudes = tickets_periodo.values(
        'id_vehiculo__marca', 'id_vehiculo__modelo', 'id_vehiculo__patente'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_km = tickets_periodo.filter(distancia_real__isnull=False).values(
        'id_vehiculo__marca', 'id_vehiculo__modelo', 'id_vehiculo__patente'
    ).annotate(
        total_km=Sum('distancia_real')
    ).order_by('-total_km')

    # Gráficos con Matplotlib
    l_top = [f"{u['id_usuario__nombre']} {u['id_usuario__apellido']}" for u in top_usuarios]
    d_top = [u['total'] for u in top_usuarios]
    chart_top_usuarios = generar_grafico_barras_horizontal(l_top, d_top)

    l_cargos = [c['id_usuario__id_cargo__nombre'] for c in solicitudes_cargo]
    d_cargos = [c['total'] for c in solicitudes_cargo]
    chart_cargos = generar_grafico_torta(l_cargos, d_cargos)

    l_veh_sol = [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente'] or ''}".strip() for v in vehiculos_solicitudes]
    d_veh_sol = [v['total'] for v in vehiculos_solicitudes]
    chart_vehiculos_sol = generar_grafico_barras_horizontal(l_veh_sol, d_veh_sol)

    l_veh_km = [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente'] or ''}".strip() for v in vehiculos_km]
    d_veh_km = [float(v['total_km']) for v in vehiculos_km]
    chart_vehiculos_km = generar_grafico_barras_horizontal(l_veh_km, d_veh_km, "{} km")
"""

# Context update for reporte_analiticas_pdf
old_context_2 = """"top_usuarios":              top_usuarios,
        "solicitudes_cargo":         solicitudes_cargo,"""

new_context_2 = """"top_usuarios":              top_usuarios,
        "solicitudes_cargo":         solicitudes_cargo,
        "chart_top_usuarios":        chart_top_usuarios,
        "chart_cargos":              chart_cargos,
        "chart_vehiculos_sol":       chart_vehiculos_sol,
        "chart_vehiculos_km":        chart_vehiculos_km,"""

# First, extract the old block from top_usuarios to solicitudes_cargo in PDF view
match = re.search(r"    top_usuarios = tickets_periodo.*?\}\)\.order_by\('-total'\)", content[content.find("def reporte_analiticas_pdf"):], re.DOTALL)
if match:
    # We replace only the first occurrence after def reporte_analiticas_pdf
    prefix = content[:content.find("def reporte_analiticas_pdf")]
    suffix = content[content.find("def reporte_analiticas_pdf"):]
    suffix = suffix.replace(match.group(0), pdf_new_logic.strip(), 1)
    content = prefix + suffix

    prefix = content[:content.find("def reporte_analiticas_pdf")]
    suffix = content[content.find("def reporte_analiticas_pdf"):]
    suffix = suffix.replace(old_context_2, new_context_2, 1)
    content = prefix + suffix

with open(file_path, "w") as f:
    f.write(content)

print("Patched views.py for PDF")
