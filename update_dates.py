import sys
import os

files_to_update = [
    "reservas/templates/reservas/historial.html",
    "reservas/templates/reservas/historial_tickets.html",
    "reservas/templates/reservas/detalle_usuario.html",
    "reservas/templates/reservas/monitor_activos.html",
]

for file_path in files_to_update:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Historial y Detalle Usuario (d/m/Y H:i)
    target1 = """          <td class="text-mono">{{ t.hora_inicio|date:"d/m/Y H:i" }}</td>
          <td class="text-mono">{% if t.hora_fin %}{{ t.hora_fin|date:"d/m/Y H:i" }}{% else %}<span class="text-muted">—</span>{% endif %}</td>"""
    
    replace1 = """          <td class="text-mono">
            <div>{{ t.hora_inicio|date:"d/m/Y H:i" }}</div>
            {% if t.hora_inicio_real %}<div style="color:var(--text);font-weight:600;font-size:11px;margin-top:2px;">R: {{ t.hora_inicio_real|date:"d/m/Y H:i" }}</div>{% endif %}
          </td>
          <td class="text-mono">
            <div>{% if t.hora_fin %}{{ t.hora_fin|date:"d/m/Y H:i" }}{% else %}<span class="text-muted">—</span>{% endif %}</div>
            {% if t.hora_fin_real %}<div style="color:var(--text);font-weight:600;font-size:11px;margin-top:2px;">R: {{ t.hora_fin_real|date:"d/m/Y H:i" }}</div>{% endif %}
          </td>"""

    if target1 in content:
        content = content.replace(target1, replace1)

    # Monitor Activos (d/m H:i)
    target2 = """          <td class="text-mono">{{ t.hora_inicio|date:"d/m H:i" }}</td>
          <td class="text-mono">{% if t.hora_fin %}{{ t.hora_fin|date:"d/m H:i" }}{% else %}<span class="text-muted">—</span>{% endif %}</td>"""

    replace2 = """          <td class="text-mono">
            <div>{{ t.hora_inicio|date:"d/m H:i" }}</div>
            {% if t.hora_inicio_real %}<div style="color:var(--text);font-weight:600;font-size:11px;margin-top:2px;">R: {{ t.hora_inicio_real|date:"d/m H:i" }}</div>{% endif %}
          </td>
          <td class="text-mono">
            <div>{% if t.hora_fin %}{{ t.hora_fin|date:"d/m H:i" }}{% else %}<span class="text-muted">—</span>{% endif %}</div>
            {% if t.hora_fin_real %}<div style="color:var(--text);font-weight:600;font-size:11px;margin-top:2px;">R: {{ t.hora_fin_real|date:"d/m H:i" }}</div>{% endif %}
          </td>"""
          
    if target2 in content:
        content = content.replace(target2, replace2)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

print("Dates updated.")
