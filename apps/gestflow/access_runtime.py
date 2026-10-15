# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\access_runtime.py
# Último recode: 2026-10-15 16:18 (America/Bahia)
# Motivo: Transmitir o nome fantasia da empresa cadastrada ao cabeçalho do IndFlow.

import json
import secrets
import string
import time
from datetime import datetime, timedelta, timezone
from flask import request, session, redirect, render_template, jsonify, Response
from itsdangerous import URLSafeTimedSerializer, BadData
from werkzeug.security import generate_password_hash, check_password_hash

TELAS = [
    ('dashboard', 'Dashboard / Painel Industrial', '/'),
    ('operacao', 'Tela Operacional', '/operacao/'),
    ('historico', 'Histórico de Produção', '/producao/historico'),
    ('paradas', 'Paradas', '/paradas/'),
    ('indicadores', 'Indicadores', '/indicadores/'),
    ('utilidades', 'Utilidades', '/utilidades/'),
    ('manutencao', 'Manutenção', '/manutencao/'),
    ('ativos', 'Ativos', '/ativos/'),
    ('operadores', 'Operadores', '/operacao/operadores'),
    ('devices', 'Dispositivos', '/devices/'),
    ('configuracoes', 'Configurações / Administração', '/admin/'),
]
ACOES = {'visualizar', 'criar', 'editar', 'excluir', 'aprovar', 'exportar'}

def prazo_timestamp(valor):
    if not valor:
        return 0
    data = datetime.fromisoformat(valor)
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return data.timestamp()


def instalar_controle_acesso(rt):
    app = rt.app
    if app.extensions.get('gestflow_access'):
        return
    app.extensions['gestflow_access'] = True
    with rt.conectar_db() as conn:
        existentes = {r['name'] for r in conn.execute('PRAGMA table_info(usuarios)')}
        for nome, tipo in {
            'acesso_sistema': "TEXT NOT NULL DEFAULT 'gestflow'",
            'indflow_permissoes_json': 'TEXT',
            'senha_provisoria_ate': 'TEXT',
        }.items():
            if nome not in existentes:
                conn.execute(f'ALTER TABLE usuarios ADD COLUMN {nome} {tipo}')
        conn.commit()

    def usuario_extra(uid=None):
        with rt.conectar_db() as conn:
            row = conn.execute('SELECT * FROM usuarios WHERE id = ?', (uid or session.get('usuario_id') or 0,)).fetchone()
        return dict(row) if row else {}

    def permissoes_indflow(u):
        if u.get('perfil') in {'administrador', 'super_admin'}:
            return {t[0]: sorted(ACOES) for t in TELAS}
        valor = u.get('indflow_permissoes_json')
        if valor is None:
            # Preserva consulta das contas anteriores, sem promover o primeiro visitante a administrador.
            return {t[0]: ['visualizar', 'exportar'] for t in TELAS[:8]}
        try:
            bruto = json.loads(valor)
            return {t[0]: sorted(set(bruto.get(t[0], [])) & ACOES) for t in TELAS}
        except (ValueError, TypeError, AttributeError):
            return {}

    def destino(u):
        return '/indflow' if u.get('acesso_sistema') == 'indflow' else '/'

    def estado(u):
        if not u:
            return None
        with rt.conectar_db() as conn:
            empresa = conn.execute('SELECT status, nome_fantasia FROM empresas WHERE id=?', (u['empresa_id'],)).fetchone()
        if u.get('status') != 'ativo' or not empresa or empresa['status'] not in {'ativo', 'trial'}:
            return None
        with app.test_request_context():
            session['usuario_id'] = u['id']
            session['empresa_id'] = u['empresa_id']
            session['usuario_perfil'] = u['perfil']
            session['usuario_permissoes_json'] = u.get('permissoes_json') or ''
            permitido = rt.modulo_empresa_ativo('indflow') and rt.usuario_tem_permissao('indflow', 'visualizar', u)
        return {
            'permitido': bool(permitido), 'telas': permissoes_indflow(u),
            'empresa_nome': str(empresa['nome_fantasia'] or '').strip(),
            'senha_ate': prazo_timestamp(u.get('senha_provisoria_ate')),
            'sessao_versao': int(u.get('sessao_versao') or 1),
            'somente_indflow': u.get('acesso_sistema') == 'indflow',
        }

    original_form = rt.montar_usuario_configuracoes_formulario
    def formulario():
        dados = original_form()
        dados['acesso_sistema'] = request.form.get('acesso_sistema', 'gestflow')
        permissoes = {}
        for valor in request.form.getlist('indflow_permissoes'):
            tela, _, acao = valor.partition(':')
            if tela in {t[0] for t in TELAS} and acao in ACOES:
                permissoes.setdefault(tela, []).append(acao)
        dados['indflow_permissoes_json'] = json.dumps(permissoes)
        return dados
    rt.montar_usuario_configuracoes_formulario = formulario

    original_validar = rt.validar_usuario_configuracoes_formulario
    def validar(dados, usuario_id=None):
        erro = original_validar(dados, usuario_id)
        if erro:
            return erro
        if dados['acesso_sistema'] not in {'gestflow', 'indflow'}:
            return 'Selecione um acesso válido.'
        if dados['acesso_sistema'] == 'indflow':
            if dados['perfil'] in {'administrador', 'super_admin'}:
                return 'Para limitar o acesso ao IndFlow, escolha um perfil sem acesso administrativo total.'
            if 'indflow:visualizar' not in request.form.getlist('permissoes'):
                return 'Libere Visualizar no item IndFlow.'
            if not any('visualizar' in a for a in json.loads(dados['indflow_permissoes_json']).values()):
                return 'Libere pelo menos uma tela do IndFlow para visualizar.'
        if dados['perfil'] not in {'administrador', 'super_admin'} and 'indflow:visualizar' in request.form.getlist('permissoes'):
            if not any('visualizar' in a for a in json.loads(dados['indflow_permissoes_json']).values()):
                return 'Marque Visualizar em pelo menos um subitem do IndFlow.'
        if usuario_id is None:
            if not dados.get('senha'):
                return 'Clique em Gerar senha antes de cadastrar.'
            return rt.validar_senha_forte(dados['senha'])
        return ''
    rt.validar_usuario_configuracoes_formulario = validar

    def salvar_extra(uid, dados, provisoria=False):
        with rt.conectar_db() as conn:
            conn.execute('UPDATE usuarios SET acesso_sistema=?, indflow_permissoes_json=? WHERE id=? AND empresa_id=?',
                         (dados['acesso_sistema'], dados['indflow_permissoes_json'], uid, rt.empresa_logada_id()))
            if provisoria:
                prazo = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
                conn.execute('UPDATE usuarios SET senha_hash=?, senha_provisoria_ate=? WHERE id=? AND empresa_id=?',
                             (generate_password_hash(dados['senha']), prazo, uid, rt.empresa_logada_id()))
            conn.commit()

    original_criar = rt.criar_usuario_configuracoes_db
    def criar(dados, permissoes_json):
        uid = original_criar(dados, permissoes_json)
        salvar_extra(uid, dados, provisoria=True)
        return uid
    rt.criar_usuario_configuracoes_db = criar
    original_atualizar = rt.atualizar_usuario_configuracoes_db
    def atualizar(uid, dados, permissoes_json):
        original_atualizar(uid, dados, permissoes_json)
        salvar_extra(uid, dados, provisoria=bool(dados.get('senha')))
    rt.atualizar_usuario_configuracoes_db = atualizar
    original_redefinir = rt.redefinir_senha_usuario_configuracoes_db
    def redefinir(uid, senha):
        original_redefinir(uid, senha)
        with rt.conectar_db() as conn:
            prazo = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
            conn.execute('UPDATE usuarios SET senha_provisoria_ate=? WHERE id=? AND empresa_id=?', (prazo, uid, rt.empresa_logada_id()))
            conn.commit()
    rt.redefinir_senha_usuario_configuracoes_db = redefinir

    def enviar_convite(uid, dados):
        base = (rt.os.getenv('GESTFLOW_BASE_URL') or getattr(rt.config, 'GESTFLOW_BASE_URL', '') or request.url_root).rstrip('/')
        corpo = (f"Olá, {dados['nome']}.\n\nSeu acesso foi cadastrado.\n"
                 f"Acesso: {base}/login\nE-mail: {dados['email']}\nSenha provisória: {dados['senha']}\n\n"
                 'Após 72 horas do cadastro, a troca de senha será obrigatória para continuar utilizando o sistema.\n'
                 'Não compartilhe sua senha.')
        return rt.enviar_email_zoho(dados['email'], 'Seu acesso ao GestFlow / IndFlow', corpo)
    rt.enviar_convite_novo_usuario = enviar_convite

    @app.context_processor
    def contexto_acesso():
        u = {}
        if request.endpoint == 'editar_usuario_configuracoes':
            u = usuario_extra((request.view_args or {}).get('usuario_id'))
        if request.method == 'POST' and request.endpoint in {'novo_usuario_configuracoes', 'editar_usuario_configuracoes'}:
            scope = request.form.get('acesso_sistema', 'gestflow')
            selecionadas = set(request.form.getlist('indflow_permissoes'))
        else:
            scope = u.get('acesso_sistema', 'gestflow')
            grants = permissoes_indflow(u) if u else {}
            selecionadas = {f'{t}:{a}' for t, acoes in grants.items() for a in acoes}
        csrf = session.get('access_csrf')
        if not csrf:
            csrf = secrets.token_urlsafe(32)
            session['access_csrf'] = csrf
        return {'indflow_telas': TELAS, 'indflow_selecionadas': selecionadas,
                'acesso_sistema_atual': scope, 'access_csrf': csrf}

    def senha_obrigatoria():
        u = usuario_extra()
        erro = ''
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf', ''), session.get('access_csrf', 'invalid')):
                return Response('Formulário inválido. Atualize a página.', status=403)
            nova = request.form.get('nova_senha', '')
            erro = rt.validar_senha_forte(nova)
            if not erro and nova != request.form.get('confirmar_senha', ''):
                erro = 'A confirmação da senha não confere.'
            if not erro and check_password_hash(u['senha_hash'], nova):
                erro = 'A nova senha precisa ser diferente da senha provisória.'
            if not erro:
                with rt.conectar_db() as conn:
                    conn.execute('UPDATE usuarios SET senha_hash=?, senha_provisoria_ate=NULL, sessao_versao=COALESCE(sessao_versao,1)+1 WHERE id=?',
                                 (generate_password_hash(nova), u['id']))
                    conn.execute("UPDATE usuario_recuperacao_senha SET usado_em=? WHERE usuario_id=? AND COALESCE(usado_em,'')=''",
                                 (rt.agora_empresa().isoformat(timespec='seconds'), u['id']))
                    conn.commit()
                session['usuario_sessao_versao'] = int(u.get('sessao_versao') or 1) + 1
                return redirect(destino(u))
        return render_template('senha_obrigatoria.html', erro=erro)
    app.add_url_rule('/alterar-senha-obrigatoria', 'senha_obrigatoria', senha_obrigatoria, methods=['GET', 'POST'])

    def gerar_senha():
        if not rt.usuario_logado_eh_administrador_empresa():
            return jsonify(erro='Acesso negado.'), 403
        if not secrets.compare_digest(request.form.get('csrf', ''), session.get('access_csrf', 'invalid')):
            return jsonify(erro='Atualize a página.'), 403
        alfabeto = string.ascii_letters + string.digits + '!@#$%&*?'
        while True:
            senha = ''.join(secrets.choice(alfabeto) for _ in range(16))
            if not rt.validar_senha_forte(senha):
                return jsonify(senha=senha)
    app.add_url_rule('/configuracoes/usuarios/gerar-senha', 'gerar_senha', gerar_senha, methods=['POST'])

    def verificar_indflow():
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        try:
            dados = URLSafeTimedSerializer(rt._segredo_sso_indflow(), salt='indflow-verificar-v1').loads(token, max_age=30)
            u = usuario_extra(int(dados['usuario_id']))
            if not u or int(u['empresa_id']) != int(dados['empresa_id']):
                return jsonify(erro='Acesso negado.'), 403
            info = estado(u)
            if not info or not info['permitido']:
                return jsonify(erro='Acesso revogado.'), 403
            return jsonify(info)
        except (BadData, ValueError, KeyError, TypeError, RuntimeError):
            return jsonify(erro='Acesso negado.'), 403
    app.add_url_rule('/integracao/indflow/verificar-acesso', 'verificar_indflow', verificar_indflow, methods=['GET'])

    original_token = rt.gerar_token_sso_indflow
    def token_sso():
        serializer = URLSafeTimedSerializer(rt._segredo_sso_indflow(), salt=rt.GESTFLOW_INDFLOW_SSO_SALT)
        payload = serializer.loads(original_token())
        info = estado(usuario_extra())
        if not info or not info['permitido']:
            raise RuntimeError('Acesso ao IndFlow não autorizado')
        payload['acesso'] = info
        return serializer.dumps(payload)
    rt.gerar_token_sso_indflow = token_sso

    def controle():
        if request.endpoint == 'verificar_indflow':
            return verificar_indflow()
        if not session.get('usuario_id') or request.endpoint in {'static', 'sair'}:
            return None
        valido, mensagem = rt.revalidar_sessao_usuario()
        if not valido:
            return redirect('/login')
        u = usuario_extra()
        vencida = bool(u.get('senha_provisoria_ate') and time.time() >= prazo_timestamp(u['senha_provisoria_ate']))
        if vencida:
            if request.endpoint == 'senha_obrigatoria':
                return senha_obrigatoria()
            return redirect('/alterar-senha-obrigatoria')
        if request.endpoint == 'senha_obrigatoria':
            return senha_obrigatoria()
        if request.endpoint == 'gerar_senha':
            return gerar_senha()
        if u.get('acesso_sistema') == 'indflow':
            if request.path in {'/', '/login', '/onboarding'}:
                return redirect('/indflow')
            if request.path != '/indflow':
                return Response('Acesso permitido somente ao IndFlow.', status=403)
            if not rt.modulo_empresa_ativo('indflow') or not rt.usuario_tem_permissao('indflow', 'visualizar', u):
                return Response('Acesso ao IndFlow não autorizado.', status=403)
            return rt.abrir_indflow()
        return None
    app.before_request_funcs.setdefault(None, []).insert(0, controle)

    @app.after_request
    def resposta_acesso(response):
        if request.endpoint in {'gerar_senha', 'senha_obrigatoria', 'verificar_indflow', 'novo_usuario_configuracoes'}:
            response.headers['Cache-Control'] = 'no-store'
        return response
