# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\nfse_homologacao.py
# Último recode: 2026-11-14 08:12:44 (America/Bahia)
# Motivo: Preparar leitura protegida do A1 piloto, diagnóstico local e assinatura XMLDSig de DPS sem transmissão.

"""Preparação de NFS-e: somente diagnóstico e assinatura local (sem comunicação com governo).

As variáveis do piloto ficam no gerenciador de segredos do Railway, nunca no banco:
GESTFLOW_NFSE_PILOTO_EMPRESA_ID, GESTFLOW_NFSE_PILOTO_PFX_B64, GESTFLOW_NFSE_PILOTO_PFX_SENHA.
O certificado deve ser ICP-Brasil real para a etapa futura; esta rotina não valida
cadeia ICP-Brasil, revogação, regras tributárias ou XML contra o XSD nacional.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier
from lxml import etree

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
RSA_SHA1 = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
_OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
_MAX_PFX_B64 = 700_000
_MAX_DPS_XML = 256_000


class NFSeHomologacaoErro(ValueError):
    """Erro de preparação local da NFS-e, sem dados secretos na mensagem."""


def _normalizar_cnpj(cnpj: str) -> str:
    return re.sub(r"[.\/\-\s]", "", str(cnpj or "").upper())


def _cnpj_do_certificado(cert: x509.Certificate) -> str:
    """Extrai CNPJ do identificador ICP-Brasil ou do CN do titular, quando presente."""
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        for other in san.get_values_for_type(x509.OtherName):
            if other.type_id == _OID_CNPJ:
                encontrado = re.search(rb"(?<![0-9])[0-9]{14}(?![0-9])", other.value)
                if encontrado:
                    return encontrado.group(0).decode("ascii")
    except x509.ExtensionNotFound:
        pass

    for atributo in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
        encontrado = re.search(r":\s*([0-9]{14})\b", atributo.value)
        if encontrado:
            return encontrado.group(1)
    return ""


def _ler_credencial_piloto(empresa_id: int, cnpj_esperado: str):
    if not cnpj_esperado:
        raise NFSeHomologacaoErro("Cadastre primeiro o CNPJ em Configurações fiscais.")
    id_definido = os.environ.get("GESTFLOW_NFSE_PILOTO_EMPRESA_ID", "").strip()
    if not id_definido:
        raise NFSeHomologacaoErro("Piloto A1 não configurado nas variáveis protegidas do Railway.")
    if id_definido != str(int(empresa_id)):
        raise NFSeHomologacaoErro("Este piloto A1 não está habilitado para esta empresa.")

    pfx_b64 = os.environ.get("GESTFLOW_NFSE_PILOTO_PFX_B64", "").strip()
    senha = os.environ.get("GESTFLOW_NFSE_PILOTO_PFX_SENHA", "")
    if not pfx_b64 or not senha:
        raise NFSeHomologacaoErro("Certificado ou senha do piloto não configurados no Railway.")
    if len(pfx_b64) > _MAX_PFX_B64:
        raise NFSeHomologacaoErro("Certificado A1 maior que o limite permitido para este piloto.")
    try:
        raw = base64.b64decode(pfx_b64, validate=True)
        chave, certificado, _cadeia = pkcs12.load_key_and_certificates(raw, senha.encode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        raise NFSeHomologacaoErro("Não foi possível ler o A1. Verifique o arquivo e a senha no Railway.") from None
    if not isinstance(chave, rsa.RSAPrivateKey) or certificado is None:
        raise NFSeHomologacaoErro("O A1 precisa conter chave privada RSA e certificado X.509.")
    agora = datetime.now(timezone.utc)
    if agora < certificado.not_valid_before_utc or agora > certificado.not_valid_after_utc:
        raise NFSeHomologacaoErro("O certificado A1 não está dentro do prazo de validade.")
    try:
        uso = certificado.extensions.get_extension_for_class(x509.KeyUsage).value
        if not uso.digital_signature:
            raise NFSeHomologacaoErro("O A1 não permite assinatura digital.")
    except x509.ExtensionNotFound:
        raise NFSeHomologacaoErro("Certificado sem extensão de uso de chave para assinatura digital.") from None
    cnpj_cert = _cnpj_do_certificado(certificado)
    if not cnpj_cert:
        raise NFSeHomologacaoErro("Não foi possível identificar o CNPJ do titular no A1.")
    if cnpj_cert != _normalizar_cnpj(cnpj_esperado):
        raise NFSeHomologacaoErro("O CNPJ do certificado não corresponde à empresa configurada.")
    return chave, certificado, cnpj_cert


def diagnosticar_certificado_nfse(empresa_id: int, cnpj_esperado: str) -> dict[str, Any]:
    """Executa prova local da chave, devolvendo somente dados públicos do certificado."""
    try:
        chave, certificado, cnpj = _ler_credencial_piloto(empresa_id, cnpj_esperado)
        desafio = b"GESTFLOW-NFSE-A1-DIAGNOSTICO-LOCAL"
        assinado = chave.sign(desafio, padding.PKCS1v15(), hashes.SHA256())
        certificado.public_key().verify(assinado, desafio, padding.PKCS1v15(), hashes.SHA256())
        titular = certificado.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return {
            "ok": True,
            "mensagem": "A1 lido, CNPJ confere e chave privada validada localmente. Não houve envio à Receita.",
            "titular": titular[0].value if titular else "Não informado",
            "cnpj": cnpj,
            "validade": certificado.not_valid_after_utc.strftime("%d/%m/%Y"),
            "fingerprint": certificado.fingerprint(hashes.SHA256()).hex().upper()[:16],
        }
    except (NFSeHomologacaoErro, ValueError) as exc:
        return {"ok": False, "mensagem": str(exc)}
    except Exception:
        # Nenhuma exceção criptográfica ou credencial deve aparecer na interface.
        return {"ok": False, "mensagem": "Falha no diagnóstico local do A1. Confira as configurações protegidas."}


def _ler_dps_xml(xml: bytes):
    if not isinstance(xml, bytes) or not 0 < len(xml) <= _MAX_DPS_XML:
        raise NFSeHomologacaoErro("XML da DPS ausente ou maior que 256 KB.")
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise NFSeHomologacaoErro("Documentos XML com DTD ou entidades não são permitidos.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        raiz = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError:
        raise NFSeHomologacaoErro("XML da DPS inválido.") from None
    if raiz.tag != f"{{{NS_NFSE}}}DPS":
        raise NFSeHomologacaoErro("A raiz deve ser DPS no namespace nacional.")
    infos = raiz.findall(f"{{{NS_NFSE}}}infDPS")
    if len(infos) != 1:
        raise NFSeHomologacaoErro("A DPS deve conter exatamente um infDPS.")
    info = infos[0]
    identificador = info.get("Id", "")
    if not re.fullmatch(r"DPS[A-Z0-9]{42}", identificador):
        raise NFSeHomologacaoErro("Identificador Id da DPS não segue o formato esperado de 45 caracteres.")
    if raiz.find(f"{{{NS_DS}}}Signature") is not None:
        raise NFSeHomologacaoErro("A DPS já contém assinatura digital.")
    return raiz, info, identificador


def assinar_dps_local(xml: bytes, empresa_id: int, cnpj_esperado: str) -> bytes:
    """Assina uma DPS já montada. NÃO cria a DPS, NÃO valida XSD e NÃO transmite.

    Usa o perfil XMLDSig nacional clássico C14N + RSA/SHA-1 documentado no
    manual integrado. Só pode ser chamado no piloto isolado; a assinatura deve
    ser homologada com o leiaute vigente antes de uso em produção.
    """
    raiz, info, identificador = _ler_dps_xml(xml)
    chave, certificado, _cnpj = _ler_credencial_piloto(empresa_id, cnpj_esperado)

    assinatura = etree.SubElement(raiz, etree.QName(NS_DS, "Signature"), nsmap={None: NS_DS})
    signed_info = etree.SubElement(assinatura, etree.QName(NS_DS, "SignedInfo"))
    etree.SubElement(signed_info, etree.QName(NS_DS, "CanonicalizationMethod"), Algorithm=C14N)
    etree.SubElement(signed_info, etree.QName(NS_DS, "SignatureMethod"), Algorithm=RSA_SHA1)
    referencia = etree.SubElement(signed_info, etree.QName(NS_DS, "Reference"), URI=f"#{identificador}")
    transformacoes = etree.SubElement(referencia, etree.QName(NS_DS, "Transforms"))
    etree.SubElement(transformacoes, etree.QName(NS_DS, "Transform"), Algorithm=ENVELOPED)
    etree.SubElement(transformacoes, etree.QName(NS_DS, "Transform"), Algorithm=C14N)
    etree.SubElement(referencia, etree.QName(NS_DS, "DigestMethod"), Algorithm=SHA1)
    digest = base64.b64encode(hashlib.sha1(etree.tostring(info, method="c14n")).digest()).decode("ascii")
    etree.SubElement(referencia, etree.QName(NS_DS, "DigestValue")).text = digest
    assinatura_raw = chave.sign(etree.tostring(signed_info, method="c14n"), padding.PKCS1v15(), hashes.SHA1())
    etree.SubElement(assinatura, etree.QName(NS_DS, "SignatureValue")).text = base64.b64encode(assinatura_raw).decode("ascii")
    key_info = etree.SubElement(assinatura, etree.QName(NS_DS, "KeyInfo"))
    x509data = etree.SubElement(key_info, etree.QName(NS_DS, "X509Data"))
    certificado_der = certificado.public_bytes(serialization.Encoding.DER)
    etree.SubElement(x509data, etree.QName(NS_DS, "X509Certificate")).text = base64.b64encode(certificado_der).decode("ascii")
    resultado = etree.tostring(raiz, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    verificar_assinatura_local(resultado)
    return resultado


def verificar_assinatura_local(xml_assinado: bytes) -> None:
    """Confere digest e assinatura offline, sem validar cadeia/revogação fiscal."""
    if not isinstance(xml_assinado, bytes) or len(xml_assinado) > _MAX_DPS_XML * 2:
        raise NFSeHomologacaoErro("XML assinado maior que o limite permitido.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        raiz = etree.fromstring(xml_assinado, parser)
        info = raiz.find(f"{{{NS_NFSE}}}infDPS")
        assinatura = raiz.find(f"{{{NS_DS}}}Signature")
        if raiz.tag != f"{{{NS_NFSE}}}DPS" or info is None or assinatura is None:
            raise NFSeHomologacaoErro("Estrutura de assinatura inválida.")
        signed_info = assinatura.find(f"{{{NS_DS}}}SignedInfo")
        referencia = signed_info.find(f"{{{NS_DS}}}Reference")
        digest = referencia.find(f"{{{NS_DS}}}DigestValue").text
        if referencia.get("URI") != f"#{info.get('Id')}":
            raise NFSeHomologacaoErro("Referência XML incorreta.")
        esperado = base64.b64encode(hashlib.sha1(etree.tostring(info, method="c14n")).digest()).decode("ascii")
        if digest != esperado:
            raise NFSeHomologacaoErro("Digest XML inválido.")
        assinatura_valor = base64.b64decode(assinatura.find(f"{{{NS_DS}}}SignatureValue").text, validate=True)
        cert_der = base64.b64decode(assinatura.find(f".//{{{NS_DS}}}X509Certificate").text, validate=True)
        certificado = x509.load_der_x509_certificate(cert_der)
        certificado.public_key().verify(assinatura_valor, etree.tostring(signed_info, method="c14n"), padding.PKCS1v15(), hashes.SHA1())
    except Exception:
        raise NFSeHomologacaoErro("Assinatura XML não passou na verificação local.") from None
