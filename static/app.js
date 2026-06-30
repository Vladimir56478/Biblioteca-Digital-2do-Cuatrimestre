// Global state
let authState = {
  isAuthenticated: false,
  ID_Usuario: null,
  Nombre_Completo: null,
  Tipo: null
}

console.log('[APP] Script loaded')

// Load auth state from localStorage
function loadAuthState() {
  console.log('[AUTH] Loading auth state')
  const stored = localStorage.getItem('authState')
  if (stored) {
    authState = JSON.parse(stored)
  }
  console.log('[AUTH] Auth state loaded:', authState.isAuthenticated)
  updateUIBasedOnAuth()
}

// Save auth state to localStorage
function saveAuthState() {
  localStorage.setItem('authState', JSON.stringify(authState))
}

function getAuthHeaders(extra = {}) {
  const headers = { ...extra }
  if (authState.ID_Usuario) headers['X-User-Id'] = String(authState.ID_Usuario)
  if (authState.Tipo) headers['X-User-Type'] = authState.Tipo
  return headers
}

// Logout
function logout() {
  authState = { isAuthenticated: false, ID_Usuario: null, Nombre_Completo: null, Tipo: null }
  localStorage.removeItem('authState')
  updateUIBasedOnAuth()
  showView('account')
}

// Update UI visibility based on auth state
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

// Show/hide view
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
  } catch (e) {
    console.error('Error in showView:', e)
  }
}

// Fetch authors for select
async function fetchAuthors() {
  try {
    const res = await fetch('/api/authors')
    const authors = await res.json()
    const sel = document.getElementById('authorSelect')
    if (sel) {
      authors.forEach(a => {
        const opt = document.createElement('option')
        opt.value = a.ID_Autor
        opt.textContent = a.Nombre
        sel.appendChild(opt)
      })
    }
  } catch (e) {
    console.error('Error fetching authors:', e)
  }
}

// Search books and display with ID
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
          <div style="font-weight:700; color:var(--accent); margin-bottom:4px"><span style="font-size:12px; background:#e8e8e8; padding:2px 6px; border-radius:4px;">#${it.ID_Libro}</span> ${it.Titulo}</div>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Autor:</strong> ${it.Autor || '--'}</p>
          <p style="margin:0; color:#444; font-size:13px;"><strong>Editorial:</strong> ${it.Editorial || '--'}</p>
          <p style="margin:0; color:#0b5a52; font-weight:700;">Stock: ${it.Stock}</p>
        </div>
      `
      container.appendChild(card)
    })
  } catch (e) {
    console.error('Error searching:', e)
  }
}

// Setup all event listeners
function setupEventListeners() {
  console.log('[EVENTS] Setting up event listeners')

  // Login
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

  // Signup
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

  // Auth tabs
  const authTabs = document.querySelectorAll('.auth-tab')
  authTabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      e.preventDefault()
      switchAuthTab(tab.getAttribute('data-tab'))
    })
  })

  // Search
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

  // Book form
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

  // Reserve form
  const reserveForm = document.getElementById('reserveForm')
  if (reserveForm) {
    reserveForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      const formData = Object.fromEntries(new FormData(e.target).entries())
      const data = {
        ID_Libro: Number(formData.ID_Libro),
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
      } else {
        if (msg) {
          msg.textContent = 'Error: ' + (j.detail || 'Error')
          msg.style.color = 'red'
        }
      }
      e.target.reset()
    })
  }

  console.log('[EVENTS] Event listeners setup complete')
}

// Navigation
function setupNavigation() {
  console.log('[NAV] Setting up navigation')
  const navItems = document.querySelectorAll('.nav-item')
  console.log('[NAV] Nav items found:', navItems.length)
  navItems.forEach(a => {
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
  console.log('[NAV] Navigation setup complete')
}

// Init function to setup all event listeners
function initializeApp() {
  console.log('[INIT] Initializing app')
  setupEventListeners()
  setupNavigation()
  loadAuthState()
  fetchAuthors()
  console.log('[INIT] App initialized')
}

// Wait for DOM to be ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp)
} else {
  // DOM is already loaded (e.g., if script is loaded async)
  initializeApp()
}

// Also try to setup immediately if elements exist
try {
  console.log('[APP] Attempting immediate setup...')
  const signupForm = document.getElementById('signupForm')
  if (signupForm && !signupForm.__setupDone) {
    console.log('[APP] Setting up signup form immediately')
    signupForm.__setupDone = true
    signupForm.addEventListener('submit', async (e) => {
      e.preventDefault()
      console.log('[SIGNUP] Form submitted')
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
  console.error('[APP] Error in immediate setup:', e)
}

console.log('[APP] Setup complete, waiting for DOM...')

// Add global form submit interceptor


console.log('[APP] Global form interceptor added')


