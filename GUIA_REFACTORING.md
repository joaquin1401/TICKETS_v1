# Guía de Refactoring - Arquitectura Limpia Django

**Versión:** 1.0  
**Fecha:** May 2025  
**Estado:** Implementación Fase 1 (Core)

---

## 📋 Resumen Ejecutivo

Se refactoriza el código del sistema de reservas siguiendo principios de **arquitectura limpia**, **SOLID** y **DRY**. El objetivo es:

- ✅ **Separación de responsabilidades**: Models, Views, Services, Selectors independientes
- ✅ **Reutilización**: Managers, Selectors, Decorators, Utils centralizados
- ✅ **Mantenibilidad**: Código con docstrings, type hints, comentarios justificativos
- ✅ **Rendimiento**: Optimización de queries (select_related, prefetch_related)
- ✅ **Escalabilidad**: Preparado para APIs y múltiples interfaces

---

## 🏗️ Arquitectura Propuesta

```
reservas/
├── models.py                    # [ACTUALIZADO] Modelos + Managers
├── selectors.py                 # [NUEVO] Funciones de lectura (queries)
├── services.py                  # [LEGADO] Compatibilidad (apunta a selectors)
├── decorators.py                # [NUEVO] @login_requerido, @admin_requerido
├── middleware.py                # [NUEVO] Inyecta usuario en request.user
├── validators.py                # [NUEVO] Validadores reutilizables
├── utils.py                     # [NUEVO] Funciones auxiliares
├── views.py                     # [EXISTENTE] Migrando gradualmente
├── views_refactored_example.py  # [REFERENCIA] Ejemplos de vistas refactorizadas
├── forms.py                     # [EXISTENTE] Sin cambios aún
└── admin.py                     # [EXISTENTE] Sin cambios aún
```

---

## 📦 Componentes Implementados

### 1. **models.py** (REFACTORIZADO)
**Cambios:**
- ✅ Agregados **Managers personalizados**: `UsuarioManager`, `VehiculoManager`, `TicketManager`
- ✅ Métodos de conveniencia en Manager:
  - `Usuario.objects.activos()` → Solo usuarios aprobados
  - `Usuario.objects.pendientes()` → Pendientes de aprobación
  - `Ticket.objects.aprobados()` → Con select_related precargado
  - `Ticket.objects.del_usuario(usuario)` → Tickets de usuario optimizados
  - `Ticket.objects.del_vehiculo_en_rango(vehiculo, inicio, fin)` → Conflictos detectados
- ✅ Agregados type hints en métodos
- ✅ Método `clean()` para validaciones
- ✅ Propiedades útiles: `Usuario.puede_ingresar()`, `Usuario.es_admin`, `Ticket.puede_ser_cancelado()`
- ✅ Índices de BD para queries frecuentes (valido, rechazado, estado, hora_inicio)
- ✅ Docstrings detallados explicando diseño

**Por qué:**
- Managers centraliza queries duplicadas → una línea en vista en lugar de 3-5
- select_related en managers evita N+1 queries automáticamente
- Índices aceleran filtrados frecuentes (login, búsquedas de estado)

---

### 2. **selectors.py** (NUEVO)
**Patrón:** Funciones de lectura (READ-ONLY) que encapsulan queries complejas

**Funciones principales:**
- `get_usuario_por_correo_con_cargo(correo)` → Para login (evita 2 queries)
- `get_tickets_usuario(usuario)` → Todos los tickets de usuario (optimizado)
- `get_tickets_aprobados_mes(vehiculo, anio, mes)` → Para calendario
- `get_dias_con_reservas(vehiculo, anio, mes)` → Qué días están ocupados
- `get_conflictos_ticket(vehiculo, inicio, fin)` → Detecta overlaps
- `buscar_usuarios(busqueda, cargo)` → Búsqueda avanzada con filtros
- `get_tickets_activos_empresa()` → Monitor para admin

**Por qué:**
- Encapsulan queries complejas con select_related predefinido
- Evitan duplicación en múltiples vistas (DRY)
- Si necesito cambiar una query, cambio en 1 lugar
- Fácil de testear (función pura, sin side effects)
- Preparado para APIs (misma función sirve para REST)

---

### 3. **middleware.py** (NUEVO)
**Clase:** `UsuarioSessionMiddleware`

**Qué hace:**
- Ejecuta antes de cada request
- Lee `request.session["usuario_id"]`
- Busca Usuario en BD con `select_related("id_cargo")`
- Inyecta en `request.user` (similar a Django's auth)
- También inyecta `request.es_admin` (bool)

**Instalación en settings.py:**
```python
MIDDLEWARE = [
    # ... otros middleware
    'reservas.middleware.UsuarioSessionMiddleware',
]
```

**Por qué:**
- Elimina `get_usuario_sesion(request)` de cada vista
- `request.user` disponible en templates sin pasar contexto extra
- Estandariza patrón de Django (similar a User model)
- Centraliza lógica de obtención de usuario

---

### 4. **decorators.py** (NUEVO)
**Decoradores:**

```python
@login_requerido
def dashboard(request):  # Redirige al login si no hay sesión
    ...

@admin_requerido
def panel_admin(request):  # Redirige si no es admin (debe ir después de login_requerido)
    ...

@requiere_usuario_activo
def historial(request):  # Valida que usuario esté aprobado
    ...
```

**Por qué:**
- Evita duplicar código de validación en cada vista
- Una línea vs 5-10 líneas de validación manual
- Centraliza reglas de acceso (cambio en 1 lugar)

---

### 5. **validators.py** (NUEVO)
**Validadores reutilizables:**

- `validar_contrasena_fuerte(password)` → 8 chars, mayús, minús, número
- `validar_rango_horario(inicio, fin)` → Valida que sean válidos, < 24h
- `validar_cantidad_pasajeros(cant, max_vehiculo)` → No excede capacidad
- `validar_prioridad_unica(prioridad)` → No duplica prioridad en cargos

**Uso:**
```python
try:
    validar_contrasena_fuerte(password)
except ValidationError as e:
    form.add_error('password', str(e))
```

**Por qué:**
- Reutilizable en models, forms, serializers
- Una fuente de verdad para reglas de validación
- Fácil de testear independientemente

---

### 6. **utils.py** (NUEVO)
**Funciones auxiliares:**

- `obtener_rango_mes(anio, mes)` → Límites de un mes para queries
- `es_pasado(datetime)` → Verifica si datetime pasó
- `minutos_hasta(datetime)` → Minutos hasta un evento
- `formatear_duracion(inicio, fin)` → "2h 30min"
- `formatear_hora_legible(datetime)` → "15:30 - 24 May"
- `es_email_valido(email)` → Validación basic
- `normalizar_nombre(nombre)` → Capitaliza palabras

**Por qué:**
- Evita duplicar lógica de formato en templates
- Facilita cálculos de disponibilidad
- Reutilizable en tests

---

### 7. **views_refactored_example.py** (REFERENCIA)
**Propósito:** Mostrar cómo refactorizar vistas existentes

**Ejemplo: Dashboard Original vs Refactorizado**

❌ **Antes (código duplicado):**
```python
def dashboard(request):
    usuario = Usuario.objects.get(pk=request.session.get("usuario_id"))
    tickets = Ticket.objects.filter(id_usuario=usuario).select_related("id_vehiculo")
    # ... 10+ líneas más
```

✅ **Después (modular):**
```python
@login_requerido
@requiere_usuario_activo
def dashboard_refactorizado(request):
    usuario = request.user  # Del middleware
    tickets = selectors.get_tickets_usuario(usuario)  # Del selector
    # ... más limpio y reutilizable
```

---

## 🔄 Plan de Migración

### Fase 1: Core (✅ COMPLETADA)
- [x] Refactorizar models.py (agregar managers)
- [x] Crear selectors.py
- [x] Crear middleware.py
- [x] Crear decorators.py
- [x] Crear validators.py
- [x] Crear utils.py

### Fase 2: Views (⏳ PRÓXIMA)
- [ ] Actualizar settings.py (agregar middleware)
- [ ] Migrare vistas una por una (usar ejemplo como guía)
- [ ] Eliminar `get_usuario_sesion()` cuando todas las vistas migradas
- [ ] Tests para vistas refactorizadas

### Fase 3: Services Modularizado (⏳ FUTURO)
- [ ] Crear `services/__init__.py`
- [ ] Mover `services/tickets_service.py`
- [ ] Crear `services/auth_service.py`
- [ ] Crear `services/usuarios_service.py`

### Fase 4: APIs (🔮 LARGO PLAZO)
- [ ] Agregar Django REST Framework
- [ ] Crear serializers reutilizando selectors
- [ ] Viewsets que usan servicios

---

## 🚀 Cómo Usar los Nuevos Componentes

### Ejemplo 1: Obtener Usuario en Vista
```python
# ANTES (duplicado en cada vista)
usuario = Usuario.objects.select_related("id_cargo").get(pk=request.session.get("usuario_id"))

# DESPUÉS (middleware + decorador)
@login_requerido
def mi_vista(request):
    usuario = request.user  # ✓ Ya tiene cargo precargado
```

### Ejemplo 2: Obtener Tickets de Usuario
```python
# ANTES (query manual, sin optimización)
tickets = Ticket.objects.filter(id_usuario=usuario).order_by("-hora_inicio")

# DESPUÉS (selector optimizado)
tickets = selectors.get_tickets_usuario(usuario)  # Ya tiene select_related
```

### Ejemplo 3: Validar Acceso Admin
```python
# ANTES (duplicado en 10+ vistas)
def panel_admin(request):
    if not request.session.get("es_admin"):
        messages.error(request, "...")
        return redirect("dashboard")
    # ...

# DESPUÉS (decorador)
@login_requerido
@admin_requerido
def panel_admin(request):
    # Acceso garantizado
    ...
```

### Ejemplo 4: Obtener Tickets en Rango
```python
# ANTES (query compleja en vista)
tickets = Ticket.objects.filter(
    id_vehiculo=vehiculo,
    estado=Ticket.ESTADO_APROBADO,
    hora_inicio__lt=hora_fin,
    hora_fin__gt=hora_inicio,
).select_related("id_usuario", "id_usuario__id_cargo")

# DESPUÉS (selector reutilizable)
tickets = selectors.get_conflictos_ticket(vehiculo, hora_inicio, hora_fin)
```

---

## 🎯 Beneficios Logrados

| Aspecto | Antes | Después |
|---------|-------|---------|
| **Duplicación** | `get_usuario_sesion()` en 20+ vistas | 1 middleware, reutilizable |
| **Queries** | N+1 en templates (usuario.id_cargo.nombre) | select_related predefinido |
| **Validación** | Esparcida en views | Centralizada en decorators, validators |
| **Testing** | Difícil (dependencias enredadas) | Fácil (funciones puras) |
| **Escalabilidad** | Código spaghetti | Modular y preparado para APIs |
| **Mantenibilidad** | Cambios afectan múltiples lugares | Un lugar a cambiar |

---

## 📝 Checklist de Implementación

```
CORE COMPLETADA ✅
- [x] models.py con managers
- [x] selectors.py
- [x] middleware.py
- [x] decorators.py
- [x] validators.py
- [x] utils.py

SIGUIENTE FASE
- [ ] Copiar contenido de views_refactored_example.py a views.py
- [ ] Actualizar settings.py (MIDDLEWARE)
- [ ] Eliminar function get_usuario_sesion()
- [ ] Ejecutar tests (si existen)
- [ ] Testear en navegador

OPCIONAL (FUTURO)
- [ ] Dividir views.py en carpeta views/ con módulos
- [ ] Crear services/ con modules
- [ ] Agregar REST API con DRF
```

---

## 🔗 Referencias Rápidas

| Necesidad | Solución | Archivo |
|-----------|----------|---------|
| Usuario de request | `request.user` | middleware.py |
| Es admin | `request.es_admin` | middleware.py |
| Validar login | `@login_requerido` | decorators.py |
| Validar admin | `@admin_requerido` | decorators.py |
| Obtener tickets usuario | `selectors.get_tickets_usuario()` | selectors.py |
| Detectar conflictos | `selectors.get_conflictos_ticket()` | selectors.py |
| Buscar usuarios | `selectors.buscar_usuarios()` | selectors.py |
| Validar contraseña | `validators.validar_contrasena_fuerte()` | validators.py |
| Formatear duración | `utils.formatear_duracion()` | utils.py |

---

## ⚠️ Notas Importantes

1. **Compatibilidad:** El archivo `services.py` sigue funcionando (apunta a selectors)
2. **Gradual:** No necesitas migrar TODO de golpe. Haz vistas una por una
3. **Tests:** Si tienes tests, actualizar los imports progresivamente
4. **Settings:** Recuerda agregar middleware en `MIDDLEWARE` de settings.py

---

## 🤔 Preguntas Frecuentes

**P: ¿Por qué separar selectors de managers?**
R: Managers son métodos del ORM (`User.objects.activos()`). Selectors son funciones independientes. Así código de lectura está centralizado fuera del modelo.

**P: ¿Necesito migrar TODO de golpe?**
R: No. Puedes ir vista por vista. El middleware y selectors funcionan en paralelo con código viejo.

**P: ¿Qué pasa si tengo tests?**
R: Actualizar imports en test_views.py para que usen selectors en lugar de queries manuales.

---

## 📞 Soporte

Cualquier duda sobre la arquitectura, revisar:
- `models.py` - Docstrings de managers
- `selectors.py` - Docstrings de funciones
- `views_refactored_example.py` - Ejemplos de uso
