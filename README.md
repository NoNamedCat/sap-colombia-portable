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
│   ├── db/                          <-- Cluster de PostgreSQL con todas las tablas y empresas
│   ├── certificados/                <-- Certificados digitales .p12 para firma XAdES-BES
│   ├── logs/                        <-- Registros del servidor y de auditoría SoD
│   └── config.json                  <-- Configuración de puertos y base de datos
│
├── Iniciar_SAP_Linux.sh             <-- Lanzador de 1-clic para Linux (Ubuntu, Debian, Fedora, Arch)
├── Iniciar_SAP_Windows.bat          <-- Lanzador de 1-clic para Windows 10/11
├── Ejecutar_Con_Proton.sh           <-- Lanzador para probar la versión Windows en Linux vía Proton
└── README.md
```

---

## 🚀 Cómo Iniciar el Programa

### En Linux
Haz doble clic en `Iniciar_SAP_Linux.sh` (o ejecútalo desde terminal):
```bash
./Iniciar_SAP_Linux.sh
```
* Inicializa y arranca el motor PostgreSQL embebido en el puerto aislado `54329`.
* Inicia el servidor web local en el puerto `8000`.
* Abre automáticamente el navegador en `http://127.0.0.1:8000`.
* Al presionar `Ctrl+C` o cerrar la terminal, apaga PostgreSQL limpiamente sin dejar residuos.

### En Windows
Haz doble clic en `Iniciar_SAP_Windows.bat`:
* Levanta el PostgreSQL embebido de Windows.
* Inicia la aplicación y abre tu navegador por defecto.
* Al cerrar la ventana, apaga la base de datos automáticamente.

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
