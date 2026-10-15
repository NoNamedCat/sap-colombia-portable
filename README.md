# ERP SAP Colombia - Versión Portable Autónoma

Esta versión está empaquetada bajo el principio de **cero instalación (Plug & Play)** y **separación total entre código y datos** para garantizar actualizaciones seguras y portabilidad completa (en disco local o memoria USB).

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
│   └── src/                         <-- Código fuente Python accesible y UI (HTML/CSS/JS)
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

## 📖 Tutorial y Manual en Línea

Puedes consultar el manual integral e interactivo con capturas de pantalla reales directamente en:
👉 **[https://nonamedcat.github.io/sap-colombia-portable/](https://nonamedcat.github.io/sap-colombia-portable/)**

---

## 🚀 Cómo Iniciar el Programa

### En Linux
Simplemente haz doble clic en `Iniciar_SAP_Linux.sh` (o ejecútalo desde terminal):
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

### En tu sistema actual usando Proton
Puedes probar el entorno Windows directamente ejecutando:
```bash
./Ejecutar_Con_Proton.sh
```

---

## 🔄 Cómo Realizar Actualizaciones (Sin Riesgo de Perder Datos)

Para actualizar el sistema a una nueva versión:
1. Asegúrate de que el programa esté cerrado.
2. Descarga la nueva versión.
3. Reemplaza únicamente la carpeta `App/`.
4. Mantén la carpeta `Data/` tal como está.
5. Inicia el sistema: todas tus facturas, numeraciones DIAN, terceros y usuarios seguirán intactos.
