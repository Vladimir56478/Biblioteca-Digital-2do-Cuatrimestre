# Lorekeeper - Biblioteca

Un Proyecto para gestionar libros, usuarios y reservas con un backend en FastAPI y una interfaz web estática.

## Qué incluye

- Backend con FastAPI, SQLAlchemy y PyMySQL
- Base de datos MySQL configurable por variables de entorno
- Frontend estático con HTML, CSS y JavaScript
- Autenticación por roles para alumnos, profesores y bibliotecarios
- Gestión de libros, reservas, historial y bajas de stock

## Estructura del proyecto

- backend/: lógica del servidor, conexión a la base de datos y endpoints de la API
- static/: interfaz web que se ve en el navegador
- requirements.txt: dependencias de Python
- README.md: guía rápida de uso

## Instalación rápida

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuración de la base de datos

Crea un archivo llamado backend/.env con tus datos.

### Ejemplo local

```ini
MYSQL_ADDON_HOST=127.0.0.1
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_USER=root
MYSQL_ADDON_PASSWORD=admin
MYSQL_ADDON_DB=biblioteca_digital
```

### Ejemplo con URI

```ini
MYSQL_ADDON_URI=mysql://usuario:contraseña@host:3306/base_de_datos
```

## Ejecutar la app

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Luego abrí:

```text
http://localhost:8000/
```

## Usuarios de prueba

El sistema trae usuarios de ejemplo para probar el software:

- Alumno: vladimir.gaspar.672@alu.tecnica29de6.edu.ar / hash_pass_123
- Profesor: alan.etkin@tecnica29de6.edu.ar / hash_pass_profe
- Bibliotecario: Bibliotecario.fanoba@tecnica29de6.edu.ar / hash_pass_67

## Notas

- El backend carga la configuración desde backend/.env.
- Si cambias la base de datos, solo hace falta actualizar ese archivo, mediante un dump export e import humilde entre maquinas(mysqlworkbench).
- No se eliminaron archivos útiles porque todos ayudan a que la app funcione en una máquina nueva.
