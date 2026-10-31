import ipaddress
import os
from pathlib import Path
from sqlalchemy import create_engine, MetaData
from sqlalchemy.engine import make_url
from dotenv import load_dotenv

# Carga la configuración de conexión desde backend/.env para que la app pueda
# usar una base local sin tocar la lógica del proyecto.
# Esto mantiene la configuración separada del código.
load_dotenv(Path(__file__).resolve().parent / '.env')

MYSQL_URI = os.getenv('MYSQL_ADDON_URI') or os.getenv('MYSQL_ADDON_URL') or os.getenv('DATABASE_URL')


def ensure_local_mysql_host(host):
    if not host:
        raise RuntimeError('La configuración de MySQL debe especificar un host local.')
    if host.lower() == 'localhost':
        return
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise RuntimeError('Lorekeeper solo permite conectarse a MySQL en esta computadora.')


if MYSQL_URI:
    if MYSQL_URI.startswith('mysql://'):
        MYSQL_URI = MYSQL_URI.replace('mysql://', 'mysql+pymysql://', 1)
    ensure_local_mysql_host(make_url(MYSQL_URI).host)
    engine = create_engine(MYSQL_URI, pool_pre_ping=True, hide_parameters=True)
else:
    DB_HOST = os.getenv('MYSQL_ADDON_HOST', '127.0.0.1')
    DB_PORT = int(os.getenv('MYSQL_ADDON_PORT', 3306))
    DB_USER = os.getenv('MYSQL_ADDON_USER', 'root')
    DB_PASS = os.getenv('MYSQL_ADDON_PASSWORD')
    DB_NAME = os.getenv('MYSQL_ADDON_DB', 'biblioteca_digital')
    ensure_local_mysql_host(DB_HOST)
    if not DB_PASS:
        raise RuntimeError('Configura MYSQL_ADDON_PASSWORD en backend/.env antes de iniciar Lorekeeper.')

    conn_str = f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    engine = create_engine(conn_str, pool_pre_ping=True, hide_parameters=True)

# El metadata funciona como el mapa del esquema de la base para que el backend
# mantenga coherencia entre tablas, consultas y operaciones del sistema.
metadata = MetaData()

# Se expone el motor activo para que las rutas de la API reutilicen la misma conexión
# y no tengan que volver a armar la configuración cada vez que consultan la base.
def get_engine():
    return engine
