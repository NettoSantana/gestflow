# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\access_control.py
# Último recode: 2026-10-15 15:14 (America/Bahia)
# Motivo: Aplicar permissões de telas e ações recebidas do GestFlow, sem interferir na comunicação dos dispositivos.

import json
import os
import time
import urllib.request
import urllib.error
from flask import request, session, redirect, jsonify, Response
from itsdangerous import URLSafeTimedSerializer

DESTINOS = {
    'dashboard': '/', 'operacao': '/operacao/', 'historico': '/producao/historico',
    'paradas': '/paradas/', 'indicadores': '/indicadores/', 'utilidades': '/utilidades/',
    'manutencao': '/manutencao/', 'ativos': '/ativos/',
    'operadores': '/operacao/operadores', 'devices': '/devices/', 'configuracoes': '/admin/',
}
ACOES = {'visualizar', 'criar', 'editar', 'excluir', 'aprovar', 'exportar'}


def permitido(tela, acao='visualizar'):
    if not session.get('gestflow_sso'):
        return True  # Operadores com QR/PIN continuam usando as regras próprias.
    return acao in (session.get('indflow_acesso') or {}).get('telas', {}).get(tela, [])


def primeiro_destino():
    return next((url for tela, url in DESTINOS.items() if permitido(tela)), None)


def role_acesso(info):
    telas = info.get('telas') or {}
    escrever = any(set(a) & {'criar', 'editar', 'excluir', 'aprovar'} for a in telas.values())
    tecnico = any('visualizar' in telas.get(t, []) for t in ('configuracoes', 'devices', 'operadores'))
    return 'admin' if escrever or tecnico else 'viewer'


def telas_rota(caminho):
    if caminho in {'/', '/producao', '/producao/'}:
        return ['dashboard']
    if caminho == '/devices/machines':
        return ['dashboard', 'operacao', 'historico', 'indicadores', 'paradas', 'devices']
    if caminho in {'/paradas/api/contexto', '/paradas/api/ocorrencias'}:
        return ['historico', 'paradas', 'operacao']
    if caminho == '/machine/status' or caminho.startswith('/indicadores/api/card/'):
        return ['dashboard', 'operacao', 'indicadores']
    if '/historico' in caminho or '/detalhe-dia' in caminho or '/detalhe-op' in caminho:
        return ['historico']
    if caminho.startswith(('/producao/config', '/machine/config')):
        return ['configuracoes']
    if caminho.startswith('/operacao/operadores'):
        return ['operadores']
    for prefixo, tela in (
        ('/indicadores', 'indicadores'), ('/operacao', 'operacao'),
        ('/producao', 'operacao'), ('/paradas', 'paradas'),
        ('/utilidades', 'utilidades'), ('/manutencao', 'manutencao'),
        ('/ativos', 'ativos'), ('/devices', 'devices'), ('/admin', 'configuracoes'),
        ('/clientes', 'configuracoes'), ('/teste', 'configuracoes'),
        ('/machine/op', 'operacao'), ('/machine/refugo', 'operacao'),
    ):
        if caminho == prefixo or caminho.startswith(prefixo + '/'):
            return [tela]
    return []


def acao_rota():
    p = request.path.lower()
    if request.method in {'GET', 'HEAD', 'OPTIONS'}:
        return 'exportar' if any(s in p for s in ('export', 'imprimir', 'download', '.csv', '.pdf')) else 'visualizar'
    if any(s in p for s in ('excluir', 'remover', 'delete', 'purge', 'hard-reset', 'archive', 'cleanup')):
        return 'excluir'
    if any(s in p for s in ('aprovar', 'encerrar', 'finalizar', 'ativar', 'cancelar', 'status')):
        return 'aprovar'
    if any(s in p for s in ('editar', 'alterar', 'config', 'reset', 'baseline', 'salvar', '/pin', '/maquinas', 'refugo', 'classificar', '/alias', '/link', '/unlink', '/api-key', '/restore')):
        return 'editar'
    return 'criar'


def instalar_controle_acesso(app):
    if app.extensions.get('indflow_access'):
        return
    app.extensions['indflow_access'] = True
    base = (os.getenv('GESTFLOW_BASE_URL') or 'https://gestflow.nettsan.ia.br').rstrip('/')

    @app.context_processor
    def contexto():
        return {'indflow_permitido': permitido, 'indflow_destino': primeiro_destino}

    @app.before_request
    def verificar():
        if not session.get('gestflow_sso') or request.endpoint == 'static':
            return None
        if request.endpoint in {'admin.logout', 'admin.sso_gestflow'}:
            return None
        info = session.get('indflow_acesso')
        if not isinstance(info, dict):
            session.clear()
            return redirect(base + '/indflow')
        senha_ate = float(info.get('senha_ate') or 0)
        if senha_ate and time.time() >= senha_ate:
            session.clear()
            return redirect(base + '/alterar-senha-obrigatoria')
        # Reconsulta no servidor para revogação, mudança de senha e novas permissões.
        # Uma falha não mantém acesso usando permissões antigas.
        if time.time() - float(session.get('indflow_acesso_verificado') or 0) >= 20:
            secret = (os.getenv('GESTFLOW_INDFLOW_SSO_SECRET') or '').strip()
            if len(secret) < 32:
                return Response('Integração de acesso indisponível.', status=503)
            token = URLSafeTimedSerializer(secret, salt='indflow-verificar-v1').dumps({
                'empresa_id': session['gestflow_empresa_id'], 'usuario_id': session['gestflow_usuario_id'],
            })
            req = urllib.request.Request(base + '/integracao/indflow/verificar-acesso', headers={'Authorization': 'Bearer ' + token})
            try:
                with urllib.request.urlopen(req, timeout=4) as response:
                    atual = json.loads(response.read(65536))
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403}:
                    session.clear()
                    return redirect(base + '/login')
                return Response('Não foi possível validar o acesso. Tente novamente.', status=503)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                return Response('Não foi possível validar o acesso. Tente novamente.', status=503)
            if not atual.get('permitido') or atual.get('sessao_versao') != info.get('sessao_versao'):
                session.clear()
                return redirect(base + '/login')
            session['indflow_acesso'] = info = atual
            session['indflow_acesso_verificado'] = time.time()
            session['role'] = role_acesso(atual)
            if atual.get('senha_ate') and time.time() >= float(atual['senha_ate']):
                session.clear()
                return redirect(base + '/alterar-senha-obrigatoria')
        if request.path == '/' and not permitido('dashboard'):
            destino = primeiro_destino()
            return redirect(destino) if destino else Response('Nenhuma tela do IndFlow foi liberada.', status=403)
        telas = telas_rota(request.path)
        acao = acao_rota()
        if not any(permitido(tela) and permitido(tela, acao) for tela in telas):
            return jsonify(ok=False, error='Acesso não autorizado a esta tela ou ação.'), 403
        return None
