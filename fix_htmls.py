import re

for filename in ["analiticas.html", "analiticas_pdf.html"]:
    file_path = f"/home/blob/dev/active projects/TICKETS_v1/reservas/templates/reservas/{filename}"
    with open(file_path, "r") as f:
        content = f.read()
    
    # Remove script tags if any exist (in analiticas.html, user might have left something or not)
    content = re.sub(r'<script.*?</script>', '', content, flags=re.DOTALL)
    
    # We replace the top 10 usuarios section
    old_top_usuarios = """<div class="card-header">
      <span class="card-title">◧ Top 10 Usuarios</span>
      <span class="badge badge-neutral">con más solicitudes</span>
    </div>
    {% if top_usuarios %}
    <div class="table-wrap">
      <table class="fleet-table">
        <thead>
          <tr>
            <th>Usuario</th>
            <th>Cargo</th>
            <th class="align-right">Solicitudes</th>
          </tr>
        </thead>
        <tbody>
          {% for u in top_usuarios %}
          <tr class="{% if forloop.first %}row-leader{% endif %}">
            <td>
              <div class="vehicle-name">
                {% if forloop.first %}<span class="leader-crown" title="Usuario más activo">★</span>{% endif %}
                <span class="primary">{{ u.id_usuario__nombre }} {{ u.id_usuario__apellido }}</span>
              </div>
            </td>
            <td><span class="badge badge-neutral">{{ u.id_usuario__id_cargo__nombre }}</span></td>
            <td class="align-right text-mono">{{ u.total }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="empty-state" style="padding: 20px;">
      <p>No hay solicitudes registradas.</p>
    </div>
    {% endif %}"""

    new_top_usuarios = """<div class="card-header">
      <span class="card-title">◧ Top 10 Usuarios</span>
      <span class="badge badge-neutral">con más solicitudes</span>
    </div>
    {% if chart_top_usuarios %}
    <div style="padding: 20px; text-align: center;">
      <img src="{{ chart_top_usuarios }}" alt="Top Usuarios" style="max-width: 100%; height: auto;">
    </div>
    {% else %}
    <div class="empty-state" style="padding: 20px;">
      <p>No hay solicitudes registradas.</p>
    </div>
    {% endif %}"""
    
    if old_top_usuarios in content:
        content = content.replace(old_top_usuarios, new_top_usuarios)
    
    # Same for cargos
    old_cargos = """<div class="card-header">
      <span class="card-title">◧ Solicitudes por Cargo</span>
      <span class="badge badge-neutral">distribución</span>
    </div>
    {% if solicitudes_cargo %}
    <div class="table-wrap">
      <table class="fleet-table">
        <thead>
          <tr>
            <th>Cargo</th>
            <th class="align-right">Total Solicitudes</th>
          </tr>
        </thead>
        <tbody>
          {% for c in solicitudes_cargo %}
          <tr>
            <td><span class="primary">{{ c.id_usuario__id_cargo__nombre }}</span></td>
            <td class="align-right text-mono">{{ c.total }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="empty-state" style="padding: 20px;">
      <p>No hay solicitudes registradas.</p>
    </div>
    {% endif %}"""

    new_cargos = """<div class="card-header">
      <span class="card-title">◧ Solicitudes por Cargo</span>
      <span class="badge badge-neutral">distribución</span>
    </div>
    {% if chart_cargos %}
    <div style="padding: 20px; max-width: 500px; margin: 0 auto; text-align: center;">
      <img src="{{ chart_cargos }}" alt="Cargos" style="max-width: 100%; height: auto;">
    </div>
    {% else %}
    <div class="empty-state" style="padding: 20px;">
      <p>No hay solicitudes registradas.</p>
    </div>
    {% endif %}"""

    if old_cargos in content:
        content = content.replace(old_cargos, new_cargos)
        
    # Append the vehicles charts at the end of the sections
    new_vehiculos = """<!-- ═══════════════════════════════════════════════════════
      Análisis de Vehículos
     ═══════════════════════════════════════════════════════ -->
<div class="act-label" style="margin-top:36px;">Análisis de Flota</div>
<div class="kpi-grid" style="grid-template-columns: 1fr 1fr; gap: 20px;">
  
  <div class="card report-card" style="margin: 0;">
    <div class="card-header">
      <span class="card-title">◧ Vehículos vs Solicitudes</span>
    </div>
    {% if chart_vehiculos_sol %}
    <div style="padding: 20px; text-align: center;">
      <img src="{{ chart_vehiculos_sol }}" alt="Vehículos vs Solicitudes" style="max-width: 100%; height: auto;">
    </div>
    {% else %}
    <div class="empty-state" style="padding: 20px;">
      <p>No hay datos.</p>
    </div>
    {% endif %}
  </div>

  <div class="card report-card" style="margin: 0;">
    <div class="card-header">
      <span class="card-title">◧ Vehículos vs Kilómetros</span>
    </div>
    {% if chart_vehiculos_km %}
    <div style="padding: 20px; text-align: center;">
      <img src="{{ chart_vehiculos_km }}" alt="Vehículos vs Km" style="max-width: 100%; height: auto;">
    </div>
    {% else %}
    <div class="empty-state" style="padding: 20px;">
      <p>No hay datos.</p>
    </div>
    {% endif %}
  </div>

</div>

"""
    if "Análisis de Flota" not in content:
        # insert before report footer
        idx = content.find("<!-- Nota de pie para el PDF -->")
        if idx != -1:
            content = content[:idx] + new_vehiculos + content[idx:]
        else:
            idx = content.find("<div class=\"report-footer\">")
            if idx != -1:
                content = content[:idx] + new_vehiculos + content[idx:]

    # Remove the empty block extra_js
    content = content.replace("{% block extra_js %}\n{% endblock %}", "")
    
    with open(file_path, "w") as f:
        f.write(content)

print("HTMLs updated.")
