#!/usr/bin/env python3
"""
================================================================================
 GESTOR DE DATOS DE DEMOSTRACIÓN (DEMO) — ERP CORPORATIVO COLOMBIA
================================================================================
Permite poblar o limpiar controladamente los datos de prueba del sistema:
  - --poblar, --seed   : Siembra empresas de prueba con branding/logos, clientes,
                         productos, bodegas y cuentas de usuario para todos los roles.
  - --limpiar, --clean  : Elimina todas las empresas y registros de demostración
                         dejando la base de datos 100% limpia y lista para producción,
                         conservando el catálogo PUC, parámetros tributarios DIAN
                         y el Superadministrador (admin@sistema.com / admin123).
  - --estado, --status  : Muestra si la base de datos activa tiene datos demo o está limpia.
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DIR = os.path.join(BASE_DIR, "App")
SRC_DIR = os.path.join(APP_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Importar funciones del gestor principal para reutilizar la conexión y arranque de PostgreSQL
sys.path.insert(0, os.path.join(APP_DIR, "scripts"))
import gestor_sistema


def setup_active_env():
    cfg = gestor_sistema.load_config()
    db_cfg = gestor_sistema.active_db_cfg(cfg)
    gestor_sistema.ensure_database_exists(db_cfg)
    dsn = gestor_sistema.build_dsn_from_cfg(db_cfg)
    os.environ["SAP_PG_DSN"] = dsn
    from sap_colombia import database as sap_db
    sap_db.PG_DSN = dsn
    # Asegurar que el esquema base y PUC existan
    sap_db.init_db(seed=False)
    return cfg, dsn


def poblar_demo_action(assume_yes=False):
    cfg, dsn = setup_active_env()
    db_name = gestor_sistema.active_dbname(cfg)
    print(f"\n🌱 Poblando base de datos activa '{db_name}' con datos de demostración...")
    from sap_colombia import demo_data
    res = demo_data.sembrar_datos_demo()
    print("✅ ¡Datos de demostración sembrados con éxito!")
    print(f"   • Empresas creadas : {res.get('empresas', 0)} (Empresa Corporativa S.A.S. y Inversiones Andinas)")
    print(f"   • Bodegas creadas  : {res.get('bodegas', 0)} (BODEGA-01 Bodega Principal)")
    print(f"   • Clientes creados : {res.get('clientes', 0)}")
    print(f"   • Productos creados: {res.get('productos', 0)} (P001 - P005 con tarifas IVA)")
    print(f"   • Empleados creados: {res.get('empleados', 0)}")
    print(f"   • Cajas POS        : {res.get('cajas_pos', 0)}")
    print(f"   • Usuarios demo    : {res.get('usuarios', 0)} (gerente, contador, vendedor, tesorero, cajero, rrhh, almacen)")
    print("\n🔑 Puedes iniciar sesión con:")
    print("   • Superadmin: admin@sistema.com / admin123")
    print("   • Gerente   : gerente@empresa.com / Gerente123!")
    print("   • Contador  : contador@empresa.com / Contador123!")


def limpiar_demo_action(assume_yes=False, full_purge=False):
    cfg, dsn = setup_active_env()
    db_name = gestor_sistema.active_dbname(cfg)
    print(f"\n⚠️  ATENCIÓN: Se procederá a LIMPIAR los datos de prueba de la base de datos '{db_name}'.")
    print("   Se preservará siempre el catálogo PUC, parámetros DIAN y el Superadministrador (admin@sistema.com).")
    
    if not assume_yes:
        confirm = input(f"¿Estás seguro de que deseas limpiar los datos demo de '{db_name}'? (s/n) [n]: ").strip().lower()
        if confirm not in ("s", "si", "y", "yes"):
            print("❌ Operación cancelada por el usuario.")
            return

    from sap_colombia import demo_data
    demo_data.limpiar_datos_demo(solo_ficticios=not full_purge)
    print(f"✨ ¡Base de datos '{db_name}' limpia con éxito!")
    print("   El sistema queda 100% limpio y listo para registrar tus empresas reales.")
    print("   Acceso inicial preservado: admin@sistema.com / admin123")


def estado_demo_action():
    cfg, dsn = setup_active_env()
    db_name = gestor_sistema.active_dbname(cfg)
    from sap_colombia import demo_data
    st = demo_data.estado_datos_demo()
    print(f"\n📊 Estado de la base de datos activa: '{db_name}'")
    print(f"   • Empresas registradas : {st['total_empresas']} (Demo: {st['empresas_demo']})")
    print(f"   • Clientes registrados : {st['total_clientes']}")
    print(f"   • Productos registrados: {st['total_productos']}")
    print(f"   • Usuarios registrados : {st['total_usuarios']} (Demo: {st['usuarios_demo']})")
    if st["tiene_demo"]:
        print("   👉 Diagnóstico: 🌱 CONTIENE DATOS DE DEMOSTRACIÓN (Para vaciar: --limpiar)")
    elif st["es_limpio"]:
        print("   👉 Diagnóstico: ✨ SISTEMA LIMPIO / PRODUCCIÓN (Para poblar demo: --poblar)")
    else:
        print("   👉 Diagnóstico: 🏢 DATOS DE PRODUCCIÓN REALES REGISTRADOS")


def main():
    parser = argparse.ArgumentParser(
        description="Gestor de Datos Demo — ERP Corporativo Colombia",
        epilog="Ejemplos:\n  python3 App/scripts/gestionar_datos_demo.py --poblar\n  python3 App/scripts/gestionar_datos_demo.py --limpiar\n  python3 App/scripts/gestionar_datos_demo.py --estado\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--poblar", "--seed", action="store_true", help="Poblar base de datos activa con datos demo")
    group.add_argument("--limpiar", "--clean", action="store_true", help="Limpiar datos demo de la base de datos activa")
    group.add_argument("--estado", "--status", action="store_true", help="Consultar estado de la base de datos")
    parser.add_argument("--full", action="store_true", help="En limpieza: vaciar completamente empresas y tablas operacionales")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirmar automáticamente sin preguntar")

    args = parser.parse_args()

    # Ejecutar dentro del contexto de servidor PostgreSQL (si es embebido, lo arranca y detiene)
    if args.poblar:
        gestor_sistema.with_db_server(poblar_demo_action, assume_yes=args.yes)
    elif args.limpiar:
        gestor_sistema.with_db_server(limpiar_demo_action, assume_yes=args.yes, full_purge=args.full)
    elif args.estado:
        gestor_sistema.with_db_server(estado_demo_action)


if __name__ == "__main__":
    main()
