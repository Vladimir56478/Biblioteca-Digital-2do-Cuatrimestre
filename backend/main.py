"""API principal de Lorekeeper.

Este módulo concentra la lógica del backend: define los endpoints para
autenticación, gestión de libros, reservas y el montaje de archivos estáticos.
"""

import datetime
import inspect
import random
import string
from functools import wraps
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.db import get_engine

app = FastAPI(title='Lorekeeper API')


def current_timestamp() -> str:
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def format_datetime(value) -> str | None:
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else None

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
# para todas las operaciones de la biblioteca: usuarios, libros, reservas y reportes.

# Aquí se definen los roles base y los usuarios iniciales que van a poder entrar al sistema.
ADMIN_EMAIL = 'Bibliotecario.fanoba@tecnica29de6.edu.ar'
PROTECTED_ROUTE_ROLES = {
    '/api/books': {'Bibliotecario'},
    '/api/reserve': {'Alumno', 'Profesor', 'Bibliotecario'},
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
# Esto permite que el backend se ejecute en bases de datos existentes
# sin fallar por columnas nuevas o tablas que no estaban definidas antes.
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

VALID_LOG_TYPES = {'Reserva Creada', 'Préstamo Activo', 'Préstamo Devuelto', 'Stock Reducido'}


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


class BookIn(BaseModel):
    Titulo: str = Field(..., max_length=100)
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int = 0


class BookUpdate(BaseModel):
    Titulo: str | None = None
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int | None = None
    Motivo: str | None = None


class ReserveIn(BaseModel):
    ID_Libro: int
    ID_Usuario: int
    Cantidad: int = 1


class StockReductionIn(BaseModel):
    ID_Libro: int
    Cantidad: int
    Motivo: str


class UserStateUpdate(BaseModel):
    Estado: str = Field(..., max_length=30)


def generate_res_code(conn) -> str:
    # Genera códigos de reserva en formato RES-XXXX donde X es letra mayúscula o dígito
    attempts = 0
    while True:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        code = f'RES-{suffix}'
        r = conn.execute(text("SELECT 1 FROM Reserva_Ejemplares WHERE Codigo_reserva = :c"), {'c': code}).fetchone()
        if not r:
            return code
        attempts += 1
        if attempts > 10:
            raise RuntimeError('Could not generate unique reservation code')


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
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo FROM Usuario WHERE ID_Usuario = :id"),
            {'id': user_id},
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail='Usuario no encontrado')

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


def get_user_reservation_limit(user_type: str) -> int:
    if user_type == 'Profesor':
        return 25
    if user_type == 'Bibliotecario':
        return 30
    return 3


def get_user_reserved_count(conn, user_id: int) -> int:
    result = conn.execute(
        text('SELECT COALESCE(SUM(Cantidad), 0) FROM Reserva_Ejemplares WHERE ID_Usuario = :id'),
        {'id': user_id}
    ).scalar()
    return int(result or 0)


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
            "INSERT INTO Libro (Titulo, Editorial, ID_Autor, Año_Publicacion, ISBN, Sinopsis, Stock)"
            " VALUES (:titulo, :editorial, :id_autor, :anio, :isbn, :sinopsis, :stock)"
        )
        params = {
            'titulo': book.Titulo,
            'editorial': book.Editorial,
            'id_autor': book.ID_Autor,
            'anio': book.Año_Publicacion,
            'isbn': book.ISBN,
            'sinopsis': book.Sinopsis,
            'stock': int(book.Stock or 0),
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
                "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ID_Autor, l.Año_Publicacion, l.ISBN, l.Sinopsis, l.Stock, a.Nombre "
                "FROM Libro l LEFT JOIN Autor a ON l.ID_Autor = a.ID_Autor WHERE l.ID_Libro = :id"
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
            'Autor': r[8],
        }


@app.put('/api/books/{book_id}')
@require_role('Bibliotecario', require_admin_email=True)
def update_book(request: Request, book_id: int, book: BookUpdate):
    user = get_authenticated_user(request, allowed_roles=['Bibliotecario'], require_admin_email=True)
    with engine.begin() as conn:
        current = conn.execute(text("SELECT Titulo, Editorial, ID_Autor, Año_Publicacion, ISBN, Sinopsis, Stock FROM Libro WHERE ID_Libro = :id"), {'id': book_id}).fetchone()
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
                conn.execute(text("UPDATE Libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
                insert_baja_record(conn, book_id, user['ID_Usuario'], reduction, book.Motivo)
                insert_log(conn, 'Stock Reducido', user['ID_Usuario'], book_id, f'Stock reducido: {reduction} ejemplar(es) - Motivo: {book.Motivo}')
                return {'ok': True, 'updated': book_id, 'reduced': reduction}
            updates.append('Stock = :stock')
            params['stock'] = new_stock

        if updates:
            conn.execute(text("UPDATE Libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
        return {'ok': True, 'updated': book_id}


@app.delete('/api/books/{book_id}')
@require_role('Bibliotecario', require_admin_email=True)
def delete_book(request: Request, book_id: int):
    with engine.begin() as conn:
        existing = conn.execute(text('SELECT 1 FROM Libro WHERE ID_Libro = :id'), {'id': book_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail='Libro no encontrado')

        conn.execute(text('DELETE FROM Reserva_Ejemplares WHERE ID_Libro = :id'), {'id': book_id})
        conn.execute(text('DELETE FROM Baja_Ejemplares WHERE ID_Libro = :id'), {'id': book_id})
        conn.execute(text('DELETE FROM Log_Sistema WHERE ID_Libro = :id'), {'id': book_id})
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
        book = conn.execute(text("SELECT Stock FROM Libro WHERE ID_Libro = :id"), {'id': data.ID_Libro}).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if book[0] < data.Cantidad:
            raise HTTPException(status_code=400, detail='Stock insuficiente para esta baja')
        conn.execute(text("UPDATE Libro SET Stock = Stock - :cantidad WHERE ID_Libro = :id"), {'cantidad': data.Cantidad, 'id': data.ID_Libro})
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

    with engine.connect() as conn:
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
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Estado "
                "FROM Usuario WHERE Tipo = :tipo ORDER BY Tipo, Nombre_Completo LIMIT :limit OFFSET :offset"
            )
            rows = conn.execute(stmt, {'tipo': allowed_roles[0], 'limit': limit, 'offset': offset}).fetchall()
        else:
            stmt = text(
                "SELECT ID_Usuario, Nombre_Completo, Gmail, Tipo, Estado "
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
        })
    return {'total': int(total), 'page': page, 'pages': pages, 'users': users}


@app.put('/api/users/{user_id}/state')
@require_role('Bibliotecario')
def update_user_state(request: Request, user_id: int, data: UserStateUpdate):
    new_state = data.Estado.strip().lower()
    if new_state not in ['vetado', 'no vetado']:
        raise HTTPException(status_code=400, detail='Estado debe ser "vetado" o "no vetado"')

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
            text("UPDATE Usuario SET Estado = :estado WHERE ID_Usuario = :id"),
            {'estado': new_state, 'id': user_id}
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')

    return {'ok': True, 'ID_Usuario': user_id, 'Estado': new_state}


@app.get('/api/search')
def search(title: str = '', page: int = 1, limit: int = 4):
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
            "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ISBN, l.Sinopsis, l.Stock, a.Nombre "
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
                'Autor': r[6],
            })
        return {'total': int(total), 'page': page, 'pages': pages, 'books': rows}


# El flujo de reservas valida que el usuario tenga permisos, no esté vetado y no supere
# el límite de ejemplares que corresponde a su tipo de cuenta.
@app.post('/api/reserve')
@require_role('Alumno', 'Profesor', 'Bibliotecario')
def reserve(request: Request, data: ReserveIn):
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor', 'Bibliotecario'])
    if user['ID_Usuario'] != data.ID_Usuario:
        raise HTTPException(status_code=403, detail='La reserva debe pertenecer al usuario autenticado')

    if data.Cantidad <= 0:
        raise HTTPException(status_code=400, detail='Cantidad inválida')

    now = datetime.datetime.utcnow()
    exp = now + datetime.timedelta(days=2)
    with engine.begin() as conn:
        # Se revisa si el usuario está habilitado para reservar.
        u = conn.execute(text("SELECT Estado FROM Usuario WHERE ID_Usuario = :id"), {'id': data.ID_Usuario}).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if u[0] == 'vetado':
            raise HTTPException(status_code=403, detail='Usuario vetado')

        # Se valida cuántos ejemplares puede reservar según el rol del usuario.
        reserved_count = get_user_reserved_count(conn, data.ID_Usuario)
        limit = get_user_reservation_limit(user['Tipo'])
        if reserved_count + data.Cantidad > limit:
            raise HTTPException(
                status_code=400,
                detail=f'Has alcanzado el límite de reserva. {user["Tipo"]} puede reservar hasta {limit} ejemplar(es) en total. Actualmente tienes {reserved_count} reservados.'
            )

        # Se comprueba que haya stock suficiente antes de crear la reserva.
        book = conn.execute(text("SELECT Stock FROM Libro WHERE ID_Libro = :id"), {'id': data.ID_Libro}).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if book[0] < data.Cantidad:
            raise HTTPException(status_code=400, detail='Stock insuficiente')

        # Se genera un código de reserva único para identificar la operación en el historial.
        code = generate_res_code(conn)

        insert_stmt = text(
            "INSERT INTO Reserva_Ejemplares (Codigo_reserva, ID_Libro, ID_Usuario, Cantidad, Fecha_Reserva, Fecha_Expiracion_Reserva)"
            " VALUES (:code, :id_libro, :id_usuario, :cantidad, :f_res, :f_exp)"
        )
        params = {
            'code': code,
            'id_libro': data.ID_Libro,
            'id_usuario': data.ID_Usuario,
            'cantidad': data.Cantidad,
            'f_res': now.strftime('%Y-%m-%d %H:%M:%S'),
            'f_exp': exp.strftime('%Y-%m-%d %H:%M:%S'),
        }
        conn.execute(insert_stmt, params)

        # Al confirmar la reserva, se descuenta el stock del libro para reflejar la disponibilidad real.
        conn.execute(text("UPDATE Libro SET Stock = Stock - :c WHERE ID_Libro = :id"), {'c': data.Cantidad, 'id': data.ID_Libro})
        insert_log(conn, 'Reserva Creada', data.ID_Usuario, data.ID_Libro, f'Reserva {code} de {data.Cantidad} ejemplar(es)')
        insert_log(conn, 'Stock Reducido', data.ID_Usuario, data.ID_Libro, f'Stock reducido por reserva {code}')

        return {'ok': True, 'Codigo_reserva': code}


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


@app.get('/api/history/reservas')
@require_role('Bibliotecario')
def get_history_reservas(request: Request, page: int = 1, limit: int = 20):
    page, limit = normalize_pagination(page, limit)
    with engine.connect() as conn:
        total = conn.execute(text('SELECT COUNT(*) FROM Reserva_Ejemplares')).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit
        res = conn.execute(
            text(
                "SELECT r.ID_Reserva, r.Codigo_reserva, r.ID_Libro, lib.Titulo, r.ID_Usuario, u.Nombre_Completo, r.Cantidad, r.Fecha_Reserva, r.Fecha_Expiracion_Reserva "
                "FROM Reserva_Ejemplares r "
                "LEFT JOIN Usuario u ON r.ID_Usuario = u.ID_Usuario "
                "LEFT JOIN Libro lib ON r.ID_Libro = lib.ID_Libro "
                "ORDER BY r.ID_Reserva DESC LIMIT :limit OFFSET :offset"
            ),
            {'limit': limit, 'offset': offset}
        )
        records = []
        for row in res.fetchall():
            records.append({
                'ID_Reserva': row[0],
                'Codigo_reserva': row[1],
                'ID_Libro': row[2],
                'Libro': row[3],
                'ID_Usuario': row[4],
                'Usuario': row[5],
                'Cantidad': row[6],
                'Fecha_Reserva': format_datetime(row[7]),
                'Fecha_Expiracion_Reserva': format_datetime(row[8]),
            })
        return {'total': int(total), 'page': page, 'pages': pages, 'reservas': records}


@app.get('/api/history/devoluciones-pendientes')
@require_role('Bibliotecario')
def get_history_devoluciones_pendientes(request: Request, page: int = 1, limit: int = 20):
    page, limit = normalize_pagination(page, limit)
    with engine.connect() as conn:
        total = conn.execute(
            text(
                "SELECT COUNT(*) FROM Reserva_Ejemplares r "
                "LEFT JOIN Usuario u ON r.ID_Usuario = u.ID_Usuario "
                "WHERE r.Fecha_Expiracion_Reserva >= NOW()"
            )
        ).scalar() or 0
        pages = max(1, (int(total) + limit - 1) // limit)
        offset = (page - 1) * limit
        res = conn.execute(
            text(
                "SELECT r.ID_Reserva, r.Codigo_reserva, lib.Titulo, u.Nombre_Completo, u.Tipo, r.Cantidad, r.Fecha_Expiracion_Reserva "
                "FROM Reserva_Ejemplares r "
                "LEFT JOIN Usuario u ON r.ID_Usuario = u.ID_Usuario "
                "LEFT JOIN Libro lib ON r.ID_Libro = lib.ID_Libro "
                "WHERE r.Fecha_Expiracion_Reserva >= NOW() "
                "ORDER BY r.Fecha_Expiracion_Reserva ASC, u.Nombre_Completo ASC, r.ID_Reserva DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {'limit': limit, 'offset': offset}
        )
        records = []
        for row in res.fetchall():
            records.append({
                'ID_Reserva': row[0],
                'Codigo_reserva': row[1],
                'Libro': row[2],
                'Profesor': row[3] or 'Sin asignar',
                'Tipo_Usuario': row[4] or 'Sin tipo',
                'Cantidad': row[5],
                'Fecha_Limite': format_datetime(row[6]),
                'Estado': 'Pendiente',
            })
        return {'total': int(total), 'page': page, 'pages': pages, 'devoluciones': records}


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


@app.delete('/api/history/reservas')
@require_role('Bibliotecario')
def delete_history_reservas(request: Request):
    with engine.begin() as conn:
        # Antes de borrar el historial de reservas, se devuelve el stock reservado al catálogo.
        reservas = conn.execute(text('SELECT ID_Libro, SUM(Cantidad) FROM Reserva_Ejemplares GROUP BY ID_Libro')).fetchall()
        for libro_id, cantidad in reservas:
            conn.execute(text('UPDATE Libro SET Stock = Stock + :cantidad WHERE ID_Libro = :id'), {'cantidad': cantidad, 'id': libro_id})
        conn.execute(text('DELETE FROM Reserva_Ejemplares'))
    return {'ok': True, 'deleted': 'reservas'}


@app.delete('/api/history/bajas')
@require_role('Bibliotecario')
def delete_history_bajas(request: Request):
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM Baja_Ejemplares'))
    return {'ok': True, 'deleted': 'bajas'}


@app.post('/api/login')
def login(data: LoginIn):
    """Iniciar sesión con Gmail y Contraseña"""
    with engine.connect() as conn:
        r = conn.execute(
            text("SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo FROM Usuario WHERE Gmail = :g AND Contraseña = :p"),
            {'g': data.Gmail, 'p': data.Contraseña},
        ).fetchone()
        if not r:
            raise HTTPException(status_code=401, detail='Credenciales inválidas')
        gmail = r[2]
        tipo = infer_user_type(gmail, r[4])
        return {'ID_Usuario': r[0], 'Nombre_Completo': r[1], 'Gmail': r[2], 'Estado': r[3], 'Tipo': tipo}


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
