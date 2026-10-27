"""API principal de Lorekeeper para catálogo, préstamos y perfiles."""

import datetime
import inspect
from functools import wraps
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import get_engine
from backend.user_deletion import ensure_no_active_loans

app = FastAPI(title='Lorekeeper API')


def current_timestamp() -> str:
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def format_datetime(value) -> str | None:
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else None


def format_date(value) -> str | None:
    return value.strftime('%Y-%m-%d') if value else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = get_engine()

# El motor SQLAlchemy es el punto central del backend.
# Las rutas reutilizan esta conexión para mantener la lógica de datos clara y compartida.
# La aplicación no vuelve a crear el engine en cada petición.
# La conexión ya quedó preparada en el módulo de base de datos y se reutiliza
# para todas las operaciones de la biblioteca: usuarios, libros, préstamos y reportes.

# Aquí se definen los roles base y los usuarios iniciales que van a poder entrar al sistema.
ADMIN_EMAIL = 'Bibliotecario.fanoba@tecnica29de6.edu.ar'
PROTECTED_ROUTE_ROLES = {
    '/api/books': {'Bibliotecario'},
}

DEFAULT_USERS = [
    {
        'Nombre_Completo': 'Vladimir Gaspar',
        'Gmail': 'vladimir.gaspar.672@alu.tecnica29de6.edu.ar',
        'Contraseña': 'hash_pass_123',
        'Tipo': 'Alumno',
    },
    {
        'Nombre_Completo': 'Alan Etkin',
        'Gmail': 'alan.etkin@tecnica29de6.edu.ar',
        'Contraseña': 'hash_pass_profe',
        'Tipo': 'Profesor',
    },
    {
        'Nombre_Completo': 'Bibliotecario Fanoba',
        'Gmail': ADMIN_EMAIL,
        'Contraseña': 'hash_pass_67',
        'Tipo': 'Bibliotecario',
    },
]

VALID_BAJA_MOTIVOS = {'Dañado', 'Extraviado', 'Retirado'}


# Al iniciar la API se revisa y actualiza el esquema si hace falta.
def ensure_user_state_column():
    try:
        with engine.begin() as conn:
            conn.execute(text('SELECT Estado FROM Usuario LIMIT 1'))
    except Exception:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE Usuario ADD COLUMN Estado VARCHAR(30) DEFAULT 'no vetado'"))
            conn.execute(text("UPDATE Usuario SET Estado = 'no vetado' WHERE Estado IS NULL"))


def ensure_user_role_column():
    try:
        with engine.begin() as conn:
            conn.execute(text('SELECT Tipo FROM Usuario LIMIT 1'))
    except Exception:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE Usuario ADD COLUMN Tipo VARCHAR(30) DEFAULT 'Alumno'"))
            conn.execute(
                text(
                    "UPDATE Usuario SET Tipo = CASE "
                    "WHEN Gmail = :admin THEN 'Bibliotecario' "
                    "WHEN Gmail LIKE :alu THEN 'Alumno' "
                    "ELSE 'Profesor' END"
                ),
                {'admin': ADMIN_EMAIL, 'alu': '%@alu.%'}
            )


ensure_user_state_column()
ensure_user_role_column()


# Se cargan cuentas de ejemplo para probar la app desde el primer inicio.
# Así se puede entrar con alumno, profesor y bibliotecario sin crear usuarios manualmente.
def ensure_default_users():
    with engine.begin() as conn:
        for user in DEFAULT_USERS:
            existing = conn.execute(
                text('SELECT 1 FROM Usuario WHERE Gmail = :g'),
                {'g': user['Gmail']}
            ).fetchone()
            if not existing:
                conn.execute(
                    text(
                        "INSERT INTO Usuario (Nombre_Completo, Gmail, Contraseña, Estado, Tipo)"
                        " VALUES (:nombre, :gmail, :pass, 'no vetado', :tipo)"
                    ),
                    {
                        'nombre': user['Nombre_Completo'],
                        'gmail': user['Gmail'],
                        'pass': user['Contraseña'],
                        'tipo': user['Tipo'],
                    }
                )


ensure_default_users()


def ensure_baja_ejemplares_table():
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS Baja_Ejemplares ("
            "ID_Baja INT AUTO_INCREMENT PRIMARY KEY, "
            "ID_Libro INT NOT NULL, "
            "ID_Usuario_Bibliotecario INT NOT NULL, "
            "Cantidad INT NOT NULL, "
            "Motivo VARCHAR(50) NOT NULL, "
            "Fecha DATETIME NOT NULL, "
            "FOREIGN KEY (ID_Libro) REFERENCES Libro(ID_Libro), "
            "FOREIGN KEY (ID_Usuario_Bibliotecario) REFERENCES Usuario(ID_Usuario)"
            ") ENGINE=InnoDB"
        ))


ensure_baja_ejemplares_table()

VALID_LOG_TYPES = {'Préstamo Activo', 'Préstamo Devuelto', 'Stock Reducido'}


def ensure_log_sistema_table():
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS Log_Sistema ("
            "ID INT AUTO_INCREMENT PRIMARY KEY, "
            "Tipo_Evento VARCHAR(50) NOT NULL, "
            "ID_Usuario INT NOT NULL, "
            "ID_Libro INT NOT NULL, "
            "Descripcion TEXT, "
            "Fecha DATETIME NOT NULL, "
            "FOREIGN KEY (ID_Usuario) REFERENCES Usuario(ID_Usuario), "
            "FOREIGN KEY (ID_Libro) REFERENCES Libro(ID_Libro)"
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
                    "ALTER TABLE Log_Sistema CHANGE COLUMN ID_Log ID INT NOT NULL AUTO_INCREMENT"
                ))


ensure_log_sistema_table()


def ensure_user_management_columns():
    with engine.begin() as conn:
        existing_columns = {
            (row[0].lower(), row[1].lower())
            for row in conn.execute(
                text(
                    "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('Usuario', 'Log_Sistema')"
                )
            ).fetchall()
        }
        user_columns = {
            'Curso': "ALTER TABLE Usuario ADD COLUMN Curso TINYINT UNSIGNED NULL",
            'Division': "ALTER TABLE Usuario ADD COLUMN Division TINYINT UNSIGNED NULL",
            'Motivo_Veto': "ALTER TABLE Usuario ADD COLUMN Motivo_Veto VARCHAR(255) NULL",
            'Veto_Hasta': "ALTER TABLE Usuario ADD COLUMN Veto_Hasta DATETIME NULL",
        }
        for column, statement in user_columns.items():
            if ('usuario', column.lower()) not in existing_columns:
                conn.execute(text(statement))

        table_exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Log_Sistema'"
            )
        ).fetchone()
        if not table_exists:
            raise RuntimeError('No existe Log_Sistema; no se puede preservar el historial de usuarios')
        if ('log_sistema', 'id_usuario') not in existing_columns:
            nullable = conn.execute(
                text(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Log_Sistema' "
                    "AND COLUMN_NAME = 'ID_Usuario'"
                ),
            ).scalar()
            if nullable == 'NO':
                conn.execute(text('ALTER TABLE Log_Sistema MODIFY COLUMN ID_Usuario INT NULL'))


ensure_user_management_columns()


def ensure_book_total_stock_column():
    with engine.begin() as conn:
        has_total_stock = conn.execute(
            text(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Libro' "
                "AND COLUMN_NAME = 'Stock_Total'"
            )
        ).fetchone()
        if has_total_stock:
            return

        conn.execute(text(
            "ALTER TABLE Libro ADD COLUMN Stock_Total INT NOT NULL DEFAULT 0"
        ))
        conn.execute(text("UPDATE Libro SET Stock_Total = Stock"))


ensure_book_total_stock_column()


def ensure_loan_schema():
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS Cuaderno_Diario ("
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
            "CONSTRAINT fk_cuaderno_libro FOREIGN KEY (ID_Libro) REFERENCES Libro(ID_Libro), "
            "CONSTRAINT fk_cuaderno_responsable FOREIGN KEY (ID_Responsable) REFERENCES Usuario(ID_Usuario) ON DELETE SET NULL, "
            "CONSTRAINT fk_cuaderno_retira FOREIGN KEY (ID_Retira) REFERENCES Usuario(ID_Usuario) ON DELETE SET NULL, "
            "CONSTRAINT fk_cuaderno_bibliotecaria FOREIGN KEY (ID_Bibliotecaria) REFERENCES Usuario(ID_Usuario), "
            "CONSTRAINT chk_cuaderno_cantidad CHECK (Cantidad > 0), "
            "CONSTRAINT chk_cuaderno_curso CHECK (Curso BETWEEN 1 AND 6), "
            "CONSTRAINT chk_cuaderno_division CHECK (Division BETWEEN 1 AND 10), "
            "CONSTRAINT chk_cuaderno_estado CHECK (Estado IN ('Activo', 'Devuelto'))"
            ") ENGINE=InnoDB"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS Ficha_Domiciliaria ("
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
            "CONSTRAINT fk_ficha_libro FOREIGN KEY (ID_Libro) REFERENCES Libro(ID_Libro), "
            "CONSTRAINT fk_ficha_responsable FOREIGN KEY (ID_Responsable) REFERENCES Usuario(ID_Usuario) ON DELETE SET NULL, "
            "CONSTRAINT fk_ficha_bibliotecaria FOREIGN KEY (ID_Bibliotecaria) REFERENCES Usuario(ID_Usuario), "
            "CONSTRAINT chk_ficha_cantidad CHECK (Cantidad > 0), "
            "CONSTRAINT chk_ficha_curso CHECK (Curso BETWEEN 1 AND 6), "
            "CONSTRAINT chk_ficha_division CHECK (Division BETWEEN 1 AND 10), "
            "CONSTRAINT chk_ficha_dias CHECK (Dias > 0), "
            "CONSTRAINT chk_ficha_estado CHECK (Estado IN ('Activo', 'Devuelto'))"
            ") ENGINE=InnoDB"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS Schema_Migration ("
            "Migration_Key VARCHAR(100) NOT NULL PRIMARY KEY, "
            "Applied_At DATETIME NOT NULL"
            ") ENGINE=InnoDB"
        ))
        legacy_table_exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Reserva_Ejemplares'"
            )
        ).fetchone()
        stock_release_done = conn.execute(
            text("SELECT 1 FROM Schema_Migration WHERE Migration_Key = 'release_legacy_reservation_stock_v1'")
        ).fetchone()
        if not stock_release_done:
            if legacy_table_exists:
                conn.execute(text(
                    "UPDATE Libro l JOIN ("
                    "SELECT ID_Libro, SUM(COALESCE(Cantidad, 0)) AS Cantidad "
                    "FROM Reserva_Ejemplares GROUP BY ID_Libro"
                    ") r ON r.ID_Libro = l.ID_Libro "
                    "SET l.Stock = COALESCE(l.Stock, 0) + r.Cantidad"
                ))
            conn.execute(
                text("INSERT INTO Schema_Migration (Migration_Key, Applied_At) VALUES "
                     "('release_legacy_reservation_stock_v1', CURRENT_TIMESTAMP)")
            )
        legacy_cleanup_done = conn.execute(
            text("SELECT 1 FROM Schema_Migration WHERE Migration_Key = 'remove_legacy_reservations_v1'")
        ).fetchone()
        if not legacy_cleanup_done:
            if legacy_table_exists:
                conn.execute(text("DELETE FROM Reserva_Ejemplares"))
            conn.execute(
                text("INSERT INTO Schema_Migration (Migration_Key, Applied_At) VALUES "
                     "('remove_legacy_reservations_v1', CURRENT_TIMESTAMP)")
            )


ensure_loan_schema()


class BookIn(BaseModel):
    Titulo: str = Field(..., max_length=100)
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int = Field(0, ge=0)


class BookUpdate(BaseModel):
    Titulo: str | None = None
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int | None = Field(None, ge=0)
    Motivo: str | None = None


class SchoolLoanIn(BaseModel):
    ID_Libro: int = Field(..., gt=0)
    ID_Responsable: int = Field(..., gt=0)
    ID_Retira: int | None = Field(None, gt=0)
    Modalidad: str
    Cantidad: int = Field(..., ge=1)
    Curso: int = Field(..., ge=1, le=6)
    Division: int = Field(..., ge=1, le=10)


class HomeLoanIn(BaseModel):
    ID_Libro: int = Field(..., gt=0)
    ID_Responsable: int = Field(..., gt=0)
    Cantidad: int = Field(..., ge=1)
    Dias: int = Field(30, ge=1)
    Apellido: str = Field(..., min_length=1, max_length=100)
    Nombre: str = Field(..., min_length=1, max_length=100)
    DNI: str = Field(..., min_length=1, max_length=30)
    Telefono: str = Field(..., min_length=1, max_length=40)


class StockReductionIn(BaseModel):
    ID_Libro: int
    Cantidad: int
    Motivo: str


class UserStateUpdate(BaseModel):
    Estado: str = Field(..., max_length=30)
    Motivo: str | None = Field(None, max_length=255)
    Duracion_Dias: int | None = Field(None, ge=1, le=365)


class UserProfileUpdate(BaseModel):
    Curso: int = Field(..., ge=1, le=6)
    Division: int = Field(..., ge=1, le=10)


class LoginIn(BaseModel):
    Gmail: str
    Contraseña: str


class SignupIn(BaseModel):
    Nombre_Completo: str
    Gmail: str
    Contraseña: str


# El rol del usuario se infiere con la misma lógica que usa la interfaz para mostrar
# las vistas y bloquear accesos según si es alumno, profesor o bibliotecario.
def infer_user_type(gmail: str, stored_type: str | None = None) -> str:
    """Inferir tipo de usuario (Alumno/Profesor/Bibliotecario) según el Gmail o el rol almacenado."""
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


# Busca la identidad del usuario en las cabeceras HTTP o en cookies.
# Devuelve el ID y el tipo de usuario para que las rutas protegidas puedan validar acceso.
def get_request_identity(request: Request) -> tuple[int | None, str | None]:
    user_id = request.headers.get('x-user-id') or request.headers.get('X-User-Id')
    user_type = request.headers.get('x-user-type') or request.headers.get('X-User-Type')
    if not user_id:
        user_id = request.cookies.get('session_user_id')
    if not user_type:
        user_type = request.cookies.get('session_user_type')
    if user_id and user_id.isdigit():
        return int(user_id), user_type
    return None, user_type


def ensure_user_not_banned(conn, row):
    if row[3] != 'vetado':
        return

    ban_reason = row[5]
    ban_until = row[6]
    if ban_until and ban_until <= datetime.datetime.utcnow():
        conn.execute(
            text(
                "UPDATE Usuario SET Estado = 'no vetado', Motivo_Veto = NULL, Veto_Hasta = NULL "
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


def get_authenticated_user(
    request: Request,
    allowed_roles: list[str] | None = None,
    require_admin_email: bool = False,
):
    cached_user = getattr(request.state, 'user', None)
    if cached_user:
        actual_type = cached_user['Tipo']
        if allowed_roles and actual_type not in allowed_roles:
            raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')
        if require_admin_email and cached_user['Gmail'].lower() != ADMIN_EMAIL.lower():
            raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')
        return cached_user

    user_id, user_type = get_request_identity(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='No autenticado')

    # Si hay un usuario válido en la base, lo devolvemos junto a su estado
    # para que el middleware o la ruta puedan seguir con la ejecución.
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo, Motivo_Veto, Veto_Hasta, Curso, Division "
                "FROM Usuario WHERE ID_Usuario = :id"
            ),
            {'id': user_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail='Usuario no encontrado')
        ensure_user_not_banned(conn, row)

    # Normaliza el tipo de usuario según el correo y los datos guardados.
    actual_type = infer_user_type(row[2], row[4])
    if not user_type:
        user_type = actual_type
    if user_type.lower() != actual_type.lower():
        raise HTTPException(status_code=403, detail='Rol no autorizado')

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
    }
    request.state.user = user
    return user


# Cada baja de stock queda registrada para mantener un historial claro de los ejemplares
# que se dañaron, perdieron o retiraron del catálogo.
def insert_baja_record(conn, libro_id: int, bibliotecario_id: int, cantidad: int, motivo: str):
    motivo = motivo.strip()
    if motivo not in VALID_BAJA_MOTIVOS:
        raise HTTPException(status_code=400, detail=f'Motivo inválido: {motivo}')
    if cantidad <= 0:
        raise HTTPException(status_code=400, detail='La cantidad de baja debe ser mayor a cero')

    conn.execute(
        text(
            "INSERT INTO Baja_Ejemplares (ID_Libro, ID_Usuario_Bibliotecario, Cantidad, Motivo, Fecha)"
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
    if tipo_evento not in VALID_LOG_TYPES:
        raise HTTPException(status_code=400, detail=f'Tipo de evento inválido: {tipo_evento}')
    conn.execute(
        text(
            "INSERT INTO Log_Sistema (Tipo_Evento, ID_Usuario, ID_Libro, Descripcion, Fecha)"
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
    if request.url.path in PROTECTED_ROUTE_ROLES:
        try:
            get_authenticated_user(
                request,
                allowed_roles=list(PROTECTED_ROUTE_ROLES[request.url.path]),
                require_admin_email=(request.url.path == '/api/books'),
            )
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})
    return await call_next(request)


# Estas rutas exponen datos que la interfaz necesita de forma directa.
# El frontend solicita autores, libros y estados de usuario para renderizar
# los formularios y las tablas sin tener que reconstruir la lógica del backend.
@app.get('/api/authors')
def list_authors():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT ID_Autor, Nombre FROM Autor ORDER BY Nombre"))
        return [{'ID_Autor': row[0], 'Nombre': row[1]} for row in res.fetchall()]


# Estas rutas controlan el catálogo de libros: alta, edición, eliminación y ajustes de stock.
# Están protegidas porque afectan directamente el inventario visible de la biblioteca.
@app.post('/api/books')
@require_role('Bibliotecario', require_admin_email=True)
def add_book(request: Request, book: BookIn):
    with engine.begin() as conn:
        # Se guarda el libro con parámetros SQL para evitar problemas con caracteres especiales.
        stmt = text(
            "INSERT INTO Libro (Titulo, Editorial, ID_Autor, Año_Publicacion, ISBN, Sinopsis, Stock, Stock_Total)"
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
    with engine.connect() as conn:
        r = conn.execute(
            text(
                "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ID_Autor, l.Año_Publicacion, "
                "l.ISBN, l.Sinopsis, l.Stock, l.Stock_Total, a.Nombre "
                "FROM Libro l LEFT JOIN Autor a ON l.ID_Autor = a.ID_Autor "
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
    user = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    with engine.begin() as conn:
        current = conn.execute(
            text(
                "SELECT Titulo, Editorial, ID_Autor, Año_Publicacion, ISBN, Sinopsis, Stock "
                "FROM Libro WHERE ID_Libro = :id FOR UPDATE"
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
                conn.execute(text("UPDATE Libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
                insert_baja_record(conn, book_id, user['ID_Usuario'], reduction, book.Motivo)
                insert_log(conn, 'Stock Reducido', user['ID_Usuario'], book_id, f'Stock reducido: {reduction} ejemplar(es) - Motivo: {book.Motivo}')
                return {'ok': True, 'updated': book_id, 'reduced': reduction}
            updates.append('Stock = :stock')
            params['stock'] = new_stock
            updates.append('Stock_Total = Stock_Total + :stock_delta')
            params['stock_delta'] = new_stock - current_stock

        if updates:
            conn.execute(text("UPDATE Libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
        return {'ok': True, 'updated': book_id}


@app.delete('/api/books/{book_id}')
@require_role('Bibliotecario', require_admin_email=True)
def delete_book(request: Request, book_id: int):
    with engine.begin() as conn:
        existing = conn.execute(
            text('SELECT 1 FROM Libro WHERE ID_Libro = :id FOR UPDATE'),
            {'id': book_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail='Libro no encontrado')

        related_records = conn.execute(
            text(
                "SELECT 1 FROM Cuaderno_Diario WHERE ID_Libro = :id "
                "UNION ALL SELECT 1 FROM Ficha_Domiciliaria WHERE ID_Libro = :id "
                "UNION ALL SELECT 1 FROM Baja_Ejemplares WHERE ID_Libro = :id "
                "UNION ALL SELECT 1 FROM Log_Sistema WHERE ID_Libro = :id LIMIT 1"
            ),
            {'id': book_id},
        ).fetchone()
        if related_records:
            raise HTTPException(
                status_code=409,
                detail='No se puede eliminar el libro porque tiene registros en historiales protegidos',
            )
        conn.execute(text('DELETE FROM Libro WHERE ID_Libro = :id'), {'id': book_id})
    return {'ok': True, 'deleted': book_id}


@app.post('/api/stock-reduction')
@require_role('Bibliotecario', require_admin_email=True)
def stock_reduction(request: Request, data: StockReductionIn):
    user = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    motivo = data.Motivo.strip() if data.Motivo else ''
    if motivo not in VALID_BAJA_MOTIVOS:
        raise HTTPException(status_code=400, detail='Motivo inválido')
    if data.Cantidad <= 0:
        raise HTTPException(status_code=400, detail='Cantidad inválida')

    with engine.begin() as conn:
        book = conn.execute(
            text("SELECT Stock FROM Libro WHERE ID_Libro = :id FOR UPDATE"),
            {'id': data.ID_Libro},
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if book[0] < data.Cantidad:
            raise HTTPException(status_code=400, detail='Stock insuficiente para esta baja')
        conn.execute(
            text(
                "UPDATE Libro SET Stock = Stock - :cantidad, "
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
                "UPDATE Usuario SET Estado = 'no vetado', Motivo_Veto = NULL, Veto_Hasta = NULL "
                "WHERE Estado = 'vetado' AND Veto_Hasta IS NOT NULL AND Veto_Hasta <= UTC_TIMESTAMP()"
            )
        )
        count_stmt = text(
            "SELECT COUNT(*) FROM Usuario WHERE Tipo IN (:tipo0, :tipo1)"
            if len(allowed_roles) == 2 else
            "SELECT COUNT(*) FROM Usuario WHERE Tipo = :tipo"
        )
        count_params = {'tipo0': allowed_roles[0], 'tipo1': allowed_roles[1]} if len(allowed_roles) == 2 else {'tipo': allowed_roles[0]}
        total = conn.execute(count_stmt, count_params).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit

        if len(allowed_roles) == 1:
            stmt = text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Estado, Curso, Division, Motivo_Veto, Veto_Hasta "
                "FROM Usuario WHERE Tipo = :tipo ORDER BY Tipo, Nombre_Completo LIMIT :limit OFFSET :offset"
            )
            rows = conn.execute(stmt, {'tipo': allowed_roles[0], 'limit': limit, 'offset': offset}).fetchall()
        else:
            stmt = text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Estado, Curso, Division, Motivo_Veto, Veto_Hasta "
                "FROM Usuario WHERE Tipo IN (:tipo0, :tipo1) ORDER BY Tipo, Nombre_Completo LIMIT :limit OFFSET :offset"
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
        })
    return {'total': int(total), 'page': page, 'pages': pages, 'users': users}


@app.put('/api/users/{user_id}/state')
@require_role('Bibliotecario')
def update_user_state(request: Request, user_id: int, data: UserStateUpdate):
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
        ban_until = datetime.datetime.utcnow() + datetime.timedelta(days=data.Duracion_Dias)

    with engine.begin() as conn:
        target = conn.execute(
            text('SELECT Tipo FROM Usuario WHERE ID_Usuario = :id'),
            {'id': user_id}
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if target[0] == 'Bibliotecario':
            raise HTTPException(status_code=403, detail='No se puede vetar al bibliotecario')

        result = conn.execute(
            text(
                "UPDATE Usuario SET Estado = :estado, Motivo_Veto = :motivo, Veto_Hasta = :hasta "
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


@app.get('/api/profile')
@require_role('Alumno', 'Profesor')
def get_profile(request: Request):
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
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor'])
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE Usuario SET Curso = :curso, Division = :division WHERE ID_Usuario = :id'),
            {'curso': data.Curso, 'division': data.Division, 'id': user['ID_Usuario']},
        )
    user['Curso'] = data.Curso
    user['Division'] = data.Division
    return {'ok': True, 'Curso': data.Curso, 'Division': data.Division}


@app.delete('/api/users/{user_id}')
@require_role('Bibliotecario')
def delete_graduated_student(request: Request, user_id: int):
    with engine.begin() as conn:
        target = conn.execute(
            text('SELECT Tipo, Curso FROM Usuario WHERE ID_Usuario = :id FOR UPDATE'),
            {'id': user_id},
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if target[0] != 'Alumno' or target[1] != 6:
            raise HTTPException(
                status_code=409,
                detail='Solo se pueden eliminar alumnos de 6.º curso',
            )

        ensure_no_active_loans(conn, user_id)

        conn.execute(
            text('UPDATE Log_Sistema SET ID_Usuario = NULL WHERE ID_Usuario = :id'),
            {'id': user_id},
        )
        try:
            conn.execute(text('DELETE FROM Usuario WHERE ID_Usuario = :id'), {'id': user_id})
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail='No se puede eliminar el alumno porque otros registros dependen de su cuenta',
            ) from exc
    return {'ok': True, 'deleted': user_id}


@app.get('/api/search')
def search(request: Request, title: str = '', page: int = 1, limit: int = 4):
    user_id, _ = get_request_identity(request)
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
            text("SELECT COUNT(*) FROM Libro WHERE Titulo LIKE :q"),
            {'q': q}
        ).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit
        stmt = text(
            "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ISBN, l.Sinopsis, l.Stock, "
            "l.Stock_Total, a.Nombre "
            "FROM Libro l LEFT JOIN Autor a ON l.ID_Autor = a.ID_Autor "
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
    if limit <= 0:
        limit = 50
    with engine.connect() as conn:
        res = conn.execute(
            text(
                "SELECT l.ID, l.Tipo_Evento, l.ID_Usuario, u.Nombre_Completo, l.ID_Libro, lib.Titulo, l.Descripcion, l.Fecha "
                "FROM Log_Sistema l "
                "LEFT JOIN Usuario u ON l.ID_Usuario = u.ID_Usuario "
                "LEFT JOIN Libro lib ON l.ID_Libro = lib.ID_Libro "
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
FROM Cuaderno_Diario c
JOIN Libro l ON l.ID_Libro = c.ID_Libro
LEFT JOIN Autor a ON a.ID_Autor = l.ID_Autor
LEFT JOIN Usuario u ON u.ID_Usuario = c.ID_Responsable
UNION ALL
SELECT 'domiciliario' AS Tipo, f.ID_Ficha AS ID_Prestamo, f.ID_Libro, l.Titulo AS Libro, a.Nombre AS Autor,
       f.ID_Responsable, COALESCE(u.Nombre_Completo, f.Responsable_Nombre) AS Responsable,
       NULL AS ID_Retira, NULL AS Retirado_Por, f.Cantidad, f.Curso, f.Division,
       f.Fecha_Prestamo, f.Fecha_Vencimiento, f.Fecha_Devolucion, f.Estado,
       f.Apellido, f.Nombre AS Nombre_Ficha, f.DNI, f.Telefono, f.Dias
FROM Ficha_Domiciliaria f
JOIN Libro l ON l.ID_Libro = f.ID_Libro
LEFT JOIN Autor a ON a.ID_Autor = l.ID_Autor
LEFT JOIN Usuario u ON u.ID_Usuario = f.ID_Responsable
"""


def loan_filters(tipo, estado, libro_id, persona, curso, division):
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
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Curso, Division "
                "FROM Usuario WHERE Tipo IN ('Alumno', 'Profesor') ORDER BY Tipo, Nombre_Completo"
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
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor'])
    filters, params = loan_filters(tipo, estado, None, '', None, None)
    with engine.connect() as conn:
        return paginated_loans(conn, page, limit, filters, params, user['ID_Usuario'])


@app.post('/api/loans/school')
@require_role('Bibliotecario', require_admin_email=True)
def create_school_loan(request: Request, data: SchoolLoanIn):
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
                "SELECT ID_Usuario, Nombre_Completo, Tipo, Estado, Curso, Division "
                "FROM Usuario WHERE ID_Usuario = :id FOR UPDATE"
            ),
            {'id': data.ID_Responsable},
        ).fetchone()
        if not responsible:
            raise HTTPException(status_code=404, detail='Cuenta responsable no encontrada')
        expected_role = 'Alumno' if modalidad == 'Alumno' else 'Profesor'
        if responsible[2] != expected_role:
            raise HTTPException(status_code=400, detail=f'La cuenta responsable debe ser de tipo {expected_role}')
        if responsible[3] == 'vetado':
            raise HTTPException(status_code=403, detail='La cuenta responsable está vetada')
        if responsible[4] is None or responsible[5] is None:
            raise HTTPException(status_code=409, detail='La cuenta responsable debe completar curso y división')

        retira = None
        if data.ID_Retira is not None:
            retira = conn.execute(
                text("SELECT ID_Usuario, Nombre_Completo, Tipo FROM Usuario WHERE ID_Usuario = :id"),
                {'id': data.ID_Retira},
            ).fetchone()
            if not retira:
                raise HTTPException(status_code=404, detail='Cuenta del alumno que retira no encontrada')
            if retira[2] != 'Alumno':
                raise HTTPException(status_code=400, detail='Solo un alumno puede retirar por indicación docente')

        active_school = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM Cuaderno_Diario "
                "WHERE ID_Responsable = :id AND Estado = 'Activo'"
            ),
            {'id': data.ID_Responsable},
        ).scalar() or 0
        active_home = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM Ficha_Domiciliaria "
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
            text('SELECT Stock FROM Libro WHERE ID_Libro = :id FOR UPDATE'),
            {'id': data.ID_Libro},
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if int(book[0] or 0) < data.Cantidad:
            raise HTTPException(status_code=409, detail='Stock insuficiente')
        conn.execute(
            text('UPDATE Libro SET Stock = Stock - :cantidad WHERE ID_Libro = :id AND Stock >= :cantidad'),
            {'cantidad': data.Cantidad, 'id': data.ID_Libro},
        )
        result = conn.execute(
            text(
                "INSERT INTO Cuaderno_Diario "
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
                "SELECT ID_Usuario, Nombre_Completo, Tipo, Estado, Curso, Division "
                "FROM Usuario WHERE ID_Usuario = :id FOR UPDATE"
            ),
            {'id': data.ID_Responsable},
        ).fetchone()
        if not responsible:
            raise HTTPException(status_code=404, detail='Cuenta responsable no encontrada')
        if responsible[2] != 'Profesor':
            raise HTTPException(status_code=400, detail='El préstamo domiciliario solo puede asignarse a un profesor')
        if responsible[3] == 'vetado':
            raise HTTPException(status_code=403, detail='La cuenta responsable está vetada')
        if responsible[4] is None or responsible[5] is None:
            raise HTTPException(status_code=409, detail='El profesor debe completar curso y división en su perfil')

        active_school = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM Cuaderno_Diario "
                "WHERE ID_Responsable = :id AND Estado = 'Activo'"
            ),
            {'id': data.ID_Responsable},
        ).scalar() or 0
        active_home = conn.execute(
            text(
                "SELECT COALESCE(SUM(Cantidad), 0) FROM Ficha_Domiciliaria "
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
            text('SELECT Stock FROM Libro WHERE ID_Libro = :id FOR UPDATE'),
            {'id': data.ID_Libro},
        ).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if int(book[0] or 0) < data.Cantidad:
            raise HTTPException(status_code=409, detail='Stock insuficiente')
        conn.execute(
            text('UPDATE Libro SET Stock = Stock - :cantidad WHERE ID_Libro = :id AND Stock >= :cantidad'),
            {'cantidad': data.Cantidad, 'id': data.ID_Libro},
        )
        result = conn.execute(
            text(
                "INSERT INTO Ficha_Domiciliaria "
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
    if tipo == 'escolar':
        table, id_column = 'Cuaderno_Diario', 'ID_Cuaderno'
    elif tipo == 'domiciliario':
        table, id_column = 'Ficha_Domiciliaria', 'ID_Ficha'
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
            text('UPDATE Libro SET Stock = Stock + :cantidad WHERE ID_Libro = :id'),
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
    page, limit = normalize_pagination(page, limit)
    with engine.connect() as conn:
        total = conn.execute(text('SELECT COUNT(*) FROM Baja_Ejemplares')).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit
        res = conn.execute(
            text(
                "SELECT b.ID_Baja, b.ID_Libro, lib.Titulo, b.ID_Usuario_Bibliotecario, u.Nombre_Completo, b.Cantidad, b.Motivo, b.Fecha "
                "FROM Baja_Ejemplares b "
                "LEFT JOIN Usuario u ON b.ID_Usuario_Bibliotecario = u.ID_Usuario "
                "LEFT JOIN Libro lib ON b.ID_Libro = lib.ID_Libro "
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
    raise HTTPException(status_code=403, detail='El historial de bajas está protegido y no se puede vaciar')


@app.post('/api/login')
def login(data: LoginIn):
    """Iniciar sesión con Gmail y Contraseña"""
    with engine.begin() as conn:
        r = conn.execute(
            text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo, Motivo_Veto, Veto_Hasta, Curso, Division "
                "FROM Usuario WHERE Gmail = :g AND Contraseña = :p"
            ),
            {'g': data.Gmail, 'p': data.Contraseña},
        ).fetchone()
        if not r:
            raise HTTPException(status_code=401, detail='Credenciales inválidas')
        ensure_user_not_banned(conn, r)
        state = 'no vetado' if r[3] == 'vetado' and r[6] else r[3]
        gmail = r[2]
        tipo = infer_user_type(gmail, r[4])
        return {
            'ID_Usuario': r[0],
            'Nombre_Completo': r[1],
            'Gmail': r[2],
            'Estado': state,
            'Tipo': tipo,
            'Curso': r[7],
            'Division': r[8],
        }


@app.post('/api/signup')
def signup(data: SignupIn):
    """Crear nueva cuenta de usuario. Detecta automáticamente el tipo (Alumno/Profesor) según el Gmail."""
    tipo = infer_user_type(data.Gmail)
    with engine.begin() as conn:
        # Verificar si el Gmail ya existe
        existing = conn.execute(text("SELECT 1 FROM Usuario WHERE Gmail = :g"), {'g': data.Gmail}).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail='El correo ya está registrado')
        # Insertar nuevo usuario
        stmt = text(
            "INSERT INTO Usuario (Nombre_Completo, Gmail, Contraseña, Estado, Tipo)"
            " VALUES (:nombre, :gmail, :contraseña, 'no vetado', :tipo)"
        )
        try:
            res = conn.execute(stmt, {'nombre': data.Nombre_Completo, 'gmail': data.Gmail, 'contraseña': data.Contraseña, 'tipo': tipo})
            new_id = res.lastrowid
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {'ok': True, 'ID_Usuario': new_id, 'Nombre_Completo': data.Nombre_Completo, 'Gmail': data.Gmail, 'Tipo': tipo}


# Se sirven los archivos estáticos que componen la interfaz web de la biblioteca.
static_dir = Path(__file__).resolve().parent.parent / 'static'
if static_dir.exists():
    app.mount('/static', StaticFiles(directory=str(static_dir)), name='static_files')
    # Sirve los archivos estáticos del frontend y la página principal.
    # Si la carpeta no existe, la API seguirá funcionando pero no habrá UI web disponible.
    app.mount('/', StaticFiles(directory=str(static_dir), html=True), name='static')
else:
    # Si la carpeta está ausente, la API sigue respondiendo pero la interfaz web no se verá.
    pass
