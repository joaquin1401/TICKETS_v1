# TICKETS_v1 - Sistema Corporativo de Reservas

Este es un sistema de reservas desarrollado en Django.

## Requisitos previos

- Python 3.10+
- PostgreSQL

## Configuración de la Base de Datos (PostgreSQL)

El proyecto utiliza variables de entorno para la conexión a la base de datos. Se incluye un archivo `.env.example` (o puedes crear un archivo `.env` directamente) para configurar estos valores de manera segura.

### Variables requeridas:

- `DB_NAME`: Nombre de la base de datos.
- `DB_USER`: Usuario de la base de datos.
- `DB_PASSWORD`: Contraseña del usuario.
- `DB_HOST`: Host de la base de datos (ej. `localhost`).
- `DB_PORT`: Puerto de conexión (ej. `5432`).

### Cómo configurar en PostgreSQL

Crea la base de datos y el usuario en tu instancia de PostgreSQL:

```sql
CREATE DATABASE tu_base_de_datos;
CREATE USER tu_usuario WITH PASSWORD 'tu_contrasena';
ALTER ROLE tu_usuario SET client_encoding TO 'utf8';
ALTER ROLE tu_usuario SET default_transaction_isolation TO 'read committed';
ALTER ROLE tu_usuario SET timezone TO 'America/Argentina/Buenos_Aires';
GRANT ALL PRIVILEGES ON DATABASE tu_base_de_datos TO tu_usuario;
```

## Configuración del Proyecto

### 1. Clonar el repositorio y entrar al directorio

```bash
cd TICKETS_v1
```

### 2. Crear y activar un entorno virtual

En Linux o macOS:
```bash
python -m venv venv
source venv/bin/activate
```

En Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar las dependencias

```bash
pip install -r requirements.txt
```

### 4. Ejecutar las migraciones de la base de datos

Aplica los modelos de Django a la base de datos PostgreSQL:

```bash
python manage.py migrate
```

### 5. Crear un superusuario (Opcional)

Para acceder al panel de administración de Django (`/admin`):

```bash
python manage.py createsuperuser
```

### 6. Ejecutar el servidor de desarrollo

```bash
python manage.py runserver
```

El proyecto estará disponible en `http://127.0.0.1:8000`.

## Variables de Entorno

Si deseas usar configuraciones diferentes a las predeterminadas, puedes definir las siguientes variables de entorno antes de ejecutar el servidor:

- `DJANGO_SECRET_KEY`: Llave secreta de Django.
- `DJANGO_DEBUG`: Define si el modo debug está activo (`True` o `False`).
- `ALLOWED_HOSTS`: Hosts permitidos (ej. `localhost 127.0.0.1`).
- `DB_NAME`: Nombre de la base de datos PostgreSQL.
- `DB_USER`: Usuario de la base de datos.
- `DB_PASSWORD`: Contraseña del usuario.
- `DB_HOST`: Host de la base de datos.
- `DB_PORT`: Puerto de conexión a la base de datos (por defecto 5432).

## Carga de Datos de Prueba (Fixtures)

Para facilitar el desarrollo, el proyecto incluye un archivo de datos iniciales con Cargos, Usuarios (contraseña: `password123`), Vehículos y Tickets.

### Pasos para cargar los datos:

1. **Activar el entorno virtual:**
   ```bash
   source venv/bin/activate  # Linux/macOS
   # o
   venv\Scripts\activate     # Windows
   ```

2. **Cargar el archivo JSON:**
   Ejecuta el siguiente comando desde la raíz del proyecto:
   ```bash
   python manage.py loaddata test_data.json
   ```

3. **Verificar en el Administrador:**
   Ingresa a `http://127.0.0.1:8000/admin` y verifica que las tablas tengan registros.
