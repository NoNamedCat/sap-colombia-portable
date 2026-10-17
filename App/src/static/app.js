console.log("app.js loaded");
let productosList = [];
let clientesList = [];
let lineas = [];
let facturasList = [];
let notasCreditoList = [];
let carteraData = null;
let dsLineas = [];
let currentUser = null;
let userPermissions = [];

const formatCOP = (val) => {
  const num = parseFloat(val) || 0;
  return "COP " + num.toLocaleString("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

// Escapado de HTML. Todo valor proveniente del servidor (razones sociales,
// descripciones, NITs, códigos de producto, mensajes de error) se inyecta en
// el DOM mediante esc(); sin esto, un "<img onerror=...>" en una razón social
// ejecutaba JavaScript y, con el JWT en localStorage, equivalía a robo de sesión.
const esc = (val) => {
  if (val === null || val === undefined) return "";
  return String(val)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
};

// Marca un fragmento como HTML ya confiable (solo para markup generado por el
// propio cliente, nunca para datos del servidor).
const raw = (html) => html;

// ============ TOAST NOTIFICATIONS ============
function showToast(message, type = "info", duration = 4000) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const icons = {
    success: "✓",
    error: "✕",
    warning: "⚠",
    info: "ℹ"
  };

  const toast = document.createElement("div");
  toast.className = `sap-toast sap-toast-${esc(type)}`;
  toast.innerHTML = `
    <div class="toast-icon">${icons[type] || "ℹ"}</div>
    <div class="toast-content">${esc(message)}</div>
    <button class="toast-close" type="button" aria-label="Cerrar">×</button>
  `;

  const closeBtn = toast.querySelector(".toast-close");
  closeBtn.onclick = () => {
    toast.classList.add("fade-out");
    setTimeout(() => toast.remove(), 250);
  };

  container.appendChild(toast);

  setTimeout(() => {
    if (toast.parentElement) {
      toast.classList.add("fade-out");
      setTimeout(() => toast.remove(), 250);
    }
  }, duration);
}

// ============ AUTH ============

function getToken() {
  return localStorage.getItem("sap_token");
}

function setToken(token) {
  if (!token || token === "undefined" || token === "null") {
    clearToken();
    return;
  }
  localStorage.setItem("sap_token", token);
  document.cookie = `sap_token=${encodeURIComponent(token)}; path=/; SameSite=Strict`;
}

function clearToken() {
  localStorage.removeItem("sap_token");
  document.cookie = "sap_token=; path=/; max-age=0; SameSite=Strict";
}

function getAuthHeaders() {
  const token = getToken();
  const headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  const activeEmpId = localStorage.getItem("sap_empresa_activa_id");
  if (activeEmpId) headers["X-Empresa-Id"] = activeEmpId;
  return headers;
}

async function apiFetch(url, options = {}) {
  const headers = { ...getAuthHeaders(), ...(options.headers || {}) };
  if (options.body && options.body.constructor !== FormData) {
    headers["Content-Type"] = "application/json";
  }
  return fetch(url, { ...options, headers });
}

async function downloadWithAuth(url, fallbackFilename = "descarga", evt = null) {
  if (evt && typeof evt.preventDefault === "function") {
    evt.preventDefault();
  }
  try {
    const res = await apiFetch(url);
    if (!res.ok) {
      let msg = `Error HTTP ${res.status}`;
      try {
        const err = await res.json();
        if (err && err.error) msg = err.error;
      } catch (_) {}
      showToast("Error al descargar: " + msg, "error");
      return false;
    }
    const blob = await res.blob();
    let filename = fallbackFilename;
    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="?([^";]+)"?/i);
    if (match && match[1]) {
      filename = match[1];
    }
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
  } catch (err) {
    showToast("Error de red al descargar: " + err.message, "error");
  }
  return false;
}
window.downloadWithAuth = downloadWithAuth;

function showLogin() {
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("main-header").style.display = "none";
  document.querySelector(".sap-tabs").style.display = "none";
  document.querySelector(".main-container").style.display = "none";
}

function hideLogin() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("main-header").style.display = "";
  document.querySelector(".sap-tabs").style.display = "";
  document.querySelector(".main-container").style.display = "";
}

async function handleLogin(e) {
  e.preventDefault();
  const usuario = document.getElementById("login-usuario").value.trim();
  const password = document.getElementById("login-password").value;
  const totpGroup = document.getElementById("login-totp-group");
  const totpInput = document.getElementById("login-totp");
  const totpCode = totpInput ? totpInput.value.trim() : "";
  const errorEl = document.getElementById("login-error");

  try {
    const loginPayload = { email: usuario, password };
    if (totpCode) {
      loginPayload.totp_code = totpCode;
    }
    const res = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(loginPayload)
    });
    const data = await res.json();

    if (!res.ok) {
      errorEl.textContent = data.error || "Credenciales inválidas";
      errorEl.style.display = "block";
      return;
    }

    if (data.requiere_2fa) {
      if (totpGroup) totpGroup.style.display = "block";
      if (totpInput) totpInput.focus();
      errorEl.textContent = data.mensaje || "Ingrese su código de verificación 2FA / TOTP";
      errorEl.style.display = "block";
      return;
    }

    setToken(data.token);
    errorEl.style.display = "none";
    document.getElementById("login-password").value = "";
    if (totpInput) totpInput.value = "";
    if (totpGroup) totpGroup.style.display = "none";
    await loadCurrentUser();
    hideLogin();
    if (data.password_changed_at === null || data.password_changed_at === undefined) {
      showForceChange();
    } else {
      await startApp();
    }
  } catch (err) {
    errorEl.textContent = "Fallo en la comunicación con el servidor.";
    errorEl.style.display = "block";
  }
}

function showForceChange() {
  document.getElementById("force-change-screen").style.display = "flex";
}

function hideForceChange() {
  document.getElementById("force-change-screen").style.display = "none";
}

async function handleForceChange(e) {
  e.preventDefault();
  const pwd = document.getElementById("fc-password").value;
  const pwd2 = document.getElementById("fc-password-confirm").value;
  const email = currentUser.email;
  const errorEl = document.getElementById("force-change-error");
  if (pwd !== pwd2) {
    errorEl.textContent = "Las contraseñas no coinciden.";
    errorEl.style.display = "block";
    return;
  }
  try {
    const res = await apiFetch("/api/usuarios/cambiar-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario_id: currentUser.id, password: pwd })
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      errorEl.textContent = data.error || "No se pudo cambiar la contraseña.";
      errorEl.style.display = "block";
      return;
    }
    clearToken();
    const loginRes = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: pwd })
    });
    const loginData = await loginRes.json();
    if (!loginRes.ok) {
      showLogin();
      return;
    }
    setToken(loginData.token);
    await loadCurrentUser();
    errorEl.style.display = "none";
    document.getElementById("fc-password").value = "";
    document.getElementById("fc-password-confirm").value = "";
    hideForceChange();
    hideLogin();
    document.getElementById("user-badge").textContent = `${esc(currentUser.nombre)} (${esc(currentUser.rol)})`;
    applyPermissions();
    await startApp();
  } catch (err) {
    errorEl.textContent = "Fallo en la comunicación con el servidor.";
    errorEl.style.display = "block";
  }
}

function handleLogout() {
  clearToken();
  currentUser = null;
  userPermissions = [];
  showLogin();
}

async function loadPeriodoContexto() {
  const badge = document.getElementById("periodo-status-badge");
  if (!badge) return;
  try {
    const res = await apiFetch("/api/sistema/periodo-contexto");
    if (!res.ok) return;
    const data = await res.json();
    badge.style.display = "inline-block";
    badge.className = "badge " + (data.abierto ? "periodo-abierto" : "periodo-cerrado");
    badge.textContent = `${data.abierto ? "📅" : "🔒"} ${data.periodo} (${data.abierto ? "Abierto" : "Cerrado"})`;
    badge.title = data.mensaje || `Periodo Fiscal ${data.periodo}`;
  } catch (e) {
    console.warn("No se pudo cargar el periodo contable:", e);
  }
}

async function loadCurrentUser() {
  try {
    const res = await apiFetch("/api/auth/me");
    if (res.status === 401) {
      clearToken();
      showLogin();
      return;
    }
    const data = await res.json();
    currentUser = data;
    userPermissions = data.permisos || [];

    if (data.password_changed_at === null || data.password_changed_at === undefined) {
      hideLogin();
      showForceChange();
      return;
    }

    document.getElementById("user-badge").textContent = `${esc(data.nombre)} (${esc(data.rol)})`;
    setupTenantSwitcher(data);
    setupModoSistema(data);
    applyPermissions();
    await loadPeriodoContexto();
    hideLogin();
  } catch (err) {
    console.error("Error cargando sesión:", err);
    clearToken();
    showLogin();
  }
}

let currentModoSistema = false;

function setupTenantSwitcher(userData) {
  const select = document.getElementById("select-empresa-activa");
  const container = document.getElementById("tenant-switcher-container");
  if (!select || !container) return;

  const empresas = userData.empresas_autorizadas || [];
  select.innerHTML = "";

  if (empresas.length === 0) {
    select.innerHTML = '<option value="">(Sin empresa)</option>';
    select.disabled = true;
    return;
  }
  select.disabled = false;

  empresas.forEach(emp => {
    const opt = document.createElement("option");
    opt.value = emp.id;
    opt.textContent = `${emp.razon_social} (NIT: ${emp.nit})`;
    select.appendChild(opt);
  });

  const savedEmpId = localStorage.getItem("sap_empresa_activa_id");
  const currentEmpId = savedEmpId || userData.empresa_activa_id || (empresas[0] ? empresas[0].id : "");
  if (currentEmpId) {
    select.value = String(currentEmpId);
    localStorage.setItem("sap_empresa_activa_id", currentEmpId);
  }

  select.onchange = onEmpresaActivaChange;
}

async function onEmpresaActivaChange(e) {
  const nuevaEmpresaId = e.target.value;
  if (!nuevaEmpresaId) return;
  try {
    const res = await apiFetch("/api/auth/seleccionar-empresa", {
      method: "POST",
      body: JSON.stringify({ empresa_id: parseInt(nuevaEmpresaId) })
    });
    if (res.ok) {
      const data = await res.json();
      if (data.token) setToken(data.token);
      localStorage.setItem("sap_empresa_activa_id", nuevaEmpresaId);
      showToast("Empresa activa: " + e.target.options[e.target.selectedIndex].text, "success");
      await loadEmpresa();
      const activeTabBtn = document.querySelector(".tab-btn.active");
      const activeTab = activeTabBtn ? activeTabBtn.dataset.tab : "dashboard";
      loadDataForTab(activeTab);
    } else {
      showToast("Error al seleccionar empresa", "error");
    }
  } catch (err) {
    showToast("Error de conexión al cambiar de empresa", "error");
  }
}

function setupModoSistema(userData) {
  const btnToggle = document.getElementById("btn-toggle-modo-sistema");
  if (!btnToggle) return;

  if (userData.es_admin_sistema) {
    btnToggle.style.display = "inline-block";
    btnToggle.onclick = toggleModoSistema;
    updateModoSistemaUI();
  } else {
    btnToggle.style.display = "none";
    currentModoSistema = false;
    updateModoSistemaUI();
  }
}

function toggleModoSistema() {
  currentModoSistema = !currentModoSistema;
  updateModoSistemaUI();
  if (currentModoSistema) {
    switchTab("admin");
    showToast("Activada Consola de Sistema / Plataforma", "info");
  } else {
    switchTab("dashboard");
    showToast("Activada Vista Operativa de Empresa", "info");
  }
}

function updateModoSistemaUI() {
  const btnToggle = document.getElementById("btn-toggle-modo-sistema");
  const labelToggle = document.getElementById("label-modo-sistema");
  const grpVentas = document.getElementById("group-ventas");
  const grpCompras = document.getElementById("group-compras");
  const grpSistema = document.getElementById("group-sistema");
  const headerTitle = document.getElementById("header-main-title");

  if (!btnToggle) return;

  if (currentModoSistema) {
    if (labelToggle) labelToggle.textContent = "🏢 Vista Operativa Empresa";
    btnToggle.style.background = "#2b6cb0";
    if (headerTitle) headerTitle.textContent = "Consola de Plataforma & Sistema (Multi-Empresa)";
    if (grpVentas) grpVentas.style.display = "none";
    if (grpCompras) grpCompras.style.display = "none";
    if (grpSistema) {
      grpSistema.querySelectorAll(".tab-btn").forEach(btn => {
        btn.style.display = (btn.dataset.tab === "admin") ? "" : "none";
      });
    }
  } else {
    if (labelToggle) labelToggle.textContent = "⚙️ Consola Sistema";
    btnToggle.style.background = "#3182ce";
    if (headerTitle) headerTitle.textContent = "Facturación Electrónica DIAN (UBL 2.1)";
    if (grpVentas) grpVentas.style.display = "";
    if (grpCompras) grpCompras.style.display = "";
    if (grpSistema) {
      grpSistema.querySelectorAll(".tab-btn").forEach(btn => {
        btn.style.display = "";
      });
    }
    applyPermissions();
  }
}

// Maps tabs to permission keys
const TAB_PERMS = {
  dashboard: ["dashboard:read"],
  facturacion: ["facturacion:read", "facturacion:create"],
  "notas-credito": ["notas_credito:read", "notas_credito:create"],
  "notas-debito": ["notas_debito:read", "notas_debito:create"],
  cartera: ["cartera:read", "cartera:create"],
  "ciclo-comercial": ["ventas:read", "ventas:create", "facturacion:read"],
  pos: ["pos:read", "pos:create", "facturacion:read"],
  "documento-soporte": ["documento_soporte:read", "documento_soporte:create"],
  "compras-cxp": ["compras:read", "compras:create", "cxp:read", "cxp:create"],
  contabilidad: ["contabilidad:read", "contabilidad:create"],
  impuestos: ["impuestos:read", "contabilidad:read"],
  precios: ["precios:read", "precios:create", "inventario:read"],
  nomina: ["nominas:read", "nominas:create"],
  importaciones: ["importaciones:read"],
  admin: ["empresas:read"]
};

const READ_ONLY_ACTION_SELECTORS = {
  facturacion: ["#btn-emitir", "#btn-guardar-factura", "#btn-liquidar", "form#factura-form button[type='submit']"],
  notas_credito: ["#btn-emitir-nc", "form#form-nota-credito button[type='submit']"],
  notas_debito: ["#btn-emitir-nd", "form#form-nota-debito button[type='submit']"],
  cartera: ["#btn-recaudo", "form#form-recaudo button[type='submit']"],
  ventas: ["#btn-guardar-cotizacion", "form#form-cotizacion button[type='submit']"],
  compras: ["#btn-procesar-compra", "#btn-emitir-radian"],
  cxp: ["#btn-guardar-egreso", "form#form-egreso button[type='submit']"],
  contabilidad: ["#btn-guardar-asiento", "#btn-cerrar-periodo"],
  nominas: ["#btn-liquidar-nomina", "#btn-emitir-nomina", "#btn-pagar-nomina"]
};

function applyPermissions() {
  const isAdmin = currentUser && (["ADMIN", "SUPERADMIN"].includes(currentUser.rol) || userPermissions.includes("*"));
  document.querySelectorAll(".tab-btn").forEach(btn => {
    const tabId = btn.dataset.tab;
    if (isAdmin) {
      btn.style.display = "";
      return;
    }
    const perms = TAB_PERMS[tabId] || [];
    const hasPermission = perms.some(p => userPermissions.includes(p));
    btn.style.display = hasPermission ? "" : "none";
    if (!hasPermission) {
      const tabEl = document.getElementById(`tab-${esc(tabId)}`);
      if (tabEl) tabEl.classList.remove("active");
    }
  });

  // Tri-State Read-Only Action Locking
  const tri = currentUser?.permisos_tri_estado || {};
  Object.entries(READ_ONLY_ACTION_SELECTORS).forEach(([recurso, selectors]) => {
    const estado = isAdmin ? "FULL" : (tri[recurso] || "NONE");
    const isReadOnly = (estado === "READ_ONLY");
    selectors.forEach(sel => {
      document.querySelectorAll(sel).forEach(el => {
        if (isReadOnly) {
          el.disabled = true;
          el.classList.add("btn-read-only-locked");
          el.title = `🔒 Solo Lectura: Requiere permisos de modificación (${recurso}:create)`;
        } else if (isAdmin || estado === "FULL") {
          el.classList.remove("btn-read-only-locked");
          if (el.title && el.title.startsWith("🔒")) {
            el.removeAttribute("title");
          }
        }
      });
    });
  });
}

// ============ TAB NAVIGATION ============

const TAB_BREADCRUMBS = {
  dashboard: "Resumen › Dashboard Gerencial",
  facturacion: "Comercial & Ventas › Facturación Electrónica DIAN",
  pos: "Comercial & Ventas › Punto de Venta POS",
  "ciclo-comercial": "Comercial & Ventas › Ciclo Comercial (Cotizaciones & Pedidos)",
  cartera: "Comercial & Ventas › Cartera & Recibos de Caja",
  "notas-credito": "Comercial & Ventas › Notas Crédito Electrónicas",
  "notas-debito": "Comercial & Ventas › Notas Débito Electrónicas",
  "compras-cxp": "Compras & CxP › Buzón RADIAN & Cuentas por Pagar",
  "documento-soporte": "Compras & CxP › Documento Soporte DIAN",
  contabilidad: "Finanzas & NIIF › Contabilidad, Estados Financieros & Kárdex",
  impuestos: "Finanzas & NIIF › Impuestos & Medios Magnéticos Exógena",
  nomina: "Talento Humano › Nómina Electrónica DIAN",
  precios: "Comercial & Ventas › Listas de Precios & Tarifarios",
  importaciones: "Plataforma › Importación Masiva Excel / CSV",
  admin: "Plataforma › Gobierno & Administración Corporativa"
};

function switchTab(tabId) {
  console.log("switchTab called with:", tabId);
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
  const targetTab = document.getElementById(`tab-${esc(tabId)}`);
  if (targetTab) targetTab.classList.add("active");
  const targetBtn = document.querySelector(`.tab-btn[data-tab="${esc(tabId)}"]`);
  if (targetBtn) targetBtn.classList.add("active");
  const bcEl = document.getElementById("header-breadcrumb");
  if (bcEl) {
    bcEl.textContent = TAB_BREADCRUMBS[tabId] || `Módulo › ${tabId}`;
  }
  loadDataForTab(tabId);
}

function loadDataForTab(tabId) {
  switch(tabId) {
    case "dashboard":
      loadDashboard();
      break;
    case "facturacion":
      loadHistorial();
      break;
    case "notas-credito":
      loadNotasCredito();
      loadFacturasForNC();
      break;
    case "notas-debito":
      loadNotasDebito();
      loadFacturasForND();
      break;
    case "cartera":
      loadCartera();
      break;
    case "ciclo-comercial":
      loadCicloComercial();
      break;
    case "pos":
      loadPosData();
      break;
    case "documento-soporte":
      loadDocumentosSoporte();
      break;
    case "compras-cxp":
      loadComprasCxp();
      break;
    case "contabilidad":
      loadBalance();
      loadCuentasPUC();
      loadAsientos();
      loadKardex();
      break;
    case "impuestos":
      loadImpuestosTab();
      break;
    case "precios":
      loadPreciosTab();
      break;
    case "nomina":
      loadEmpleados();
      loadNominasHistorial();
      switchNominaTab("empleados");
      break;
    case "importaciones":
      // No data to load, UI is static
      break;
    case "admin":
      loadAdminData();
      load2faStatus();
      break;
  }
}

function exportarCartera() {
  downloadWithAuth("/api/reportes/cartera/exportar?formato=csv", "cartera.csv");
}

function exportarAsientos() {
  downloadWithAuth("/api/reportes/libro-diario/exportar?formato=csv", "libro_diario.csv");
}

function exportarKardex() {
  downloadWithAuth("/api/reportes/kardex/exportar?formato=csv", "kardex.csv");
}

// ============ INIT ============

async function init() {
  console.log("init called");
  document.getElementById("login-form").addEventListener("submit", handleLogin);
  document.getElementById("force-change-form").addEventListener("submit", handleForceChange);
  document.getElementById("btn-logout").addEventListener("click", handleLogout);
  setupTabNavigation();

  const token = getToken();
  if (token) {
    await loadCurrentUser();
    if (currentUser && !currentUser.password_changed_at) {
      hideLogin();
      showForceChange();
    } else if (currentUser) {
      await startApp();
    }
  } else {
    showLogin();
  }
}

async function startApp() {
  console.log("startApp called");
  await loadEmpresa();
  await loadClientes();
  await loadProductos();
  await loadDashboard();
  await loadHistorial();
  addLinea();
  setupTabNavigation();
}

function setupTabNavigation() {
  const btns = document.querySelectorAll(".tab-btn");
  btns.forEach(btn => {
    if (btn.getAttribute("data-listener") === "true") return;
    btn.setAttribute("data-listener", "true");
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Sidebar Collapse Toggle
  const toggleBtn = document.getElementById("btn-toggle-sidebar");
  if (toggleBtn && !toggleBtn.dataset.bound) {
    toggleBtn.dataset.bound = "true";
    if (localStorage.getItem("sap_sidebar_collapsed") === "1") {
      document.body.classList.add("sidebar-collapsed");
    }
    toggleBtn.addEventListener("click", () => {
      document.body.classList.toggle("sidebar-collapsed");
      localStorage.setItem(
        "sap_sidebar_collapsed",
        document.body.classList.contains("sidebar-collapsed") ? "1" : "0"
      );
    });
  }

  // Sidebar Quick Search (Ctrl+K)
  const searchInput = document.getElementById("sidebar-search-input");
  if (searchInput && !searchInput.dataset.bound) {
    searchInput.dataset.bound = "true";
    searchInput.addEventListener("input", () => {
      const q = searchInput.value.trim().toLowerCase();
      document.querySelectorAll("#main-nav-tabs .tab-btn").forEach(btn => {
        const text = (btn.textContent || "").toLowerCase();
        const title = (btn.getAttribute("title") || "").toLowerCase();
        const matches = !q || text.includes(q) || title.includes(q);
        btn.classList.toggle("nav-filtered-out", !matches);
      });
    });
    document.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        document.body.classList.remove("sidebar-collapsed");
        searchInput.focus();
        searchInput.select();
      }
    });
  }

  // Admin Sub-navigation Filter
  const adminSubnav = document.getElementById("admin-subnav");
  if (adminSubnav && !adminSubnav.dataset.bound) {
    adminSubnav.dataset.bound = "true";
    adminSubnav.querySelectorAll(".admin-subnav-btn").forEach(b => {
      b.addEventListener("click", () => {
        adminSubnav.querySelectorAll(".admin-subnav-btn").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        const filter = b.dataset.adminFilter;
        document.querySelectorAll("#tab-admin [data-admin-section]").forEach(sec => {
          if (sec.id && sec.id.endsWith("-form") && sec.style.display === "none") {
            return;
          }
          if (filter === "all" || sec.dataset.adminSection === filter) {
            sec.classList.remove("admin-section-hidden");
          } else {
            sec.classList.add("admin-section-hidden");
          }
        });
      });
    });
  }
}

async function loadDashboard() {
  console.log("loadDashboard called");
  try {
    const res = await apiFetch("/api/dashboard/kpis");
    const kpis = await res.json();
    document.getElementById("kpi-ventas").textContent = formatCOP(kpis.ventas_mes);
    document.getElementById("kpi-cartera").textContent = formatCOP(kpis.cartera_pendiente);
    document.getElementById("kpi-vencida").textContent = formatCOP(kpis.cartera_vencida);
    document.getElementById("kpi-ticket").textContent = formatCOP(kpis.ticket_promedio);
    const stockAlertas = kpis.stock ? kpis.stock.stock_alertas : [];
    document.getElementById("kpi-stock").textContent = stockAlertas.filter(a => a.saldo < a.stock_minimo).length;

    const tbody = document.getElementById("stock-alertas-tbody");
    tbody.innerHTML = "";
    const alerts = stockAlertas.filter(a => a.saldo < a.stock_minimo);
    if (alerts.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #888;">Sin alertas de stock.</td></tr>';
      return;
    }
    alerts.forEach(a => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(a.codigo)}</td><td>${esc(a.nombre)}</td><td>${esc(a.bodega)}</td><td>${esc(a.saldo)}</td><td>${esc(a.stock_minimo)}</td>`;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando dashboard:", err);
  }
}

async function loadAsientos() {
  try {
    const page = document.getElementById("asientos-page").value || "1";
    const res = await apiFetch(`/api/contabilidad/asientos?page=${esc(page)}&limit=50`);
    const payload = await res.json();
    const tbody = document.getElementById("asientos-tbody");
    tbody.innerHTML = "";
    (payload.data || []).forEach(a => {
      const tr = document.createElement("tr");
      const movs = (a.movimientos || []).map(m => `${esc(m.cuenta_codigo)} ${esc(m.concepto)} D:${esc(m.debito)} C:${esc(m.credito)}`).join("<br>");
      tr.innerHTML = `<td>${esc(a.numero_comprobante)}</td><td>${esc(a.fecha)}</td><td>${esc(a.concepto)}</td><td>${raw(movs)}</td>`;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando asientos:", err);
  }
}

async function loadKardex() {
  try {
    const res = await apiFetch("/api/inventario/kardex");
    const kardex = await res.json();
    const tbody = document.getElementById("kardex-tbody");
    tbody.innerHTML = "";
    if (kardex.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #888;">Sin movimientos de inventario.</td></tr>';
      return;
    }
    kardex.forEach(k => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(k.fecha)}</td><td>${esc(k.producto_codigo)}</td><td>${esc(k.bodega_codigo)}</td><td>${esc(k.tipo_movimiento)}</td><td>${esc(k.cantidad_entrada)}</td><td>${esc(k.cantidad_salida)}</td><td>${esc(k.saldo_cantidad)}</td>`;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando kardex:", err);
  }
}

async function loadEmpresa() {
  try {
    const res = await apiFetch("/api/empresa");
    const data = await res.json();
    document.getElementById("empresa-nombre").textContent = `${esc(data.razon_social)} (NIT: ${esc(data.nit)}-${esc(data.dv)})`;
    document.getElementById("emp-nit-info").textContent = `${esc(data.nit)}-${esc(data.dv)}`;
    document.getElementById("emp-razon").textContent = esc(data.razon_social);
    document.getElementById("emp-resolucion-info").textContent = `Res. ${esc(data.resolucion_dian)} de ${esc(data.fecha_resolucion)} (${esc(data.prefijo_resolucion)})`;
    document.getElementById("emp-rango").textContent = `${esc(data.rango_desde)} hasta ${esc(data.rango_hasta)}`;
    document.getElementById("empresa-ambiente").textContent = `Ambiente: ${esc(data.tipo_ambiente === "2" ? "Producción en operación (2)" : "Producción en habilitación (1)")}`;

    // El badge de estado DIAN antes decía "En Línea" fijo, mqttieniendo el modo
    // de operación. Ahora refleja el modo real (mock vs. DIAN real) y si hay
    // certificado configurado, que es lo que exige la DIAN en producción.
    const badge = document.getElementById("dian-status-badge");
    const real = data.url_dian && data.url_dian.trim() !== "";
    const conCert = !!(data.ruta_certificado && data.ruta_certificado.trim() !== "");
    const produccion = data.tipo_ambiente === "2";
    if (!real) {
      badge.className = "badge badge-warning";
      badge.textContent = "DIAN: modo simulado (no transmite a la DIAN real)";
      badge.title = "Configure empresas.url_dian y SAP_DIAN_MODE=real para transmite a la DIAN.";
    } else if (produccion && !conCert) {
      badge.className = "badge badge-danger";
      badge.textContent = "DIAN: producción SIN certificado digital";
      badge.title = "La DIAN rechaza toda factura de producción sin firma digital.";
    } else {
      badge.className = "badge badge-success";
      badge.textContent = prod2Texto(produccion) + (conCert ? " · con certificado" : " · sin certificado");
    }

    applyCompanyBranding(data);
  } catch (err) {
    console.error("Error cargando empresa:", err);
  }
}

function applyCompanyBranding(empresa) {
  if (!empresa) return;
  const root = document.documentElement;
  const primario = empresa.color_primario || "#2563eb";
  const secundario = empresa.color_secundario || "#1d4ed8";
  const sidebar = empresa.color_sidebar || "#0f172a";
  const fondo = empresa.color_fondo || "#f1f5f9";

  root.style.setProperty("--sap-blue", primario);
  root.style.setProperty("--sap-dark-blue", secundario);
  root.style.setProperty("--sap-button-hover", secundario);
  root.style.setProperty("--sap-header-bg", sidebar);
  root.style.setProperty("--sap-sidebar-bg", sidebar);
  root.style.setProperty("--sap-bg", fondo);

  const headerEl = document.getElementById("main-header");
  if (headerEl) {
    headerEl.style.background = sidebar;
  }
  const sidebarEl = document.getElementById("main-nav-tabs");
  if (sidebarEl) {
    sidebarEl.style.background = sidebar;
  }

  // Logo & Sigla de Marca
  const initials = (empresa.nombre_marca && empresa.nombre_marca.trim())
    ? empresa.nombre_marca.trim()
    : (empresa.razon_social ? empresa.razon_social.split(/\s+/).slice(0, 2).map(w => w[0] || "").join("").toUpperCase() || "ERP" : "ERP");

  ["header-logo-box", "login-logo-box"].forEach(boxId => {
    const box = document.getElementById(boxId);
    if (!box) return;
    if (empresa.logo_data && empresa.logo_data.startsWith("data:image/")) {
      box.innerHTML = `<img src="${empresa.logo_data}" alt="${esc(initials)}" class="company-logo-img">`;
      box.classList.add("has-custom-logo");
    } else {
      box.textContent = initials;
      box.classList.remove("has-custom-logo");
      box.style.background = `linear-gradient(135deg, ${primario} 0%, ${secundario} 100%)`;
    }
  });

  if (empresa.razon_social) {
    document.title = `${empresa.razon_social} — ERP Facturación DIAN`;
    const loginTitle = document.getElementById("login-brand-title");
    if (loginTitle) loginTitle.textContent = empresa.razon_social;
  }

  // Fuente Tipográfica Personalizada o Seleccionada
  let styleTag = document.getElementById("dynamic-company-font");
  if (!styleTag) {
    styleTag = document.createElement("style");
    styleTag.id = "dynamic-company-font";
    document.head.appendChild(styleTag);
  }

  const fontName = empresa.fuente_nombre || "Inter";
  if (empresa.fuente_data && empresa.fuente_data.startsWith("data:")) {
    styleTag.textContent = `
      @font-face {
        font-family: 'CompanyCustomFont';
        src: url('${empresa.fuente_data}');
        font-weight: 100 900;
        font-display: swap;
      }
      body, button, input, select, textarea {
        font-family: 'CompanyCustomFont', -apple-system, BlinkMacSystemFont, sans-serif !important;
      }
    `;
  } else if (fontName === "Georgia") {
    styleTag.textContent = `
      body, button, input, select, textarea {
        font-family: Georgia, 'Times New Roman', serif !important;
      }
    `;
  } else if (fontName === "System") {
    styleTag.textContent = `
      body, button, input, select, textarea {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
      }
    `;
  } else {
    const gFontId = "google-font-" + fontName.toLowerCase().replace(/\s+/g, "-");
    if (["Roboto", "Montserrat", "Poppins", "Inter"].includes(fontName) && !document.getElementById(gFontId)) {
      const link = document.createElement("link");
      link.id = gFontId;
      link.rel = "stylesheet";
      link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(fontName)}:wght@400;500;600;700;800&display=swap`;
      document.head.appendChild(link);
    }
    styleTag.textContent = `
      body, button, input, select, textarea {
        font-family: '${fontName}', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
      }
    `;
  }
}

async function openActiveCompanyBranding() {
  switchTab("admin");
  const empFilterBtn = document.querySelector('#admin-subnav .admin-subnav-btn[data-admin-filter="empresas"]');
  if (empFilterBtn) empFilterBtn.click();
  try {
    const res = await apiFetch("/api/empresa");
    if (res.ok) {
      const emp = await res.json();
      if (emp && emp.id) {
        showEmpresaForm(emp);
        const panel = document.querySelector(".branding-studio-panel");
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  } catch (e) {
    console.error("No se pudo abrir editor de marca:", e);
  }
}

function prod2Texto(produccion) {
  return produccion ? "DIAN: producción en operación" : "DIAN: producción en habilitación";
}

async function loadClientes() {
  try {
    const res = await apiFetch("/api/clientes");
    clientesList = await res.json();
    const sel = document.getElementById("cliente-select");
    sel.innerHTML = '<option value="">Seleccione un cliente...</option>';
    clientesList.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.nit;
      opt.textContent = `${esc(c.razon_social)} (NIT: ${esc(c.nit)}-${esc(c.dv)})`;
      sel.appendChild(opt);
    });
  } catch (err) {
    console.error("Error cargando clientes:", err);
  }
}

async function loadProductos() {
  try {
    const res = await apiFetch("/api/productos");
    productosList = await res.json();
  } catch (err) {
    console.error("Error cargando productos:", err);
  }
}

// ============ TAB 1: FACTURACIÓN ============

function addLinea() {
  const id = Date.now() + Math.random();
  lineas.push({
    id: id,
    producto_codigo: productosList[0] ? productosList[0].codigo : "",
    descripcion: productosList[0] ? productosList[0].descripcion : "",
    cantidad: 1,
    valor_unitario: productosList[0] ? productosList[0].precio_unitario : 0,
    tarifa_iva: productosList[0] ? productosList[0].tarifa_iva : "IVA_19",
    tipo_bien_servicio: productosList[0] ? productosList[0].tipo_bien_servicio : "BIENES"
  });
  renderLineas();
  calcularFiscal();
}

function removeLinea(id) {
  if (lineas.length <= 1) {
    alert("La factura debe tener al menos una línea.");
    return;
  }
  lineas = lineas.filter(l => l.id !== id);
  renderLineas();
  calcularFiscal();
}

function renderLineas() {
  const tbody = document.getElementById("lineas-tbody");
  tbody.innerHTML = "";

  lineas.forEach((l, idx) => {
    const tr = document.createElement("tr");
    let prodOptions = productosList.map(p =>
      `<option value="${esc(p.codigo)}" ${esc(p.codigo === l.producto_codigo ? "selected" : "")}>${esc(p.descripcion)}</option>`
    ).join("");

    tr.innerHTML = `
      <td>
        <select class="form-control" onchange="onSelectProducto(${esc(l.id)}, this.value)">
          ${raw(prodOptions)}
        </select>
      </td>
      <td>
        <select class="form-control" onchange="onUpdateLinea(${esc(l.id)}, 'tipo_bien_servicio', this.value)">
          <option value="BIENES" ${esc(l.tipo_bien_servicio === 'BIENES' ? 'selected' : '')}>Bienes (2.5%)</option>
          <option value="SERVICIOS" ${esc(l.tipo_bien_servicio === 'SERVICIOS' ? 'selected' : '')}>Servicios (4%)</option>
          <option value="ARRENDAMIENTO" ${esc(l.tipo_bien_servicio === 'ARRENDAMIENTO' ? 'selected' : '')}>Arriendo (3.5%)</option>
          <option value="EXENTO" ${esc(l.tipo_bien_servicio === 'EXENTO' ? 'selected' : '')}>Sin Retención</option>
        </select>
      </td>
      <td>
        <input type="number" min="1" step="1" class="form-control" value="${esc(l.cantidad)}"
               onchange="onUpdateLinea(${esc(l.id)}, 'cantidad', this.value)" style="width: 70px;">
      </td>
      <td>
        <input type="number" min="0" step="100" class="form-control" value="${esc(l.valor_unitario)}"
               onchange="onUpdateLinea(${esc(l.id)}, 'valor_unitario', this.value)">
      </td>
      <td>
        <select class="form-control" onchange="onUpdateLinea(${esc(l.id)}, 'tarifa_iva', this.value)">
          <option value="IVA_19" ${esc(l.tarifa_iva === 'IVA_19' ? 'selected' : '')}>19% General</option>
          <option value="IVA_5" ${esc(l.tarifa_iva === 'IVA_5' ? 'selected' : '')}>5% Reducido</option>
          <option value="IVA_0" ${esc(l.tarifa_iva === 'IVA_0' ? 'selected' : '')}>0% Exento</option>
        </select>
      </td>
      <td id="subtotal-col-${esc(l.id)}">
        ${esc(formatCOP(l.cantidad * l.valor_unitario))}
      </td>
      <td>
        <button class="btn btn-danger" onclick="removeLinea(${esc(l.id)})">✕</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function onSelectProducto(lineaId, codigo) {
  const prod = productosList.find(p => p.codigo === codigo);
  if (!prod) return;
  const linea = lineas.find(l => l.id === lineaId);
  if (linea) {
    linea.producto_codigo = prod.codigo;
    linea.descripcion = prod.descripcion;
    linea.valor_unitario = prod.precio_unitario;
    linea.tarifa_iva = prod.tarifa_iva;
    linea.tipo_bien_servicio = prod.tipo_bien_servicio;
    renderLineas();
    calcularFiscal();
  }
}

function onUpdateLinea(lineaId, field, val) {
  const linea = lineas.find(l => l.id === lineaId);
  if (linea) {
    linea[field] = val;
    calcularFiscal();
    const subCol = document.getElementById(`subtotal-col-${esc(lineaId)}`);
    if (subCol) subCol.textContent = formatCOP(linea.cantidad * linea.valor_unitario);
  }
}

let fiscalDebounceTimer = null;

async function calcularFiscal() {
  if (fiscalDebounceTimer) {
    clearTimeout(fiscalDebounceTimer);
  }
  
  fiscalDebounceTimer = setTimeout(async () => {
    try {
      const res = await apiFetch("/api/liquidar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lineas })
      });
      const data = await res.json();
      if (res.ok) {
        document.getElementById("sum-subtotal").textContent = formatCOP(data.base_total);
        document.getElementById("sum-iva19").textContent = formatCOP(data.iva_19);
        document.getElementById("sum-iva5").textContent = formatCOP(data.iva_5);
        document.getElementById("sum-iva0").textContent = formatCOP(data.iva_0);
        document.getElementById("sum-total-iva").textContent = formatCOP(data.total_iva);
        document.getElementById("sum-retefuente").textContent = formatCOP(data.retefuente);
        document.getElementById("sum-reteiva").textContent = formatCOP(data.reteiva);
        document.getElementById("sum-reteica").textContent = formatCOP(data.reteica);
        document.getElementById("sum-total").textContent = formatCOP(data.total_factura);
      }
    } catch (err) {
      console.error("Error liquidando:", err);
    }
  }, 500);
}

async function emitirFactura() {
  const clienteNit = document.getElementById("cliente-select").value;
  if (!clienteNit) {
    alert("Por favor seleccione un cliente/adquirente.");
    return;
  }

  const btn = document.getElementById("btn-emitir-dian");
  btn.disabled = true;
  btn.textContent = "Transmitiendo a la DIAN...";

  try {
    const res = await apiFetch("/api/emitir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cliente_nit: clienteNit,
        lineas: lineas,
        tipo_operacion: document.getElementById("tipo-operacion").value
      })
    });
    const data = await res.json();

    if (!res.ok) {
      alert("Error al emitir factura: " + (data.error || "Desconocido"));
      return;
    }

    document.getElementById("resultado-dian").style.display = "block";
    document.getElementById("res-consecutivo").textContent = data.consecutivo;
    document.getElementById("res-estado").textContent = data.estado_dian;
    document.getElementById("res-desc").textContent = `${esc(data.status_description)} (Código ${esc(data.status_code)})`;
    document.getElementById("res-trackid").textContent = data.track_id;
    document.getElementById("res-fecha").textContent = data.fecha_validacion;
    document.getElementById("res-cufe").textContent = data.cufe;
    document.getElementById("res-qr-str").textContent = data.qr;
    const btnXml = document.getElementById("btn-descargar-xml");
    if (btnXml) {
      btnXml.href = `/api/facturas/${esc(data.id)}/xml`;
      btnXml.onclick = (ev) => downloadWithAuth(btnXml.href, `Factura_${data.consecutivo}.xml`, ev);
    }
    const btnPdf = document.getElementById("btn-descargar-pdf");
    if (btnPdf) {
      btnPdf.href = `/api/facturas/${esc(data.id)}/pdf`;
      btnPdf.onclick = (ev) => downloadWithAuth(btnPdf.href, `Factura_${data.consecutivo}.pdf`, ev);
    }
    const btnZip = document.getElementById("btn-descargar-zip");
    if (btnZip) {
      btnZip.href = `/api/facturas/${esc(data.id)}/zip`;
      btnZip.onclick = (ev) => downloadWithAuth(btnZip.href, `AttachedDocument_${data.consecutivo}.zip`, ev);
    }
    const btnMail = document.getElementById("btn-enviar-correo-emision");
    if (btnMail) {
      btnMail.onclick = () => abrirModalEmail(data.id, data.consecutivo, clienteNit);
    }

    showToast(`Factura ${esc(data.consecutivo)} emitida y validada exitosamente por la DIAN.`, "success");

    document.getElementById("resultado-dian").scrollIntoView({ behavior: "smooth" });

    await loadHistorial();
  } catch (err) {
    console.error("Error emitiendo:", err);
    alert("Fallo en la comunicación con el servidor.");
  }   finally {
    btn.disabled = false;
    btn.textContent = "Emitir Factura Electrónica a DIAN";
  }
}

function _facturasQuery() {
  const desde = document.getElementById("f-filters-desde");
  const hasta = document.getElementById("f-filters-hasta");
  const cliente = document.getElementById("f-filters-cliente");
  const estado = document.getElementById("f-filters-estado");
  const page = document.getElementById("f-filters-page");
  const params = new URLSearchParams();
  if (desde && desde.value) params.set("fecha_desde", desde.value);
  if (hasta && hasta.value) params.set("fecha_hasta", hasta.value);
  if (cliente && cliente.value) params.set("cliente_nit", cliente.value);
  if (estado && estado.value) params.set("estado_cartera", estado.value);
  if (page) params.set("page", page.value || "1");
  params.set("limit", "100");
  return params.toString();
}

async function loadHistorial() {
  try {
    const res = await apiFetch(`/api/facturas?${esc(_facturasQuery())}`);
    const payload = await res.json();
    const facturas = payload.data || [];
    facturasList = facturas;
    const tbody = document.getElementById("historial-tbody");
    tbody.innerHTML = "";

    if (facturas.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #888;">No hay facturas emitidas aún.</td></tr>';
      return;
    }

    facturas.forEach(f => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(f.id)}</td>
        <td><strong>${esc(f.consecutivo)}</strong></td>
        <td>${esc(f.fecha)} ${esc(f.hora)}</td>
        <td>${esc(f.cliente_nit)}</td>
        <td>${esc(formatCOP(f.subtotal))}</td>
        <td>${esc(formatCOP(f.total_iva))}</td>
        <td><strong>${esc(formatCOP(f.total_factura))}</strong></td>
        <td><span class="badge badge-success">${esc(f.estado_dian)}</span></td>
        <td><code>${esc((f.track_id || '').substring(0, 10))}...</code></td>
        <td class="action-buttons-cell" style="white-space: nowrap;">
          <a href="/api/facturas/${esc(f.id)}/xml" onclick="return downloadWithAuth(this.href, 'Factura_${esc(f.consecutivo)}.xml', event)" class="btn btn-secondary btn-action-xs" title="Descargar XML UBL 2.1">XML</a>
          <a href="/api/facturas/${esc(f.id)}/pdf" onclick="return downloadWithAuth(this.href, 'Factura_${esc(f.consecutivo)}.pdf', event)" class="btn btn-primary btn-action-xs" title="Descargar PDF">PDF</a>
          <a href="/api/facturas/${esc(f.id)}/zip" onclick="return downloadWithAuth(this.href, 'AttachedDocument_${esc(f.consecutivo)}.zip', event)" class="btn btn-info btn-action-xs" title="Descargar AttachedDocument (ZIP)">ZIP</a>
          <button type="button" class="btn btn-success btn-action-xs" onclick="abrirModalEmail(${esc(f.id)}, '${esc(f.consecutivo)}', '${esc(f.cliente_nit)}')" title="Enviar por Correo">✉️</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    const info = document.getElementById("f-filters-info");
    if (info) info.textContent = `Total: ${esc(payload.total)}`;
  } catch (err) {
    console.error("Error cargando historial:", err);
  }
}

// ============ TAB 2: NOTAS CRÉDITO ============

async function loadFacturasForNC() {
  try {
    const res = await apiFetch("/api/facturas?limit=1000");
    const payload = await res.json();
    const facturas = payload.data || [];
    facturasList = facturas;
    const sel = document.getElementById("nc-factura-select");
    sel.innerHTML = '<option value="">Seleccione una factura...</option>';
    facturas.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f.id;
      opt.textContent = `#${esc(f.id)} - ${esc(f.consecutivo)} - ${esc(f.cliente_nit)} - ${esc(formatCOP(f.total_factura))}`;
      sel.appendChild(opt);
    });
  } catch (err) {
    console.error("Error cargando facturas para NC:", err);
  }
}

async function emitirNotaCredito() {
  const facturaId = document.getElementById("nc-factura-select").value;
  if (!facturaId) {
    alert("Por favor seleccione una factura padre.");
    return;
  }

  const motivo = document.getElementById("nc-motivo").value;
  const descripcion = document.getElementById("nc-descripcion").value;
  const tipoAnulacion = document.getElementById("nc-anulacion").value;
  const montoParcial = parseFloat(document.getElementById("nc-monto-parcial").value) || 0;

  const btn = document.getElementById("btn-emitir-nc");
  btn.disabled = true;
  btn.textContent = "Procesando Nota Crédito...";

  try {
    const payload = {
      factura_id: parseInt(facturaId),
      motivo_dian: motivo,
      descripcion_motivo: descripcion,
      tipo_anulacion: tipoAnulacion
    };

    if (tipoAnulacion === "PARCIAL" && montoParcial > 0) {
      const factura = facturasList.find(f => f.id === parseInt(facturaId));
      if (factura) {
        payload.lineas_devolucion = [{
          producto_codigo: "DEV",
          descripcion: "Devolución parcial",
          cantidad: 1,
          valor_unitario: montoParcial,
          subtotal: montoParcial,
          tarifa_iva: "IVA_19",
          valor_iva: 0
        }];
      }
    }

    const res = await apiFetch("/api/notas-credito/crear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok) {
      alert("Error al emitir Nota Crédito: " + (data.error || JSON.stringify(data)));
      return;
    }

    const nc = data.nota_credito || data;
    document.getElementById("nc-resultado").style.display = "block";
    document.getElementById("nc-res-consecutivo").textContent = nc.consecutivo || "-";
    document.getElementById("nc-res-motivo").textContent = descripcion || motivo;
    document.getElementById("nc-res-subtotal").textContent = formatCOP(nc.subtotal);
    document.getElementById("nc-res-total").textContent = formatCOP(nc.total_nota);
    document.getElementById("nc-res-saldo").textContent = data.nuevo_saldo_factura || "-";
    document.getElementById("nc-res-cude").textContent = nc.cude || "-";

    document.getElementById("nc-resultado").scrollIntoView({ behavior: "smooth" });

    await loadNotasCredito();
    await loadHistorial();
  } catch (err) {
    console.error("Error emitiendo NC:", err);
    alert("Fallo en la comunicación con el servidor.");
  }   finally {
    btn.disabled = false;
    btn.textContent = "Emitir Nota Crédito";
  }
}

async function loadNotasCredito() {
  try {
    const res = await apiFetch("/api/notas-credito");
    const notas = await res.json();
    notasCreditoList = notas;
    const tbody = document.getElementById("nc-tbody");
    tbody.innerHTML = "";

    if (notas.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #888;">No hay notas crédito emitidas.</td></tr>';
      return;
    }

    notas.forEach(nc => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(nc.id)}</td>
        <td><strong>${esc(nc.prefijo || "")}${esc(nc.consecutivo)}</strong></td>
        <td>${esc(nc.fecha)} ${esc(nc.hora)}</td>
        <td>${esc(nc.factura_consecutivo || '-')}</td>
        <td>${esc(nc.cliente_nit)}</td>
        <td>${esc(nc.descripcion_motivo || nc.motivo_dian)}</td>
        <td>${esc(formatCOP(nc.subtotal))}</td>
        <td><strong>${esc(formatCOP(nc.total_nota))}</strong></td>
        <td><span class="badge badge-success">${esc(nc.estado_dian)}</span></td>
        <td><code>${esc((nc.track_id || '').substring(0, 10))}...</code></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando notas crédito:", err);
  }
}

// ============ MODAL EMAIL FACTURA ============

function abrirModalEmail(facturaId, consecutivo, clienteNit) {
  const modal = document.getElementById("modal-email-factura");
  if (!modal) return;
  document.getElementById("email-factura-id").value = facturaId;
  document.getElementById("email-factura-info").textContent = `Factura #${esc(facturaId)} (Consecutivo: ${esc(consecutivo)})`;

  let emailSugerido = "";
  if (clienteNit && clientesList && clientesList.length) {
    const c = clientesList.find(cli => cli.nit === clienteNit);
    if (c && c.email) emailSugerido = c.email;
  }
  document.getElementById("email-factura-destinatario").value = emailSugerido || "";
  const empNombre = document.getElementById("empresa-nombre")?.textContent || "SAP Colombia";
  document.getElementById("email-factura-asunto").value = `Factura Electrónica ${esc(consecutivo)} - ${empNombre}`;

  const resBox = document.getElementById("email-envio-resultado");
  if (resBox) {
    resBox.style.display = "none";
    resBox.textContent = "";
  }

  modal.style.display = "flex";
}

function cerrarModalEmail() {
  const modal = document.getElementById("modal-email-factura");
  if (modal) modal.style.display = "none";
}

async function enviarFacturaEmailConfirm() {
  const facturaId = document.getElementById("email-factura-id").value;
  const emailDestino = document.getElementById("email-factura-destinatario").value.trim();
  const asunto = document.getElementById("email-factura-asunto").value.trim();
  const btn = document.getElementById("btn-confirmar-envio-email");
  const resBox = document.getElementById("email-envio-resultado");

  if (!emailDestino) {
    showToast("Por favor ingrese el correo del destinatario.", "warning");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Enviando correo...";

  try {
    const res = await apiFetch("/api/facturas/enviar-correo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        factura_id: parseInt(facturaId),
        email_destino: emailDestino,
        asunto: asunto || undefined
      })
    });
    const data = await res.json();

    if (!res.ok) {
      if (resBox) {
        resBox.style.display = "block";
        resBox.className = "result-box bg-danger";
        resBox.textContent = `Error: ${data.error || "No se pudo enviar el correo"}`;
      }
      showToast(data.error || "Error al enviar correo", "error");
      return;
    }

    if (resBox) {
      resBox.style.display = "block";
      resBox.className = "result-box bg-success";
      resBox.textContent = `✓ Correo enviado exitosamente a ${emailDestino} con PDF y ZIP AttachedDocument.`;
    }
    showToast(`Correo enviado exitosamente a ${emailDestino}`, "success");
    setTimeout(() => {
      cerrarModalEmail();
    }, 1800);
  } catch (err) {
    console.error("Error enviando factura por correo:", err);
    if (resBox) {
      resBox.style.display = "block";
      resBox.className = "result-box bg-danger";
      resBox.textContent = "Fallo en la comunicación con el servidor.";
    }
    showToast("Fallo en la comunicación con el servidor.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Enviar Documento";
  }
}

// ============ NOTAS DÉBITO ============

let notasDebitoList = [];

function actualizarTotalND() {
  const subtotalEl = document.getElementById("nd-subtotal");
  const tarifaEl = document.getElementById("nd-tarifa-iva");
  if (!subtotalEl || !tarifaEl) return;
  const subtotal = parseFloat(subtotalEl.value) || 0;
  const tarifaIva = tarifaEl.value;
  let pct = 0;
  if (tarifaIva === "IVA_19") pct = 0.19;
  else if (tarifaIva === "IVA_5") pct = 0.05;
  const iva = subtotal * pct;
  const total = subtotal + iva;
  const preview = document.getElementById("nd-total-preview");
  if (preview) {
    preview.textContent = formatCOP(total);
  }
}

async function loadFacturasForND() {
  try {
    const res = await apiFetch("/api/facturas?limit=1000");
    const payload = await res.json();
    const facturas = payload.data || [];
    const sel = document.getElementById("nd-factura-select");
    if (!sel) return;
    sel.innerHTML = '<option value="">Seleccione una factura...</option>';
    facturas.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f.id;
      opt.textContent = `#${esc(f.id)} - ${esc(f.consecutivo)} - ${esc(f.cliente_nit)} - ${esc(formatCOP(f.total_factura))}`;
      sel.appendChild(opt);
    });
  } catch (err) {
    console.error("Error cargando facturas para ND:", err);
  }
}

async function loadNotasDebito() {
  try {
    const res = await apiFetch("/api/notas-debito");
    const notas = await res.json();
    notasDebitoList = notas || [];
    const tbody = document.getElementById("nd-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (notasDebitoList.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #888;">No hay notas débito emitidas aún.</td></tr>';
      return;
    }

    const conceptos = {
      "1": "1 - Intereses",
      "2": "2 - Gastos por cobrar",
      "3": "3 - Cambio de valor",
      "4": "4 - Otros"
    };

    notasDebitoList.forEach(nd => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(nd.id)}</td>
        <td><strong>${esc(nd.prefijo || "")}${esc(nd.consecutivo)}</strong></td>
        <td>${esc(nd.fecha || "")} ${esc(nd.hora || "")}</td>
        <td>${esc(nd.factura_consecutivo || "-")}</td>
        <td>${esc(nd.cliente_nit || "-")}</td>
        <td>${esc(nd.descripcion_motivo || conceptos[nd.concepto_dian] || nd.concepto_dian || "-")}</td>
        <td>${esc(formatCOP(nd.subtotal))}</td>
        <td><strong>${esc(formatCOP(nd.total_nota))}</strong></td>
        <td><span class="badge badge-success">${esc(nd.estado_dian || "Aceptada")}</span></td>
        <td><code>${esc((nd.track_id || "").substring(0, 10))}...</code></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando notas débito:", err);
  }
}

async function emitirNotaDebito() {
  const facturaId = document.getElementById("nd-factura-select")?.value;
  if (!facturaId) {
    alert("Por favor seleccione una factura padre.");
    return;
  }

  const concepto = document.getElementById("nd-concepto")?.value || "4";
  const descripcion = document.getElementById("nd-descripcion")?.value.trim() || "";
  const subtotal = parseFloat(document.getElementById("nd-subtotal")?.value) || 0;
  const tarifaIva = document.getElementById("nd-tarifa-iva")?.value || "IVA_19";

  if (subtotal <= 0) {
    alert("Por favor ingrese un subtotal mayor a 0.");
    return;
  }

  let iva19 = "0.00";
  let iva5 = "0.00";
  if (tarifaIva === "IVA_19") {
    iva19 = (subtotal * 0.19).toFixed(2);
  } else if (tarifaIva === "IVA_5") {
    iva5 = (subtotal * 0.05).toFixed(2);
  }

  const btn = document.getElementById("btn-emitir-nd");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Procesando Nota Débito...";
  }

  try {
    const payload = {
      factura_id: parseInt(facturaId),
      concepto_dian: concepto,
      descripcion: descripcion,
      subtotal: subtotal.toFixed(2),
      iva_19: iva19,
      iva_5: iva5
    };

    const res = await apiFetch("/api/notas-debito/crear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok) {
      alert("Error al emitir Nota Débito: " + (data.error || JSON.stringify(data)));
      return;
    }

    const nd = data.nota_debito || data;
    const resEl = document.getElementById("nd-resultado");
    if (resEl) {
      resEl.style.display = "block";
      const elCons = document.getElementById("nd-res-consecutivo");
      if (elCons) elCons.textContent = (nd.prefijo || "") + (nd.consecutivo || "-");
      const elConc = document.getElementById("nd-res-concepto");
      if (elConc) elConc.textContent = descripcion || concepto;
      const elSub = document.getElementById("nd-res-subtotal");
      if (elSub) elSub.textContent = formatCOP(nd.subtotal);
      const elTot = document.getElementById("nd-res-total");
      if (elTot) elTot.textContent = formatCOP(nd.total_nota);
      const elSal = document.getElementById("nd-res-saldo");
      if (elSal) elSal.textContent = formatCOP(data.nuevo_saldo_factura || 0);
      const elCude = document.getElementById("nd-res-cude");
      if (elCude) elCude.textContent = nd.cude || "-";
      const elEst = document.getElementById("nd-res-estado");
      if (elEst) elEst.textContent = nd.estado_dian || "Aceptada";

      resEl.scrollIntoView({ behavior: "smooth" });
    }

    showToast(`Nota Débito ${nd.prefijo || ""}${nd.consecutivo} emitida y validada exitosamente.`, "success");

    await loadNotasDebito();
    await loadHistorial();
  } catch (err) {
    console.error("Error emitiendo ND:", err);
    alert("Fallo en la comunicación con el servidor.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⚡ Emitir Nota Débito";
    }
  }
}

// ============ TAB 3: CARTERA Y RECAUDOS ============

async function loadCartera() {
  try {
    const [edadesRes, facturasRes] = await Promise.all([
      apiFetch("/api/cartera/edades"),
      apiFetch("/api/facturas?limit=1000")
    ]);
    const edades = await edadesRes.json();
    const payload = await facturasRes.json();
    const facturas = payload.data || [];
    facturasList = facturas;

    // Semáforo
    const resumen = edades.resumen || {};
    document.getElementById("cartera-corriente").textContent = formatCOP(resumen.corriente || "0");
    document.getElementById("cartera-v30").textContent = formatCOP(resumen["1_a_30"] || "0");
    document.getElementById("cartera-v60").textContent = formatCOP(resumen["31_a_60"] || "0");
    document.getElementById("cartera-v90").textContent = formatCOP(resumen["61_a_90"] || "0");
    document.getElementById("cartera-mas90").textContent = formatCOP(resumen.mas_90 || "0");

    // Facturas pendientes
    const pendientes = facturas.filter(f => f.saldo_pendiente && parseFloat(f.saldo_pendiente) > 0);
    const tbody = document.getElementById("cartera-tbody");
    tbody.innerHTML = "";

    if (pendientes.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #888;">No hay facturas con saldo pendiente.</td></tr>';
      return;
    }

    pendientes.forEach(f => {
      const tr = document.createElement("tr");
      const estadoBadge = f.estado_cartera === "PAGADA_TOTAL" ? "badge-success" : "badge-info";
      tr.innerHTML = `
        <td>${esc(f.id)}</td>
        <td><strong>${esc(f.consecutivo)}</strong></td>
        <td>${esc(f.fecha)}</td>
        <td>${esc(f.fecha_vencimiento || '-')}</td>
        <td>${esc(f.cliente_nit)}</td>
        <td><strong>${esc(formatCOP(f.saldo_pendiente))}</strong></td>
        <td><span class="badge ${esc(estadoBadge)}">${esc(f.estado_cartera || 'PENDIENTE')}</span></td>
        <td>
          <button class="btn btn-primary" onclick="abrirModalRecaudo(${esc(f.id)})">Recaudar</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando cartera:", err);
  }
}

function abrirModalRecaudo(facturaId) {
  const factura = facturasList.find(f => f.id === facturaId);
  if (!factura) return;

  document.getElementById("recaudo-factura-info").textContent =
    `#${esc(factura.id)} - ${esc(factura.consecutivo)} | Cliente: ${esc(factura.cliente_nit)} | Saldo: ${esc(formatCOP(factura.saldo_pendiente))}`;
  document.getElementById("recaudo-monto").value = factura.saldo_pendiente;
  document.getElementById("recaudo-monto").max = factura.saldo_pendiente;
  document.getElementById("recaudo-referencia").value = "";
  document.getElementById("recaudo-observaciones").value = "";
  document.getElementById("modal-recaudo").style.display = "flex";
  document.getElementById("modal-recaudo").dataset.facturaId = facturaId;
}

function cerrarModalRecaudo() {
  document.getElementById("modal-recaudo").style.display = "none";
}

async function confirmarRecaudo() {
  const facturaId = parseInt(document.getElementById("modal-recaudo").dataset.facturaId);
  const monto = parseFloat(document.getElementById("recaudo-monto").value);
  const medio = document.getElementById("recaudo-medio").value;
  const referencia = document.getElementById("recaudo-referencia").value;
  const observaciones = document.getElementById("recaudo-observaciones").value;

  if (!monto || monto <= 0) {
    alert("El monto del recaudo debe ser mayor a 0.");
    return;
  }

  const btn = document.getElementById("btn-confirmar-recaudo");
  btn.disabled = true;
  btn.textContent = "Procesando...";

  try {
    const res = await apiFetch("/api/cartera/recaudar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        factura_id: facturaId,
        monto: monto,
        medio_pago: medio,
        referencia: referencia,
        observaciones: observaciones
      })
    });
    const data = await res.json();

    if (!res.ok) {
      alert("Error al registrar recaudo: " + (data.error || JSON.stringify(data)));
      return;
    }

    alert(`Recaudo ${esc(data.recibo ? data.recibo.numero : '')} registrado exitosamente.`);
    cerrarModalRecaudo();
    await loadCartera();
    await loadHistorial();
  } catch (err) {
    console.error("Error registrando recaudo:", err);
    alert("Fallo en la comunicación con el servidor.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Confirmar Recaudo";
  }
}

// ============ TAB 4: DOCUMENTO SOPORTE ============

function addDsLinea() {
  const id = Date.now() + Math.random();
  dsLineas.push({ id, producto_codigo: "", descripcion: "", subtotal: 0 });
  renderDsLineas();
}

function removeDsLinea(id) {
  dsLineas = dsLineas.filter(l => l.id !== id);
  renderDsLineas();
}

function renderDsLineas() {
  const tbody = document.getElementById("ds-lineas-tbody");
  tbody.innerHTML = "";

  dsLineas.forEach(l => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <input type="text" class="form-control" value="${esc(l.producto_codigo)}"
               onchange="onUpdateDsLinea(${esc(l.id)}, 'producto_codigo', this.value)">
      </td>
      <td>
        <input type="text" class="form-control" value="${esc(l.descripcion)}"
               onchange="onUpdateDsLinea(${esc(l.id)}, 'descripcion', this.value)">
      </td>
      <td>
        <input type="number" min="0" step="100" class="form-control" value="${esc(l.subtotal)}"
               onchange="onUpdateDsLinea(${esc(l.id)}, 'subtotal', this.value)">
      </td>
      <td>
        <button class="btn btn-danger" onclick="removeDsLinea(${esc(l.id)})">✕</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function onUpdateDsLinea(lineaId, field, val) {
  const linea = dsLineas.find(l => l.id === lineaId);
  if (linea) linea[field] = val;
}

async function emitirDocumentoSoporte() {
  if (dsLineas.length === 0) {
    alert("Debe agregar al menos una línea al documento soporte.");
    return;
  }

  const btn = document.getElementById("btn-emitir-ds");
  btn.disabled = true;
  btn.textContent = "Generando CUDS...";

  try {
    const payload = {
      datos: {
        prefijo: document.getElementById("ds-prefijo").value,
        proveedor_nit: document.getElementById("ds-proveedor-nit").value,
        proveedor_nombre: document.getElementById("ds-proveedor-nombre").value,
        proveedor_doc: document.getElementById("ds-tipo-doc").value,
        tarifa_retefuente: document.getElementById("ds-retefuente").value,
        tarifa_reteica: document.getElementById("ds-reteica").value
      },
      lineas: dsLineas.map(l => ({
        producto_codigo: l.producto_codigo,
        descripcion: l.descripcion,
        subtotal: l.subtotal
      }))
    };

    const res = await apiFetch("/api/documento-soporte/crear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok) {
      alert("Error al emitir Documento Soporte: " + (data.error || JSON.stringify(data)));
      return;
    }

    const doc = data.documento || data;
    document.getElementById("ds-resultado").style.display = "block";
    document.getElementById("ds-res-consecutivo").textContent = doc.consecutivo || "-";
    document.getElementById("ds-res-proveedor").textContent = doc.proveedor_nit || "-";
    document.getElementById("ds-res-subtotal").textContent = formatCOP(doc.subtotal);
    document.getElementById("ds-res-retefuente").textContent = formatCOP(doc.retefuente);
    document.getElementById("ds-res-reteica").textContent = formatCOP(doc.reteica);
    document.getElementById("ds-res-total").textContent = formatCOP(doc.total_documento);
    document.getElementById("ds-res-cuds").textContent = doc.cuds || "-";

    document.getElementById("ds-resultado").scrollIntoView({ behavior: "smooth" });

    await loadDocumentosSoporte();
  } catch (err) {
    console.error("Error emitiendo DS:", err);
    alert("Fallo en la comunicación con el servidor.");
  }   finally {
    btn.disabled = false;
    btn.textContent = "Emitir Documento Soporte";
  }
}

async function loadDocumentosSoporte() {
  try {
    const res = await apiFetch("/api/documento-soporte");
    const docs = await res.json();
    const tbody = document.getElementById("ds-tbody");
    tbody.innerHTML = "";

    if (docs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: #888;">No hay documentos soporte emitidos.</td></tr>';
      return;
    }

    docs.forEach(doc => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(doc.id)}</td>
        <td><strong>${esc(doc.prefijo || "")}${esc(doc.consecutivo)}</strong></td>
        <td>${esc(doc.fecha)}</td>
        <td>${esc(doc.proveedor_nit)}</td>
        <td>${esc(doc.proveedor_nombre)}</td>
        <td>${esc(formatCOP(doc.subtotal))}</td>
        <td>${esc(formatCOP(doc.retefuente))}</td>
        <td>${esc(formatCOP(doc.reteica))}</td>
        <td><strong>${esc(formatCOP(doc.total_documento))}</strong></td>
        <td><code>${esc((doc.cuds || '').substring(0, 12))}...</code></td>
        <td><span class="badge badge-success">${esc(doc.estado_dian)}</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando documentos soporte:", err);
  }
}

// ============ TAB 5: CONTABILIDAD PUC ============

async function loadBalance() {
  try {
    const res = await apiFetch("/api/contabilidad/balance");
    const data = await res.json();

    const cuentas = data.cuentas || [];
    const tbody = document.getElementById("balance-tbody");
    tbody.innerHTML = "";

    if (cuentas.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #888;">No hay movimientos contables.</td></tr>';
    }

    let totalDebitos = 0;
    let totalCreditos = 0;

    cuentas.forEach(c => {
      const tr = document.createElement("tr");
      const deb = parseFloat(c.debitos) || 0;
      const cred = parseFloat(c.creditos) || 0;
      totalDebitos += deb;
      totalCreditos += cred;
      tr.innerHTML = `
        <td>${esc(c.codigo)}</td>
        <td>${esc(c.nombre)}</td>
        <td><span class="cuenta-natureza">${esc(c.naturaleza)}</span></td>
        <td>${esc(c.categoria)}</td>
        <td>${esc(formatCOP(deb))}</td>
        <td>${esc(formatCOP(cred))}</td>
        <td><strong>${esc(formatCOP(c.saldo_final))}</strong></td>
      `;
      tbody.appendChild(tr);
    });

    document.getElementById("balance-total-debitos").textContent = formatCOP(totalDebitos);
    document.getElementById("balance-total-creditos").textContent = formatCOP(totalCreditos);

    const diferencia = Math.abs(totalDebitos - totalCreditos);
    const diffEl = document.getElementById("balance-diferencia");
    diffEl.textContent = formatCOP(diferencia);
    diffEl.style.color = diferencia < 0.01 ? "var(--sap-success)" : "var(--sap-danger)";

    // Validación partida doble
    const valEl = document.getElementById("balance-validation");
    valEl.style.display = "flex";
    const badge = document.getElementById("balance-badge");
    const msg = document.getElementById("balance-message");
    if (diferencia < 0.01) {
      badge.textContent = "✓";
      badge.className = "badge badge-success";
      msg.textContent = "Partida doble validada: Débitos = Créditos";
    } else {
      badge.textContent = "✕";
      badge.className = "badge badge-info";
      msg.textContent = `Desbalance: Débitos ≠ Créditos (diferencia ${esc(formatCOP(diferencia))})`;
    }
  } catch (err) {
    console.error("Error cargando balance:", err);
  }
}

async function loadCuentasPUC() {
  try {
    const res = await apiFetch("/api/contabilidad/cuentas");
    const cuentas = await res.json();
    const tbody = document.getElementById("cuentas-tbody");
    tbody.innerHTML = "";

    if (cuentas.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #888;">No hay cuentas PUC registradas.</td></tr>';
      return;
    }

    cuentas.forEach(c => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(c.codigo)}</td>
        <td>${esc(c.nombre)}</td>
        <td><span class="cuenta-natureza">${esc(c.naturaleza)}</span></td>
        <td>${esc(c.categoria)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error cargando cuentas PUC:", err);
  }
}

// ==============================
// Sistema Admin UI
// ==============================

async function loadAdminData() {
  try {
    const [empresasRes, usuariosRes, rolesRes, userEmpRes] = await Promise.all([
      apiFetch('/api/admin/empresas'),
      apiFetch('/api/admin/usuarios'),
      apiFetch('/api/admin/roles'),
      apiFetch('/api/admin/usuario-empresas'),
    ]);
    const empresas = await empresasRes.json();
    const usuarios = await usuariosRes.json();
    const roles = await rolesRes.json();
    const userEmpresas = await userEmpRes.json();
    renderEmpresasTable(empresas);
    renderUsuariosTable(usuarios);
    renderRolesTable(roles);
    renderUsuarioEmpresasTable(userEmpresas);
    populateEmpresaSelects(empresas);
    populateRolesSelect(roles);
    populateUsuarioEmpresasSelects(usuarios, empresas);
  } catch (e) {
    console.error('Error cargando admin:', e);
  }
}

function renderUsuarioEmpresasTable(mappings) {
  const tbody = document.getElementById('tbody-usuario-empresas');
  if (!tbody) return;
  if (!Array.isArray(mappings) || mappings.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#a0aec0;">No hay asignaciones registradas</td></tr>';
    return;
  }
  tbody.innerHTML = mappings.map(m => `
    <tr>
      <td><strong>${esc(m.usuario_nombre || m.usuario_id)}</strong></td>
      <td>${esc(m.email || '')}</td>
      <td><span class="badge badge-secondary">${esc(m.rol_global || 'SISTEMA')}</span></td>
      <td>${esc(m.razon_social || m.empresa_id)}</td>
      <td>${esc(m.nit || '')}</td>
      <td><span class="badge badge-success">${esc(m.rol_en_empresa || '')}</span></td>
      <td>
        <button class="btn btn-sm btn-danger" onclick="desasignarUsuarioEmpresa(${esc(m.usuario_id)}, ${esc(m.empresa_id)})">Desvincular</button>
      </td>
    </tr>
  `).join('');
}

function populateUsuarioEmpresasSelects(usuarios, empresas) {
  const uSel = document.getElementById('asig-ue-usuario');
  const eSel = document.getElementById('asig-ue-empresa');
  if (uSel && Array.isArray(usuarios)) {
    uSel.innerHTML = usuarios.map(u => `<option value="${esc(u.id)}">${esc(u.nombre || u.email)} (${esc(u.email)})</option>`).join('');
  }
  if (eSel && Array.isArray(empresas)) {
    eSel.innerHTML = empresas.map(e => `<option value="${esc(e.id)}">${esc(e.razon_social)} (NIT: ${esc(e.nit)})</option>`).join('');
  }
}

async function asignarUsuarioEmpresa() {
  const uSel = document.getElementById('asig-ue-usuario');
  const eSel = document.getElementById('asig-ue-empresa');
  const rSel = document.getElementById('asig-ue-rol');
  if (!uSel || !eSel || !rSel) return;

  const usuario_id = parseInt(uSel.value);
  const empresa_id = parseInt(eSel.value);
  const rol_en_empresa = rSel.value;

  if (!usuario_id || !empresa_id) {
    showToast("Seleccione usuario y empresa", "warning");
    return;
  }

  try {
    const res = await apiFetch('/api/admin/usuario-empresas', {
      method: 'POST',
      body: JSON.stringify({ usuario_id, empresa_id, rol_en_empresa, es_predeterminada: false })
    });
    if (res.ok) {
      showToast("Usuario asignado exitosamente a la empresa", "success");
      const listRes = await apiFetch('/api/admin/usuario-empresas');
      const listData = await listRes.json();
      renderUsuarioEmpresasTable(listData);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || "Error al asignar usuario", "error");
    }
  } catch (e) {
    showToast("Error de conexión al asignar usuario", "error");
  }
}

async function desasignarUsuarioEmpresa(usuario_id, empresa_id) {
  if (!confirm("¿Desea desvincular a este usuario de la empresa?")) return;
  try {
    const res = await apiFetch(`/api/admin/usuario-empresas?usuario_id=${usuario_id}&empresa_id=${empresa_id}`, {
      method: 'DELETE'
    });
    if (res.ok) {
      showToast("Usuario desvinculado de la empresa", "success");
      const listRes = await apiFetch('/api/admin/usuario-empresas');
      const listData = await listRes.json();
      renderUsuarioEmpresasTable(listData);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || "Error al desvincular", "error");
    }
  } catch (e) {
    showToast("Error de conexión al desvincular", "error");
  }
}

function renderEmpresasTable(empresas) {
  const tbody = document.getElementById('tbody-empresas');
  if (!tbody) return;
  tbody.innerHTML = empresas.map(e => {
    const cPrim = e.color_primario || '#0070f2';
    const cSide = e.color_sidebar || '#0f172a';
    const cSec = e.color_secundario || '#1b90ff';
    const marca = e.nombre_marca || 'ERP';
    const fontName = e.fuente_data ? 'Fuentes Propia' : (e.fuente_nombre || 'Inter');
    const logoBadge = e.logo_data
      ? `<img src="${esc(e.logo_data)}" alt="Logo" style="height:24px; max-width:56px; object-fit:contain; border-radius:4px; background:#fff; padding:2px; border:1px solid #e2e8f0; vertical-align:middle; margin-right:6px;">`
      : `<span style="display:inline-flex; align-items:center; justify-content:center; height:22px; padding:0 6px; border-radius:4px; background:${esc(cPrim)}; color:#fff; font-weight:800; font-size:0.7rem; margin-right:6px;">${esc(marca)}</span>`;
    return `
    <tr>
      <td>${esc(e.id)}</td>
      <td>${esc(e.nit || '')}</td>
      <td><strong>${esc(e.razon_social || '')}</strong></td>
      <td>
        <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
          ${logoBadge}
          <span title="Color Primario: ${esc(cPrim)}" style="width:14px; height:14px; border-radius:50%; background:${esc(cPrim)}; display:inline-block; border:1px solid rgba(0,0,0,0.15);"></span>
          <span title="Color Secundario: ${esc(cSec)}" style="width:14px; height:14px; border-radius:50%; background:${esc(cSec)}; display:inline-block; border:1px solid rgba(0,0,0,0.15);"></span>
          <span title="Color Menú: ${esc(cSide)}" style="width:14px; height:14px; border-radius:50%; background:${esc(cSide)}; display:inline-block; border:1px solid rgba(0,0,0,0.15);"></span>
          <span class="badge badge-secondary" style="font-size:0.7rem;">🔤 ${esc(fontName)}</span>
        </div>
      </td>
      <td>${esc(e.user_count || 0)}</td>
      <td>
        <button class="btn btn-sm btn-primary" onclick="editEmpresa(${esc(e.id)})" title="Personalizar Marca, Logo, Colores y Fuente">🎨 Marca / Editar</button>
        <button class="btn btn-sm btn-danger" onclick="deleteEmpresa(${esc(e.id)})">Eliminar</button>
      </td>
    </tr>
  `}).join('');
}

function updateLogoPreviewBox(logoData, badgeText) {
  const preview = document.getElementById('emp-logo-preview');
  if (!preview) return;
  if (logoData && logoData.startsWith('data:image/')) {
    preview.innerHTML = `<img src="${logoData}" alt="Logo Preview" style="max-height:46px; max-width:92px; object-fit:contain;">`;
  } else {
    preview.innerHTML = `<span id="emp-logo-preview-placeholder" style="font-weight:800; color:var(--sap-brand); font-size:0.85rem;">${esc(badgeText || 'ERP')}</span>`;
  }
}

function clearEmpresaLogo() {
  const hidden = document.getElementById('emp-logo-data');
  const fileInput = document.getElementById('emp-logo-file');
  const badgeInput = document.getElementById('emp-nombre-marca');
  if (hidden) hidden.value = '';
  if (fileInput) fileInput.value = '';
  updateLogoPreviewBox('', badgeInput ? badgeInput.value : 'ERP');
}

function clearEmpresaFont() {
  const hidden = document.getElementById('emp-fuente-data');
  const fileInput = document.getElementById('emp-fuente-file');
  const statusEl = document.getElementById('emp-fuente-status');
  if (hidden) hidden.value = '';
  if (fileInput) fileInput.value = '';
  if (statusEl) statusEl.textContent = 'Sin archivo de fuente personalizado (usando fuente seleccionada).';
}

function setPickerAndHex(pickerId, hexId, value) {
  const picker = document.getElementById(pickerId);
  const hex = document.getElementById(hexId);
  if (picker && /^#[0-9A-Fa-f]{6}$/.test(value)) picker.value = value;
  if (hex) hex.value = value;
}

function applyBrandingPreset(primario, secundario, sidebar, fondo) {
  setPickerAndHex('emp-color-primario-picker', 'emp-color-primario', primario);
  setPickerAndHex('emp-color-secundario-picker', 'emp-color-secundario', secundario);
  setPickerAndHex('emp-color-sidebar-picker', 'emp-color-sidebar', sidebar);
  setPickerAndHex('emp-color-fondo-picker', 'emp-color-fondo', fondo);
  // Previsualizar en vivo
  applyCompanyBranding({
    razon_social: document.getElementById('emp-razon-social')?.value || currentBrandingEmpresa?.razon_social || 'Empresa Corporativa',
    nit: document.getElementById('empresa-nit')?.value || currentBrandingEmpresa?.nit || '',
    dv: document.getElementById('emp-dv')?.value || currentBrandingEmpresa?.dv || '',
    nombre_marca: document.getElementById('emp-nombre-marca')?.value || 'ERP',
    logo_data: document.getElementById('emp-logo-data')?.value || '',
    color_primario: primario,
    color_secundario: secundario,
    color_sidebar: sidebar,
    color_fondo: fondo,
    fuente_nombre: document.getElementById('emp-fuente-nombre')?.value || 'Inter',
    fuente_data: document.getElementById('emp-fuente-data')?.value || ''
  });
}

function initBrandingStudioBindings() {
  const pairs = [
    ['emp-color-primario-picker', 'emp-color-primario'],
    ['emp-color-secundario-picker', 'emp-color-secundario'],
    ['emp-color-sidebar-picker', 'emp-color-sidebar'],
    ['emp-color-fondo-picker', 'emp-color-fondo']
  ];
  pairs.forEach(([pickerId, hexId]) => {
    const picker = document.getElementById(pickerId);
    const hex = document.getElementById(hexId);
    if (picker && hex && !picker.dataset.bound) {
      picker.dataset.bound = '1';
      picker.addEventListener('input', () => {
        hex.value = picker.value;
      });
      hex.addEventListener('input', () => {
        if (/^#[0-9A-Fa-f]{6}$/.test(hex.value.trim())) {
          picker.value = hex.value.trim();
        }
      });
    }
  });

  const badgeInput = document.getElementById('emp-nombre-marca');
  if (badgeInput && !badgeInput.dataset.bound) {
    badgeInput.dataset.bound = '1';
    badgeInput.addEventListener('input', () => {
      const currentLogo = document.getElementById('emp-logo-data')?.value || '';
      if (!currentLogo) {
        updateLogoPreviewBox('', badgeInput.value || 'ERP');
      }
    });
  }

  const logoFile = document.getElementById('emp-logo-file');
  if (logoFile && !logoFile.dataset.bound) {
    logoFile.dataset.bound = '1';
    logoFile.addEventListener('change', (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      if (file.size > 2 * 1024 * 1024) {
        showToast('El logo no debe superar 2 MB', 'warning');
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        const hidden = document.getElementById('emp-logo-data');
        if (hidden) hidden.value = dataUrl;
        updateLogoPreviewBox(dataUrl, document.getElementById('emp-nombre-marca')?.value || 'ERP');
        showToast('Logo cargado. Guarde la empresa para aplicar permanentemente.', 'info');
      };
      reader.readAsDataURL(file);
    });
  }

  const fontFile = document.getElementById('emp-fuente-file');
  if (fontFile && !fontFile.dataset.bound) {
    fontFile.dataset.bound = '1';
    fontFile.addEventListener('change', (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      if (file.size > 4 * 1024 * 1024) {
        showToast('El archivo de fuente no debe superar 4 MB', 'warning');
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        const hidden = document.getElementById('emp-fuente-data');
        if (hidden) hidden.value = dataUrl;
        const statusEl = document.getElementById('emp-fuente-status');
        if (statusEl) statusEl.textContent = `✅ Fuente personalizada cargada: ${file.name}`;
        showToast(`Fuente "${file.name}" lista para guardar`, 'info');
      };
      reader.readAsDataURL(file);
    });
  }
}

function renderUsuariosTable(usuarios) {
  const tbody = document.getElementById('tbody-usuarios');
  if (!tbody) return;
  tbody.innerHTML = usuarios.map(u => `
    <tr>
      <td>${esc(u.id)}</td>
      <td>${esc(u.email || '')}</td>
      <td>${esc(u.nombre || '')}</td>
      <td><span class="badge badge-${esc(u.rol === 'SUPERADMIN' ? 'danger' : u.rol === 'ADMIN_SISTEMA' ? 'warning' : 'success')}">${esc(u.rol || '')}</span></td>
      <td>${esc(u.empresa_id ? u.empresa_id : '— Sistema —')}</td>
      <td>${esc(u.activo ? 'Sí' : 'No')}</td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="editUsuario(${esc(u.id)})">Editar</button>
        <button class="btn btn-sm btn-danger" onclick="deleteUsuario(${esc(u.id)})">Eliminar</button>
      </td>
    </tr>
  `).join('');
}

function renderRolesTable(roles) {
  const tbody = document.getElementById('tbody-roles');
  if (!tbody) return;
  tbody.innerHTML = roles.map(r => `
    <tr>
      <td>${esc(r.id)}</td>
      <td>${esc(r.nombre || '')}</td>
      <td>${esc(r.descripcion || '')}</td>
      <td>${esc(r.tipo || 'EMPRESA')}</td>
      <td>${esc(r.activo ? 'Sí' : 'No')}</td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="editRol(${esc(r.id)})">Editar</button>
        <button class="btn btn-sm btn-primary" onclick="showPermisosRol(${esc(r.id)})">Permisos</button>
        <button class="btn btn-sm btn-danger" onclick="deleteRol(${esc(r.id)})">Eliminar</button>
      </td>
    </tr>
  `).join('');
}

function populateEmpresaSelects(empresas) {
  ['usr-empresa', 'rol-empresa'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">— Sin empresa (sistema) —</option>';
    empresas.forEach(e => {
      const opt = document.createElement('option');
      opt.value = e.id;
      opt.textContent = `${esc(e.razon_social)} (${esc(e.nit)})`;
      sel.appendChild(opt);
    });
    if (current) sel.value = current;
  });
}

function populateRolesSelect(roles) {
  const sel = document.getElementById('usr-rol');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '';
  roles.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.nombre;
    opt.textContent = r.nombre;
    sel.appendChild(opt);
  });
  if (current) sel.value = current;
}

// --- Empresa CRUD ---
function showEmpresaForm(empresa = null) {
  initBrandingStudioBindings();
  const card = document.getElementById('card-empresa-form');
  const title = document.getElementById('empresa-form-title');
  const form = document.getElementById('form-empresa');
  if (card && form) {
    card.style.display = 'block';
    if (empresa) {
      title.textContent = 'Editar Empresa #' + empresa.id + ' — ' + (empresa.razon_social || '');
      form.querySelector('#emp-id').value = empresa.id;
      form.querySelector('#empresa-nit').value = empresa.nit || '';
      form.querySelector('#emp-dv').value = empresa.dv || '';
      form.querySelector('#emp-razon-social').value = empresa.razon_social || '';
      form.querySelector('#emp-direccion').value = empresa.direccion || '';
      form.querySelector('#emp-municipio').value = empresa.municipio || '';
      form.querySelector('#emp-departamento').value = empresa.departamento || '';
      form.querySelector('#emp-prefijo').value = empresa.prefijo_resolucion || '';
      form.querySelector('#empresa-resolucion').value = empresa.resolucion_dian || '';
      form.querySelector('#emp-fecha-resolucion').value = empresa.fecha_resolucion || '';
      form.querySelector('#emp-clave').value = empresa.clave_tecnica || '';
      form.querySelector('#emp-ambiente').value = empresa.tipo_ambiente || '2';
      form.querySelector('#emp-url-dian').value = empresa.url_dian || '';
      // Branding fields
      const marca = empresa.nombre_marca || 'ERP';
      const logoData = empresa.logo_data || '';
      const cPrim = empresa.color_primario || '#0070f2';
      const cSec = empresa.color_secundario || '#1b90ff';
      const cSide = empresa.color_sidebar || '#0f172a';
      const cFondo = empresa.color_fondo || '#f4f6f9';
      const fNombre = empresa.fuente_nombre || 'Inter';
      const fData = empresa.fuente_data || '';
      if (form.querySelector('#emp-nombre-marca')) form.querySelector('#emp-nombre-marca').value = marca;
      if (form.querySelector('#emp-logo-data')) form.querySelector('#emp-logo-data').value = logoData;
      updateLogoPreviewBox(logoData, marca);
      setPickerAndHex('emp-color-primario-picker', 'emp-color-primario', cPrim);
      setPickerAndHex('emp-color-secundario-picker', 'emp-color-secundario', cSec);
      setPickerAndHex('emp-color-sidebar-picker', 'emp-color-sidebar', cSide);
      setPickerAndHex('emp-color-fondo-picker', 'emp-color-fondo', cFondo);
      if (form.querySelector('#emp-fuente-nombre')) form.querySelector('#emp-fuente-nombre').value = fNombre;
      if (form.querySelector('#emp-fuente-data')) form.querySelector('#emp-fuente-data').value = fData;
      const statusEl = document.getElementById('emp-fuente-status');
      if (statusEl) {
        statusEl.textContent = fData
          ? '✅ Fuente personalizada activa en esta empresa.'
          : 'Sin archivo de fuente personalizado (usando fuente seleccionada).';
      }
    } else {
      title.textContent = 'Nueva Empresa';
      form.reset();
      form.querySelector('#emp-id').value = '';
      if (form.querySelector('#emp-nombre-marca')) form.querySelector('#emp-nombre-marca').value = 'ERP';
      if (form.querySelector('#emp-logo-data')) form.querySelector('#emp-logo-data').value = '';
      if (form.querySelector('#emp-fuente-data')) form.querySelector('#emp-fuente-data').value = '';
      updateLogoPreviewBox('', 'ERP');
      setPickerAndHex('emp-color-primario-picker', 'emp-color-primario', '#0070f2');
      setPickerAndHex('emp-color-secundario-picker', 'emp-color-secundario', '#1b90ff');
      setPickerAndHex('emp-color-sidebar-picker', 'emp-color-sidebar', '#0f172a');
      setPickerAndHex('emp-color-fondo-picker', 'emp-color-fondo', '#f4f6f9');
    }
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

async function saveEmpresa(e) {
  e.preventDefault();
  const form = e.target;
  const id = form.querySelector('#emp-id').value;
  const data = {
    nit: form.querySelector('#empresa-nit').value,
    dv: form.querySelector('#emp-dv').value,
    razon_social: form.querySelector('#emp-razon-social').value,
    direccion: form.querySelector('#emp-direccion').value,
    municipio: form.querySelector('#emp-municipio').value,
    departamento: form.querySelector('#emp-departamento').value,
    prefijo_resolucion: form.querySelector('#emp-prefijo').value,
    resolucion_dian: form.querySelector('#empresa-resolucion').value,
    fecha_resolucion: form.querySelector('#emp-fecha-resolucion').value,
    clave_tecnica: form.querySelector('#emp-clave').value,
    tipo_ambiente: form.querySelector('#emp-ambiente').value,
    url_dian: form.querySelector('#emp-url-dian').value,
    nombre_marca: form.querySelector('#emp-nombre-marca')?.value || 'ERP',
    logo_data: form.querySelector('#emp-logo-data')?.value || '',
    color_primario: form.querySelector('#emp-color-primario')?.value || '#0070f2',
    color_secundario: form.querySelector('#emp-color-secundario')?.value || '#1b90ff',
    color_sidebar: form.querySelector('#emp-color-sidebar')?.value || '#0f172a',
    color_fondo: form.querySelector('#emp-color-fondo')?.value || '#f4f6f9',
    fuente_nombre: form.querySelector('#emp-fuente-nombre')?.value || 'Inter',
    fuente_data: form.querySelector('#emp-fuente-data')?.value || '',
  };
  try {
    if (id) {
      await apiFetch('/api/admin/empresas/' + id, { method: 'PUT', body: JSON.stringify(data) });
    } else {
      await apiFetch('/api/admin/empresas', { method: 'POST', body: JSON.stringify(data) });
    }
    document.getElementById('card-empresa-form').style.display = 'none';
    showToast('Empresa e identidad visual guardadas correctamente', 'success');
    await loadAdminData();
    await loadEmpresa();
    // Actualizar selector superior de empresas si existe
    const sel = document.getElementById('select-empresa-activa');
    if (sel && id && String(sel.value) === String(id)) {
      const opt = sel.querySelector(`option[value="${id}"]`);
      if (opt) opt.textContent = `${data.razon_social} (${data.nit})`;
    }
  } catch (e2) {
    showToast('Error al guardar empresa: ' + e2.message, 'error');
  }
}

async function editEmpresa(id) {
  try {
    const res = await apiFetch('/api/admin/empresas/' + id);
    const emp = await res.json();
    showEmpresaForm(emp);
  } catch (e) { alert('Error: ' + e.message); }
}

async function deleteEmpresa(id) {
  if (!confirm('¿Eliminar la empresa #' + id + '?')) return;
  try {
    await apiFetch('/api/admin/empresas/' + id, { method: 'DELETE' });
    await loadAdminData();
  } catch (e) { alert('Error: ' + e.message); }
}

// --- Usuario CRUD ---
function showUsuarioForm(usuario = null) {
  const card = document.getElementById('card-usuario-form');
  const title = document.getElementById('usuario-form-title');
  const form = document.getElementById('form-usuario');
  if (card && form) {
    card.style.display = 'block';
    if (usuario) {
      title.textContent = 'Editar Usuario #' + usuario.id;
      form.querySelector('#usr-id').value = usuario.id;
      form.querySelector('#usr-email').value = usuario.email || '';
      form.querySelector('#usr-nombre').value = usuario.nombre || '';
      form.querySelector('#usr-rol').value = usuario.rol || '';
      form.querySelector('#usr-empresa').value = usuario.empresa_id || '';
      form.querySelector('#usr-activo').value = usuario.activo ? '1' : '0';
      form.querySelector('#usr-password').value = '';
      form.querySelector('#usr-password').placeholder = 'Dejar vacío para no cambiar';
      form.querySelector('#usr-password').required = false;
    } else {
      title.textContent = 'Nuevo Usuario';
      form.reset();
      form.querySelector('#usr-id').value = '';
      form.querySelector('#usr-password').required = true;
    }
  }
}

async function saveUsuario(e) {
  e.preventDefault();
  const id = document.getElementById('usr-id').value;
  const data = {
    email: document.getElementById('usr-email').value,
    nombre: document.getElementById('usr-nombre').value,
    rol: document.getElementById('usr-rol').value,
    empresa_id: document.getElementById('usr-empresa').value || null,
    activo: parseInt(document.getElementById('usr-activo').value),
  };
  const pwd = document.getElementById('usr-password').value;
  if (pwd) data.password = pwd;
  try {
    if (id) {
      await apiFetch('/api/admin/usuarios/' + id, { method: 'PUT', body: JSON.stringify(data) });
    } else {
      await apiFetch('/api/admin/usuarios', { method: 'POST', body: JSON.stringify(data) });
    }
    document.getElementById('card-usuario-form').style.display = 'none';
    await loadAdminData();
  } catch (e2) { alert('Error: ' + e2.message); }
}

async function editUsuario(id) {
  try {
    const res = await apiFetch('/api/admin/usuarios/' + id);
    const u = await res.json();
    showUsuarioForm(u);
  } catch (e) { alert('Error: ' + e.message); }
}

async function deleteUsuario(id) {
  if (!confirm('¿Eliminar el usuario #' + id + '?')) return;
  try {
    await apiFetch('/api/admin/usuarios/' + id, { method: 'DELETE' });
    await loadAdminData();
  } catch (e) { alert('Error: ' + e.message); }
}

// --- Rol CRUD ---
function showRolForm(rol = null) {
  const card = document.getElementById('card-rol-form');
  const title = document.getElementById('rol-form-title');
  const form = document.getElementById('form-rol');
  if (card && form) {
    card.style.display = 'block';
    if (rol) {
      title.textContent = 'Editar Rol #' + rol.id;
      form.querySelector('#rol-id').value = rol.id;
      form.querySelector('#rol-nombre').value = rol.nombre || '';
      form.querySelector('#rol-descripcion').value = rol.descripcion || '';
      form.querySelector('#rol-activo').value = rol.activo ? '1' : '0';
    } else {
      title.textContent = 'Nuevo Rol';
      form.reset();
      form.querySelector('#rol-id').value = '';
    }
  }
}

async function saveRol(e) {
  e.preventDefault();
  const id = document.getElementById('rol-id').value;
  const data = {
    nombre: document.getElementById('rol-nombre').value,
    descripcion: document.getElementById('rol-descripcion').value,
    empresa_id: document.getElementById('rol-empresa').value || null,
    activo: parseInt(document.getElementById('rol-activo').value),
  };
  try {
    if (id) {
      await apiFetch('/api/admin/roles/' + id, { method: 'PUT', body: JSON.stringify(data) });
    } else {
      await apiFetch('/api/admin/roles', { method: 'POST', body: JSON.stringify(data) });
    }
    document.getElementById('card-rol-form').style.display = 'none';
    await loadAdminData();
  } catch (e2) { alert('Error: ' + e2.message); }
}

async function editRol(id) {
  try {
    const res = await apiFetch('/api/admin/roles/' + id);
    const r = await res.json();
    showRolForm(r);
  } catch (e) { alert('Error: ' + e.message); }
}

async function deleteRol(id) {
  if (!confirm('¿Eliminar el rol #' + id + '?')) return;
  try {
    await apiFetch('/api/admin/roles/' + id, { method: 'DELETE' });
    await loadAdminData();
  } catch (e) { alert('Error: ' + e.message); }
}

// --- Permisos de Rol & SoD ---
let currentRolId = null;
let sodCatalogCache = [];

async function loadSoDCatalog() {
  if (sodCatalogCache.length > 0) return sodCatalogCache;
  try {
    const res = await apiFetch('/api/rbac/sod-matriz');
    if (res.ok) {
      const data = await res.json();
      sodCatalogCache = data.conflictos || [];
    }
  } catch (e) {
    console.warn("No se pudo cargar la matriz SoD:", e);
  }
  return sodCatalogCache;
}

function checkSoDConflicts() {
  const container = document.getElementById('sod-warnings-container');
  const list = document.getElementById('sod-warnings-list');
  if (!container || !list) return;

  const checked = new Set([...document.querySelectorAll('#permisos-grid input[type="checkbox"]:checked')].map(cb => cb.value));
  if (checked.has('*') || checked.size === 0) {
    container.style.display = 'none';
    list.innerHTML = '';
    return;
  }

  const conflicts = sodCatalogCache.filter(c => checked.has(c.permiso_a) && checked.has(c.permiso_b));
  if (conflicts.length === 0) {
    container.style.display = 'none';
    list.innerHTML = '';
    return;
  }

  container.style.display = 'block';
  list.innerHTML = conflicts.map(c => `
    <div class="sod-conflict-box">
      <span class="sod-conflict-badge ${c.nivel.toLowerCase()}">[${esc(c.id)} - Riesgo ${esc(c.nivel)}]</span>
      <strong>${esc(c.titulo)}</strong>: ${esc(c.descripcion)}
      <div style="margin-top: 4px; font-style: italic; color: #4a5568;">
        🛡️ Control compensatorio sugerido: ${esc(c.control_compensatorio)}
      </div>
    </div>
  `).join('');
}

async function showPermisosRol(id) {
  try {
    const res = await apiFetch('/api/admin/roles/' + id + '/permisos');
    const data = await res.json();
    const roleRes = await apiFetch('/api/admin/roles/' + id);
    const role = await roleRes.json();
    
    currentRolId = id;
    document.getElementById('permisos-modal-title').textContent = 'Permisos de: ' + role.nombre;
    document.getElementById('permisos-modal').style.display = 'flex';
    
    // Load catalog and SoD matrix concurrently
    const [catRes, _] = await Promise.all([
      apiFetch('/api/permisos'),
      loadSoDCatalog()
    ]);
    const catalog = await catRes.json();
    
    // Group by resource
    const grouped = {};
    catalog.permisos.forEach(p => {
      const recurso = p.split(':')[0];
      if (!grouped[recurso]) grouped[recurso] = [];
      grouped[recurso].push(p);
    });
    
    const permisosGrid = document.getElementById('permisos-grid');
    permisosGrid.innerHTML = '';
    
    Object.entries(grouped).forEach(([recurso, perms]) => {
      const permsHtml = perms.map(p => `
        <label style="display:inline-flex; align-items:center; gap:4px; margin-right:10px; cursor:pointer;">
          <input type="checkbox" value="${esc(p)}" ${data.permisos.includes(p) ? 'checked' : ''} onchange="checkSoDConflicts()">
          <span>${esc(p.split(':')[1])}</span>
        </label>
      `).join('');

      permisosGrid.innerHTML += `
        <div class="permisos-recurso" style="margin-bottom: 12px; padding: 8px 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px;">
          <div class="permisos-recurso-header" style="margin-bottom: 6px;">
            <strong style="color: #2b6cb0; text-transform: uppercase; font-size: 12px;">${esc(recurso)}</strong>
          </div>
          <div class="permisos-recurso-perms" style="display: flex; flex-wrap: wrap; gap: 6px;">
            ${permsHtml}
          </div>
        </div>
      `;
    });
    
    checkSoDConflicts();
    document.getElementById('btn-save-permisos').onclick = savePermisos;
  } catch (e) { alert('Error: ' + e.message); }
}

function toggleAllPermisos(checked) {
  const checkboxes = document.querySelectorAll('#permisos-grid input[type="checkbox"]');
  checkboxes.forEach(cb => cb.checked = checked);
  checkSoDConflicts();
}

async function savePermisos() {
  const selected = [...document.querySelectorAll('#permisos-grid input[type="checkbox"]:checked')]
    .map(cb => cb.value);

  const conflicts = sodCatalogCache.filter(c => selected.includes(c.permiso_a) && selected.includes(c.permiso_b));
  if (conflicts.length > 0) {
    const confirmMsg = `Atención: Este rol tiene ${conflicts.length} conflicto(s) de Segregación de Funciones (SoD) de riesgo detectados.\n¿Desea asignar estos permisos de todos modos asumiendo el control compensatorio?`;
    if (!confirm(confirmMsg)) {
      return;
    }
  }
  
  try {
    await apiFetch('/api/admin/roles/' + currentRolId + '/permisos', {
      method: 'PUT',
      body: JSON.stringify({ permisos: selected })
    });
    closePermisosModal();
    await loadAdminData();
  } catch (e) { alert('Error: ' + e.message); }
}

function closePermisosModal() {
  document.getElementById('permisos-modal').style.display = 'none';
  const container = document.getElementById('sod-warnings-container');
  if (container) container.style.display = 'none';
  currentRolId = null;
}

// ============ NOMINA ============

let nominaEmpleadosCache = [];

function calcularNetoEstimado(emp) {
  const salario = parseFloat(emp.salario_base) || 0;
  const auxilio = parseFloat(emp.auxilio_transporte) || 0;
  const totalDevengado = salario + auxilio;
  const basePension = Math.min(salario, 2114985);
  const dedSalud = basePension * 0.04;
  const dedPension = basePension * 0.04;
  return totalDevengado - dedSalud - dedPension;
}

async function loadEmpleados() {
  try {
    const resp = await apiFetch("/api/nomina/empleados");
    const data = await resp.json();
    nominaEmpleadosCache = data;
    renderEmpleadosTable(data);
    updateNominaSummary(data);
    poblarSelectNominaEmpleado();
  } catch (e) {
    console.error("loadEmpleados error:", e);
  }
}

function poblarSelectNominaEmpleado() {
  const sel = document.getElementById("nomina-empleado-select");
  if (!sel) return;
  sel.textContent = "";
  const optVacio = document.createElement("option");
  optVacio.value = "";
  optVacio.textContent = "Seleccione un empleado...";
  sel.appendChild(optVacio);
  nominaEmpleadosCache.filter(e => e.activo === 1).forEach(e => {
    const opt = document.createElement("option");
    opt.value = e.id;
    opt.textContent = `${e.nombres} ${e.apellidos} — ${e.documento}`;
    sel.appendChild(opt);
  });
}

function _periodoNominaSeleccionado() {
  const inicio = document.getElementById("nomina-periodo-inicio").value;
  const fin = document.getElementById("nomina-periodo-fin").value;
  if (!inicio || !fin) {
    alert("Complete las fechas del periodo");
    return null;
  }
  return { periodo_inicio: inicio, periodo_fin: fin };
}

async function liquidarNominaIndividual() {
  const empleadoId = document.getElementById("nomina-empleado-select").value;
  if (!empleadoId) { alert("Seleccione un empleado"); return; }
  const periodo = _periodoNominaSeleccionado();
  if (!periodo) return;
  const box = document.getElementById("resultado-liquidacion");
  box.style.display = "block";
  box.innerHTML = "<b>Liquidando...</b>";
  try {
    const resp = await apiFetch("/api/nomina/liquidar", {
      method: "POST",
      body: JSON.stringify({ empleado_id: parseInt(empleadoId, 10), ...periodo }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      box.innerHTML = `<b style="color:var(--sap-danger);">Error:</b> ${esc(data.error || "Error desconocido")}`;
      return;
    }
    const liq = data.calculacion || data;
    box.innerHTML = `<b style="color:var(--sap-success);">Liquidación calculada</b><br>` +
      `Devengado: ${esc(formatCOP(liq.total_devengado))} | ` +
      `Deducciones: ${esc(formatCOP(liq.total_deducciones))} | ` +
      `Neto: ${esc(formatCOP(liq.neto_pagar))}`;
  } catch (e) {
    box.innerHTML = `<b style="color:var(--sap-danger);">Error de red:</b> ${esc(e.message)}`;
  }
}

async function emitirNominaIndividual() {
  const empleadoId = document.getElementById("nomina-empleado-select").value;
  if (!empleadoId) { alert("Seleccione un empleado"); return; }
  const periodo = _periodoNominaSeleccionado();
  if (!periodo) return;
  const box = document.getElementById("resultado-nomina");
  box.style.display = "block";
  box.innerHTML = "<b>Emitiendo nómina a DIAN...</b>";
  try {
    const resp = await apiFetch("/api/nomina/emitir", {
      method: "POST",
      body: JSON.stringify({ empleado_id: parseInt(empleadoId, 10), ...periodo }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      box.innerHTML = `<b style="color:var(--sap-danger);">Error:</b> ${esc(data.error || "Error desconocido")}`;
      return;
    }
    const nom = data.nomina || {};
    box.innerHTML = `<b style="color:var(--sap-success);">Nómina emitida</b><br>` +
      `Consecutivo: ${esc(nom.consecutivo || "")} | CUNE: ${esc(nom.cune || "")}<br>` +
      `Estado DIAN: ${esc(data.estado_dian || nom.estado_dian || "-")} | ` +
      `Neto: ${esc(formatCOP(nom.neto_pagar))}`;
    await loadNominasHistorial();
  } catch (e) {
    box.innerHTML = `<b style="color:var(--sap-danger);">Error de red:</b> ${esc(e.message)}`;
  }
}

function renderEmpleadosTable(empleados) {
  const tbody = document.querySelector("#tabla-empleados tbody");
  if (!tbody) return;
  const search = document.getElementById("emp-search");
  const term = search ? search.value.toLowerCase() : "";
  
  const filtered = term
    ? empleados.filter(e =>
        (e.nombres + " " + e.apellidos + " " + e.documento).toLowerCase().includes(term)
      )
    : empleados;

  tbody.innerHTML = filtered.map((emp, i) => {
    const neto = calcularNetoEstimado(emp);
    const estadoBadge = emp.activo
      ? '<span class="badge badge-success">Activo</span>'
      : '<span class="badge badge-muted">Inactivo</span>';
    return `<tr>
      <td>${esc(i + 1)}</td>
      <td>${esc(emp.documento)}</td>
      <td>${esc(emp.nombres)} ${esc(emp.apellidos)}</td>
      <td class="text-right">${esc(formatCOP(emp.salario_base))}</td>
      <td class="text-right">${esc(formatCOP(emp.auxilio_transporte))}</td>
      <td class="text-right"><strong>${esc(formatCOP(neto))}</strong></td>
      <td>${estadoBadge}</td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="editEmpleado(${esc(emp.id)})">Editar</button>
      </td>
    </tr>`;
  }).join("");
}

function editEmpleado(id) {
  const emp = nominaEmpleadosCache.find(e => e.id === id);
  if (!emp) return;
  const form = document.getElementById("form-empleado");
  form.style.display = "block";
  document.getElementById("empleado-documento").value = emp.documento;
  document.getElementById("emp-nombres").value = emp.nombres;
  document.getElementById("emp-apellidos").value = emp.apellidos;
  document.getElementById("emp-salario").value = emp.salario_base;
  document.getElementById("emp-auxilio").value = emp.auxilio_transporte || "175405";
  form.dataset.editingId = id;
}

async function guardarEmpleado(e) {
  e.preventDefault();
  const form = e.target;
  const editingId = form.dataset.editingId;
  const payload = {
    tipo_documento: "CC",
    documento: form.querySelector("#empleado-documento").value,
    nombres: form.querySelector("#emp-nombres").value,
    apellidos: form.querySelector("#emp-apellidos").value,
    salario_base: form.querySelector("#emp-salario").value,
    auxilio_transporte: form.querySelector("#emp-auxilio").value,
  };
  try {
    const url = editingId ? `/api/empleados/${encodeURIComponent(editingId)}` : "/api/empleados";
    const method = editingId ? "PUT" : "POST";
    const resp = await apiFetch(url, { method, body: JSON.stringify(payload) });
    if (resp.ok) {
      form.querySelector("#empleado-documento").value = "";
      form.querySelector("#emp-nombres").value = "";
      form.querySelector("#emp-apellidos").value = "";
      form.querySelector("#emp-salario").value = "";
      form.querySelector("#emp-auxilio").value = "175405";
      delete form.dataset.editingId;
      showToast(editingId ? "Empleado actualizado correctamente" : "Empleado creado correctamente", "success");
      await loadEmpleados();
    } else {
      const err = await resp.json();
      alert("Error: " + (err.error || resp.status));
    }
  } catch (e) {
    alert("Error de red: " + e.message);
  }
}

function updateNominaSummary(empleados) {
  const activos = empleados.filter(e => e.activo === 1);
  document.getElementById("nomina-summary-actives").textContent = activos.length;
  
  const totalSalarios = activos.reduce((sum, e) => sum + (parseFloat(e.salario_base) || 0), 0);
  const totalAux = activos.reduce((sum, e) => sum + (parseFloat(e.auxilio_transporte) || 0), 0);
  document.getElementById("nomina-summary-total").textContent = formatCOP(totalSalarios + totalAux);
  
  const totalCargas = activos.reduce((sum, e) => {
    const salario = parseFloat(e.salario_base) || 0;
    const base = salario;
    return sum + base * (0.0866 + 0.0866 + 0.0266 + 0.0142 + 0.0088);
  }, 0);
  document.getElementById("nomina-summary-costo").textContent = formatCOP(totalSalarios + totalAux + totalCargas);
}

async function loadNominasHistorial() {
  try {
    const filtro = document.getElementById("nomina-historial-filtro");
    const estado = filtro ? filtro.value : "";
    let url = "/api/nomina/historial";
    if (estado) url += "?estado_pago=" + estado;
    
    const resp = await apiFetch(url);
    const data = await resp.json();
    const tbody = document.querySelector("#tabla-nominas tbody");
    tbody.innerHTML = data.map(nom => {
      const nombre = nom.nombres ? `${esc(nom.nombres)} ${esc(nom.apellidos)}` : "—";
      const estadoBadge = nom.estado_pago === "PAGADA"
        ? '<span class="badge badge-success">PAGADA</span>'
        : '<span class="badge badge-warning">PENDIENTE</span>';
      const dianBadge = nom.estado_dian === "EMITIDA"
        ? '<span class="badge badge-info">EMITIDA</span>'
        : `<span class="badge badge-muted">${esc(nom.estado_dian || "SIN_EMITIR")}</span>`;
      const btnPago = nom.estado_pago !== "PAGADA"
        ? `<button class="btn btn-sm btn-primary" onclick="pagarNomina(${esc(nom.id)})">Pagar</button>`
        : "—";
      return `<tr>
        <td><input type="checkbox" class="nomina-cb" value="${esc(nom.id)}" ${esc(nom.estado_pago === "PAGADA" ? "disabled" : "")}></td>
        <td>${esc(nom.consecutivo)}</td>
        <td>${esc(nom.periodo_inicio)} → ${esc(nom.periodo_fin)}</td>
        <td>${esc(nombre)}</td>
        <td class="text-right">${esc(formatCOP(nom.total_devengado))}</td>
        <td class="text-right">${esc(formatCOP(nom.total_deducciones))}</td>
        <td class="text-right"><strong>${esc(formatCOP(nom.neto_pagar))}</strong></td>
        <td>${raw(dianBadge)}</td>
        <td>${raw(estadoBadge)}</td>
        <td>${raw(btnPago)}</td>
      </tr>`;
    }).join("");
    
    const selectAll = document.getElementById("nomina-select-all");
    if (selectAll) selectAll.onchange = function() {
      document.querySelectorAll(".nomina-cb:not(:disabled)").forEach(cb => cb.checked = selectAll.checked);
    };
  } catch (e) {
    console.error("loadNominasHistorial error:", e);
  }
}

async function pagarNomina(nominaId) {
  if (!confirm("¿Confirmar pago de esta nómina?")) return;
  try {
    const resp = await apiFetch("/api/nomina/pagar", {
      method: "POST",
      body: JSON.stringify({ nomina_id: nominaId, medio_pago: "EFECTIVO" }),
    });
    const data = await resp.json();
    if (resp.ok) {
      const box = document.getElementById("resultado-pago-nomina");
      box.style.display = "block";
      box.innerHTML = `<b>Pago exitoso:</b> Recibo #${esc(data.recibo.id)} | Monto: ${esc(formatCOP(data.recibo.monto))} | Estado: ${esc(data.estado)}`;
      setTimeout(() => { box.style.display = "none"; }, 4000);
      await loadNominasHistorial();
    } else {
      alert("Error: " + (data.error || resp.status));
    }
  } catch (e) {
    alert("Error de red: " + e.message);
  }
}

async function pagarTodosPendientes() {
  const cbs = [...document.querySelectorAll(".nomina-cb:checked")];
  let ids = cbs.map(cb => parseInt(cb.value));
  
  if (ids.length === 0) {
    const resp = await apiFetch("/api/nomina/historial?estado_pago=PENDIENTE");
    const pendientes = await resp.json();
    ids = pendientes.map(n => n.id);
  }
  
  if (ids.length === 0) {
    alert("No hay nóminas pendientes por pagar.");
    return;
  }
  
  if (!confirm(`¿Confirmar pago de ${esc(ids.length)} nómina(s)?`)) return;
  
  const box = document.getElementById("resultado-pago-nomina");
  box.style.display = "block";
  box.innerHTML = `<b>Procesando pagos...</b>`;
  
  try {
    const resp = await apiFetch("/api/nomina/pagar-todos", {
      method: "POST",
      body: JSON.stringify({ nomina_ids: ids, medio_pago: "EFECTIVO" }),
    });
    const data = await resp.json();
    if (data.exito === 0) {
      box.innerHTML = `<b style="color: var(--sap-danger);">Error:</b> Ninguna nómina pudo pagarse.`;
    } else {
      box.innerHTML = `<b style="color: var(--sap-success);">Pago exitoso:</b> ${esc(data.exito)} de ${esc(data.total)} nómina(s) pagadas.`;
      if (data.errores.length > 0) {
        box.innerHTML += `<br><small style="color: var(--sap-danger);">Errores: ${esc(data.errores.map(e => `#${e.nomina_id}: ${e.error}`).join(", "))}</small>`;
      }
    }
    setTimeout(() => { box.style.display = "none"; }, 5000);
    await loadNominasHistorial();
  } catch (e) {
    alert("Error de red: " + e.message);
  }
}

async function liquidarTodos() {
  const periodoInicio = document.getElementById("nomina-periodo-inicio").value;
  const periodoFin = document.getElementById("nomina-periodo-fin").value;
  if (!periodoInicio || !periodoFin) {
    alert("Complete las fechas del periodo");
    return;
  }
  
  const activos = nominaEmpleadosCache.filter(e => e.activo === 1);
  if (activos.length === 0) {
    alert("No hay empleados activos.");
    return;
  }
  
  const box = document.getElementById("resultado-liquidacion");
  box.style.display = "block";
  box.innerHTML = `<b>Procesando ${esc(activos.length)} liquidaciones...</b>`;
  
  let exitos = 0, fallos = 0;
  const errores = [];
  
  for (const emp of activos) {
    try {
      const resp = await apiFetch("/api/nomina/liquidar", {
        method: "POST",
        body: JSON.stringify({
          empleado_id: emp.id,
          periodo_inicio: periodoInicio,
          periodo_fin: periodoFin,
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        exitos++;
      } else {
        fallos++;
        errores.push(`${esc(emp.nombres)}: ${esc(data.error)}`);
      }
    } catch (e) {
      fallos++;
      errores.push(`${esc(emp.nombres)}: ${esc(e.message)}`);
    }
  }
  
  box.innerHTML = `<b>Liquidaciones:</b> ${esc(exitos)} exitos, ${esc(fallos)} fallos.`;
  if (errores.length > 0) {
    box.innerHTML += `<br><small style="color: var(--sap-danger);">${esc(errores.join(", "))}</small>`;
  }
}

async function emitirTodos() {
  const periodoInicio = document.getElementById("nomina-periodo-inicio").value;
  const periodoFin = document.getElementById("nomina-periodo-fin").value;
  if (!periodoInicio || !periodoFin) {
    alert("Complete las fechas del periodo");
    return;
  }
  
  const activos = nominaEmpleadosCache.filter(e => e.activo === 1);
  if (activos.length === 0) {
    alert("No hay empleados activos.");
    return;
  }
  
  if (!confirm(`¿Emitir nómina para ${esc(activos.length)} empleado(s)?`)) return;
  
  const box = document.getElementById("resultado-nomina");
  box.style.display = "block";
  box.innerHTML = `<b>Procesando ${esc(activos.length)} nominas...</b>`;
  
  let emitidas = 0, fallos = 0;
  const nominaIds = [];
  
  for (const emp of activos) {
    try {
      const resp = await apiFetch("/api/nomina/emitir", {
        method: "POST",
        body: JSON.stringify({
          empleado_id: emp.id,
          periodo_inicio: periodoInicio,
          periodo_fin: periodoFin,
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        emitidas++;
        nominaIds.push(data.nomina.id);
      } else {
        fallos++;
      }
    } catch (e) {
      fallos++;
    }
  }
  
  let msg = `<b>Nominas:</b> ${esc(emitidas)} emitidas, ${esc(fallos)} fallos.`;
  
  if (emitidas > 0) {
    const pagarResp = await apiFetch("/api/nomina/pagar-todos", {
      method: "POST",
      body: JSON.stringify({ nomina_ids: nominaIds, medio_pago: "EFECTIVO" }),
    });
    const pagarData = await pagarResp.json();
    msg += ` Pagos: ${esc(pagarData.exito)} exitos, ${esc(pagarData.fallos)} fallos.`;
  }
  
  box.innerHTML = msg;
  await loadNominasHistorial();
}

function switchNominaTab(tabName) {
  document.querySelectorAll(".nomina-subtab").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".nomina-subtab-content").forEach(content => content.style.display = "none");
  
  const activeBtn = document.querySelector(`.nomina-subtab[data-nomina-tab="${esc(tabName)}"]`);
  if (activeBtn) activeBtn.classList.add("active");
  
  const content = document.getElementById(`nomina-sub-${esc(tabName)}`);
  if (content) content.style.display = "block";
  
  if (tabName === "historial") {
    loadNominasHistorial();
  }
}

document.querySelectorAll(".nomina-subtab").forEach(btn => {
  btn.addEventListener("click", () => {
    switchNominaTab(btn.dataset.nominaTab);
  });
});
document.getElementById("nomina-historial-filtro").addEventListener("change", () => {
  loadNominasHistorial();
});

// ============ IMPORTACIONES MASIVAS ============

const IMPORT_TYPES = {
  facturas: "Facturas de Venta",
  saldos_iniciales: "Saldos Iniciales",
  toma_inventario: "Toma de Inventario"
};

function updateImportUI() {
  const tipo = document.getElementById("import-tipo").value;
  const btnImport = document.getElementById("btn-import");
  btnImport.disabled = !tipo;
}

document.getElementById("import-file").addEventListener("change", function(e) {
  const file = e.target.files[0];
  const fileNameSpan = document.getElementById("selected-file-name");
  if (file) {
    fileNameSpan.textContent = file.name;
  }
});

function updateProgress(percent) {
  const progressDiv = document.getElementById("import-progress");
  const fill = document.getElementById("progress-fill");
  const text = document.getElementById("progress-text");
  progressDiv.style.display = "flex";
  fill.style.width = percent + "%";
  text.textContent = percent + "%";
}

function showResults(data) {
  const resultsDiv = document.getElementById("import-results");
  const tipo = document.getElementById("import-tipo").value;
  const typeName = IMPORT_TYPES[tipo] || "Importación";
  
  let html = `
    <h4 style="margin-bottom: 16px;">Resultado de la Importación: ${esc(typeName)}</h4>
    <div class="result-summary">
      <div class="stat-box success">
        <div class="stat-value">${esc(data.success_count || 0)}</div>
        <div class="stat-label">Éxitos</div>
      </div>
      <div class="stat-box error">
        <div class="stat-value">${esc(data.error_count || 0)}</div>
        <div class="stat-label">Errores</div>
      </div>
    </div>
  `;
  
  if (data.errors && data.errors.length > 0) {
    html += `
      <h5>Detalles de Errores:</h5>
      <table>
        <thead>
          <tr><th>Línea</th><th>Descripción</th></tr>
        </thead>
        <tbody>
    `;
    data.errors.forEach(err => {
      html += `<tr class="error-row"><td>${esc(err.line || '-')}</td><td class="error-msg">${esc(err.message)}</td></tr>`;
    });
    html += `</tbody></table>`;
  }
  
  resultsDiv.innerHTML = html;
  resultsDiv.style.display = "block";
}

function _fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result || "");
      const idx = res.indexOf(",");
      resolve(idx >= 0 ? res.slice(idx + 1) : res);
    };
    reader.onerror = (err) => reject(err);
    reader.readAsDataURL(file);
  });
}

async function startImport() {
  const tipo = document.getElementById("import-tipo").value;
  const fileInput = document.getElementById("import-file");
  const file = fileInput.files[0];
  
  if (!tipo) {
    alert("Por favor seleccione un tipo de importación.");
    return;
  }
  
  if (!file) {
    alert("Por favor seleccione un archivo.");
    return;
  }
  
  const btnImport = document.getElementById("btn-import");
  btnImport.disabled = true;
  btnImport.textContent = "Importando...";
  
  try {
    updateProgress(10);
    const content_b64 = await _fileToBase64(file);
    const formato = file.name.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv";
    const endpointTipo = tipo.replace(/_/g, "-");
    
    const res = await apiFetch("/api/importaciones/" + endpointTipo, {
      method: "POST",
      body: JSON.stringify({ content_b64, formato })
    });
    
    updateProgress(90);
    
    const data = await res.json();
    updateProgress(100);
    
    if (res.ok) {
      showResults(data);
    } else {
      alert("Error en la importación: " + (data.error || "Error desconocido"));
    }
  } catch (err) {
    alert("Error de red: " + err.message);
  } finally {
    btnImport.disabled = false;
    btnImport.textContent = "Importar";
  }
}

function downloadTemplate() {
  const tipo = document.getElementById("import-tipo").value;
  if (!tipo) {
    alert("Por favor seleccione un tipo de importación.");
    return;
  }
  downloadWithAuth(`/api/importaciones/plantilla?tipo=${encodeURIComponent(tipo)}`, `plantilla_${tipo}.csv`);
}

// ============ EVENT LISTENERS ============

const formEmpresa = document.getElementById('form-empresa');
if (formEmpresa) formEmpresa.addEventListener('submit', saveEmpresa);
const formUsuario = document.getElementById('form-usuario');
if (formUsuario) formUsuario.addEventListener('submit', saveUsuario);
const formRol = document.getElementById('form-rol');
if (formRol) formRol.addEventListener('submit', saveRol);

document.getElementById("btn-new-empresa").addEventListener("click", () => showEmpresaForm(null));
const btnNewUsuario = document.getElementById("btn-new-usuario");
if (btnNewUsuario) btnNewUsuario.addEventListener("click", () => showUsuarioForm(null));
const btnCancelUsuario = document.getElementById("btn-cancel-usuario");
if (btnCancelUsuario) btnCancelUsuario.addEventListener("click", () => {
  const card = document.getElementById("card-usuario-form");
  if (card) card.style.display = "none";
});
const btnNewRol = document.getElementById("btn-new-rol");
if (btnNewRol) btnNewRol.addEventListener("click", () => showRolForm(null));
const btnCancelRol = document.getElementById("btn-cancel-rol");
if (btnCancelRol) btnCancelRol.addEventListener("click", () => {
  const card = document.getElementById("card-rol-form");
  if (card) card.style.display = "none";
});
const btnAsigUE = document.getElementById("btn-asignar-usuario-empresa");
if (btnAsigUE) btnAsigUE.addEventListener("click", asignarUsuarioEmpresa);
document.getElementById("btn-add-linea").addEventListener("click", addLinea);
document.getElementById("form-empleado").addEventListener("submit", guardarEmpleado);
document.getElementById("btn-liquidar-todos").addEventListener("click", liquidarTodos);
document.getElementById("btn-emitir-todos").addEventListener("click", emitirTodos);
document.getElementById("btn-pagar-pendientes").addEventListener("click", pagarTodosPendientes);
document.getElementById("btn-toggle-form-empleado").addEventListener("click", () => {
  const form = document.getElementById("form-empleado");
  delete form.dataset.editingId;
  form.style.display = form.style.display === "none" ? "block" : "none";
});
document.getElementById("emp-search").addEventListener("input", () => {
  renderEmpleadosTable(nominaEmpleadosCache);
});
document.getElementById("btn-emitir-dian").addEventListener("click", emitirFactura);
document.getElementById("btn-emitir-nc").addEventListener("click", emitirNotaCredito);
const btnEmitirNd = document.getElementById("btn-emitir-nd");
if (btnEmitirNd) btnEmitirNd.addEventListener("click", emitirNotaDebito);
document.getElementById("btn-add-ds-linea").addEventListener("click", addDsLinea);
document.getElementById("btn-emitir-ds").addEventListener("click", emitirDocumentoSoporte);
document.getElementById("btn-cancel-empresa").addEventListener("click", () => {
  document.getElementById('card-empresa-form').style.display = 'none';
});
document.getElementById("btn-close-recaudo").addEventListener("click", cerrarModalRecaudo);
document.getElementById("btn-cancel-recaudo").addEventListener("click", cerrarModalRecaudo);
document.getElementById("btn-confirmar-recaudo").addEventListener("click", confirmarRecaudo);
document.getElementById("btn-download-template").addEventListener("click", downloadTemplate);
const btnLiqNom = document.getElementById("btn-liquidar-nomina");
if (btnLiqNom) btnLiqNom.addEventListener("click", liquidarNominaIndividual);
const btnEmiNom = document.getElementById("btn-emitir-nomina");
if (btnEmiNom) btnEmiNom.addEventListener("click", emitirNominaIndividual);

// ============ SEGURIDAD 2FA / TOTP ============

async function load2faStatus() {
  try {
    const res = await apiFetch("/api/auth/2fa/status");
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById("2fa-badge-status");
    const btnInit = document.getElementById("btn-init-2fa");
    const btnDisable = document.getElementById("btn-disable-2fa");
    if (data.enabled) {
      if (badge) {
        badge.className = "badge badge-success";
        badge.textContent = "Estado 2FA: ACTIVO (Google Authenticator / Authy)";
      }
      if (btnInit) btnInit.style.display = "none";
      if (btnDisable) btnDisable.style.display = "inline-block";
    } else {
      if (badge) {
        badge.className = "badge badge-secondary";
        badge.textContent = "Estado 2FA: INACTIVO";
      }
      if (btnInit) btnInit.style.display = "inline-block";
      if (btnDisable) btnDisable.style.display = "none";
    }
  } catch (err) {
    console.error("Error loading 2FA status:", err);
  }
}

async function init2faSetup() {
  try {
    const res = await apiFetch("/api/auth/2fa/setup", { method: "POST" });
    if (!res.ok) {
      showToast("Error al inicializar 2FA", "error");
      return;
    }
    const data = await res.json();
    window._temp2faSecret = data.secret;
    const disp = document.getElementById("2fa-secret-display");
    if (disp) disp.textContent = data.secret;
    const panel = document.getElementById("2fa-setup-panel");
    if (panel) panel.style.display = "block";
  } catch (err) {
    showToast("Error al configurar 2FA", "error");
  }
}

async function confirmEnable2fa() {
  const code = (document.getElementById("2fa-verify-code")?.value || "").trim();
  if (!code || code.length !== 6) {
    showToast("Ingrese un código de 6 dígitos válido", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/auth/2fa/verify", {
      method: "POST",
      body: JSON.stringify({ secret: window._temp2faSecret, codigo: code }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || "Código incorrecto", "error");
      return;
    }
    showToast("¡Autenticación 2FA activada con éxito!", "success");
    document.getElementById("2fa-setup-panel").style.display = "none";
    document.getElementById("2fa-verify-code").value = "";
    load2faStatus();
  } catch (err) {
    showToast("Error al verificar código 2FA", "error");
  }
}

async function disable2fa() {
  if (!confirm("¿Está seguro de desactivar la autenticación de dos factores (2FA)?")) return;
  try {
    const res = await apiFetch("/api/auth/2fa/disable", { method: "POST" });
    if (res.ok) {
      showToast("2FA desactivado correctamente", "info");
      load2faStatus();
    }
  } catch (err) {
    showToast("Error al desactivar 2FA", "error");
  }
}

// ============ CICLO COMERCIAL (VENTAS) ============

let cotLineas = [];

function loadCicloComercial() {
  loadCotizaciones();
  loadPedidos();
  populateCicloSelects();
}

function populateCicloSelects() {
  const selCli = document.getElementById("cot-cliente");
  if (selCli) {
    selCli.innerHTML = clientesList.map(c => `<option value="${esc(c.nit)}">${esc(c.razon_social)} (${esc(c.nit)})</option>`).join("");
  }
  const selProd = document.getElementById("cot-prod");
  if (selProd) {
    selProd.innerHTML = productosList.map(p => `<option value="${esc(p.codigo)}">${esc(p.descripcion)} - ${formatCOP(p.precio_unitario)}</option>`).join("");
    if (productosList.length > 0 && document.getElementById("cot-precio")) {
      document.getElementById("cot-precio").value = productosList[0].precio_unitario || "0";
    }
  }
}

function addLineaCot() {
  const prodSelect = document.getElementById("cot-prod");
  const cantInput = document.getElementById("cot-cant");
  const precioInput = document.getElementById("cot-precio");
  if (!prodSelect || !cantInput || !precioInput) return;
  const prodCode = prodSelect.value;
  const prod = productosList.find(p => p.codigo === prodCode) || { descripcion: prodCode, tarifa_iva: "IVA_19" };
  const cant = parseFloat(cantInput.value) || 1;
  const precio = parseFloat(precioInput.value) || 0;
  const subtotal = cant * precio;
  const iva = (prod.tarifa_iva === "IVA_19" ? subtotal * 0.19 : (prod.tarifa_iva === "IVA_5" ? subtotal * 0.05 : 0));
  const total = subtotal + iva;

  cotLineas.push({
    producto_codigo: prodCode,
    descripcion: prod.descripcion,
    cantidad: cant,
    valor_unitario: precio,
    tarifa_iva: prod.tarifa_iva || "IVA_19",
    subtotal: subtotal.toFixed(2),
    total: total.toFixed(2),
  });
  renderCotLineas();
}

function renderCotLineas() {
  const tbody = document.getElementById("cot-lineas-tbody");
  if (!tbody) return;
  tbody.innerHTML = cotLineas.map((l, idx) => `
    <tr>
      <td>${esc(l.producto_codigo)}</td>
      <td>${esc(l.descripcion)}</td>
      <td>${l.cantidad}</td>
      <td>${formatCOP(l.valor_unitario)}</td>
      <td>${esc(l.tarifa_iva)}</td>
      <td>${formatCOP(l.total)}</td>
      <td><button type="button" class="btn btn-sm btn-danger" onclick="removeCotLinea(${idx})">✕</button></td>
    </tr>
  `).join("");
}

function removeCotLinea(idx) {
  cotLineas.splice(idx, 1);
  renderCotLineas();
}

async function guardarCotizacion(e) {
  if (e) e.preventDefault();
  const cli = document.getElementById("cot-cliente")?.value;
  const venc = document.getElementById("cot-vencimiento")?.value;
  const desc = document.getElementById("cot-descuento")?.value || 0;
  const obs = document.getElementById("cot-observaciones")?.value;
  if (!cli) {
    showToast("Seleccione un cliente", "warning");
    return;
  }
  if (cotLineas.length === 0) {
    showToast("Agregue al menos un ítem a la cotización", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/ventas/cotizaciones", {
      method: "POST",
      body: JSON.stringify({
        cliente_nit: cli,
        fecha_vencimiento: venc,
        descuento_porcentaje: desc,
        observaciones: obs,
        lineas: cotLineas
      }),
    });
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.error || "Error guardando cotización");
    }
    const created = await res.json();
    if (created.estado === "REQUIERE_APROBACION") {
      showToast("Cotización guardada: Requiere aprobación por descuento > 15%", "warning");
    } else {
      showToast("Cotización guardada exitosamente", "success");
    }
    cotLineas = [];
    renderCotLineas();
    loadCicloComercial();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadCotizaciones() {
  try {
    const res = await apiFetch("/api/ventas/cotizaciones");
    if (!res.ok) return;
    const cots = await res.json();
    const tbody = document.getElementById("tbody-cotizaciones");
    if (!tbody) return;
    const canApprove = currentUser && (
      ["ADMIN", "SUPERADMIN", "ADMIN_EMPRESA"].includes(currentUser.rol) ||
      userPermissions.includes("ventas:update") ||
      userPermissions.includes("*")
    );
    tbody.innerHTML = cots.map(c => {
      let estadoBadge = `<span class="badge badge-info">${esc(c.estado)}</span>`;
      let accionBtn = '';
      if (c.estado === 'REQUIERE_APROBACION') {
        estadoBadge = `<span class="badge" style="background:#dd6b20;color:#fff;">⚠️ Dto ${esc(c.descuento_porcentaje)}% (Por Aprobar)</span>`;
        if (canApprove) {
          accionBtn = `<button class="btn btn-sm btn-warning" onclick="aprobarCotizacionDescuento(${c.id})">✅ Aprobar Dto</button>`;
        } else {
          accionBtn = `<span class="text-muted" style="font-size:11px;" title="Requiere rol de administración o supervisor">🔒 Pendiente Aprobación</span>`;
        }
      } else if (c.estado === 'COTIZADO') {
        accionBtn = `<button class="btn btn-sm btn-primary" onclick="convertirCotizacionAPedido(${c.id})">Aprobar y Pedido ➔</button>`;
      } else if (c.estado === 'APROBADO') {
        estadoBadge = `<span class="badge badge-success">APROBADO</span>`;
        accionBtn = `<span class="text-muted">En Pedido</span>`;
      }
      return `
        <tr>
          <td>${esc(c.id)}</td>
          <td><strong>${esc(c.consecutivo)}</strong></td>
          <td>${esc(c.cliente_nit)}</td>
          <td>${esc(c.fecha)}</td>
          <td>${formatCOP(c.total)}</td>
          <td>${estadoBadge}</td>
          <td>${accionBtn}</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Error loading cotizaciones:", err);
  }
}

async function aprobarCotizacionDescuento(cotId) {
  try {
    const res = await apiFetch(`/api/ventas/cotizaciones/${cotId}/aprobar`, { method: "POST" });
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.error || "No se pudo aprobar");
    }
    showToast("Cotización aprobada por gerencia comercial", "success");
    loadCotizaciones();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadPedidos() {
  try {
    const res = await apiFetch("/api/ventas/pedidos");
    if (!res.ok) return;
    const peds = await res.json();
    const tbody = document.getElementById("tbody-pedidos");
    if (!tbody) return;
    tbody.innerHTML = peds.map(p => `
      <tr>
        <td>${esc(p.id)}</td>
        <td><strong>${esc(p.consecutivo)}</strong></td>
        <td>${esc(p.cliente_nit)}</td>
        <td>${esc(p.fecha)}</td>
        <td>${formatCOP(p.total)}</td>
        <td><span class="badge ${p.estado === 'FACTURADO' ? 'badge-success' : (p.estado === 'DESPACHADO' ? 'badge-warning' : 'badge-info')}">${esc(p.estado)}</span></td>
        <td>
          ${p.estado === 'PENDIENTE' ? `
            <button class="btn btn-sm btn-secondary" onclick="convertirPedidoARemision(${p.id})">Remisión</button>
            <button class="btn btn-sm btn-primary" onclick="convertirPedidoAFactura(${p.id})">Facturar 1-Clic ⚡</button>
          ` : (p.estado === 'DESPACHADO' ? `
            <button class="btn btn-sm btn-primary" onclick="convertirPedidoAFactura(${p.id})">Facturar 1-Clic ⚡</button>
          ` : `<span class="badge badge-success">Factura DIAN Emitida</span>`)}
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Error loading pedidos:", err);
  }
}

async function convertirCotizacionAPedido(cotId) {
  try {
    const res = await apiFetch(`/api/ventas/cotizaciones/${cotId}/convertir-pedido`, { method: "POST" });
    if (!res.ok) throw new Error("No se pudo convertir");
    showToast("Cotización aprobada y convertida a Pedido de Venta", "success");
    loadCicloComercial();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function convertirPedidoARemision(pedId) {
  try {
    const res = await apiFetch(`/api/ventas/pedidos/${pedId}/convertir-remision`, { method: "POST" });
    if (!res.ok) throw new Error("No se pudo generar remisión");
    showToast("Remisión de despacho generada con éxito", "success");
    loadPedidos();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function convertirPedidoAFactura(pedId) {
  try {
    const res = await apiFetch(`/api/ventas/pedidos/${pedId}/convertir-factura`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error al facturar");
    }
    const data = await res.json();
    showToast(`¡Factura ${data.prefijo}-${data.consecutivo} emitida y transmitida a la DIAN!`, "success");
    loadPedidos();
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============ POS ELECTRÓNICO ============

let currentPosSesion = null;

async function loadPosData() {
  loadPosCajas();
  loadPosSesiones();
}

async function loadPosCajas() {
  try {
    const res = await apiFetch("/api/pos/cajas");
    if (!res.ok) return;
    const cajas = await res.json();
    const sel = document.getElementById("pos-select-caja");
    if (!sel) return;
    if (cajas.length === 0) {
      await apiFetch("/api/pos/cajas", {
        method: "POST",
        body: JSON.stringify({ nombre: "Caja Principal 01", ubicacion: "Mostrador 1" }),
      });
      return loadPosCajas();
    }
    sel.innerHTML = cajas.map(c => `<option value="${esc(c.id)}">${esc(c.nombre)} (${esc(c.ubicacion || 'Principal')})</option>`).join("");
  } catch (err) {
    console.error("Error loading POS cajas:", err);
  }
}

async function loadPosSesiones() {
  try {
    const res = await apiFetch("/api/pos/sesiones");
    if (!res.ok) return;
    const sesiones = await res.json();
    const abierta = sesiones.find(s => s.estado === "ABIERTA");
    currentPosSesion = abierta || null;

    const nomEl = document.getElementById("pos-caja-activa-nom");
    const estEl = document.getElementById("pos-turno-estado");
    const baseEl = document.getElementById("pos-base-inicial");
    const ventasEl = document.getElementById("pos-ventas-turno");
    const btnAbrir = document.getElementById("btn-pos-abrir-caja");
    const btnCerrar = document.getElementById("btn-pos-cerrar-caja");

    if (abierta) {
      if (nomEl) nomEl.textContent = abierta.caja_nombre || `Caja #${abierta.caja_id}`;
      if (estEl) estEl.textContent = "ABIERTO";
      if (baseEl) baseEl.textContent = formatCOP(abierta.monto_inicial);
      if (ventasEl) ventasEl.textContent = formatCOP(abierta.total_ventas_efectivo);
      if (btnAbrir) btnAbrir.style.display = "none";
      if (btnCerrar) btnCerrar.style.display = "inline-block";
    } else {
      if (nomEl) nomEl.textContent = "Sin Caja Abierta";
      if (estEl) estEl.textContent = "CERRADO";
      if (baseEl) baseEl.textContent = "$0";
      if (ventasEl) ventasEl.textContent = "$0";
      if (btnAbrir) btnAbrir.style.display = "inline-block";
      if (btnCerrar) btnCerrar.style.display = "none";
    }
  } catch (err) {
    console.error("Error loading POS sesiones:", err);
  }
}

async function abrirTurnoCaja() {
  const cajaId = document.getElementById("pos-select-caja")?.value;
  const monto = document.getElementById("pos-monto-base")?.value || "100000";
  if (!cajaId) {
    showToast("Seleccione una caja", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/pos/abrir-caja", {
      method: "POST",
      body: JSON.stringify({ caja_id: cajaId, monto_inicial: monto }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error al abrir caja");
    }
    showToast("Turno de caja abierto correctamente", "success");
    loadPosSesiones();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function openArqueoModal() {
  if (!currentPosSesion) return;
  document.getElementById("pos-arqueo-esperado").textContent = formatCOP(currentPosSesion.total_esperado || currentPosSesion.monto_inicial);
  document.getElementById("modal-pos-arqueo").style.display = "flex";
}

function closeArqueoModal() {
  document.getElementById("modal-pos-arqueo").style.display = "none";
}

async function confirmarArqueoCaja() {
  if (!currentPosSesion) return;
  const conteo = document.getElementById("pos-conteo-fisico")?.value;
  const obs = document.getElementById("pos-arqueo-obs")?.value || "";
  if (!conteo) {
    showToast("Ingrese el conteo físico en efectivo", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/pos/cerrar-caja", {
      method: "POST",
      body: JSON.stringify({ sesion_id: currentPosSesion.id, total_real: conteo, observaciones: obs }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error al cerrar");
    }
    const data = await res.json();
    closeArqueoModal();
    showToast(`Arqueo completado: Descuadre = ${formatCOP(data.diferencia)} (${data.descuadre_tipo})`, data.diferencia == 0 ? "success" : "warning");
    loadPosSesiones();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function verTirillaPos(facturaId) {
  try {
    const res = await apiFetch(`/api/pos/ticket/${facturaId}?ancho=80`);
    if (!res.ok) throw new Error("No se pudo generar tirilla");
    const data = await res.json();
    document.getElementById("pos-ticket-preview").textContent = data.texto_ticket;
    document.getElementById("card-pos-ticket").style.display = "block";
    switchTab("pos");
  } catch (err) {
    showToast(err.message, "error");
  }
}

function imprimirTirillaPos() {
  window.print();
}

// ============ BUZÓN DE COMPRAS & CXP ============

async function loadComprasCxp() {
  loadComprasFacturas();
  loadCxpData();
}

async function loadComprasFacturas() {
  try {
    const res = await apiFetch("/api/compras/facturas");
    if (!res.ok) return;
    const facturas = await res.json();
    const tbody = document.getElementById("tbody-compras");
    if (!tbody) return;
    tbody.innerHTML = facturas.map(f => `
      <tr>
        <td>${esc(f.id)}</td>
        <td><strong>${esc(f.proveedor_nombre)}</strong><br><small class="text-muted">NIT: ${esc(f.proveedor_nit)}</small></td>
        <td>${esc(f.prefijo || '')}-${esc(f.consecutivo)}</td>
        <td>${esc(f.fecha)}</td>
        <td>${formatCOP(f.subtotal)}</td>
        <td>${formatCOP(f.total_iva)}</td>
        <td><strong>${formatCOP(f.total)}</strong></td>
        <td><span class="badge ${f.estado_radian.includes('ACEPTADO') ? 'badge-success' : (f.estado_radian.includes('RECIBIDO') ? 'badge-info' : 'badge-warning')}">${esc(f.estado_radian)}</span></td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="emitirEventoRadian(${f.id}, '030')">030 Acuse</button>
          <button class="btn btn-sm btn-secondary" onclick="emitirEventoRadian(${f.id}, '032')">032 Bienes</button>
          <button class="btn btn-sm btn-primary" onclick="emitirEventoRadian(${f.id}, '033')">033 Aceptación</button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Error loading compras:", err);
  }
}

async function loadCxpData() {
  try {
    const res = await apiFetch("/api/cxp/edades");
    if (!res.ok) return;
    const data = await res.json();
    document.getElementById("cxp-kpi-corriente").textContent = formatCOP(data.corriente);
    document.getElementById("cxp-kpi-1-30").textContent = formatCOP(data["1_30"]);
    document.getElementById("cxp-kpi-31-60").textContent = formatCOP(data["31_60"]);
    document.getElementById("cxp-kpi-mas-90").textContent = formatCOP(data.mas_90);
    document.getElementById("cxp-kpi-total").textContent = formatCOP(data.total_deuda);

    const tbody = document.getElementById("tbody-cxp");
    if (!tbody) return;
    tbody.innerHTML = (data.facturas || []).map(f => `
      <tr>
        <td>${esc(f.id)}</td>
        <td>${esc(f.proveedor_nombre || f.proveedor_nit)}</td>
        <td>${esc(f.prefijo || '')}-${esc(f.consecutivo || f.factura_compra_id)}</td>
        <td>${esc(f.fecha_vencimiento || '-')} ${f.es_vencida ? `<span class="badge badge-danger">${f.dias_vencido}d mora</span>` : ''}</td>
        <td>${formatCOP(f.monto_total)}</td>
        <td><strong>${formatCOP(f.saldo_pendiente)}</strong></td>
        <td><span class="badge ${f.estado === 'PAGADA' ? 'badge-success' : 'badge-warning'}">${esc(f.estado)}</span></td>
        <td>
          <button class="btn btn-sm btn-primary" onclick="abrirModalEgreso(${f.factura_compra_id}, '${esc(f.proveedor_nombre || f.proveedor_nit)}', '${esc(f.saldo_pendiente)}')">Pagar (CE)</button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Error loading CxP:", err);
  }
}

async function emitirEventoRadian(facturaCompraId, codigoEvento) {
  try {
    const res = await apiFetch("/api/compras/radian-evento", {
      method: "POST",
      body: JSON.stringify({ factura_compra_id: facturaCompraId, codigo_evento: codigoEvento }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error al emitir evento RADIAN");
    }
    const data = await res.json();
    showToast(`Evento RADIAN ${codigoEvento} emitido exitosamente. CUDE: ${data.cude.substring(0, 16)}...`, "success");
    loadComprasFacturas();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function abrirModalEgreso(fcId, provNombre, saldo) {
  document.getElementById("egreso-fc-id").value = fcId;
  document.getElementById("egreso-proveedor-info").textContent = `${provNombre} — Saldo pendiente: ${formatCOP(saldo)}`;
  document.getElementById("egreso-monto").value = parseFloat(saldo) || 0;
  document.getElementById("modal-cxp-egreso").style.display = "flex";
}

function closeEgresoModal() {
  document.getElementById("modal-cxp-egreso").style.display = "none";
}

async function confirmarEgreso() {
  const fcId = document.getElementById("egreso-fc-id")?.value;
  const monto = document.getElementById("egreso-monto")?.value;
  const medio = document.getElementById("egreso-medio-pago")?.value || "TRANSFERENCIA";
  const obs = document.getElementById("egreso-obs")?.value || "";
  if (!monto || parseFloat(monto) <= 0) {
    showToast("Ingrese un monto válido", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/cxp/egreso", {
      method: "POST",
      body: JSON.stringify({ factura_compra_id: fcId ? parseInt(fcId) : null, monto, medio_pago: medio, observaciones: obs }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error al registrar egreso");
    }
    closeEgresoModal();
    showToast("Comprobante de Egreso registrado y causado en contabilidad", "success");
    loadCxpData();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function procesarArchivoCompra() {
  const fileInput = document.getElementById("compra-file-input");
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    showToast("Seleccione un archivo XML o ZIP de factura de proveedor", "warning");
    return;
  }
  const file = fileInput.files[0];
  const reader = new FileReader();

  if (file.name.toLowerCase().endsWith(".zip")) {
    reader.onload = async (e) => {
      const arrayBuffer = e.target.result;
      const bytes = new Uint8Array(arrayBuffer);
      let binary = "";
      for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
      const b64 = btoa(binary);
      enviarCompraXml(b64, true);
    };
    reader.readAsArrayBuffer(file);
  } else {
    reader.onload = async (e) => {
      enviarCompraXml(e.target.result, false);
    };
    reader.readAsText(file);
  }
}

async function enviarCompraXml(content, esBase64) {
  try {
    const res = await apiFetch("/api/compras/procesar-xml", {
      method: "POST",
      body: JSON.stringify({ xml: content, es_base64: esBase64 }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error al procesar factura de proveedor");
    }
    const data = await res.json();
    showToast(`¡Factura ${data.prefijo || ''}-${data.consecutivo} de ${data.proveedor_nombre} causada exitosamente!`, "success");
    document.getElementById("compra-file-input").value = "";
    loadComprasCxp();
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============ IMPUESTOS DIAN (FORMULARIOS 300 / 350) ============

function loadImpuestosTab() {
  const anio = new Date().getFullYear();
  if (document.getElementById("f300-anio")) document.getElementById("f300-anio").value = anio;
  if (document.getElementById("f350-anio")) document.getElementById("f350-anio").value = anio;
}

async function calcularF300() {
  const bim = document.getElementById("f300-bimestre")?.value || "1";
  const anio = document.getElementById("f300-anio")?.value || "2026";
  try {
    const res = await apiFetch(`/api/impuestos/formulario-300?bimestre=${bim}&anio=${anio}`);
    if (!res.ok) throw new Error("Error calculando Formulario 300");
    const data = await res.json();
    const tbody = document.getElementById("f300-tbody");
    const r = data.renglones;
    tbody.innerHTML = `
      <tr><td><strong>27</strong></td><td>Ingresos brutos operaciones gravadas tarifa general (19%)</td><td>${formatCOP(r["27_ingresos_gravados_19"])}</td></tr>
      <tr><td><strong>28</strong></td><td>Ingresos brutos operaciones gravadas tarifa del 5%</td><td>${formatCOP(r["28_ingresos_gravados_5"])}</td></tr>
      <tr><td><strong>29</strong></td><td>Ingresos brutos operaciones no gravadas o excluidas (0%)</td><td>${formatCOP(r["29_ingresos_no_gravados_excluidos"])}</td></tr>
      <tr style="background:#f1f5f9;"><td><strong>34</strong></td><td><strong>Total ingresos brutos</strong></td><td><strong>${formatCOP(r["34_total_ingresos_brutos"])}</strong></td></tr>
      <tr style="background:#f1f5f9;"><td><strong>41</strong></td><td><strong>Total ingresos netos del periodo</strong></td><td><strong>${formatCOP(r["41_total_ingresos_netos"])}</strong></td></tr>
      <tr><td><strong>59</strong></td><td>Impuesto sobre las ventas generado a la tarifa general (19%)</td><td>${formatCOP(r["59_impuesto_generado_19"])}</td></tr>
      <tr><td><strong>60</strong></td><td>Impuesto sobre las ventas generado a la tarifa del 5%</td><td>${formatCOP(r["60_impuesto_generado_5"])}</td></tr>
      <tr style="background:#f1f5f9;"><td><strong>67</strong></td><td><strong>Total impuesto generado</strong></td><td><strong>${formatCOP(r["67_total_impuesto_generado"])}</strong></td></tr>
      <tr><td><strong>78</strong></td><td>IVA descontable por compras de bienes y servicios nacionales</td><td>${formatCOP(r["78_iva_descontable_compras"])}</td></tr>
      <tr style="background:#f1f5f9;"><td><strong>82</strong></td><td><strong>Total impuestos descontables</strong></td><td><strong>${formatCOP(r["82_total_impuestos_descontables"])}</strong></td></tr>
      <tr style="background:#e0f2fe; font-size:1.1em;"><td><strong>83</strong></td><td><strong>SALDO A PAGAR POR EL PERIODO FISCAL</strong></td><td><strong>${formatCOP(r["83_saldo_a_pagar"])}</strong></td></tr>
      <tr><td><strong>84</strong></td><td>Saldo a favor por el periodo fiscal</td><td>${formatCOP(r["84_saldo_a_favor"])}</td></tr>
    `;
    document.getElementById("f300-resultado").style.display = "block";
    showToast("Formulario 300 liquidado correctamente", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function calcularF350() {
  const mes = document.getElementById("f350-mes")?.value || "1";
  const anio = document.getElementById("f350-anio")?.value || "2026";
  try {
    const res = await apiFetch(`/api/impuestos/formulario-350?mes=${mes}&anio=${anio}`);
    if (!res.ok) throw new Error("Error calculando Formulario 350");
    const data = await res.json();
    const tbody = document.getElementById("f350-tbody");
    const r = data.renglones;
    tbody.innerHTML = `
      <tr><td><strong>50</strong></td><td>Retención en la fuente por compras generales</td><td>${formatCOP(r["50_retencion_compras"])}</td></tr>
      <tr><td><strong>51</strong></td><td>Retención en la fuente por servicios</td><td>${formatCOP(r["51_retencion_servicios"])}</td></tr>
      <tr><td><strong>52</strong></td><td>Retención en la fuente por honorarios y comisiones</td><td>${formatCOP(r["52_retencion_honorarios"])}</td></tr>
      <tr><td><strong>53</strong></td><td>Retención en la fuente por pagos laborales</td><td>${formatCOP(r["53_retencion_pagos_laborales"])}</td></tr>
      <tr><td><strong>84</strong></td><td>Retenciones de IVA practicadas (ReteIVA)</td><td>${formatCOP(r["84_retenciones_iva"])}</td></tr>
      <tr style="background:#e0f2fe; font-size:1.1em;"><td><strong>87</strong></td><td><strong>TOTAL RETENCIONES / SALDO A PAGAR</strong></td><td><strong>${formatCOP(r["87_total_retenciones"])}</strong></td></tr>
    `;
    document.getElementById("f350-resultado").style.display = "block";
    showToast("Formulario 350 liquidado correctamente", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============ LISTAS DE PRECIOS & TRASLADOS ============

async function loadPreciosTab() {
  loadListasPrecios();
  populatePreciosSelects();
}

async function populatePreciosSelects() {
  const prodSel = document.getElementById("asig-prod-select");
  const trasSel = document.getElementById("tras-prod");
  const html = productosList.map(p => `<option value="${esc(p.codigo)}">${esc(p.descripcion)} (${esc(p.codigo)})</option>`).join("");
  if (prodSel) prodSel.innerHTML = html;
  if (trasSel) trasSel.innerHTML = html;
}

async function loadListasPrecios() {
  try {
    const res = await apiFetch("/api/listas-precios");
    if (!res.ok) return;
    const listas = await res.json();
    const tbody = document.getElementById("tbody-listas-precios");
    const sel = document.getElementById("asig-lp-select");
    if (tbody) {
      tbody.innerHTML = listas.map(l => `
        <tr>
          <td>${esc(l.id)}</td>
          <td><strong>${esc(l.nombre)}</strong></td>
          <td>${esc(l.descripcion || '-')}</td>
          <td><button class="btn btn-sm btn-secondary" onclick="verPreciosLista(${l.id})">Ver Precios</button></td>
        </tr>
      `).join("");
    }
    if (sel) {
      sel.innerHTML = listas.map(l => `<option value="${esc(l.id)}">${esc(l.nombre)}</option>`).join("");
    }
  } catch (err) {
    console.error("Error loading listas precios:", err);
  }
}

async function verPreciosLista(listaId) {
  try {
    const res = await apiFetch(`/api/listas-precios/${encodeURIComponent(listaId)}/precios`);
    if (!res.ok) {
      showToast("No se pudieron cargar los precios de la lista", "error");
      return;
    }
    const precios = await res.json();
    const sel = document.getElementById("asig-lp-select");
    if (sel) sel.value = String(listaId);
    if (!precios || precios.length === 0) {
      showToast(`La lista #${listaId} aún no tiene precios especiales asignados.`, "info");
      return;
    }
    const resumen = precios
      .map(p => `${p.producto_codigo}: ${formatCOP(p.precio_especial)}`)
      .join(" | ");
    showToast(`Precios Lista #${listaId}: ${resumen}`, "info", 7000);
  } catch (err) {
    showToast("Error consultando precios: " + err.message, "error");
  }
}
window.verPreciosLista = verPreciosLista;

async function crearListaPrecio() {
  const nom = document.getElementById("lp-nombre")?.value.trim();
  const desc = document.getElementById("lp-desc")?.value.trim();
  if (!nom) {
    showToast("Ingrese el nombre de la lista", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/listas-precios", {
      method: "POST",
      body: JSON.stringify({ nombre: nom, descripcion: desc }),
    });
    if (!res.ok) throw new Error("Error creando lista");
    showToast(`Lista de precios "${nom}" creada con éxito`, "success");
    document.getElementById("lp-nombre").value = "";
    document.getElementById("lp-desc").value = "";
    loadListasPrecios();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function guardarPrecioProducto() {
  const listaId = document.getElementById("asig-lp-select")?.value;
  const prodCod = document.getElementById("asig-prod-select")?.value;
  const precio = document.getElementById("asig-precio-val")?.value;
  if (!listaId || !prodCod) return;
  try {
    const res = await apiFetch(`/api/listas-precios/${listaId}/precios`, {
      method: "POST",
      body: JSON.stringify({ producto_codigo: prodCod, precio }),
    });
    if (!res.ok) throw new Error("Error asignando precio");
    showToast("Precio especial asignado correctamente", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function ejecutarTrasladoBodega() {
  const prod = document.getElementById("tras-prod")?.value;
  const orig = document.getElementById("tras-origen")?.value.trim();
  const dest = document.getElementById("tras-destino")?.value.trim();
  const cant = document.getElementById("tras-cant")?.value;
  const lote = document.getElementById("tras-lote")?.value.trim();
  if (!prod || !orig || !dest || !cant) {
    showToast("Diligencie todos los campos de traslado", "warning");
    return;
  }
  try {
    const res = await apiFetch("/api/inventario/traslados", {
      method: "POST",
      body: JSON.stringify({ producto_codigo: prod, bodega_origen: orig, bodega_destino: dest, cantidad: cant, lote }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Error en traslado");
    }
    showToast(`Traslado de ${cant} unidades de ${prod} completado con éxito`, "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============ ATTACH NEW EVENT LISTENERS ============

const btnInit2fa = document.getElementById("btn-init-2fa");
if (btnInit2fa) btnInit2fa.addEventListener("click", init2faSetup);
const btnConfirm2fa = document.getElementById("btn-confirm-enable-2fa");
if (btnConfirm2fa) btnConfirm2fa.addEventListener("click", confirmEnable2fa);
const btnCancel2fa = document.getElementById("btn-cancel-enable-2fa");
if (btnCancel2fa) btnCancel2fa.addEventListener("click", () => document.getElementById("2fa-setup-panel").style.display = "none");
const btnDisable2fa = document.getElementById("btn-disable-2fa");
if (btnDisable2fa) btnDisable2fa.addEventListener("click", disable2fa);

const btnAddLineaCot = document.getElementById("btn-add-linea-cot");
if (btnAddLineaCot) btnAddLineaCot.addEventListener("click", addLineaCot);
const formCot = document.getElementById("form-cotizacion");
if (formCot) formCot.addEventListener("submit", guardarCotizacion);

const btnAbrirPos = document.getElementById("btn-pos-abrir-caja");
if (btnAbrirPos) btnAbrirPos.addEventListener("click", abrirTurnoCaja);
const btnCerrarPos = document.getElementById("btn-pos-cerrar-caja");
if (btnCerrarPos) btnCerrarPos.addEventListener("click", openArqueoModal);
const btnCloseArqueo = document.getElementById("btn-close-arqueo");
if (btnCloseArqueo) btnCloseArqueo.addEventListener("click", closeArqueoModal);
const btnCancelArqueo = document.getElementById("btn-cancel-arqueo");
if (btnCancelArqueo) btnCancelArqueo.addEventListener("click", closeArqueoModal);
const btnConfirmArqueo = document.getElementById("btn-confirmar-arqueo");
if (btnConfirmArqueo) btnConfirmArqueo.addEventListener("click", confirmarArqueoCaja);
const btnImprimirTirilla = document.getElementById("btn-imprimir-tirilla");
if (btnImprimirTirilla) btnImprimirTirilla.addEventListener("click", imprimirTirillaPos);

const btnProcesarCompra = document.getElementById("btn-procesar-compra-file");
if (btnProcesarCompra) btnProcesarCompra.addEventListener("click", procesarArchivoCompra);
const btnCloseEgreso = document.getElementById("btn-close-egreso");
if (btnCloseEgreso) btnCloseEgreso.addEventListener("click", closeEgresoModal);
const btnCancelEgreso = document.getElementById("btn-cancel-egreso");
if (btnCancelEgreso) btnCancelEgreso.addEventListener("click", closeEgresoModal);
const btnConfirmEgreso = document.getElementById("btn-confirmar-egreso");
if (btnConfirmEgreso) btnConfirmEgreso.addEventListener("click", confirmarEgreso);

const btnCalcularF300 = document.getElementById("btn-calcular-f300");
if (btnCalcularF300) btnCalcularF300.addEventListener("click", calcularF300);
const btnCalcularF350 = document.getElementById("btn-calcular-f350");
if (btnCalcularF350) btnCalcularF350.addEventListener("click", calcularF350);

const btnCrearLp = document.getElementById("btn-crear-lista-precio");
if (btnCrearLp) btnCrearLp.addEventListener("click", crearListaPrecio);
const btnGuardarPrecio = document.getElementById("btn-guardar-precio-prod");
if (btnGuardarPrecio) btnGuardarPrecio.addEventListener("click", guardarPrecioProducto);
const btnTraslado = document.getElementById("btn-ejecutar-traslado");
if (btnTraslado) btnTraslado.addEventListener("click", ejecutarTrasladoBodega);


window.addEventListener("DOMContentLoaded", () => {
  console.log("DOMContentLoaded, calling init()");
  init().catch(err => console.error("init() error:", err));
});
