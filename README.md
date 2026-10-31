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

Configura `backend/.env` con la conexión a MySQL de esta computadora. MySQL debe
escuchar solo en `127.0.0.1`; no se debe exponer su puerto a la red:

```ini
MYSQL_ADDON_HOST=127.0.0.1
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_USER=root
MYSQL_ADDON_PASSWORD=tu_clave_local
MYSQL_ADDON_DB=biblioteca_digital
```

También se admiten `MYSQL_ADDON_URI`, `MYSQL_ADDON_URL` y `DATABASE_URL`, pero
Lorekeeper rechaza conexiones MySQL cuyo host no sea local. No se crea una base
separada automáticamente ni se necesita Internet para usar la aplicación una
vez instaladas sus dependencias.

## Inicio local y acceso por LAN

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

En la computadora anfitriona abre <http://localhost:8000/>. El servidor escucha
en todas las interfaces, pero el Firewall de Windows debe permitir TCP 8000
para que otros equipos puedan conectarse. En una terminal de PowerShell como
administrador, crea una regla limitada a redes privadas:

```powershell
New-NetFirewallRule -DisplayName "Lorekeeper TCP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

Consulta la IP con `ipconfig` y usa la dirección IPv4 del adaptador conectado a
la misma red Wi-Fi/LAN que los demás dispositivos. Desde cada dispositivo abre
`http://IP-DE-LA-PC:8000/` (reemplaza el texto por esa IP; puede cambiar al
cambiar de red). No configures port forwarding en el router y no abras TCP
3306: solo la computadora anfitriona se conecta a MySQL, que permanece en
`127.0.0.1`. Todos los clientes utilizan la misma base de datos del anfitrión.

Para desarrollo local también se puede iniciar con recarga automática:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Al iniciar, el backend aplica cambios de esquema existentes si faltan columnas
y tablas. No agrega cuentas de demostración ni elimina o reinicializa usuarios,
libros, préstamos o reservas heredadas. Las cuentas existentes conservan sus
contraseñas: al iniciar sesión correctamente, una contraseña heredada en texto
plano se reemplaza por su hash PBKDF2. Las cuentas nuevas requieren al menos 12
caracteres.

La sesión se mantiene en una cookie HttpOnly del navegador y es independiente
por dispositivo. HTTP en una LAN compartida no cifra las credenciales ni los
datos transmitidos. Antes de usar cuentas o datos reales, prepara HTTPS y revisa
la protección contra CSRF apropiada para las sesiones mediante cookies.

`backend/.env` está excluido por `.gitignore`; no publiques sus valores. Si alguna
contraseña que estuvo compartida sigue vigente, cámbiala. Usa credenciales
únicas y robustas para MySQL y las cuentas antes de incorporar datos reales.

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
- En Perfiles, el bibliotecario puede clasificar como egresado o no egresado a
  los alumnos de 6.º curso. Un egresado se puede inactivar y reactivar sin
  eliminar su cuenta, préstamos ni historial. La inactivación requiere registrar
  primero las devoluciones pendientes, tanto si el alumno era responsable como
  si retiró el préstamo (`ID_Retira`). Las cuentas inactivas no pueden iniciar
  sesión ni recibir préstamos nuevos. El veto es independiente de la actividad
  y se conserva al inactivar/reactivar.
- No existe alta de préstamo mediante el antiguo endpoint de reservas.

Las fechas de préstamo/vencimiento/devolución se almacenan como `DATE` y se
presentan como `dd/mm/aaaa` en las vistas de préstamos.
