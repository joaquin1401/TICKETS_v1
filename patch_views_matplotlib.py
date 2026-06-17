import re
file_path = "/home/blob/dev/active projects/TICKETS_v1/reservas/views.py"

with open(file_path, "r") as f:
    content = f.read()

# Make sure we import the new functions
import_statement = "from .chart_utils import generar_grafico_barras_horizontal, generar_grafico_torta\n"
if "from .chart_utils import" not in content:
    content = content.replace("from django.db.models import Count, Sum\n    import json", "from django.db.models import Count, Sum\n    import json\n    " + import_statement)

# Now, we find the section where we generate JSON and replace it
# For reporte_analiticas:
json_generation_start = "top_usuarios_json = json.dumps({"
json_generation_end = "vehiculos_km_json = json.dumps({\n        \"labels\": [f\"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente'] or ''}\".strip() for v in vehiculos_km],\n        \"data\": [float(v['total_km']) for v in vehiculos_km]\n    })"

new_generation = """
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

# Context update for reporte_analiticas
old_context_1 = """"top_usuarios_json":         top_usuarios_json,
        "solicitudes_cargo_json":    solicitudes_cargo_json,
        "vehiculos_solicitudes_json": vehiculos_solicitudes_json,
        "vehiculos_km_json":         vehiculos_km_json,"""

new_context_1 = """"chart_top_usuarios":        chart_top_usuarios,
        "chart_cargos":              chart_cargos,
        "chart_vehiculos_sol":       chart_vehiculos_sol,
        "chart_vehiculos_km":        chart_vehiculos_km,"""

# First, extract everything from top_usuarios_json to the end of vehiculos_km_json block
match = re.search(r'top_usuarios_json = json\.dumps\(\{.*?vehiculos_km_json = json\.dumps\(\{.*?\}\)', content, re.DOTALL)
if match:
    content = content.replace(match.group(0), new_generation)

content = content.replace(old_context_1, new_context_1)

with open(file_path, "w") as f:
    f.write(content)

print("Patched views.py for HTML")
