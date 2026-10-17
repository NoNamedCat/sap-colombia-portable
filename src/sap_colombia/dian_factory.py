"""Fábrica del cliente DIAN según la configuración de entorno.

Selecciona entre el mock server local (desarrollo/pruebas) y el cliente
SOAP real de DIAN (producción) basándose en ``SAP_DIAN_MODE``.
"""

import logging

from sap_colombia import config
from sap_colombia.dian_client import DianClient
from sap_colombia.dian_mock_server import DianMockServer
from sap_colombia.dian_soap_client import ConfigDian, DianSoapClient

logger = logging.getLogger(__name__)

_mock_server: DianMockServer | None = None


def get_dian_client(emisor_nit: str | dict = "", empresa: dict | None = None) -> DianClient | DianSoapClient:
    """Devuelve el cliente DIAN apropiado según la configuración global y de la empresa.

    Prioridad:
    1. Si el modo global es ``mock_soap``, usa el simulador SOAP WCF local.
    2. Si el modo global es ``real``, transmite por SOAP real (usando ``empresa.url_dian``
       si está definida, o el endpoint oficial DIAN según ``tipo_ambiente``).
    3. Si el modo global es ``auto`` (o por defecto cuando la empresa define ``url_dian``
       y no se ha forzado ``mock``), usa ``url_dian`` si apunta a un servidor real;
       si está vacía, usa el simulador Mockup local.
    """
    import os

    if isinstance(emisor_nit, dict) and empresa is None:
        empresa = emisor_nit
        emisor_nit = str(empresa.get("nit") or "")

    mode = config.dian_mode()
    emp_url = str((empresa or {}).get("url_dian") or "").strip()
    emp_amb = str((empresa or {}).get("tipo_ambiente") or "2").strip()

    if mode == "mock_soap":
        return get_mock_soap_client(str(emisor_nit), empresa)

    # Determinar si se forzó globalmente el modo mock (por variable de entorno o Data/config.json)
    env_mode = os.environ.get("SAP_DIAN_MODE", "").strip().lower()
    cfg_mode = str(config._load_portable_config().get("dian", {}).get("mode", "")).strip().lower()
    forced_mock = (env_mode == "mock") or (not env_mode and cfg_mode == "mock")

    use_real_soap = False
    if mode == config.DIAN_MODE_REAL:
        use_real_soap = True
    elif not forced_mock and emp_url.startswith(("http://", "https://")) and "mock" not in emp_url.lower():
        use_real_soap = True

    if use_real_soap:
        if emp_url.startswith(("http://", "https://")):
            target_url = emp_url
        elif os.environ.get("SAP_DIAN_TRANSMIT_URL"):
            target_url = config.dian_transmit_url()
        else:
            target_url = (
                config.DIAN_PRODUCCION_URL_DEFAULT
                if emp_amb == "2"
                else config.DIAN_HABILITACION_URL_DEFAULT
            )
        cfg = ConfigDian(
            url_transmit=target_url,
            user_api=config.dian_user(),
            password_api=config.dian_password(),
            timeout=config.dian_timeout(),
            test_set_id=config.dian_test_set_id(),
        )
        logger.info("DIAN mode: real, endpoint=%s", cfg.url_transmit)
        return DianSoapClient(cfg)
    return _get_mock_client(emisor_nit, empresa)


def get_mock_soap_client(emisor_nit: str = "", empresa: dict | None = None) -> DianSoapClient:
    """Devuelve un cliente SOAP WCF apuntando al mock server local (pruebas 1:1 de SOAP sin internet)."""
    global _mock_server
    from sap_colombia.cufe_calculator import normalizar_numero
    if _mock_server is None:
        _mock_server = DianMockServer(emisor_nit=emisor_nit, empresa=empresa or {})
        _mock_server.start()
    else:
        if emisor_nit:
            _mock_server.emisor_nit = normalizar_numero(emisor_nit)
        if empresa:
            _mock_server.empresa = empresa

    cfg = ConfigDian(
        url_transmit=f"{_mock_server.base_url}/WcfDianCustomerServices.svc",
        user_api="pruebas",
        password_api="pass123",
        test_set_id="test-set-001",
    )
    return DianSoapClient(cfg)


def _get_mock_client(emisor_nit: str, empresa: dict | None = None) -> DianClient:
    """Devuelve (y arranca si es necesario) el mock server local."""
    global _mock_server
    from sap_colombia.cufe_calculator import normalizar_numero
    if _mock_server is None:
        _mock_server = DianMockServer(emisor_nit=emisor_nit, empresa=empresa or {})
        _mock_server.start()
    else:
        if emisor_nit:
            _mock_server.emisor_nit = normalizar_numero(emisor_nit)
        if empresa:
            # El mock se comparte entre emitters: se actualizan los parámetros que
            # afectan la validación (rango, ambiente).
            _mock_server.empresa = empresa
    return DianClient(_mock_server.base_url)
