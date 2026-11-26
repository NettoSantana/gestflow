# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\rtc_laboratorio.py
# Último recode: 2026-11-26 05:22:02 (America/Bahia)
# Motivo: Consumir as APIs oficiais RTC pela rede privada do Railway e validar XML de laboratório.

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from lxml import etree

from nfse_laboratorio import NS_NFSE, PASTA_XSD, NFSeLaboratorioErro, erro_validacao_xsd, validar_xsd_oficial

CALCULADORAS = {
    "regular": ("GESTFLOW_RTC_REGULAR_URL", "/api/calculadora/observabilidade/regime-geral"),
    "simples": ("GESTFLOW_RTC_SIMPLES_URL", "/api/calculadora/observabilidade/simples-nacional"),
}
MAX_ENTRADA = 256_000
MAX_RESPOSTA = 8_000_000
LOGGER = logging.getLogger(__name__)


class RTCLaboratorioErro(ValueError):
    """Falha de entrada ou comunicação no laboratório."""


class SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _enviar(variavel, rota, dados, tipo, aceite):
    url = urlsplit(os.environ.get(variavel, "").strip())
    if (
        url.scheme != "http" or not url.hostname
        or not url.hostname.endswith(".railway.internal")
        or url.username is not None or url.password is not None
        or url.path not in ("", "/") or url.query or url.fragment
    ):
        raise RTCLaboratorioErro("Serviço fiscal privado indisponível.")
    pedido = Request(
        f"http://{url.netloc}{rota}", data=dados, method="POST",
        headers={"Content-Type": tipo, "Accept": aceite},
    )
    cliente = build_opener(ProxyHandler({}), SemRedirecionamento())
    try:
        with cliente.open(pedido, timeout=10) as resposta:
            corpo = resposta.read(MAX_RESPOSTA + 1)
            tipo_resposta = resposta.headers.get_content_type()
    except HTTPError as erro:
        with erro:
            codigo = erro.code
            if aceite == "application/json" and codigo in (400, 422):
                return erro.read(MAX_ENTRADA), codigo
        LOGGER.warning("RTC %s respondeu HTTP %s", variavel, codigo)
        raise RTCLaboratorioErro(f"Serviço fiscal respondeu HTTP {codigo}.") from None
    except (URLError, OSError):
        LOGGER.warning("Falha de conexão RTC %s", variavel)
        raise RTCLaboratorioErro("Falha de comunicação com o serviço fiscal.") from None
    if len(corpo) > MAX_RESPOSTA or tipo_resposta != aceite:
        raise RTCLaboratorioErro("Resposta inválida do serviço fiscal.")
    return corpo, 200


def calcular_rtc(regime, texto):
    if regime not in CALCULADORAS:
        raise RTCLaboratorioErro("Selecione o regime tributário.")
    dados = texto.encode("utf-8")
    if not 0 < len(dados) <= MAX_ENTRADA:
        raise RTCLaboratorioErro("JSON vazio ou acima do limite do laboratório.")
    try:
        objeto = json.loads(dados)
    except (ValueError, RecursionError):
        raise RTCLaboratorioErro("JSON da operação inválido.") from None
    if not isinstance(objeto, dict):
        raise RTCLaboratorioErro("O JSON da operação deve ser um objeto.")
    variavel, rota = CALCULADORAS[regime]
    corpo, codigo = _enviar(variavel, rota, dados, "application/json", "application/json")
    try:
        return {"http": codigo, "resultado": json.loads(corpo)}
    except (ValueError, RecursionError):
        raise RTCLaboratorioErro("A calculadora retornou um JSON inválido.") from None


def conferir_xml_rtc(xml):
    if not 0 < len(xml) <= MAX_ENTRADA:
        raise RTCLaboratorioErro("XML vazio ou acima do limite do laboratório.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        raiz = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError:
        raise RTCLaboratorioErro("XML malformado.") from None
    if raiz.getroottree().docinfo.doctype:
        raise RTCLaboratorioErro("DTD e entidades externas são proibidas.")
    if raiz.tag == f"{{{NS_NFSE}}}DPS":
        return {"tipo": "DPS", **validar_xsd_oficial(xml)}
    if raiz.tag != f"{{{NS_NFSE}}}NFSe":
        raise RTCLaboratorioErro("Informe uma DPS ou NFS-e do leiaute nacional.")
    ambiente = raiz.findtext(f"{{{NS_NFSE}}}infNFSe/{{{NS_NFSE}}}DPS/{{{NS_NFSE}}}infDPS/{{{NS_NFSE}}}tpAmb")
    if ambiente != "2":
        raise RTCLaboratorioErro("O laboratório aceita somente NFS-e de homologação (tpAmb=2).")
    try:
        erro = erro_validacao_xsd(xml, PASTA_XSD / "NFSe_v1.01.xsd")
    except (etree.LxmlError, NFSeLaboratorioErro, OSError):
        raise RTCLaboratorioErro("Falha ao carregar ou aplicar o XSD de NFS-e.") from None
    return {
        "tipo": "NFSe", "executada": True, "aprovada": erro is None,
        "mensagem": erro if erro is not None else "XML aceito pelo XSD de produção restrita.",
    }


def gerar_danfse(xml):
    resultado = conferir_xml_rtc(xml)
    if resultado["tipo"] != "NFSe" or not resultado["aprovada"]:
        raise RTCLaboratorioErro("O DANFSe exige uma NFS-e de homologação aprovada pelo XSD.")
    pdf, _ = _enviar("GESTFLOW_RTC_DANFSE_URL", "/api/danfse", xml, "application/xml", "application/pdf")
    if not pdf.startswith(b"%PDF-"):
        raise RTCLaboratorioErro("O gerador retornou um PDF inválido.")
    return pdf
