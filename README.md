# TICKETS_v1 - Sistema Corporativo de Reservas

Este es un sistema de reservas desarrollado en Django.

## Requisitos previos

- Python 3.10+
- PostgreSQL

## Configuración de la Base de Datos (PostgreSQL)

El proyecto está configurado para utilizar PostgreSQL por defecto. Necesitas crear una base de datos y un usuario para la aplicación. 
Por defecto, las variables de entorno asumen los siguientes valores, pero puedes modificarlos si es necesario:

- **Base de datos**: `reservas_db`
- **Usuario**: `postgres`
- **Contraseña**: `postgres`
- **Host**: `localhost`
- **Puerto**: `5432`

### Cómo configurar en PostgreSQL

Abre `psql` (o pgAdmin) e ingresa los siguientes comandos:

```sql
CREATE DATABASE reservas_db;
CREATE USER postgres WITH PASSWORD 'postgres';
ALTER ROLE postgres SET client_encoding TO 'utf8';
ALTER ROLE postgres SET default_transaction_isolation TO 'read committed';
ALTER ROLE postgres SET timezone TO 'America/Argentina/Buenos_Aires';
GRANT ALL PRIVILEGES ON DATABASE reservas_db TO postgres;
```

*(Si utilizas otros credenciales, asegúrate de configurar las variables de entorno correspondientes antes de ejecutar el servidor).*

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
