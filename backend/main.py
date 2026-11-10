"""API de Lorekeeper: autenticación, catálogo, perfiles, préstamos e historial.

Este módulo conecta la interfaz estática con MySQL. Al importarse, prepara el
esquema compatible; luego las rutas validan datos y permisos y realizan las
operaciones de negocio dentro de transacciones SQLAlchemy.
"""

import base64
import datetime
import hashlib
import hmac
import inspect
import secrets
import time
from functools import wraps
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import inspect as sqlalchemy_inspect, text

from backend.db import get_engine
from backend.user_deletion import ensure_no_active_loans

app = FastAPI(title='Lorekeeper API')
# La cookie contiene un token aleatorio; el servidor guarda su hash, usuario y vencimiento.
SESSION_COOKIE = 'lorekeeper_session'
SESSION_TTL_SECONDS = 12 * 60 * 60
PASSWORD_HASH_ITERATIONS = 600_000
# Las sesiones viven en memoria: usar un solo worker hasta persistirlas fuera del proceso.
sessions: dict[str, tuple[int, float]] = {}
sessions_lock = Lock()


def utc_now() -> datetime.datetime:
    """Devuelve UTC sin zona horaria, formato compatible con columnas MySQL DATETIME."""
    # MySQL DATETIME no guarda zona horaria; se conserva UTC como valor sin zona.
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def current_timestamp() -> str:
    """Formatea la hora UTC para los registros de historial existentes."""
    return utc_now().strftime('%Y-%m-%d %H:%M:%S')


def format_datetime(value) -> str | None:
    """Convierte una fecha/hora de MySQL al formato de la API."""
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else None


def format_date(value) -> str | None:
    """Convierte una fecha de MySQL a ISO 8601 o devuelve ``None``."""
    return value.strftime('%Y-%m-%d') if value else None


# El motor se crea en db.py y se reutiliza tanto en consultas como en transacciones.
engine = get_engine()

# Aquí se define la cuenta administrativa cuyas operaciones requieren autorización adicional.
ADMIN_EMAIL = 'Bibliotecario.fanoba@tecnica29de6.edu.ar'
PROTECTED_ROUTE_ROLES = {
    '/api/books': {'Bibliotecario'},
}

VALID_BAJA_MOTIVOS = {'Dañado', 'Extraviado', 'Retirado'}


# Migraciones de compatibilidad: agregan solo columnas faltantes a las tablas base.
def ensure_user_state_column():
    """Añade el estado de veto a instalaciones que todavía no lo tienen."""
    columns = {
        column['name'].lower()
        for column in sqlalchemy_inspect(engine).get_columns('usuario')
    }
    if 'estado' not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuario ADD COLUMN Estado VARCHAR(30) DEFAULT 'no vetado'"))
            conn.execute(text("UPDATE usuario SET Estado = 'no vetado' WHERE Estado IS NULL"))


def ensure_user_role_column():
    """Añade el rol y asigna uno inicial a cuentas preexistentes."""
    columns = {
        column['name'].lower()
        for column in sqlalchemy_inspect(engine).get_columns('usuario')
    }
    if 'tipo' not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuario ADD COLUMN Tipo VARCHAR(30) DEFAULT 'Alumno'"))
            conn.execute(
                text(
                    "UPDATE usuario SET Tipo = CASE "
                    "WHEN Gmail = :admin THEN 'Bibliotecario' "
                    "WHEN Gmail LIKE :alu THEN 'Alumno' "
                    "ELSE 'Profesor' END"
                ),
                {'admin': ADMIN_EMAIL, 'alu': '%@alu.%'}
            )


ensure_user_state_column()
ensure_user_role_column()


def ensure_baja_ejemplares_table():
    """Crea el registro de bajas técnicas sin reemplazar datos existentes."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS baja_ejemplares ("
            "ID_Baja INT AUTO_INCREMENT PRIMARY KEY, "
            "ID_Libro INT NOT NULL, "
            "ID_Usuario_Bibliotecario INT NOT NULL, "
            "Cantidad INT NOT NULL, "
            "Motivo VARCHAR(50) NOT NULL, "
            "Fecha DATETIME NOT NULL, "
            "FOREIGN KEY (ID_Libro) REFERENCES libro(ID_Libro), "
            "FOREIGN KEY (ID_Usuario_Bibliotecario) REFERENCES usuario(ID_Usuario)"
            ") ENGINE=InnoDB"
        ))


ensure_baja_ejemplares_table()

VALID_LOG_TYPES = {'Préstamo Activo', 'Préstamo Devuelto', 'Stock Reducido'}


def ensure_log_sistema_table():
    """Crea el historial de eventos y adapta el nombre de ID heredado."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS log_sistema ("
            "ID INT AUTO_INCREMENT PRIMARY KEY, "
            "Tipo_Evento VARCHAR(50) NOT NULL, "
            "ID_Usuario INT NOT NULL, "
            "ID_Libro INT NOT NULL, "
            "Descripcion TEXT, "
            "Fecha DATETIME NOT NULL, "
            "FOREIGN KEY (ID_Usuario) REFERENCES usuario(ID_Usuario), "
            "FOREIGN KEY (ID_Libro) REFERENCES libro(ID_Libro)"
            ") ENGINE=InnoDB"
        ))

        # Si una instalación anterior guardaba la columna con otro nombre, se adapta
        # para que el historial del sistema siga funcionando con el formato actual.
        has_id = conn.execute(text(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'log_sistema' AND COLUMN_NAME = 'ID'"
        )).fetchone()
        if not has_id:
            has_id_log = conn.execute(text(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'log_sistema' AND COLUMN_NAME = 'ID_Log'"
            )).fetchone()
            if has_id_log:
                conn.execute(text(
                    "ALTER TABLE log_sistema CHANGE COLUMN ID_Log ID INT NOT NULL AUTO_INCREMENT"
                ))


ensure_log_sistema_table()


def ensure_user_management_columns():
    """Prepara curso y datos de veto; conserva compatibilidad del historial."""
    with engine.begin() as conn:
        existing_columns = {
            (row[0].lower(), row[1].lower())
            for row in conn.execute(
                text(
                    "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('usuario', 'log_sistema')"
                )
            ).fetchall()
        }
        user_columns = {
            'Curso': "ALTER TABLE usuario ADD COLUMN Curso TINYINT UNSIGNED NULL",
            'Division': "ALTER TABLE usuario ADD COLUMN Division TINYINT UNSIGNED NULL",
            'Motivo_Veto': "ALTER TABLE usuario ADD COLUMN Motivo_Veto VARCHAR(255) NULL",
            'Veto_Hasta': "ALTER TABLE usuario ADD COLUMN Veto_Hasta DATETIME NULL",
        }
        for column, statement in user_columns.items():
            if ('usuario', column.lower()) not in existing_columns:
                conn.execute(text(statement))

        table_exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'log_sistema'"
            )
        ).fetchone()
        if not table_exists:
            raise RuntimeError('No existe log_sistema; no se puede preservar el historial de usuarios')
        if ('log_sistema', 'id_usuario') not in existing_columns:
            nullable = conn.execute(
                text(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'log_sistema' "
                    "AND COLUMN_NAME = 'ID_Usuario'"
                ),
            ).scalar()
            if nullable == 'NO':
                conn.execute(text('ALTER TABLE log_sistema MODIFY COLUMN ID_Usuario INT NULL'))


ensure_user_management_columns()


def ensure_book_total_stock_column():
    """Agrega el inventario total y lo inicializa desde el stock disponible."""
    with engine.begin() as conn:
        has_total_stock = conn.execute(
            text(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'libro' "
                "AND COLUMN_NAME = 'Stock_Total'"
            )
        ).fetchone()
        if has_total_stock:
            return

        conn.execute(text(
            "ALTER TABLE libro ADD COLUMN Stock_Total INT NOT NULL DEFAULT 0"
        ))
        conn.execute(text("UPDATE libro SET Stock_Total = Stock"))


ensure_book_total_stock_column()


def ensure_loan_schema():
    """Crea tablas e índices para préstamos escolares, domiciliarios y migraciones.

    Las claves foráneas preservan las relaciones y los índices aceleran búsquedas
    frecuentes por responsable, estado, libro y fecha.
    """
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS cuaderno_diario ("
            "ID_Cuaderno INT NOT NULL AUTO_INCREMENT, "
            "ID_Libro INT NOT NULL, "
            "ID_Responsable INT NULL, Responsable_Nombre VARCHAR(100) NOT NULL, "
            "ID_Retira INT NULL, Retira_Nombre VARCHAR(100) NULL, "
            "ID_Bibliotecaria INT NOT NULL, Cantidad INT UNSIGNED NOT NULL, "
            "Curso TINYINT UNSIGNED NOT NULL, Division TINYINT UNSIGNED NOT NULL, "
            "Fecha_Prestamo DATE NOT NULL, Fecha_Vencimiento DATE NOT NULL, "
            "Fecha_Devolucion DATE NULL, Estado VARCHAR(20) NOT NULL DEFAULT 'Activo', "
            "PRIMARY KEY (ID_Cuaderno), "
            "INDEX idx_cuaderno_estado_responsable (Estado, ID_Responsable), "
            "INDEX idx_cuaderno_libro_estado (ID_Libro, Estado), "
            "INDEX idx_cuaderno_fecha (Fecha_Prestamo), "
            "CONSTRAINT fk_cuaderno_libro FOREIGN KEY (ID_Libro) REFERENCES libro(ID_Libro), "
            "CONSTRAINT fk_cuaderno_responsable FOREIGN KEY (ID_Responsable) REFERENCES usuario(ID_Usuario) ON DELETE SET NULL, "
            "CONSTRAINT fk_cuaderno_retira FOREIGN KEY (ID_Retira) REFERENCES usuario(ID_Usuario) ON DELETE SET NULL, "
            "CONSTRAINT fk_cuaderno_bibliotecaria FOREIGN KEY (ID_Bibliotecaria) REFERENCES usuario(ID_Usuario), "
            "CONSTRAINT chk_cuaderno_cantidad CHECK (Cantidad > 0), "
            "CONSTRAINT chk_cuaderno_curso CHECK (Curso BETWEEN 1 AND 6), "
            "CONSTRAINT chk_cuaderno_division CHECK (Division BETWEEN 1 AND 10), "
            "CONSTRAINT chk_cuaderno_estado CHECK (Estado IN ('Activo', 'Devuelto'))"
            ") ENGINE=InnoDB"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS ficha_domiciliaria ("
            "ID_Ficha INT NOT NULL AUTO_INCREMENT, "
            "ID_Libro INT NOT NULL, "
            "ID_Responsable INT NULL, Responsable_Nombre VARCHAR(100) NOT NULL, "
            "ID_Bibliotecaria INT NOT NULL, Cantidad INT UNSIGNED NOT NULL, "
            "Apellido VARCHAR(100) NOT NULL, Nombre VARCHAR(100) NOT NULL, "
            "DNI VARCHAR(30) NOT NULL, Telefono VARCHAR(40) NOT NULL, "
            "Curso TINYINT UNSIGNED NOT NULL, Division TINYINT UNSIGNED NOT NULL, "
            "Dias INT UNSIGNED NOT NULL, Fecha_Prestamo DATE NOT NULL, Fecha_Vencimiento DATE NOT NULL, "
            "Fecha_Devolucion DATE NULL, Estado VARCHAR(20) NOT NULL DEFAULT 'Activo', "
            "PRIMARY KEY (ID_Ficha), "
            "INDEX idx_ficha_estado_responsable (Estado, ID_Responsable), "
            "INDEX idx_ficha_libro_estado (ID_Libro, Estado), "
            "INDEX idx_ficha_fecha (Fecha_Prestamo), "
            "CONSTRAINT fk_ficha_libro FOREIGN KEY (ID_Libro) REFERENCES libro(ID_Libro), "
            "CONSTRAINT fk_ficha_responsable FOREIGN KEY (ID_Responsable) REFERENCES usuario(ID_Usuario) ON DELETE SET NULL, "
            "CONSTRAINT fk_ficha_bibliotecaria FOREIGN KEY (ID_Bibliotecaria) REFERENCES usuario(ID_Usuario), "
            "CONSTRAINT chk_ficha_cantidad CHECK (Cantidad > 0), "
            "CONSTRAINT chk_ficha_curso CHECK (Curso BETWEEN 1 AND 6), "
            "CONSTRAINT chk_ficha_division CHECK (Division BETWEEN 1 AND 10), "
            "CONSTRAINT chk_ficha_dias CHECK (Dias > 0), "
            "CONSTRAINT chk_ficha_estado CHECK (Estado IN ('Activo', 'Devuelto'))"
            ") ENGINE=InnoDB"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migration ("
            "Migration_Key VARCHAR(100) NOT NULL PRIMARY KEY, "
            "Applied_At DATETIME NOT NULL"
            ") ENGINE=InnoDB"
        ))
ensure_loan_schema()


def ensure_graduated_account_fields():
    """Prepara egreso y actividad de cuenta y registra la migración aplicada."""
    with engine.begin() as conn:
        existing_columns = {
            row[0].lower(): (row[1], row[2])
            for row in conn.execute(
                text(
                    "SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'usuario'"
                )
            ).fetchall()
        }
        account_columns = {
            'Es_Egresado': (
                "ALTER TABLE usuario ADD COLUMN Es_Egresado TINYINT(1) NOT NULL DEFAULT 0",
                "ALTER TABLE usuario MODIFY COLUMN Es_Egresado TINYINT(1) NOT NULL DEFAULT 0",
                '0',
            ),
            'Cuenta_Activa': (
                "ALTER TABLE usuario ADD COLUMN Cuenta_Activa TINYINT(1) NOT NULL DEFAULT 1",
                "ALTER TABLE usuario MODIFY COLUMN Cuenta_Activa TINYINT(1) NOT NULL DEFAULT 1",
                '1',
            ),
        }
        for column, (add_statement, modify_statement, default) in account_columns.items():
            column_state = existing_columns.get(column.lower())
            if column_state is None:
                conn.execute(text(add_statement))
            else:
                nullable, current_default = column_state
                if nullable == 'YES':
                    conn.execute(
                        text(f"UPDATE usuario SET {column} = :default WHERE {column} IS NULL"),
                        {'default': int(default)},
                    )
                if nullable == 'YES' or str(current_default) != default:
                    conn.execute(text(modify_statement))

        migration_key = 'graduated_account_state_v1'
        migration_applied = conn.execute(
            text("SELECT 1 FROM schema_migration WHERE Migration_Key = :key"),
            {'key': migration_key},
        ).fetchone()
        if not migration_applied:
            conn.execute(
                text(
                    "INSERT INTO schema_migration (Migration_Key, Applied_At) "
                    "VALUES (:key, CURRENT_TIMESTAMP)"
                ),
                {'key': migration_key},
            )


ensure_graduated_account_fields()


# Modelos Pydantic: describen y validan el JSON recibido antes de ejecutar SQL.
class BookIn(BaseModel):
    """Campos necesarios para dar de alta un libro."""
    Titulo: str = Field(..., max_length=100)
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int = Field(0, ge=0)


class BookUpdate(BaseModel):
    """Campos opcionales para actualizar solo partes de un libro."""
    Titulo: str | None = None
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int | None = Field(None, ge=0)
    Motivo: str | None = None


class SchoolLoanIn(BaseModel):
    """Datos de un préstamo escolar y de la persona responsable."""
    ID_Libro: int = Field(..., gt=0)
    ID_Responsable: int = Field(..., gt=0)
    ID_Retira: int | None = Field(None, gt=0)
    Modalidad: str
    Cantidad: int = Field(..., ge=1)
    Curso: int = Field(..., ge=1, le=6)
    Division: int = Field(..., ge=1, le=10)


class HomeLoanIn(BaseModel):
    """Datos del préstamo domiciliario y de la ficha física."""
    ID_Libro: int = Field(..., gt=0)
    ID_Responsable: int = Field(..., gt=0)
    Cantidad: int = Field(..., ge=1)
    Dias: int = Field(30, ge=1)
    Apellido: str = Field(..., min_length=1, max_length=100)
    Nombre: str = Field(..., min_length=1, max_length=100)
    DNI: str = Field(..., min_length=1, max_length=30)
    Telefono: str = Field(..., min_length=1, max_length=40)


class StockReductionIn(BaseModel):
    """Cantidad y motivo requeridos para registrar una baja de inventario."""
    ID_Libro: int
    Cantidad: int
    Motivo: str


class UserStateUpdate(BaseModel):
    """Estado de veto y, al aplicarlo, motivo y duración."""
    Estado: str = Field(..., max_length=30)
    Motivo: str | None = Field(None, max_length=255)
    Duracion_Dias: int | None = Field(None, ge=1, le=365)


class GraduatedStatusUpdate(BaseModel):
    """Clasificación de egreso de un alumno de sexto curso."""
    Es_Egresado: bool


class AccountActivationUpdate(BaseModel):
    """Estado activo/inactivo para una cuenta de alumno egresado."""
    Cuenta_Activa: bool


class UserProfileUpdate(BaseModel):
    """Curso y división que completa o modifica el usuario."""
    Curso: int = Field(..., ge=1, le=6)
    Division: int = Field(..., ge=1, le=10)


class LoginIn(BaseModel):
    """Credenciales validadas para iniciar sesión."""
    Gmail: str = Field(..., min_length=1, max_length=320)
    Contraseña: str


class SignupIn(BaseModel):
    """Datos validados para crear una cuenta desde el formulario público."""
    Nombre_Completo: str = Field(..., min_length=1, max_length=100)
    Gmail: str = Field(..., min_length=1, max_length=320)
    Contraseña: str


def hash_password(password: str) -> str:
    """Genera una cadena PBKDF2 que contiene algoritmo, iteraciones, sal y hash."""
    # PBKDF2 combina una sal aleatoria y muchas iteraciones; no guarda la contraseña original.
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, PASSWORD_HASH_ITERATIONS
    )
    salt_encoded = base64.urlsafe_b64encode(salt).decode('ascii').rstrip('=')
    digest_encoded = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    return f'pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt_encoded}${digest_encoded}'


def verify_password(password: str, stored_password: str | None) -> tuple[bool, bool]:
    """Verifica el hash y devuelve (es_válida, es_contraseña_heredada)."""
    if not stored_password:
        return False, False
    if stored_password.startswith('pbkdf2_sha256$'):
        try:
            algorithm, iterations, salt_encoded, digest_encoded = stored_password.split('$')
            if algorithm != 'pbkdf2_sha256':
                return False, False
            salt = base64.urlsafe_b64decode(salt_encoded + '=' * (-len(salt_encoded) % 4))
            expected = base64.urlsafe_b64decode(digest_encoded + '=' * (-len(digest_encoded) % 4))
            if len(salt) != 16 or len(expected) != 32:
                return False, False
            iteration_count = int(iterations)
            if not 100_000 <= iteration_count <= 2_000_000:
                return False, False
            actual = hashlib.pbkdf2_hmac(
                'sha256', password.encode('utf-8'), salt, iteration_count
            )
        except (ValueError, TypeError):
            return False, False
        return hmac.compare_digest(actual, expected), False
    return hmac.compare_digest(
        password.encode('utf-8'), stored_password.encode('utf-8')
    ), True


def create_session(response: Response, user_id: int, request: Request):
    """Crea sesión temporal y envía el token opaco como cookie HttpOnly."""
    # Se guarda el resumen del token, no el token de la cookie; se eliminan sesiones vencidas.
    token = secrets.token_urlsafe(32)
    now = time.time()
    with sessions_lock:
        expired_keys = [key for key, (_, expires_at) in sessions.items() if expires_at <= now]
        for key in expired_keys:
            del sessions[key]
        sessions[hashlib.sha256(token.encode('ascii')).hexdigest()] = (user_id, now + SESSION_TTL_SECONDS)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == 'https',
        samesite='lax',
        path='/',
    )


def clear_session(response: Response, request: Request):
    """Invalida el token de la sesión actual y borra la cookie del navegador."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with sessions_lock:
            sessions.pop(hashlib.sha256(token.encode('utf-8')).hexdigest(), None)
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=request.url.scheme == 'https',
        samesite='lax',
        path='/',
    )


# El rol del usuario se infiere con la misma lógica que usa la interfaz para mostrar
# las vistas y bloquear accesos según si es alumno, profesor o bibliotecario.
def infer_user_type(gmail: str, stored_type: str | None = None) -> str:
    """Obtiene el rol guardado o, en cuentas antiguas, lo deduce del correo."""
    if stored_type:
        normalized = stored_type.strip().lower()
        if normalized == 'bibliotecario':
            return 'Bibliotecario'
        if normalized == 'profesor':
            return 'Profesor'
        return 'Alumno'
    if gmail.lower() == ADMIN_EMAIL.lower():
        return 'Bibliotecario'
    return 'Alumno' if '@alu.' in gmail.lower() else 'Profesor'


def get_request_identity(request: Request) -> int | None:
    """Busca la sesión de la cookie; elimina del almacenamiento tokens vencidos."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    key = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with sessions_lock:
        session = sessions.get(key)
        if not session:
            return None
        user_id, expires_at = session
        if expires_at <= time.time():
            sessions.pop(key, None)
            return None
        return user_id


def ensure_user_not_banned(conn, row):
    """Rechaza usuarios vetados y limpia un veto temporal ya vencido."""
    if row[3] != 'vetado':
        return

    ban_reason = row[5]
    ban_until = row[6]
    if ban_until and ban_until <= utc_now():
        conn.execute(
            text(
                "UPDATE usuario SET Estado = 'no vetado', Motivo_Veto = NULL, Veto_Hasta = NULL "
                "WHERE ID_Usuario = :id"
            ),
            {'id': row[0]},
        )
        return

    detail = f'Usuario vetado. Motivo: {ban_reason or "No especificado"}.'
    if ban_until:
        detail += f' Veto vigente hasta {format_datetime(ban_until)} UTC.'
    else:
        detail += ' El veto no tiene fecha de finalización.'
    raise HTTPException(status_code=403, detail=detail)


def ensure_user_active(row):
    """Rechaza cuentas inactivas aunque la persona no tenga un veto."""
    if not row[9]:
        raise HTTPException(status_code=403, detail='La cuenta está inactiva')


def get_authenticated_user(
    request: Request,
    allowed_roles: list[str] | None = None,
    require_admin_email: bool = False,
):
    """Carga la identidad desde la cookie y comprueba rol, actividad y veto.

    El middleware guarda el usuario en ``request.state`` para que las rutas
    protegidas puedan reutilizarlo durante la misma solicitud.
    """
    cached_user = getattr(request.state, 'user', None)
    if cached_user:
        actual_type = cached_user['Tipo']
        if allowed_roles and actual_type not in allowed_roles:
            raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')
        if require_admin_email and cached_user['Gmail'].lower() != ADMIN_EMAIL.lower():
            raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')
        return cached_user

    user_id = get_request_identity(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='No autenticado')

    # Si hay un usuario válido en la base, lo devolvemos junto a su estado
    # para que el middleware o la ruta puedan seguir con la ejecución.
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo, Motivo_Veto, Veto_Hasta, "
                "Curso, Division, Cuenta_Activa, Es_Egresado "
                "FROM usuario WHERE ID_Usuario = :id"
            ),
            {'id': user_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail='Usuario no encontrado')
        ensure_user_active(row)
        ensure_user_not_banned(conn, row)

    actual_type = infer_user_type(row[2], row[4])

    if allowed_roles and actual_type not in allowed_roles:
        raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')

    # Comprueba si se requiere que el usuario sea el administrador principal.
    if require_admin_email and row[2].lower() != ADMIN_EMAIL.lower():
        raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')

    user = {
        'ID_Usuario': row[0],
        'Nombre_Completo': row[1],
        'Gmail': row[2],
        'Estado': row[3],
        'Tipo': actual_type,
        'Curso': row[7],
        'Division': row[8],
        'Cuenta_Activa': bool(row[9]),
        'Es_Egresado': bool(row[10]),
    }
    request.state.user = user
    return user


# Cada baja de stock queda registrada para mantener un historial claro de los ejemplares
# que se dañaron, perdieron o retiraron del catálogo.
def insert_baja_record(conn, libro_id: int, bibliotecario_id: int, cantidad: int, motivo: str):
    """Guarda la baja técnica dentro de la transacción que modifica el stock."""
    motivo = motivo.strip()
    if motivo not in VALID_BAJA_MOTIVOS:
        raise HTTPException(status_code=400, detail=f'Motivo inválido: {motivo}')
    if cantidad <= 0:
        raise HTTPException(status_code=400, detail='La cantidad de baja debe ser mayor a cero')

    conn.execute(
        text(
            "INSERT INTO baja_ejemplares (ID_Libro, ID_Usuario_Bibliotecario, Cantidad, Motivo, Fecha)"
            " VALUES (:id_libro, :id_usuario, :cantidad, :motivo, :fecha)"
        ),
        {
            'id_libro': libro_id,
            'id_usuario': bibliotecario_id,
            'cantidad': cantidad,
            'motivo': motivo,
            'fecha': current_timestamp(),
        }
    )


def insert_log(conn, tipo_evento: str, usuario_id: int, libro_id: int, descripcion: str | None = None):
    """Agrega un evento permitido al historial de operaciones."""
    if tipo_evento not in VALID_LOG_TYPES:
        raise HTTPException(status_code=400, detail=f'Tipo de evento inválido: {tipo_evento}')
    conn.execute(
        text(
            "INSERT INTO log_sistema (Tipo_Evento, ID_Usuario, ID_Libro, Descripcion, Fecha)"
            " VALUES (:tipo, :id_usuario, :id_libro, :descripcion, :fecha)"
        ),
        {
            'tipo': tipo_evento,
            'id_usuario': usuario_id,
            'id_libro': libro_id,
            'descripcion': descripcion,
            'fecha': current_timestamp(),
        }
    )


# El decorador `require_role` aplica validación de usuario a nivel de ruta.
# Busca el objeto Request, verifica credenciales y bloquea accesos no autorizados
# antes de ejecutar la función del endpoint.
def require_role(*allowed_roles: str, require_admin_email: bool = False):
    """Protege una ruta y, opcionalmente, exige además el correo de administración."""
    # El decorador valida permisos en el servidor; ocultar una opción del menú no es seguridad.
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                request = kwargs.get('request') or next((arg for arg in args if isinstance(arg, Request)), None)
                if request is None:
                    raise HTTPException(status_code=401, detail='No autenticado')
                get_authenticated_user(request, allowed_roles=list(allowed_roles), require_admin_email=require_admin_email)
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            request = kwargs.get('request') or next((arg for arg in args if isinstance(arg, Request)), None)
            if request is None:
                raise HTTPException(status_code=401, detail='No autenticado')
            get_authenticated_user(request, allowed_roles=list(allowed_roles), require_admin_email=require_admin_email)
            return func(*args, **kwargs)

        return sync_wrapper

    return decorator


# Normaliza los parámetros de paginación recibidos desde la interfaz.
# Evita valores inválidos y establece valores mínimos seguros.
def normalize_pagination(page: int = 1, limit: int = 4) -> tuple[int, int]:
    """Evita páginas y límites menores que uno en las consultas de listas."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 4
    page = max(page, 1)
    limit = max(limit, 1)
    return page, limit


@app.middleware('http')
async def enforce_role_middleware(request: Request, call_next):
    """Comprueba sesiones en las rutas API y deja pasar rutas públicas."""
    user_id = get_request_identity(request)
    if user_id and request.url.path.startswith('/api/') and request.url.path not in (
        '/api/login', '/api/signup', '/api/logout'
    ):
        try:
            if request.url.path in PROTECTED_ROUTE_ROLES:
                get_authenticated_user(
                    request,
                    allowed_roles=list(PROTECTED_ROUTE_ROLES[request.url.path]),
                    require_admin_email=(request.url.path == '/api/books'),
                )
            else:
                get_authenticated_user(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})
    return await call_next(request)


# Rutas de autores y catálogo: abastecen la búsqueda y la administración de libros.
# El frontend solicita autores, libros y estados de usuario para renderizar
# los formularios y las tablas sin tener que reconstruir la lógica del backend.
@app.get('/api/authors')
def list_authors():
    """Lista autores para completar los selectores de libros."""
    with engine.connect() as conn:
        res = conn.execute(text("SELECT ID_Autor, Nombre FROM autor ORDER BY Nombre"))
        return [{'ID_Autor': row[0], 'Nombre': row[1]} for row in res.fetchall()]


# Los cambios de catálogo requieren el rol y el correo de la bibliotecaria principal.
@app.post('/api/books')
@require_role('Bibliotecario', require_admin_email=True)
def add_book(request: Request, book: BookIn):
    """Crea un libro e inicializa su stock disponible y total."""
    with engine.begin() as conn:
        # Se guarda el libro con parámetros SQL para evitar problemas con caracteres especiales.
        stmt = text(
            "INSERT INTO libro (Titulo, Editorial, ID_Autor, Año_Publicacion, ISBN, Sinopsis, Stock, Stock_Total)"
            " VALUES (:titulo, :editorial, :id_autor, :anio, :isbn, :sinopsis, :stock, :stock_total)"
        )
        params = {
            'titulo': book.Titulo,
            'editorial': book.Editorial,
            'id_autor': book.ID_Autor,
            'anio': book.Año_Publicacion,
            'isbn': book.ISBN,
            'sinopsis': book.Sinopsis,
            'stock': int(book.Stock or 0),
            'stock_total': int(book.Stock or 0),
        }
        try:
            res = conn.execute(stmt, params)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {'ok': True, 'inserted': res.lastrowid}


@app.get('/api/books/{book_id}')
@require_role('Bibliotecario', require_admin_email=True)
def get_book(request: Request, book_id: int):
    """Devuelve los datos completos de un libro para el formulario de edición."""
    with engine.connect() as conn:
        r = conn.execute(
            text(
                "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ID_Autor, l.Año_Publicacion, "
                "l.ISBN, l.Sinopsis, l.Stock, l.Stock_Total, a.Nombre "
                "FROM libro l LEFT JOIN autor a ON l.ID_Autor = a.ID_Autor "
                "WHERE l.ID_Libro = :id"
            ),
            {'id': book_id}
        ).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        return {
            'ID_Libro': r[0],
            'Titulo': r[1],
            'Editorial': r[2],
            'ID_Autor': r[3],
            'Año_Publicacion': r[4],
            'ISBN': r[5],
            'Sinopsis': r[6],
            'Stock': r[7],
            'Stock_Disponible': r[7],
            'Stock_Total': r[8],
            'Autor': r[9],
        }


@app.put('/api/books/{book_id}')
@require_role('Bibliotecario', require_admin_email=True)
def update_book(request: Request, book_id: int, book: BookUpdate):
    """Actualiza los campos enviados y registra reducciones de inventario."""
    user = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    with engine.begin() as conn:
        current = conn.execute(
            text(
                "SELECT Titulo, Editorial, ID_Autor, Año_Publicacion, ISBN, Sinopsis, Stock "
                "FROM libro WHERE ID_Libro = :id FOR UPDATE"
            ),
            {'id': book_id},
        ).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail='Libro no encontrado')

        updates = []
        params: dict[str, object] = {'id': book_id}
        if book.Titulo is not None:
            updates.append('Titulo = :titulo')
            params['titulo'] = book.Titulo
        if book.Editorial is not None:
            updates.append('Editorial = :editorial')
            params['editorial'] = book.Editorial
        if book.ID_Autor is not None:
            updates.append('ID_Autor = :id_autor')
            params['id_autor'] = book.ID_Autor
        if book.Año_Publicacion is not None:
            updates.append('Año_Publicacion = :anio')
            params['anio'] = book.Año_Publicacion
        if book.ISBN is not None:
            updates.append('ISBN = :isbn')
            params['isbn'] = book.ISBN
        if book.Sinopsis is not None:
            updates.append('Sinopsis = :sinopsis')
            params['sinopsis'] = book.Sinopsis

        current_stock = int(current[6])
        if book.Stock is not None:
            new_stock = int(book.Stock)
            if new_stock < 0:
                raise HTTPException(status_code=400, detail='Stock no puede ser negativo')
            if new_stock < current_stock:
                if not book.Motivo:
                    raise HTTPException(status_code=400, detail='Motivo requerido al reducir stock')
                reduction = current_stock - new_stock
                updates.append('Stock = :stock')
                params['stock'] = new_stock
                updates.append('Stock_Total = Stock_Total + :stock_delta')
                params['stock_delta'] = new_stock - current_stock
                conn.execute(text("UPDATE libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
                insert_baja_record(conn, book_id, user['ID_Usuario'], reduction, book.Motivo)
                insert_log(conn, 'Stock Reducido', user['ID_Usuario'], book_id, f'Stock reducido: {reduction} ejemplar(es) - Motivo: {book.Motivo}')
                return {'ok': True, 'updated': book_id, 'reduced': reduction}
            updates.append('Stock = :stock')
            params['stock'] = new_stock
            updates.append('Stock_Total = Stock_Total + :stock_delta')
            params['stock_delta'] = new_stock - current_stock

        if updates:
            conn.execute(text("UPDATE libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
        return {'ok': True, 'updated': book_id}


@app.delete('/api/books/{book_id}')
@require_role('Bibliotecario', require_admin_email=True)
def delete_book(request: Request, book_id: int):
    """Elimina un libro solo cuando no está referenciado por un historial."""
    with engine.begin() as conn:
        existing = conn.execute(
            text('SELECT 1 FROM libro WHERE ID_Libro = :id FOR UPDATE'),
            {'id': book_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail='Libro no encontrado')

        related_records = conn.execute(
            text(
                "SELECT 1 FROM cuaderno_diario WHERE ID_Libro = :id "
                "UNION ALL SELECT 1 FROM ficha_domiciliaria WHERE ID_Libro = :id "
                "UNION ALL SELECT 1 FROM baja_ejemplares WHERE ID_Libro = :id "
                "UNION ALL SELECT 1 FROM log_sistema WHERE ID_Libro = :id LIMIT 1"
            ),
            {'id': book_id},
        ).fetchone()
        if related_records:
            raise HTTPException(
                status_code=409,
                detail='No se puede eliminar el libro porque tiene registros en historiales protegidos',
            )
        conn.execute(text('DELETE FROM libro WHERE ID_Libro = :id'), {'id': book_id})
    return {'ok': True, 'deleted': book_id}


@app.post('/api/stock-reduction')
@require_role('Bibliotecario', require_admin_email=True)
def stock_reduction(request: Request, data: StockReductionIn):
    """Reduce stock disponible y total, guardando el motivo y el evento."""
    user = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    motivo = data.Motivo.strip() if data.Motivo else ''
    if motivo not in VALID_BAJA_MOTIVOS:
        raise HTTPException(status_code=400, detail='Motivo inválido')
    if data.Cantidad <= 0:
        raise HTTPException(status_code=400, detail='Cantidad inválida')

    with engine.begin() as conn:
        book = conn.execute(
            text("SELECT Stock FROM libro WHERE ID_Libro = :id FOR UPDATE"),
            {'id': data.ID_Libro},
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if book[0] < data.Cantidad:
            raise HTTPException(status_code=400, detail='Stock insuficiente para esta baja')
        conn.execute(
            text(
                "UPDATE libro SET Stock = Stock - :cantidad, "
                "Stock_Total = Stock_Total - :cantidad WHERE ID_Libro = :id"
            ),
            {'cantidad': data.Cantidad, 'id': data.ID_Libro},
        )
        insert_baja_record(conn, data.ID_Libro, user['ID_Usuario'], data.Cantidad, motivo)
        insert_log(conn, 'Stock Reducido', user['ID_Usuario'], data.ID_Libro, f'Stock reducido por baja técnica: {motivo}')
        return {'ok': True, 'ID_Libro': data.ID_Libro, 'Cantidad': data.Cantidad}


@app.get('/api/users')
@require_role('Bibliotecario')
def list_users(request: Request, role: str = 'all', page: int = 1, limit: int = 10):
    """Devuelve perfiles paginados y libera vetos temporales vencidos."""
    role = role.strip()
    page, limit = normalize_pagination(page, limit)
    if role == 'all':
        allowed_roles = ['Alumno', 'Profesor']
    elif role in ('Alumno', 'Profesor'):
        allowed_roles = [role]
    else:
        raise HTTPException(status_code=400, detail='Role inválido')

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE usuario SET Estado = 'no vetado', Motivo_Veto = NULL, Veto_Hasta = NULL "
                "WHERE Estado = 'vetado' AND Veto_Hasta IS NOT NULL AND Veto_Hasta <= UTC_TIMESTAMP()"
            )
        )
        count_stmt = text(
            "SELECT COUNT(*) FROM usuario WHERE Tipo IN (:tipo0, :tipo1)"
            if len(allowed_roles) == 2 else
            "SELECT COUNT(*) FROM usuario WHERE Tipo = :tipo"
        )
        count_params = {'tipo0': allowed_roles[0], 'tipo1': allowed_roles[1]} if len(allowed_roles) == 2 else {'tipo': allowed_roles[0]}
        total = conn.execute(count_stmt, count_params).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit

        if len(allowed_roles) == 1:
            stmt = text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Estado, Curso, Division, "
                "Motivo_Veto, Veto_Hasta, Es_Egresado, Cuenta_Activa "
                "FROM usuario WHERE Tipo = :tipo ORDER BY Tipo, Nombre_Completo LIMIT :limit OFFSET :offset"
            )
            rows = conn.execute(stmt, {'tipo': allowed_roles[0], 'limit': limit, 'offset': offset}).fetchall()
        else:
            stmt = text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Estado, Curso, Division, "
                "Motivo_Veto, Veto_Hasta, Es_Egresado, Cuenta_Activa "
                "FROM usuario WHERE Tipo IN (:tipo0, :tipo1) ORDER BY Tipo, Nombre_Completo LIMIT :limit OFFSET :offset"
            )
            rows = conn.execute(stmt, {'tipo0': allowed_roles[0], 'tipo1': allowed_roles[1], 'limit': limit, 'offset': offset}).fetchall()

    users = []
    for row in rows:
        users.append({
            'ID_Usuario': row[0],
            'Nombre_Completo': row[1],
            'Gmail': row[2],
            'Tipo': row[3],
            'Estado': row[4] or 'no vetado',
            'Curso': row[5],
            'Division': row[6],
            'Motivo_Veto': row[7],
            'Veto_Hasta': format_datetime(row[8]),
            'Es_Egresado': bool(row[9]),
            'Cuenta_Activa': bool(row[10]),
        })
    return {'total': int(total), 'page': page, 'pages': pages, 'users': users}


@app.put('/api/users/{user_id}/state')
@require_role('Bibliotecario')
def update_user_state(request: Request, user_id: int, data: UserStateUpdate):
    """Aplica o quita un veto; no confunde el veto con la actividad de la cuenta."""
    new_state = data.Estado.strip().lower()
    if new_state not in ['vetado', 'no vetado']:
        raise HTTPException(status_code=400, detail='Estado debe ser "vetado" o "no vetado"')

    ban_reason = None
    ban_until = None
    if new_state == 'vetado':
        ban_reason = data.Motivo.strip() if data.Motivo else ''
        if not ban_reason:
            raise HTTPException(status_code=400, detail='El motivo del veto es obligatorio')
        if data.Duracion_Dias is None:
            raise HTTPException(status_code=400, detail='La duración del veto es obligatoria')
        ban_until = utc_now() + datetime.timedelta(days=data.Duracion_Dias)

    with engine.begin() as conn:
        target = conn.execute(
            text('SELECT Tipo, Es_Egresado FROM usuario WHERE ID_Usuario = :id FOR UPDATE'),
            {'id': user_id}
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if target[0] == 'Bibliotecario':
            raise HTTPException(status_code=403, detail='No se puede vetar al bibliotecario')
        if new_state == 'vetado' and target[1]:
            raise HTTPException(status_code=409, detail='No se puede aplicar un veto nuevo a un egresado')

        result = conn.execute(
            text(
                "UPDATE usuario SET Estado = :estado, Motivo_Veto = :motivo, Veto_Hasta = :hasta "
                "WHERE ID_Usuario = :id"
            ),
            {'estado': new_state, 'motivo': ban_reason, 'hasta': ban_until, 'id': user_id}
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')

    return {
        'ok': True,
        'ID_Usuario': user_id,
        'Estado': new_state,
        'Motivo_Veto': ban_reason,
        'Veto_Hasta': format_datetime(ban_until),
    }


@app.put('/api/users/{user_id}/graduated-status')
@require_role('Bibliotecario')
def update_graduated_status(request: Request, user_id: int, data: GraduatedStatusUpdate):
    """Permite clasificar como egresado solo a un alumno de sexto curso."""
    with engine.begin() as conn:
        target = conn.execute(
            text('SELECT Tipo, Curso FROM usuario WHERE ID_Usuario = :id FOR UPDATE'),
            {'id': user_id},
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if target[0] != 'Alumno' or target[1] != 6:
            raise HTTPException(
                status_code=409,
                detail='La clasificación solo se puede cambiar para alumnos de 6.º curso',
            )
        conn.execute(
            text('UPDATE usuario SET Es_Egresado = :egresado WHERE ID_Usuario = :id'),
            {'egresado': data.Es_Egresado, 'id': user_id},
        )
    return {'ok': True, 'ID_Usuario': user_id, 'Es_Egresado': data.Es_Egresado}


@app.put('/api/users/{user_id}/activation')
@require_role('Bibliotecario')
def update_account_activation(request: Request, user_id: int, data: AccountActivationUpdate):
    """Activa/inactiva egresados sin borrar su cuenta ni su historial."""
    with engine.begin() as conn:
        target = conn.execute(
            text(
                'SELECT Tipo, Es_Egresado, Cuenta_Activa '
                'FROM usuario WHERE ID_Usuario = :id FOR UPDATE'
            ),
            {'id': user_id},
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if target[0] != 'Alumno' or not target[1]:
            raise HTTPException(status_code=409, detail='Solo se puede inactivar o reactivar a un alumno egresado')
        if not data.Cuenta_Activa:
            ensure_no_active_loans(conn, user_id)
        conn.execute(
            text('UPDATE usuario SET Cuenta_Activa = :active WHERE ID_Usuario = :id'),
            {'active': data.Cuenta_Activa, 'id': user_id},
        )
    return {
        'ok': True,
        'ID_Usuario': user_id,
        'Cuenta_Activa': data.Cuenta_Activa,
    }


@app.get('/api/profile')
@require_role('Alumno', 'Profesor')
def get_profile(request: Request):
    """Entrega el curso y la división del usuario autenticado."""
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor'])
    return {
        'ID_Usuario': user['ID_Usuario'],
        'Curso': user['Curso'],
        'Division': user['Division'],
        'complete': user['Curso'] is not None and user['Division'] is not None,
    }


@app.put('/api/profile')
@require_role('Alumno', 'Profesor')
def update_profile(request: Request, data: UserProfileUpdate):
    """Guarda curso y división en la cuenta del usuario autenticado."""
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor'])
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE usuario SET Curso = :curso, Division = :division WHERE ID_Usuario = :id'),
            {'curso': data.Curso, 'division': data.Division, 'id': user['ID_Usuario']},
        )
    user['Curso'] = data.Curso
    user['Division'] = data.Division
    return {'ok': True, 'Curso': data.Curso, 'Division': data.Division}


@app.get('/api/search')
def search(request: Request, title: str = '', page: int = 1, limit: int = 4):
    """Busca por título y devuelve libros paginados en formato JSON."""
    user_id = get_request_identity(request)
    if user_id:
        user = get_authenticated_user(request)
        if user['Tipo'] in ('Alumno', 'Profesor') and (
            user['Curso'] is None or user['Division'] is None
        ):
            raise HTTPException(
                status_code=409,
                detail='Completa tu curso y división en tu perfil antes de consultar el catálogo',
            )
    title = title.strip()
    page, limit = normalize_pagination(page, limit)
    q = f"%{title}%"
    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM libro WHERE Titulo LIKE :q"),
            {'q': q}
        ).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit
        stmt = text(
            "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ISBN, l.Sinopsis, l.Stock, "
            "l.Stock_Total, a.Nombre "
            "FROM libro l LEFT JOIN autor a ON l.ID_Autor = a.ID_Autor "
            "WHERE l.Titulo LIKE :q ORDER BY l.Titulo LIMIT :limit OFFSET :offset"
        )
        res = conn.execute(stmt, {'q': q, 'limit': limit, 'offset': offset})
        rows = []
        for r in res.fetchall():
            rows.append({
                'ID_Libro': r[0],
                'Titulo': r[1],
                'Editorial': r[2],
                'ISBN': r[3],
                'Sinopsis': r[4],
                'Stock': r[5],
                'Stock_Disponible': r[5],
                'Stock_Total': r[6],
                'Autor': r[7],
            })
        return {'total': int(total), 'page': page, 'pages': pages, 'books': rows}


@app.get('/api/logs')
@require_role('Bibliotecario')
def get_logs(request: Request, limit: int = 50):
    """Devuelve los eventos recientes para la vista de historial."""
    if limit <= 0:
        limit = 50
    with engine.connect() as conn:
        res = conn.execute(
            text(
                "SELECT l.ID, l.Tipo_Evento, l.ID_Usuario, u.Nombre_Completo, l.ID_Libro, lib.Titulo, l.Descripcion, l.Fecha "
                "FROM log_sistema l "
                "LEFT JOIN usuario u ON l.ID_Usuario = u.ID_Usuario "
                "LEFT JOIN libro lib ON l.ID_Libro = lib.ID_Libro "
                "ORDER BY l.Fecha DESC LIMIT :limit"
            ),
            {'limit': limit}
        )
        logs = []
        for row in res.fetchall():
            logs.append({
                'ID': row[0],
                'Tipo_Evento': row[1],
                'ID_Usuario': row[2],
                'Usuario': row[3],
                'ID_Libro': row[4],
                'Libro': row[5],
                'Descripcion': row[6],
                'Fecha': row[7].strftime('%Y-%m-%d %H:%M:%S') if row[7] else None,
            })
        return logs


LOAN_UNION_SQL = """
SELECT 'escolar' AS Tipo, c.ID_Cuaderno AS ID_Prestamo, c.ID_Libro, l.Titulo AS Libro, a.Nombre AS Autor,
       c.ID_Responsable, COALESCE(u.Nombre_Completo, c.Responsable_Nombre) AS Responsable,
       c.ID_Retira, c.Retira_Nombre AS Retirado_Por, c.Cantidad, c.Curso, c.Division,
       c.Fecha_Prestamo, c.Fecha_Vencimiento, c.Fecha_Devolucion, c.Estado,
       NULL AS Apellido, NULL AS Nombre_Ficha, NULL AS DNI, NULL AS Telefono, NULL AS Dias
FROM cuaderno_diario c
JOIN libro l ON l.ID_Libro = c.ID_Libro
LEFT JOIN autor a ON a.ID_Autor = l.ID_Autor
LEFT JOIN usuario u ON u.ID_Usuario = c.ID_Responsable
UNION ALL
SELECT 'domiciliario' AS Tipo, f.ID_Ficha AS ID_Prestamo, f.ID_Libro, l.Titulo AS Libro, a.Nombre AS Autor,
       f.ID_Responsable, COALESCE(u.Nombre_Completo, f.Responsable_Nombre) AS Responsable,
       NULL AS ID_Retira, NULL AS Retirado_Por, f.Cantidad, f.Curso, f.Division,
       f.Fecha_Prestamo, f.Fecha_Vencimiento, f.Fecha_Devolucion, f.Estado,
       f.Apellido, f.Nombre AS Nombre_Ficha, f.DNI, f.Telefono, f.Dias
FROM ficha_domiciliaria f
JOIN libro l ON l.ID_Libro = f.ID_Libro
LEFT JOIN autor a ON a.ID_Autor = l.ID_Autor
LEFT JOIN usuario u ON u.ID_Usuario = f.ID_Responsable
"""
# La unión normaliza columnas de los dos módulos para compartir filtros y tarjetas.


def loan_filters(tipo, estado, libro_id, persona, curso, division):
    """Construye filtros parametrizados para listados de préstamos."""
    conditions = []
    params: dict[str, object] = {}
    if tipo and tipo != 'todos':
        if tipo not in ('escolar', 'domiciliario'):
            raise HTTPException(status_code=400, detail='Tipo de préstamo inválido')
        conditions.append('Tipo = :tipo')
        params['tipo'] = tipo
    if estado and estado != 'todos':
        if estado not in ('Activo', 'Devuelto'):
            raise HTTPException(status_code=400, detail='Estado de préstamo inválido')
        conditions.append('Estado = :estado')
        params['estado'] = estado
    if libro_id is not None:
        if libro_id <= 0:
            raise HTTPException(status_code=400, detail='Libro inválido')
        conditions.append('ID_Libro = :libro_id')
        params['libro_id'] = libro_id
    if persona:
        conditions.append('Responsable LIKE :persona')
        params['persona'] = f'%{persona.strip()}%'
    if curso is not None:
        if not 1 <= curso <= 6:
            raise HTTPException(status_code=400, detail='Curso inválido')
        conditions.append('Curso = :curso')
        params['curso'] = curso
    if division is not None:
        if not 1 <= division <= 10:
            raise HTTPException(status_code=400, detail='División inválida')
        conditions.append('Division = :division')
        params['division'] = division
    return (' WHERE ' + ' AND '.join(conditions) if conditions else ''), params


def loan_record(row):
    """Convierte una fila de la unión SQL al objeto JSON público."""
    return {
        'Tipo': row[0],
        'ID_Prestamo': row[1],
        'ID_Libro': row[2],
        'Libro': row[3],
        'Autor': row[4],
        'ID_Responsable': row[5],
        'Responsable': row[6],
        'ID_Retira': row[7],
        'Retirado_Por': row[8],
        'Cantidad': row[9],
        'Curso': row[10],
        'Division': row[11],
        'Fecha_Prestamo': format_date(row[12]),
        'Fecha_Vencimiento': format_date(row[13]),
        'Fecha_Devolucion': format_date(row[14]),
        'Estado': row[15],
        'Apellido': row[16],
        'Nombre_Ficha': row[17],
        'DNI': row[18],
        'Telefono': row[19],
        'Dias': row[20],
    }


def paginated_loans(conn, page, limit, filters, params, owner_id=None):
    """Consulta préstamos paginados, opcionalmente limitados al responsable."""
    page, limit = normalize_pagination(page, limit)
    limit = min(limit, 100)
    owner_filter = (
        (' AND ' if filters else ' WHERE ') + 'ID_Responsable = :owner_id'
        if owner_id is not None else ''
    )
    query = f'WITH loans AS ({LOAN_UNION_SQL})'
    total = conn.execute(
        text(query + ' SELECT COUNT(*) FROM loans' + filters + owner_filter),
        {**params, **({'owner_id': owner_id} if owner_id is not None else {})},
    ).scalar() or 0
    pages = max(1, (int(total) + limit - 1) // limit)
    page = min(page, pages)
    rows = conn.execute(
        text(
            query + ' SELECT * FROM loans' + filters + owner_filter
            + ' ORDER BY Fecha_Prestamo DESC, ID_Prestamo DESC LIMIT :limit OFFSET :offset'
        ),
        {
            **params,
            **({'owner_id': owner_id} if owner_id is not None else {}),
            'limit': limit,
            'offset': (page - 1) * limit,
        },
    ).fetchall()
    return {'total': int(total), 'page': page, 'pages': pages, 'prestamos': [loan_record(row) for row in rows]}


@app.get('/api/loan-users')
@require_role('Bibliotecario', require_admin_email=True)
def list_loan_users(request: Request):
    """Lista cuentas activas que la bibliotecaria puede seleccionar."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Curso, Division "
                "FROM usuario WHERE Tipo IN ('Alumno', 'Profesor') AND Cuenta_Activa = 1 "
                "ORDER BY Tipo, Nombre_Completo"
            )
        ).fetchall()
    return [
        {
            'ID_Usuario': row[0],
            'Nombre_Completo': row[1],
            'Gmail': row[2],
            'Tipo': row[3],
            'Curso': row[4],
            'Division': row[5],
        }
        for row in rows
    ]


@app.get('/api/loans')
@require_role('Bibliotecario', require_admin_email=True)
def list_all_loans(
    request: Request,
    tipo: str = 'todos',
    estado: str = 'todos',
    libro_id: int | None = None,
    persona: str = '',
    curso: int | None = None,
    division: int | None = None,
    page: int = 1,
    limit: int = 20,
):
    """Lista préstamos globales aplicando los filtros de administración."""
    filters, params = loan_filters(tipo, estado, libro_id, persona, curso, division)
    with engine.connect() as conn:
        return paginated_loans(conn, page, limit, filters, params)


@app.get('/api/my-loans')
@require_role('Alumno', 'Profesor')
def list_my_loans(
    request: Request,
    estado: str = 'todos',
    tipo: str = 'todos',
    page: int = 1,
    limit: int = 20,
):
    """Limita el historial al usuario autenticado; no acepta un dueño del cliente."""
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor'])
    filters, params = loan_filters(tipo, estado, None, '', None, None)
    with engine.connect() as conn:
        return paginated_loans(conn, page, limit, filters, params, user['ID_Usuario'])


@app.post('/api/loans/school')
@require_role('Bibliotecario', require_admin_email=True)
def create_school_loan(request: Request, data: SchoolLoanIn):
    """Crea un Cuaderno Diario, descuenta stock y registra el movimiento juntos."""
    librarian = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    modalidad = data.Modalidad.strip()
    if modalidad not in ('Alumno', 'Profesor', 'AlumnoPorProfesor'):
        raise HTTPException(status_code=400, detail='Modalidad escolar inválida')
    if (modalidad == 'AlumnoPorProfesor') != (data.ID_Retira is not None):
        raise HTTPException(status_code=400, detail='Indica el alumno que retira solo para un préstamo por profesor')

    today = datetime.date.today()
    with engine.begin() as conn:
        responsible = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Tipo, Estado, Curso, Division, Cuenta_Activa "
                "FROM usuario WHERE ID_Usuario = :id FOR UPDATE"
            ),
            {'id': data.ID_Responsable},
        ).fetchone()
        if not responsible:
            raise HTTPException(status_code=404, detail='Cuenta responsable no encontrada')
        expected_role = 'Alumno' if modalidad == 'Alumno' else 'Profesor'
        if responsible[2] != expected_role:
            raise HTTPException(status_code=400, detail=f'La cuenta responsable debe ser de tipo {expected_role}')
        if not responsible[6]:
            raise HTTPException(status_code=403, detail='La cuenta responsable está inactiva')
        if responsible[3] == 'vetado':
            raise HTTPException(status_code=403, detail='La cuenta responsable está vetada')
        if responsible[4] is None or responsible[5] is None:
            raise HTTPException(status_code=409, detail='La cuenta responsable debe completar curso y división')

        retira = None
        if data.ID_Retira is not None:
            retira = conn.execute(
                text(
                    "SELECT ID_Usuario, Nombre_Completo, Tipo, Cuenta_Activa "
                    "FROM usuario WHERE ID_Usuario = :id FOR UPDATE"
                ),
                {'id': data.ID_Retira},
            ).fetchone()
            if not retira:
                raise HTTPException(status_code=404, detail='Cuenta del alumno que retira no encontrada')
            if retira[2] != 'Alumno':
                raise HTTPException(status_code=400, detail='Solo un alumno puede retirar por indicación docente')
            if not retira[3]:
                raise HTTPException(status_code=403, detail='La cuenta del alumno que retira está inactiva')

        active_school = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM cuaderno_diario "
                "WHERE ID_Responsable = :id AND Estado = 'Activo'"
            ),
            {'id': data.ID_Responsable},
        ).scalar() or 0
        active_home = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM ficha_domiciliaria "
                "WHERE ID_Responsable = :id AND Estado = 'Activo'"
            ),
            {'id': data.ID_Responsable},
        ).scalar() or 0
        if expected_role == 'Alumno' and int(active_school) + int(active_home) + data.Cantidad > 1:
            raise HTTPException(status_code=409, detail='Un alumno solo puede tener 1 ejemplar escolar activo en total')
        if expected_role == 'Profesor' and int(active_school) + int(active_home) + data.Cantidad > 45:
            available = max(0, 45 - int(active_school) - int(active_home))
            raise HTTPException(
                status_code=409,
                detail=f'El profesor solo tiene saldo disponible para {available} ejemplar(es) de su máximo de 45',
            )

        book = conn.execute(
            text('SELECT Stock FROM libro WHERE ID_Libro = :id FOR UPDATE'),
            {'id': data.ID_Libro},
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if int(book[0] or 0) < data.Cantidad:
            raise HTTPException(status_code=409, detail='Stock insuficiente')
        conn.execute(
            text('UPDATE libro SET Stock = Stock - :cantidad WHERE ID_Libro = :id AND Stock >= :cantidad'),
            {'cantidad': data.Cantidad, 'id': data.ID_Libro},
        )
        result = conn.execute(
            text(
                "INSERT INTO cuaderno_diario "
                "(ID_Libro, ID_Responsable, Responsable_Nombre, ID_Retira, Retira_Nombre, "
                "ID_Bibliotecaria, Cantidad, Curso, Division, Fecha_Prestamo, Fecha_Vencimiento, Estado) "
                "VALUES (:libro, :responsable, :responsable_nombre, :retira, :retira_nombre, "
                ":bibliotecaria, :cantidad, :curso, :division, :fecha, :fecha, 'Activo')"
            ),
            {
                'libro': data.ID_Libro,
                'responsable': data.ID_Responsable,
                'responsable_nombre': responsible[1],
                'retira': retira[0] if retira else None,
                'retira_nombre': retira[1] if retira else None,
                'bibliotecaria': librarian['ID_Usuario'],
                'cantidad': data.Cantidad,
                'curso': data.Curso,
                'division': data.Division,
                'fecha': today,
            },
        )
        loan_id = result.lastrowid
        insert_log(
            conn,
            'Préstamo Activo',
            data.ID_Responsable,
            data.ID_Libro,
            f'Cuaderno Diario #{loan_id}: {data.Cantidad} ejemplar(es), responsable {responsible[1]}',
        )
    return {'ok': True, 'ID_Prestamo': loan_id, 'Fecha_Prestamo': format_date(today), 'Fecha_Vencimiento': format_date(today)}


@app.post('/api/loans/home')
@require_role('Bibliotecario', require_admin_email=True)
def create_home_loan(request: Request, data: HomeLoanIn):
    """Crea una Ficha Domiciliaria con vencimiento y responsable docente."""
    librarian = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    values = (data.Apellido.strip(), data.Nombre.strip(), data.DNI.strip(), data.Telefono.strip())
    if not all(values):
        raise HTTPException(status_code=400, detail='Apellido, nombre, DNI y teléfono son obligatorios')

    today = datetime.date.today()
    try:
        due = today + datetime.timedelta(days=data.Dias)
    except OverflowError as exc:
        raise HTTPException(status_code=400, detail='La cantidad de días excede el calendario admitido') from exc
    with engine.begin() as conn:
        responsible = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Tipo, Estado, Curso, Division, Cuenta_Activa "
                "FROM usuario WHERE ID_Usuario = :id FOR UPDATE"
            ),
            {'id': data.ID_Responsable},
        ).fetchone()
        if not responsible:
            raise HTTPException(status_code=404, detail='Cuenta responsable no encontrada')
        if responsible[2] != 'Profesor':
            raise HTTPException(status_code=400, detail='El préstamo domiciliario solo puede asignarse a un profesor')
        if not responsible[6]:
            raise HTTPException(status_code=403, detail='La cuenta responsable está inactiva')
        if responsible[3] == 'vetado':
            raise HTTPException(status_code=403, detail='La cuenta responsable está vetada')
        if responsible[4] is None or responsible[5] is None:
            raise HTTPException(status_code=409, detail='El profesor debe completar curso y división en su perfil')

        active_school = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM cuaderno_diario "
                "WHERE ID_Responsable = :id AND Estado = 'Activo'"
            ),
            {'id': data.ID_Responsable},
        ).scalar() or 0
        active_home = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM ficha_domiciliaria "
                "WHERE ID_Responsable = :id AND Estado = 'Activo'"
            ),
            {'id': data.ID_Responsable},
        ).scalar() or 0
        available = 45 - int(active_school) - int(active_home)
        if data.Cantidad > available:
            raise HTTPException(
                status_code=409,
                detail=f'El profesor solo tiene saldo disponible para {max(0, available)} ejemplar(es) de su máximo de 45',
            )

        book = conn.execute(
            text('SELECT Stock FROM libro WHERE ID_Libro = :id FOR UPDATE'),
            {'id': data.ID_Libro},
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if int(book[0] or 0) < data.Cantidad:
            raise HTTPException(status_code=409, detail='Stock insuficiente')
        conn.execute(
            text('UPDATE libro SET Stock = Stock - :cantidad WHERE ID_Libro = :id AND Stock >= :cantidad'),
            {'cantidad': data.Cantidad, 'id': data.ID_Libro},
        )
        result = conn.execute(
            text(
                "INSERT INTO ficha_domiciliaria "
                "(ID_Libro, ID_Responsable, Responsable_Nombre, ID_Bibliotecaria, Cantidad, "
                "Apellido, Nombre, DNI, Telefono, Curso, Division, Dias, Fecha_Prestamo, "
                "Fecha_Vencimiento, Estado) "
                "VALUES (:libro, :responsable, :responsable_nombre, :bibliotecaria, :cantidad, "
                ":apellido, :nombre, :dni, :telefono, :curso, :division, :dias, :fecha, :vencimiento, 'Activo')"
            ),
            {
                'libro': data.ID_Libro,
                'responsable': data.ID_Responsable,
                'responsable_nombre': responsible[1],
                'bibliotecaria': librarian['ID_Usuario'],
                'cantidad': data.Cantidad,
                'apellido': values[0],
                'nombre': values[1],
                'dni': values[2],
                'telefono': values[3],
                'curso': responsible[4],
                'division': responsible[5],
                'dias': data.Dias,
                'fecha': today,
                'vencimiento': due,
            },
        )
        loan_id = result.lastrowid
        insert_log(
            conn,
            'Préstamo Activo',
            data.ID_Responsable,
            data.ID_Libro,
            f'Ficha Domiciliaria #{loan_id}: {data.Cantidad} ejemplar(es), vencimiento {format_date(due)}',
        )
    return {'ok': True, 'ID_Prestamo': loan_id, 'Fecha_Prestamo': format_date(today), 'Fecha_Vencimiento': format_date(due)}


@app.post('/api/loans/{tipo}/{loan_id}/return')
@require_role('Bibliotecario', require_admin_email=True)
def return_loan(request: Request, tipo: str, loan_id: int):
    """Cierra un préstamo activo, devuelve sus ejemplares al stock y registra el evento."""
    if tipo == 'escolar':
        table, id_column = 'cuaderno_diario', 'ID_Cuaderno'
    elif tipo == 'domiciliario':
        table, id_column = 'ficha_domiciliaria', 'ID_Ficha'
    else:
        raise HTTPException(status_code=400, detail='Tipo de préstamo inválido')

    today = datetime.date.today()
    with engine.begin() as conn:
        loan = conn.execute(
            text(f"SELECT ID_Libro, Cantidad, Estado FROM {table} WHERE {id_column} = :id FOR UPDATE"),
            {'id': loan_id},
        ).fetchone()
        if not loan:
            raise HTTPException(status_code=404, detail='Préstamo no encontrado')
        if loan[2] != 'Activo':
            raise HTTPException(status_code=409, detail='El préstamo ya fue devuelto')
        updated = conn.execute(
            text(
                f"UPDATE {table} SET Estado = 'Devuelto', Fecha_Devolucion = :fecha "
                f"WHERE {id_column} = :id AND Estado = 'Activo'"
            ),
            {'fecha': today, 'id': loan_id},
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail='El préstamo ya fue devuelto')
        conn.execute(
            text('UPDATE libro SET Stock = Stock + :cantidad WHERE ID_Libro = :id'),
            {'cantidad': loan[1], 'id': loan[0]},
        )
        librarian = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
        insert_log(
            conn,
            'Préstamo Devuelto',
            librarian['ID_Usuario'],
            loan[0],
            f'{tipo.title()} #{loan_id} devuelto; se repusieron {loan[1]} ejemplar(es)',
        )
    return {'ok': True, 'ID_Prestamo': loan_id, 'Estado': 'Devuelto', 'Cantidad_Repuesta': loan[1]}


@app.get('/api/history/bajas')
@require_role('Bibliotecario')
def get_history_bajas(request: Request, page: int = 1, limit: int = 20):
    """Devuelve el historial protegido de bajas en páginas."""
    page, limit = normalize_pagination(page, limit)
    with engine.connect() as conn:
        total = conn.execute(text('SELECT COUNT(*) FROM baja_ejemplares')).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit
        res = conn.execute(
            text(
                "SELECT b.ID_Baja, b.ID_Libro, lib.Titulo, b.ID_Usuario_Bibliotecario, u.Nombre_Completo, b.Cantidad, b.Motivo, b.Fecha "
                "FROM baja_ejemplares b "
                "LEFT JOIN usuario u ON b.ID_Usuario_Bibliotecario = u.ID_Usuario "
                "LEFT JOIN libro lib ON b.ID_Libro = lib.ID_Libro "
                "ORDER BY b.ID_Baja DESC LIMIT :limit OFFSET :offset"
            ),
            {'limit': limit, 'offset': offset}
        )
        records = []
        for row in res.fetchall():
            records.append({
                'ID_Baja': row[0],
                'ID_Libro': row[1],
                'Libro': row[2],
                'ID_Usuario_Bibliotecario': row[3],
                'Usuario': row[4],
                'Cantidad': row[5],
                'Motivo': row[6],
                'Fecha': row[7].strftime('%Y-%m-%d %H:%M:%S') if row[7] else None,
            })
        return {'total': int(total), 'page': page, 'pages': pages, 'bajas': records}


@app.delete('/api/history/bajas')
@require_role('Bibliotecario')
def delete_history_bajas(request: Request):
    """Mantiene explícitamente bloqueado el borrado del historial."""
    raise HTTPException(status_code=403, detail='El historial de bajas está protegido y no se puede vaciar')


@app.post('/api/login')
def login(data: LoginIn, request: Request, response: Response):
    """Verifica credenciales y migra a PBKDF2 si la contraseña era heredada."""
    if not 1 <= len(data.Contraseña) <= 256:
        raise HTTPException(status_code=400, detail='La contraseña tiene un formato inválido')
    with engine.begin() as conn:
        r = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo, Motivo_Veto, Veto_Hasta, "
                "Curso, Division, Cuenta_Activa, Es_Egresado, Contraseña "
                "FROM usuario WHERE Gmail = :g"
            ),
            {'g': data.Gmail},
        ).fetchone()
        if not r:
            raise HTTPException(status_code=401, detail='Credenciales inválidas')
        password_valid, is_legacy_password = verify_password(data.Contraseña, r[11])
        if not password_valid:
            raise HTTPException(status_code=401, detail='Credenciales inválidas')
        if is_legacy_password:
            conn.execute(
                text("UPDATE usuario SET Contraseña = :password WHERE ID_Usuario = :id"),
                {'password': hash_password(data.Contraseña), 'id': r[0]},
            )
        ensure_user_active(r)
        ensure_user_not_banned(conn, r)
        state = 'no vetado' if r[3] == 'vetado' and r[6] else r[3]
        gmail = r[2]
        tipo = infer_user_type(gmail, r[4])
        result = {
            'ID_Usuario': r[0],
            'Nombre_Completo': r[1],
            'Gmail': r[2],
            'Estado': state,
            'Tipo': tipo,
            'Curso': r[7],
            'Division': r[8],
            'Cuenta_Activa': bool(r[9]),
            'Es_Egresado': bool(r[10]),
        }
    create_session(response, r[0], request)
    return result


@app.get('/api/session')
def get_session(request: Request):
    """Devuelve el usuario de la cookie actual para restaurar la interfaz."""
    user = get_authenticated_user(request)
    return {
        'ID_Usuario': user['ID_Usuario'],
        'Nombre_Completo': user['Nombre_Completo'],
        'Gmail': user['Gmail'],
        'Estado': user['Estado'],
        'Tipo': user['Tipo'],
        'Curso': user['Curso'],
        'Division': user['Division'],
        'Cuenta_Activa': user['Cuenta_Activa'],
        'Es_Egresado': user['Es_Egresado'],
    }


@app.post('/api/logout')
def logout(request: Request, response: Response):
    """Finaliza la sesión actual en servidor y navegador."""
    clear_session(response, request)
    return {'ok': True}


@app.post('/api/signup')
def signup(data: SignupIn, request: Request, response: Response):
    """Registra una cuenta pública y crea su sesión inicial."""
    if not 12 <= len(data.Contraseña) <= 256:
        raise HTTPException(
            status_code=400,
            detail='La contraseña debe tener entre 12 y 256 caracteres',
        )
    if data.Gmail.strip().lower() == ADMIN_EMAIL.lower():
        raise HTTPException(status_code=403, detail='Esta cuenta no puede registrarse desde el formulario público')
    tipo = infer_user_type(data.Gmail)
    with engine.begin() as conn:
        # Verificar si el Gmail ya existe
        existing = conn.execute(text("SELECT 1 FROM usuario WHERE Gmail = :g"), {'g': data.Gmail}).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail='El correo ya está registrado')
        # Insertar nuevo usuario
        stmt = text(
            "INSERT INTO usuario (Nombre_Completo, Gmail, Contraseña, Estado, Tipo)"
            " VALUES (:nombre, :gmail, :contraseña, 'no vetado', :tipo)"
        )
        res = conn.execute(stmt, {
            'nombre': data.Nombre_Completo,
            'gmail': data.Gmail,
            'contraseña': hash_password(data.Contraseña),
            'tipo': tipo,
        })
        new_id = res.lastrowid
    create_session(response, new_id, request)
    return {'ok': True, 'ID_Usuario': new_id, 'Nombre_Completo': data.Nombre_Completo, 'Gmail': data.Gmail, 'Tipo': tipo}


# Montaje del frontend: FastAPI entrega tanto los recursos de /static como index.html.
static_dir = Path(__file__).resolve().parent.parent / 'static'
if static_dir.exists():
    app.mount('/static', StaticFiles(directory=str(static_dir)), name='static_files')
    # La ruta raíz sirve index.html; la API sigue disponible bajo /api/.
    app.mount('/', StaticFiles(directory=str(static_dir), html=True), name='static')
else:
    # Permite ejecutar las rutas API aunque se haya quitado el frontend.
    pass
