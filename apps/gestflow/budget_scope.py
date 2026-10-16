# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\budget_scope.py
# Último recode: 2026-10-16 14:32 (America/Bahia)
# Motivo: Preservar títulos, listas e parágrafos dos orçamentos com HTML limitado e seguro.

import html
import re
from html.parser import HTMLParser
from markupsafe import Markup

MARCADOR = '<!--GESTFLOW_SCOPE_V1-->'
TAGS = {'p', 'div', 'br', 'h1', 'h2', 'h3', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li', 'blockquote'}
IGNORAR = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template', 'noscript', 'head'}


class _HTMLSeguro(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.saida = []
        self.abertas = []
        self.bloqueadas = []

    def handle_starttag(self, tag, attrs):
        if self.bloqueadas:
            if tag in IGNORAR:
                self.bloqueadas.append(tag)
            return
        if tag in IGNORAR:
            self.bloqueadas.append(tag)
            return
        if tag not in TAGS:
            return
        atributo = ''
        if tag == 'ol':
            inicio = dict(attrs).get('start', '')
            if re.fullmatch(r'\d{1,5}', inicio or ''):
                atributo = f' start="{int(inicio)}"'
        self.saida.append(f'<{tag}{atributo}>')
        if tag != 'br':
            self.abertas.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br':
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.bloqueadas:
            if tag == self.bloqueadas[-1]:
                self.bloqueadas.pop()
            return
        if tag in self.abertas:
            while self.abertas:
                atual = self.abertas.pop()
                self.saida.append(f'</{atual}>')
                if atual == tag:
                    break

    def handle_data(self, data):
        if not self.bloqueadas:
            self.saida.append(html.escape(data, quote=False))

    def resultado(self):
        while self.abertas:
            self.saida.append(f'</{self.abertas.pop()}>')
        return ''.join(self.saida).strip()


def _normalizar_linhas(valor):
    return str(valor or '').replace('\r\n', '\n').replace('\r', '\n').replace('\\n', '\n').strip()


def _rico(valor):
    texto = re.sub(r'^\s*Escopo:\s*', '', _normalizar_linhas(valor), count=1, flags=re.I)
    return texto.startswith(MARCADOR)


def _sanitizar(valor):
    parser = _HTMLSeguro()
    parser.feed(str(valor or '').replace(MARCADOR, ''))
    parser.close()
    return parser.resultado()


def normalizar_escopo(valor):
    texto = _normalizar_linhas(valor)
    if _rico(texto):
        texto = re.sub(r'^\s*Escopo:\s*', '', texto, count=1, flags=re.I)
        seguro = _sanitizar(texto)
        return MARCADOR + seguro if re.sub(r'<[^>]+>', '', seguro).strip() else ''
    return texto


def _inline(texto):
    texto = html.escape(texto, quote=False)
    return re.sub(r'\*\*([^*\n]+)\*\*', r'<strong>\1</strong>', texto)


def _texto_html(valor):
    saida = []
    lista = None
    for linha in _normalizar_linhas(valor).split('\n'):
        titulo = re.match(r'^\s*(#{1,6})\s+(.+)$', linha)
        item = re.match(r'^\s*([-*+•]|\d+[.)])\s+(.+)$', linha)
        tipo = ('ul' if not item.group(1)[0].isdigit() else 'ol') if item else None
        if lista and tipo != lista:
            saida.append(f'</{lista}>')
            lista = None
        if item:
            if not lista:
                inicio = re.match(r'\d+', item.group(1))
                atributo = f' start="{int(inicio[0])}"' if tipo == 'ol' and inicio else ''
                saida.append(f'<{tipo}{atributo}>')
                lista = tipo
            saida.append('<li>' + _inline(item.group(2)) + '</li>')
        elif titulo:
            nivel = min(len(titulo.group(1)), 3)
            saida.append(f'<h{nivel}>' + _inline(titulo.group(2)) + f'</h{nivel}>')
        else:
            saida.append('<p>' + (_inline(linha) if linha.strip() else '<br>') + '</p>')
    if lista:
        saida.append(f'</{lista}>')
    return ''.join(saida)


def escopo_html(valor):
    texto = normalizar_escopo(valor)
    return _sanitizar(texto) if _rico(texto) else (_texto_html(texto) if texto else '')


def formatar_escopo(observacoes, dados_gerador=None):
    dados = dados_gerador or {}
    principal = escopo_html(dados.get('escopo') or observacoes)
    adicional = escopo_html(dados.get('observacoes_cliente'))
    if adicional:
        principal += '<h3>Observações adicionais</h3>' + adicional
    return {'html': Markup(principal), 'secoes': [], 'texto_livre': [], 'observacoes_adicionais': []}


class _TextoSimples(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []

    def handle_starttag(self, tag, attrs):
        if tag in {'p', 'div', 'br', 'h1', 'h2', 'h3', 'li', 'blockquote'}:
            self.partes.append('\n' + ('- ' if tag == 'li' else ''))

    def handle_endtag(self, tag):
        if tag in {'p', 'div', 'h1', 'h2', 'h3', 'li', 'blockquote'}:
            self.partes.append('\n')

    def handle_data(self, data):
        self.partes.append(data)


def escopo_texto_simples(valor):
    if not _rico(valor):
        return str(valor or '')
    parser = _TextoSimples()
    parser.feed(escopo_html(valor))
    return re.sub(r'\n{3,}', '\n\n', ''.join(parser.partes)).strip()
