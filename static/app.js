/*
  Lógica de la interfaz de la biblioteca digital.
  Controla el login, los permisos por rol, la búsqueda de libros,
  la edición del catálogo, las reservas y la comunicación con la API del backend.
*/

// Estado global de la app para conservar la sesión del usuario entre recargas de la página.
let authState = {
  isAuthenticated: false,
  ID_Usuario: null,
  Nombre_Completo: null,
  Tipo: null
}

let currentEditBookStock = null
let historyCurrentTab = 'reservas'

// Recupera la sesión guardada en el navegador para volver a entrar a la app sin pedir login otra vez.
function loadAuthState() {
  const stored = localStorage.getItem('authState')
  if (stored) {
    authState = JSON.parse(stored)
  }
  updateUIBasedOnAuth()
  if (authState.isAuthenticated) {
    showView('home')
    doSearch()
  }
}

// Guarda la sesión actual para que los datos del usuario sigan disponibles en esa misma máquina.
function saveAuthState() {
  localStorage.setItem('authState', JSON.stringify(authState))
}

function getAuthHeaders(extra = {}) {
  const headers = { ...extra }
  if (authState.ID_Usuario) headers['X-User-Id'] = String(authState.ID_Usuario)
  if (authState.Tipo) headers['X-User-Type'] = authState.Tipo
  return headers
}

// Cerrar sesión
function logout() {
  authState = { isAuthenticated: false, ID_Usuario: null, Nombre_Completo: null, Tipo: null }
  localStorage.removeItem('authState')
  updateUIBasedOnAuth()
  showView('account')
}

function setItemVisibility(item, isVisible) {
  item.style.opacity = isVisible ? '1' : '0.35'
  item.style.pointerEvents = isVisible ? 'auto' : 'none'
  item.style.cursor = isVisible ? 'pointer' : 'not-allowed'
}

// Ajusta qué elementos se ven según el rol del usuario y si ya inició sesión.
function updateUIBasedOnAuth() {
  const protectedItems = document.querySelectorAll('[data-protected="true"]')
  const welcome = document.getElementById('welcome')
  const normalizedRole = authState.Tipo ? authState.Tipo.trim() : ''
  const isUser = normalizedRole === 'Alumno' || normalizedRole === 'Profesor' || normalizedRole === 'Bibliotecario'

  if (authState.isAuthenticated) {
    protectedItems.forEach(item => {
      const requiredRole = item.getAttribute('data-role')
      let isVisible = false
      if (!requiredRole || requiredRole === 'user') {
        isVisible = isUser
      } else if (requiredRole === 'Bibliotecario') {
        isVisible = normalizedRole === 'Bibliotecario'
      } else {
        isVisible = normalizedRole === requiredRole
      }
      setItemVisibility(item, isVisible)
    })
    if (welcome) {
      welcome.style.display = 'block'
      welcome.textContent = `¡Hola, ${authState.Nombre_Completo}! (${authState.Tipo})\n[Cerrar sesión]`
      welcome.style.cursor = 'pointer'
      welcome.onclick = logout
    }
  } else {
    protectedItems.forEach(item => setItemVisibility(item, false))
    if (welcome) {
      welcome.style.display = 'none'
    }
  }
}

// Cambia entre las vistas principales de la app y bloquea el acceso a las pantallas reservadas al bibliotecario.
function showView(viewName) {
  try {
    if (viewName !== 'account' && !authState.isAuthenticated) {
      console.warn('Acceso bloqueado: debes iniciar sesión primero')
      showView('account')
      return
    }
    const adminViews = ['admin', 'edit', 'history', 'profiles']
    if (adminViews.includes(viewName) && authState.Tipo !== 'Bibliotecario') {
      console.warn('Acceso bloqueado: solo el bibliotecario puede entrar a esta vista')
      showView('home')
      return
    }
    const views = ['account', 'home', 'reserve', 'admin', 'edit', 'history', 'profiles']
    views.forEach(v => {
      const el = document.getElementById('view-' + v)
      if (el) el.style.display = 'none'
    })
    const target = document.getElementById('view-' + viewName)
    if (target) target.style.display = 'block'
    if (viewName === 'edit') {
      loadEditBooks()
    }
    if (viewName === 'history') {
      loadHistoryLogs()
    }
    if (viewName === 'profiles') {
      loadProfiles()
    }
  } catch (e) {
    console.error('Error in showView:', e)
  }
}

// Carga los autores disponibles para completar los formularios de alta y edición de libros.
async function fetchAuthors() {
  try {
    const res = await fetch('/api/authors')
    const authors = await res.json()
    const selects = document.querySelectorAll('#authorSelect, #editAuthorSelect')
    selects.forEach(sel => {
      if (!sel) return
      sel.innerHTML = '<option value="">Seleccione autor</option>'
      authors.forEach(a => {
        const opt = document.createElement('option')
        opt.value = a.ID_Autor
        opt.textContent = a.Nombre
        sel.appendChild(opt)
      })
    })
  } catch (e) {
    console.error('Error fetching authors:', e)
  }
}

const editState = { page: 1, limit: 4, pages: 1, query: '' }

// Solicita los libros que pueden editarse y arma la lista paginada para la vista de administración.
async function loadEditBooks(query = '', page = 1) {
  const results = document.getElementById('editListTab')
  const pagination = document.getElementById('editPagination')
  if (!results) return
  editState.query = query
  try {
    const res = await fetch('/api/search?title=' + encodeURIComponent(query) + '&page=' + page + '&limit=' + editState.limit)
    const data = await res.json()
    results.innerHTML = ''
    if (!res.ok) {
      results.innerHTML = '<p>Error cargando libros para editar</p>'
      if (pagination) pagination.innerHTML = ''
      return
    }
    if (!data.books || data.books.length === 0) {
      results.innerHTML = '<p>No se encontraron libros para editar</p>'
      if (pagination) pagination.innerHTML = ''
      return
    }
    data.books.forEach(it => {
      const card = document.createElement('div')
      card.className = 'card'
      card.innerHTML = `
        <div class="thumb"></div>
        <div style="flex:1">
          <div style="font-weight:700; color:var(--accent); margin-bottom:4px">${it.Titulo}</div>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Autor:</strong> ${it.Autor || '--'}</p>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Editorial:</strong> ${it.Editorial || '--'}</p>
          <p style="margin:0; color:#0b5a52; font-weight:700;">Stock: ${it.Stock}</p>
          <button type="button" class="edit-book-btn" data-id="${it.ID_Libro}">Editar</button>
        </div>
      `
      results.appendChild(card)
    })
    document.querySelectorAll('.edit-book-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const bookId = Number(btn.getAttribute('data-id'))
        const book = data.books.find(item => item.ID_Libro === bookId)
        if (book) populateEditForm(book)
      })
    })
    editState.page = data.page
    editState.pages = data.pages
    if (pagination) {
      renderPagination(pagination, data.page, data.pages, newPage => loadEditBooks(query, newPage))
    }
    switchEditSubtab('list')
  } catch (e) {
    console.error('Error al cargar libros para editar:', e)
    results.innerHTML = '<p>Error cargando libros para editar</p>'
    if (pagination) pagination.innerHTML = ''
  }
}

function populateEditForm(book) {
  const form = document.getElementById('editForm')
  if (!form) return
  document.getElementById('editBookId').value = book.ID_Libro
  document.getElementById('editTitulo').value = book.Titulo || ''
  document.getElementById('editEditorial').value = book.Editorial || ''
  document.getElementById('editAño_Publicacion').value = book.Año_Publicacion || ''
  document.getElementById('editISBN').value = book.ISBN || ''
  document.getElementById('editSinopsis').value = book.Sinopsis || ''
  document.getElementById('editStock').value = book.Stock ?? 0
  document.getElementById('editMotivo').value = ''
  currentEditBookStock = book.Stock ?? 0
  const authorSelect = document.getElementById('editAuthorSelect')
  if (authorSelect) {
    authorSelect.value = book.ID_Autor || ''
  }
  // Cambiar a la subpestaña de detalle para que el usuario edite el libro seleccionado
  switchEditSubtab('detail')
}

// Cambiar entre subpestañas de edición: 'list' o 'detail'
function switchEditSubtab(tab) {
  const list = document.getElementById('editListTab')
  const detail = document.getElementById('editDetailTab')
  const tabButtons = document.querySelectorAll('.edit-tab-btn')
  if (tab === 'detail') {
    if (list) list.style.display = 'none'
    if (detail) detail.style.display = 'block'
  } else {
    if (list) list.style.display = 'block'
    if (detail) detail.style.display = 'none'
  }
  tabButtons.forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === tab)
  })
}

// Construye una tabla dinámica para mostrar el historial de reservas y bajas con formato consistente.
async function renderHistoryTable(columns, rows, container, msg) {
  if (!container) return
  container.innerHTML = ''
  if (msg) msg.textContent = ''

  if (!rows.length) {
    container.innerHTML = '<p>No hay registros para mostrar.</p>'
    return
  }

  const table = document.createElement('table')
  table.className = 'history-table'

  const thead = document.createElement('thead')
  const headerRow = document.createElement('tr')
  columns.forEach(col => {
    const th = document.createElement('th')
    th.textContent = col.label
    headerRow.appendChild(th)
  })
  thead.appendChild(headerRow)
  table.appendChild(thead)

  const tbody = document.createElement('tbody')
  rows.forEach(rowData => {
    const row = document.createElement('tr')
    columns.forEach(col => {
      const td = document.createElement('td')
      const value = rowData[col.key]
      td.textContent = value != null ? value : '-'
      row.appendChild(td)
    })
    tbody.appendChild(row)
  })
  table.appendChild(tbody)
  container.appendChild(table)
}

function switchHistorySubtab(tab) {
  historyCurrentTab = tab
  document.querySelectorAll('.history-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tab)
  })
  const reservasEl = document.getElementById('history-reservas')
  const bajasEl = document.getElementById('history-bajas')
  if (tab === 'reservas') {
    if (reservasEl) reservasEl.style.display = 'block'
    if (bajasEl) bajasEl.style.display = 'none'
    loadHistoryReservas()
  } else {
    if (reservasEl) reservasEl.style.display = 'none'
    if (bajasEl) bajasEl.style.display = 'block'
    loadHistoryBajas()
  }
}

async function loadHistoryLogs() {
  switchHistorySubtab(historyCurrentTab)
}

const historyState = {
  reservas: { page: 1, limit: 10, pages: 1 },
  bajas: { page: 1, limit: 10, pages: 1 }
}

async function loadHistoryReservas(page = 1) {
  const container = document.getElementById('history-reservas')
  const pagination = document.getElementById('historyReservasPagination')
  const msg = document.getElementById('historyMsg')
  if (!container) return
  if (msg) msg.textContent = ''

  try {
    const res = await fetch('/api/history/reservas?page=' + page + '&limit=' + historyState.reservas.limit, {
      headers: getAuthHeaders()
    })
    const data = await res.json()
    if (!res.ok) {
      if (msg) {
        msg.textContent = 'Error cargando reservas: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
      return
    }

    const columns = [
      { key: 'Codigo_reserva', label: 'Código' },
      { key: 'Fecha_Reserva', label: 'Fecha reserva' },
      { key: 'Fecha_Expiracion_Reserva', label: 'Fecha expiración' },
      { key: 'Usuario', label: 'Usuario' },
      { key: 'Libro', label: 'Libro' },
      { key: 'Cantidad', label: 'Cantidad' }
    ]
    renderHistoryTable(columns, data.reservas || [], container, msg)
    historyState.reservas.page = data.page
    historyState.reservas.pages = data.pages
    if (pagination) {
      renderPagination(pagination, data.page, data.pages, newPage => loadHistoryReservas(newPage))
    }
  } catch (e) {
    console.error('Error al cargar reservas:', e)
    if (msg) {
      msg.textContent = 'Error cargando reservas'
      msg.style.color = 'red'
    }
  }
}

async function loadHistoryBajas(page = 1) {
  const container = document.getElementById('history-bajas')
  const pagination = document.getElementById('historyBajasPagination')
  const msg = document.getElementById('historyMsg')
  if (!container) return
  if (msg) msg.textContent = ''

  try {
    const res = await fetch('/api/history/bajas?page=' + page + '&limit=' + historyState.bajas.limit, {
      headers: getAuthHeaders()
    })
    const data = await res.json()
    if (!res.ok) {
      if (msg) {
        msg.textContent = 'Error cargando bajas: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
      return
    }

    const columns = [
      { key: 'Fecha', label: 'Fecha' },
      { key: 'Libro', label: 'Libro' },
      { key: 'Cantidad', label: 'Cantidad' },
      { key: 'Motivo', label: 'Motivo' }
    ]
    renderHistoryTable(columns, data.bajas || [], container, msg)
    historyState.bajas.page = data.page
    historyState.bajas.pages = data.pages
    if (pagination) {
      renderPagination(pagination, data.page, data.pages, newPage => loadHistoryBajas(newPage))
    }
  } catch (e) {
    console.error('Error al cargar bajas:', e)
    if (msg) {
      msg.textContent = 'Error cargando bajas de stock'
      msg.style.color = 'red'
    }
  }
}


const searchState = { page: 1, limit: 4, total: 0, pages: 1 }

function renderPagination(container, page, pages, onPageClick) {
  if (!container) return
  container.innerHTML = ''
  if (pages <= 1) return

  const prev = document.createElement('button')
  prev.textContent = 'Anterior'
  prev.disabled = page <= 1
  prev.addEventListener('click', () => onPageClick(page - 1))
  container.appendChild(prev)

  for (let i = 1; i <= pages; i += 1) {
    const btn = document.createElement('button')
    btn.textContent = String(i)
    btn.className = i === page ? 'active' : ''
    btn.disabled = i === page
    btn.addEventListener('click', () => onPageClick(i))
    container.appendChild(btn)
  }

  const next = document.createElement('button')
  next.textContent = 'Siguiente'
  next.disabled = page >= pages
  next.addEventListener('click', () => onPageClick(page + 1))
  container.appendChild(next)
}

// Consulta la API del catálogo y arma las tarjetas del buscador con stock y botón de reserva.
async function doSearch(page = 1) {
  const searchInput = document.getElementById('searchInput')
  if (!searchInput) return
  const q = searchInput.value
  const container = document.getElementById('results')
  const pagination = document.getElementById('resultsPagination')
  if (!container) return
  
  try {
    const res = await fetch('/api/search?title=' + encodeURIComponent(q) + '&page=' + page + '&limit=' + searchState.limit)
    const data = await res.json()
    container.innerHTML = ''
    if (!res.ok) {
      container.innerHTML = '<p>Error cargando catálogo.</p>'
      return
    }
    if (!data.books || data.books.length === 0) {
      container.innerHTML = '<p>No se encontraron libros</p>'
      pagination.innerHTML = ''
      return
    }
    data.books.forEach(it => {
      const card = document.createElement('div')
      card.className = 'card'
      card.innerHTML = `
        <div class="thumb"></div>
        <div style="flex:1">
          <div style="font-weight:700; color:var(--accent); margin-bottom:4px;">${it.Titulo}</div>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Autor:</strong> ${it.Autor || '--'}</p>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Editorial:</strong> ${it.Editorial || '--'}</p>
          <p style="margin:0; color:#0b5a52; font-weight:700;">Stock: ${it.Stock}</p>
          <button type="button" class="reserve-btn" data-id="${it.ID_Libro}" data-titulo="${it.Titulo}" style="margin-top: 8px; background: #0b5a52; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;">Reservar</button>
        </div>
      `
      container.appendChild(card)
    })
    document.querySelectorAll('.reserve-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault()
        const titulo = btn.getAttribute('data-titulo')
        const bookId = Number(btn.getAttribute('data-id'))
        preFillAndShowReserveForm(titulo, bookId)
      })
    })
    searchState.page = data.page
    searchState.pages = data.pages
    if (pagination) {
      renderPagination(pagination, data.page, data.pages, newPage => doSearch(newPage))
    }
  } catch (e) {
    console.error('Error searching:', e)
    if (container) {
      container.innerHTML = '<p>Error cargando catálogo.</p>'
    }
  }
}

function preFillAndShowReserveForm(titulo, bookId) {
  const tituloInput = document.getElementById('reserveTitulo')
  const bookIdInput = document.getElementById('reserveBookId')
  if (tituloInput) {
    tituloInput.value = titulo
  }
  if (bookIdInput) {
    bookIdInput.value = bookId || ''
  }
  showView('reserve')
}

// Mantiene el estado de paginación de la tabla de usuarios para navegar entre páginas de perfiles.
const profilesState = { page: 1, limit: 10, pages: 1 }

async function loadProfiles(page = 1) {
  const container = document.getElementById('profilesContainer')
  const pagination = document.getElementById('profilesPagination')
  const msg = document.getElementById('profilesMsg')
  if (!container) return
  if (msg) msg.textContent = ''

  try {
    const res = await fetch('/api/users?role=all&page=' + page + '&limit=' + profilesState.limit, {
      headers: getAuthHeaders()
    })
    const data = await res.json()
    if (!res.ok) {
      if (msg) {
        msg.textContent = 'Error cargando perfiles: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
      return
    }

    container.innerHTML = ''
    if (!data.users || !Array.isArray(data.users) || data.users.length === 0) {
      container.innerHTML = '<p>No hay usuarios registrados</p>'
      if (pagination) pagination.innerHTML = ''
      return
    }

    const table = document.createElement('table')
    table.className = 'history-table'
    table.style.width = '100%'

    const thead = document.createElement('thead')
    const headerRow = document.createElement('tr')
    const headers = ['Nombre', 'Gmail', 'Tipo', 'Estado', 'Acciones']
    headers.forEach(h => {
      const th = document.createElement('th')
      th.textContent = h
      headerRow.appendChild(th)
    })
    thead.appendChild(headerRow)
    table.appendChild(thead)

    const tbody = document.createElement('tbody')
    data.users.forEach(user => {
      const row = document.createElement('tr')
      
      const nameCell = document.createElement('td')
      nameCell.textContent = user.Nombre_Completo || '-'
      row.appendChild(nameCell)

      const gmailCell = document.createElement('td')
      gmailCell.textContent = user.Gmail || '-'
      row.appendChild(gmailCell)

      const typeCell = document.createElement('td')
      typeCell.textContent = user.Tipo || '-'
      row.appendChild(typeCell)

      const stateCell = document.createElement('td')
      stateCell.textContent = user.Estado || 'no vetado'
      row.appendChild(stateCell)

      const actionCell = document.createElement('td')
      if (user.Estado === 'vetado') {
        const unbanBtn = document.createElement('button')
        unbanBtn.type = 'button'
        unbanBtn.textContent = 'Desvetar'
        unbanBtn.style.background = '#4caf50'
        unbanBtn.style.color = 'white'
        unbanBtn.style.border = 'none'
        unbanBtn.style.padding = '6px 12px'
        unbanBtn.style.borderRadius = '4px'
        unbanBtn.style.cursor = 'pointer'
        unbanBtn.addEventListener('click', async () => {
          await unbanUser(user.ID_Usuario)
          loadProfiles(page)
        })
        actionCell.appendChild(unbanBtn)
      } else {
        const banBtn = document.createElement('button')
        banBtn.type = 'button'
        banBtn.textContent = 'Vetar'
        banBtn.style.background = '#f44336'
        banBtn.style.color = 'white'
        banBtn.style.border = 'none'
        banBtn.style.padding = '6px 12px'
        banBtn.style.borderRadius = '4px'
        banBtn.style.cursor = 'pointer'
        banBtn.addEventListener('click', async () => {
          await banUser(user.ID_Usuario)
          loadProfiles(page)
        })
        actionCell.appendChild(banBtn)
      }
      row.appendChild(actionCell)
      tbody.appendChild(row)
    })
    table.appendChild(tbody)
    container.appendChild(table)

    profilesState.page = data.page
    profilesState.pages = data.pages
    if (pagination) {
      renderPagination(pagination, data.page, data.pages, newPage => loadProfiles(newPage))
    }
  } catch (e) {
    console.error('Error cargando perfiles:', e)
    if (msg) {
      msg.textContent = 'Error cargando perfiles: ' + e.message
      msg.style.color = 'red'
    }
  }
}

// Vetar usuario
async function banUser(userId) {
  const msg = document.getElementById('profilesMsg')
  try {
    const res = await fetch('/api/users/' + userId + '/state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ Estado: 'vetado' })
    })
    const data = await res.json()
    if (res.ok) {
      if (msg) {
        msg.textContent = 'Usuario vetado correctamente'
        msg.style.color = 'green'
      }
      loadProfiles()
    } else {
      if (msg) {
        msg.textContent = 'Error vetando usuario: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
    }
  } catch (e) {
    console.error('Error vetando usuario:', e)
    if (msg) {
      msg.textContent = 'Error vetando usuario'
      msg.style.color = 'red'
    }
  }
}

// Desvetar usuario
async function unbanUser(userId) {
  const msg = document.getElementById('profilesMsg')
  try {
    const res = await fetch('/api/users/' + userId + '/state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ Estado: 'no vetado' })
    })
    const data = await res.json()
    if (res.ok) {
      if (msg) {
        msg.textContent = 'Usuario desvetado correctamente'
        msg.style.color = 'green'
      }
      loadProfiles()
    } else {
      if (msg) {
        msg.textContent = 'Error desvetando usuario: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
    }
  } catch (e) {
    console.error('Error desvetando usuario:', e)
    if (msg) {
      msg.textContent = 'Error desvetando usuario'
      msg.style.color = 'red'
    }
  }
}

// Conecta formularios, botones y enlaces con las funciones de la interfaz para que respondan a la interacción del usuario.
function setupEventListeners() {
  // Se preparan los controles de la interfaz al cargar la página.

  // Inicio de sesión
  const loginForm = document.getElementById('loginForm')
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const data = Object.fromEntries(new FormData(e.target).entries())
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      const j = await res.json()
      const msg = document.getElementById('loginMsg')
      if (res.ok) {
        authState.isAuthenticated = true
        authState.ID_Usuario = j.ID_Usuario
        authState.Nombre_Completo = j.Nombre_Completo
        authState.Tipo = j.Tipo
        saveAuthState()
        updateUIBasedOnAuth()
        if (msg) msg.textContent = ''
        e.target.reset()
        showView('home')
        doSearch()
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
          msg.style.color = 'red'
        }
      }
    })
  }

  // Registro de cuenta
  const signupForm = document.getElementById('signupForm')
  if (signupForm) {
    signupForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const data = Object.fromEntries(new FormData(e.target).entries())
      const res = await fetch('/api/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      const j = await res.json()
      const msg = document.getElementById('signupMsg')
      if (res.ok) {
        authState.isAuthenticated = true
        authState.ID_Usuario = j.ID_Usuario
        authState.Nombre_Completo = j.Nombre_Completo
        authState.Tipo = j.Tipo
        saveAuthState()
        updateUIBasedOnAuth()
        if (msg) {
          msg.textContent = 'Cuenta creada exitosamente'
          msg.style.color = 'green'
        }
        e.target.reset()
        switchAuthTab('login')
        setTimeout(() => { showView('home'); doSearch() }, 1000)
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
          msg.style.color = 'red'
        }
      }
    })
  }

  // Pestañas de autenticación
  const authTabs = document.querySelectorAll('.auth-tab')
  authTabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      e.preventDefault()
      switchAuthTab(tab.getAttribute('data-tab'))
    })
  })

  // Buscar libros
  const searchBtn = document.getElementById('searchBtn')
  if (searchBtn) {
    searchBtn.addEventListener('click', doSearch)
  }
  const searchInput = document.getElementById('searchInput')
  if (searchInput) {
    searchInput.addEventListener('keyup', (e) => {
      if (e.key === 'Enter') doSearch()
    })
  }

  // Formulario de alta de libro
  const bookForm = document.getElementById('bookForm')
  if (bookForm) {
    bookForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const data = Object.fromEntries(new FormData(e.target).entries())
      if (data.ID_Autor === '') data.ID_Autor = null
      if (data.Año_Publicacion === '') data.Año_Publicacion = null
      data.Stock = Number(data.Stock || 0)
      const res = await fetch('/api/books', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(data)
      })
      const j = await res.json()
      const msg = document.getElementById('bookMsg')
      if (res.ok) {
        if (msg) {
          msg.textContent = 'Libro creado'
          msg.style.color = 'green'
        }
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
          msg.style.color = 'red'
        }
      }
      e.target.reset()
    })
  }

  // Formulario de reserva
  const reserveForm = document.getElementById('reserveForm')
  if (reserveForm) {
    reserveForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const formData = Object.fromEntries(new FormData(e.target).entries())
      // Si no se proporcionó ID_Libro, intentar resolver por título (case-insensitive)
      let libroId = Number(formData.ID_Libro)
      const tituloIngresado = (formData.Titulo || '').trim()
      if ((!libroId || libroId === 0) && tituloIngresado) {
        try {
          const sres = await fetch('/api/search?title=' + encodeURIComponent(tituloIngresado) + '&limit=10')
          const sdata = await sres.json()
          if (sres.ok && Array.isArray(sdata.books) && sdata.books.length > 0) {
            const titleLower = tituloIngresado.toLowerCase()
            // Preferir coincidencia exacta ignorando mayúsculas
            const exact = sdata.books.find(b => (b.Titulo || '').toLowerCase() === titleLower)
            if (exact) {
              libroId = exact.ID_Libro
            } else if (sdata.books.length === 1) {
              // Si solo hay un resultado, usarlo
              libroId = sdata.books[0].ID_Libro
            }
          }
        } catch (err) {
          console.error('Error buscando libro por título antes de reservar:', err)
        }
      }

      const data = {
        ID_Libro: Number(libroId),
        ID_Usuario: authState.ID_Usuario,
        Cantidad: Number(formData.Cantidad)
      }
      const msg = document.getElementById('reserveMsg')
      if (!data.ID_Libro) {
        if (msg) {
          msg.textContent = 'Error: Debes seleccionar un libro desde el catálogo antes de reservar.'
          msg.style.color = 'red'
        }
        return
      }
      const res = await fetch('/api/reserve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(data)
      })
      const j = await res.json()
      if (res.ok) {
        if (msg) {
          msg.textContent = 'Reserva: ' + j.Codigo_reserva
          msg.style.color = 'green'
        }
        e.target.reset()
      } else {
        if (msg) {
          const detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
          msg.textContent = 'Error: ' + (detail || 'Error')
          msg.style.color = 'red'
        }
      }
    })
  }

  // Botón para limpiar título pre-rellenado
  const clearTituloBtn = document.getElementById('clearTituloBtn')
  if (clearTituloBtn) {
    clearTituloBtn.addEventListener('click', () => {
      const tituloInput = document.getElementById('reserveTitulo')
      const bookIdInput = document.getElementById('reserveBookId')
      if (tituloInput) {
        tituloInput.value = ''
        tituloInput.focus()
      }
      if (bookIdInput) {
        bookIdInput.value = ''
      }
    })
  }

  const editSearchBtn = document.getElementById('editSearchBtn')
  const editSearchInput = document.getElementById('editSearchInput')
  if (editSearchBtn && editSearchInput) {
    editSearchBtn.addEventListener('click', () => {
      loadEditBooks(editSearchInput.value)
    })
    editSearchInput.addEventListener('keyup', (e) => {
      if (e.key === 'Enter') loadEditBooks(editSearchInput.value)
    })
  }

  // Botones de pestañas en la vista de edición
  document.querySelectorAll('.edit-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const t = btn.getAttribute('data-tab')
      // Si se cambia a la pestaña lista, recargar los libros (lista completa/búsqueda actual)
      if (t === 'list') {
        const editSearchInput = document.getElementById('editSearchInput')
        const q = editSearchInput ? editSearchInput.value : ''
        loadEditBooks(q)
      } else {
        switchEditSubtab(t)
      }
    })
  })

  document.querySelectorAll('.history-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-tab')
      switchHistorySubtab(tab)
    })
  })

  const backToEditList = document.getElementById('backToEditList')
  if (backToEditList) {
    backToEditList.addEventListener('click', () => {
      // Volver a la lista y refrescar
      switchEditSubtab('list')
      const editSearchInput = document.getElementById('editSearchInput')
      loadEditBooks(editSearchInput?.value || '')
    })
  }

  const editForm = document.getElementById('editForm')
  const deleteBookBtn = document.getElementById('deleteBookBtn')
  if (deleteBookBtn) {
    deleteBookBtn.addEventListener('click', async () => {
      const bookId = Number(document.getElementById('editBookId').value)
      if (!bookId) return
      if (!confirm('¿Eliminar este libro y todos los registros asociados? Esta acción no se puede deshacer.')) return
      try {
        const res = await fetch('/api/books/' + bookId, {
          method: 'DELETE',
          headers: getAuthHeaders()
        })
        const j = await res.json()
        const msg = document.getElementById('editMsg')
        if (res.ok) {
          if (msg) {
            msg.textContent = 'Libro eliminado correctamente'
            msg.style.color = 'green'
          }
          switchEditSubtab('list')
          loadEditBooks(editSearchInput?.value || '')
        } else {
          if (msg) {
            msg.textContent = 'Error: ' + (j.detail || 'Error')
            msg.style.color = 'red'
          }
        }
      } catch (e) {
        console.error('Error eliminando libro:', e)
      }
    })
  }

  if (editForm) {
    editForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const formData = Object.fromEntries(new FormData(e.target).entries())
      const bookId = Number(formData.ID_Libro)
      const stockValue = formData.Stock !== '' ? Number(formData.Stock) : undefined
      const payload = {
        Titulo: formData.Titulo || undefined,
        Editorial: formData.Editorial || undefined,
        ID_Autor: formData.ID_Autor ? Number(formData.ID_Autor) : undefined,
        Año_Publicacion: formData.Año_Publicacion ? Number(formData.Año_Publicacion) : undefined,
        ISBN: formData.ISBN || undefined,
        Sinopsis: formData.Sinopsis || undefined,
        Stock: stockValue,
      }
      if (currentEditBookStock !== null && stockValue !== undefined && stockValue < currentEditBookStock) {
        if (!formData.Motivo) {
          const msg = document.getElementById('editMsg')
          if (msg) {
            msg.textContent = 'Debe seleccionar un motivo técnico cuando reduce stock.'
            msg.style.color = 'red'
          }
          return
        }
        payload.Motivo = formData.Motivo
      }
      const res = await fetch('/api/books/' + bookId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(payload)
      })
      const j = await res.json()
      const msg = document.getElementById('editMsg')
      if (res.ok) {
        if (msg) {
          msg.textContent = 'Libro actualizado correctamente'
          msg.style.color = 'green'
        }
        loadEditBooks(editSearchInput?.value || '')
        if (currentEditBookStock !== null && stockValue !== undefined && stockValue < currentEditBookStock) {
          document.getElementById('editMotivo').value = ''
        }
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
          msg.style.color = 'red'
        }
      }
    })

    const editStockInput = document.getElementById('editStock')
    const editMotivoSelect = document.getElementById('editMotivo')
    if (editStockInput && editMotivoSelect) {
      editStockInput.addEventListener('input', () => {
        const stockValue = Number(editStockInput.value)
        if (currentEditBookStock !== null && stockValue < currentEditBookStock) {
          editMotivoSelect.style.display = 'block'
        } else {
          editMotivoSelect.style.display = 'none'
          editMotivoSelect.value = ''
        }
      })
    }
  }

  const clearReservasBtn = document.getElementById('clearReservasBtn')
  const clearBajasBtn = document.getElementById('clearBajasBtn')
  if (clearReservasBtn) {
    clearReservasBtn.addEventListener('click', async () => {
      if (!confirm('¿Eliminar todos los registros de reservas del historial?')) return
      const res = await fetch('/api/history/reservas', {
        method: 'DELETE',
        headers: getAuthHeaders()
      })
      const j = await res.json()
      const msg = document.getElementById('historyMsg')
      if (res.ok) {
        if (msg) {
          msg.textContent = 'Historial de reservas eliminado.'
          msg.style.color = 'green'
        }
        if (historyCurrentTab === 'reservas') loadHistoryReservas()
      } else if (msg) {
        msg.textContent = 'Error: ' + (j.detail || 'Error')
        msg.style.color = 'red'
      }
    })
  }
  if (clearBajasBtn) {
    clearBajasBtn.addEventListener('click', async () => {
      if (!confirm('¿Eliminar todos los registros de bajas de stock?')) return
      const res = await fetch('/api/history/bajas', {
        method: 'DELETE',
        headers: getAuthHeaders()
      })
      const j = await res.json()
      const msg = document.getElementById('historyMsg')
      if (res.ok) {
        if (msg) {
          msg.textContent = 'Historial de bajas eliminado.'
          msg.style.color = 'green'
        }
        if (historyCurrentTab === 'bajas') loadHistoryBajas()
      } else if (msg) {
        msg.textContent = 'Error: ' + (j.detail || 'Error')
        msg.style.color = 'red'
      }
    })
  }

  // Los eventos quedan listos para la interacción del usuario.
}

function setupNavigation() {
  // Se definen las rutas visibles dentro de la app.
  document.querySelectorAll('.nav-item').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault()
      const view = a.getAttribute('data-view')
      if (view !== 'account' && !authState.isAuthenticated) {
        alert('Debes iniciar sesión o crear una cuenta primero')
        showView('account')
        return
      }
      showView(view)
    })
  })
  // La navegación queda lista para cambiar entre vistas.
}

// Inicializa la app cargando listeners, sesión y datos base para que la biblioteca quede lista para usar.
function initializeApp() {
  // La interfaz se prepara para usar la sesión y el catálogo.
  setupEventListeners()
  setupNavigation()
  loadAuthState()
  fetchAuthors()
  // La app ya está lista para usarse.
}

// Esperar a que el DOM esté listo
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp)
} else {
  // El DOM ya está cargado (por ejemplo, si el script es async)
  initializeApp()
}

// También intentar configurar inmediatamente si los elementos ya existen
try {
  console.log('[APP] Intentando configuración inmediata...')
  const signupForm = document.getElementById('signupForm')
  if (signupForm && !signupForm.__setupDone) {
    console.log('[APP] Configurando formulario de registro inmediatamente')
    signupForm.__setupDone = true
    signupForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      console.log('[SIGNUP] Formulario enviado')
      const data = Object.fromEntries(new FormData(e.target).entries())
      const res = await fetch('/api/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      const j = await res.json()
      const msg = document.getElementById('signupMsg')
      if (res.ok) {
        authState.isAuthenticated = true
        authState.ID_Usuario = j.ID_Usuario
        authState.Nombre_Completo = j.Nombre_Completo
        authState.Tipo = j.Tipo
        saveAuthState()
        updateUIBasedOnAuth()
        if (msg) {
          msg.textContent = 'Cuenta creada'
          msg.style.color = 'green'
        }
        e.target.reset()
        showView('home')
        doSearch()
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
          msg.style.color = 'red'
        }
      }
    })
  }
} catch (e) {
    console.error('[APP] Error en la configuración inmediata:', e)
  }

console.log('[APP] Configuración completa, esperando el DOM...')
// Agregar interceptor global de envío de formularios


console.log('[APP] Interceptor global de formularios agregado')


