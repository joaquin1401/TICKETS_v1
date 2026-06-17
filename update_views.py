import re

file_path = "/home/blob/dev/active projects/TICKETS_v1/reservas/views.py"
with open(file_path, "r") as f:
    content = f.read()

import_pattern = r"(from django\.db\.models import Count)"
import_replacement = r"from django.db.models import Count, Sum\nimport json"
content = re.sub(import_pattern, import_replacement, content, count=1)

json_logic = """
    top_usuarios = tickets_periodo.values(
        'id_usuario__nombre', 'id_usuario__apellido', 'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')[:10]

    top_usuarios_json = json.dumps({
        "labels": [f"{u['id_usuario__nombre']} {u['id_usuario__apellido']}" for u in top_usuarios],
        "data": [u['total'] for u in top_usuarios]
    })

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    solicitudes_cargo_json = json.dumps({
        "labels": [c['id_usuario__id_cargo__nombre'] for c in solicitudes_cargo],
        "data": [c['total'] for c in solicitudes_cargo]
    })

    vehiculos_solicitudes = tickets_periodo.values(
        'id_vehiculo__marca', 'id_vehiculo__modelo'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_solicitudes_json = json.dumps({
        "labels": [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']}" for v in vehiculos_solicitudes],
        "data": [v['total'] for v in vehiculos_solicitudes]
    })

    vehiculos_km = tickets_periodo.filter(distancia_real__isnull=False).values(
        'id_vehiculo__marca', 'id_vehiculo__modelo'
    ).annotate(
        total_km=Sum('distancia_real')
    ).order_by('-total_km')

    vehiculos_km_json = json.dumps({
        "labels": [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']}" for v in vehiculos_km],
        "data": [float(v['total_km']) for v in vehiculos_km]
    })
"""

# Replace the old top_usuarios logic in reporte_analiticas
old_logic = """    top_usuarios = tickets_periodo.values(
        'id_usuario__nombre', 'id_usuario__apellido', 'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')[:5]

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')"""

content = content.replace(old_logic, json_logic, 1)

# Add variables to context dict
old_context = """"top_usuarios":              top_usuarios,
        "solicitudes_cargo":         solicitudes_cargo,"""

new_context = """"top_usuarios":              top_usuarios,
        "solicitudes_cargo":         solicitudes_cargo,
        "top_usuarios_json":         top_usuarios_json,
        "solicitudes_cargo_json":    solicitudes_cargo_json,
        "vehiculos_solicitudes_json": vehiculos_solicitudes_json,
        "vehiculos_km_json":         vehiculos_km_json,"""

content = content.replace(old_context, new_context, 1)

with open(file_path, "w") as f:
    f.write(content)

print("Updated views.py")
