# TICKETS_v1 — Vehicle Reservation System (Django)

> **AI Agent Guide** — This document is written for AI coding agents (DeepSeek, Claude, GPT, etc.) to quickly understand the project architecture, conventions, and business logic without needing to read every file.

---

## 1. Overview

A corporate vehicle reservation system built with **Django** (Python) + **PostgreSQL**. It manages hierarchical user roles, vehicle fleets, reservation tickets with conflict detection, and driver assignments. Developed for **UTN FRRE** (Universidad Tecnológica Nacional, Facultad Regional Resistencia).

**Tech Stack:**

- **Backend:** Django 6.0+, Python 3.10+
- **Database:** PostgreSQL
- **Async tasks:** django-q2 (Django ORM broker)
- **Charts:** Matplotlib (inline base64 PNG)
- **CSS:** Custom dark-theme UI (no framework)
- **Geocoding:** Nominatim (OSM) + OSRM for distance calculation
- **Email:** SMTP (Gmail) via async tasks

---

## 2. Project Structure

```
TICKETS_v1/
├── config/                         # Django project configuration
│   ├── settings.py                 # All settings (DB, email, sessions, qcluster)
│   ├── urls.py                     # Root URL routing → includes 'reservas/'
│   ├── wsgi.py                     # WSGI for production (Gunicorn)
│   └── asgi.py                     # ASGI (unused)
│
├── reservas/                       # Main Django app (the entire system)
│   ├── models.py                   # All 8 models (see §3)
│   ├── views.py                    # All views (~2563 lines) — session-based auth
│   ├── forms.py                    # Django Forms (~20 form classes)
│   ├── urls.py                     # App URL routing (27+ paths)
│   ├── admin.py                    # Django Admin customizations
│   ├── tests.py                    # Unit tests
│   ├── tasks.py                    # Async task wrappers (django-q2)
│   ├── signals.py                  # Signal handlers (auto-notifications)
│   ├── apps.py                     # App config (registers signals)
│   │
│   ├── management/commands/        # Custom management commands
│   │   ├── poblar_bd.py            # Seed DB with test data
│   │   ├── limpiar_bd.py           # Clean DB
│   │   ├── runapp.py               # Run dev server + qcluster together
│   │   └── send_reminders.py       # Cron task: send reminder emails
│   │
│   ├── utils/
│   │   ├── services.py             # Core business logic (conflict detection, ticket creation)
│   │   ├── notifications.py        # Notification dispatch (async email)
│   │   ├── email_verification.py   # Email verification service (code + magic link)
│   │   ├── email_utils.py          # Email rendering (HTML → inline CSS)
│   │   ├── password_recovery.py    # Password recovery (OTP + magic link)
│   │   ├── chart_utils.py          # Matplotlib chart generation (base64)
│   │   └── __init__.py
│   │
│   ├── templates/reservas/         # Django templates
│   │   ├── base.html               # Base layout (dark theme, sidebar, breadcrumbs)
│   │   ├── 404.html
│   │   ├── auth/                   # Login, register, password recovery, email verification
│   │   ├── tickets/                # Ticket CRUD, historial, monitor, chofer dashboard
│   │   ├── vehiculos/              # Vehicle list, create/edit form
│   │   ├── usuarios/               # User detail, validation panel, user list
│   │   ├── analiticas/             # Analytics dashboard, per-vehicle reports, PDF
│   │   ├── emails/                 # Email templates (creation, cancellation, reminders)
│   │   ├── admin/                  # Global config
│   │   └── includes/_pagination.html
│   │
│   └── migrations/                 # Django DB migrations (0026 as latest)
│
├── static/                         # Static assets
│   ├── css/base.css                # Main stylesheet (dark theme, ~4000+ lines)
│   ├── css/pages/                  # Page-specific CSS
│   └── img/                        # Logos and icons
│
├── scripts/                        # Development scripts
│   └── generar_100_reservas.py
│
├── .github/workflows/ci.yml        # CI pipeline
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

## 3. Data Model (8 Models)

### 3.1 `Cargo` — Position / Role Hierarchy

| Field       | Type                        | Description                                                                                  |
| ----------- | --------------------------- | -------------------------------------------------------------------------------------------- |
| `nombre`    | CharField (unique, choices) | Role name: Decano, Vicedecano, Secretario, Subsecretario, Usuario, Chofer, Administrador SEU |
| `prioridad` | PositiveIntegerField        | **Lower = higher priority** (0 = Admin SEU, highest)                                         |

- Used for **conflict resolution**: a user with lower priority number can override another's reservation.

### 3.2 `Usuario` — User Account

| Field                | Type                | Description                         |
| -------------------- | ------------------- | ----------------------------------- |
| `id_cargo`           | FK → Cargo          | User's role (determines hierarchy)  |
| `nombre`, `apellido` | CharField           | First and last name                 |
| `correo`             | EmailField (unique) | Used as login identifier            |
| `contrasena`         | CharField (max 255) | Hashed password (bcrypt-compatible) |
| `valido`             | BooleanField        | Approved by admin?                  |
| `rechazado`          | BooleanField        | Explicitly rejected?                |
| `correo_verificado`  | BooleanField        | Email verified after registration   |
| `departamento`       | CharField (choices) | Department                          |
| `activo`             | BooleanField        | Account active/inactive             |

**Properties:** `nombre_completo` (returns "Nombre Apellido"), `prioridad` (delegates to cargo)

**Auth flow:** Session-based (no DRF/JWT). Session stores `usuario_id` and `es_admin`.

### 3.3 `Vehiculo` — Vehicle

| Field                | Type                             | Description                 |
| -------------------- | -------------------------------- | --------------------------- |
| `marca`              | CharField                        | Brand (e.g., Toyota)        |
| `modelo`             | CharField                        | Model (e.g., Hiace)         |
| `patente`            | CharField (unique, **required**) | License plate               |
| `cant_pasajeros`     | PositiveIntegerField             | Passenger capacity          |
| `activo`             | BooleanField                     | Available for reservations? |
| `exclusivo_decanato` | BooleanField                     | Only the Dean can book this |
| `requiere_chofer`    | BooleanField                     | A driver must be assigned   |

**`__str__`:** `"{marca} {modelo} {patente} ({cant_pasajeros} pasajeros)"`

### 3.4 `Ticket` — Reservation

| Field                | Type                              | Description                                                    |
| -------------------- | --------------------------------- | -------------------------------------------------------------- |
| `id_usuario`         | FK → Usuario (CASCADE)            | Requesting user                                                |
| `id_vehiculo`        | FK → Vehiculo (PROTECT)           | Reserved vehicle                                               |
| `conductor`          | FK → Usuario (SET_NULL, nullable) | Assigned driver                                                |
| `requiere_chofer`    | BooleanField                      | Requires a driver                                              |
| `para_tercero`       | BooleanField                      | Vehicle used by someone else                                   |
| `destino`            | CharField(255)                    | Destination / purpose                                          |
| `distancia_est`      | DecimalField                      | Estimated distance (km, OSRM ×2)                               |
| `distancia_real`     | DecimalField (nullable)           | Actual distance (from odometer)                                |
| `kilometraje_inicio` | DecimalField (nullable)           | Starting odometer                                              |
| `kilometraje_fin`    | DecimalField (nullable)           | Ending odometer                                                |
| `cant_pasajeros`     | PositiveIntegerField              | Confirmed passengers                                           |
| `descripcion`        | TextField                         | Notes / justification                                          |
| `hora_inicio`        | DateTimeField                     | Start time                                                     |
| `hora_inicio_real`   | DateTimeField (nullable)          | Actual departure                                               |
| `hora_fin`           | DateTimeField (nullable)          | Estimated return                                               |
| `hora_fin_real`      | DateTimeField (nullable)          | Actual return                                                  |
| `estado`             | CharField (choices)               | `pendiente`, `aprobado`, `cancelado`, `en_curso`, `finalizado` |
| `fecha`              | DateField (auto_now_add)          | Creation date                                                  |
| `observacion`        | TextField                         | Admin notes / cancellation reason                              |

**Key states:**

- `ESTADO_PENDIENTE` — Unused currently
- `ESTADO_APROBADO` — Active reservation (checked for conflicts)

### 3.5 `VerificacionCorreo` — Email Verification

| Field       | Type                         | Description          |
| ----------- | ---------------------------- | -------------------- |
| `usuario`   | FK → Usuario (CASCADE)       | User to verify       |
| `codigo`    | CharField(6)                 | 6-digit numeric code |
| `token`     | UUIDField                    | Magic link token     |
| `creado_en` | DateTimeField (auto_now_add) | Created timestamp    |
| `usado`     | BooleanField                 | Already consumed?    |

**Expiry:** 30 minutes (checked via `esta_vigente()` method).

### 3.6 `RecuperacionPassword` — Password Recovery

| Field       | Type                         | Description              |
| ----------- | ---------------------------- | ------------------------ |
| `usuario`   | FK → Usuario (CASCADE)       | User recovering password |
| `codigo`    | CharField(6)                 | 6-digit OTP              |
| `token`     | UUIDField                    | Magic link token         |
| `creado_en` | DateTimeField (auto_now_add) | Created timestamp        |
| `usado`     | BooleanField                 | Already consumed?        |

**Expiry:** 30 minutes.

### 3.7 `ConfiguracionGlobal` — Global Settings

| Field                        | Type                             | Description                       |
| ---------------------------- | -------------------------------- | --------------------------------- |
| `dias_anticipacion_reservas` | PositiveIntegerField (default=3) | Min advance days for reservations |

**Singleton** — only one record exists (pk=1). Use `ConfiguracionGlobal.get_solo()`.

### 3.8 `Feriado` — Holiday

| Field         | Type                  | Description          |
| ------------- | --------------------- | -------------------- |
| `fecha`       | DateField (unique)    | Holiday date         |
| `descripcion` | CharField(255, blank) | Optional description |

---

## 4. Business Logic (`reservas/utils/services.py`)

### 4.1 Conflict Detection

```python
obtener_tickets_en_conflicto(vehiculo, hora_inicio, hora_fin, excluir_ticket_id=None)
```

- Returns all `APROBADO` tickets for a vehicle overlapping the time range.
- Overlap: `existing.hora_inicio < new.hora_fin AND existing.hora_fin > new.hora_inicio`

## 6. URL Structure (27+ Routes)

| Path                                          | View                            | Description                        |
| --------------------------------------------- | ------------------------------- | ---------------------------------- |
| **Auth**                                      |                                 |                                    |
| `/`                                           | `login_view`                    | Login page                         |
| `/registro/`                                  | `registro`                      | Registration                       |
| `/logout/`                                    | `logout_view`                   | Logout                             |
| `/verificar-correo/`                          | `verificar_correo`              | Email verification (code form)     |
| `/verificar-correo/<uuid:token>/`             | `verificar_correo_enlace`       | Magic link verification            |
| `/recuperar-password/`                        | `solicitar_recuperacion`        | Password recovery request          |
| `/recuperar-password/verificar/`              | `verificar_recuperacion`        | Enter OTP code                     |
| `/recuperar-password/verificar/<uuid:token>/` | `verificar_recuperacion_enlace` | Magic link recovery                |
| `/recuperar-password/nueva/`                  | `nueva_contrasena`              | Set new password                   |
| **User Tickets**                              |                                 |                                    |
| `/inicio/`                                    | `inicio`                        | Dashboard + quick reservation form |
| `/historial/`                                 | `historial`                     | User's ticket history              |
| `/tickets/<int:pk>/`                          | `detalle_ticket`                | Ticket detail                      |
| `/tickets/<int:pk>/cancelar/`                 | `cancelar_ticket`               | Cancel own ticket                  |
| **Driver**                                    |                                 |                                    |
| `/chofer/dashboard/`                          | `chofer_dashboard`              | Driver's trip dashboard            |
| `/tickets/<int:pk>/aceptar/`                  | `aceptar_ticket`                | Start trip (set km_start)          |
| `/tickets/<int:pk>/finalizar/`                | `finalizar_ticket`              | End trip (set km_end)              |
| **Admin**                                     |                                 |                                    |
| `/admin-panel/validacion/`                    | `panel_validacion`              | Approve/reject new users           |
| `/admin-panel/usuarios/`                      | `usuarios`                      | User directory                     |
| `/admin-panel/usuarios/<int:pk>/`             | `detalle_usuario`               | User detail + deactivation         |
| `/admin-panel/usuarios/crear/`                | `admin_crear_usuario`           | Admin creates user                 |
| `/admin-panel/tickets/activos/`               | `monitor_tickets_activos`       | Live active tickets                |
| `/admin-panel/tickets/historial/`             | `historial_tickets`             | Full ticket history                |
| `/admin-panel/tickets/historial/descargar/`   | `descargar_historial_csv`       | Export CSV                         |
| `/admin-panel/vehiculos/`                     | `listado_vehiculos`             | Vehicle list                       |
| `/admin-panel/vehiculos/nueva/`               | `alta_vehiculo`                 | Create vehicle                     |
| `/admin-panel/vehiculos/<int:pk>/editar/`     | `edicion_vehiculo`              | Edit vehicle                       |
| **Analytics**                                 |                                 |                                    |
| `/admin-panel/analiticas/`                    | `reporte_analiticas`            | Analytics dashboard                |
| `/admin-panel/analiticas/vehiculo/<int:pk>/`  | `analiticas_vehiculo`           | Per-vehicle analytics              |
| `/admin-panel/analiticas/pdf/`                | `reporte_analiticas_pdf`        | PDF report (HTML+CSS)              |
| **Config**                                    |                                 |                                    |
| `/admin-panel/configuracion/`                 | `configuracion_global`          | System settings                    |
| **API**                                       |                                 |                                    |
| `/api/calcular-distancia/`                    | `api_calcular_distancia`        | AJAX: estimate route distance      |

### 4.2 Ticket Creation with Conflict Resolution

```python
crear_ticket_con_reglas(usuario, vehiculo, destino, hora_inicio, hora_fin, ...) -> ResultadoCreacion
```

**Rules (Epic 4):**

1. If **no conflicts** → auto-approve.
2. If conflicts exist and **current user has higher priority** (lower `prioridad` number) than ALL conflicting users → approve and cancel conflicting tickets (overwrite).
3. Otherwise → reject with explanation.

**`ResultadoCreacion`:** `exito` (bool), `mensaje` (str), `ticket` (Ticket|None), `conflictos` (list).

### 4.3 Distance Calculation

```python
calcular_distancia_osrm(destino) -> float
```

- Geocodes via Nominatim → queries OSRM from UTN FRRE coordinates.
- Returns **round-trip distance** (×2). Returns 0.0 on error.

### 4.4 Ticket Cancellation (by user)

```python
cancelar_ticket_usuario(ticket, usuario) -> tuple(bool, str)
```

- Only ticket owner can cancel. Only `APROBADO` tickets. Must be **5+ days before** start.

### 4.5 Driver Operations

- **Accept:** Sets `kilometraje_inicio`, `hora_inicio_real` → status `EN_CURSO`.
- **Finish:** Sets `kilometraje_fin`, `hora_fin_real`, calculates `distancia_real` → status `FINALIZADO`.

---

## 5. Authentication & Session System

**Session-based auth** (no DRF, no JWT). Session stores:

- `request.session["usuario_id"]` — PK of logged-in user
- `request.session["es_admin"]` — Boolean (True if Cargo.prioridad == 0)

**Decorators:**

- `@login_requerido` — Redirects to `/` (login) if no session
- `@admin_requerido` — Redirects to `/inicio` if not admin

**Registration flow:**

1. Register → `valido=False, rechazado=False, correo_verificado=False`
2. Verification email sent (6-digit code + magic link)
3. User verifies email → `correo_verificado=True`
4. Admin approves user → `valido=True`
5. Login allowed only if `valido=True` AND `correo_verificado=True`

- `ESTADO_CANCELADO` — Cancelled (reason in `observacion`)
- `ESTADO_EN_CURSO` — Driver started the trip
- `ESTADO_FINALIZADO` — Trip completed

---

## 7. Async Task System (django-q2)

- **Broker:** Django ORM (default DB)
- **Config in settings.py:** `Q_CLUSTER` with 4 workers, 90s timeout
- **Start command:** `python manage.py qcluster` (or `python manage.py runapp` for dev)

**Tasks** (`reservas/tasks.py`):

- `enviar_correo_async()` — Send plain email via `send_mail`
- `enviar_correo_templated_async()` — Send HTML email via `send_templated_email`

**Scheduled tasks (cron):** `send_reminders.py` — sends 3-day and same-day reminders.

**Notifications:** Managed in `reservas/utils/notifications.py` — uses `NotificationLog` to prevent duplicate sends.

---

## 8. Email System

- **Provider:** SMTP (Gmail default)
- **HTML emails** with inline CSS (via `premailer` library)
- **All email templates** in `reservas/templates/reservas/emails/`
- **Types of emails sent:**
  - Verification email (code + magic link)
  - Reservation created confirmation
  - Reservation cancelled notification
  - Account rejected notification
  - 3-day reminder
  - Same-day reminder
  - Password recovery (code + magic link)

**Key utility:** `send_templated_email()` in `email_utils.py`:

- Renders HTML template → converts CSS variables → inlines styles via `premailer`
- Generates plain-text fallback via `strip_tags()`
- Falls back to `.txt` template if HTML fails

---

## 9. Forms (`reservas/forms.py`)

Major form classes:

| Form                      | Purpose                                        |
| ------------------------- | ---------------------------------------------- |
| `RegistroForm`            | User registration (validates password match)   |
| `LoginForm`               | Login with email + password                    |
| `TicketForm`              | Create reservation (time, capacity, conflicts) |
| `VehiculoSelectorForm`    | Vehicle selector for calendar                  |
| `VehiculoForm`            | Create/edit vehicle                            |
| `FiltroUsuariosForm`      | Admin user search/filter                       |
| `FiltroTicketsForm`       | Admin ticket history filter                    |
| `AdminCrearUsuarioForm`   | Admin creates user accounts                    |
| `AdminEditarUsuarioForm`  | Admin edits user accounts                      |
| `VerificacionCodigoForm`  | Email verification code entry                  |
| `ConfiguracionGlobalForm` | System settings                                |
| Recovery forms            | Password recovery (3-step flow)                |

---

## 10. UI / Templates

**Design:** Custom dark theme with CSS custom properties. No Bootstrap/Tailwind.

**Base layout** (`base.html`):

- Sidebar navigation (role-dependent)
- Breadcrumbs
- Content area
- Flash messages (Django messages framework)

**Color scheme:**

- Background: `#0f1014` (dark)
- Surface: `#181b22` (card bg)
- Accent: `#38bdf8` (sky blue)
- Success: `#4ade80`
- Warning: `#fbbf24`
- Danger: `#e85252`
- Text: `#cbd5e1`

**Templates are in Spanish** (UI language is Spanish).

---

## 11. Analytics Module

**Location:** `reporte_analiticas` view and related templates.

**Features:**

- KPIs: total tickets, approvals, cancellations, distances
- Bar charts (Matplotlib, base64 inline): by department, cargo, vehicle
- Per-vehicle deep dive: usage stats, top users, distance metrics
- PDF export (HTML+CSS rendered in browser print)

**Charts** (`chart_utils.py`):

- `generar_grafico_barras_horizontal()` — Horizontal bar chart
- `generar_grafico_torta()` — Pie chart
- Returns base64-encoded PNG data URIs

---

## 12. Key Conventions for AI Agents

### Naming

- **Spanish** throughout (models, views, templates, URLs, code comments)
- Snake_case for Python identifiers
- Template files use `snake_case.html`
- URL names use `snake_case`

### Session

- Always check `request.session["usuario_id"]` for auth
- Helper: `get_usuario_sesion(request)` returns `Usuario | None`
- Decorators: `@login_requerido`, `@admin_requerido`

### Pagination

- Helper: `paginate_queryset(request, queryset, per_page=20)`
- Returns `(page_obj, pagination_query_string)`

### Foreign Keys

- `id_cargo`, `id_vehiculo`, `id_usuario` — prefix `id_` convention

### Template Context

- `usuario` — always the logged-in user instance

### Important Migration History

- `0020_vehiculo_patente.py` — Added `patente` field (initially nullable)
- `0025_feriado.py` — Added holidays model
- `0026_vehiculo_patente_not_null.py` — Made `patente` required (non-nullable)

---

## 13. Running the Project

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Database (PostgreSQL required)
# Configure .env with DB credentials
python manage.py migrate

# Seed test data (optional)
python manage.py poblar_bd --clean

# Run (dev server + async worker)
python manage.py runapp
```

**Test credentials** (after `poblar_bd`):

- Admin: `admin@universidad.edu` / `test123456`
- Dean: `decano_aprobado@universidad.edu` / `test123456`
- Regular user: `usuario_aprobado@universidad.edu` / `test123456`
- Driver: `chofer1@universidad.edu` / `test123456`

---

## 14. Key Dependencies

| Package         | Purpose                       |
| --------------- | ----------------------------- |
| Django 6.0+     | Web framework                 |
| psycopg2-binary | PostgreSQL adapter            |
| django-q2       | Async task queue (ORM broker) |
| python-dotenv   | Environment variables         |
| matplotlib      | Chart generation              |
| numpy           | Chart data handling           |
| requests        | HTTP (Nominatim/OSRM API)     |
| premailer       | Inline CSS for emails         |

---

## 15. Tips for AI Agents Modifying This Code

1. **Models are in Spanish** — `Vehiculo` (not Vehicle), `Usuario` (not User), `Cargo` (not Role), `Patente` (not LicensePlate).
2. **Templates are in Spanish** — UI text, labels, and messages.
3. **Session auth, not DRF** — Use `request.session` + decorators, not `request.user`.
4. **Async via django-q2** — Long operations (emails, distance calc) use `async_task`.
5. **Signals for notifications** — `ticket_post_save` triggers email notifications automatically.
6. **Always run `poblar_bd --clean` before testing** to reset and seed test data.
7. **Check `migrations/` for latest** before creating new migrations.
8. **Rendering charts** uses non-interactive Matplotlib backend (`Agg`).
9. **Email HTML** uses `premailer` to inline CSS — test both HTML and plain-text rendering.
