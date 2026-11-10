/*
  Lógica de la interfaz de la biblioteca digital.
  Controla el login, los permisos por rol, la búsqueda de libros,
  la edición del catálogo, los préstamos y la comunicación con la API del backend.
*/

// Estado de presentación; la identidad real se obtiene del backend mediante la cookie de sesión.
let authState = {
  isAuthenticated: false,
  ID_Usuario: null,
  Nombre_Completo: null,
  Tipo: null
}

let currentEditBookStock = null
let historyCurrentTab = 'bajas'
let banTargetUserId = null
let uiAudioContext = null
let uiAudioUnlocked = false
let audioWarningShown = false

function getUiAudioContext() {
  if (uiAudioContext) return uiAudioContext
  const AudioContextConstructor = window.AudioContext || window.webkitAudioContext
  if (!AudioContextConstructor) {
    if (!audioWarningShown) {
      console.warn('El navegador no admite audio para el feedback de la interfaz.')
      audioWarningShown = true
    }
    return null
  }
  uiAudioContext = new AudioContextConstructor()
  return uiAudioContext
}

function playTone(context, frequency, startOffset, duration, type = 'sine') {
  const oscillator = context.createOscillator()
  const gain = context.createGain()
  const start = context.currentTime + startOffset
  oscillator.type = type
  oscillator.frequency.setValueAtTime(frequency, start)
  gain.gain.setValueAtTime(0.0001, start)
  gain.gain.exponentialRampToValueAtTime(0.035, start + 0.008)
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration)
  oscillator.connect(gain)
  gain.connect(context.destination)
  oscillator.start(start)
  oscillator.stop(start + duration)
}

function playUiSound(kind = 'click') {
  const context = getUiAudioContext()
  if (!context) return

  const play = () => {
    uiAudioUnlocked = true
    if (kind === 'success') {
      playTone(context, 660, 0, 0.09)
      playTone(context, 880, 0.1, 0.12)
    } else if (kind === 'error') {
      playTone(context, 260, 0, 0.11, 'triangle')
      playTone(context, 190, 0.13, 0.13, 'triangle')
    } else {
      playTone(context, 470, 0, 0.045)
    }
  }

  if (context.state === 'running') {
    play()
    return
  }
  context.resume().then(play).catch(error => {
    console.warn('No se pudo habilitar el audio de la interfaz:', error)
  })
}

function setupInteractionSounds() {
  const lastFeedback = new WeakMap()
  const statusForMessage = message => {
    const text = message.textContent.trim()
    if (!text) return null
    const color = message.style.color.toLowerCase()
    if (color === 'green' || color === 'rgb(0, 128, 0)') return 'success'
    if (color === 'red' || color === 'rgb(255, 0, 0)') return 'error'
    return /\b(error|no se pudo|falló|fallo)\b/i.test(text) ? 'error' : null
  }

  document.addEventListener('click', event => {
    if (!(event.target instanceof Element)) return
    const control = event.target.closest('button, a.nav-item, #welcome')
    if (!control || control.hasAttribute('disabled') || control.getAttribute('aria-disabled') === 'true') return
    uiAudioUnlocked = true
    playUiSound('click')
  }, true)

  const feedbackObserver = new MutationObserver(records => {
    const changedMessages = new Set()
    records.forEach(record => {
      const target = record.target instanceof Element ? record.target : record.target.parentElement
      const message = target?.closest('.msg')
      if (message) changedMessages.add(message)
    })
    changedMessages.forEach(message => {
      const status = statusForMessage(message)
      if (!status) {
        lastFeedback.delete(message)
        return
      }
      if (!uiAudioUnlocked) return
      const fingerprint = `${status}:${message.textContent.trim()}`
      if (lastFeedback.get(message) === fingerprint) return
      lastFeedback.set(message, fingerprint)
      playUiSound(status)
    })
  })
  feedbackObserver.observe(document.body, {
    attributes: true,
    attributeFilter: ['style'],
    characterData: true,
    childList: true,
    subtree: true
  })
}

async function loadAuthState() {
  try {
    const response = await fetch('/api/session')
    if (response.ok) {
      const user = await response.json()
      authState = { ...user, isAuthenticated: true }
      updateUIBasedOnAuth()
      showView('home')
      return
    }
    if (response.status !== 401) {
      const result = await response.json()
      const message = document.getElementById('loginMsg')
      if (message) message.textContent = 'No se pudo verificar la sesión: ' + (result.detail || 'Error')
    }
  } catch {
    const message = document.getElementById('loginMsg')
    if (message) message.textContent = 'No se pudo conectar con el servidor para verificar la sesión.'
  }
  updateUIBasedOnAuth()
}

function getAuthHeaders(extra = {}) {
  return { ...extra }
}

async function logout() {
  let response
  try {
    response = await fetch('/api/logout', { method: 'POST' })
  } catch {
    alert('No se pudo conectar con el servidor para cerrar la sesión.')
    playUiSound('error')
    return
  }
  if (!response.ok) {
    alert('No se pudo cerrar la sesión en el servidor.')
    playUiSound('error')
    return
  }
  playUiSound('success')
  authState = { isAuthenticated: false, ID_Usuario: null, Nombre_Completo: null, Tipo: null }
  updateUIBasedOnAuth()
  showView('account')
}

function setItemVisibility(item, isVisible) {
  item.hidden = !isVisible
}

// Ajusta qué elementos se ven según el rol del usuario y si ya inició sesión.
function updateUIBasedOnAuth() {
  const protectedItems = document.querySelectorAll('[data-protected="true"]')
  const welcome = document.getElementById('welcome')
  const navMore = document.getElementById('navMore')
  const navMoreToggle = document.getElementById('navMoreToggle')
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
      } else if (requiredRole === 'borrower') {
        isVisible = normalizedRole === 'Alumno' || normalizedRole === 'Profesor'
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
  if (navMore) {
    navMore.hidden = !navMore.querySelector('.nav-more-menu .nav-item:not([hidden])')
    navMore.classList.remove('is-open')
  }
  if (navMoreToggle) navMoreToggle.setAttribute('aria-expanded', 'false')
}

// Cambia entre las vistas principales de la app y bloquea el acceso a las pantallas reservadas al bibliotecario.
function showView(viewName) {
  try {
    if (viewName !== 'account' && !authState.isAuthenticated) {
      console.warn('Acceso bloqueado: debes iniciar sesión primero')
      showView('account')
      return
    }
    const adminViews = ['admin', 'edit', 'history', 'profiles', 'loans']
    if (adminViews.includes(viewName) && authState.Tipo !== 'Bibliotecario') {
      console.warn('Acceso bloqueado: solo el bibliotecario puede entrar a esta vista')
      showView('home')
      return
    }
    if (viewName === 'my-loans' && !['Alumno', 'Profesor'].includes(authState.Tipo)) {
      showView('home')
      return
    }
    const views = ['account', 'home', 'my-loans', 'loans', 'admin', 'edit', 'history', 'profiles']
    views.forEach(v => {
      const el = document.getElementById('view-' + v)
      if (el) el.style.display = 'none'
    })
    const target = document.getElementById('view-' + viewName)
    if (target) target.style.display = 'block'
    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
      if (item.getAttribute('data-view') === viewName) {
        item.setAttribute('aria-current', 'page')
      } else {
        item.removeAttribute('aria-current')
      }
    })
    const navMore = document.getElementById('navMore')
    const navMoreToggle = document.getElementById('navMoreToggle')
    if (navMoreToggle) {
      navMoreToggle.classList.toggle('active', Boolean(navMore?.querySelector('[aria-current="page"]')))
    }
    if (viewName === 'home') {
      loadProfile()
      doSearch()
    }
    if (viewName === 'my-loans') loadMyLoans()
    if (viewName === 'loans') {
      loadLoanFormOptions()
      loadAdminLoans()
    }
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

// Esta petición se hace una vez al iniciar la app para mantener los selects actualizados.
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

// El resultado incluye botones para cargar cada libro en el formulario de edición.
// Solicita los libros que pueden editarse y arma la lista paginada para la vista de administración.
async function loadEditBooks(query = '', page = 1) {
  const results = document.getElementById('editListTab')
  const pagination = document.getElementById('editPagination')
  if (!results) return
  editState.query = query
  try {
    const res = await fetch('/api/search?title=' + encodeURIComponent(query) + '&page=' + page + '&limit=' + editState.limit, {
      headers: getAuthHeaders()
    })
    const data = await res.json()
    results.innerHTML = ''
    if (!res.ok) {
      results.innerHTML = '<p>Error cargando libros para editar</p>'
      if (pagination) pagination.innerHTML = ''
      playUiSound('error')
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
          <p style="margin:0; color:#0b5a52; font-weight:700;">Total: ${it.Stock_Total} · Disponibles: ${it.Stock_Disponible}</p>
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
    playUiSound('error')
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

// Construye una tabla dinámica para mostrar historiales con formato consistente.
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
      td.dataset.label = col.label
      td.textContent = value != null ? value : '-'
      row.appendChild(td)
    })
    tbody.appendChild(row)
  })
  table.appendChild(tbody)
  container.appendChild(table)
}

function switchHistorySubtab(tab) {
  historyCurrentTab = 'bajas'
  const bajasEl = document.getElementById('history-bajas')
  if (bajasEl) bajasEl.style.display = 'block'
  loadHistoryBajas()
}

async function loadHistoryLogs() {
  switchHistorySubtab(historyCurrentTab)
}

const historyState = {
  bajas: { page: 1, limit: 10, pages: 1 }
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

// Consulta el catálogo y presenta únicamente los ejemplares disponibles.
async function doSearch(page = 1) {
  const searchInput = document.getElementById('searchInput')
  if (!searchInput) return
  const q = searchInput.value
  const container = document.getElementById('results')
  const pagination = document.getElementById('resultsPagination')
  if (!container) return
  
  try {
    const res = await fetch('/api/search?title=' + encodeURIComponent(q) + '&page=' + page + '&limit=' + searchState.limit, {
      headers: getAuthHeaders()
    })
    const data = await res.json()
    container.innerHTML = ''
    if (!res.ok) {
      container.textContent = data.detail || 'Error cargando catálogo.'
      playUiSound('error')
      return
    }
    if (!data.books || data.books.length === 0) {
      container.innerHTML = '<p>No se encontraron libros</p>'
      if (pagination) pagination.innerHTML = ''
      return
    }
    data.books.forEach(it => {
      const card = document.createElement('div')
      card.className = 'card'
      const details = document.createElement('div')
      details.style.flex = '1'
      const title = document.createElement('div')
      title.className = 'book-title'
      title.textContent = it.Titulo
      const author = document.createElement('p')
      author.textContent = `Autor: ${it.Autor || '--'}`
      const publisher = document.createElement('p')
      publisher.textContent = `Editorial: ${it.Editorial || '--'}`
      const stock = document.createElement('p')
      stock.className = 'book-stock'
      stock.textContent = `Total: ${it.Stock_Total} · Disponibles: ${it.Stock_Disponible}`
      details.append(title, author, publisher, stock)
      card.appendChild(document.createElement('div')).className = 'thumb'
      card.appendChild(details)
      container.appendChild(card)
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
    playUiSound('error')
  }
}

// Mantiene el estado de paginación de la tabla de usuarios para navegar entre páginas de perfiles.
const profilesState = { page: 1, limit: 10, pages: 1 }
let loanUsers = []
let loanBooks = []

function formatDateDisplay(value) {
  if (!value) return '—'
  const [year, month, day] = String(value).slice(0, 10).split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

async function loadProfile() {
  const panel = document.getElementById('profilePanel')
  const catalog = document.getElementById('catalogContent')
  if (!panel || !catalog) return
  if (authState.Tipo === 'Bibliotecario') {
    panel.style.display = 'none'
    catalog.style.display = 'block'
    return
  }
  panel.style.display = 'block'
  try {
    const res = await fetch('/api/profile', { headers: getAuthHeaders() })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'No se pudo consultar el perfil')
    const complete = data.complete === true
    document.getElementById('profileCourse').value = data.Curso ? String(data.Curso) : ''
    document.getElementById('profileDivision').value = data.Division ? String(data.Division) : ''
    document.getElementById('profilePrompt').textContent = complete
      ? 'Puedes actualizar estos datos cuando cambien.'
      : 'Completa ambos datos antes de acceder al catálogo.'
    catalog.style.display = complete ? 'block' : 'none'
    authState.Curso = data.Curso
    authState.Division = data.Division
  } catch (error) {
    catalog.style.display = 'none'
    const msg = document.getElementById('profileMsg')
    if (msg) {
      msg.textContent = error.message
      msg.style.color = 'red'
    }
  }
}

function setSelectOptions(select, options, placeholder) {
  if (!select) return
  select.replaceChildren()
  const first = document.createElement('option')
  first.value = ''
  first.textContent = placeholder
  select.appendChild(first)
  options.forEach(item => {
    const option = document.createElement('option')
    option.value = String(item.value)
    option.textContent = item.label
    if (item.disabled) option.disabled = true
    select.appendChild(option)
  })
}

function populateSchoolResponsible() {
  const mode = document.getElementById('schoolMode')?.value || 'Alumno'
  const requiredRole = mode === 'Alumno' ? 'Alumno' : 'Profesor'
  const users = loanUsers.filter(user => user.Tipo === requiredRole)
  setSelectOptions(
    document.getElementById('schoolResponsible'),
    users.map(user => ({
      value: user.ID_Usuario,
      label: `${user.Nombre_Completo} · ${user.Tipo}${user.Curso && user.Division ? ` · ${user.Curso}.º ${user.Division}.ª` : ' · perfil pendiente'}`,
    })),
    'Selecciona responsable'
  )
  const retireWrap = document.getElementById('schoolRetireWrap')
  if (retireWrap) retireWrap.style.display = mode === 'AlumnoPorProfesor' ? 'block' : 'none'
  const retire = document.getElementById('schoolRetire')
  setSelectOptions(
    retire,
    loanUsers.filter(user => user.Tipo === 'Alumno').map(user => ({
      value: user.ID_Usuario,
      label: user.Nombre_Completo,
    })),
    'Selecciona alumno'
  )
  document.getElementById('schoolCourse').value = ''
  document.getElementById('schoolDivision').value = ''
}

async function loadLoanFormOptions() {
  const msg = document.getElementById('adminLoansMsg')
  try {
    const [usersRes, booksRes] = await Promise.all([
      fetch('/api/loan-users', { headers: getAuthHeaders() }),
      fetch('/api/search?limit=1000', { headers: getAuthHeaders() }),
    ])
    const usersData = await usersRes.json()
    const booksData = await booksRes.json()
    if (!usersRes.ok) throw new Error(usersData.detail || 'No se pudieron cargar las cuentas')
    if (!booksRes.ok) throw new Error(booksData.detail || 'No se pudo cargar el catálogo')
    loanUsers = usersData
    loanBooks = booksData.books || []
    populateSchoolResponsible()
    setSelectOptions(
      document.getElementById('homeResponsible'),
      loanUsers.filter(user => user.Tipo === 'Profesor').map(user => ({
        value: user.ID_Usuario,
        label: `${user.Nombre_Completo}${user.Curso && user.Division ? ` · ${user.Curso}.º ${user.Division}.ª` : ' · perfil pendiente'}`,
      })),
      'Selecciona profesor'
    )
    const books = loanBooks.map(book => ({
      value: book.ID_Libro,
      label: `${book.Titulo} · ${book.Autor || 'Autor desconocido'} · disponibles: ${book.Stock_Disponible}`,
      disabled: Number(book.Stock_Disponible) <= 0,
    }))
    setSelectOptions(document.getElementById('schoolBook'), books, 'Selecciona un libro')
    setSelectOptions(document.getElementById('homeBook'), books, 'Selecciona un libro')
    setSelectOptions(
      document.getElementById('adminLoanBook'),
      loanBooks.map(book => ({ value: book.ID_Libro, label: book.Titulo })),
      'Todos los libros'
    )
    if (msg) msg.textContent = ''
  } catch (error) {
    console.error('Error cargando opciones de préstamos:', error)
    if (msg) {
      msg.textContent = error.message
      msg.style.color = 'red'
    }
  }
}

function makeLoanCard(loan, librarian) {
  const card = document.createElement('article')
  card.className = 'loan-card'
  const heading = document.createElement('h3')
  heading.textContent = `#${loan.ID_Prestamo} · ${loan.Tipo === 'escolar' ? 'Cuaderno Diario' : 'Ficha Domiciliaria'} · ${loan.Estado}`
  card.appendChild(heading)
  const details = [
    `Libro: ${loan.Libro}${loan.Autor ? ` · ${loan.Autor}` : ''}`,
    `Responsable: ${loan.Responsable}`,
    `Cantidad: ${loan.Cantidad}`,
    `Curso/división: ${loan.Curso}.º ${loan.Division}.ª`,
    `Préstamo: ${formatDateDisplay(loan.Fecha_Prestamo)}`,
    `Vencimiento: ${formatDateDisplay(loan.Fecha_Vencimiento)}`,
    `Devolución: ${formatDateDisplay(loan.Fecha_Devolucion)}`,
  ]
  if (loan.Retirado_Por) details.push(`Retiró: ${loan.Retirado_Por} (por cuenta del profesor)`)
  if (loan.Apellido || loan.Nombre_Ficha) details.push(`Ficha: ${loan.Apellido || ''} ${loan.Nombre_Ficha || ''} · DNI ${loan.DNI || '—'} · Tel. ${loan.Telefono || '—'} · ${loan.Dias} días`)
  details.forEach(detail => {
    const line = document.createElement('p')
    line.textContent = detail
    card.appendChild(line)
  })
  if (librarian && loan.Estado === 'Activo') {
    const returnButton = document.createElement('button')
    returnButton.type = 'button'
    returnButton.textContent = 'Registrar devolución total'
    returnButton.addEventListener('click', async () => {
      if (!confirm(`¿Confirmas la devolución total del préstamo #${loan.ID_Prestamo}?`)) return
      const response = await fetch(`/api/loans/${loan.Tipo}/${loan.ID_Prestamo}/return`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      const result = await response.json()
      const msg = document.getElementById('adminLoansMsg')
      if (!response.ok) {
        if (msg) {
          msg.textContent = result.detail || 'No se pudo registrar la devolución'
          msg.style.color = 'red'
        }
        return
      }
      if (msg) {
        msg.textContent = `Préstamo #${loan.ID_Prestamo} devuelto; se repusieron ${result.Cantidad_Repuesta} ejemplar(es).`
        msg.style.color = 'green'
      }
      await Promise.all([loadAdminLoans(), loadLoanFormOptions()])
      doSearch()
    })
    card.appendChild(returnButton)
  }
  return card
}

const adminLoanState = { page: 1, limit: 10, status: 'Activo' }
const myLoanState = { page: 1, limit: 10 }

async function fetchAndRenderLoans(url, containerId, paginationId, msgId, page, limit, librarian, state) {
  const container = document.getElementById(containerId)
  const pagination = document.getElementById(paginationId)
  const msg = document.getElementById(msgId)
  if (!container) return
  try {
    const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}page=${page}&limit=${limit}`, {
      headers: getAuthHeaders(),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'No se pudieron cargar los préstamos')
    container.replaceChildren()
    if (!data.prestamos.length) {
      container.textContent = 'No hay préstamos para mostrar.'
    } else {
      data.prestamos.forEach(loan => container.appendChild(makeLoanCard(loan, librarian)))
    }
    if (msg && msg.style.color !== 'green') msg.textContent = ''
    state.page = data.page
    if (pagination) {
      renderPagination(pagination, data.page, data.pages, nextPage => {
        if (librarian) loadAdminLoans(nextPage)
        else loadMyLoans(nextPage)
      })
    }
  } catch (error) {
    console.error('Error consultando préstamos:', error)
    container.textContent = ''
    if (msg) {
      msg.textContent = error.message
      msg.style.color = 'red'
    }
  }
}

function loadAdminLoans(page = 1) {
  const params = new URLSearchParams({
    tipo: document.getElementById('adminLoanType')?.value || 'todos',
    estado: adminLoanState.status,
    persona: document.getElementById('adminLoanPerson')?.value.trim() || '',
  })
  const bookId = document.getElementById('adminLoanBook')?.value
  const course = document.getElementById('adminLoanCourse')?.value
  const division = document.getElementById('adminLoanDivision')?.value
  if (bookId) params.set('libro_id', bookId)
  if (course) params.set('curso', course)
  if (division) params.set('division', division)
  return fetchAndRenderLoans(
    '/api/loans?' + params.toString(),
    'adminLoansContainer',
    'adminLoansPagination',
    'adminLoansMsg',
    page,
    adminLoanState.limit,
    true,
    adminLoanState
  )
}

function loadMyLoans(page = 1) {
  const params = new URLSearchParams({
    tipo: document.getElementById('myLoanType')?.value || 'todos',
    estado: document.getElementById('myLoanState')?.value || 'todos',
  })
  return fetchAndRenderLoans(
    '/api/my-loans?' + params.toString(),
    'myLoansContainer',
    'myLoansPagination',
    'myLoansMsg',
    page,
    myLoanState.limit,
    false,
    myLoanState
  )
}

function openBanDialog(user) {
  const dialog = document.getElementById('banDialog')
  const targetName = document.getElementById('banTargetName')
  const reason = document.getElementById('banReason')
  const duration = document.getElementById('banDuration')
  if (!dialog || !reason || !duration) return

  banTargetUserId = user.ID_Usuario
  if (targetName) targetName.textContent = `${user.Nombre_Completo} (${user.Gmail})`
  reason.value = user.Motivo_Veto || ''
  const remainingDays = user.Veto_Hasta
    ? Math.ceil((new Date(user.Veto_Hasta.replace(' ', 'T') + 'Z').getTime() - Date.now()) / 86400000)
    : 7
  duration.value = String(Math.min(365, Math.max(1, remainingDays)))
  dialog.showModal()
}

async function loadProfiles(page = 1, preserveMessage = false) {
  const container = document.getElementById('profilesContainer')
  const pagination = document.getElementById('profilesPagination')
  const msg = document.getElementById('profilesMsg')
  if (!container) return
  if (msg && !preserveMessage) msg.textContent = ''

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
    table.className = 'history-table profiles-table'
    table.style.width = '100%'

    const thead = document.createElement('thead')
    const headerRow = document.createElement('tr')
    const headers = ['Nombre', 'Gmail', 'Tipo', 'Curso / División', 'Clasificación', 'Actividad', 'Veto', 'Acciones']
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

      const courseCell = document.createElement('td')
      courseCell.textContent = user.Curso && user.Division
        ? `${user.Curso}.º ${user.Division}.ª`
        : 'Pendiente de completar'
      row.appendChild(courseCell)

      const classificationCell = document.createElement('td')
      if (user.Tipo === 'Alumno' && Number(user.Curso) === 6) {
        const classification = document.createElement('select')
        classification.className = 'profile-classification-select'
        classification.setAttribute('aria-label', `Clasificación de ${user.Nombre_Completo}`)
        classification.innerHTML = '<option value="false">No egresado</option><option value="true">Egresado</option>'
        classification.value = user.Es_Egresado ? 'true' : 'false'
        classification.addEventListener('change', async () => {
          classification.disabled = true
          await updateGraduatedStatus(user.ID_Usuario, classification.value === 'true')
          await loadProfiles(page, true)
        })
        classificationCell.appendChild(classification)
      } else if (user.Tipo === 'Alumno') {
        classificationCell.textContent = user.Es_Egresado ? 'Egresado' : 'No egresado'
      } else {
        classificationCell.textContent = '-'
      }
      row.appendChild(classificationCell)

      const activityCell = document.createElement('td')
      activityCell.textContent = user.Cuenta_Activa ? 'Activa' : 'Inactiva'
      row.appendChild(activityCell)

      const stateCell = document.createElement('td')
      stateCell.textContent = user.Estado || 'no vetado'
      if (user.Estado === 'vetado') {
        const banDetails = document.createElement('small')
        banDetails.className = 'ban-details'
        banDetails.textContent = `${user.Motivo_Veto || 'Sin motivo'} · hasta ${user.Veto_Hasta || 'indefinido'} UTC`
        stateCell.appendChild(document.createElement('br'))
        stateCell.appendChild(banDetails)
      }
      row.appendChild(stateCell)

      const actionCell = document.createElement('td')
      const actions = document.createElement('div')
      actions.className = 'profile-actions'
      if (user.Estado === 'vetado') {
        const unbanBtn = document.createElement('button')
        unbanBtn.type = 'button'
        unbanBtn.textContent = 'Desvetar'
        unbanBtn.addEventListener('click', async () => {
          if (await unbanUser(user.ID_Usuario)) loadProfiles(page, true)
        })
        actions.appendChild(unbanBtn)
      }
      if (!user.Es_Egresado) {
        const banBtn = document.createElement('button')
        banBtn.type = 'button'
        banBtn.textContent = user.Estado === 'vetado' ? 'Editar veto' : 'Vetar'
        banBtn.addEventListener('click', () => openBanDialog(user))
        actions.appendChild(banBtn)
      }

      if (user.Tipo === 'Alumno' && user.Es_Egresado) {
        const activationBtn = document.createElement('button')
        activationBtn.type = 'button'
        activationBtn.className = user.Cuenta_Activa ? 'danger-button' : ''
        activationBtn.textContent = user.Cuenta_Activa ? 'Inactivar egresado' : 'Reactivar cuenta'
        activationBtn.addEventListener('click', async () => {
          const nextActiveState = !user.Cuenta_Activa
          const confirmation = nextActiveState
            ? `¿Reactivar la cuenta de ${user.Nombre_Completo}?`
            : `¿Inactivar la cuenta de ${user.Nombre_Completo}? La cuenta y su historial se conservarán. Primero deben registrarse todas las devoluciones pendientes.`
          if (!confirm(confirmation)) return
          await updateAccountActivation(user.ID_Usuario, nextActiveState)
          await loadProfiles(page, true)
        })
        actions.appendChild(activationBtn)
      }
      actionCell.appendChild(actions)
      row.appendChild(actionCell)
      row.querySelectorAll('td').forEach((cell, index) => {
        cell.dataset.label = headers[index]
      })
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

async function updateGraduatedStatus(userId, isGraduated) {
  const msg = document.getElementById('profilesMsg')
  try {
    const res = await fetch('/api/users/' + userId + '/graduated-status', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ Es_Egresado: isGraduated })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Error')
    if (msg) {
      msg.textContent = 'Clasificación actualizada correctamente'
      msg.style.color = 'green'
    }
    return true
  } catch (error) {
    console.error('Error actualizando clasificación:', error)
    if (msg) {
      msg.textContent = 'No se pudo actualizar la clasificación: ' + error.message
      msg.style.color = 'red'
    }
    return false
  }
}

async function updateAccountActivation(userId, isActive) {
  const msg = document.getElementById('profilesMsg')
  try {
    const res = await fetch('/api/users/' + userId + '/activation', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ Cuenta_Activa: isActive })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Error')
    if (msg) {
      msg.textContent = isActive ? 'Cuenta reactivada correctamente' : 'Cuenta inactivada correctamente'
      msg.style.color = 'green'
    }
    return true
  } catch (error) {
    console.error('Error actualizando actividad de la cuenta:', error)
    if (msg) {
      msg.textContent = 'No se pudo actualizar la cuenta: ' + error.message
      msg.style.color = 'red'
    }
    return false
  }
}

async function banUser(userId, reason, durationDays) {
  const msg = document.getElementById('profilesMsg')
  try {
    const res = await fetch('/api/users/' + userId + '/state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ Estado: 'vetado', Motivo: reason, Duracion_Dias: durationDays })
    })
    const data = await res.json()
    if (!res.ok) {
      if (msg) {
        msg.textContent = 'Error vetando usuario: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
      return false
    }
    if (msg) {
      msg.textContent = 'Veto temporal actualizado correctamente'
      msg.style.color = 'green'
    }
    return true
  } catch (e) {
    console.error('Error vetando usuario:', e)
    if (msg) {
      msg.textContent = 'Error vetando usuario'
      msg.style.color = 'red'
    }
    return false
  }
}

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
      return true
    } else {
      if (msg) {
        msg.textContent = 'Error desvetando usuario: ' + (data.detail || 'Error')
        msg.style.color = 'red'
      }
      return false
    }
  } catch (e) {
    console.error('Error desvetando usuario:', e)
    if (msg) {
      msg.textContent = 'Error desvetando usuario'
      msg.style.color = 'red'
    }
    return false
  }
}

// Conecta formularios, botones y enlaces con las funciones de la interfaz para que respondan a la interacción del usuario.
function setupEventListeners() {
  // Vincula los controles HTML a las funciones de negocio del frontend.
  // Esto deja el DOM listo para responder a interacciones del usuario.

  const banForm = document.getElementById('banForm')
  const banDialog = document.getElementById('banDialog')
  const cancelBanBtn = document.getElementById('cancelBanBtn')
  if (banForm && banDialog) {
    banForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const reason = document.getElementById('banReason').value.trim()
      const duration = Number(document.getElementById('banDuration').value)
      if (!banTargetUserId) return
      if (await banUser(banTargetUserId, reason, duration)) {
        banDialog.close()
        banForm.reset()
        banTargetUserId = null
        loadProfiles(profilesState.page, true)
      }
    })
  }
  if (cancelBanBtn && banDialog) {
    cancelBanBtn.addEventListener('click', () => {
      banDialog.close()
      banTargetUserId = null
    })
  }
  if (banDialog) {
    banDialog.addEventListener('close', () => {
      banTargetUserId = null
    })
  }

  const profileForm = document.getElementById('profileForm')
  if (profileForm) {
    profileForm.addEventListener('submit', async event => {
      event.preventDefault()
      const payload = {
        Curso: Number(document.getElementById('profileCourse').value),
        Division: Number(document.getElementById('profileDivision').value),
      }
      const msg = document.getElementById('profileMsg')
      try {
        const response = await fetch('/api/profile', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify(payload),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'No se pudo guardar el perfil')
        authState.Curso = result.Curso
        authState.Division = result.Division
        if (msg) {
          msg.textContent = 'Curso y división guardados.'
          msg.style.color = 'green'
        }
        await loadProfile()
        doSearch()
      } catch (error) {
        if (msg) {
          msg.textContent = error.message
          msg.style.color = 'red'
        }
      }
    })
  }

  const schoolMode = document.getElementById('schoolMode')
  if (schoolMode) schoolMode.addEventListener('change', populateSchoolResponsible)
  const schoolResponsible = document.getElementById('schoolResponsible')
  if (schoolResponsible) {
    schoolResponsible.addEventListener('change', () => {
      const selected = loanUsers.find(user => String(user.ID_Usuario) === schoolResponsible.value)
      document.getElementById('schoolCourse').value = selected?.Curso ? String(selected.Curso) : ''
      document.getElementById('schoolDivision').value = selected?.Division ? String(selected.Division) : ''
    })
  }

  const schoolLoanForm = document.getElementById('schoolLoanForm')
  if (schoolLoanForm) {
    schoolLoanForm.addEventListener('submit', async event => {
      event.preventDefault()
      const formData = Object.fromEntries(new FormData(schoolLoanForm).entries())
      const payload = {
        ...formData,
        ID_Libro: Number(formData.ID_Libro),
        ID_Responsable: Number(formData.ID_Responsable),
        ID_Retira: formData.ID_Retira ? Number(formData.ID_Retira) : null,
        Cantidad: Number(formData.Cantidad),
        Curso: Number(formData.Curso),
        Division: Number(formData.Division),
      }
      const msg = document.getElementById('schoolLoanMsg')
      try {
        const response = await fetch('/api/loans/school', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify(payload),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'No se pudo registrar el préstamo')
        if (msg) {
          msg.textContent = `Cuaderno Diario #${result.ID_Prestamo} registrado. Vence ${formatDateDisplay(result.Fecha_Vencimiento)}.`
          msg.style.color = 'green'
        }
        schoolLoanForm.reset()
        populateSchoolResponsible()
        await Promise.all([loadAdminLoans(), loadLoanFormOptions()])
        doSearch()
      } catch (error) {
        if (msg) {
          msg.textContent = error.message
          msg.style.color = 'red'
        }
      }
    })
  }

  const homeLoanForm = document.getElementById('homeLoanForm')
  if (homeLoanForm) {
    homeLoanForm.addEventListener('submit', async event => {
      event.preventDefault()
      const formData = Object.fromEntries(new FormData(homeLoanForm).entries())
      const payload = {
        ...formData,
        ID_Libro: Number(formData.ID_Libro),
        ID_Responsable: Number(formData.ID_Responsable),
        Cantidad: Number(formData.Cantidad),
        Dias: Number(formData.Dias),
      }
      const msg = document.getElementById('homeLoanMsg')
      try {
        const response = await fetch('/api/loans/home', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify(payload),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'No se pudo registrar el préstamo')
        if (msg) {
          msg.textContent = `Ficha Domiciliaria #${result.ID_Prestamo} registrada. Vence ${formatDateDisplay(result.Fecha_Vencimiento)}.`
          msg.style.color = 'green'
        }
        homeLoanForm.reset()
        await Promise.all([loadAdminLoans(), loadLoanFormOptions()])
        doSearch()
      } catch (error) {
        if (msg) {
          msg.textContent = error.message
          msg.style.color = 'red'
        }
      }
    })
  }

  document.querySelectorAll('.loan-tab-btn').forEach(button => {
    button.addEventListener('click', () => {
      const school = button.getAttribute('data-tab') === 'school'
      document.getElementById('schoolLoanPanel').style.display = school ? 'block' : 'none'
      document.getElementById('homeLoanPanel').style.display = school ? 'none' : 'block'
      document.querySelectorAll('.loan-tab-btn').forEach(tab => tab.classList.toggle('active', tab === button))
    })
    document.querySelectorAll('.loan-state-tab-btn').forEach(button => {
      button.addEventListener('click', () => {
        adminLoanState.status = button.getAttribute('data-state')
        document.querySelectorAll('.loan-state-tab-btn').forEach(tab => tab.classList.toggle('active', tab === button))
        loadAdminLoans(1)
      })
    })
  })
  document.getElementById('adminLoansFilter')?.addEventListener('click', () => loadAdminLoans(1))
  document.getElementById('myLoansRefresh')?.addEventListener('click', () => loadMyLoans(1))

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
        authState.Curso = j.Curso
        authState.Division = j.Division
        updateUIBasedOnAuth()
        if (msg) msg.textContent = ''
        playUiSound('success')
        e.target.reset()
        showView('home')
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
        authState.Curso = j.Curso || null
        authState.Division = j.Division || null
        updateUIBasedOnAuth()
        if (msg) {
          msg.textContent = 'Cuenta creada exitosamente'
          msg.style.color = 'green'
        }
        e.target.reset()
        switchAuthTab('login')
        setTimeout(() => showView('home'), 1000)
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

  // Los eventos quedan listos para la interacción del usuario.
}

function setupNavigation() {
  // Se definen las rutas visibles dentro de la app.
  const navMore = document.getElementById('navMore')
  const navMoreToggle = document.getElementById('navMoreToggle')
  if (navMore && navMoreToggle) {
    navMoreToggle.addEventListener('click', () => {
      const isOpen = navMore.classList.toggle('is-open')
      navMoreToggle.setAttribute('aria-expanded', String(isOpen))
    })
    document.addEventListener('click', event => {
      if (event.target instanceof Node && !navMore.contains(event.target)) {
        navMore.classList.remove('is-open')
        navMoreToggle.setAttribute('aria-expanded', 'false')
      }
    })
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && navMore.classList.contains('is-open')) {
        navMore.classList.remove('is-open')
        navMoreToggle.setAttribute('aria-expanded', 'false')
        navMoreToggle.focus()
      }
    })
  }
  document.querySelectorAll('.nav-item[data-view]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault()
      const view = a.getAttribute('data-view')
      if (view !== 'account' && !authState.isAuthenticated) {
        alert('Debes iniciar sesión o crear una cuenta primero')
        showView('account')
        return
      }
      if (navMore?.contains(a)) {
        navMore.classList.remove('is-open')
        navMoreToggle?.setAttribute('aria-expanded', 'false')
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
  setupInteractionSounds()
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
