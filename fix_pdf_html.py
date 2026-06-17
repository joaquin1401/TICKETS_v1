import re

file_path = "/home/blob/dev/active projects/TICKETS_v1/reservas/templates/reservas/analiticas_pdf.html"
with open(file_path, "r") as f:
    content = f.read()

# Replace Top Usuarios table
old_top_usuarios = """        {% if top_usuarios %}
        <table>
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
                  {% if forloop.first %}<span class="leader-crown">★</span>{% endif %}
                  {{ u.id_usuario__nombre }} {{ u.id_usuario__apellido }}
                </div>
              </td>
              <td><span class="badge badge-neutral">{{ u.id_usuario__id_cargo__nombre }}</span></td>
              <td class="align-right">{{ u.total }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% endif %}"""

new_top_usuarios = """        {% if chart_top_usuarios %}
        <div style="padding: 10pt; text-align: center;">
          <img src="{{ chart_top_usuarios }}" alt="Top Usuarios" style="max-width: 100%; height: auto;">
        </div>
        {% endif %}"""

content = content.replace(old_top_usuarios, new_top_usuarios)

# Replace Cargos table
old_cargos = """        {% if solicitudes_cargo %}
        <table>
          <thead>
            <tr>
              <th>Cargo</th>
              <th class="align-right">Total Solicitudes</th>
            </tr>
          </thead>
          <tbody>
            {% for c in solicitudes_cargo %}
            <tr>
              <td>{{ c.id_usuario__id_cargo__nombre }}</td>
              <td class="align-right">{{ c.total }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% endif %}"""

new_cargos = """        {% if chart_cargos %}
        <div style="padding: 10pt; text-align: center;">
          <img src="{{ chart_cargos }}" alt="Solicitudes por Cargo" style="max-width: 100%; height: auto;">
        </div>
        {% endif %}"""

content = content.replace(old_cargos, new_cargos)

with open(file_path, "w") as f:
    f.write(content)

print("PDF HTML updated.")
