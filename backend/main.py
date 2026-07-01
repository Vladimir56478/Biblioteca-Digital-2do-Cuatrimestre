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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = get_engine()

# Datos base para inicializar usuarios y permisos en la base al arrancar.
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


# Inicialización de esquema: garantizan que existan columnas y tablas necesarias
# cuando el servicio se levanta por primera vez.
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


ensure_user_role_column()


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


# Helpers de usuario y autorización
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


# Funciones de ayuda para extraer identidad de la petición
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
    if not user_id or not user_type:
        raise HTTPException(status_code=401, detail='No autenticado')

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT ID_Usuario, Nombre_Completo, Gmail, Estado, Tipo FROM Usuario WHERE ID_Usuario = :id"),
            {'id': user_id},
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail='Usuario no encontrado')

    actual_type = infer_user_type(row[2], row[4])
    if user_type.lower() != actual_type.lower():
        raise HTTPException(status_code=403, detail='Rol no autorizado')

    if allowed_roles and actual_type not in allowed_roles:
        raise HTTPException(status_code=403, detail='No tiene permisos para esta acción')

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


# Registro de bajas técnicas de ejemplares
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
            'fecha': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        }
    )


# Decorador para exigir roles y permisos en rutas
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


@app.get('/api/authors')
def list_authors():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT ID_Autor, Nombre FROM Autor ORDER BY Nombre"))
        return [{'ID_Autor': row[0], 'Nombre': row[1]} for row in res.fetchall()]


@app.post('/api/books')
@require_role('Bibliotecario', require_admin_email=True)
def add_book(request: Request, book: BookIn):
    with engine.begin() as conn:
        # Insertar de forma segura usando parámetros
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
                return {'ok': True, 'updated': book_id, 'reduced': reduction}
            updates.append('Stock = :stock')
            params['stock'] = new_stock

        if updates:
            conn.execute(text("UPDATE Libro SET " + ', '.join(updates) + " WHERE ID_Libro = :id"), params)
        return {'ok': True, 'updated': book_id}


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
        return {'ok': True, 'ID_Libro': data.ID_Libro, 'Cantidad': data.Cantidad}


@app.get('/api/search')
def search(title: str = ''):
    q = f"%{title.strip()}%"
    with engine.connect() as conn:
        stmt = text(
            "SELECT l.ID_Libro, l.Titulo, l.Editorial, l.ISBN, l.Sinopsis, l.Stock, a.Nombre "
            "FROM Libro l LEFT JOIN Autor a ON l.ID_Autor = a.ID_Autor "
            "WHERE l.Titulo LIKE :q ORDER BY l.Titulo"
        )
        res = conn.execute(stmt, {'q': q})
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
        return rows


@app.post('/api/reserve')
@require_role('Alumno', 'Profesor', 'Bibliotecario')
def reserve(request: Request, data: ReserveIn):
    user = get_authenticated_user(request, allowed_roles=['Alumno', 'Profesor', 'Bibliotecario'])
    if user['ID_Usuario'] != data.ID_Usuario:
        raise HTTPException(status_code=403, detail='La reserva debe pertenecer al usuario autenticado')

    now = datetime.datetime.utcnow()
    exp = now + datetime.timedelta(days=2)
    with engine.begin() as conn:
        # Verificar el estado del usuario
        u = conn.execute(text("SELECT Estado FROM Usuario WHERE ID_Usuario = :id"), {'id': data.ID_Usuario}).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if u[0] == 'vetado':
            raise HTTPException(status_code=403, detail='Usuario vetado')

        # Verificar stock disponible
        book = conn.execute(text("SELECT Stock FROM Libro WHERE ID_Libro = :id"), {'id': data.ID_Libro}).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if book[0] < data.Cantidad:
            raise HTTPException(status_code=400, detail='Stock insuficiente')

        # Generar código de reserva único
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

        # Reducir stock del libro reservado
        conn.execute(text("UPDATE Libro SET Stock = Stock - :c WHERE ID_Libro = :id"), {'c': data.Cantidad, 'id': data.ID_Libro})

        return {'ok': True, 'Codigo_reserva': code}


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


# Serve static files (robust path resolution)
static_dir = Path(__file__).resolve().parent.parent / 'static'
if static_dir.exists():
    app.mount('/static', StaticFiles(directory=str(static_dir)), name='static_files')
    # Serve index at root
    app.mount('/', StaticFiles(directory=str(static_dir), html=True), name='static')
else:
    # If static folder missing, root will still respond with API only
    pass
