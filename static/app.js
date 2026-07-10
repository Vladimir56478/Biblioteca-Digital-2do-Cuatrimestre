/*
  Lógica del frontend de la biblioteca digital.
  Controla la sesión del usuario, visibilidad de vistas, búsqueda de libros,
  creación y edición de contenidos, reservas y comunicación con la API.
*/

// Estado global de la aplicación
let authState = {
  isAuthenticated: false,
  ID_Usuario: null,
  Nombre_Completo: null,
  Tipo: null
}

let currentEditBookStock = null
let historyCurrentTab = 'reservas'

console.log('[APP] Script cargado')

// Cargar el estado de autenticación desde localStorage
function loadAuthState() {
  console.log('[AUTH] Cargando estado de autenticación')
  const stored = localStorage.getItem('authState')
  if (stored) {
    authState = JSON.parse(stored)
  }
  console.log('[AUTH] Auth state loaded:', authState.isAuthenticated)
  updateUIBasedOnAuth()
  if (authState.isAuthenticated) {
    showView('home')
    doSearch()
  }
}

// Guardar el estado de autenticación en localStorage
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

// Actualizar visibilidad de la interfaz según la autenticación
function updateUIBasedOnAuth() {
  console.log('[UI] Updating UI based on auth')
  const protectedItems = document.querySelectorAll('[data-protected="true"]')
  console.log('[UI] Found protected items:', protectedItems.length)
  const welcome = document.getElementById('welcome')
  console.log('[UI] Welcome element:', welcome ? 'found' : 'NOT FOUND')
  
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
      item.style.opacity = isVisible ? '1' : '0.35'
      item.style.pointerEvents = isVisible ? 'auto' : 'none'
      item.style.cursor = isVisible ? 'pointer' : 'not-allowed'
    })
    if (welcome) {
      welcome.style.display = 'block'
      welcome.textContent = `¡Hola, ${authState.Nombre_Completo}! (${authState.Tipo})\n[Cerrar sesión]`
      welcome.style.cursor = 'pointer'
      welcome.onclick = logout
    }
  } else {
    protectedItems.forEach(item => {
      item.style.opacity = '0.4'
      item.style.pointerEvents = 'none'
      item.style.cursor = 'not-allowed'
    })
    if (welcome) {
      welcome.style.display = 'none'
    }
  }
  console.log('[UI] UI update complete')
}

// Mostrar u ocultar vistas de la aplicación
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
  } catch (e) {
    console.error('Error in showView:', e)
  }
}

function switchAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tab)
  })
  const loginForm = document.getElementById('loginForm')
  const signupForm = document.getElementById('signupForm')
  if (tab === 'signup') {
    if (loginForm) loginForm.style.display = 'none'
    if (signupForm) signupForm.style.display = 'block'
  } else {
    if (loginForm) loginForm.style.display = 'block'
    if (signupForm) signupForm.style.display = 'none'
  }
}

// Obtener autores para los controles select
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

async function loadEditBooks(query = '') {
  const results = document.getElementById('editListTab')
  if (!results) return
  try {
    const res = await fetch('/api/search?title=' + encodeURIComponent(query))
    const items = await res.json()
    results.innerHTML = ''
    if (!items.length) {
      results.innerHTML = '<p>No se encontraron libros para editar</p>'
      return
    }
    items.forEach(it => {
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
        const book = items.find(item => item.ID_Libro === bookId)
        if (book) populateEditForm(book)
      })
    })
    // Asegurarse de que esté activa la subpestaña lista después de cargar
    switchEditSubtab('list')
  } catch (e) {
    console.error('Error al cargar libros para editar:', e)
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

// Buscar libros y mostrarlos con su ID
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

async function loadHistoryReservas() {
  const container = document.getElementById('history-reservas')
  const msg = document.getElementById('historyMsg')
  if (!container) return
  if (msg) msg.textContent = ''

  try {
    const res = await fetch('/api/history/reservas?limit=50', {
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
    renderHistoryTable(columns, data, container, msg)
  } catch (e) {
    console.error('Error al cargar reservas:', e)
    if (msg) {
      msg.textContent = 'Error cargando reservas'
      msg.style.color = 'red'
    }
  }
}

async function loadHistoryBajas() {
  const container = document.getElementById('history-bajas')
  const msg = document.getElementById('historyMsg')
  if (!container) return
  if (msg) msg.textContent = ''

  try {
    const res = await fetch('/api/history/bajas?limit=50', {
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
    renderHistoryTable(columns, data, container, msg)
  } catch (e) {
    console.error('Error al cargar bajas:', e)
    if (msg) {
      msg.textContent = 'Error cargando bajas de stock'
      msg.style.color = 'red'
    }
  }
}


async function doSearch() {
  const searchInput = document.getElementById('searchInput')
  if (!searchInput) return
  const q = searchInput.value
  const container = document.getElementById('results')
  if (!container) return
  
  try {
    const res = await fetch('/api/search?title=' + encodeURIComponent(q))
    const items = await res.json()
    container.innerHTML = ''
    if (items.length === 0) {
      container.innerHTML = '<p>No se encontraron libros</p>'
      return
    }
    items.forEach(it => {
      const card = document.createElement('div')
      card.className = 'card'
      card.innerHTML = `
        <div class="thumb"></div>
        <div style="flex:1">
          <div style="font-weight:700; color:var(--accent); margin-bottom:4px;">${it.Titulo}</div>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Autor:</strong> ${it.Autor || '--'}</p>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Editorial:</strong> ${it.Editorial || '--'}</p>
          <p style="margin:0; color:#0b5a52; font-weight:700;">Stock: ${it.Stock}</p>
          <button type="button" class="reserve-btn" data-titulo="${it.Titulo}" style="margin-top: 8px; background: #0b5a52; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;">Reservar</button>
        </div>
      `
      container.appendChild(card)
    })
    // Agregar event listeners a los botones de reserva
    document.querySelectorAll('.reserve-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault()
        const titulo = btn.getAttribute('data-titulo')
        preFillAndShowReserveForm(titulo)
      })
    })
  } catch (e) {
    console.error('Error searching:', e)
  }
}

function preFillAndShowReserveForm(titulo) {
  const tituloInput = document.getElementById('reserveTitulo')
  if (tituloInput) {
    tituloInput.value = titulo
  }
  showView('reserve')
}

// Configurar todos los event listeners de la página
function setupEventListeners() {
  console.log('[EVENTS] Configurando event listeners')

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
      const data = {
        Titulo: formData.Titulo.trim(),
        ID_Usuario: authState.ID_Usuario,
        Cantidad: Number(formData.Cantidad)
      }
      const res = await fetch('/api/reserve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(data)
      })
      const j = await res.json()
      const msg = document.getElementById('reserveMsg')
      if (res.ok) {
        if (msg) {
          msg.textContent = 'Reserva: ' + j.Codigo_reserva
          msg.style.color = 'green'
        }
        e.target.reset()
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
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
      if (tituloInput) {
        tituloInput.value = ''
        tituloInput.focus()
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

  console.log('[EVENTS] Event listeners registered')
}

function setupNavigation() {
  console.log('[NAV] Configurando navegación')
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
  console.log('[NAV] Configuración de navegación completada')
}

// Función de inicialización para configurar la app
function initializeApp() {
  console.log('[INIT] Inicializando app')
  setupEventListeners()
  setupNavigation()
  loadAuthState()
  fetchAuthors()
  console.log('[INIT] App inicializada')
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


