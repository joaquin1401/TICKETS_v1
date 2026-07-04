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
- `SITE_URL`: URL base del sitio para enlaces en correos electrónicos (ej. `http://127.0.0.1:8000`). Por defecto `http://localhost:8000`.


### Cómo configurar en PostgreSQL

Crea el usuario y la base de datos (asignándole el usuario como dueño) en tu instancia de PostgreSQL. Esto evitará problemas de permisos con el esquema `public` en versiones recientes de PostgreSQL:

```sql
CREATE USER tu_usuario WITH PASSWORD 'tu_contrasena';
CREATE DATABASE tu_base_de_datos OWNER tu_usuario;
ALTER ROLE tu_usuario SET client_encoding TO 'utf8';
ALTER ROLE tu_usuario SET default_transaction_isolation TO 'read committed';
ALTER ROLE tu_usuario SET timezone TO 'America/Argentina/Buenos_Aires';
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

Para ejecutar el proyecto localmente junto con el procesador de tareas en segundo plano (necesario para el envío de correos y otras tareas asíncronas), utiliza el comando personalizado `runapp`:

```bash
python manage.py runapp
```

*(También puedes especificar una IP y puerto, por ejemplo: `python manage.py runapp 0.0.0.0:8000`).*

Este comando iniciará simultáneamente el servidor web y el worker de `django-q2` (`qcluster`). El proyecto estará disponible en `http://127.0.0.1:8000`.

El comando para correr el proyecto por default es:
```bash
python manage.py runserver
```


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

## Carga de Datos de Prueba

Para realizar pruebas, el proyecto incluye un comando para poblar la base de datos con datos de test (Cargos, Usuarios, Vehículos y Reservas en distintos estados). La contraseña de todos los usuarios es: `test123456`.

### Pasos para cargar los datos:

1. **Activar el entorno virtual:**
   ```bash
   source venv/bin/activate  # Linux/macOS
   # o
   venv\Scripts\activate     # Windows
   ```

2. **Ejecutar el script de población:**
   Ejecuta el siguiente comando desde la raíz del proyecto para generar los datos:
   ```bash
   python manage.py poblar_bd
   ```
   *Nota: Si deseas limpiar los datos anteriores antes de generar nuevos, puedes usar el flag `--clean` (`python manage.py poblar_bd --clean`).*

3. **Verificar los datos:**
   Ingresa a `http://127.0.0.1:8000` o utiliza uno de los correos de prueba generados. Todos usan la contraseña `test123456`:

   * **Administrador:** `admin@universidad.edu`
   * **Decano:** `decano_aprobado@universidad.edu`
   * **Secretario:** `secretario_aprobado@universidad.edu`
   * **Usuario regular:** `usuario_aprobado@universidad.edu`
   * **Chofer:** `chofer1@universidad.edu`

## Despliegue en Producción (Deployment)

Para desplegar esta aplicación en un entorno de producción (como Render, Heroku, VPS o similar), debes tener en cuenta los siguientes puntos críticos:

### 1. Variables de Entorno Fundamentales y Adicionales
Asegúrate de configurar correctamente las variables de entorno principales para producción:

- `DJANGO_DEBUG`: **Debe** ser `False`.
- `ALLOWED_HOSTS`: Lista de dominios permitidos (ej. `tu-dominio.onrender.com`).
- `SITE_URL`: URL base de tu dominio en producción (ej. `https://tu-dominio.onrender.com`). Es usada para construir enlaces en los correos electrónicos.
- `CSRF_TRUSTED_ORIGINS`: URLs confiables para peticiones POST (ej. `https://tu-dominio.onrender.com`).

Además de la base de datos, debes configurar las credenciales de correo electrónico para que el sistema pueda enviar notificaciones y recuperar contraseñas:

- `EMAIL_HOST`: Servidor SMTP (ej. `smtp.gmail.com`).
- `EMAIL_PORT`: Puerto SMTP (ej. `587`).
- `EMAIL_USE_TLS`: `True` o `False`.
- `EMAIL_HOST_USER`: Tu dirección de correo (ej. `tu-correo@gmail.com`).
- `EMAIL_HOST_PASSWORD`: Contraseña de aplicación de tu proveedor de correo.

### 2. Servidor Web (Gunicorn)
No uses `manage.py runserver` en producción. Utiliza un servidor WSGI como `gunicorn`.
El comando de inicio (Start Command) para el servicio web debería ser:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

### 3. Tareas en Segundo Plano (Worker) ⚠️ IMPORTANTE
El sistema utiliza **django-q2** para procesar el envío de correos de forma asíncrona usando la base de datos. Si no ejecutas este proceso, **los correos no se enviarán**.

En tu plataforma de despliegue, debes configurar un proceso adicional (tipo *Worker* o *Background Job*) que ejecute el siguiente comando de forma continua:

```bash
python manage.py qcluster
```

*Ejemplo en Render:* Debes crear un **Background Worker** separado de tu **Web Service**. Ambos deben apuntar al mismo repositorio y compartir las mismas variables de entorno (especialmente la Base de Datos). El comando de inicio para este worker es `python manage.py qcluster`.

### 4. Archivos Estáticos
En producción, el servidor de desarrollo de Django (`DEBUG=False`) no sirve los archivos estáticos automáticamente. Tienes dos opciones para servirlos:

**Opción A (Recomendada para Render/Heroku): Usar WhiteNoise**
1. Instala WhiteNoise: `pip install whitenoise` y agrégalo a tu `requirements.txt`.
2. En `settings.py`, agrégalo a la lista de `MIDDLEWARE` justo debajo de `SecurityMiddleware`:
   ```python
   MIDDLEWARE = [
       "django.middleware.security.SecurityMiddleware",
       "whitenoise.middleware.WhiteNoiseMiddleware",  # Añadir esta línea
       # ...
   ]
   ```

**Opción B (Recomendada para VPS): Usar Nginx o Apache**
Configura tu servidor web (Nginx/Apache) para que intercepte todas las peticiones a `/static/` y sirva los archivos directamente desde la carpeta `staticfiles`.

En ambos casos, asegúrate de **recolectar los archivos estáticos** durante el proceso de build (Build Command) antes de iniciar la aplicación. Por ejemplo:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
```
