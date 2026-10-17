import os

html_content = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tutorial Paso a Paso — ERP Corporativo Colombia (DIAN UBL 2.1)</title>
  <style>
    :root {
      --primary: #0070f2;
      --primary-dark: #0050b3;
      --secondary: #1b90ff;
      --bg: #f4f6f9;
      --card-bg: #ffffff;
      --text: #0f172a;
      --text-muted: #475569;
      --border: #e2e8f0;
      --accent-red: #ef4444;
      --success: #059669;
      --warning: #d97706;
      --sidebar-w: 310px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.65;
      display: flex;
    }

    /* Sidebar Navigation */
    #sidebar {
      width: var(--sidebar-w);
      height: 100vh;
      background: #0f172a;
      color: #f8fafc;
      position: fixed;
      top: 0;
      left: 0;
      overflow-y: auto;
      border-right: 1px solid #1e293b;
      display: flex;
      flex-direction: column;
      z-index: 100;
    }
    .sidebar-brand {
      padding: 20px 18px;
      background: #090e1a;
      border-bottom: 1px solid #1e293b;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .sap-badge {
      background: linear-gradient(135deg, #0070f2 0%, #1d4ed8 100%);
      color: #fff;
      font-weight: 900;
      padding: 6px 11px;
      border-radius: 8px;
      font-size: 15px;
      letter-spacing: 0.8px;
      box-shadow: 0 4px 12px rgba(0, 112, 242, 0.35);
    }
    .brand-title {
      font-size: 14.5px;
      font-weight: 800;
      color: #fff;
      line-height: 1.2;
    }
    .brand-sub {
      font-size: 11.5px;
      color: #94a3b8;
      margin-top: 2px;
    }
    .sidebar-search {
      padding: 12px 16px;
      border-bottom: 1px solid #1e293b;
    }
    .sidebar-search input {
      width: 100%;
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid #334155;
      background: #1e293b;
      color: #f8fafc;
      font-size: 12.5px;
      outline: none;
    }
    .sidebar-search input:focus {
      border-color: #38bdf8;
    }
    .sidebar-menu {
      padding: 12px 0 28px 0;
      list-style: none;
      flex: 1;
    }
    .menu-section {
      padding: 14px 18px 5px 18px;
      font-size: 10.5px;
      text-transform: uppercase;
      font-weight: 800;
      color: #64748b;
      letter-spacing: 0.08em;
    }
    .sidebar-menu li a {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 18px;
      color: #cbd5e1;
      text-decoration: none;
      font-size: 13px;
      font-weight: 500;
      transition: all 0.15s ease;
      border-left: 3px solid transparent;
    }
    .sidebar-menu li a:hover {
      background: rgba(255, 255, 255, 0.06);
      color: #ffffff;
      border-left-color: var(--primary);
    }

    /* Main Content */
    #main {
      margin-left: var(--sidebar-w);
      flex: 1;
      max-width: 1180px;
      padding: 36px 48px 90px 48px;
    }

    .hero-banner {
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #0070f2 100%);
      color: #fff;
      padding: 38px 42px;
      border-radius: 16px;
      margin-bottom: 36px;
      box-shadow: 0 16px 32px -10px rgba(15, 23, 42, 0.25);
    }
    .hero-banner h1 {
      font-size: 30px;
      font-weight: 800;
      margin-bottom: 12px;
      letter-spacing: -0.02em;
    }
    .hero-banner p {
      font-size: 15.5px;
      color: #e2e8f0;
      max-width: 860px;
      line-height: 1.6;
    }
    .hero-meta {
      display: flex;
      gap: 12px;
      margin-top: 22px;
      flex-wrap: wrap;
    }
    .pill {
      background: rgba(255, 255, 255, 0.14);
      border: 1px solid rgba(255, 255, 255, 0.25);
      padding: 5px 14px;
      border-radius: 999px;
      font-size: 12.5px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .how-to-read-box {
      background: #ffffff;
      border: 2px solid #bfdbfe;
      border-radius: 12px;
      padding: 18px 22px;
      margin-bottom: 32px;
      display: flex;
      align-items: center;
      gap: 18px;
      box-shadow: 0 4px 12px rgba(0, 112, 242, 0.06);
    }
    .how-to-read-icon {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: #fef2f2;
      border: 2px solid #ef4444;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      flex-shrink: 0;
    }

    /* Module Cards */
    .module-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 28px 30px;
      margin-bottom: 36px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }
    .module-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 16px;
      border-bottom: 1px solid #f1f5f9;
      padding-bottom: 14px;
    }
    .module-header h2 {
      font-size: 21px;
      font-weight: 800;
      color: var(--text);
      margin: 0;
    }
    .module-tag {
      background: #eff6ff;
      color: #1d4ed8;
      border: 1px solid #bfdbfe;
      font-size: 11.5px;
      font-weight: 700;
      padding: 4px 12px;
      border-radius: 999px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    p {
      margin-bottom: 14px;
      font-size: 15px;
      color: #334155;
    }

    /* Visual Step-by-Step List */
    .step-list {
      list-style: none;
      padding: 0;
      margin: 18px 0 8px 0;
      display: grid;
      gap: 12px;
    }
    .step-item {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 12px 16px;
      transition: border-color 0.15s ease;
    }
    .step-item:hover {
      border-color: #93c5fd;
      background: #f0f9ff;
    }
    .step-num {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: var(--accent-red);
      color: #ffffff;
      font-weight: 800;
      font-size: 13.5px;
      flex-shrink: 0;
      box-shadow: 0 2px 6px rgba(239, 68, 68, 0.35);
      margin-top: 1px;
    }
    .step-text {
      font-size: 14.5px;
      color: #1e293b;
    }
    .step-text strong {
      color: #0f172a;
    }

    /* Screenshot Box */
    .screenshot-box {
      margin: 20px 0;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 12px 28px -6px rgba(15, 23, 42, 0.22);
    }
    .screenshot-header {
      background: #1e293b;
      padding: 9px 16px;
      font-size: 12px;
      font-weight: 600;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #334155;
    }
    .screenshot-header .dots {
      display: flex;
      gap: 6px;
    }
    .dot { width: 10px; height: 10px; border-radius: 50%; }
    .dot-red { background: #ef4444; }
    .dot-yellow { background: #f59e0b; }
    .dot-green { background: #10b981; }

    .screenshot-box img {
      width: 100%;
      height: auto;
      display: block;
      cursor: zoom-in;
    }
    .screenshot-caption {
      padding: 10px 16px;
      font-size: 12.5px;
      color: #94a3b8;
      background: #0f172a;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-top: 1px solid #1e293b;
    }

    /* Alerts */
    .alert {
      padding: 14px 18px;
      border-radius: 10px;
      margin: 16px 0 4px 0;
      font-size: 14px;
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }
    .alert-info {
      background: #eff6ff;
      border-left: 4px solid #0070f2;
      color: #1e3a8a;
    }
    .alert-success {
      background: #ecfdf5;
      border-left: 4px solid #059669;
      color: #065f46;
    }
    .alert-warning {
      background: #fffbeb;
      border-left: 4px solid #d97706;
      color: #92400e;
    }

    /* Tables */
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0 10px 0;
      background: #fff;
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
    }
    th {
      background: #f1f5f9;
      color: #0f172a;
      text-align: left;
      padding: 12px 16px;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid var(--border);
    }
    td {
      padding: 12px 16px;
      font-size: 13.5px;
      border-bottom: 1px solid var(--border);
      color: #334155;
    }
    tr:last-child td { border-bottom: none; }
    tr:nth-child(even) { background-color: #f8fafc; }
    code {
      background: #f1f5f9;
      color: #0f172a;
      padding: 2px 7px;
      border-radius: 5px;
      font-weight: 700;
      font-size: 13px;
    }

    .role-badge {
      display: inline-block;
      padding: 3px 9px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 800;
    }
    .role-admin { background: #fee2e2; color: #991b1b; }
    .role-gerente { background: #dbeafe; color: #1e40af; }
    .role-contador { background: #fef3c7; color: #92400e; }
    .role-vendedor { background: #dcfce7; color: #166534; }
    .role-tesorero { background: #f3e8ff; color: #6b21a8; }
    .role-pos { background: #ffedd5; color: #9a3412; }
    .role-rrhh { background: #fce7f3; color: #9d174d; }

    /* Lightbox Modal */
    #lightbox {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.92);
      z-index: 9999;
      justify-content: center;
      align-items: center;
      cursor: zoom-out;
      padding: 24px;
    }
    #lightbox img {
      max-width: 95vw;
      max-height: 94vh;
      border-radius: 10px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.6);
    }

    @media (max-width: 960px) {
      #sidebar { display: none; }
      #main { margin-left: 0; padding: 20px; }
    }
  </style>
</head>
<body>

  <!-- Menú Lateral del Tutorial -->
  <nav id="sidebar">
    <div class="sidebar-brand">
      <div class="sap-badge">ERP</div>
      <div>
        <div class="brand-title">Manual Paso a Paso</div>
        <div class="brand-sub">Guía Visual Interactiva</div>
      </div>
    </div>
    <div class="sidebar-search">
      <input type="text" id="menu-filter" placeholder="🔍 Buscar tema en el manual..." oninput="filterMenu(this.value)">
    </div>
    <ul class="sidebar-menu" id="tutorial-nav-list">
      <li class="menu-section">Arranque y Configuración</li>
      <li><a href="#scripts-arranque">🚀 Scripts de Inicio y Configuración</a></li>
      <li><a href="#credenciales">🔑 Cuentas y Contraseñas de Prueba</a></li>

      <li class="menu-section">Primeros Pasos</li>
      <li><a href="#paso-1">1. Cómo Iniciar Sesión</a></li>
      <li><a href="#paso-2">2. Menú Lateral y Barra Superior</a></li>
      <li><a href="#paso-3">3. Dashboard e Indicadores</a></li>

      <li class="menu-section">Marca y Tema por Empresa</li>
      <li><a href="#paso-4">4. Cambiar Logo, Nombre, Colores y Fuente</a></li>
      <li><a href="#paso-5">5. Cambiar entre Múltiples Empresas</a></li>

      <li class="menu-section">Ventas, POS y Cartera</li>
      <li><a href="#paso-6">6. Emitir Factura Electrónica DIAN</a></li>
      <li><a href="#paso-7">7. Emitir Notas Crédito (Anular/Corregir)</a></li>
      <li><a href="#paso-8">8. Ciclo Comercial (Cotización a Factura)</a></li>
      <li><a href="#paso-9">9. Punto de Venta POS (Mostrador)</a></li>
      <li><a href="#paso-10">10. Cartera de Clientes y Pagos</a></li>

      <li class="menu-section">Compras e Inventario</li>
      <li><a href="#paso-11">11. Compras XML, RADIAN y CxP</a></li>
      <li><a href="#paso-12">12. Documento Soporte (No Obligados)</a></li>
      <li><a href="#paso-13">13. Listas de Precios y Lotes</a></li>

      <li class="menu-section">Contabilidad, Impuestos y Nómina</li>
      <li><a href="#paso-14">14. Contabilidad PUC y Balance</a></li>
      <li><a href="#paso-15">15. Impuestos DIAN (300, 350 y Exógena)</a></li>
      <li><a href="#paso-16">16. Nómina Electrónica DIAN</a></li>

      <li class="menu-section">Administración y Roles</li>
      <li><a href="#paso-17">17. Consola de Empresas y Usuarios</a></li>
      <li><a href="#paso-18">18. Permisos y Control Antifraude SoD</a></li>
      <li><a href="#vistas-roles">19. Vistas según el Cargo del Usuario</a></li>
    </ul>
  </nav>

  <!-- Contenido Principal -->
  <main id="main">

    <!-- Banner Principal -->
    <div class="hero-banner" id="inicio">
      <h1>Guía Visual Paso a Paso — ERP Corporativo Colombia</h1>
      <p>Aprende a usar toda la plataforma desde cero en minutos. Cada captura de pantalla te muestra con <strong>números rojos (①, ②, ③)</strong> y el <strong>cursor del mouse (🖱️)</strong> exactamente dónde hacer clic en cada operación.</p>
      <div class="hero-meta">
        <span class="pill">🖱️ Guía con Cursor Paso a Paso</span>
        <span class="pill">🎨 Marca, Logo y Fuentes por Empresa</span>
        <span class="pill">🇨🇴 Facturación DIAN UBL 2.1 + RADIAN</span>
        <span class="pill">🏢 Multi-Empresa & Multi-Usuario</span>
      </div>
    </div>

    <div class="how-to-read-box">
      <div class="how-to-read-icon">🖱️</div>
      <div>
        <strong style="font-size:15.5px; color:#0f172a;">¿Cómo leer las imágenes de este tutorial?</strong>
        <p style="margin:4px 0 0 0; font-size:14px; color:#475569;">
          En cada imagen verás <strong>recuadros rojos numerados (1, 2, 3...)</strong> en el orden exacto en que debes llenar los datos, y un <strong>cursor blanco con onda roja</strong> señalando el botón exacto donde debes hacer clic. <em>(Puedes hacer clic sobre cualquier imagen para verla en pantalla completa).</em>
        </p>
      </div>
    </div>

    <!-- SECCIÓN DE SCRIPTS Y PANEL DE CONFIGURACIÓN -->
    <section class="module-card" id="scripts-arranque">
      <div class="module-header">
        <h2>🚀 Scripts de Inicio y Panel de Configuración (Linux & Windows)</h2>
        <span class="module-tag">Primer Paso · Plug & Play</span>
      </div>
      <p>El sistema está empaquetado de manera <strong>100% portable y autónoma</strong>. No requiere instalación manual ni dependencias del sistema operativo. Puedes iniciarlo directamente en 1 clic o abrir el <strong>Panel de Control Interactivo</strong> para configurar bases de datos (embebida vs externa), conmutar entre entorno de Pruebas y Real DIAN, y respaldar tu información:</p>

      <h3 style="margin:18px 0 10px 0; color:#0f172a;">⚡ 1. Lanzadores de 1 Clic y Panel de Control</h3>
      <table>
        <thead>
          <tr>
            <th>Acción</th>
            <th>En Linux</th>
            <th>En Windows (10 / 11)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Iniciar el ERP en 1 Clic</strong> (Arranca PostgreSQL portable + Web UI en el navegador)</td>
            <td>Ejecuta <code>./Iniciar_ERP_Linux.sh</code></td>
            <td>Doble clic en <code>Iniciar_ERP_Windows.bat</code></td>
          </tr>
          <tr>
            <td><strong>Abrir el Panel de Control y Configuración</strong> (BD, Entorno DIAN, Respaldos y Motores)</td>
            <td>Ejecuta <code>./Configurar_ERP_Linux.sh</code></td>
            <td>Doble clic en <code>Configurar_ERP_Windows.bat</code></td>
          </tr>
        </tbody>
      </table>

      <h3 style="margin:22px 0 10px 0; color:#0f172a;">🎛️ 2. Opciones Paso a Paso del Panel de Control Interactivo</h3>
      <p>Al abrir <code>./Configurar_ERP_Linux.sh</code> (Linux) o <code>Configurar_ERP_Windows.bat</code> (Windows), verás el estado actual del sistema y <strong>10 opciones numeradas</strong>:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>🚀 Iniciar el ERP Corporativo Ahora:</strong> Arranca automáticamente el motor PostgreSQL embebido (si estás en modo Portable), verifica las tablas de la base de datos activa y abre la interfaz web en <code>http://127.0.0.1:8000</code>. Al cerrar la ventana con <code>Ctrl+C</code>, apaga PostgreSQL de forma segura.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>🏠 Cambiar a Base de Datos PORTABLE Embebida (guardada en <code>Data/</code>):</strong> Guarda todas tus empresas, facturas y contabilidad dentro de la carpeta del proyecto (<code>Data/db</code> en Linux y <code>Data/db_windows</code> en Windows) usando el puerto <code>54329</code> para no chocar con ningún otro PostgreSQL instalado.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>🌐 Cambiar a Servidor PostgreSQL EXTERNO (Red Local / Nube / Docker):</strong> Te pide el <em>Host/IP</em> (ej. <code>192.168.1.50</code> o RDS), <em>Puerto</em> (<code>5432</code>), <em>Usuario</em>, <em>Contraseña</em> y <em>Nombre de Base de Datos</em>. Prueba la conexión en vivo, crea la base de datos si no existe y guarda la configuración en <code>Data/config.json</code>.</div>
        </li>
        <li class="step-item">
          <span class="step-num">4</span>
          <div class="step-text"><strong>🏛️ Cambiar Entorno Global (🧪 Pruebas Mockup vs. 🚀 Trabajo Real DIAN):</strong> Separa por completo las pruebas del trabajo real con aislamiento total de base de datos:
            <br>• <strong>🧪 Entorno de Pruebas (Simulador Mockup Local):</strong> Usa la base de datos de pruebas (<code>sap_colombia_pruebas</code>) y el simulador local, sin tocar internet ni alterar los registros de producción.
            <br>• <strong>🚀 Entorno de Trabajo Real (Servidor Oficial DIAN):</strong> Conecta a la base de datos de producción (<code>sap_colombia</code>) y transmite directamente a los Web Services SOAP oficiales de la DIAN (<code>vpfe.dian.gov.co</code> o <code>vpfe-hab.dian.gov.co</code>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">5</span>
          <div class="step-text"><strong>🔁 Migrar / Clonar BD REAL  ➜  BD de PRUEBAS (Sandbox Seguro):</strong> Copia con un solo clic el 100% de la base de datos real (empresas, clientes, productos, cuentas PUC, facturas, etc.) sobre la base de datos de pruebas. La base de datos real solo se lee, por lo que nunca se compromete tu información real.</div>
        </li>
        <li class="step-item">
          <span class="step-num">6</span>
          <div class="step-text"><strong>🧹 Reiniciar BD de PRUEBAS (Limpiar datos de pruebas):</strong> Vacía la base de datos de pruebas para empezar desde cero con datos limpios de demostración cuando lo necesites.</div>
        </li>
        <li class="step-item">
          <span class="step-num">7</span>
          <div class="step-text"><strong>📦 Portabilizar / Descargar Motores (Linux + Windows para USB):</strong> Descarga y empaqueta automáticamente PostgreSQL 17.2 y Python 3.12 + librerías nativas para Linux (<code>App/engine/linux</code>, <code>App/runtime/linux</code>) y Windows (<code>App/engine/windows</code>, <code>App/runtime/windows</code>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">8</span>
          <div class="step-text"><strong>💾 Exportar Respaldo Universal de Datos:</strong> Exporta todas las tablas de la base de datos activa a un archivo neutro <code>Data/backups/respaldo_universal.json</code>.</div>
        </li>
        <li class="step-item">
          <span class="step-num">9</span>
          <div class="step-text"><strong>📥 Importar / Restaurar Respaldo Universal:</strong> Restaura el archivo <code>Data/backups/respaldo_universal.json</code> en la base de datos activa. Es la forma ideal de pasar tus datos entre Linux, Windows o hacia un servidor PostgreSQL externo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">10</span>
          <div class="step-text"><strong>🔧 Cambiar Puerto Web HTTP / Acceso desde Red Local (LAN):</strong> Te permite cambiar el puerto web (por defecto <code>8000</code>) y habilitar el acceso en red local (<code>0.0.0.0</code>) para que otros computadores de la oficina entren desde su navegador.</div>
        </li>
      </ul>

      <div class="alert alert-info">
        <div>💡</div>
        <div><strong>Comandos Directos por Terminal (Opcional):</strong> También puedes automatizar cualquier cambio sin entrar al menú interactivo ejecutando:
          <br>• Clonar BD Real a BD de Pruebas: <code>./Configurar_ERP_Linux.sh --clone-to-test -y</code>
          <br>• Reiniciar BD de Pruebas: <code>./Configurar_ERP_Linux.sh --reset-test-db -y</code>
          <br>• Configurar todo el sistema para Pruebas (Simulador Local): <code>./Configurar_ERP_Linux.sh --set-dian mock</code>
          <br>• Configurar todo el sistema para Trabajo Real (DIAN Producción): <code>./Configurar_ERP_Linux.sh --set-dian real --dian-ambiente 2</code>
          <br>• Usar BD Portable Embebida: <code>./Configurar_ERP_Linux.sh --set-db embedded --port 54329</code>
          <br>• Usar PostgreSQL Externo: <code>./Configurar_ERP_Linux.sh --set-db external --host 192.168.1.50 --port 5432 --user postgres --password secret --dbname sap_colombia</code>
        </div>
      </div>
    </section>

    <!-- TABLA DE CREDENCIALES -->
    <section class="module-card" id="credenciales">
      <div class="module-header">
        <h2>🔑 Cuentas y Contraseñas Listas para Probar</h2>
        <span class="module-tag">Usuarios de Demostración</span>
      </div>
      <p>Usa cualquiera de estas cuentas en <a href="http://127.0.0.1:8000" target="_blank" style="color:var(--primary); font-weight:700;">http://127.0.0.1:8000</a> para explorar cada perfil:</p>

      <table>
        <thead>
          <tr>
            <th>Cargo / Rol</th>
            <th>Usuario (Correo)</th>
            <th>Contraseña</th>
            <th>¿Qué puede hacer en el sistema?</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><span class="role-badge role-admin">SUPERADMIN</span></td>
            <td><code>admin@sistema.com</code></td>
            <td><code>admin123</code></td>
            <td>Control total, creación de empresas, personalización de marca/logo/colores/fuentes y permisos SoD.</td>
          </tr>
          <tr>
            <td><span class="role-badge role-gerente">ADMIN_EMPRESA</span></td>
            <td><code>gerente@empresa.com</code></td>
            <td><code>Gerente123!</code></td>
            <td>Dashboard gerencial, aprobación de descuentos mayores al 15% y supervisión de la empresa.</td>
          </tr>
          <tr>
            <td><span class="role-badge role-contador">CONTADOR</span></td>
            <td><code>contador@empresa.com</code></td>
            <td><code>Contador123!</code></td>
            <td>Contabilidad PUC, Balance de Prueba, Estados Financieros, Impuestos 300/350/Exógena y Cierre Fiscal.</td>
          </tr>
          <tr>
            <td><span class="role-badge role-vendedor">VENDEDOR</span></td>
            <td><code>vendedor@empresa.com</code></td>
            <td><code>Vendedor123!</code></td>
            <td>Ciclo comercial, creación de cotizaciones propias, pedidos y facturación.</td>
          </tr>
          <tr>
            <td><span class="role-badge role-tesorero">TESORERO</span></td>
            <td><code>tesorero@empresa.com</code></td>
            <td><code>Tesorero123!</code></td>
            <td>Buzón de compras XML, emisión de eventos RADIAN (030, 032, 033) y Cuentas por Pagar.</td>
          </tr>
          <tr>
            <td><span class="role-badge role-cajero">CAJERO_POS</span></td>
            <td><code>cajero@empresa.com</code></td>
            <td><code>Cajero123!</code></td>
            <td>Apertura de turno de caja, emisión rápida de tickets POS y arqueo de caja diario.</td>
          </tr>
          <tr>
            <td><span class="role-badge role-rrhh">RECURSOS_HUMANOS</span></td>
            <td><code>rrhh@empresa.com</code></td>
            <td><code>Nomina123!</code></td>
            <td>Vinculación de empleados, horas extra, seguridad social y Nómina Electrónica DIAN.</td>
          </tr>
          <tr>
            <td><span class="role-badge">ALMACENISTA</span></td>
            <td><code>almacen@empresa.com</code></td>
            <td><code>Almacen123!</code></td>
            <td>Control de inventario, listas de precios y lotes con fecha de vencimiento.</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- PASO 1: LOGIN -->
    <section class="module-card" id="paso-1">
      <div class="module-header">
        <h2>Paso 1. Cómo Iniciar Sesión en la Plataforma</h2>
        <span class="module-tag">Acceso Seguro</span>
      </div>
      <p>Al abrir el sistema en tu navegador (<code>http://127.0.0.1:8000</code>), verás la ventana de acceso corporativo:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Escribe tu correo electrónico:</strong> En el campo <em>Correo Corporativo</em>, escribe tu usuario (por ejemplo, <code>admin@sistema.com</code>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Ingresa tu contraseña:</strong> Digita tu clave personal en el campo <em>Contraseña</em> (por ejemplo, <code>admin123</code>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Iniciar Sesión Segura":</strong> Presiona el botón azul donde apunta el cursor para entrar al ERP.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Pantalla de Inicio de Sesión — Paso a Paso</span>
        </div>
        <img src="screenshots/01_login_screen.png" alt="Paso 1: Iniciar Sesión" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 1: Ingreso de credenciales y clic en Iniciar Sesión Segura.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 2: BARRA SUPERIOR Y MENÚ LATERAL -->
    <section class="module-card" id="paso-2">
      <div class="module-header">
        <h2>Paso 2. Conociendo el Menú Lateral y la Barra Superior</h2>
        <span class="module-tag">Navegación Rápida</span>
      </div>
      <p>Una vez dentro, la pantalla se divide en dos zonas muy simples: el <strong>Menú Lateral Izquierdo</strong> (con todos los módulos organizados por área) y la <strong>Barra Superior de Contexto</strong>:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Botón Contraer / Expandir Menú:</strong> Haz clic en el ícono de tres líneas arriba a la izquierda si deseas ocultar o ampliar el menú lateral para tener más espacio en pantalla.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Buscador Rápido de Módulos (<code>Ctrl + K</code>):</strong> Escribe cualquier palabra (ej. <em>"Factura"</em>, <em>"Nómina"</em>, <em>"Impuestos"</em>) para filtrar el menú al instante.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Selector de Empresa Activa:</strong> Si manejas varias empresas o razones sociales en la plataforma, cámbialas desde este desplegable sin cerrar sesión.</div>
        </li>
        <li class="step-item">
          <span class="step-num">4</span>
          <div class="step-text"><strong>Botón <code>🎨 Marca & Tema</code>:</strong> Haz clic aquí en cualquier momento para cambiar el logo, nombre, colores o fuente tipográfica de la empresa activa.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Barra Superior y Menú Lateral Organizacional</span>
        </div>
        <img src="screenshots/02_header_scope_bar.png" alt="Paso 2: Barra Superior y Menú" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 2: Controles principales de navegación, buscador Ctrl+K y selector de empresa.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 3: DASHBOARD EJECUTIVO -->
    <section class="module-card" id="paso-3">
      <div class="module-header">
        <h2>Paso 3. Cómo Consultar el Resumen del Negocio (Dashboard)</h2>
        <span class="module-tag">Indicadores KPI</span>
      </div>
      <p>El <strong>Dashboard</strong> te muestra de un vistazo cómo va la empresa en el mes actual:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Dashboard":</strong> Es la primera opción del menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Revisa las Tarjetas de Indicadores (KPIs):</strong> Observa las Ventas del Mes, Total Recaudado, Cuentas por Cobrar pendientes y Estado de Facturas DIAN.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Actualizar Datos:</strong> Presiona el botón de actualización arriba a la derecha para refrescar las gráficas y cifras al segundo.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Dashboard Ejecutivo e Indicadores Financieros</span>
        </div>
        <img src="screenshots/03_dashboard.png" alt="Paso 3: Dashboard" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 3: Vista general de ingresos, cartera y estado de facturación DIAN.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 4: PERSONALIZACIÓN DE MARCA POR EMPRESA -->
    <section class="module-card" id="paso-4">
      <div class="module-header">
        <h2>Paso 4. Cómo Cambiar el Nombre, Logo, Colores y Fuente de cada Empresa</h2>
        <span class="module-tag">Identidad Visual por Empresa</span>
      </div>
      <p>Cada empresa registrada en la plataforma puede tener su <strong>propio nombre, logo, paleta de colores y fuente tipográfica</strong>. Para configurarlo:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Cambia el Nombre / Razón Social y la Sigla:</strong> Haz clic en el botón superior <code>🎨 Marca & Tema</code> (o entra a <em>Administración → Empresas → 🎨 Marca / Editar</em>) y escribe el nombre de tu empresa.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Sube el Logo de tu Empresa:</strong> Haz clic en <em>Subir imagen de Logo</em> y selecciona tu archivo <code>.png</code>, <code>.svg</code>, <code>.jpg</code> o <code>.webp</code>. Verás la vista previa inmediatamente a la derecha.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Elige un Tema de Colores:</strong> Puedes hacer clic en cualquiera de los <strong>5 Temas Rápidos</strong> (<em>Azul</em>, <em>Esmeralda</em>, <em>Índigo</em>, <em>Borgoña</em>, <em>Grafito</em>) o elegir cualquier color exacto para Botones, Menú Lateral y Fondo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">4</span>
          <div class="step-text"><strong>Cambia o Sube tu Fuente Tipográfica:</strong> Elige una fuente profesional de la lista o sube tu propio archivo de fuente corporativa (<code>.ttf</code>, <code>.otf</code>, <code>.woff</code>, <code>.woff2</code>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">5</span>
          <div class="step-text"><strong>Haz clic en "💾 Guardar Empresa y Aplicar Tema":</strong> Toda la interfaz se actualizará al instante con la marca de tu empresa.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Estudio de Identidad Visual, Logo, Colores y Tipografía por Empresa</span>
        </div>
        <img src="screenshots/04_branding_empresa.png" alt="Paso 4: Personalizar Marca y Tema" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 4: Configuración completa de logo, colores y fuentes personalizadas por empresa.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 5: CAMBIO ENTRE EMPRESAS CON TEMA PROPIO -->
    <section class="module-card" id="paso-5">
      <div class="module-header">
        <h2>Paso 5. Cómo Alternar entre Empresas (Cambio Automático de Marca)</h2>
        <span class="module-tag">Multi-Empresa en Vivo</span>
      </div>
      <p>Cuando tienes dos o más empresas registradas, cada una conserva su propio diseño guardado en la base de datos:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en el selector "Empresa" de la barra superior:</strong> Elige otra empresa registrada (por ejemplo, <em>Inversiones Andinas S.A.S.</em>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Observa el cambio inmediato:</strong> El logo superior, el nombre de la empresa, el color del menú lateral (verde esmeralda) y la tipografía cambian automáticamente junto con toda su contabilidad y facturación aislada.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Cambio Automático de Logo, Colores y Tipografía al Alternar de Empresa</span>
        </div>
        <img src="screenshots/05_multiempresa_tema_esmeralda.png" alt="Paso 5: Cambio de Empresa y Tema" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 5: Inversiones Andinas S.A.S. cargada con su propio logo, fuente Montserrat y tema Esmeralda.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 6: FACTURACIÓN ELECTRÓNICA -->
    <section class="module-card" id="paso-6">
      <div class="module-header">
        <h2>Paso 6. Cómo Emitir una Factura Electrónica DIAN (UBL 2.1)</h2>
        <span class="module-tag">Facturación DIAN</span>
      </div>
      <p>Para crear una factura de venta legal con cálculo automático de IVA/retenciones, código CUFE y PDF:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Entra al módulo "Facturación":</strong> Haz clic en <em>Facturación</em> en el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Selecciona el Cliente:</strong> Elige el cliente adquirente en la lista desplegable y el medio de pago (Contado o Crédito).</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Agrega los Productos o Servicios:</strong> Elige el producto, escribe la cantidad y usa <code>+ Agregar Ítem</code> si deseas incluir más líneas. A la derecha verás la <strong>Liquidación Tributaria Automática</strong> (Subtotal, IVA, Retefuente, ReteIVA, ReteICA y Total).</div>
        </li>
        <li class="step-item">
          <span class="step-num">4</span>
          <div class="step-text"><strong>Haz clic en "⚡ Emitir Factura Electrónica a DIAN":</strong> El sistema firmará el XML UBL 2.1, generará el CUFE y habilitará la descarga inmediata del PDF y XML.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Emisión de Factura Electrónica DIAN Paso a Paso</span>
        </div>
        <img src="screenshots/06_facturacion.png" alt="Paso 6: Facturación Electrónica" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 6: Selección de cliente, adición de ítems y clic en Emitir Factura Electrónica a DIAN.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 7: NOTAS CRÉDITO -->
    <section class="module-card" id="paso-7">
      <div class="module-header">
        <h2>Paso 7. Cómo Emitir una Nota Crédito (Anular o Corregir una Factura)</h2>
        <span class="module-tag">Devoluciones y Anulaciones</span>
      </div>
      <p>Si necesitas anular una factura emitida o registrar una devolución parcial ante la DIAN:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Notas Crédito":</strong> En el menú lateral bajo la sección Comercial.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Elige la Factura Asociada:</strong> Selecciona la factura original aceptada por la DIAN que deseas afectar.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Selecciona el Motivo DIAN:</strong> Elige el concepto oficial (ej. <em>Anulación de factura electrónica</em>, <em>Devolución parcial de bienes</em> o <em>Descuento comercial</em>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">4</span>
          <div class="step-text"><strong>Haz clic en "Emitir Nota Crédito":</strong> Se generará el CUDE electrónico y el asiento contable de reversión automáticamente.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Emisión de Nota Crédito Electrónica</span>
        </div>
        <img src="screenshots/07_notas_credito.png" alt="Paso 7: Notas Crédito" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 7: Selección de factura padre, motivo DIAN y emisión de Nota Crédito.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 8: CICLO COMERCIAL -->
    <section class="module-card" id="paso-8">
      <div class="module-header">
        <h2>Paso 8. Cómo Usar el Ciclo Comercial (Cotización ➔ Pedido ➔ Factura)</h2>
        <span class="module-tag">Flujo en Cascada</span>
      </div>
      <p>Evita digitar dos veces la misma venta. Crea primero una cotización y conviértela en pedido, remisión y factura con un clic:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Abre "Ciclo Comercial":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Selecciona el Cliente y los Productos a Cotizar:</strong> Indica cantidades y porcentaje de descuento (si supera el 15%, pedirá aprobación gerencial).</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Crear Cotización":</strong> Una vez creada, en la tabla inferior podrás presionar <code>Aprobar y Pedido ➔</code>, <code>Remisionar ➔</code> y <code>Facturar 1-Clic ⚡</code>.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Ciclo Comercial en Cascada</span>
        </div>
        <img src="screenshots/08_ciclo_comercial.png" alt="Paso 8: Ciclo Comercial" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 8: Creación de cotización y conversión rápida en cascada hasta Factura DIAN.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 9: PUNTO DE VENTA POS -->
    <section class="module-card" id="paso-9">
      <div class="module-header">
        <h2>Paso 9. Cómo Operar el Punto de Venta POS (Caja de Mostrador)</h2>
        <span class="module-tag">POS Electrónico</span>
      </div>
      <p>Para ventas rápidas de mostrador con control de turnos de cajero y arqueo de efectivo:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Punto de Venta POS":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Digita la Base Inicial de Efectivo:</strong> Escribe el dinero con el que inicia la caja al abrir el turno.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Abrir Turno":</strong> Luego podrás registrar ventas rápidas con código de barras y, al final del día, cerrar el turno con cuadre de caja automático.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Punto de Venta POS y Control de Turnos de Caja</span>
        </div>
        <img src="screenshots/09_pos_system.png" alt="Paso 9: Punto de Venta POS" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 9: Apertura de turno de caja y emisión de tirillas electrónicas POS.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 10: CARTERA Y RECAUDOS -->
    <section class="module-card" id="paso-10">
      <div class="module-header">
        <h2>Paso 10. Cómo Controlar la Cartera (Cuentas por Cobrar) y Registrar Pagos</h2>
        <span class="module-tag">Recaudos y Edades</span>
      </div>
      <p>Revisa qué clientes tienen facturas pendientes o vencidas y registra sus pagos o abonos:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Entra a "Cartera & Recaudos":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Revisa el Semáforo de Edades de Cartera:</strong> Identifica saldos al día (Corriente) y vencidos a 30, 60, 90 o más de 90 días.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic para Registrar el Abono / Recibo de Caja:</strong> Selecciona la factura a crédito, digita el valor pagado por el cliente y presiona el botón para descontar el saldo y contabilizar el ingreso en bancos/caja.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Semáforo de Cartera y Registro de Recaudos</span>
        </div>
        <img src="screenshots/10_cartera.png" alt="Paso 10: Cartera y Recaudos" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 10: Control de vencimientos y aplicación de pagos de clientes.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 11: COMPRAS, RADIAN Y CXP -->
    <section class="module-card" id="paso-11">
      <div class="module-header">
        <h2>Paso 11. Cómo Cargar Facturas de Proveedores (XML), Eventos RADIAN y CxP</h2>
        <span class="module-tag">RADIAN & Proveedores</span>
      </div>
      <p>Para registrar compras a crédito, causar las Cuentas por Pagar y emitir los eventos obligatorios RADIAN ante la DIAN:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Buzón Compras & CxP":</strong> En la sección de Compras del menú lateral.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Selecciona el archivo XML o ZIP del proveedor:</strong> Sube la factura electrónica que te envió tu proveedor.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Procesar XML":</strong> El sistema lee automáticamente el proveedor, productos e impuestos, y te permite emitir en 1 clic los eventos <code>030 Acuse de Recibo</code>, <code>032 Recepción del Bien</code> y <code>033 Aceptación Expresa</code>.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Buzón de Compras XML, Eventos RADIAN y Cuentas por Pagar</span>
        </div>
        <img src="screenshots/11_compras_cxp.png" alt="Paso 11: Compras y RADIAN" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 11: Recepción automatizada de XML de proveedores y eventos RADIAN.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 12: DOCUMENTO SOPORTE -->
    <section class="module-card" id="paso-12">
      <div class="module-header">
        <h2>Paso 12. Cómo Emitir un Documento Soporte (Compras a No Obligados a Facturar)</h2>
        <span class="module-tag">Código CUDS</span>
      </div>
      <p>Cuando compras bienes o servicios a una persona natural no obligada a expedir factura electrónica, debes emitir el <strong>Documento Soporte Electrónico</strong> para deducir ese gasto:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Doc. Soporte DIAN":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Ingresa el NIT/Cédula y nombre del proveedor:</strong> Completa la descripción del servicio o compra, el valor y la tarifa de retención aplicable.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Emitir Documento Soporte":</strong> El sistema generará el código <strong>CUDS</strong> oficial y el soporte en PDF.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Emisión de Documento Soporte Electrónico DIAN</span>
        </div>
        <img src="screenshots/12_documento_soporte.png" alt="Paso 12: Documento Soporte" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 12: Diligenciamiento y transmisión de Documento Soporte con código CUDS.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 13: PRECIOS Y LOTES -->
    <section class="module-card" id="paso-13">
      <div class="module-header">
        <h2>Paso 13. Cómo Configurar Listas de Precios y Lotes de Inventario</h2>
        <span class="module-tag">Precios & Trazabilidad</span>
      </div>
      <p>Administra precios diferenciados para Mayoristas, Distribuidores o Clientes VIP, así como lotes con fecha de vencimiento:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Listas de Precios":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Escribe el Nombre de la Lista y el Descuento:</strong> Define las condiciones comerciales del canal.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Crear Lista":</strong> Más abajo en la misma pantalla también puedes asignar precios especiales por producto y registrar lotes con fecha de vencimiento.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Gestión de Listas de Precios y Lotes</span>
        </div>
        <img src="screenshots/13_listas_precios.png" alt="Paso 13: Listas de Precios" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 13: Creación de listas de precios por canal y control de lotes de inventario.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 14: CONTABILIDAD PUC -->
    <section class="module-card" id="paso-14">
      <div class="module-header">
        <h2>Paso 14. Cómo Consultar la Contabilidad PUC, Libros Oficiales y Cierre de Mes</h2>
        <span class="module-tag">Partida Doble NIIF</span>
      </div>
      <p>Todas las facturas, compras, pagos y nóminas generan su asiento contable automáticamente en el Plan Único de Cuentas (PUC):</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Contabilidad & NIIF":</strong> En la sección Finanzas del menú lateral.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Verifica el Cuadre de Partida Doble:</strong> El banner superior confirma en tiempo real que <strong>Total Débitos = Total Créditos</strong>.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Consulta el Balance de Prueba y Cierre de Periodo:</strong> Haz clic en actualizar balance, consultar Estado de Resultados / Balance General o ejecutar el Cierre Contable Mensual para proteger el periodo.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Contabilidad PUC y Balance de Comprobación en Tiempo Real</span>
        </div>
        <img src="screenshots/14_contabilidad_puc.png" alt="Paso 14: Contabilidad PUC" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 14: Validación de ecuación patrimonial y libros contables oficiales.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 15: IMPUESTOS DIAN -->
    <section class="module-card" id="paso-15">
      <div class="module-header">
        <h2>Paso 15. Cómo Generar Borradores de Impuestos DIAN (300, 350 y Exógena)</h2>
        <span class="module-tag">Declaraciones Tributarias</span>
      </div>
      <p>Obtén en segundos los borradores listos para declarar en el portal Muisca de la DIAN:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Impuestos & Exógena":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Selecciona el Periodo Fiscal:</strong> Elige el año y mes/bimestre que vas a liquidar.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Generar Borrador":</strong> Calcula automáticamente los renglones del <strong>Formulario 300 (IVA)</strong>, <strong>Formulario 350 (Retención en la Fuente)</strong> y los formatos 1001, 1003 y 1007 de <strong>Información Exógena</strong>.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Liquidación de Formularios DIAN 300, 350 y Medios Magnéticos</span>
        </div>
        <img src="screenshots/15_impuestos_dian.png" alt="Paso 15: Impuestos DIAN" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 15: Generación en 1 clic de borradores tributarios oficiales DIAN.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 16: NÓMINA ELECTRÓNICA -->
    <section class="module-card" id="paso-16">
      <div class="module-header">
        <h2>Paso 16. Cómo Liquidar y Transmitir la Nómina Electrónica DIAN</h2>
        <span class="module-tag">Nómina & Seguridad Social</span>
      </div>
      <p>Registra tus trabajadores, liquida salario, auxilio de transporte, horas extra, salud, pensión y prestaciones patronales:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Nómina Electrónica":</strong> En el menú lateral izquierdo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Completa los datos del Empleado:</strong> Ingresa documento, nombres, cargo, tipo de contrato y salario mensual.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Guardar Empleado" y Liquida el Periodo:</strong> El sistema calcula el neto a pagar, provisiones patronales y genera el XML de Nómina Electrónica DIAN con código CUNE.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Módulo de Nómina Electrónica y Gestión de Empleados</span>
        </div>
        <img src="screenshots/16_nomina_electronica.png" alt="Paso 16: Nómina Electrónica" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 16: Registro de empleados, liquidación mensual y emisión de soporte de nómina DIAN.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 17: CONSOLA DE ADMINISTRACIÓN -->
    <section class="module-card" id="paso-17">
      <div class="module-header">
        <h2>Paso 17. Cómo Administrar Empresas, Usuarios y Accesos Multi-Empresa</h2>
        <span class="module-tag">Consola de Administración</span>
      </div>
      <p>Desde el módulo de <strong>Administración</strong> puedes crear nuevas empresas en la plataforma, registrar usuarios y asignar a qué empresas tiene acceso cada persona:</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en "Administración":</strong> Al final del menú lateral izquierdo (o en el botón superior <code>⚙️ Consola Sistema</code>).</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Usa las Sub-Pestañas de Organización:</strong> Filtra limpiamente entre <em>🏢 Empresas & DIAN</em>, <em>👥 Usuarios & Accesos</em>, <em>🛡️ Roles & SoD</em> y <em>🔐 Seguridad 2FA</em>.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "🎨 Marca / Editar" o "+ Nueva Empresa":</strong> Crea todas las empresas que necesites y personaliza el logo, colores y fuente de cada una.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Consola de Administración Multi-Empresa</span>
        </div>
        <img src="screenshots/17_consola_sistema.png" alt="Paso 17: Administración" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 17: Tabla de empresas con vista previa de su logo, paleta de colores y tipografía.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 18: PERMISOS Y MATRIZ SOD -->
    <section class="module-card" id="paso-18">
      <div class="module-header">
        <h2>Paso 18. Cómo Configurar Permisos por Rol y Auditoría Antifraude (SoD)</h2>
        <span class="module-tag">Seguridad ISO 27001</span>
      </div>
      <p>El sistema incluye un detector inteligente de <strong>Segregación de Funciones (SoD)</strong> que te avisa si a un mismo rol se le otorgan permisos riesgosos combinados (por ejemplo, crear proveedores y también aprobarles pagos):</p>

      <ul class="step-list">
        <li class="step-item">
          <span class="step-num">1</span>
          <div class="step-text"><strong>Haz clic en la sub-pestaña "🛡️ Roles & SoD":</strong> Dentro del módulo de Administración, y presiona el botón <code>Permisos</code> del rol que deseas configurar.</div>
        </li>
        <li class="step-item">
          <span class="step-num">2</span>
          <div class="step-text"><strong>Marca o desmarca las casillas:</strong> Activa permisos de <em>Lectura</em>, <em>Escritura</em> o <em>Anulación</em> para cada módulo.</div>
        </li>
        <li class="step-item">
          <span class="step-num">3</span>
          <div class="step-text"><strong>Haz clic en "Guardar Permisos":</strong> El auditor SoD validará las reglas en vivo y guardará la configuración del rol.</div>
        </li>
      </ul>

      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Matriz de Permisos por Rol y Auditoría Antifraude SoD en Vivo</span>
        </div>
        <img src="screenshots/18_sod_permisos_modal.png" alt="Paso 18: Permisos y SoD" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Paso 18: Configuración granular de permisos con alerta preventiva de conflictos SoD.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

    <!-- PASO 19: VISTAS SEGÚN EL CARGO -->
    <section class="module-card" id="vistas-roles">
      <div class="module-header">
        <h2>Paso 19. Así se Adapta la Interfaz según el Cargo de cada Usuario</h2>
        <span class="module-tag">Menú Inteligente por Rol</span>
      </div>
      <p>El ERP oculta automáticamente los módulos que no corresponden al cargo del trabajador para que su pantalla sea más simple, rápida y segura:</p>

      <h3 style="margin:18px 0 8px 0; color:#0f172a;">💼 Vista del Vendedor Comercial</h3>
      <p>Solo visualiza sus módulos comerciales (Ciclo Comercial, Facturación y Clientes) y únicamente sus propias cotizaciones:</p>
      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Interfaz Simplificada para el Rol: VENDEDOR</span>
        </div>
        <img src="screenshots/19_vista_vendedor.png" alt="Vista Vendedor" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Vista Vendedor: Menú acotado al área comercial y creación de cotizaciones.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>

      <h3 style="margin:24px 0 8px 0; color:#0f172a;">💰 Vista del Tesorero / Cuentas por Pagar</h3>
      <p>Enfocada en recepción de facturas de compra XML, eventos RADIAN, Documento Soporte y Cartera:</p>
      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Interfaz Especializada para el Rol: TESORERO</span>
        </div>
        <img src="screenshots/20_vista_tesorero.png" alt="Vista Tesorero" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Vista Tesorero: Gestión de compras, RADIAN, pagos y recaudos.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>

      <h3 style="margin:24px 0 8px 0; color:#0f172a;">🛒 Vista del Cajero Punto de Venta (POS)</h3>
      <p>Pantalla limpia de mostrador dedicada exclusivamente a turnos de caja y tirillas POS:</p>
      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Interfaz Exclusiva de Mostrador para el Rol: CAJERO POS</span>
        </div>
        <img src="screenshots/21_vista_cajero_pos.png" alt="Vista Cajero POS" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Vista Cajero POS: Operación rápida de apertura de turno y ventas de mostrador.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>

      <h3 style="margin:24px 0 8px 0; color:#0f172a;">👥 Vista de Recursos Humanos y Nómina</h3>
      <p>Acceso exclusivo al módulo de empleados, novedades y Nómina Electrónica DIAN:</p>
      <div class="screenshot-box">
        <div class="screenshot-header">
          <div class="dots"><div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div></div>
          <span>Interfaz Especializada para el Rol: RECURSOS HUMANOS</span>
        </div>
        <img src="screenshots/22_vista_rrhh.png" alt="Vista RRHH" onclick="zoomImage(this)">
        <div class="screenshot-caption">
          <span>Vista Recursos Humanos: Gestión exclusiva de personal y liquidación de nómina.</span>
          <span>🔍 Clic para ampliar</span>
        </div>
      </div>
    </section>

  </main>

  <!-- Visor de Imagen en Pantalla Completa -->
  <div id="lightbox" onclick="closeLightbox()">
    <img id="lightbox-img" src="" alt="Vista Ampliada">
  </div>

  <script>
    function zoomImage(img) {
      const lb = document.getElementById('lightbox');
      const lbImg = document.getElementById('lightbox-img');
      lbImg.src = img.src;
      lb.style.display = 'flex';
    }
    function closeLightbox() {
      document.getElementById('lightbox').style.display = 'none';
    }
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') closeLightbox();
    });
    function filterMenu(q) {
      const term = (q || '').toLowerCase().trim();
      const items = document.querySelectorAll('#tutorial-nav-list li');
      items.forEach(li => {
        if (li.classList.contains('menu-section')) return;
        const txt = (li.textContent || '').toLowerCase();
        li.style.display = (!term || txt.includes(term)) ? '' : 'none';
      });
    }
  </script>
</body>
</html>
"""

out_dir = os.path.join(os.path.dirname(__file__), "..", "src", "static", "tutorial")
os.makedirs(out_dir, exist_ok=True)
out_file = os.path.join(out_dir, "index.html")
with open(out_file, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"✅ Tutorial interactivo generado exitosamente en: {out_file}")
