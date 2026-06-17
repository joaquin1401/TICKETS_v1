import re

file_path = "/home/blob/dev/active projects/TICKETS_v1/reservas/templates/reservas/analiticas.html"
with open(file_path, "r") as f:
    content = f.read()

# Define the script string exactly as it was injected
script_to_remove = """<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
</script>"""

# Replace all occurrences
new_content = content.replace(script_to_remove + "\n", "")
new_content = new_content.replace(script_to_remove, "")

# Now add it cleanly at the end
final_content = new_content + "\n{% block extra_js %}\n" + script_to_remove + "\n{% endblock %}\n"

with open(file_path, "w") as f:
    f.write(final_content)

print("Fixed analiticas.html")
