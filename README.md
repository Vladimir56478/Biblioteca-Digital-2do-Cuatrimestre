# Lorekeeper - Biblioteca (demo)

Proyecto minimal para la app "Lorekeeper". Implementa:

- Backend en FastAPI con conexión a MySQL (SQLAlchemy + PyMySQL)
- Endpoints: `/api/authors`, `/api/books`, `/api/search`, `/api/reserve`
- Frontend móvil (estático) en `static/` con HTML/CSS/JS

Instalación rápida:

1. Crear un entorno virtual e instalar dependencias:

```bash
python -m venv .venv
source .venv/bin/activate   # windows: .venv\Scripts\activate
pip install -r requirements.txt
```


2. Crear un archivo `.env` en la carpeta `backend/` (o exportar variables) con las credenciales. El proyecto acepta las variables `MYSQL_ADDON_*` o `MYSQL_ADDON_URI` proporcionadas por Clever Cloud. Ejemplo:

```
MYSQL_ADDON_HOST=bfoewoyw9sucpqt3tgf1-mysql.services.clever-cloud.com
MYSQL_ADDON_DB=bfoewoyw9sucpqt3tgf1
MYSQL_ADDON_USER=u7dgtmfkuhg5dtxp
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_PASSWORD=YzSEZAOI7JW0h4EQgkwb
# o bien (URI completa):
MYSQL_ADDON_URI=mysql://u7dgtmfkuhg5dtxp:YzSEZAOI7JW0h4EQgkwb@bfoewoyw9sucpqt3tgf1-mysql.services.clever-cloud.com:3306/bfoewoyw9sucpqt3tgf1
```

3. Ejecutar el servidor:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

4. Abrir `http://localhost:8000/` para la interfaz móvil-first.

Notas:
- Todas las consultas usan parámetros preparados a través de SQLAlchemy `text()`.
- El generador de códigos de reserva produce `RES-XXXX` y verifica unicidad en DB.
