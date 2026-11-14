# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\nfse_laboratorio.py
# Último recode: 2026-11-14 09:02:52 (America/Bahia)
# Motivo: Gerar DPS demonstrativa do leiaute restrito NT 009 e simular retornos, sem transmissão ou dados reais.

"""Laboratório isolado de DPS/NFS-e: SEM envio, sem certificado e sem nota fiscal válida.

A validação OFICIAL por XSD é habilitada somente quando um administrador coloca
os arquivos originais do pacote governamental de 20/10/2026 em pasta privada
 e configura GESTFLOW_NFSE_XSD_DPS_PATH com o caminho absoluto para DPS_v1.01.xsd.
Não se utiliza schema alternativo como prova de conformidade oficial.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from lxml import etree

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
LEIAUTE_HOMOLOGACAO = "NT 009 - Produção Restrita, pacote 20/10/2026"
CENARIOS = {"aceita", "rejeitada", "cancelada"}


class NFSeLaboratorioErro(ValueError):
    """Erro de validação do laboratório, sem enviar informações fiscais."""


def _tag(pai: etree._Element, nome: str, conteudo: str | int) -> etree._Element:
    item = etree.SubElement(pai, etree.QName(NS_NFSE, nome))
    item.text = str(conteudo)
    return item


def _validar_amostra() -> dict[str, Any]:
    # Dados 100% sintéticos. Não consultar nem reutilizar o CNPJ cadastrado no GestFlow.
    return {
        "municipio": "3550308",
        "cnpj": "11222333000181",
        "cpf_tomador": "11144477735",
        "nome_tomador": "Cliente de laboratorio (ficticio)",
        "codigo_servico": "100202",
        "valor_servico": "100.00",
        "descricao": "Prestacao ficticia para teste tecnico do GESTFLOW - sem valor fiscal",
        "serie": 1,
        "numero": 1,
    }


def gerar_dps_demonstracao() -> bytes:
    """Gera DPS XML NÃO ASSINADA, sem dados de qualquer cliente do GestFlow.

    Espelha a estrutura-base do leiaute de produção restrita de outubro/2026,
    mas somente o XSD oficial da versão pode comprovar conformidade sintática.
    As regras fiscais da SEFIN também exigem validações externas posteriores.
    """
    d = _validar_amostra()
    if not re.fullmatch(r"[0-9]{7}", d["municipio"]):
        raise NFSeLaboratorioErro("Código IBGE de teste inválido.")
    identificador = (
        "DPS" + d["municipio"] + "2" + d["cnpj"]
        + str(d["serie"]).zfill(5) + str(d["numero"]).zfill(15)
    )
    if not re.fullmatch(r"DPS[0-9]{42}", identificador):
        raise NFSeLaboratorioErro("Identificador DPS de laboratório inválido.")

    raiz = etree.Element(etree.QName(NS_NFSE, "DPS"), nsmap={None: NS_NFSE})
    raiz.set("versao", "1.01")
    info = etree.SubElement(raiz, etree.QName(NS_NFSE, "infDPS"))
    info.set("Id", identificador)
    # Campo finNFSe é obrigatório no infDPS da produção restrita (NT 009).
    for nome, valor in (
        ("tpAmb", 2),
        ("dhEmi", "2026-11-14T08:00:00-03:00"),
        ("verAplic", "GESTFLOW-LAB-1"),
        ("serie", d["serie"]),
        ("nDPS", d["numero"]),
        ("dCompet", "2026-11-14"),
        ("tpEmit", 1),
        ("finNFSe", 0),
        ("cLocEmi", d["municipio"]),
    ):
        _tag(info, nome, valor)

    prestador = etree.SubElement(info, etree.QName(NS_NFSE, "prest"))
    _tag(prestador, "CNPJ", d["cnpj"])
    regime = etree.SubElement(prestador, etree.QName(NS_NFSE, "regTrib"))
    _tag(regime, "opSimpNac", "3")
    _tag(regime, "regApTribSN", "1")
    _tag(regime, "regEspTrib", "0")

    tomador = etree.SubElement(info, etree.QName(NS_NFSE, "toma"))
    _tag(tomador, "CPF", d["cpf_tomador"])
    _tag(tomador, "xNome", d["nome_tomador"])
    endereco = etree.SubElement(tomador, etree.QName(NS_NFSE, "end"))
    endereco_nacional = etree.SubElement(endereco, etree.QName(NS_NFSE, "endNac"))
    _tag(endereco_nacional, "cMun", d["municipio"])
    _tag(endereco_nacional, "CEP", "01001000")
    _tag(endereco, "xLgr", "Rua de Laboratorio")
    _tag(endereco, "nro", "100")
    _tag(endereco, "xBairro", "Centro")

    servico = etree.SubElement(info, etree.QName(NS_NFSE, "serv"))
    local = etree.SubElement(servico, etree.QName(NS_NFSE, "locPrest"))
    _tag(local, "cLocPrestacao", d["municipio"])
    codigo = etree.SubElement(servico, etree.QName(NS_NFSE, "cServ"))
    _tag(codigo, "cTribNac", d["codigo_servico"])
    _tag(codigo, "xDescServ", d["descricao"])

    valores = etree.SubElement(info, etree.QName(NS_NFSE, "valores"))
    prestado = etree.SubElement(valores, etree.QName(NS_NFSE, "vServPrest"))
    _tag(prestado, "vServ", d["valor_servico"])
    tributacao = etree.SubElement(valores, etree.QName(NS_NFSE, "trib"))
    municipal = etree.SubElement(tributacao, etree.QName(NS_NFSE, "tribMun"))
    _tag(municipal, "tribISSQN", "1")
    _tag(municipal, "tpRetISSQN", "1")
    total = etree.SubElement(tributacao, etree.QName(NS_NFSE, "totTrib"))
    totais = etree.SubElement(total, etree.QName(NS_NFSE, "vTotTrib"))
    for nome in ("vTotTribFed", "vTotTribEst", "vTotTribMun"):
        _tag(totais, nome, "0.00")

    return etree.tostring(raiz, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def conferir_estrutura_local(xml: bytes) -> None:
    """Checa segurança e formato básico. NÃO substitui a validação por XSD."""
    if not isinstance(xml, bytes) or not 0 < len(xml) <= 256_000:
        raise NFSeLaboratorioErro("XML vazio ou muito grande para o laboratório.")
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise NFSeLaboratorioErro("DTD e entidades externas são proibidas.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        raiz = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError:
        raise NFSeLaboratorioErro("XML malformado.") from None
    if raiz.tag != f"{{{NS_NFSE}}}DPS" or raiz.get("versao") != "1.01":
        raise NFSeLaboratorioErro("DPS fora do namespace ou da versão de laboratório.")
    inf = raiz.find(f"{{{NS_NFSE}}}infDPS")
    if inf is None or not re.fullmatch(r"DPS[0-9]{42}", inf.get("Id", "")):
        raise NFSeLaboratorioErro("Id DPS inválido.")
    if inf.findtext(f"{{{NS_NFSE}}}tpAmb") != "2":
        raise NFSeLaboratorioErro("O laboratório só aceita tpAmb=2.")
    if inf.findtext(f"{{{NS_NFSE}}}finNFSe") != "0":
        raise NFSeLaboratorioErro("Falta a finalidade regular da NFS-e.")
    if len(raiz.findall(f"{{{NS_NFSE}}}infDPS")) != 1:
        raise NFSeLaboratorioErro("DPS deve conter um único infDPS.")


def validar_xsd_oficial(xml: bytes) -> dict[str, Any]:
    """Só valida com o arquivo oficial completo instalado pelo administrador.

    XSDs incluídos/importados devem estar ao lado do DPS_v1.01.xsd.
    Não acessa rede, não transfere XML e não usa esquema simplificado.
    """
    caminho = os.environ.get("GESTFLOW_NFSE_XSD_DPS_PATH", "").strip()
    if not caminho:
        return {
            "executada": False, "aprovada": False,
            "mensagem": "XSD oficial de homologação não instalado; conformidade nacional NÃO verificada.",
        }
    arquivo = Path(caminho)
    if not arquivo.is_absolute() or arquivo.name != "DPS_v1.01.xsd" or not arquivo.is_file():
        return {"executada": False, "aprovada": False, "mensagem": "Caminho do XSD oficial inválido."}
    try:
        conferir_estrutura_local(xml)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
        documento_xsd = etree.parse(str(arquivo), parser)
        schema = etree.XMLSchema(documento_xsd)
        documento_xml = etree.fromstring(xml, parser)
        if schema.validate(documento_xml):
            return {"executada": True, "aprovada": True, "mensagem": "XML aceito pelo XSD configurado localmente (não pela SEFIN)."}
        return {
            "executada": True, "aprovada": False,
            "mensagem": "XML rejeitado pelo XSD configurado: " + str(schema.error_log.last_error or "erro desconhecido")[:250],
        }
    except (etree.XMLSchemaError, etree.XMLSyntaxError, NFSeLaboratorioErro, OSError):
        return {"executada": False, "aprovada": False, "mensagem": "Falha ao carregar/validar o pacote XSD local."}


def simular_retorno(cenario: str) -> dict[str, Any]:
    """Cenários fictícios: não modifica rascunhos e não cria número fiscal."""
    casos = {
        "aceita": ("LAB-ACEITA", "DPS recebida e aceita no SIMULADOR (nenhuma NFS-e foi emitida)."),
        "rejeitada": ("LAB-REJEITADA", "DPS recusada no SIMULADOR por regra fictícia de cadastro."),
        "cancelada": ("LAB-CANCELADA", "Rascunho cancelado no SIMULADOR; nenhum evento fiscal foi transmitido."),
    }
    escolha = cenario if cenario in CENARIOS else "aceita"
    codigo, mensagem = casos[escolha]
    return {
        "cenario": escolha,
        "codigo": codigo,
        "mensagem": mensagem,
        "simulacao": True,
        "nota_fiscal_emitida": False,
        "chave_acesso": None,
        "protocolo": None,
    }


def executar_laboratorio(cenario: str = "aceita") -> dict[str, Any]:
    xml = gerar_dps_demonstracao()
    conferir_estrutura_local(xml)
    return {
        "leiaute": LEIAUTE_HOMOLOGACAO,
        "xml": xml.decode("utf-8"),
        "xsd": validar_xsd_oficial(xml),
        "simulacao": simular_retorno(cenario),
        "certificado_utilizado": False,
        "transmissao_realizada": False,
        "aviso": "LABORATÓRIO: documento com dados fictícios, não assinado e sem validade fiscal.",
    }
