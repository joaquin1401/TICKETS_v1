import re

file_path = "/home/blob/dev/active projects/TICKETS_v1/reservas/templates/reservas/analiticas.html"
with open(file_path, "r") as f:
    content = f.read()

# Replace the tables with canvas elements
users_behavior_section = """<!-- ═══════════════════════════════════════════════════════
      Comportamiento de Usuarios
     ═══════════════════════════════════════════════════════ -->
<div class="act-label" style="margin-top:36px;">Comportamiento de Usuarios</div>
<div class="kpi-grid" style="grid-template-columns: 1fr 1fr; gap: 20px;">
  
  <div class="card report-card" style="margin: 0;">
    <div class="card-header">
      <span class="card-title">◧ Top 10 Usuarios</span>
      <span class="badge badge-neutral">con más solicitudes</span>
    </div>
    <div style="padding: 20px;">
      <canvas id="topUsuariosChart"></canvas>
    </div>
  </div>

  <div class="card report-card" style="margin: 0;">
    <div class="card-header">
      <span class="card-title">◧ Solicitudes por Cargo</span>
      <span class="badge badge-neutral">distribución</span>
    </div>
    <div style="padding: 20px;">
      <canvas id="cargosChart"></canvas>
    </div>
  </div>

</div>

<!-- ═══════════════════════════════════════════════════════
      Análisis de Vehículos
     ═══════════════════════════════════════════════════════ -->
<div class="act-label" style="margin-top:36px;">Análisis de Flota</div>
<div class="kpi-grid" style="grid-template-columns: 1fr 1fr; gap: 20px;">
  
  <div class="card report-card" style="margin: 0;">
    <div class="card-header">
      <span class="card-title">◧ Vehículos vs Solicitudes</span>
    </div>
    <div style="padding: 20px;">
      <canvas id="vehiculosSolicitudesChart"></canvas>
    </div>
  </div>

  <div class="card report-card" style="margin: 0;">
    <div class="card-header">
      <span class="card-title">◧ Vehículos vs Kilómetros</span>
    </div>
    <div style="padding: 20px;">
      <canvas id="vehiculosKmChart"></canvas>
    </div>
  </div>

</div>"""

# Find where "Comportamiento de Usuarios" starts and replace until the footer
start_idx = content.find("<!-- ═══════════════════════════════════════════════════════\n      Comportamiento de Usuarios")
end_idx = content.find("<!-- Nota de pie para el PDF -->")

new_content = content[:start_idx] + users_behavior_section + "\n\n" + content[end_idx:]

# Add Chart.js and DataLabels plugin
scripts = """
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels"></script>
<script>
  Chart.register(ChartDataLabels);
  
  const commonOptions = {
    responsive: true,
    plugins: {
      legend: { display: false },
      datalabels: {
        color: '#fff',
        font: { weight: 'bold' },
        anchor: 'end',
        align: 'left',
        formatter: Math.round
      }
    }
  };

  const topUsuariosData = {{ top_usuarios_json|safe }};
  new Chart(document.getElementById('topUsuariosChart'), {
    type: 'bar',
    data: {
      labels: topUsuariosData.labels,
      datasets: [{
        data: topUsuariosData.data,
        backgroundColor: '#4ade80',
        borderRadius: 4
      }]
    },
    options: {
      ...commonOptions,
      indexAxis: 'y',
    }
  });

  const cargosData = {{ solicitudes_cargo_json|safe }};
  new Chart(document.getElementById('cargosChart'), {
    type: 'pie',
    data: {
      labels: cargosData.labels,
      datasets: [{
        data: cargosData.data,
        backgroundColor: ['#4ade80', '#38bdf8', '#fbbf24', '#f87171', '#a78bfa']
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'right' },
        datalabels: {
          color: '#fff',
          font: { weight: 'bold' },
          formatter: Math.round
        }
      }
    }
  });

  const vehiculosSolData = {{ vehiculos_solicitudes_json|safe }};
  new Chart(document.getElementById('vehiculosSolicitudesChart'), {
    type: 'bar',
    data: {
      labels: vehiculosSolData.labels,
      datasets: [{
        data: vehiculosSolData.data,
        backgroundColor: '#38bdf8',
        borderRadius: 4
      }]
    },
    options: {
      ...commonOptions,
      indexAxis: 'y',
    }
  });

  const vehiculosKmData = {{ vehiculos_km_json|safe }};
  new Chart(document.getElementById('vehiculosKmChart'), {
    type: 'bar',
    data: {
      labels: vehiculosKmData.labels,
      datasets: [{
        data: vehiculosKmData.data,
        backgroundColor: '#a78bfa',
        borderRadius: 4
      }]
    },
    options: {
      ...commonOptions,
      indexAxis: 'y',
      plugins: {
        ...commonOptions.plugins,
        datalabels: {
          ...commonOptions.plugins.datalabels,
          formatter: function(value) { return value + ' km'; }
        }
      }
    }
  });
</script>
"""

new_content = new_content.replace("{% endblock %}", scripts + "\n{% endblock %}")

with open(file_path, "w") as f:
    f.write(new_content)

print("Updated analiticas.html")
