import os
import re

SOURCE_FILE = "reservas/templates/reservas/chofer_dashboard.html"
TEMPLATE_DIR = "reservas/templates/reservas/"

with open(SOURCE_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# We want to extract the common parts: header and stats
# Then extract the three sections: en curso, disponibles, finalizados
# And build 3 separate files.

# Common header goes up to <div class="stats-grid">...</div>
header_pattern = re.compile(r"^(.*?<div class=\"stats-grid\">.*?</div>)", re.DOTALL)
header_match = header_pattern.search(content)
common_header = header_match.group(1) if header_match else ""

# Replace the variables in the stats grid
common_header = common_header.replace(
    "{{ tickets_en_curso|length }}", "{{ count_en_curso }}"
).replace(
    "{{ tickets_disponibles|length }}", "{{ count_disponibles }}"
).replace(
    "{{ tickets_finalizados|length }}", "{{ count_finalizados }}"
)

# Extract sections based on headers
en_curso_pattern = re.compile(r"(<h2.*?Mis Viajes en Curso.*?)(?=<h2.*?Viajes Disponibles)", re.DOTALL)
disponibles_pattern = re.compile(r"(<h2.*?Viajes Disponibles.*?)(?=<h2.*?Últimos Viajes)", re.DOTALL)
finalizados_pattern = re.compile(r"(<h2.*?Últimos Viajes Finalizados.*?)({% endblock %})", re.DOTALL)

en_curso_match = en_curso_pattern.search(content)
disponibles_match = disponibles_pattern.search(content)
finalizados_match = finalizados_pattern.search(content)

en_curso_html = en_curso_match.group(1) if en_curso_match else ""
disponibles_html = disponibles_match.group(1) if disponibles_match else ""
finalizados_html = finalizados_match.group(1) if finalizados_match else ""

# Save chofer_en_curso.html
with open(os.path.join(TEMPLATE_DIR, "chofer_en_curso.html"), "w", encoding="utf-8") as f:
    f.write(common_header + "\n" + en_curso_html + "\n{% endblock %}\n")

# Save chofer_disponibles.html
with open(os.path.join(TEMPLATE_DIR, "chofer_disponibles.html"), "w", encoding="utf-8") as f:
    f.write(common_header + "\n" + disponibles_html + "\n{% endblock %}\n")

# Save chofer_finalizados.html
with open(os.path.join(TEMPLATE_DIR, "chofer_finalizados.html"), "w", encoding="utf-8") as f:
    f.write(common_header + "\n" + finalizados_html + "\n{% endblock %}\n")

print("Templates created.")
