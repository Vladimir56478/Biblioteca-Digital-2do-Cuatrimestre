async function fetchAuthors(){
  const res = await fetch('/api/authors')
  const authors = await res.json()
  const sel = document.getElementById('authorSelect')
  authors.forEach(a=>{
    const opt = document.createElement('option')
    opt.value = a.ID_Autor
    opt.textContent = a.Nombre
    sel.appendChild(opt)
  })
}

async function doSearch(){
  const q = document.getElementById('searchInput').value
  const res = await fetch('/api/search?title=' + encodeURIComponent(q))
  const items = await res.json()
  const container = document.getElementById('results')
  container.innerHTML = ''
  if(items.length===0){container.innerHTML='<p>No se encontraron libros</p>';return}
  items.forEach(it=>{
    const card = document.createElement('div'); card.className='card'
    card.innerHTML = `<h3>${it.Titulo}</h3><p><strong>Autor:</strong> ${it.Autor||'--'}</p><p><strong>Editorial:</strong> ${it.Editorial||'--'}</p><p><strong>Stock:</strong> ${it.Stock}</p>`
    container.appendChild(card)
  })
}

document.getElementById('searchBtn').addEventListener('click', doSearch)
document.getElementById('searchInput').addEventListener('keyup', (e)=>{ if(e.key==='Enter') doSearch() })

document.getElementById('bookForm').addEventListener('submit', async (e)=>{
  e.preventDefault()
  const form = e.target
  const data = Object.fromEntries(new FormData(form).entries())
  // convert numeric fields
  if(data.ID_Autor==='') data.ID_Autor = null
  if(data.Año_Publicacion==='') data.Año_Publicacion = null
  data.Stock = Number(data.Stock||0)
  const res = await fetch('/api/books', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
  const j = await res.json()
  const msg = document.getElementById('bookMsg')
  if(res.ok) msg.textContent = 'Libro creado con ID ' + (j.inserted || '')
  else msg.textContent = 'Error: ' + (j.detail||JSON.stringify(j))
  form.reset()
})

document.getElementById('reserveForm').addEventListener('submit', async (e)=>{
  e.preventDefault()
  const data = Object.fromEntries(new FormData(e.target).entries())
  data.ID_Libro = Number(data.ID_Libro)
  data.ID_Usuario = Number(data.ID_Usuario)
  data.Cantidad = Number(data.Cantidad)
  const res = await fetch('/api/reserve', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
  const j = await res.json()
  const msg = document.getElementById('reserveMsg')
  if(res.ok) msg.textContent = 'Reserva creada: ' + j.Codigo_reserva
  else msg.textContent = 'Error: ' + (j.detail||JSON.stringify(j))
  e.target.reset()
})

// Init
fetchAuthors()
doSearch()

// Login handling
document.getElementById('loginForm').addEventListener('submit', async (e)=>{
  e.preventDefault()
  const data = Object.fromEntries(new FormData(e.target).entries())
  const res = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})
  const j = await res.json()
  const msg = document.getElementById('loginMsg')
  const welcome = document.getElementById('welcome')
  if(res.ok){
    msg.textContent = ''
    welcome.style.display = 'block'
    welcome.textContent = `¡Hola, ${j.Nombre_Completo}! (${j.Tipo})`;
    // hide login form
    e.target.style.display = 'none'
  } else {
    msg.textContent = 'Error: ' + (j.detail || JSON.stringify(j))
  }
})

// Simple view router for mobile nav
document.querySelectorAll('.nav-item').forEach(a=>{
  a.addEventListener('click', (e)=>{
    e.preventDefault()
    const view = a.getAttribute('data-view')
    document.getElementById('view-home').style.display = 'none'
    document.getElementById('view-admin').style.display = 'none'
    document.getElementById('view-reserve').style.display = 'none'
    document.getElementById('view-login').style.display = 'none'
    if(view === 'home') document.getElementById('view-home').style.display = 'block'
    if(view === 'admin') document.getElementById('view-admin').style.display = 'block'
    if(view === 'reserve') document.getElementById('view-reserve').style.display = 'block'
  })
})

// Ensure initial view
document.getElementById('view-login').style.display = 'block'
