"""Configuración central del sistema ERP Colombia.

Lee variables de entorno con prefijo ``SAP_`` y proporciona acceso
tipado a la configuración de la aplicación. Las claves de entorno
soportadas son:

- ``SAP_DIAN_MODE``: ``mock`` (default) o ``real`` — selecciona el
  cliente DIAN (mock server local o cliente SOAP real).
- ``SAP_DIAN_USER``: usuario API de DIAN (solo modo ``real``).
- ``SAP_DIAN_PASSWORD``: contraseña API de DIAN (solo modo ``real``).
- ``SAP_DIAN_TRANSMIT_URL``: URL del endpoint SOAP de DIAN
  (default: ``https://facturae.dian.gov.co/Services/Documentos/TransmitDocuments``).
- ``SAP_DIAN_TIMEOUT``: timeout en segundos para peticiones SOAP
  (default: ``60``).
- ``SAP_JWT_SECRET``: secreto para firma de tokens JWT (si no se
  define, se genera y persiste en la BD).
"""

import json
import os
from pathlib import Path

DianMode = str

DIAN_MODE_MOCK = "mock"
DIAN_MODE_REAL = "real"

_DIAN_MODE_DEFAULT = DIAN_MODE_MOCK

DIAN_HABILITACION_URL_DEFAULT = (
    "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc"
)
DIAN_PRODUCCION_URL_DEFAULT = (
    "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc"
)

DIAN_TRANSMIT_URL_DEFAULT = DIAN_HABILITACION_URL_DEFAULT

_DIAN_TIMEOUT_DEFAULT = 60


def _load_portable_config() -> dict:
    """Lee Data/config.json si existe en la estructura portable."""
    try:
        # App/src/sap_colombia/config.py -> base portable = parents[3]
        base_dir = Path(__file__).resolve().parents[3]
        cfg_path = base_dir / "Data" / "config.json"
        if cfg_path.is_file():
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def pg_dsn() -> str:
    """Retorna el DSN PostgreSQL desde SAP_PG_DSN o Data/config.json (soporta BD portable embebida o PostgreSQL externo)."""
    from urllib.parse import quote_plus

    env_dsn = _get_env("SAP_PG_DSN")
    if env_dsn:
        return env_dsn
    cfg = _load_portable_config().get("database", {})
    custom_dsn = (cfg.get("dsn") or "").strip()
    if custom_dsn:
        return custom_dsn
    host = _get_env("SAP_DB_HOST") or cfg.get("host") or "127.0.0.1"
    port = _get_env("SAP_DB_PORT") or cfg.get("port") or 54329
    user = _get_env("SAP_DB_USER") or cfg.get("user") or "sap"
    password = _get_env("SAP_DB_PASSWORD") if os.environ.get("SAP_DB_PASSWORD") is not None else (cfg.get("password") or "")
    dbname = _get_env("SAP_DB_NAME") or cfg.get("dbname") or "sap_colombia"
    sslmode = _get_env("SAP_DB_SSLMODE") or cfg.get("sslmode") or ""

    auth_part = quote_plus(str(user))
    if password:
        auth_part += f":{quote_plus(str(password))}"
    dsn = f"postgresql://{auth_part}@{host}:{port}/{dbname}"
    if sslmode:
        dsn += f"?sslmode={quote_plus(str(sslmode))}"
    return dsn



def http_port() -> int:
    """Retorna el puerto HTTP desde PORT o Data/config.json."""
    raw = _get_env("PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    cfg = _load_portable_config().get("server", {})
    try:
        return int(cfg.get("http_port", 8000))
    except (TypeError, ValueError):
        return 8000


def _get_env(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip()


def dian_mode() -> str:
    """Modo de operación DIAN: ``mock``, ``real``, ``mock_soap`` o ``auto``."""
    env_mode = _get_env("SAP_DIAN_MODE").lower()
    if env_mode in (DIAN_MODE_MOCK, DIAN_MODE_REAL, "mock_soap", "auto"):
        return env_mode
    cfg_mode = str(_load_portable_config().get("dian", {}).get("mode", "")).strip().lower()
    if cfg_mode in (DIAN_MODE_MOCK, DIAN_MODE_REAL, "mock_soap", "auto"):
        return cfg_mode
    return _DIAN_MODE_DEFAULT


def dian_user() -> str:
    """Usuario API de DIAN."""
    return _get_env("SAP_DIAN_USER") or str(_load_portable_config().get("dian", {}).get("user", ""))


def dian_password() -> str:
    """Contraseña API de DIAN."""
    return _get_env("SAP_DIAN_PASSWORD") or str(_load_portable_config().get("dian", {}).get("password", ""))


def dian_ambiente() -> str:
    """Ambiente DIAN: '1' para habilitación/pruebas, '2' para producción."""
    return _get_env("SAP_DIAN_AMBIENTE") or str(_load_portable_config().get("dian", {}).get("ambiente", "1"))


def dian_test_set_id() -> str:
    """Identificador del set de pruebas para habilitación."""
    return _get_env("SAP_DIAN_TEST_SET_ID") or str(_load_portable_config().get("dian", {}).get("test_set_id", ""))


def dian_transmit_url() -> str:
    """URL del endpoint SOAP de DIAN para transmisión de documentos."""
    custom = _get_env("SAP_DIAN_TRANSMIT_URL") or str(_load_portable_config().get("dian", {}).get("transmit_url", "")).strip()
    if custom:
        return custom
    if dian_ambiente() == "2":
        return DIAN_PRODUCCION_URL_DEFAULT
    return DIAN_HABILITACION_URL_DEFAULT



def dian_timeout() -> int:
    """Timeout en segundos para peticiones SOAP a DIAN."""
    raw = _get_env("SAP_DIAN_TIMEOUT", str(_DIAN_TIMEOUT_DEFAULT))
    try:
        return int(raw)
    except ValueError:
        return _DIAN_TIMEOUT_DEFAULT


def jwt_secret() -> str | None:
    """Secreto JWT desde entorno, o ``None`` si debe generarse en la BD."""
    val = _get_env("SAP_JWT_SECRET")
    return val if val else None

