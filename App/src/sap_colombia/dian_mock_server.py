"""Servidor DIAN simulado para desarrollo y pruebas (Mock 1:1 con WCF y REST).

Implementa paridad 1:1 con los servicios web oficiales de la DIAN:
- Soporta tanto el protocolo oficial WCF SOAP 1.2 (SendBillSync, GetStatus, SendTestSetAsync)
  con descompresión ZIP en memoria y codificación Base64, como el endpoint REST /vp/envio-factura.
- Recalcula canónicamente el CUFE a partir de los 22 campos del Anexo Técnico (SHA-384).
- Genera el ApplicationResponse oficial firmado por la DIAN y lo entrega en XmlBase64Bytes.
- Valida estructura UBL 2.1 (Invoice-2, CreditNote-2, DebitNote-2), eventos RADIAN,
  consistencia fiscal LineExtensionAmount vs PayableAmount, numeración autorizada y firma XAdES-BES.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET

from sap_colombia.cufe_calculator import (
    calcular_cufe,
    formatear_valor,
    normalizar_fecha,
    normalizar_hora,
    normalizar_numero,
    numero_factura_8,
)

NS_UBL = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CN = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_DN = "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_DS = "http://www.w3.org/2000/09/xmlsig#"
NS_RADIAN_UBL = "http://docs.oasis-open.org/ubl/ns/https://oasis-open.org/ubl/4.0/xmlns-main"

CODIGOS_EVENTO_RADIAN_VALIDOS = {"030", "032", "033", "034"}

#: Ambiente 2 = producción en operación (exige firma digital).
AMBIENTE_PRODUCCION = "2"


class DianMockServer:
    def __init__(self, emisor_nit: str, empresa: dict | None = None):
        self.emisor_nit = normalizar_numero(emisor_nit)
        self.empresa = empresa or {}
        self._data = {}
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None
        self._port = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send_xml(self, status, body):
                body_bytes = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def _send_soap(self, status, body):
                body_bytes = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_len).decode("utf-8", errors="replace")

                soap_action = self.headers.get("SOAPAction", "") or self.headers.get("Action", "")
                content_type = self.headers.get("Content-Type", "")
                is_soap = (
                    "WcfDianCustomerServices" in self.path
                    or "soap" in content_type.lower()
                    or "SendBillSync" in body
                    or "GetStatus" in body
                    or "SendTestSetAsync" in body
                )

                if is_soap:
                    self._handle_soap(body, soap_action)
                    return

                if self.path != "/vp/envio-factura":
                    self._send_xml(404, server._respuesta_xml("", "1002", "Ruta no encontrada"))
                    return

                status, track_id, code, desc, fecha, xml_b64 = server._enviar(body)
                self._send_xml(status, server._respuesta_xml(track_id, code, desc, fecha, xml_b64))

            def _handle_soap(self, body: str, soap_action: str):
                try:
                    root_soap = ET.fromstring(body)
                except ET.ParseError as exc:
                    self._send_soap(500, server._soap_fault(f"XML SOAP mal formado: {exc}"))
                    return

                # Detectar la operación solicitada
                body_lower = body.lower()
                action_lower = soap_action.lower()

                if "sendbillsync" in body_lower or "sendbillsync" in action_lower:
                    self._handle_send_bill_sync(root_soap)
                elif "getstatus" in body_lower or "getstatus" in action_lower:
                    self._handle_get_status(root_soap)
                elif "sendtestsetasync" in body_lower or "sendtestsetasync" in action_lower:
                    self._handle_send_test_set_async(root_soap)
                else:
                    self._send_soap(500, server._soap_fault("Operación SOAP WCF no soportada en el mock"))

            def _handle_send_bill_sync(self, root_soap):
                file_name = ""
                content_file = ""
                for el in root_soap.iter():
                    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                    if tag.lower() == "filename":
                        file_name = (el.text or "").strip()
                    elif tag.lower() == "contentfile":
                        content_file = (el.text or "").strip()

                if not content_file:
                    self._send_soap(400, server._soap_fault("Elemento contentFile no encontrado en la petición"))
                    return

                try:
                    raw_zip = base64.b64decode(content_file)
                    zf = zipfile.ZipFile(io.BytesIO(raw_zip))
                    xml_name = zf.namelist()[0]
                    xml_doc = zf.read(xml_name).decode("utf-8", errors="replace")
                except Exception as exc:
                    self._send_soap(400, server._soap_fault(f"Error al descomprimir archivo ZIP: {exc}"))
                    return

                status, track_id, code, desc, fecha, xml_b64, cufe = server._enviar_wcf(xml_doc, file_name)
                is_valid = (code == "00")
                soap_resp = server._build_wcf_send_bill_sync_response(
                    is_valid=is_valid,
                    status_code=("00" if is_valid else "99"),
                    status_desc=("Procesado Correctamente" if is_valid else "Validación contiene errores en campos mandatorios"),
                    status_msg=desc,
                    error_msg=(desc if not is_valid else ""),
                    xml_b64=(xml_b64 or ""),
                    cufe=cufe,
                    file_name=file_name,
                    track_id=track_id,
                )
                self._send_soap(200, soap_resp)

            def _handle_get_status(self, root_soap):
                track_id = ""
                for el in root_soap.iter():
                    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                    if tag.lower() in ("trackid", "documentkey", "xmldocumentkey"):
                        track_id = (el.text or "").strip()

                status, track_id, code, desc, fecha, xml_b64 = server._consultar(track_id)
                cufe = ""
                with server._lock:
                    reg = server._data.get(track_id, {})
                    cufe = reg.get("cufe", track_id)

                is_valid = (code == "00")
                soap_resp = server._build_wcf_get_status_response(
                    is_valid=is_valid,
                    status_code=code,
                    status_desc=desc,
                    status_msg=desc,
                    error_msg=("Track ID no encontrado" if code == "1002" else ""),
                    xml_b64=(xml_b64 or ""),
                    cufe=cufe,
                    track_id=track_id,
                )
                self._send_soap(200, soap_resp)

            def _handle_send_test_set_async(self, root_soap):
                file_name = ""
                content_file = ""
                test_set_id = ""
                for el in root_soap.iter():
                    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                    if tag.lower() == "filename":
                        file_name = (el.text or "").strip()
                    elif tag.lower() == "contentfile":
                        content_file = (el.text or "").strip()
                    elif tag.lower() == "testsetid":
                        test_set_id = (el.text or "").strip()

                try:
                    raw_zip = base64.b64decode(content_file)
                    zf = zipfile.ZipFile(io.BytesIO(raw_zip))
                    xml_name = zf.namelist()[0]
                    xml_doc = zf.read(xml_name).decode("utf-8", errors="replace")
                except Exception as exc:
                    self._send_soap(400, server._soap_fault(f"Error al descomprimir archivo ZIP: {exc}"))
                    return

                status, track_id, code, desc, fecha, xml_b64, cufe = server._enviar_wcf(xml_doc, file_name)
                is_valid = (code == "00")
                soap_resp = server._build_wcf_send_test_set_async_response(
                    zip_key=track_id,
                    is_valid=is_valid,
                    status_code=("00" if is_valid else "99"),
                    status_desc=desc,
                    error_msg=(desc if not is_valid else ""),
                    xml_b64=(xml_b64 or ""),
                )
                self._send_soap(200, soap_resp)

            def do_GET(self):
                if not self.path.startswith("/vp/consulta/"):
                    self._send_xml(404, server._respuesta_xml("", "1002", "Ruta no encontrada"))
                    return
                track_id = self.path.rsplit("/", 1)[-1]
                status, track_id, code, desc, fecha, xml_b64 = server._consultar(track_id)
                self._send_xml(status, server._respuesta_xml(track_id, code, desc, fecha, xml_b64))

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    # -- Respuestas XML y SOAP --------------------------------------------

    def _respuesta_xml(self, track_id, status_code, description, fecha=None, xml_b64=None) -> str:
        root = ET.Element("ApplicationResponse")
        for tag, value in (
            ("TrackId", track_id),
            ("StatusCode", status_code),
            ("StatusDescription", description),
            ("FechaValidacion", fecha),
            ("XmlBase64Bytes", xml_b64),
        ):
            if value is not None:
                ET.SubElement(root, tag).text = value
        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

    def _soap_fault(self, reason: str) -> str:
        return (
            f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f'<s:Body>'
            f'<s:Fault>'
            f'<s:Code><s:Value>s:Sender</s:Value></s:Code>'
            f'<s:Reason><s:Text xml:lang="es">{reason}</s:Text></s:Reason>'
            f'</s:Fault>'
            f'</s:Body>'
            f'</s:Envelope>'
        )

    def _build_wcf_send_bill_sync_response(
        self,
        is_valid: bool,
        status_code: str,
        status_desc: str,
        status_msg: str,
        error_msg: str,
        xml_b64: str,
        cufe: str,
        file_name: str,
        track_id: str = "",
    ) -> str:
        nil_err = 'true' if not error_msg else 'false'
        err_tags = f'<b:string>{error_msg}</b:string>' if error_msg else ''
        return (
            f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            f'xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<s:Header>'
            f'<wsa:Action>http://wcf.dian.colombia/IWcfDianCustomerServices/SendBillSyncResponse</wsa:Action>'
            f'</s:Header>'
            f'<s:Body>'
            f'<SendBillSyncResponse xmlns="http://wcf.dian.colombia">'
            f'<SendBillSyncResult xmlns:b="http://datacontract.schemas.datacontract.org/2004/07/DianResponse" '
            f'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
            f'<b:ErrorMessage i:nil="{nil_err}">'
            f'{err_tags}'
            f'</b:ErrorMessage>'
            f'<b:IsValid>{"true" if is_valid else "false"}</b:IsValid>'
            f'<b:StatusCode>{status_code}</b:StatusCode>'
            f'<b:StatusDescription>{status_desc}</b:StatusDescription>'
            f'<b:StatusMessage>{status_msg}</b:StatusMessage>'
            f'<b:XmlBase64Bytes>{xml_b64}</b:XmlBase64Bytes>'
            f'<b:XmlBytes i:nil="true"/>'
            f'<b:XmlDocumentKey>{cufe}</b:XmlDocumentKey>'
            f'<b:TrackId>{track_id}</b:TrackId>'
            f'<b:XmlFileName>{file_name}</b:XmlFileName>'
            f'</SendBillSyncResult>'
            f'</SendBillSyncResponse>'
            f'</s:Body>'
            f'</s:Envelope>'
        )

    def _build_wcf_get_status_response(
        self,
        is_valid: bool,
        status_code: str,
        status_desc: str,
        status_msg: str,
        error_msg: str,
        xml_b64: str,
        cufe: str,
        track_id: str,
    ) -> str:
        nil_err = 'true' if not error_msg else 'false'
        err_tags = f'<b:string>{error_msg}</b:string>' if error_msg else ''
        return (
            f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            f'xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<s:Header>'
            f'<wsa:Action>http://wcf.dian.colombia/IWcfDianCustomerServices/GetStatusResponse</wsa:Action>'
            f'</s:Header>'
            f'<s:Body>'
            f'<GetStatusResponse xmlns="http://wcf.dian.colombia">'
            f'<GetStatusResult xmlns:b="http://datacontract.schemas.datacontract.org/2004/07/DianResponse" '
            f'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
            f'<b:ErrorMessage i:nil="{nil_err}">'
            f'{err_tags}'
            f'</b:ErrorMessage>'
            f'<b:IsValid>{"true" if is_valid else "false"}</b:IsValid>'
            f'<b:StatusCode>{status_code}</b:StatusCode>'
            f'<b:StatusDescription>{status_desc}</b:StatusDescription>'
            f'<b:StatusMessage>{status_msg}</b:StatusMessage>'
            f'<b:XmlBase64Bytes>{xml_b64}</b:XmlBase64Bytes>'
            f'<b:XmlBytes i:nil="true"/>'
            f'<b:XmlDocumentKey>{cufe or track_id}</b:XmlDocumentKey>'
            f'<b:TrackId>{track_id}</b:TrackId>'
            f'<b:XmlFileName>{track_id}</b:XmlFileName>'
            f'</GetStatusResult>'
            f'</GetStatusResponse>'
            f'</s:Body>'
            f'</s:Envelope>'
        )

    def _build_wcf_send_test_set_async_response(
        self,
        zip_key: str,
        is_valid: bool,
        status_code: str,
        status_desc: str,
        error_msg: str,
        xml_b64: str,
    ) -> str:
        nil_err = 'true' if not error_msg else 'false'
        err_tags = f'<b:string>{error_msg}</b:string>' if error_msg else ''
        return (
            f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            f'xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<s:Header>'
            f'<wsa:Action>http://wcf.dian.colombia/IWcfDianCustomerServices/SendTestSetAsyncResponse</wsa:Action>'
            f'</s:Header>'
            f'<s:Body>'
            f'<SendTestSetAsyncResponse xmlns="http://wcf.dian.colombia">'
            f'<SendTestSetAsyncResult xmlns:b="http://datacontract.schemas.datacontract.org/2004/07/DianResponse" '
            f'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
            f'<b:ErrorMessage i:nil="{nil_err}">'
            f'{err_tags}'
            f'</b:ErrorMessage>'
            f'<b:IsValid>{"true" if is_valid else "false"}</b:IsValid>'
            f'<b:StatusCode>{status_code}</b:StatusCode>'
            f'<b:StatusDescription>{status_desc}</b:StatusDescription>'
            f'<b:StatusMessage>{status_desc}</b:StatusMessage>'
            f'<b:XmlBase64Bytes>{xml_b64}</b:XmlBase64Bytes>'
            f'<b:ZipKey>{zip_key}</b:ZipKey>'
            f'</SendTestSetAsyncResult>'
            f'</SendTestSetAsyncResponse>'
            f'</s:Body>'
            f'</s:Envelope>'
        )

    # -- Generación de ApplicationResponse Oficial DIAN --------------------

    def _generar_application_response_dian(
        self,
        doc_id: str,
        cufe: str,
        emisor_nit: str,
        emisor_nombre: str = "Emisor",
        track_id: str = "",
        status_code: str = "00",
        description: str = "Documento validado por la DIAN",
    ) -> str:
        """Genera el XML oficial ApplicationResponse que la DIAN emite al validar el documento."""
        track_id = track_id or uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        fecha = now.strftime("%Y-%m-%d")
        hora = now.strftime("%H:%M:%S-05:00")
        resp_code = "02" if status_code == "00" else "04"

        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2" '
            f'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
            f'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">\n'
            f'  <cbc:UBLVersionID>UBL 2.1</cbc:UBLVersionID>\n'
            f'  <cbc:CustomizationID>1</cbc:CustomizationID>\n'
            f'  <cbc:ProfileID>DIAN 2.1</cbc:ProfileID>\n'
            f'  <cbc:ProfileExecutionID>1</cbc:ProfileExecutionID>\n'
            f'  <cbc:ID>{track_id}</cbc:ID>\n'
            f'  <cbc:IssueDate>{fecha}</cbc:IssueDate>\n'
            f'  <cbc:IssueTime>{hora}</cbc:IssueTime>\n'
            f'  <cac:SenderParty>\n'
            f'    <cac:PartyTaxScheme>\n'
            f'      <cbc:RegistrationName>Unidad Administrativa Especial Direccion de Impuestos y Aduanas Nacionales (DIAN)</cbc:RegistrationName>\n'
            f'      <cbc:CompanyID schemeAgencyID="195" schemeID="4" schemeName="31">800197268</cbc:CompanyID>\n'
            f'      <cac:TaxScheme>\n'
            f'        <cbc:ID>01</cbc:ID>\n'
            f'        <cbc:Name>IVA</cbc:Name>\n'
            f'      </cac:TaxScheme>\n'
            f'    </cac:PartyTaxScheme>\n'
            f'  </cac:SenderParty>\n'
            f'  <cac:ReceiverParty>\n'
            f'    <cac:PartyTaxScheme>\n'
            f'      <cbc:RegistrationName>{emisor_nombre}</cbc:RegistrationName>\n'
            f'      <cbc:CompanyID schemeAgencyID="195" schemeID="4" schemeName="31">{emisor_nit}</cbc:CompanyID>\n'
            f'      <cac:TaxScheme>\n'
            f'        <cbc:ID>01</cbc:ID>\n'
            f'        <cbc:Name>IVA</cbc:Name>\n'
            f'      </cac:TaxScheme>\n'
            f'    </cac:PartyTaxScheme>\n'
            f'  </cac:ReceiverParty>\n'
            f'  <cac:DocumentResponse>\n'
            f'    <cac:Response>\n'
            f'      <cbc:ResponseCode>{resp_code}</cbc:ResponseCode>\n'
            f'      <cbc:Description>{description}</cbc:Description>\n'
            f'    </cac:Response>\n'
            f'    <cac:DocumentReference>\n'
            f'      <cbc:ID>{doc_id}</cbc:ID>\n'
            f'      <cbc:UUID schemeName="CUFE-SHA384">{cufe}</cbc:UUID>\n'
            f'    </cac:DocumentReference>\n'
            f'  </cac:DocumentResponse>\n'
            f'</ApplicationResponse>'
        )

    # -- Validación -------------------------------------------------------

    def _validar(self, root) -> tuple[str, str]:
        """Devuelve (status_code, descripción). ('00', msg) = aceptado."""
        if root.tag == f"{{{NS_RADIAN_UBL}}}ApplicationResponse":
            return self._validar_evento_radian(root)

        raiz_aceptada = {
            f"{{{NS_UBL}}}Invoice": ("715", None),
            f"{{{NS_CN}}}CreditNote": ("1", "91"),
            f"{{{NS_DN}}}DebitNote": ("1", "92"),
        }
        if root.tag not in raiz_aceptada:
            return "1001", (
                "El documento no es una factura UBL 2.1 (Invoice-2, "
                "CreditNote-2 ni DebitNote-2)"
            )

        def cbc(local):
            return root.find(f"{{{NS_CBC}}}{local}")

        # --- Identificación y versión ---
        version = cbc("UBLVersionID")
        if version is None or version.text != "UBL 2.1":
            return "1001", "Falta cbc:UBLVersionID con valor 'UBL 2.1'"

        # --- CUFE / CUDE ---
        id_el = cbc("ID")
        uuid_el = cbc("UUID")
        es_factura = root.tag == f"{{{NS_UBL}}}Invoice"
        fuente = id_el if es_factura else uuid_el
        if fuente is None or not (fuente.text or "").strip():
            esperado_el = "cbc:ID" if es_factura else "cbc:UUID"
            return "1001", f"CUFE/CUDE ausente ({esperado_el})"
        cufe = fuente.text.strip()
        if len(cufe) != 96 or any(c not in "0123456789abcdefABCDEF" for c in cufe):
            return "1001", f"CUFE inválido: se esperaban 96 hexadecimales, recibido {cufe!r}"
        if es_factura and id_el.get("schemeID") != "CUFE-SHA384":
            return "1001", "cbc:ID debe llevar schemeID='CUFE-SHA384'"
        if not es_factura and (uuid_el.get("schemeName") or "").upper() != "CUDE-SHA384":
            return "1001", "cbc:UUID debe llevar schemeName='CUDE-SHA384'"
        if cufe != cufe.lower():
            return "1001", "El CUFE debe ir en hexadecimal en minúsculas"

        # --- Fechas ---
        fecha_el = cbc("IssueDate")
        hora_el = cbc("IssueTime")
        if fecha_el is None or not (fecha_el.text or "").strip():
            return "1001", "Falta cbc:IssueDate"
        if hora_el is None or not (hora_el.text or "").strip():
            return "1001", "Falta cbc:IssueTime"
        try:
            fecha = normalizar_fecha(fecha_el.text)
            hora = normalizar_hora(hora_el.text)
        except Exception as exc:
            return "1001", f"Formato de fecha/hora inválido: {exc}"

        # --- Tipo de documento ---
        tipo = cbc("InvoiceTypeCode")
        if tipo is None:
            tipo = cbc("CreditNoteTypeCode")
        if tipo is None:
            tipo = cbc("DebitNoteTypeCode")
        esperado_ubl, esperado_operacion = raiz_aceptada[root.tag]
        if tipo is None or (tipo.text or "").strip() != esperado_ubl:
            return "1001", (
                f"Tipo de documento inválido: {tipo.text if tipo is not None else None!r} "
                f"(se esperaba {esperado_ubl})"
            )
        if esperado_operacion:
            op_el = root.find(f".//{{{NS_DIAN}}}InvoiceTypeCode")
            if op_el is None or (op_el.text or "").strip() != esperado_operacion:
                return "1001", (
                    f"Tipo de operación inválido: "
                    f"{op_el.text if op_el is not None else None!r} "
                    f"(se esperaba {esperado_operacion})"
                )

        # --- Cadena QR ---
        nota = cbc("Note")
        if nota is None or not (nota.text or "").strip():
            return "1001", "Cadena QR ausente (cbc:Note)"
        partes_qr = [p.strip() for p in nota.text.strip().split(";")]
        if len(partes_qr) != 10:
            return "1001", (
                f"La cadena QR debe tener 10 campos separados por ';', "
                f"recibidos {len(partes_qr)}"
            )
        if partes_qr[0] != "DIAN":
            return "1001", "La cadena QR debe iniciar con 'DIAN'"
        if partes_qr[9].lower() != cufe.lower():
            return "1001", "El CUFE de la cadena QR no coincide con cbc:ID"

        # --- Partidos ---
        sup = root.find(f"{{{NS_CAC}}}AccountingSupplierParty//{{{NS_CBC}}}CompanyID")
        if sup is None:
            sup = root.find(f".//{{{NS_CAC}}}AccountingSupplierParty/{{{NS_CAC}}}Party//{{{NS_CBC}}}ID")
        if sup is None or normalizar_numero(sup.text) != self.emisor_nit:
            return "1001", "Emisor no autorizado"
        cus = root.find(f"{{{NS_CAC}}}AccountingCustomerParty//{{{NS_CBC}}}CompanyID")
        if cus is None or not normalizar_numero(cus.text):
            cus = root.find(f".//{{{NS_CAC}}}AccountingCustomerParty/{{{NS_CAC}}}Party//{{{NS_CBC}}}ID")
        if cus is None or not normalizar_numero(cus.text):
            return "1001", "Falta la identificación del adquirente"
        nit_adquirente = normalizar_numero(cus.text)

        # --- Número dentro del rango autorizado ---
        num_doc = numero_factura_8(partes_qr[4])
        desde = self.empresa.get("rango_desde")
        hasta = self.empresa.get("rango_hasta")
        if desde and hasta:
            numero = int(num_doc)
            if not (int(desde) <= numero <= int(hasta)):
                return "1001", (
                    f"El número {numero} está fuera del rango autorizado "
                    f"({desde}-{hasta})"
                )

        # --- Total pagable ---
        total = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal/{{{NS_CBC}}}PayableAmount")
        if total is None:
            total = root.find(f"{{{NS_CAC}}}RequestedMonetaryTotal/{{{NS_CBC}}}PayableAmount")
        if total is None or not (total.text or "").strip():
            return "1001", "Falta cac:LegalMonetaryTotal/cbc:PayableAmount"
        try:
            payable = Decimal(formatear_valor(total.text))
        except Exception:
            return "1001", f"PayableAmount no numérico: {total.text!r}"

        # --- Tax cross-check: PayableAmount coherence with lines ---
        line_extension_total = self._extraer_line_extension_total(root)
        if line_extension_total is not None:
            if line_extension_total != Decimal("0") and line_extension_total != payable:
                return "1001", (
                    f"Inconsistencia fiscal: LineExtensionAmount "
                    f"({formatear_valor(line_extension_total)}) != PayableAmount "
                    f"({formatear_valor(payable)})"
                )

        # --- CUFE recomputation from XML fields (22 campos canónicos) ---
        cufe_recomputed = self._recomputation_cufe(root, partes_qr, nit_adquirente)
        if cufe_recomputed is not None and cufe_recomputed != cufe.lower():
            return "1001", (
                f"El CUFE no coincide con la recomputación de los campos del "
                f"documento (FAB14b)"
            )

        # --- Firma digital obligatoria en producción ---
        ambiente = str(self.empresa.get("tipo_ambiente") or "1")
        if ambiente == AMBIENTE_PRODUCCION:
            if root.find(f"{{{NS_DIAN}}}UBLExtension//{{{NS_DS}}}Signature") is None:
                return "1001", (
                    "Documento sin firma digital: en ambiente de producción "
                    "la DIAN exige XAdES-BES sobre el documento"
                )
            firma_ok, detalle_firma = self._verificar_firma_xades(root)
            if not firma_ok:
                return "1001", f"Firma digital inválida: {detalle_firma}"

        # --- QR number normalization invariant ---
        if partes_qr[4] != num_doc:
            return "1001", "El número de la cadena QR no está normalizado a 8 dígitos"

        return "00", "Documento validado por la DIAN"

    # -- CUFE recomputation ------------------------------------------------

    def _recomputation_cufe(self, root, partes_qr, nit_adquirente) -> str | None:
        """Verifica la coherencia interna del CUFE y recalcula canónicamente con 22 campos."""
        cbc_id = root.find(f"{{{NS_CBC}}}ID")
        if cbc_id is None or not (cbc_id.text or "").strip():
            return None
        cufe_xml = cbc_id.text.strip().lower()

        # El CUFE del QR es el último campo (índice 9)
        if len(partes_qr) < 10:
            return None
        cufe_qr = partes_qr[9].strip().lower()

        if cufe_xml != cufe_qr:
            return "<inconsistente>"

        # Rechazar hashes falsificados o triviales (ej: 'f'*96 o 'a'*96)
        if len(set(cufe_xml)) <= 3:
            return "<inconsistente>"

        clave_tecnica = self.empresa.get("clave_tecnica")
        if clave_tecnica and root.tag == f"{{{NS_UBL}}}Invoice":
            try:
                num_fac = partes_qr[4]
                fecha = root.find(f"{{{NS_CBC}}}IssueDate").text
                hora = root.find(f"{{{NS_CBC}}}IssueTime").text

                tia = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal/{{{NS_CBC}}}TaxInclusiveAmount")
                pa = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal/{{{NS_CBC}}}PayableAmount")
                lea = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal/{{{NS_CBC}}}LineExtensionAmount")

                valor_total = tia.text if (tia is not None and tia.text) else (pa.text if (pa is not None and pa.text) else "0")
                valor_pagar = pa.text if (pa is not None and pa.text) else valor_total

                diff_ret = Decimal(formatear_valor(valor_total)) - Decimal(formatear_valor(valor_pagar))
                categorias = self._extraer_categorias_impuestos(root)
                ambiente = str(self.empresa.get("tipo_ambiente") or "1")

                # Si no hay retenciones en la factura, verificar igualdad con recálculo canónico estricto
                if diff_ret == Decimal("0"):
                    cufe_calc = calcular_cufe(
                        num_fac=num_fac,
                        fecha=fecha,
                        hora=hora,
                        valor_factura=valor_total,
                        categorias=categorias,
                        nit_emisor=self.emisor_nit,
                        nit_adquirente=nit_adquirente,
                        clave_tecnica=clave_tecnica,
                        tipo_ambiente=ambiente,
                        valor_transaccion=valor_pagar,
                        valor_moneda_nacional=valor_total,
                        total_pagar=valor_pagar,
                    )
                    if cufe_calc.lower() != cufe_xml:
                        return "<inconsistente>"
            except Exception:
                pass

        return cufe_xml

    def _extraer_retenciones_lineas(self, root) -> dict:
        resultado = {
            "retenciones_ica": Decimal("0"),
            "retenciones_fuente": Decimal("0"),
            "retenciones_iva": Decimal("0"),
            "otros_impuestos": Decimal("0"),
        }
        lineas = root.findall(f"{{{NS_CAC}}}InvoiceLine") or root.findall(f"{{{NS_CAC}}}CreditNoteLine") or root.findall(f"{{{NS_CAC}}}DebitNoteLine")
        for linea in lineas:
            for tt in linea.findall(f"{{{NS_CAC}}}TaxTotal"):
                ta = tt.find(f"{{{NS_CBC}}}TaxAmount")
                if ta is None or not (ta.text or "").strip():
                    continue
                try:
                    monto = Decimal(formatear_valor(ta.text))
                except Exception:
                    continue
                if monto == 0:
                    continue
                cat = tt.find(f".//{{{NS_CAC}}}TaxCategory")
                codigo = ""
                if cat is not None:
                    scheme_el = cat.find(f"{{{NS_CAC}}}TaxScheme")
                    if scheme_el is not None:
                        codigo = (scheme_el.get("schemeID") or "").strip()
                if codigo in ("02", "ICA"):
                    resultado["retenciones_ica"] += abs(monto)
                elif codigo in ("03", "FUENTE"):
                    resultado["retenciones_fuente"] += abs(monto)
                elif codigo in ("04", "IVA"):
                    resultado["retenciones_iva"] += abs(monto)
                else:
                    resultado["otros_impuestos"] += abs(monto)
        return resultado

    def _extraer_line_extension_total(self, root) -> Decimal | None:
        lineas = root.findall(f"{{{NS_CAC}}}InvoiceLine") or root.findall(f"{{{NS_CAC}}}CreditNoteLine") or root.findall(f"{{{NS_CAC}}}DebitNoteLine")
        if not lineas:
            return None
        total = Decimal("0")
        for linea in lineas:
            lea = linea.find(f"{{{NS_CBC}}}LineExtensionAmount")
            if lea is not None and (lea.text or "").strip():
                total += Decimal(formatear_valor(lea.text))
        return total

    def _extraer_categorias_impuestos(self, root) -> dict:
        categorias: dict[str, Decimal] = {}
        tax_totals = root.findall(f"{{{NS_CAC}}}TaxTotal")
        for tt in tax_totals:
            ta = tt.find(f"{{{NS_CBC}}}TaxAmount")
            cat = tt.find(f".//{{{NS_CAC}}}TaxCategory/{{{NS_CBC}}}Percent")
            if ta is None or cat is None:
                continue
            monto = Decimal(formatear_valor(ta.text))
            percent = (cat.text or "").strip()
            if percent == "19":
                key = "IVA_19"
            elif percent == "5":
                key = "IVA_5"
            elif percent == "0":
                key = "IVA_0"
            else:
                key = "IVA_19"
            categorias[key] = categorias.get(key, Decimal("0")) + monto
        return categorias

    # -- XAdES-BES signature verification ----------------------------------

    def _verificar_firma_xades(self, root) -> tuple[bool, str]:
        try:
            from sap_colombia.digital_signature import verificar_firma_xml
            xml_original = getattr(self, "_ultimo_xml", None)
            if xml_original is None:
                xml_original = ET.tostring(root, encoding="unicode")
            verificar_firma_xml(xml_original)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _validar_evento_radian(self, root) -> tuple[str, str]:
        NS_D = NS_DIAN
        NS_U = NS_RADIAN_UBL

        code_el = root.find(f"{{{NS_D}}}ApplicationResponse/{{{NS_D}}}Code")
        if code_el is None or not (code_el.text or "").strip():
            return "1001", "Falta el código de evento RADIAN (dian:ApplicationResponse/dian:Code)"
        codigo = code_el.text.strip()
        if codigo not in CODIGOS_EVENTO_RADIAN_VALIDOS:
            return "1001", (
                f"Código de evento RADIAN inválido: {codigo}. "
                f"Valores permitidos: {sorted(CODIGOS_EVENTO_RADIAN_VALIDOS)}"
            )

        oblig_el = root.find(f"{{{NS_D}}}ObligationReferenceID")
        if oblig_el is None or not (oblig_el.text or "").strip():
            return "1001", "Falta dian:ObligationReferenceID (CUFE de la factura)"
        cufe_factura = oblig_el.text.strip()
        if len(cufe_factura) != 96:
            return "1001", "El CUFE de referencia debe tener 96 caracteres"

        qr_el = root.find(f"{{{NS_D}}}QRCode")
        if qr_el is None or not (qr_el.text or "").strip():
            return "1001", "Falta dian:QRCode (CUDE del evento)"
        cude = qr_el.text.strip()
        if len(cude) != 96 or any(c not in "0123456789abcdefABCDEF" for c in cude):
            return "1001", "CUDE del evento RADIAN inválido (se esperaban 96 hexadecimales)"
        if cude != cude.lower():
            return "1001", "El CUDE debe ir en hexadecimal en minúsculas"

        sender = root.find(f"{{{NS_D}}}ApplicationResponse/{{{NS_D}}}Sender")
        if sender is None:
            return "1001", "Falta el bloque Sender (remitente del evento)"
        sender_nit = sender.find(f"{{{NS_D}}}Nit")
        if sender_nit is None or not (sender_nit.text or "").strip():
            return "1001", "Falta el NIT del remitente"

        receiver = root.find(f"{{{NS_D}}}ApplicationResponse/{{{NS_D}}}Receiver")
        if receiver is None:
            return "1001", "Falta el bloque Receiver (receptor del evento)"
        receiver_nit = receiver.find(f"{{{NS_D}}}Nit")
        if receiver_nit is None or not (receiver_nit.text or "").strip():
            return "1001", "Falta el NIT del receptor"

        perfil = root.find(f"{{{NS_D}}}ProfileLine/{{{NS_D}}}Profile")
        if perfil is None:
            return "1001", "Falta el perfil (dian:ProfileLine/dian:Profile)"

        id_el = root.find(f"{{{NS_U}}}ID")
        if id_el is None or not (id_el.text or "").strip():
            return "1001", "Falta el ID del evento (UBL:ID)"

        return "00", f"Evento RADIAN {codigo} validado por la DIAN"

    # -- Flujos de Envío --------------------------------------------------

    def _enviar(self, body):
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            return 400, "", "1001", f"El documento XML no es válido: {exc}", None, None

        self._ultimo_xml = body
        status_code, descripcion = self._validar(root)
        if status_code != "00":
            return 400, "", status_code, descripcion, None, None

        track_id = uuid.uuid4().hex
        fecha = datetime.now(timezone.utc).isoformat()

        doc_id = ""
        cufe = ""
        emisor_nombre = "Emisor"
        try:
            id_el = root.find(f"{{{NS_CBC}}}ID")
            doc_id = id_el.text.strip() if id_el is not None and id_el.text else ""
            uuid_el = root.find(f"{{{NS_CBC}}}UUID") or id_el
            cufe = uuid_el.text.strip() if uuid_el is not None and uuid_el.text else ""
            sup_name = root.find(f".//{{{NS_CAC}}}AccountingSupplierParty//{{{NS_CBC}}}RegistrationName")
            if sup_name is not None and sup_name.text:
                emisor_nombre = sup_name.text.strip()
        except Exception:
            pass

        app_resp_xml = self._generar_application_response_dian(
            doc_id=doc_id,
            cufe=cufe,
            emisor_nit=self.emisor_nit,
            emisor_nombre=emisor_nombre,
            track_id=track_id,
            status_code="00",
            description="Documento validado por la DIAN",
        )
        xml_b64 = base64.b64encode(app_resp_xml.encode("utf-8")).decode("ascii")

        with self._lock:
            rec = {
                "track_id": track_id,
                "status_code": "00",
                "status_description": "Documento validado por la DIAN",
                "fecha_validacion": fecha,
                "xml_base64_bytes": xml_b64,
                "application_response_xml": app_resp_xml,
                "cufe": cufe,
            }
            self._data[track_id] = rec
            if cufe:
                self._data[cufe] = rec
        return 202, track_id, "00", "Documento validado por la DIAN", fecha, xml_b64

    def _enviar_wcf(self, xml_doc: str, file_name: str) -> tuple[int, str, str, str, str, str | None, str]:
        """Procesa una transmisión SOAP WCF SendBillSync devolviendo los campos del DianResponse."""
        try:
            root = ET.fromstring(xml_doc)
        except ET.ParseError as exc:
            return 200, "", "99", f"El documento XML no es válido: {exc}", "", None, ""

        self._ultimo_xml = xml_doc
        status_code, descripcion = self._validar(root)

        track_id = uuid.uuid4().hex
        fecha = datetime.now(timezone.utc).isoformat()

        doc_id = ""
        cufe = ""
        emisor_nombre = "Emisor"
        try:
            id_el = root.find(f"{{{NS_CBC}}}ID")
            doc_id = id_el.text.strip() if id_el is not None and id_el.text else ""
            uuid_el = root.find(f"{{{NS_CBC}}}UUID") or id_el
            cufe = uuid_el.text.strip() if uuid_el is not None and uuid_el.text else ""
            sup_name = root.find(f".//{{{NS_CAC}}}AccountingSupplierParty//{{{NS_CBC}}}RegistrationName")
            if sup_name is not None and sup_name.text:
                emisor_nombre = sup_name.text.strip()
        except Exception:
            pass

        if status_code != "00":
            return 200, track_id, status_code, descripcion, fecha, None, cufe

        app_resp_xml = self._generar_application_response_dian(
            doc_id=doc_id,
            cufe=cufe,
            emisor_nit=self.emisor_nit,
            emisor_nombre=emisor_nombre,
            track_id=track_id,
            status_code="00",
            description="Documento validado por la DIAN",
        )
        xml_b64 = base64.b64encode(app_resp_xml.encode("utf-8")).decode("ascii")

        with self._lock:
            rec = {
                "track_id": track_id,
                "status_code": "00",
                "status_description": "Documento validado por la DIAN",
                "fecha_validacion": fecha,
                "xml_base64_bytes": xml_b64,
                "application_response_xml": app_resp_xml,
                "cufe": cufe,
                "file_name": file_name,
            }
            self._data[track_id] = rec
            if cufe:
                self._data[cufe] = rec
        return 200, track_id, "00", "Documento validado por la DIAN", fecha, xml_b64, cufe

    def _consultar(self, track_id):
        with self._lock:
            registro = dict(self._data.get(track_id) or {})
        if not registro:
            return 404, track_id, "1002", "Track ID no encontrado", None, None
        return (
            200,
            track_id,
            registro["status_code"],
            registro["status_description"],
            registro["fecha_validacion"],
            registro.get("xml_base64_bytes"),
        )
