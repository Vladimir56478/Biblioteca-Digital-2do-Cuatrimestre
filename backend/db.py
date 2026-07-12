import os
from pathlib import Path
from sqlalchemy import create_engine, MetaData
from dotenv import load_dotenv

# Carga la configuración de conexión desde backend/.env para que la app pueda
# usar una base local o la de Clever Cloud sin tocar la lógica del proyecto.
load_dotenv(Path(__file__).resolve().parent / '.env')

# Si la instancia externa ofrece una URL completa, se usa primero porque
# simplifica la conexión del backend con menos variables manuales.
MYSQL_URI = os.getenv('MYSQL_ADDON_URI') or os.getenv('MYSQL_ADDON_URL') or os.getenv('DATABASE_URL')

if MYSQL_URI:
    # Asegura que SQLAlchemy use el driver de MySQL para conectar con la base de datos del sistema.
    if MYSQL_URI.startswith('mysql://'):
        engine = create_engine(MYSQL_URI.replace('mysql://', 'mysql+pymysql://'), pool_pre_ping=True)
    else:
        engine = create_engine(MYSQL_URI, pool_pre_ping=True)
else:
    # Si no hay una URL externa, se arma una conexión local con los datos del archivo .env
    # para seguir desarrollando y probando la biblioteca en el equipo.
    DB_HOST = os.getenv('MYSQL_ADDON_HOST', '127.0.0.1')
    DB_PORT = int(os.getenv('MYSQL_ADDON_PORT', 3306))
    DB_USER = os.getenv('MYSQL_ADDON_USER', 'root')
    DB_PASS = os.getenv('MYSQL_ADDON_PASSWORD', 'admin')
    DB_NAME = os.getenv('MYSQL_ADDON_DB', 'biblioteca_digital')

    conn_str = f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    engine = create_engine(conn_str, pool_pre_ping=True)

# El metadata funciona como el mapa del esquema de la base para que el backend
# mantenga coherencia entre tablas, consultas y operaciones del sistema.
metadata = MetaData()

# Se expone el motor activo para que las rutas de la API reutilicen la misma conexión
# y no tengan que volver a armar la configuración cada vez que consultan la base.
def get_engine():
    return engine
