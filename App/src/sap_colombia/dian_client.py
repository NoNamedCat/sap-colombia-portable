import base64
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class TransmisionResult:
    """Resultado de la transmisión o consulta de una factura o documento electrónico."""

    estado: str
    track_id: str
    status_code: str
    status_description: str
    fecha_validacion: str = ""
    xml_base64_bytes: str = ""
    application_response_xml: str = ""
    errores: list[str] = field(default_factory=list)
    cude: str = ""
    raw_response: str = ""

    def __post_init__(self):
        if self.errores is None:
            self.errores = []


@runtime_checkable
class DianClientProtocol(Protocol):
    """Protocolo unificado que deben satisfacer tanto el cliente mock como el SOAP real."""

    def transmitir_xml(self, xml: str) -> TransmisionResult:
        """Transmite el documento XML firmado a la DIAN (o al mock)."""
        ...

    def consultar(self, track_id: str) -> TransmisionResult:
        """Consulta el estado de validación de un documento por su track_id."""
        ...


class DianClient:
    """Cliente HTTP REST para la transmisión de facturas a DIAN (o su mock)."""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url.rstrip("/")

    def transmitir(self, factura) -> TransmisionResult:
        return self.transmitir_xml(factura.xml)

    def transmitir_xml(self, xml: str) -> TransmisionResult:
        data = xml.encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/vp/envio-factura",
            data=data,
            headers={"Content-Type": "application/xml; charset=utf-8"},
            method="POST",
        )
        return self._parsear(req)

    def consultar(self, track_id: str) -> TransmisionResult:
        req = urllib.request.Request(
            f"{self.base_url}/vp/consulta/{track_id}",
            method="GET",
        )
        return self._parsear(req)

    def _parsear(self, req) -> TransmisionResult:
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")

        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return TransmisionResult(
                estado="Rechazada",
                track_id="",
                status_code="1001",
                status_description="Respuesta no válida del servidor",
                raw_response=body,
            )

        def texto(tag):
            nodo = root.find(tag)
            return (nodo.text or "").strip() if nodo is not None else ""

        track_id = texto("TrackId")
        status_code = texto("StatusCode")
        description = texto("StatusDescription")
        fecha = texto("FechaValidacion")
        xml_b64 = texto("XmlBase64Bytes")
        app_resp_xml = texto("ApplicationResponse") or ""

        if xml_b64 and not app_resp_xml:
            try:
                app_resp_xml = base64.b64decode(xml_b64).decode("utf-8", errors="replace")
            except Exception:
                pass

        errores = []
        err_nodes = root.findall(".//ErrorMessage") or root.findall(".//string")
        for err in err_nodes:
            if (err.text or "").strip():
                errores.append(err.text.strip())

        if status_code == "00":
            estado = "Aceptada"
        elif status_code in ("1002", "90", "66"):
            estado = "NoEncontrada"
        else:
            estado = "Rechazada"

        return TransmisionResult(
            estado=estado,
            track_id=track_id,
            status_code=status_code,
            status_description=description,
            fecha_validacion=fecha,
            xml_base64_bytes=xml_b64,
            application_response_xml=app_resp_xml,
            errores=errores,
            raw_response=body,
        )
