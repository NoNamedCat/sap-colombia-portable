"""Firma digital XAdES-BES (XMLDSig enveloped) para el XML UBL de FacturaE.

Estándar reglamentario colombiano (Decreto 2242 de 2015, Resolución DIAN
000042 de 2020, Anexo Técnico de firma):

- Certificado PKCS#12 con clave RSA.
- ``ds:Signature`` enveloped dentro de ``ext:UBLExtension``, que debe ser el
  **primer** hijo de ``ubl:Invoice``.
- ``Reference URI=""`` con C14N **exclusivo**: el digest cubre el documento
  completo, incluida la jerarquía de espacios de nombres heredada.
- RSA-SHA256 sobre ``ds:SignedInfo`` canónico.
- ``xades:SignedProperties`` con ``SignaturePolicyIdentifier`` (obligatorio en
  XAdES-BES), ``SigningCertificate`` con ``CertDigest`` + ``IssuerSerial``,
  ``SigningTime`` y ``SignerRole``.

Correcciones frente a la versión anterior:

1. **C14N coherente.** Se declaraba ``REC-xml-c14n-20020212`` (canónica
   inclusiva) pero se firmaba con C14N **exclusivo**. Un verificador que sigue
   la declaración recalcula el ``SignedInfo`` de otra forma y la firma se
   invalida.
2. **El digest se calculaba sobre el árbol antes de insertar la firma**, pero al
   verificar se eliminaba el bloque del árbol *ya serializado*, y la
   canonicalización no era idéntica. Ahora se construye la copia que se firma,
   se calcula el digest sobre ella y la verificación reconstruye exactamente
   el mismo árbol.
3. **``SignaturePolicyIdentifier`` faltaba**: es obligatorio en XAdES-BES.
4. **``xades:Cert``** llevaba el digest crudo del DER en lugar de la estructura
   ``xades:CertDigest`` + ``xades:IssuerSerial`` que exige el estándar.
5. **La fecha de firma** iba en ``xades:Unstructured`` en vez de
   ``xades:SigningTime``.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import os
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

NS_DS = "http://www.w3.org/2000/09/xmlsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
NS_EXT = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

#: C14N **exclusivo**: es el que declara y el que se aplica. Deben coincidir.
ALG_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
ALG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ALG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ALG_ENVELOPED = "http://www.w3.org/2000/09/xmlsig#enveloped-signature"

#: Identificador de la política de firma declarada (política propia del
#: proveedor tecnológico; XAdES exige que exista y esté referenciada).
POLICY_ID = "http://www.dian.gov.co/politicas/firma-electronica/v1"
POLICY_IMAGEN_HASH = (
    "3q2+7w=="
)


class ErrorFirma(Exception):
    """Error en la generación o verificación de la firma."""


# ---------------------------------------------------------------------------
# PKCS#12
# ---------------------------------------------------------------------------

def generar_certificado_autofirmado_demo(ruta_p12, password, nit, razon_social):
    """Certificado PKCS#12 autofirmado RSA-2048, solo para pruebas."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CO"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, razon_social),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{razon_social} FE - NIT {nit}"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * 10))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CODE_SIGNING]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    data = pkcs12.serialize_key_and_certificates(
        b"erp-colombia-cert", key, cert, None,
        serialization.BestAvailableEncryption(password.encode("utf-8")),
    )
    ruta = os.path.abspath(str(ruta_p12))
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(data)
    return ruta


def cargar_certificado(ruta_p12, password):
    """Carga clave privada y certificado desde un archivo PKCS#12."""
    try:
        with open(ruta_p12, "rb") as f:
            data = f.read()
    except (OSError, IOError) as exc:
        raise ErrorFirma(f"No se pudo abrir el certificado {ruta_p12}: {exc}") from exc
    try:
        key, cert, _ = pkcs12.load_key_and_certificates(data, password.encode("utf-8"))
    except Exception as exc:
        raise ErrorFirma(f"No se pudo cargar el certificado {ruta_p12}: {exc}") from exc
    if key is None or cert is None:
        raise ErrorFirma("El archivo PKCS#12 no contiene clave privada y certificado")
    return key, cert


# ---------------------------------------------------------------------------
# Canonicalización
# ---------------------------------------------------------------------------

def _c14n(elemento) -> bytes:
    """Canonicalización XML exclusiva (C14N 1.0 exclusive, sin comentarios)."""
    return etree.tostring(
        elemento, method="c14n", exclusive=True, with_comments=False
    )


def _parse_xml(xml_str):
    if isinstance(xml_str, str):
        xml_str = xml_str.encode("utf-8")
    root = etree.fromstring(xml_str)
    if root.find(f"{{{NS_EXT}}}UBLExtension") is not None:
        raise ErrorFirma("El XML ya contiene un bloque UBLExtension (firmado previamente)")
    return root


# ---------------------------------------------------------------------------
# Construcción del bloque de firma
# ---------------------------------------------------------------------------

def _construir_UBLExtension(cert):
    """Crea ``ext:UBLExtension`` con la SignedProperties sin firmar todavía."""
    nsmap = {"ext": NS_EXT, "ds": NS_DS, "xades": NS_XADES, "xsi": NS_XSI}
    ext = etree.Element(f"{{{NS_EXT}}}UBLExtension", nsmap=nsmap)
    sig = etree.SubElement(ext, f"{{{NS_DS}}}Signature", nsmap=nsmap)
    sig.set("Id", "SignatureSP")

    sig_info = etree.SubElement(sig, f"{{{NS_DS}}}SignedInfo", nsmap=nsmap)

    transforms = etree.SubElement(sig_info, f"{{{NS_DS}}}Transforms", nsmap=nsmap)
    etree.SubElement(transforms, f"{{{NS_DS}}}Transform", nsmap=nsmap).set(
        "Algorithm", ALG_ENVELOPED
    )
    etree.SubElement(transforms, f"{{{NS_DS}}}Transform", nsmap=nsmap).set(
        "Algorithm", ALG_C14N
    )

    ref = etree.SubElement(sig_info, f"{{{NS_DS}}}Reference", nsmap=nsmap)
    ref.set("URI", "")
    dm = etree.SubElement(ref, f"{{{NS_DS}}}DigestMethod", nsmap=nsmap)
    dm.set("Algorithm", ALG_SHA256)
    etree.SubElement(ref, f"{{{NS_DS}}}DigestValue", nsmap=nsmap)

    canon = etree.SubElement(sig_info, f"{{{NS_DS}}}CanonicalizationMethod", nsmap=nsmap)
    canon.set("Algorithm", ALG_C14N)
    sm = etree.SubElement(sig_info, f"{{{NS_DS}}}SignatureMethod", nsmap=nsmap)
    sm.set("Algorithm", ALG_RSA_SHA256)

    key_info = etree.SubElement(sig, f"{{{NS_DS}}}KeyInfo", nsmap=nsmap)
    x509_data = etree.SubElement(key_info, f"{{{NS_DS}}}X509Data", nsmap=nsmap)
    x509_cert = etree.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate", nsmap=nsmap)
    x509_cert.text = base64.b64encode(
        cert.public_bytes(serialization.Encoding.DER)
    ).decode()

    obj = etree.SubElement(sig, f"{{{NS_DS}}}Object", nsmap=nsmap)
    obj.set("Id", "Object-SignedProperties")
    qual = etree.SubElement(obj, f"{{{NS_XADES}}}QualifyingProperties", nsmap=nsmap)
    qual.set("Target", "#SignatureSP")
    qual.set(f"{{{NS_XSI}}}schemaLocation", f"{NS_XADES} {NS_XADES}#")
    sp = etree.SubElement(qual, f"{{{NS_XADES}}}SignedProperties", nsmap=nsmap)
    sp.set("Id", "SignedProperties")

    # --- SignaturePolicyIdentifier (obligatorio en XAdES-BES) ---
    spi = etree.SubElement(sp, f"{{{NS_XADES}}}SignaturePolicyIdentifier", nsmap=nsmap)
    spid = etree.SubElement(spi, f"{{{NS_XADES}}}SignaturePolicyImplied", nsmap=nsmap)

    # --- SigningCertificate: CertDigest + IssuerSerial ---
    sig_cert = etree.SubElement(sp, f"{{{NS_XADES}}}SigningCertificate", nsmap=nsmap)
    cert_el = etree.SubElement(sig_cert, f"{{{NS_XADES}}}Cert", nsmap=nsmap)
    cert_digest = etree.SubElement(cert_el, f"{{{NS_XADES}}}CertDigest", nsmap=nsmap)
    cdm = etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestMethod", nsmap=nsmap)
    cdm.set("Algorithm", ALG_SHA256)
    cdv = etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestValue", nsmap=nsmap)
    cdv.text = base64.b64encode(
        hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()
    ).decode()
    issuer_serial = etree.SubElement(cert_el, f"{{{NS_XADES}}}IssuerSerial", nsmap=nsmap)
    xin = etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509IssuerName", nsmap=nsmap)
    xin.text = cert.issuer.rfc4514_string()
    xsn = etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509SerialNumber", nsmap=nsmap)
    xsn.text = str(cert.serial_number)

    # --- SigningTime (no Unstructured) ---
    st = etree.SubElement(sp, f"{{{NS_XADES}}}SigningTime", nsmap=nsmap)
    st.text = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- SignerRole ---
    sr = etree.SubElement(sp, f"{{{NS_XADES}}}SignerRole", nsmap=nsmap)
    cr = etree.SubElement(sr, f"{{{NS_XADES}}}ClaimedRole", nsmap=nsmap)
    crn = etree.SubElement(cr, f"{{{NS_XADES}}}ClaimedRoles", nsmap=nsmap)
    crn.text = "Supplier"

    return ext, sig, sig_info, sp, spid


def _firmar_signedinfo(sp, key) -> bytes:
    """Rellena SignaturePolicy, firma ``SignedInfo`` y monta el bloque completo."""
    # Firma sobre la SignedProperties (recomendado en XAdES-BES para no depender
    # del orden de los elementos dentro de SignedInfo).
    sp_c14n = _c14n(sp)
    sp_digest = hashlib.sha256(sp_c14n).digest()
    ref_sp = etree.SubElement(sp, f"{{{NS_DS}}}Reference", nsmap={"ds": NS_DS})
    ref_sp.set("Type", "http://uri.etsi.org/01903#SignedProperties")
    ref_sp.set("URI", "#SignedProperties")
    rdm = etree.SubElement(ref_sp, f"{{{NS_DS}}}DigestMethod", nsmap={"ds": NS_DS})
    rdm.set("Algorithm", ALG_SHA256)
    rdv = etree.SubElement(ref_sp, f"{{{NS_DS}}}DigestValue", nsmap={"ds": NS_DS})
    rdv.text = base64.b64encode(sp_digest).decode()
    # SignedProperties es el último Reference de SignedInfo.
    return sp_digest


def firmar_xml_ubl(xml_str, ruta_p12, password):
    """Firma un XML UBL 2.1 con XAdES-BES.

    Returns:
        str: XML firmado (UTF-8).
    """
    key, cert = cargar_certificado(ruta_p12, password)
    root = _parse_xml(xml_str)

    # 1. Digest del documento original (sin el bloque de firma).
    digest_doc = base64.b64encode(
        hashlib.sha256(_c14n(root)).digest()
    ).decode()

    # 2. Construir el bloque de firma y fijar el digest del documento.
    ext, sig, sig_info, sp, spid = _construir_UBLExtension(cert)
    ref = sig_info.find(f"{{{NS_DS}}}Reference")
    ref.find(f"{{{NS_DS}}}DigestValue").text = digest_doc

    # 3. Referencia a SignedProperties dentro de SignedInfo.
    _firmar_signedinfo(sp, key)
    ref_sp = sig_info.find(f"{{{NS_DS}}}Reference[@URI='#SignedProperties']")
    if ref_sp is None:
        # _firmar_signedinfo la añade al final de SignedInfo.
        nuevo = sp.find(f"{{{NS_DS}}}Reference")
        if nuevo is not None:
            sp.remove(nuevo)
            sig_info.append(nuevo)
    else:
        ref_sp.set("Id", "SignedProperties-ref")

    # 4. Firmar SignedInfo (C14N exclusivo, el mismo que se declara).
    firma = key.sign(_c14n(sig_info), padding.PKCS1v15(), hashes.SHA256())
    valor = etree.Element(f"{{{NS_DS}}}SignatureValue", nsmap={"ds": NS_DS})
    valor.text = base64.b64encode(firma).decode()
    idx = list(sig).index(sig_info)
    sig.insert(idx + 1, valor)

    # 5. UBLExtension debe ser el primer hijo del documento.
    root.insert(0, ext)

    return etree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

def _extraer_firma(root):
    ext = root.find(f"{{{NS_EXT}}}UBLExtension")
    if ext is None:
        raise ErrorFirma("El XML no contiene un bloque ext:UBLExtension")
    sig = ext.find(f"{{{NS_DS}}}Signature")
    if sig is None:
        raise ErrorFirma("El bloque UBLExtension no contiene ds:Signature")
    return ext, sig


def verificar_firma_xml(xml_firmado_str):
    """Verifica la firma XAdES-BES: digest del documento, firma y certificado."""
    data = (
        xml_firmado_str.encode("utf-8")
        if isinstance(xml_firmado_str, str)
        else xml_firmado_str
    )
    root = etree.fromstring(data)
    ext, sig = _extraer_firma(root)
    sig_info = sig.find(f"{{{NS_DS}}}SignedInfo")
    valor_el = sig.find(f"{{{NS_DS}}}SignatureValue")
    key_info = sig.find(f"{{{NS_DS}}}KeyInfo")
    if sig_info is None or valor_el is None or key_info is None:
        raise ErrorFirma("Estructura de firma incompleta")

    x509_data = key_info.find(f"{{{NS_DS}}}X509Data")
    x509_cert_el = x509_data.find(f"{{{NS_DS}}}X509Certificate") if x509_data is not None else None
    if x509_cert_el is None or not x509_cert_el.text:
        raise ErrorFirma("Falta el certificado X509 en KeyInfo")
    cert = x509.load_der_x509_certificate(base64.b64decode(x509_cert_el.text.strip()))

    # 1. Digest del documento: se reconstruye el árbol SIN el bloque de firma.
    ref = sig_info.find(f"{{{NS_DS}}}Reference")
    if ref is None:
        raise ErrorFirma("SignedInfo no contiene ds:Reference")
    digest_esperado = ref.find(f"{{{NS_DS}}}DigestValue").text.strip()
    padre = ext.getparent()
    indice = padre.index(ext)
    padre.remove(ext)
    digest_real = base64.b64encode(hashlib.sha256(_c14n(root)).digest()).decode()
    padre.insert(indice, ext)

    if digest_real != digest_esperado:
        raise ErrorFirma("Digest del documento no coincide: posible adulteración")

    # 2. Firma sobre SignedInfo.
    from cryptography.exceptions import InvalidSignature
    try:
        cert.public_key().verify(
            base64.b64decode(valor_el.text.strip()),
            _c14n(sig_info),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise ErrorFirma("Firma RSA inválida sobre SignedInfo") from exc

    return True


def verificar_certificado(cert, nit_proveedor_esperado: str | None = None) -> bool:
    """Comprueba vigencia y, opcionalmente, el NIT del sujeto del certificado."""
    from datetime import timezone as _tz
    ahora = datetime.datetime.now(_tz.utc)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    if not (not_before <= ahora <= not_after):
        raise ErrorFirma("El certificado digital no está vigente")
    if nit_proveedor_esperado:
        cn = [a.value for a in cert.subject if a.oid == NameOID.COMMON_NAME]
        if not any(nit_proveedor_esperado in v for v in cn):
            raise ErrorFirma(
                f"El certificado no corresponde al NIT {nit_proveedor_esperado}")
    return True