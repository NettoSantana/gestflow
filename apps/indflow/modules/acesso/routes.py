# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\modules\acesso\routes.py
# Último recode: 2026-10-26 11:31 (America/Bahia)
# Motivo: Receber crachás coletados pelo mestre e vincular depois, sem liberar máquinas.
"""API preparada para firmware ESP32 futuro: não altera o firmware já instalado.

Fluxo:
  painel inicia captura -> ESP faz polling autenticado -> envia UID -> recebe instrução
  -> grava/valida localmente -> confirma -> painel declara sucesso.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, render_template, request, session

from modules.admin.routes import admin_required, login_required
from modules.db_indflow import get_db
# Mesma fonte de máquinas que alimenta a tela Devices e o Painel Industrial.
# _machine_rows inclui máquinas cadastradas sem dispositivo e exclui arquivadas.
from modules.devices.routes import _machine_rows

acesso_bp = Blueprint('acesso', __name__, template_folder='templates')

_MASTER_UID = '00E6242D'  # Nunca cadastrar o cartão mestre fixo como funcionário.
_CAPTURE_TIMEOUT_SECONDS = 45
_ACK_TIMEOUT_SECONDS = 90


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec='seconds')


def _uid(value):
    text = re.sub(r'[^0-9A-F]', '', str(value or '').upper())
    if not 6 <= len(text) <= 8 or not re.fullmatch(r'[0-9A-F]+', text):
        raise ValueError('Crachá inválido. É necessário UID hexadecimal completo.')
    # Wiegand-26 é apresentado no firmware com oito caracteres e zeros à esquerda.
    return text.zfill(8)


def _cliente():
    return str(session.get('cliente_id') or '').strip()


def _csrf():
    value = session.get('acesso_csrf')
    if not value:
        value = secrets.token_urlsafe(32)
        session['acesso_csrf'] = value
    return value


def _check_csrf():
    return hmac.compare_digest(str(request.headers.get('X-CSRF-Token') or ''), str(session.get('acesso_csrf') or 'invalid'))


def _error(message, status=400):
    return jsonify(ok=False, error=message), status


def _payload():
    p = request.get_json(silent=True)
    if not isinstance(p, dict):
        raise ValueError('Envie JSON válido.')
    return p


def init_access_db():
    """Tabelas novas, sem alterações ou backfill das tabelas de produção."""
    db = get_db()
    try:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS acesso_funcionarios (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            matricula TEXT NOT NULL DEFAULT '',
            setor TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ativo',
            cracha_uid TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_acesso_funcionarios_empresa ON acesso_funcionarios(cliente_id, nome);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_acesso_cracha_empresa ON acesso_funcionarios(cliente_id, cracha_uid)
            WHERE cracha_uid IS NOT NULL;
        CREATE TABLE IF NOT EXISTS acesso_leitores (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            codigo TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ativo',
            last_seen TEXT,
            firmware TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(cliente_id, codigo)
        );
        CREATE INDEX IF NOT EXISTS ix_acesso_leitores_empresa ON acesso_leitores(cliente_id, machine_id);
        CREATE TABLE IF NOT EXISTS acesso_comandos (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            leitor_id TEXT NOT NULL,
            funcionario_id TEXT NOT NULL,
            operacao TEXT NOT NULL,
            cracha_uid TEXT,
            estado TEXT NOT NULL,
            erro TEXT NOT NULL DEFAULT '',
            criado_em TEXT NOT NULL,
            expira_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_acesso_comandos_leitor ON acesso_comandos(leitor_id, estado);
        CREATE TABLE IF NOT EXISTS acesso_permissoes (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            funcionario_id TEXT NOT NULL,
            leitor_id TEXT NOT NULL,
            situacao TEXT NOT NULL,
            atualizado_em TEXT NOT NULL,
            UNIQUE(cliente_id, funcionario_id, leitor_id)
        );
        CREATE TABLE IF NOT EXISTS acesso_crachas_coletados (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            leitor_id TEXT NOT NULL,
            cracha_uid TEXT NOT NULL,
            coletado_em TEXT NOT NULL,
            UNIQUE(cliente_id, cracha_uid)
        );
        CREATE TABLE IF NOT EXISTS acesso_eventos (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            leitor_id TEXT NOT NULL,
            evento_id TEXT NOT NULL,
            evento TEXT NOT NULL,
            cracha_uid TEXT,
            funcionario_id TEXT,
            status TEXT NOT NULL DEFAULT '',
            epoch INTEGER,
            fonte_hora TEXT NOT NULL DEFAULT 'desconhecida',
            observacao TEXT NOT NULL DEFAULT '',
            recebido_em TEXT NOT NULL,
            UNIQUE(leitor_id, evento_id)
        );
        CREATE INDEX IF NOT EXISTS ix_acesso_eventos_empresa ON acesso_eventos(cliente_id, recebido_em);
        ''')
        db.commit()
    finally:
        db.close()


def _expire(db, cliente_id=None, reader_id=None):
    clauses = ["estado IN ('aguardando_leitura','aguardando_confirmacao','pendente_dispositivo')", 'expira_em < ?']
    args = [_iso()]
    if cliente_id:
        clauses.append('cliente_id=?')
        args.append(cliente_id)
    if reader_id:
        clauses.append('leitor_id=?')
        args.append(reader_id)
    db.execute("UPDATE acesso_comandos SET estado='expirado', erro='Prazo esgotado', atualizado_em=? WHERE " + ' AND '.join(clauses), (_iso(), *args))


def _require_write():
    if not _check_csrf():
        return _error('Sessão expirada ou CSRF inválido. Atualize a página.', 403)
    if not _cliente():
        return _error('Empresa não identificada.', 403)
    return None


def _reader_from_token(db):
    raw = request.headers.get('Authorization', '')
    if not raw.startswith('Bearer '):
        return None
    token = raw[7:].strip()
    if not (32 <= len(token) <= 256):
        return None
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    row = db.execute("""SELECT l.* FROM acesso_leitores l
        JOIN clientes c ON c.id=l.cliente_id
        WHERE l.token_hash=? AND l.status='ativo' AND c.status='active'""", (digest,)).fetchone()
    return row


def _device_auth(db):
    reader = _reader_from_token(db)
    if not reader:
        return None
    # Somente o leitor autorizado pode operar seus próprios comandos.
    db.execute('UPDATE acesso_leitores SET last_seen=?, firmware=? WHERE id=?',
               (_iso(), str(request.headers.get('X-Firmware-Version') or '')[:100], reader['id']))
    return reader


def _serialize_cmd(cmd, person):
    result = dict(id=cmd['id'], operacao=cmd['operacao'], estado=cmd['estado'], expira_em=cmd['expira_em'])
    if cmd['operacao'] == 'capturar':
        result['acao'] = 'aguardar_cracha' if cmd['estado'] == 'aguardando_leitura' else 'aguardar_confirmacao'
    elif cmd['operacao'] == 'permitir':
        result.update(acao='gravar_cracha', cracha_uid=cmd['cracha_uid'])
    elif cmd['operacao'] == 'revogar':
        result.update(acao='remover_cracha', cracha_uid=cmd['cracha_uid'])
    if person:
        result['funcionario_id'] = person['id']
    return result


@acesso_bp.get('/')
@login_required
def home():
    cid = _cliente()
    if not cid:
        return 'Empresa não identificada', 403
    db = get_db()
    try:
        _expire(db, cid)
        people = [dict(r) for r in db.execute('SELECT * FROM acesso_funcionarios WHERE cliente_id=? ORDER BY nome COLLATE NOCASE', (cid,))]
        readers = [dict(r) for r in db.execute('SELECT * FROM acesso_leitores WHERE cliente_id=? ORDER BY machine_id,codigo', (cid,))]
        grants = [dict(r) for r in db.execute('SELECT funcionario_id,leitor_id,situacao FROM acesso_permissoes WHERE cliente_id=?', (cid,))]
        events = [dict(r) for r in db.execute('''SELECT e.*,l.machine_id,l.codigo,f.nome AS funcionario_nome
          FROM acesso_eventos e JOIN acesso_leitores l ON l.id=e.leitor_id
          LEFT JOIN acesso_funcionarios f ON f.id=e.funcionario_id AND f.cliente_id=e.cliente_id
          WHERE e.cliente_id=? ORDER BY e.recebido_em DESC LIMIT 35''', (cid,))]
        for event in events:
            epoch = event.get('epoch')
            try:
                event['horario_local'] = datetime.fromtimestamp(int(epoch), timezone.utc).astimezone(
                    ZoneInfo('America/Bahia')).strftime('%d/%m/%Y %H:%M:%S') if epoch else 'Não confirmado'
            except (ValueError, TypeError, OverflowError, OSError):
                event['horario_local'] = 'Não confirmado'
        pending = [dict(r) for r in db.execute("""SELECT c.id,c.operacao,c.estado,c.criado_em,c.expira_em,
          c.funcionario_id,c.leitor_id,f.nome AS funcionario_nome,l.machine_id,l.codigo
          FROM acesso_comandos c JOIN acesso_leitores l ON l.id=c.leitor_id AND l.cliente_id=c.cliente_id
          LEFT JOIN acesso_funcionarios f ON f.id=c.funcionario_id AND f.cliente_id=c.cliente_id
          WHERE c.cliente_id=? AND c.estado IN ('aguardando_leitura','aguardando_confirmacao','pendente_dispositivo')
          ORDER BY c.criado_em""", (cid,))]
        collected = [dict(r) for r in db.execute("""SELECT c.*,l.machine_id,l.codigo
          FROM acesso_crachas_coletados c JOIN acesso_leitores l ON l.id=c.leitor_id AND l.cliente_id=c.cliente_id
          WHERE c.cliente_id=? AND NOT EXISTS (SELECT 1 FROM acesso_funcionarios f
            WHERE f.cliente_id=c.cliente_id AND f.cracha_uid=c.cracha_uid)
          ORDER BY c.coletado_em DESC""", (cid,))]
        machines = [m['machine_id'] for m in _machine_rows(db, cid)]
        db.commit()
    finally:
        db.close()
    return render_template('acesso_home.html', people=people, readers=readers,
                           grants=grants, events=events, machines=machines, pending=pending, collected=collected,
                           csrf=_csrf(), can_write=str(session.get('role') or '').lower() in ('admin','superadmin'))


@acesso_bp.post('/api/funcionarios')
@admin_required
def create_person():
    fail = _require_write()
    if fail: return fail
    try:
        p = _payload()
        nome = str(p.get('nome') or '').strip()
        matricula = str(p.get('matricula') or '').strip()
        setor = str(p.get('setor') or '').strip()
        if not 2 <= len(nome) <= 120 or len(matricula) > 40 or len(setor) > 80:
            raise ValueError('Confira nome (2 a 120 caracteres), matrícula e setor.')
        cid = _cliente()
        person_id = str(uuid.uuid4())
        db = get_db()
        try:
            db.execute('INSERT INTO acesso_funcionarios (id,cliente_id,nome,matricula,setor,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                       (person_id,cid,nome,matricula,setor,_iso(),_iso()))
            db.commit()
        finally: db.close()
        return jsonify(ok=True, funcionario_id=person_id, mensagem='Funcionário criado. Vincule o crachá no leitor.')
    except ValueError as exc: return _error(str(exc))


@acesso_bp.post('/api/funcionarios/<funcionario_id>/situacao')
@admin_required
def change_person(funcionario_id):
    fail = _require_write()
    if fail: return fail
    try:
        p = _payload()
        situacao = str(p.get('status') or '')
        if situacao not in ('ativo', 'inativo'):
            raise ValueError('Situação inválida.')
        cid = _cliente()
        db = get_db()
        try:
            person = db.execute('SELECT id FROM acesso_funcionarios WHERE id=? AND cliente_id=?',(funcionario_id,cid)).fetchone()
            if not person: return _error('Funcionário não encontrado.',404)
            if situacao == 'inativo':
                # Não prometer revogação local instantânea: primeiro agendar remoções.
                rows = db.execute("SELECT leitor_id FROM acesso_permissoes WHERE cliente_id=? AND funcionario_id=? AND situacao IN ('ativo','pendente')",(cid,funcionario_id)).fetchall()
                card = db.execute('SELECT cracha_uid FROM acesso_funcionarios WHERE id=?',(funcionario_id,)).fetchone()['cracha_uid']
                for r in rows:
                    _queue(db,cid,r['leitor_id'],funcionario_id,'revogar',card)
            db.execute('UPDATE acesso_funcionarios SET status=?,updated_at=? WHERE id=? AND cliente_id=?', (situacao,_iso(),funcionario_id,cid))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:db.close()
        return jsonify(ok=True,mensagem='Situação atualizada. Revogações aguardam confirmação dos dispositivos.')
    except ValueError as exc: return _error(str(exc), 409)


def _queue(db,cid,reader_id,person_id,operation,uid=None):
    active=db.execute("SELECT id FROM acesso_comandos WHERE leitor_id=? AND estado IN ('aguardando_leitura','aguardando_confirmacao','pendente_dispositivo')",(reader_id,)).fetchone()
    if active: raise ValueError('Já existe uma operação pendente neste leitor.')
    command_id=str(uuid.uuid4())
    state='aguardando_leitura' if operation=='capturar' else 'pendente_dispositivo'
    ttl=_CAPTURE_TIMEOUT_SECONDS if operation=='capturar' else 7 * 24 * 3600
    db.execute('''INSERT INTO acesso_comandos (id,cliente_id,leitor_id,funcionario_id,operacao,cracha_uid,estado,criado_em,expira_em,atualizado_em)
        VALUES (?,?,?,?,?,?,?,?,?,?)''', (command_id,cid,reader_id,person_id,operation,uid,state,_iso(),_iso(_now()+timedelta(seconds=ttl)),_iso()))
    return command_id


@acesso_bp.post('/api/leitores')
@admin_required
def create_reader():
    fail = _require_write()
    if fail:return fail
    try:
        p=_payload()
        code=str(p.get('codigo') or '').strip().upper()
        mid=str(p.get('machine_id') or '').strip().lower()
        if not re.fullmatch(r'[A-Z0-9_\-]{4,48}',code): raise ValueError('Identificador do leitor inválido.')
        cid=_cliente()
        # Não exigir sensor/ESP de produção: o leitor de crachá é independente.
        with_db = get_db()
        try:
            allowed = {str(m['machine_id']).lower() for m in _machine_rows(with_db, cid)}
        finally:
            with_db.close()
        if mid not in allowed: raise ValueError('Escolha uma máquina cadastrada nesta empresa.')
        token=secrets.token_urlsafe(36)
        db=get_db()
        try:
            db.execute('INSERT INTO acesso_leitores (id,cliente_id,codigo,machine_id,token_hash,created_at) VALUES (?,?,?,?,?,?)',
                      (str(uuid.uuid4()),cid,code,mid,hashlib.sha256(token.encode()).hexdigest(),_iso()))
            db.commit()
        except sqlite3.IntegrityError: return _error('Esse identificador de leitor já existe nesta empresa.',409)
        finally:db.close()
        return jsonify(ok=True,token=token,mensagem='Leitor cadastrado. Copie a chave agora; ela não será exibida novamente.')
    except ValueError as exc:return _error(str(exc))


@acesso_bp.post('/api/capturas')
@admin_required
def start_capture():
    fail=_require_write()
    if fail:return fail
    try:
        p=_payload();cid=_cliente()
        person_id=str(p.get('funcionario_id') or '').strip()
        reader_id=str(p.get('leitor_id') or '').strip()
        db=get_db()
        try:
            db.execute('BEGIN IMMEDIATE');_expire(db,cid,reader_id)
            person=db.execute("SELECT * FROM acesso_funcionarios WHERE id=? AND cliente_id=? AND status='ativo'",(person_id,cid)).fetchone()
            reader=db.execute("SELECT * FROM acesso_leitores WHERE id=? AND cliente_id=? AND status='ativo'",(reader_id,cid)).fetchone()
            if not person or not reader: raise ValueError('Funcionário ou leitor não encontrado/ativo nesta empresa.')
            if person['cracha_uid']: raise ValueError('Funcionário já tem crachá. Use a gestão de permissões para novas máquinas.')
            cmd_id=_queue(db,cid,reader_id,person_id,'capturar')
            db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
        return jsonify(ok=True,comando_id=cmd_id,estado='aguardando_leitura',mensagem='Aproxime o crachá do leitor em até 45 segundos.')
    except ValueError as exc:return _error(str(exc),409)


@acesso_bp.post('/api/permissoes')
@admin_required
def permissions():
    fail=_require_write()
    if fail:return fail
    try:
        p=_payload();cid=_cliente()
        person_id=str(p.get('funcionario_id') or '');reader_id=str(p.get('leitor_id') or '')
        action=str(p.get('acao') or '')
        if action not in ('permitir','revogar'):raise ValueError('Ação inválida.')
        db=get_db()
        try:
            db.execute('BEGIN IMMEDIATE');_expire(db,cid,reader_id)
            person=db.execute('SELECT * FROM acesso_funcionarios WHERE id=? AND cliente_id=?',(person_id,cid)).fetchone()
            reader=db.execute("SELECT * FROM acesso_leitores WHERE id=? AND cliente_id=? AND status='ativo'",(reader_id,cid)).fetchone()
            if not person or not reader or not person['cracha_uid']:raise ValueError('Cadastre primeiro o crachá do funcionário e um leitor ativo.')
            if action=='permitir' and person['status']!='ativo':raise ValueError('Funcionário inativo.')
            cmd_id=_queue(db,cid,reader_id,person_id,action,person['cracha_uid']);db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
        return jsonify(ok=True,comando_id=cmd_id,mensagem='Solicitação enviada à fila. Aguarde confirmação do ESP32.')
    except ValueError as exc:return _error(str(exc),409)


@acesso_bp.get('/api/comandos/<comando_id>')
@login_required
def command_status(comando_id):
    cid=_cliente()
    if not cid:return _error('Empresa não identificada.',403)
    db=get_db()
    try:
        _expire(db,cid)
        row=db.execute('SELECT * FROM acesso_comandos WHERE id=? AND cliente_id=?',(comando_id,cid)).fetchone()
        db.commit()
    finally:db.close()
    if not row:return _error('Solicitação não encontrada.',404)
    return jsonify(ok=True,estado=row['estado'],erro=row['erro'],cracha_uid=row['cracha_uid'] if row['estado']=='confirmado' else None,
                   mensagem='Funcionário cadastrado com sucesso!' if row['operacao']=='capturar' and row['estado']=='confirmado' else '')


@acesso_bp.post('/api/comandos/<comando_id>/cancelar')
@admin_required
def cancel_cmd(comando_id):
    fail=_require_write()
    if fail:return fail
    cid=_cliente();db=get_db()
    try:
        db.execute("UPDATE acesso_comandos SET estado='cancelado',atualizado_em=? WHERE id=? AND cliente_id=? AND estado IN ('aguardando_leitura','aguardando_confirmacao','pendente_dispositivo')",(_iso(),comando_id,cid))
        db.commit()
    finally:db.close()
    return jsonify(ok=True)


@acesso_bp.get('/iot/comandos')
def device_poll():
    db=get_db()
    try:
        reader=_device_auth(db)
        if not reader:return _error('Credencial do dispositivo inválida.',401)
        _expire(db,reader['cliente_id'],reader['id'])
        cmd=db.execute("SELECT * FROM acesso_comandos WHERE leitor_id=? AND estado IN ('aguardando_leitura','aguardando_confirmacao','pendente_dispositivo') ORDER BY criado_em LIMIT 1",(reader['id'],)).fetchone()
        person=db.execute('SELECT id FROM acesso_funcionarios WHERE id=? AND cliente_id=?',(cmd['funcionario_id'],reader['cliente_id'])).fetchone() if cmd else None
        db.commit()
        return jsonify(ok=True,comando=_serialize_cmd(cmd,person) if cmd else None)
    finally:db.close()


@acesso_bp.post('/iot/captura')
def device_scan():
    db=get_db()
    try:
        reader=_device_auth(db)
        if not reader:return _error('Credencial do dispositivo inválida.',401)
        try:
            p=_payload();uid=_uid(p.get('cracha_uid'));cmd_id=str(p.get('comando_id') or '')
            if uid.lstrip('0') == _MASTER_UID.lstrip('0'):raise ValueError('Crachá mestre reservado; não pode ser vinculado.')
            if int(p.get('bits') or 0) != 26:raise ValueError('Somente leitura Wiegand 26 válida é aceita.')
        except (ValueError,TypeError):return _error('Crachá inválido, mestre ou leitura incompleta.',400)
        db.commit();db.execute('BEGIN IMMEDIATE');_expire(db,reader['cliente_id'],reader['id'])
        cmd=db.execute("SELECT * FROM acesso_comandos WHERE id=? AND leitor_id=? AND cliente_id=? AND operacao='capturar' AND estado='aguardando_leitura'",(cmd_id,reader['id'],reader['cliente_id'])).fetchone()
        if not cmd:
            db.rollback();return _error('Nenhuma captura ativa para este leitor.',409)
        duplicate=db.execute('SELECT id FROM acesso_funcionarios WHERE cliente_id=? AND cracha_uid=?',(reader['cliente_id'],uid)).fetchone()
        if duplicate:
            db.execute("UPDATE acesso_comandos SET estado='falhou',erro=?,atualizado_em=? WHERE id=?",('Crachá já vinculado a outro funcionário.',_iso(),cmd_id))
            db.commit();return _error('Crachá já cadastrado nesta empresa.',409)
        db.execute("UPDATE acesso_comandos SET estado='aguardando_confirmacao',cracha_uid=?,expira_em=?,atualizado_em=? WHERE id=?",
                   (uid,_iso(_now()+timedelta(seconds=_ACK_TIMEOUT_SECONDS)),_iso(),cmd_id))
        db.commit()
        return jsonify(ok=True,comando_id=cmd_id,acao='gravar_cracha',cracha_uid=uid,
                       aviso='Somente confirme após persistir o crachá no armazenamento local do ESP32.')
    finally:db.close()


@acesso_bp.post('/iot/confirmacao')
def device_ack():
    db=get_db()
    try:
        reader=_device_auth(db)
        if not reader:return _error('Credencial do dispositivo inválida.',401)
        try:
            p=_payload();cmd_id=str(p.get('comando_id') or '');ok=p.get('gravado') is True
            if len(cmd_id)>64:raise ValueError('Identificador inválido.')
        except ValueError as exc:return _error(str(exc))
        db.commit();db.execute('BEGIN IMMEDIATE');_expire(db,reader['cliente_id'],reader['id'])
        cmd=db.execute('SELECT * FROM acesso_comandos WHERE id=? AND leitor_id=? AND cliente_id=?',(cmd_id,reader['id'],reader['cliente_id'])).fetchone()
        if not cmd:
            db.rollback();return _error('Comando não encontrado.',404)
        if cmd['estado']=='confirmado':
            db.commit();return jsonify(ok=True,estado='confirmado')
        expected='aguardando_confirmacao' if cmd['operacao']=='capturar' else 'pendente_dispositivo'
        if cmd['estado']!=expected:
            db.rollback();return _error('Comando expirado ou não está aguardando confirmação.',409)
        if not ok:
            db.execute("UPDATE acesso_comandos SET estado='falhou',erro=?,atualizado_em=? WHERE id=?",
                       (str(p.get('erro') or 'ESP32 não confirmou gravação.')[:250],_iso(),cmd_id));db.commit()
            return jsonify(ok=True,estado='falhou')
        person=db.execute('SELECT * FROM acesso_funcionarios WHERE id=? AND cliente_id=?',(cmd['funcionario_id'],reader['cliente_id'])).fetchone()
        if not person:
            db.rollback();return _error('Funcionário não encontrado.',404)
        try:
            if cmd['operacao']=='capturar':
                if person['cracha_uid'] and person['cracha_uid']!=cmd['cracha_uid']:
                    raise ValueError('Funcionário já possui outro crachá.')
                db.execute('UPDATE acesso_funcionarios SET cracha_uid=?,updated_at=? WHERE id=? AND cliente_id=?',
                           (cmd['cracha_uid'],_iso(),person['id'],reader['cliente_id']))
            situacao='revogada' if cmd['operacao']=='revogar' else 'ativa'
            db.execute('''INSERT INTO acesso_permissoes (id,cliente_id,funcionario_id,leitor_id,situacao,atualizado_em)
                VALUES (?,?,?,?,?,?) ON CONFLICT(cliente_id,funcionario_id,leitor_id)
                DO UPDATE SET situacao=excluded.situacao, atualizado_em=excluded.atualizado_em''',
                (str(uuid.uuid4()),reader['cliente_id'],person['id'],reader['id'],situacao,_iso()))
            db.execute("UPDATE acesso_comandos SET estado='confirmado',atualizado_em=? WHERE id=?",(_iso(),cmd_id))
            db.commit()
        except (sqlite3.IntegrityError,ValueError):
            db.rollback();return _error('Conflito: crachá já vinculado ou funcionário mudou.',409)
        return jsonify(ok=True,estado='confirmado',mensagem='Gravação no ESP32 confirmada.')
    finally:db.close()


@acesso_bp.post('/iot/eventos')
def device_event():
    db=get_db()
    try:
        reader=_device_auth(db)
        if not reader:return _error('Credencial do dispositivo inválida.',401)
        try:
            p=_payload();event_id=str(p.get('evento_id') or '').strip()
            event_type=str(p.get('evento') or '').strip().upper()
            if not 8<=len(event_id)<=90 or not re.fullmatch('[A-Z0-9_]{3,48}',event_type):raise ValueError('Evento inválido.')
            card=_uid(p['cracha_uid']) if p.get('cracha_uid') else None
            epoch=p.get('epoch')
            if epoch is not None:
                epoch=int(epoch)
                if not 1700000000<=epoch<=4102444800:raise ValueError('Epoch inválido.')
            source=str(p.get('fonte_hora') or 'desconhecida')[:40]
            if source not in ('ntp','rtc','ntp_recuperado','estimada','desconhecida'):source='desconhecida'
            status=str(p.get('status') or '')[:40]
            obs=str(p.get('observacao') or '')[:400]
        except (ValueError,TypeError,KeyError) as exc:return _error(str(exc))
        person=db.execute('SELECT id FROM acesso_funcionarios WHERE cliente_id=? AND cracha_uid=?',(reader['cliente_id'],card)).fetchone() if card else None
        cursor=db.execute('''INSERT OR IGNORE INTO acesso_eventos(id,cliente_id,leitor_id,evento_id,evento,cracha_uid,funcionario_id,status,epoch,fonte_hora,observacao,recebido_em)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(str(uuid.uuid4()),reader['cliente_id'],reader['id'],event_id,event_type,card,
                                            person['id'] if person else None,status,epoch,source,obs,_iso()))
        db.commit()
        return jsonify(ok=True,duplicado=cursor.rowcount==0)
    finally:db.close()


@acesso_bp.post('/iot/crachas')
def device_collect_card():
    """Recebe coleta do mestre, sem criar permissao nem comando de gravacao."""
    db = get_db()
    try:
        reader = _device_auth(db)
        if not reader: return _error('Credencial do dispositivo inválida.', 401)
        try:
            p = _payload()
            uid = _uid(p.get('cracha_uid'))
            if int(p.get('bits') or 0) != 26 or int(uid, 16) == 0 or uid == _MASTER_UID:
                raise ValueError('Crachá mestre, vazio ou leitura inválida.')
        except (ValueError, TypeError) as exc: return _error(str(exc))
        db.execute("""INSERT INTO acesso_crachas_coletados(id,cliente_id,leitor_id,cracha_uid,coletado_em)
          VALUES(?,?,?,?,?) ON CONFLICT(cliente_id,cracha_uid) DO NOTHING""",
          (str(uuid.uuid4()), reader['cliente_id'], reader['id'], uid, _iso()))
        db.commit()
        return jsonify(ok=True, mensagem='Coleta recebida; permissões não foram alteradas.')
    finally: db.close()


@acesso_bp.post('/api/crachas/<coleta_id>/vincular')
@admin_required
def associate_collected_card(coleta_id):
    fail = _require_write()
    if fail: return fail
    try:
        p = _payload()
        person_id = str(p.get('funcionario_id') or '')
        cid = _cliente()
        db = get_db()
        try:
            db.execute('BEGIN IMMEDIATE')
            card = db.execute('SELECT * FROM acesso_crachas_coletados WHERE id=? AND cliente_id=?', (coleta_id,cid)).fetchone()
            person = db.execute("SELECT * FROM acesso_funcionarios WHERE id=? AND cliente_id=? AND status='ativo'", (person_id,cid)).fetchone()
            if not card or not person: raise ValueError('Coleta ou funcionário não encontrado nesta empresa.')
            if person['cracha_uid'] and person['cracha_uid'] != card['cracha_uid']:
                raise ValueError('Funcionário já possui outro crachá.')
            # O índice único impede vínculo duplicado em requisições concorrentes.
            db.execute('UPDATE acesso_funcionarios SET cracha_uid=?,updated_at=? WHERE id=? AND cliente_id=?',
                       (card['cracha_uid'],_iso(),person_id,cid))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally: db.close()
        return jsonify(ok=True,mensagem='Crachá vinculado. Use Permissões para autorizar nas máquinas e aguarde a confirmação do ESP32.')
    except sqlite3.IntegrityError: return _error('Crachá já vinculado a outro funcionário.',409)
    except ValueError as exc: return _error(str(exc),409)
