"""Carga la configuración MySQL y crea el motor compartido por la API.

La configuración se lee primero desde ``backend/.env`` y puede usar una URI,
variables de Clever Cloud o variables para una base local. Este módulo no abre
una conexión hasta que SQLAlchemy la necesita.
"""

import ipaddress
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from dotenv import load_dotenv

# .env separa la conexión del código y está excluido del repositorio.
load_dotenv(Path(__file__).resolve().parent / '.env')

# Una URI definida explícitamente tiene prioridad sobre los bloques de variables.
MYSQL_URI = os.getenv('MYSQL_ADDON_URI') or os.getenv('MYSQL_ADDON_URL') or os.getenv('DATABASE_URL')


def ensure_local_mysql_host(host: str) -> None:
    """Rechaza hosts externos en la configuración local de MySQL."""
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


# Crear una URL mediante SQLAlchemy evita errores al escapar contraseñas con
# caracteres reservados. La URI configurada se conserva como alternativa directa.
if MYSQL_URI:
    if MYSQL_URI.startswith('mysql://'):
        MYSQL_URI = MYSQL_URI.replace('mysql://', 'mysql+pymysql://', 1)
    database_url = MYSQL_URI
else:
    CLEVER_CLOUD_HOST = os.getenv('MYSQL_CLEVER_CLOUD_HOST')
    if CLEVER_CLOUD_HOST:
        DB_HOST = CLEVER_CLOUD_HOST
        DB_PORT = int(os.getenv('MYSQL_CLEVER_CLOUD_PORT', 3306))
        DB_USER = os.getenv('MYSQL_CLEVER_CLOUD_USER')
        DB_PASS = os.getenv('MYSQL_CLEVER_CLOUD_PASSWORD')
        DB_NAME = os.getenv('MYSQL_CLEVER_CLOUD_DB')
        if not DB_USER or not DB_NAME:
            raise RuntimeError('Configura usuario y base en backend/.env para Clever Cloud.')
    else:
        DB_HOST = os.getenv('MYSQL_ADDON_HOST', '127.0.0.1')
        DB_PORT = int(os.getenv('MYSQL_ADDON_PORT', 3306))
        DB_USER = os.getenv('MYSQL_ADDON_USER', 'root')
        DB_PASS = os.getenv('MYSQL_ADDON_PASSWORD')
        DB_NAME = os.getenv('MYSQL_ADDON_DB', 'biblioteca_digital')
        ensure_local_mysql_host(DB_HOST)

    if not DB_PASS:
        password_variable = (
            'MYSQL_CLEVER_CLOUD_PASSWORD'
            if CLEVER_CLOUD_HOST
            else 'MYSQL_ADDON_PASSWORD'
        )
        raise RuntimeError(f'Configura {password_variable} en backend/.env antes de iniciar Lorekeeper.')

    database_url = URL.create(
        'mysql+pymysql',
        username=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )

# `pool_pre_ping` comprueba conexiones reutilizadas; `hide_parameters` evita
# registrar valores de consultas, que podrían incluir datos sensibles.
engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True)

# Un solo motor administra el conjunto de conexiones reutilizado por la API.
def get_engine():
    """Devuelve el motor global para que las rutas compartan el mismo pool."""
    return engine
