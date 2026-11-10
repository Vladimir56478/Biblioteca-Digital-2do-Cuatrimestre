# Lorekeeper — Biblioteca Digital

Lorekeeper es una biblioteca digital para administrar el catálogo de libros,
las cuentas de alumnos y profesores, los préstamos escolares y domiciliarios,
y el historial de movimientos de inventario. Incluye una interfaz web y una
API desarrollada con FastAPI, conectada a MySQL.

## Contenido

- [Funciones principales](#funciones-principales)
- [Estructura y archivos del proyecto](#estructura-y-archivos-del-proyecto)
- [Cómo se relacionan las partes](#cómo-se-relacionan-las-partes)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Configuración de MySQL](#configuración-de-mysql)
- [Iniciar Lorekeeper](#iniciar-lorekeeper)
- [Reglas de uso](#reglas-de-uso)
- [Datos, sesiones y seguridad](#datos-sesiones-y-seguridad)
- [Comprobaciones y solución de problemas](#comprobaciones-y-solución-de-problemas)

## Funciones principales

- Buscar y consultar libros del catálogo.
- Administrar el catálogo y el stock como Bibliotecario.
- Registrar préstamos del **Cuaderno Diario** y de la **Ficha Domiciliaria**.
- Consultar préstamos propios o, como Bibliotecario, filtrar y registrar
  devoluciones.
- Consultar perfiles, clasificar alumnos egresados y gestionar vetos y cuentas.
- Consultar el historial de bajas técnicas de ejemplares.

## Estructura y archivos del proyecto

```text
Biblioteca-Digital-2do-Cuatrimestre/
├── backend/
│   ├── .env                 # Configuración privada de la conexión a MySQL
│   ├── db.py                # Carga configuración y prepara el motor SQLAlchemy
│   ├── main.py              # API, migraciones y reglas principales de Lorekeeper
│   └── user_deletion.py     # Evita inactivar cuentas con préstamos activos
├── static/
│   ├── app.js               # Interacciones, vistas y solicitudes a la API
│   ├── index.html           # Estructura de las pantallas del sitio
│   ├── logo.png             # Logo que muestra la página
│   └── styles.css           # Apariencia y diseño adaptable
├── .gitignore               # Archivos locales o generados que Git debe ignorar
├── README.md                # Guía del proyecto, instalación, uso y seguridad
├── requirements.txt         # Paquetes Python que necesita el backend
├── .venv/                   # Entorno virtual local (se crea al instalar)
├── .vscode/                 # Ajustes opcionales del editor (locales)
└── .git/                    # Historial y datos internos del repositorio Git
```

### Archivos de la aplicación

- **`backend/main.py`** es el punto principal del backend. Define la aplicación
  FastAPI, los endpoints `/api/...`, la validación de datos, la autenticación,
  los roles y las reglas de catálogo, préstamos, perfiles e historial. También
  comprueba y adapta las tablas o columnas que requieren las funciones actuales
  cuando se importa la aplicación al iniciar Uvicorn.
- **`backend/db.py`** carga `backend/.env`, selecciona la conexión local,
  Clever Cloud o una URI configurada y crea un motor SQLAlchemy compartido.
  `main.py` obtiene ese mismo motor para ejecutar consultas y transacciones.
- **`backend/user_deletion.py`** contiene una validación de préstamos activa
  que usa `main.py` antes de inactivar un alumno egresado. Revisa tanto los
  préstamos donde es responsable como aquellos que retiró por otra persona.
- **`backend/.env`** guarda los datos privados para conectar con MySQL. Se crea
  localmente y **no debe compartirse ni subirse al repositorio**.
- **`static/index.html`** define las vistas, formularios, navegación y nombres
  de los controles que manipula JavaScript. Carga la hoja de estilos y el
  archivo de interacción.
- **`static/app.js`** escucha esos controles, solicita datos a `/api/...`,
  muestra resultados y actualiza la pantalla. Los permisos visuales ayudan a
  la navegación, pero la autorización real siempre se comprueba en el backend.
- **`static/styles.css`** define colores, distribución, accesibilidad visual y
  adaptaciones para pantallas pequeñas.
- **`static/logo.png`** es la imagen de marca que muestra el encabezado HTML.
- **`README.md`** explica cómo configurar, iniciar y usar Lorekeeper, además de
  sus reglas y limitaciones operativas.

### Archivos y carpetas de desarrollo

- **`requirements.txt`** enumera las dependencias externas de Python. `pip
  install -r requirements.txt` instala FastAPI para la API, Uvicorn para
  ejecutarla, SQLAlchemy para las conexiones y consultas, PyMySQL como
  controlador MySQL, y `python-dotenv` para leer `backend/.env`. No contiene
  el código de la aplicación.
- **`.venv/`** es el entorno virtual local de Python. Aísla los paquetes
  instalados para este proyecto de los de otros proyectos; utiliza la versión
  de Python con la que se creó. Se crea con `python -m venv .venv`, se usa mediante
  `.venv\Scripts\python.exe` en Windows y **no se sube a Git**; otra persona
  puede reconstruirlo instalando `requirements.txt`.
- **`.gitignore`** indica a Git qué archivos locales o generados no debe
  registrar. Aquí se excluyen `.env`, `.venv/`, `venv/`, `env/`, cachés y
  bytecode de Python (`__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd`), ajustes
  locales del editor (`.vscode/`, `.idea/`) y dependencias de Node
  (`node_modules/`). Ignorar un archivo no lo borra de la computadora; evita
  agregarlo al control de versiones.
- **`.vscode/settings.json`** contiene un ajuste local del editor para usar
  variables de entorno en la terminal integrada. La carpeta `.vscode/` está
  excluida de Git, por lo que este ajuste puede no existir al clonar el proyecto.
- **`backend/__pycache__/`** y los archivos `*.pyc` son resultados automáticos
  de Python al importar módulos; no son código fuente y se pueden regenerar.
- **`.git/`** guarda internamente los commits, ramas y metadatos de Git. No es
  parte de la aplicación ni se edita manualmente.

El proyecto no tiene un `package.json` ni una carpeta `node_modules/`: el
frontend usa JavaScript del navegador sin un paso de compilación o instalación
de paquetes Node.

## Cómo se relacionan las partes

1. El comando de Uvicorn carga `backend.main:app`, que crea la API y obtiene el
   motor de base de datos configurado por `backend/db.py`.
2. Durante el inicio, `main.py` ejecuta las comprobaciones de esquema incluidas
   para habilitar las funciones. La base principal y sus tablas base deben
   existir antes de arrancar la aplicación.
3. FastAPI sirve `static/index.html` y los recursos de `static/`. El HTML
   construye la interfaz; CSS la presenta; JavaScript responde a los controles
   y solicita información al backend.
4. Cada solicitud de datos llega a un endpoint `/api/...`. FastAPI valida su
   contenido con modelos Pydantic; los endpoints protegidos verifican sesión,
   rol y reglas de negocio antes de consultar MySQL.
5. SQLAlchemy ejecuta las consultas con parámetros. Las operaciones que deben
   mantenerse juntas (por ejemplo, registrar un préstamo, descontar stock y
   escribir el historial) usan una transacción: se confirman si todo sale bien
   y se revierten ante un error.
6. La API devuelve datos JSON y `app.js` los muestra en la vista correspondiente.
   `user_deletion.py` aporta la comprobación específica que protege el historial
   antes de inactivar cuentas con préstamos pendientes.

En resumen: **HTML/CSS/JavaScript muestran y controlan la interfaz; FastAPI
valida y aplica reglas; SQLAlchemy y PyMySQL conectan el backend con MySQL; y
Git conserva el código, no los archivos locales excluidos.**

## Requisitos

- Python 3.10 o posterior.
- MySQL 8 con InnoDB y una base existente que incluya `usuario`, `libro` y
  `autor`. Los nombres y las columnas base deben coincidir con las consultas de
  la aplicación.
- Acceso de red a MySQL desde la computadora que ejecuta Lorekeeper.

La aplicación crea o adapta algunas tablas y columnas al iniciar, pero no crea
la base de datos ni las tablas principales, ni genera usuarios de demostración.

## Instalación

Desde PowerShell, en la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Si PowerShell impide activar el entorno virtual, se puede invocar directamente
el ejecutable ubicado en `.venv\Scripts\python.exe`.

## Configuración de MySQL

Completa `backend/.env` con una de las opciones siguientes. Para MySQL local,
usa una dirección de loopback y reemplaza la contraseña de ejemplo:

```ini
MYSQL_ADDON_HOST=127.0.0.1
MYSQL_ADDON_PORT=3306
MYSQL_ADDON_USER=root
MYSQL_ADDON_PASSWORD=COMPLETAR_CON_LA_CLAVE_LOCAL
MYSQL_ADDON_DB=biblioteca_digital
```

Para conectar con Clever Cloud mediante variables individuales, configura
`MYSQL_CLEVER_CLOUD_HOST`, `MYSQL_CLEVER_CLOUD_PORT`, `MYSQL_CLEVER_CLOUD_USER`,
`MYSQL_CLEVER_CLOUD_PASSWORD` y `MYSQL_CLEVER_CLOUD_DB`. La presencia del host
de Clever Cloud selecciona ese bloque; al quitarlo, se vuelve a la configuración
local.

También se admiten las variables `MYSQL_ADDON_URI`, `MYSQL_ADDON_URL` y
`DATABASE_URL`. Si alguna está definida, tiene prioridad sobre los bloques de
variables individuales. Las URI con esquema `mysql://` se adaptan al controlador
PyMySQL utilizado por el proyecto. El modo de conexión local rechaza hosts que
no sean `localhost` o loopback; una URI explícita o el bloque de Clever Cloud
puede apuntar a una base remota.

`backend/.env` contiene credenciales. No compartas sus valores ni los agregues
al repositorio; el archivo ya está excluido por `.gitignore`.

## Iniciar Lorekeeper

Inicia el servidor desde la carpeta raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

En la computadora anfitriona abre <http://localhost:8000/>. Para desarrollo con
recarga automática:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Acceso desde otros dispositivos de la LAN

El servidor escucha en todas las interfaces. Para permitir el acceso desde
otros dispositivos:

1. Permite TCP 8000 en el Firewall de Windows, solo para redes privadas. En una
   terminal de PowerShell como administrador:

   ```powershell
   New-NetFirewallRule -DisplayName "Lorekeeper TCP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
   ```
2. Ejecuta `ipconfig` y busca la IPv4 de la computadora anfitriona conectada a
   la misma red.
3. En cada dispositivo abre `http://IP-DE-LA-PC:8000/` y reemplaza el texto por
   esa dirección IPv4.

No configures redirección de puertos en el router ni expongas TCP 3306. Solo la
computadora anfitriona debe conectarse a MySQL; los demás dispositivos usan la
aplicación a través de la LAN.

## Reglas de uso

- La Bibliotecaria crea préstamos desde **Préstamos**, eligiendo un libro del
  catálogo y una cuenta responsable. Solo ella consulta la lista global y
  registra devoluciones.
- El **Cuaderno Diario** vence el día de su alta. Un alumno puede tener un
  ejemplar escolar activo en total; un profesor puede tener hasta 45 ejemplares
  activos sumando ambos módulos. Si un alumno retira un libro por indicación
  docente, el profesor continúa siendo responsable del préstamo.
- La **Ficha Domiciliaria** solo se asigna a un Profesor. El libro y el autor
  provienen del catálogo; se guardan los datos de la ficha y los días corridos
  (30 por defecto) para calcular el vencimiento.
- Los préstamos descuentan `libro.Stock`; `libro.Stock_Total` representa el
  inventario total. Un préstamo vencido sigue activo hasta que la Bibliotecaria
  registra la devolución total.
- Alumnos y Profesores solo consultan sus propios préstamos activos e historial.
- Antes de usar el catálogo, Alumno y Profesor deben guardar su curso (1–6) y
  división (1–10) desde **Inicio**. Luego pueden actualizar esos datos desde el
  mismo lugar; **Perfiles** permite a la Bibliotecaria consultarlos, pero no
  editarlos.
- Las bajas de stock y los préstamos/devoluciones se registran en el historial.
  Los libros con movimientos o historial de préstamos no se pueden eliminar.
- En **Perfiles**, la Bibliotecaria puede clasificar como egresado o no egresado
  a un alumno de 6.º curso. Un egresado se puede inactivar y reactivar sin
  eliminar su cuenta, préstamos ni historial. Antes de inactivarlo deben
  registrarse las devoluciones pendientes, tanto si era responsable como si
  retiró el préstamo (`ID_Retira`). Una cuenta inactiva no puede iniciar sesión
  ni recibir préstamos; el veto se conserva por separado de la actividad.
- No se permite crear préstamos mediante el antiguo endpoint de reservas.

Las fechas de préstamo, vencimiento y devolución se almacenan como `DATE` y se
presentan como `dd/mm/aaaa` en las vistas de préstamos.

## Datos, sesiones y seguridad

- Al iniciar, el backend aplica las migraciones incluidas para agregar o adaptar
  algunas tablas y columnas. No reinicializa usuarios, libros, préstamos ni
  reservas heredadas.
- Las contraseñas heredadas en texto plano se convierten en hashes PBKDF2
  después de un inicio de sesión correcto. Las cuentas nuevas requieren
  contraseñas de 12 a 256 caracteres.
- La sesión usa una cookie `HttpOnly`, independiente por dispositivo, con una
  duración de 12 horas. Las sesiones se guardan en la memoria del proceso: usa
  un solo worker de Uvicorn y ten presente que reiniciar el servidor cierra las
  sesiones existentes.
- `--host 0.0.0.0` permite conexiones desde la LAN, pero HTTP no cifra las
  credenciales ni los datos transmitidos. Para datos reales, utiliza HTTPS y
  revisa una protección CSRF adecuada para sesiones basadas en cookies.
- Usa contraseñas únicas y robustas para MySQL y las cuentas. Si una contraseña
  que estuvo compartida continúa activa, cámbiala.

## Comprobaciones y solución de problemas

Para comprobar la sintaxis de los módulos Python sin iniciar la aplicación:

```powershell
.\.venv\Scripts\python.exe -m compileall backend
```

Si el servidor no inicia, revisa que MySQL esté disponible, que la base y las
tablas principales existan y que las variables de `backend/.env` sean correctas.
No compartas el archivo `.env` al pedir ayuda. Si falla la conexión, confirma
también el host y puerto configurados y que el usuario tenga permisos sobre la
base.
