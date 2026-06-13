import os
import re

VIEWS_FILE = "reservas/views.py"
URLS_FILE = "reservas/urls.py"
BASE_HTML = "reservas/templates/reservas/base.html"

# 1. Update views.py
with open(VIEWS_FILE, "r", encoding="utf-8") as f:
    views_content = f.read()

new_views = """
@login_requerido
@chofer_requerido
def chofer_disponibles(request):
    usuario = get_usuario_sesion(request)
    from django.utils import timezone
    
    tickets_disponibles_qs = Ticket.objects.filter(
        estado=Ticket.ESTADO_APROBADO, 
        conductor__isnull=True,
        hora_inicio__gte=timezone.now()
    ).select_related('id_vehiculo').order_by('hora_inicio')
    page_obj, pagination_query = paginate_queryset(request, tickets_disponibles_qs)
    
    context = {
        "usuario": usuario,
        "tickets_disponibles": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "count_en_curso": Ticket.objects.filter(estado=Ticket.ESTADO_EN_CURSO, conductor=usuario).count(),
        "count_disponibles": tickets_disponibles_qs.count(),
        "count_finalizados": Ticket.objects.filter(estado=Ticket.ESTADO_FINALIZADO, conductor=usuario).count()
    }
    return render(request, "reservas/chofer_disponibles.html", context)

@login_requerido
@chofer_requerido
def chofer_en_curso(request):
    usuario = get_usuario_sesion(request)
    from django.utils import timezone
    
    tickets_en_curso = Ticket.objects.filter(
        estado=Ticket.ESTADO_EN_CURSO,
        conductor=usuario
    ).select_related('id_vehiculo').order_by('hora_inicio')
    
    context = {
        "usuario": usuario,
        "tickets_en_curso": tickets_en_curso,
        "count_en_curso": tickets_en_curso.count(),
        "count_disponibles": Ticket.objects.filter(estado=Ticket.ESTADO_APROBADO, conductor__isnull=True, hora_inicio__gte=timezone.now()).count(),
        "count_finalizados": Ticket.objects.filter(estado=Ticket.ESTADO_FINALIZADO, conductor=usuario).count()
    }
    return render(request, "reservas/chofer_en_curso.html", context)

@login_requerido
@chofer_requerido
def chofer_finalizados(request):
    usuario = get_usuario_sesion(request)
    from django.utils import timezone
    
    tickets_finalizados = Ticket.objects.filter(
        estado=Ticket.ESTADO_FINALIZADO,
        conductor=usuario
    ).select_related('id_vehiculo').order_by('-hora_inicio')[:20]
    
    context = {
        "usuario": usuario,
        "tickets_finalizados": tickets_finalizados,
        "count_en_curso": Ticket.objects.filter(estado=Ticket.ESTADO_EN_CURSO, conductor=usuario).count(),
        "count_disponibles": Ticket.objects.filter(estado=Ticket.ESTADO_APROBADO, conductor__isnull=True, hora_inicio__gte=timezone.now()).count(),
        "count_finalizados": Ticket.objects.filter(estado=Ticket.ESTADO_FINALIZADO, conductor=usuario).count()
    }
    return render(request, "reservas/chofer_finalizados.html", context)
"""

# Replace chofer_dashboard in views.py
target_view = re.search(r"@login_requerido\n@chofer_requerido\ndef chofer_dashboard.*?return render.*?\}\)", views_content, re.DOTALL)
if target_view:
    # Also add a redirect for chofer_dashboard just in case
    redirect_view = """
@login_requerido
@chofer_requerido
def chofer_dashboard(request):
    return redirect("chofer_disponibles")
"""
    views_content = views_content[:target_view.start()] + redirect_view + new_views + views_content[target_view.end():]
    with open(VIEWS_FILE, "w", encoding="utf-8") as f:
        f.write(views_content)
else:
    print("Could not find chofer_dashboard in views.py")

# 2. Update urls.py
with open(URLS_FILE, "r", encoding="utf-8") as f:
    urls_content = f.read()

new_urls = """    path("chofer/dashboard/", views.chofer_dashboard, name="chofer_dashboard"),
    path("chofer/disponibles/", views.chofer_disponibles, name="chofer_disponibles"),
    path("chofer/en-curso/", views.chofer_en_curso, name="chofer_en_curso"),
    path("chofer/finalizados/", views.chofer_finalizados, name="chofer_finalizados"),"""

target_url = 'path("chofer/dashboard/", views.chofer_dashboard, name="chofer_dashboard"),'
if target_url in urls_content:
    urls_content = urls_content.replace(target_url, new_urls)
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        f.write(urls_content)

# 3. Update base.html menu
with open(BASE_HTML, "r", encoding="utf-8") as f:
    base_content = f.read()

menu_chofer_target = """    <div class="sidebar-section">
      <div class="sidebar-section-label">Menú de Viajes</div>
      <a href="{% url 'chofer_dashboard' %}"
        class="nav-item {% if request.resolver_match.url_name == 'chofer_dashboard' %}active{% endif %}">
        <span class="icon">⬡</span> Panel de Chofer
      </a>
    </div>"""

menu_chofer_new = """    <div class="sidebar-section">
      <div class="sidebar-section-label">Menú de Viajes</div>
      <a href="{% url 'chofer_disponibles' %}" class="nav-item {% if request.resolver_match.url_name == 'chofer_disponibles' %}active{% endif %}">
        <span class="icon">◎</span> Viajes Disponibles
      </a>
      <a href="{% url 'chofer_en_curso' %}" class="nav-item {% if request.resolver_match.url_name == 'chofer_en_curso' %}active{% endif %}">
        <span class="icon">◉</span> Viajes en Curso
      </a>
      <a href="{% url 'chofer_finalizados' %}" class="nav-item {% if request.resolver_match.url_name == 'chofer_finalizados' %}active{% endif %}">
        <span class="icon">◌</span> Viajes Finalizados
      </a>
    </div>"""

menu_admin_target = """      <a href="{% url 'chofer_dashboard' %}"
        class="nav-item {% if request.resolver_match.url_name == 'chofer_dashboard' %}active{% endif %}">
        <span class="icon">⬡</span> Panel de Chofer
      </a>"""

menu_admin_new = """      <a href="{% url 'chofer_disponibles' %}" class="nav-item {% if request.resolver_match.url_name == 'chofer_disponibles' %}active{% endif %}">
        <span class="icon">◎</span> Viajes Disponibles (Chofer)
      </a>
      <a href="{% url 'chofer_en_curso' %}" class="nav-item {% if request.resolver_match.url_name == 'chofer_en_curso' %}active{% endif %}">
        <span class="icon">◉</span> Viajes en Curso (Chofer)
      </a>
      <a href="{% url 'chofer_finalizados' %}" class="nav-item {% if request.resolver_match.url_name == 'chofer_finalizados' %}active{% endif %}">
        <span class="icon">◌</span> Viajes Finalizados (Chofer)
      </a>"""

base_content = base_content.replace(menu_chofer_target, menu_chofer_new)
base_content = base_content.replace(menu_admin_target, menu_admin_new)

with open(BASE_HTML, "w", encoding="utf-8") as f:
    f.write(base_content)

print("Files modified successfully.")
