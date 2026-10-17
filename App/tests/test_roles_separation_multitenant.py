"""Tests para Separación de Roles (Administrador de Sistema vs Empresa) y Multi-Tenant."""
import json
import pytest
from sap_colombia import database as db, auth, admin, rbac, dbutil


def test_rbac_roles_tipo_sistema_vs_empresa():
    """Valida la clasificación de roles entre SISTEMA y EMPRESA."""
    conn = db.get_connection()
    roles = dbutil.query(conn, "SELECT nombre, tipo FROM roles").fetchall()
    conn.close()
    roles_map = {r["nombre"]: r.get("tipo") for r in roles}
    
    assert roles_map["SUPERADMIN"] == "SISTEMA"
    assert roles_map["ADMIN_SISTEMA"] == "SISTEMA"
    assert roles_map["ADMIN"] == "SISTEMA"
    
    assert roles_map["ADMIN_EMPRESA"] == "EMPRESA"
    assert roles_map["CAJERO_POS"] == "EMPRESA"
    assert roles_map["TESORERO"] == "EMPRESA"
    assert roles_map["RECURSOS_HUMANOS"] == "EMPRESA"


def test_multitenant_mapping_and_access():
    """Valida la asignación y desasignación de usuarios a empresas."""
    import time
    ts = int(time.time() * 1000) % 10000000
    conn = db.get_connection()
    # Crear una empresa adicional de prueba
    cur = dbutil.query(
        conn,
        "INSERT INTO empresas (nit, razon_social) VALUES (?, ?) RETURNING id",
        (f"901{ts:06d}", f"Empresa Multi {ts}")
    )
    segunda_emp_id = cur.fetchone()["id"]
    
    # Crear un usuario de prueba
    h, salt = auth.hash_password("UserPass123!")
    cur = dbutil.query(
        conn,
        "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) VALUES (?, ?, ?, ?, ?, 1, '2026-01-01T00:00:00') RETURNING id",
        (f"operador_{ts}@multitenant.com", "Operador Multi", "VENDEDOR", h, salt)
    )
    user_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()

    # Inicialmente no tiene empresas asignadas
    empresas = admin.get_empresas_for_user(user_id)
    assert len(empresas) == 0

    # Asignar a la segunda empresa como VENDEDOR
    ok = admin.assign_user_to_empresa(user_id, segunda_emp_id, rol_en_empresa="VENDEDOR", es_predeterminada=True)
    assert ok is True

    # Verificar que ahora tiene acceso
    empresas = admin.get_empresas_for_user(user_id)
    assert len(empresas) == 1
    assert empresas[0]["id"] == segunda_emp_id
    assert empresas[0]["rol_en_empresa"] == "VENDEDOR"

    # Verificar mapeo general para el panel de administración
    mapping = admin.get_user_empresas_mapping()
    item = next((m for m in mapping if m["usuario_id"] == user_id and m["empresa_id"] == segunda_emp_id), None)
    assert item is not None
    assert item["rol_en_empresa"] == "VENDEDOR"

    # Desasignar
    ok_del = admin.unassign_user_from_empresa(user_id, segunda_emp_id)
    assert ok_del is True
    assert len(admin.get_empresas_for_user(user_id)) == 0


def test_sysadmin_has_global_access_to_all_empresas():
    """Un Administrador de Sistema (ADMIN o SUPERADMIN) tiene acceso automático a todas las empresas."""
    conn = db.get_connection()
    admin_row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'admin@saluki.com'").fetchone()
    conn.close()
    assert admin_row is not None
    admin_id = admin_row["id"]

    empresas = admin.get_empresas_for_user(admin_id)
    conn = db.get_connection()
    total_empresas = dbutil.query(conn, "SELECT COUNT(*) AS total FROM empresas").fetchone()["total"]
    conn.close()

    assert len(empresas) == total_empresas
    assert total_empresas > 0


def test_sod_risk_catalog_and_toxic_combinations():
    """Valida el catálogo de riesgos SoD y la detección de combinaciones tóxicas."""
    catalogo = rbac.catalogo_conflictos_sod()
    assert len(catalogo) >= 5
    ids = [c["id"] for c in catalogo]
    assert "SOD-001" in ids
    assert "SOD-002" in ids
    assert "SOD-005" in ids

    # Conflict: Compras + CxP
    perms_toxicas = ["compras:create", "compras:read", "cxp:create", "cxp:read"]
    conflictos = rbac.analizar_conflictos_sod(perms_toxicas)
    assert len(conflictos) == 1
    assert conflictos[0]["id"] == "SOD-001"
    assert conflictos[0]["nivel"] == "ALTO"

    # Conflicto múltiple: Nómina + CxP y Facturación + Notas Crédito
    perms_multi = ["nominas:create", "cxp:create", "facturacion:create", "notas_credito:create"]
    conflictos_multi = rbac.analizar_conflictos_sod(perms_multi)
    assert len(conflictos_multi) == 2
    conf_ids = {c["id"] for c in conflictos_multi}
    assert conf_ids == {"SOD-002", "SOD-003"}

    # Rol sin conflictos (ej. Solo Vendedor)
    perms_limpios = ["facturacion:read", "facturacion:create", "clientes:read", "clientes:create"]
    assert len(rbac.analizar_conflictos_sod(perms_limpios)) == 0


def test_tri_state_permission_resolver():
    """Valida la resolución tri-estado: FULL, READ_ONLY o NONE."""
    # Lectura pura
    perms_lectura = {"facturacion:read", "compras:read"}
    assert rbac.resolver_permiso_tri_estado(perms_lectura, "facturacion") == "READ_ONLY"
    assert rbac.resolver_permiso_tri_estado(perms_lectura, "compras") == "READ_ONLY"
    assert rbac.resolver_permiso_tri_estado(perms_lectura, "cxp") == "NONE"

    # Escritura / Modificación
    perms_escritura = {"facturacion:read", "facturacion:create"}
    assert rbac.resolver_permiso_tri_estado(perms_escritura, "facturacion") == "FULL"

    # Superadmin con comodín *
    assert rbac.resolver_permiso_tri_estado({"*"}, "cualquier_cosa") == "FULL"


def test_quote_discount_approval_workflow_and_row_scoping():
    """Valida el flujo de aprobación por límite de descuento (>15%) y data ownership."""
    from sap_colombia import commercial_cycle

    # 1. Cotización normal (descuento <= 15%)
    cot_normal = commercial_cycle.crear_cotizacion({
        "cliente_nit": "900123456",
        "usuario_id": 999,
        "descuento_porcentaje": "10.00",
        "lineas": [{"producto_codigo": "ITEM-1", "descripcion": "Prod A", "cantidad": 2, "valor_unitario": "50000.00"}]
    })
    assert cot_normal["estado"] == "COTIZADO"
    assert cot_normal["usuario_id"] == 999

    # 2. Cotización con descuento excesivo (> 15%) requiere aprobación
    cot_excesiva = commercial_cycle.crear_cotizacion({
        "cliente_nit": "900123456",
        "usuario_id": 888,
        "descuento_porcentaje": "25.00",
        "lineas": [{"producto_codigo": "ITEM-2", "descripcion": "Prod B", "cantidad": 1, "valor_unitario": "100000.00"}]
    })
    assert cot_excesiva["estado"] == "REQUIERE_APROBACION"
    assert cot_excesiva["aprobado_por"] is None

    # Intentar convertir sin visto bueno debe ser rechazado
    with pytest.raises(ValueError, match="requiere aprobación previa"):
        commercial_cycle.convertir_cotizacion_a_pedido(cot_excesiva["id"])

    # Aprobar por gerencia / admin
    res_aprob = commercial_cycle.aprobar_cotizacion(cot_excesiva["id"], usuario_aprobador_id=1)
    assert res_aprob["estado"] == "COTIZADO"
    assert res_aprob["aprobado_por"] == 1

    # Ahora sí debe permitir convertir a pedido
    ped = commercial_cycle.convertir_cotizacion_a_pedido(cot_excesiva["id"])
    assert ped["estado"] == "PENDIENTE"
    assert ped["usuario_id"] == 888

    # 3. Data Ownership: Filtrado de cotizaciones y pedidos por vendedor
    cots_vendedor = commercial_cycle.listar_cotizaciones(usuario_id=888)
    assert any(c["id"] == cot_excesiva["id"] for c in cots_vendedor)
    assert not any(c["id"] == cot_normal["id"] for c in cots_vendedor)

