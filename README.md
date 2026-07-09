# Lorekeeper - Biblioteca (demo)

Proyecto minimal con backend en FastAPI y frontend estático.

- Backend: FastAPI + SQLAlchemy + PyMySQL
- Base de datos: MySQL
- Frontend: `static/` con HTML/CSS/JS
- Endpoints principales: `/api/authors`, `/api/books`, `/api/search`, `/api/reserve`

## Estructura del proyecto

El proyecto está dividido en dos partes claras:

- `backend/`: contiene la lógica del servidor, la conexión a la base de datos y los endpoints de la API.
- `static/`: contiene la interfaz web que se muestra al usuario en el navegador.

### Por qué existe cada archivo

- `README.md`: documenta cómo instalar, configurar y ejecutar la aplicación.
- `requirements.txt`: lista las dependencias de Python necesarias para correr el backend.
- `backend/main.py`: es el archivo central del backend. Define la API, la autenticación por roles, la gestión de libros, las reservas y el servicio de archivos estáticos.
- `backend/db.py`: se encarga de crear y devolver el motor de conexión a MySQL usando variables de entorno.
- `static/index.html`: define la estructura de la interfaz, incluyendo las vistas de cuenta, catálogo, reservas y administración.
- `static/app.js`: contiene la lógica del frontend: login, registro, navegación, búsqueda, alta/edición de libros y reservas.
- `static/styles.css`: define los estilos visuales de la aplicación para que la interfaz sea más usable.

También se añadieron comentarios explicativos en los archivos principales para que sea más sencillo comprender qué hace cada parte del código.

## 1. Instalar dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Configurar la base de datos

Crea `backend/.env` con tus credenciales.

### MySQL local

```ini
MYSQL_ADDON_HOST=127.0.0.1
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_USER=root
MYSQL_ADDON_PASSWORD=admin
MYSQL_ADDON_DB=biblioteca_digital
```

### MySQL en Clever Cloud

```ini
MYSQL_ADDON_HOST=bfoewoyw9sucpqt3tgf1-mysql.services.clever-cloud.com
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_USER=u7dgtmfkuhg5dtxp
MYSQL_ADDON_PASSWORD=YzSEZAOI7JW0h4EQgkwb
MYSQL_ADDON_DB=bfoewoyw9sucpqt3tgf1
```

O usar URI completa:

```ini
MYSQL_ADDON_URI=mysql://usuario:contraseña@host:3306/base_de_datos
```

> Con este archivo cambia la conexión sin tocar el código.

## 3. Ejecutar el servidor

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## 4. Reiniciar el servidor

Si cambias `backend/.env` o necesitas aplicar un cambio, detén el servidor con `Ctrl+C` y vuelve a ejecutar el mismo comando.

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## 5. Abrir la app.

En tu navegador local:

```text
http://localhost:8000/
```

Si quieres acceder desde otra computadora en la misma red, usa la IP de tu PC:

```text
http://<TU_IP_LOCAL>:8000/
```

## 6. Cerrar y volver a abrir Visual Studio Code

- Antes de cerrar VS Code, detén el servidor con `Ctrl+C` en el terminal.
- Si cierras VS Code con el servidor activo, el servidor se detiene automáticamente.
- Al volver a abrir el proyecto, ejecuta de nuevo:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

> Esto aplica igual si usas MySQL local o Clever Cloud.

## Notas

- `backend/db.py` carga `backend/.env` directamente.
- Si pones datos locales en `.env`, el backend usará tu MySQL local.
- Si pones datos de Clever Cloud en `.env`, el backend usará la nube.
- Todas las consultas en el backend usan SQLAlchemy `text()`.
- El generador de reserva crea códigos `RES-XXXX` y verifica unicidad.
