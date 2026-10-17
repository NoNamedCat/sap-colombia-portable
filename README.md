# ERP Corporativo Colombia (DIAN UBL 2.1) — Versión Portable Autónoma

Plataforma ERP empresarial multi-empresa para Colombia con **Facturación Electrónica DIAN UBL 2.1**, **Eventos RADIAN**, **Documento Soporte (CUDS)**, **Nómina Electrónica (CUNE)**, **Punto de Venta POS**, **Contabilidad PUC NIIF**, **Impuestos DIAN (300, 350, Exógena)**, **Segregación de Funciones Antifraude (SoD ISO 27001)** y **Estudio de Identidad Visual por Empresa (Logo, Nombre, Colores y Fuentes Propias)**.

Empaquetada bajo el principio de **cero instalación (Plug & Play)** y **separación total entre código (`App/`) y datos (`Data/`)** para garantizar actualizaciones seguras y portabilidad completa.

---

## 📖 Tutorial Visual Paso a Paso (con Indicadores de Cursor)

Consulta el **Manual y Tutorial Interactivo desde Cero**, donde cada pantalla muestra paso a paso con números (`①`, `②`, `③`) y el cursor (`🖱️`) exactamente dónde hacer clic:

- 🌐 **En línea (GitHub Pages):** **[https://nonamedcat.github.io/sap-colombia-portable/](https://nonamedcat.github.io/sap-colombia-portable/)**
- 💻 **Local (con el servidor encendido):** **[http://127.0.0.1:8000/tutorial/index.html](http://127.0.0.1:8000/tutorial/index.html)**

---

## ✨ Novedades Principales

- 🎨 **Identidad Visual y Marca Independiente por Empresa (Multi-Tenant Branding):**
  - Personaliza el **Nombre / Razón Social** y la **Sigla de Marca** de cada empresa registrada.
  - Sube el **Logo propio** de cada empresa (`.png`, `.svg`, `.jpg`, `.webp`).
  - Configura la **Paleta de Colores** por empresa (*Color Primario*, *Secundario*, *Menú Lateral* y *Fondo*) o aplica uno de los **5 Temas Corporativos de 1 Clic** (*Horizon Blue*, *Esmeralda*, *Índigo*, *Borgoña*, *Grafito*).
  - Selecciona la **Fuente Tipográfica** o sube archivos de fuente propios (`.ttf`, `.otf`, `.woff`, `.woff2`) para cada empresa.
- 🧭 **Interfaz Corporativa Moderna:**
  - Menú lateral izquierdo colapsable organizado por áreas operativas.
  - Buscador rápido de módulos en vivo (`Ctrl + K`).
  - Barra superior ejecutiva con selector de empresa en tiempo real, estado de periodo contable y acceso rápido a `🎨 Marca & Tema`.

---

## 📂 Estructura de Directorios

```text
SAP_Colombia_Portable/
│
├── App/                             <-- ARCHIVOS DEL SISTEMA (Se actualizan reemplazando esta carpeta)
│   ├── engine/                      <-- Motores de PostgreSQL embebidos (Linux / Windows)
│   │   ├── linux/
│   │   └── windows/
│   ├── runtime/                     <-- Entornos de ejecución
│   ├── scripts/                     <-- Generadores automáticos de capturas y tutorial HTML
│   ├── src/                         <-- Código fuente Python, API REST y UI (HTML/CSS/JS)
│   └── tests/                       <-- Suite completa de pruebas automatizadas (Pytest + Playwright)
│
├── Data/                            <-- TUS DATOS (NUNCA SE BORRAN NI TOCAN EN ACTUALIZACIONES)
│   ├── db/                          <-- Cluster PostgreSQL embebido en Linux (puerto 54329)
│   ├── db_windows/                  <-- Cluster PostgreSQL embebido en Windows (puerto 54329)
│   ├── backups/                     <-- Respaldos universales JSON para migrar entre SO o servidores
│   ├── certificados/                <-- Certificados digitales .p12 para firma XAdES-BES
│   ├── logs/                        <-- Registros del servidor y de auditoría SoD
│   └── config.json                  <-- Configuración global (BD embebida vs externa, puertos, DIAN)
│
├── Iniciar_ERP_Linux.sh             <-- Lanzador de 1-clic para Linux (Ubuntu, Debian, Fedora, Arch)
├── Iniciar_ERP_Windows.bat          <-- Lanzador de 1-clic para Windows 10/11
├── Configurar_ERP_Linux.sh          <-- Panel de Control y Configuración en Linux (Menú interactivo)
├── Configurar_ERP_Windows.bat       <-- Panel de Control y Configuración en Windows (Menú interactivo)
├── Ejecutar_Con_Proton.sh           <-- Lanzador para probar la versión Windows en Linux vía Proton
└── README.md
```

---

## 🚀 Cómo Iniciar el Programa

### En Linux
Haz doble clic en `Iniciar_ERP_Linux.sh` (o ejecútalo desde la terminal):
```bash
./Iniciar_ERP_Linux.sh
```
* Arranca automáticamente el motor PostgreSQL embebido en el puerto aislado `54329` (o conecta al PostgreSQL externo si fue configurado).
* Selecciona la base de datos adecuada según el entorno activo (`sap_colombia_pruebas` o `sap_colombia`).
* Inicia el servidor web local en el puerto `8000`.
* Abre automáticamente el navegador en `http://127.0.0.1:8000`.
* Al presionar `Ctrl+C` o cerrar la terminal, apaga PostgreSQL limpiamente sin dejar residuos.

### En Windows
Haz doble clic en `Iniciar_ERP_Windows.bat`:
* Levanta el PostgreSQL embebido de Windows (o conecta a tu servidor PostgreSQL externo).
* Inicia la aplicación y abre tu navegador por defecto en `http://127.0.0.1:8000`.
* Al cerrar la ventana, apaga la base de datos automáticamente.

---

## 🎛️ Panel de Control y Configuración (Menú Interactivo)

Tanto en Linux como en Windows dispones de un panel de control interactivo para administrar el sistema sin tocar archivos de configuración manualmente:
- En **Linux**: `./Configurar_ERP_Linux.sh`
- En **Windows**: Doble clic en `Configurar_ERP_Windows.bat`

El panel incluye **10 opciones**:
1. **🚀 Iniciar el ERP Corporativo Ahora**: Levanta servicios y abre el navegador.
2. **🏠 Conmutar a Base de Datos PORTABLE Embebida**: Guarda todo en `Data/db` (Linux) o `Data/db_windows` (Windows).
3. **🌐 Conectar a PostgreSQL EXTERNO**: Conecta a cualquier servidor en red local, Docker o nube (AWS RDS, Supabase, Azure).
4. **🏛️ Cambiar Entorno Global (Pruebas Mockup vs. DIAN Real)**:
   - *🧪 Pruebas (Simulador Local)*: Aísla el trabajo en la BD `sap_colombia_pruebas` sin conexión a internet.
   - *🚀 Trabajo Real (DIAN)*: Conecta con la BD de producción `sap_colombia` y Web Services SOAP oficiales de la DIAN.
5. **🔁 Clonar BD Real a BD de Pruebas (Sandbox Seguro)**: Copia el 100% de empresas, clientes, cuentas y facturas de producción a la BD de pruebas con un clic para ensayar sin comprometer datos reales.
6. **🧹 Reiniciar BD de Pruebas**: Limpia la base de datos de pruebas para empezar desde cero.
7. **📦 Portabilizar / Descargar Motores**: Descarga e instala automáticamente PostgreSQL 17.2 y Python 3.12 con sus dependencias en `App/`.
8. **💾 Exportar Respaldo Universal**: Genera un archivo neutro JSON en `Data/backups/` con todas las tablas.
9. **📥 Importar / Restaurar Respaldo Universal**: Restaura datos entre plataformas (Linux ↔ Windows ↔ PostgreSQL externo).
10. **🔧 Cambiar Puerto Web y Acceso en Red Local (LAN)**: Permite habilitar acceso a otros computadores en red local (`0.0.0.0`).

---

## 🔑 Cuentas de Prueba Incluidas

| Cargo / Rol | Correo Electrónico | Contraseña | Alcance Operativo |
| :--- | :--- | :--- | :--- |
| **SUPERADMIN** | `admin@sistema.com` | `admin123` | Control total de plataforma, empresas, marca/colores/fuentes y SoD |
| **ADMIN_EMPRESA** | `gerente@empresa.com` | `Gerente123!` | Dashboard gerencial, aprobación de descuentos y supervisión |
| **CONTADOR** | `contador@empresa.com` | `Contador123!` | PUC, balance, libros oficiales, impuestos 300/350/Exógena y cierre |
| **VENDEDOR** | `vendedor@empresa.com` | `Vendedor123!` | Ciclo comercial, cotizaciones propias, pedidos y facturación |
| **TESORERO** | `tesorero@empresa.com` | `Tesorero123!` | Buzón XML compras, eventos RADIAN (030/032/033) y Cuentas por Pagar |
| **CAJERO_POS** | `cajero@empresa.com` | `Cajero123!` | Apertura de turno, tickets electrónicos POS y arqueo de caja |
| **RECURSOS_HUMANOS** | `rrhh@empresa.com` | `Nomina123!` | Registro de personal, liquidación mensual y Nómina Electrónica DIAN |
| **ALMACENISTA** | `almacen@empresa.com` | `Almacen123!` | Kardex, listas de precios y control de lotes con vencimiento |

---

## 🔄 Cómo Realizar Actualizaciones (Sin Riesgo de Perder Datos)

1. Asegúrate de que el programa esté cerrado.
2. Descarga la nueva versión.
3. Reemplaza únicamente la carpeta `App/`.
4. Mantén la carpeta `Data/` tal como está.
5. Inicia el sistema: todas tus empresas, logos, temas, facturas, numeraciones DIAN, terceros y usuarios seguirán intactos.
