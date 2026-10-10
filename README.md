# Lorekeeper - Biblioteca

Un Proyecto para gestionar libros, usuarios y reservas con un backend en FastAPI y una interfaz web estática.

## Qué incluye

- Backend con FastAPI, SQLAlchemy y PyMySQL
- Base de datos MySQL configurable por variables de entorno
- Frontend estático con HTML, CSS y JavaScript
- Autenticación por roles para alumnos, profesores y bibliotecarios
- Gestión de libros, reservas, historial protegido y bajas de stock
- Gestión de curso, egresados de 6.º y vetos temporales con motivo
- Visualización del stock total y de las unidades disponibles
- Interfaz adaptable a celular y PC

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
- Al iniciar, el backend agrega de forma compatible las columnas de curso y veto que usan las funciones nuevas. Los alumnos existentes quedan con el curso sin asignar hasta que el bibliotecario lo complete en Gestión de Perfiles.
- Los historiales no se pueden vaciar ni borrar al eliminar un libro; el backend conserva sus registros. La eliminación de alumnos solo está habilitada para alumnos identificados en 6.º y sin reservas pendientes.
- El stock disponible corresponde a `Libro.Stock`, mientras que `Libro.Stock_Total` conserva el inventario total: reservar ejemplares reduce solo la disponibilidad; agregar o dar de baja ejemplares actualiza ambos valores. En bases existentes, al agregar la columna se conserva el total que ya mostraba la aplicación.
- Si cambias la base de datos, solo hace falta actualizar ese archivo, mediante un dump export e import humilde entre maquinas(mysqlworkbench).
- No se eliminaron archivos útiles porque todos ayudan a que la app funcione en una máquina nueva.
