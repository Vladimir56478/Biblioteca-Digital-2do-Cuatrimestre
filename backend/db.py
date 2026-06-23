import os
from pathlib import Path
from sqlalchemy import create_engine, MetaData
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')

# Prefer Clever Cloud style variables if provided
MYSQL_URI = os.getenv('MYSQL_ADDON_URI') or os.getenv('MYSQL_ADDON_URL') or os.getenv('DATABASE_URL')

if MYSQL_URI:
    # Ensure SQLAlchemy uses pymysql driver
    if MYSQL_URI.startswith('mysql://'):
        engine = create_engine(MYSQL_URI.replace('mysql://', 'mysql+pymysql://'), pool_pre_ping=True)
    else:
        engine = create_engine(MYSQL_URI, pool_pre_ping=True)
else:
    # Default to a local MySQL database for development/testing.
    # Use backend/.env to switch between local and Clever Cloud easily.
    DB_HOST = os.getenv('MYSQL_ADDON_HOST', '127.0.0.1')
    DB_PORT = int(os.getenv('MYSQL_ADDON_PORT', 3306))
    DB_USER = os.getenv('MYSQL_ADDON_USER', 'root')
    DB_PASS = os.getenv('MYSQL_ADDON_PASSWORD', 'admin')
    DB_NAME = os.getenv('MYSQL_ADDON_DB', 'biblioteca_digital')

    conn_str = f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    engine = create_engine(conn_str, pool_pre_ping=True)

metadata = MetaData()

def get_engine():
    return engine
