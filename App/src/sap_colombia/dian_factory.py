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


def get_dian_client(emisor_nit: str = "", empresa: dict | None = None) -> DianClient | DianSoapClient:
    """Devuelve el cliente DIAN según el modo global del sistema (``mock`` vs ``real``)."""
    mode = config.dian_mode()
    if mode == "mock_soap":
        return get_mock_soap_client(emisor_nit, empresa)
    if mode == config.DIAN_MODE_REAL:
        cfg = ConfigDian(
            url_transmit=config.dian_transmit_url(),
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
