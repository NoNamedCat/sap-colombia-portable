"""Cliente SOAP 1.2 con WS-Security para DIAN FacturaE (WCF).

Transmite el XML UBL firmado a los servicios web oficiales de la DIAN
(WcfDianCustomerServices.svc) mediante operaciones SendBillSync, GetStatus
y SendTestSetAsync, conforme a la Res. 000042 de 2020 y Anexo Técnico 1.9.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import io
import logging
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from sap_colombia.dian_client import TransmisionResult

NS_WSSE = "http://docs.oasis-open.org/wss/2004/08/security/wssecurity/1.0"
NS_WSA = "http://www.w3.org/2005/08/addressing"
NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_WCF = "http://wcf.dian.colombia"
NS_DIAN_RESP = "http://datacontract.schemas.datacontract.org/2004/07/DianResponse"

logger = logging.getLogger(__name__)


class ErrorDian(Exception):
    """Error en la transmisión SOAP a DIAN."""


@dataclass
class ConfigDian:
    """Configuración del endpoint SOAP de DIAN."""

    url_transmit: str
    user_api: str = ""
    password_api: str = ""
    timeout: int = 60
    test_set_id: str = ""


class DianSoapClient:
    """Cliente SOAP 1.2 WCF para el servicio WcfDianCustomerServices de la DIAN."""

    def __init__(self, config: ConfigDian):
        self.config = config
        self.timeout = config.timeout
        self.session = requests.Session()

    def _build_ws_security_header(self, user: str, password: str) -> str:
        """Genera el bloque WS-Security 1.0 con UsernameToken (PasswordDigest)."""
        nonce_bytes = uuid.uuid4().bytes[:16]
        nonce_b64 = base64.b64encode(nonce_bytes).decode("ascii")
        created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        digest = base64.b64encode(
            hashlib.sha1(f"{password}{nonce_b64}{created}".encode("utf-8")).digest()
        ).decode("ascii")
        return (
            f'<wsse:Security xmlns:wsse="{NS_WSSE}">'
            f'<wsse:UsernameToken>'
            f'<wsse:Username>{user}</wsse:Username>'
            f'<wsse:Password Type="{NS_WSSE}#UsernameToken#PasswordDigest">{digest}</wsse:Password>'
            f'<wsse:Nonce EncodingType="{NS_WSSE}#Base64">{nonce_b64}</wsse:Nonce>'
            f'<wsse:Created>{created}</wsse:Created>'
            f'</wsse:UsernameToken>'
            f'</wsse:Security>'
        )

    def _empaquetar_zip_en_memoria(self, xml_doc: str, nombre_base: str) -> tuple[str, str]:
        """Comprime el XML en un .zip en memoria y retorna (nombre_archivo_zip, base64_zip)."""
        clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "", nombre_base) or "documento"
        xml_name = f"{clean_name}.xml"
        zip_name = f"{clean_name}.zip"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(xml_name, xml_doc.encode("utf-8"))

        zip_bytes = buf.getvalue()
        zip_b64 = base64.b64encode(zip_bytes).decode("ascii")
        return zip_name, zip_b64

    def _extraer_identificadores_xml(self, xml_doc: str) -> tuple[str, str, str]:
        """Extrae (tipo_doc, emisor_nit, consecutivo) del XML UBL."""
        try:
            root = ET.fromstring(xml_doc)
            tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
            tipo = "fv"
            if "CreditNote" in tag:
                tipo = "nc"
            elif "DebitNote" in tag:
                tipo = "nd"
            elif "ApplicationResponse" in tag:
                tipo = "ar"

            # Consecutivo
            id_el = root.find(".//{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID")
            consecutivo = (id_el.text or "").strip() if id_el is not None else uuid.uuid4().hex[:8]

            # Nit emisor
            nit = ""
            for tag_nit in (".//{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CompanyID",
                            ".//{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID"):
                el = root.find(tag_nit)
                if el is not None and (el.text or "").strip():
                    nit = "".join(c for c in el.text if c.isdigit())
                    if nit:
                        break
            if not nit:
                nit = "900000000"

            return tipo, nit, consecutivo
        except Exception:
            return "fv", "900000000", uuid.uuid4().hex[:8]

    def _generar_nombre_archivo_dian(self, tipo: str, nit: str, consecutivo: str) -> str:
        """Genera el nombre de archivo normativo según Anexo Técnico (ej: fv09001234560002600000001)."""
        nit_10 = "".join(c for c in nit if c.isdigit()).zfill(10)[:10]
        consecutivo_num = "".join(c for c in consecutivo if c.isdigit()) or "1"
        consecutivo_hex_or_pad = consecutivo_num.zfill(10)[-10:]
        year_2 = datetime.datetime.now().strftime("%y")
        return f"{tipo.lower()}{nit_10}{year_2}{consecutivo_hex_or_pad}"

    def transmitir_xml(
        self,
        xml: str,
        tipo_documento: str = "FV",
        consecutivo: str = "",
        nit_emisor: str = "",
    ) -> TransmisionResult:
        """Transmite el XML firmado mediante el método oficial SendBillSync de WCF."""
        tipo_auto, nit_auto, consecutivo_auto = self._extraer_identificadores_xml(xml)
        tipo = tipo_documento or tipo_auto
        nit = nit_emisor or nit_auto
        consec = consecutivo or consecutivo_auto

        nombre_base = self._generar_nombre_archivo_dian(tipo, nit, consec)
        zip_name, zip_b64 = self._empaquetar_zip_en_memoria(xml, nombre_base)

        user = self.config.user_api
        password = self.config.password_api
        security_hdr = self._build_ws_security_header(user, password) if (user and password) else ""

        action = "http://wcf.dian.colombia/IWcfDianCustomerServices/SendBillSync"
        envelope = (
            f'<soap:Envelope xmlns:soap="{NS_SOAP}" '
            f'xmlns:wcf="{NS_WCF}" '
            f'xmlns:wsa="{NS_WSA}" '
            f'xmlns:wsse="{NS_WSSE}">'
            f'<soap:Header>'
            f'<wsa:Action>{action}</wsa:Action>'
            f'<wsa:To>{self.config.url_transmit}</wsa:To>'
            f'<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>'
            f'{security_hdr}'
            f'</soap:Header>'
            f'<soap:Body>'
            f'<wcf:SendBillSync>'
            f'<wcf:fileName>{zip_name}</wcf:fileName>'
            f'<wcf:contentFile>{zip_b64}</wcf:contentFile>'
            f'</wcf:SendBillSync>'
            f'</soap:Body>'
            f'</soap:Envelope>'
        )

        headers = {
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "SOAPAction": action,
        }

        logger.info("Transmitiendo SendBillSync a DIAN (%s, %d bytes)", zip_name, len(envelope))
        try:
            resp = self.session.post(
                self.config.url_transmit,
                data=envelope.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ErrorDian(f"Error de red al transmitir a DIAN: {exc}") from exc

        return self._parse_soap_wcf_result(resp.text)

    def consultar(self, track_id: str) -> TransmisionResult:
        """Consulta el estado del documento por track_id mediante GetStatus de WCF."""
        user = self.config.user_api
        password = self.config.password_api
        security_hdr = self._build_ws_security_header(user, password) if (user and password) else ""

        action = "http://wcf.dian.colombia/IWcfDianCustomerServices/GetStatus"
        envelope = (
            f'<soap:Envelope xmlns:soap="{NS_SOAP}" '
            f'xmlns:wcf="{NS_WCF}" '
            f'xmlns:wsa="{NS_WSA}" '
            f'xmlns:wsse="{NS_WSSE}">'
            f'<soap:Header>'
            f'<wsa:Action>{action}</wsa:Action>'
            f'<wsa:To>{self.config.url_transmit}</wsa:To>'
            f'<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>'
            f'{security_hdr}'
            f'</soap:Header>'
            f'<soap:Body>'
            f'<wcf:GetStatus>'
            f'<wcf:trackId>{track_id}</wcf:trackId>'
            f'</wcf:GetStatus>'
            f'</soap:Body>'
            f'</soap:Envelope>'
        )

        headers = {
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "SOAPAction": action,
        }

        try:
            resp = self.session.post(
                self.config.url_transmit,
                data=envelope.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ErrorDian(f"Error de red al consultar en DIAN: {exc}") from exc

        return self._parse_soap_wcf_result(resp.text)

    def send_test_set_async(self, xml: str, test_set_id: str = "") -> TransmisionResult:
        """Envía un documento del catálogo de habilitación mediante SendTestSetAsync."""
        tid = test_set_id or self.config.test_set_id
        if not tid:
            raise ErrorDian("Falta test_set_id para invocar SendTestSetAsync")

        tipo, nit, consec = self._extraer_identificadores_xml(xml)
        nombre_base = self._generar_nombre_archivo_dian(tipo, nit, consec)
        zip_name, zip_b64 = self._empaquetar_zip_en_memoria(xml, nombre_base)

        user = self.config.user_api
        password = self.config.password_api
        security_hdr = self._build_ws_security_header(user, password) if (user and password) else ""

        action = "http://wcf.dian.colombia/IWcfDianCustomerServices/SendTestSetAsync"
        envelope = (
            f'<soap:Envelope xmlns:soap="{NS_SOAP}" '
            f'xmlns:wcf="{NS_WCF}" '
            f'xmlns:wsa="{NS_WSA}" '
            f'xmlns:wsse="{NS_WSSE}">'
            f'<soap:Header>'
            f'<wsa:Action>{action}</wsa:Action>'
            f'<wsa:To>{self.config.url_transmit}</wsa:To>'
            f'<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>'
            f'{security_hdr}'
            f'</soap:Header>'
            f'<soap:Body>'
            f'<wcf:SendTestSetAsync>'
            f'<wcf:fileName>{zip_name}</wcf:fileName>'
            f'<wcf:contentFile>{zip_b64}</wcf:contentFile>'
            f'<wcf:testSetId>{tid}</wcf:testSetId>'
            f'</wcf:SendTestSetAsync>'
            f'</soap:Body>'
            f'</soap:Envelope>'
        )

        headers = {
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "SOAPAction": action,
        }

        try:
            resp = self.session.post(
                self.config.url_transmit,
                data=envelope.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ErrorDian(f"Error de red en SendTestSetAsync: {exc}") from exc

        return self._parse_soap_wcf_result(resp.text)

    def _parse_soap_wcf_result(self, body: str) -> TransmisionResult:
        """Parsea la respuesta SOAP WCF conteniendo un objeto DianResponse."""
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ErrorDian(f"Respuesta SOAP inválida: {exc}") from exc

        # Verificar si hay SOAP Fault
        fault = root.find(".//{http://www.w3.org/2003/05/soap-envelope}Fault") or root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
        if fault is not None:
            reason = fault.find(".//{http://www.w3.org/2003/05/soap-envelope}Text") or fault.find("faultstring")
            msg = reason.text if reason is not None and reason.text else "SOAP Fault desconocido"
            return TransmisionResult(
                estado="Rechazada",
                track_id="",
                status_code="99",
                status_description=f"Fault SOAP: {msg}",
                errores=[msg],
                raw_response=body,
            )

        def buscar_texto(local_tag: str) -> str:
            for el in root.iter():
                tag_name = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                if tag_name.lower() == local_tag.lower():
                    return (el.text or "").strip()
            return ""

        status_code = buscar_texto("StatusCode") or "99"
        status_desc = buscar_texto("StatusDescription") or buscar_texto("StatusMessage") or "Sin descripción"
        is_valid = buscar_texto("IsValid").lower() == "true"
        doc_key = buscar_texto("XmlDocumentKey")
        zip_key = buscar_texto("ZipKey")
        track_id = buscar_texto("TrackId") or doc_key or zip_key or uuid.uuid4().hex

        # Extraer lista de mensajes de error
        errores: list[str] = []
        for el in root.iter():
            tag_name = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag_name.lower() in ("errormessage", "string") and (el.text or "").strip():
                errores.append(el.text.strip())

        # Extraer ApplicationResponse en base64 si viene
        xml_b64 = buscar_texto("XmlBase64Bytes")
        app_resp_xml = ""
        if xml_b64:
            try:
                app_resp_xml = base64.b64decode(xml_b64).decode("utf-8", errors="replace")
            except Exception:
                pass

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if status_code == "00" or is_valid:
            estado = "Aceptada"
        elif status_code in ("1002", "90", "66"):
            estado = "NoEncontrada"
        else:
            estado = "Rechazada"

        return TransmisionResult(
            estado=estado,
            track_id=track_id,
            status_code=status_code,
            status_description=status_desc,
            fecha_validacion=now_str,
            xml_base64_bytes=xml_b64,
            application_response_xml=app_resp_xml,
            errores=errores,
            cude=doc_key,
            raw_response=body,
        )

    # -----------------------------------------------------------------------
    # Compatibilidad Legacy (para pruebas anteriores)
    # -----------------------------------------------------------------------

    def _build_soap_envelope(self, user, password, xml_doc: str) -> str:
        """Envuelve el XML firmado en un SOAP 1.2 envelope con WS-Security (legacy)."""
        security = self._build_ws_security_header(user, password)
        return (
            f'<soap:Envelope xmlns:soap="{NS_SOAP}" '
            f'xmlns:wsa="{NS_WSA}" '
            f'xmlns:wsse="{NS_WSSE}">'
            f'<soap:Header>'
            f'<wsa:To>http://www.dian.gov.co/FacturaE/TransmitDocuments</wsa:To>'
            f'<wsa:Action>http://www.dian.gov.co/FacturaE/TransmitDocuments</wsa:Action>'
            f'<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>'
            f'{security}'
            f'</soap:Header>'
            f'<soap:Body>'
            f'<TransmitDocuments>'
            f'{xml_doc}'
            f'</TransmitDocuments>'
            f'</soap:Body>'
            f'</soap:Envelope>'
        )

    def transmitir_documentos(self, xml_firmado: str) -> dict:
        """Transmite el XML firmado a DIAN mediante SOAP 1.2 (interfaz legacy)."""
        if not self.config.user_api or not self.config.password_api:
            raise ErrorDian("Falta user_api o password_api para SOAP")
        user = self.config.user_api
        password = self.config.password_api
        url = self.config.url_transmit
        envelope = self._build_soap_envelope(user, password, xml_firmado)
        logger.info("Transmitiendo a DIAN vía SOAP legacy (%d bytes)", len(envelope))
        try:
            resp = self.session.post(
                url,
                data=envelope.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "http://www.dian.gov.co/FacturaE/TransmitDocuments",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ErrorDian(f"Error de red al transmitir a DIAN: {exc}") from exc
        if resp.status_code >= 400:
            raise ErrorDian(f"DIAN respondió HTTP {resp.status_code}: {resp.text[:300]}")
        return self._parse_response(resp.text)

    def _parse_response(self, body: str) -> dict:
        """Extrae el resultado del cuerpo SOAP legacy."""
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ErrorDian(f"Respuesta SOAP inválida: {exc}") from exc
        ns = {"soap": NS_SOAP}
        body_el = root.find("soap:Body", ns)
        if body_el is None:
            return {"raw": body}
        fault = body_el.find("soap:Fault", ns)
        if fault is not None:
            reason = fault.find("soap:Reason/soap:Text", ns)
            text_err = reason.text if reason is not None and reason.text else body[:300]
            raise ErrorDian(f"Fault SOAP: {text_err}")
        result = {}
        for child in body_el:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if len(child) == 0:
                result[tag] = child.text or ""
            else:
                result[tag] = {
                    (c.tag.split("}")[-1] if "}" in c.tag else c.tag): (c.text or "")
                    for c in child
                }
        return result
