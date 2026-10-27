# Lorekeeper - Biblioteca

Aplicación de biblioteca con backend FastAPI, MySQL y una interfaz web interactiva
que consulta y actualiza los datos mediante la API. Gestiona el catálogo,
perfiles, préstamos escolares (Cuaderno Diario), préstamos domiciliarios
(Ficha Domiciliaria) y bajas de inventario.

## Requisitos

- Python 3.10 o posterior
- MySQL 8 con InnoDB y una base local existente con las tablas `Usuario`,
  `Libro` y `Autor`

## Instalación y configuración

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configura `backend/.env` con la conexión local de la biblioteca:

```ini
MYSQL_ADDON_HOST=127.0.0.1
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_USER=root
MYSQL_ADDON_PASSWORD=tu_clave_local
MYSQL_ADDON_DB=biblioteca_digital
```

También se admite `MYSQL_ADDON_URI`, `MYSQL_ADDON_URL` o `DATABASE_URL`; si se
usa una URI, comprueba que apunte a la base local prevista antes de iniciar la
aplicación. No se crea una base separada automáticamente.

## Inicio

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Abre <http://localhost:8000/>.

En cada inicio el backend aplica cambios idempotentes: agrega `Usuario.Curso` y
`Usuario.Division` si faltan, crea `Cuaderno_Diario`, `Ficha_Domiciliaria` y sus
índices/relaciones, y registra la migración aplicada en `Schema_Migration`.
La migración `remove_legacy_reservations_v1` vacía una sola vez los registros de
prueba de `Reserva_Ejemplares` y devuelve su cantidad a `Libro.Stock` disponible
sin tocar `Stock_Total`. No elimina esa tabla ni borra usuarios, libros, autores,
logs u otras filas. Haz un respaldo de la base antes de desplegar cambios de
esquema.

## Uso y reglas

- La Bibliotecaria crea préstamos desde **Préstamos** eligiendo un libro real del
  catálogo y una cuenta responsable. Solo ella puede consultar la lista global
  y registrar devoluciones.
- El Cuaderno Diario vence la fecha local de su alta. Un alumno puede tener un
  solo ejemplar escolar activo en total. Un docente puede tener hasta 45
  ejemplares activos sumando ambos módulos. En préstamos mediados por un
  alumno, el responsable continúa siendo el profesor.
- La Ficha Domiciliaria solo puede asignarse a una cuenta Profesor. El título y
  autor proceden del catálogo; se guardan los datos de ficha, los días
  corridos (30 por defecto) y la fecha límite calculada.
- Ambos préstamos descuentan únicamente `Libro.Stock`; `Libro.Stock_Total`
  conserva el inventario total. Los registros vencidos siguen activos hasta que
  la Bibliotecaria registra la devolución total.
- Alumno y Profesor solo ven sus propios préstamos activos e historial. Un
  alumno que retira por indicación de un profesor no se convierte en responsable.
- Al primer ingreso, Alumno y Profesor deben guardar su curso (1–6) y división
  (1–10) desde Inicio antes de usar el catálogo. Luego pueden actualizar esos
  datos desde el mismo lugar. Perfiles de Bibliotecaria permite consultarlos,
  pero no editarlos.
- Las bajas de stock y los préstamos/devoluciones se registran en el historial.
  Los libros con movimientos o historial de préstamos no se pueden eliminar.
  Los préstamos activos bloquean la eliminación de un alumno egresado; las
  filas históricas de préstamos se conservan.
- No existe alta de préstamo mediante el antiguo endpoint de reservas.

Las fechas de préstamo/vencimiento/devolución se almacenan como `DATE` y se
presentan como `dd/mm/aaaa` en las vistas de préstamos.
