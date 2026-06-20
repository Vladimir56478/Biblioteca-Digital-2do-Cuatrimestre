import datetime
import random
import string
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
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


class BookIn(BaseModel):
    Titulo: str = Field(..., max_length=100)
    Editorial: str | None = None
    ID_Autor: int | None = None
    Año_Publicacion: int | None = None
    ISBN: str | None = None
    Sinopsis: str | None = None
    Stock: int = 0


class ReserveIn(BaseModel):
    ID_Libro: int
    ID_Usuario: int
    Cantidad: int = 1


def generate_res_code(conn) -> str:
    # RES-XXXX where X is uppercase letter or digit
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


def infer_user_type(gmail: str) -> str:
    """Infer user type (Alumno/Profesor) from email format"""
    return 'Alumno' if '@alu.' in gmail else 'Profesor'


@app.get('/api/authors')
def list_authors():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT ID_Autor, Nombre FROM Autor ORDER BY Nombre"))
        return [{'ID_Autor': row[0], 'Nombre': row[1]} for row in res.fetchall()]


@app.post('/api/books')
def add_book(book: BookIn):
    with engine.begin() as conn:
        # Insert safely using parameters
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
def reserve(data: ReserveIn):
    now = datetime.datetime.utcnow()
    exp = now + datetime.timedelta(days=2)
    with engine.begin() as conn:
        # Check user state
        u = conn.execute(text("SELECT Estado FROM Usuario WHERE ID_Usuario = :id"), {'id': data.ID_Usuario}).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail='Usuario no encontrado')
        if u[0] == 'vetado':
            raise HTTPException(status_code=403, detail='Usuario vetado')

        # Check stock
        book = conn.execute(text("SELECT Stock FROM Libro WHERE ID_Libro = :id"), {'id': data.ID_Libro}).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail='Libro no encontrado')
        if book[0] < data.Cantidad:
            raise HTTPException(status_code=400, detail='Stock insuficiente')

        # Generate unique code
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

        # Optionally decrement stock
        conn.execute(text("UPDATE Libro SET Stock = Stock - :c WHERE ID_Libro = :id"), {'c': data.Cantidad, 'id': data.ID_Libro})

        return {'ok': True, 'Codigo_reserva': code}


@app.post('/api/login')
def login(data: LoginIn):
    """Login user with Gmail and Contraseña"""
    with engine.connect() as conn:
        r = conn.execute(text("SELECT ID_Usuario, Nombre_Completo, Gmail, Estado FROM Usuario WHERE Gmail = :g AND Contraseña = :p"), {'g': data.Gmail, 'p': data.Contraseña}).fetchone()
        if not r:
            raise HTTPException(status_code=401, detail='Credenciales inválidas')
        gmail = r[2]
        tipo = infer_user_type(gmail)
        return {'ID_Usuario': r[0], 'Nombre_Completo': r[1], 'Gmail': r[2], 'Estado': r[3], 'Tipo': tipo}


@app.post('/api/signup')
def signup(data: SignupIn):
    """Create new user account. Automatically detects user type (Alumno/Profesor) from Gmail"""
    tipo = infer_user_type(data.Gmail)
    with engine.begin() as conn:
        # Check if Gmail already exists
        existing = conn.execute(text("SELECT 1 FROM Usuario WHERE Gmail = :g"), {'g': data.Gmail}).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail='El correo ya está registrado')
        # Insert new user
        stmt = text(
            "INSERT INTO Usuario (Nombre_Completo, Gmail, Contraseña, Estado)"
            " VALUES (:nombre, :gmail, :contraseña, 'no vetado')"
        )
        try:
            res = conn.execute(stmt, {'nombre': data.Nombre_Completo, 'gmail': data.Gmail, 'contraseña': data.Contraseña})
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
