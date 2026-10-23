# Caminho: apps/indflow/tests/test_acesso_backend.py
# Testes de integração isolada do SQLite/fluxo de comandos, sem conexão à internet.
# Correção 23/10/2026: fechar conexões SQLite; testar máquinas registradas sem device,
# isolamento por empresa e exclusão de máquinas arquivadas na API de leitores.
# Pode rodar em ambientes sem Flask instalado, substituindo apenas os decorators HTTP.
import importlib.util
from contextlib import closing
import pathlib
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB_FILE = None
SESSION = {}
REQ = None

class FakeBlueprint:
    def __init__(self, *a, **k):pass
    def get(self, *a, **k):return lambda f:f
    def post(self, *a, **k):return lambda f:f
    def route(self, *a, **k):return lambda f:f

class FakeRequest:
    def __init__(self):self.headers={};self.body={}
    def get_json(self, silent=True):return self.body


def get_db():
    c=sqlite3.connect(DB_FILE,timeout=20)
    c.row_factory=sqlite3.Row
    return c


def setup_import():
    global REQ
    REQ=FakeRequest()
    flask=types.ModuleType('flask')
    flask.Blueprint=FakeBlueprint
    flask.jsonify=lambda **kwargs:kwargs
    flask.render_template=lambda *a,**k:(a,k)
    flask.redirect=lambda *a,**k: None
    flask.url_for=lambda *a,**k: '/'
    flask.request=REQ
    flask.session=SESSION
    sys.modules['flask']=flask
    mods=types.ModuleType('modules');mods.__path__=[];sys.modules['modules']=mods
    adm=types.ModuleType('modules.admin');adm.__path__=[];sys.modules['modules.admin']=adm
    ar=types.ModuleType('modules.admin.routes')
    ar.admin_required=lambda f:f;ar.login_required=lambda f:f
    sys.modules['modules.admin.routes']=ar
    di=types.ModuleType('modules.db_indflow');di.get_db=get_db
    sys.modules['modules.db_indflow']=di
    dev_pkg=types.ModuleType('modules.devices');dev_pkg.__path__=[];sys.modules['modules.devices']=dev_pkg
    dev_spec=importlib.util.spec_from_file_location('modules.devices.routes', ROOT/'modules/devices/routes.py')
    dev_mod=importlib.util.module_from_spec(dev_spec)
    sys.modules['modules.devices.routes']=dev_mod
    dev_spec.loader.exec_module(dev_mod)
    spec=importlib.util.spec_from_file_location('acesso_routes',ROOT/'modules/acesso/routes.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def unpack(result):
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],int):return result[0],result[1]
    return result,200

class AccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global DB_FILE
        cls.temp=tempfile.TemporaryDirectory()
        DB_FILE=str(pathlib.Path(cls.temp.name)/'test_access.sqlite')
        cls.mod=setup_import()
        with closing(get_db()) as conexao, conexao as db:
            db.execute("CREATE TABLE clientes (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            db.execute("INSERT INTO clientes VALUES ('empresaA','active'),('empresaB','active')")
            db.execute("CREATE TABLE devices (device_id TEXT PRIMARY KEY, cliente_id TEXT, machine_id TEXT)")
            db.execute("""CREATE TABLE indflow_machine_registry (
                cliente_id TEXT NOT NULL, machine_id TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY (cliente_id, machine_id))""")
            db.execute("""CREATE TABLE indflow_machine_archives (
                cliente_id TEXT NOT NULL, machine_id TEXT NOT NULL, archived_at TEXT NOT NULL,
                PRIMARY KEY (cliente_id, machine_id))""")
            db.execute("INSERT INTO indflow_machine_registry VALUES ('empresaA','maquina01','2026-10-23')")
        cls.mod.init_access_db()

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        SESSION.clear();SESSION.update(cliente_id='empresaA', role='admin')
        REQ.headers.clear(); REQ.body={}
        self.csrf=self.mod._csrf();REQ.headers['X-CSRF-Token']=self.csrf
        with closing(get_db()) as conexao, conexao as db:
            for t in ('acesso_eventos','acesso_permissoes','acesso_comandos','acesso_leitores','acesso_funcionarios'):
                db.execute('DELETE FROM '+t)
            db.execute('DELETE FROM devices')
            db.execute('DELETE FROM indflow_machine_archives')
            db.execute('DELETE FROM indflow_machine_registry')
            db.execute("INSERT INTO indflow_machine_registry VALUES ('empresaA','maquina01','2026-10-23')")

    def call(self,fn,body={},status=200,*args):
        REQ.body=body
        resp,code=unpack(fn(*args))
        self.assertEqual(code,status,resp)
        return resp

    def provision(self):
        p=self.call(self.mod.create_person,dict(nome='Maria Silva',matricula='MT-01',setor='Produção'))
        reader=self.call(self.mod.create_reader,dict(codigo='ESP32_CRACHA_01',machine_id='maquina01'))
        with closing(get_db()) as conexao, conexao as db:
            rid=db.execute('SELECT id FROM acesso_leitores').fetchone()['id']
        return p['funcionario_id'],rid,reader['token']

    def as_device(self,token):
        REQ.headers.pop('X-CSRF-Token',None)
        REQ.headers['Authorization']='Bearer '+token

    def test_registered_machine_without_production_device_and_tenant_isolation(self):
        # A tela Devices criou a máquina, mas ainda não há device/MAC de produção.
        with closing(get_db()) as conexao, conexao as db:
            db.execute("INSERT INTO indflow_machine_registry VALUES ('empresaA','plaina','2026-10-23')")
            db.execute("INSERT INTO indflow_machine_registry VALUES ('empresaB','serra','2026-10-23')")
            db.execute("INSERT INTO indflow_machine_registry VALUES ('empresaA','arquivada','2026-10-23')")
            db.execute("INSERT INTO indflow_machine_archives VALUES ('empresaA','arquivada','2026-10-23')")
        template, context = self.mod.home()
        self.assertEqual(template, ('acesso_home.html',))
        self.assertIn('plaina', context['machines'])
        self.assertNotIn('serra', context['machines'])
        self.assertNotIn('arquivada', context['machines'])
        reader = self.call(self.mod.create_reader, dict(codigo='ESP32_CRACHA_01', machine_id='plaina'))
        self.assertTrue(reader['ok'])
        self.call(self.mod.create_reader, dict(codigo='ESP32_CRACHA_02', machine_id='serra'), 400)
        self.call(self.mod.create_reader, dict(codigo='ESP32_CRACHA_03', machine_id='arquivada'), 400)
        with closing(get_db()) as conexao, conexao as db:
            row=db.execute("SELECT machine_id FROM acesso_leitores WHERE cliente_id='empresaA'").fetchone()
        self.assertEqual(row['machine_id'], 'plaina')

    def test_capture_success_only_after_real_device_ack(self):
        pid,rid,token=self.provision()
        start=self.call(self.mod.start_capture,dict(funcionario_id=pid,leitor_id=rid))
        cmd=start['comando_id']
        state=self.call(self.mod.command_status,{},200,cmd)
        self.assertEqual(state['estado'],'aguardando_leitura')
        self.as_device(token)
        queued=self.call(self.mod.device_poll)
        self.assertEqual(queued['comando']['acao'],'aguardar_cracha')
        scan=self.call(self.mod.device_scan,dict(comando_id=cmd,cracha_uid='0D0C49D',bits=26))
        self.assertEqual(scan['acao'],'gravar_cracha')
        queued=self.call(self.mod.device_poll)
        self.assertEqual(queued['comando']['acao'],'aguardar_confirmacao')
        with closing(get_db()) as conexao, conexao as db:
            self.assertIsNone(db.execute('SELECT cracha_uid FROM acesso_funcionarios WHERE id=?',(pid,)).fetchone()['cracha_uid'])
        result=self.call(self.mod.device_ack,dict(comando_id=cmd,gravado=True))
        self.assertEqual(result['estado'],'confirmado')
        with closing(get_db()) as conexao, conexao as db:
            person=db.execute('SELECT cracha_uid FROM acesso_funcionarios WHERE id=?',(pid,)).fetchone()
            grant=db.execute('SELECT situacao FROM acesso_permissoes WHERE funcionario_id=?',(pid,)).fetchone()
        self.assertEqual(person['cracha_uid'],'00D0C49D')
        self.assertEqual(grant['situacao'],'ativa')
        self.assertEqual(self.call(self.mod.device_ack,dict(comando_id=cmd,gravado=True))['estado'],'confirmado')

    def test_capture_duplicate_and_master_block(self):
        pid,rid,token=self.provision()
        cmd=self.call(self.mod.start_capture,dict(funcionario_id=pid,leitor_id=rid))['comando_id']
        self.as_device(token)
        self.call(self.mod.device_scan,dict(comando_id=cmd,cracha_uid='E6242D',bits=26),400)
        self.call(self.mod.device_scan,dict(comando_id=cmd,cracha_uid='ABCDEF12',bits=4),400)
        self.assertEqual(self.call(self.mod.device_scan,dict(comando_id=cmd,cracha_uid='C647CD',bits=26))['acao'],'gravar_cracha')
        self.call(self.mod.device_ack,dict(comando_id=cmd,gravado=True))
        REQ.headers.pop('Authorization');REQ.headers['X-CSRF-Token']=self.csrf
        pid2=self.call(self.mod.create_person,dict(nome='João Lima'))['funcionario_id']
        cmd2=self.call(self.mod.start_capture,dict(funcionario_id=pid2,leitor_id=rid))['comando_id']
        self.as_device(token)
        self.call(self.mod.device_scan,dict(comando_id=cmd2,cracha_uid='00C647CD',bits=26),409)
        with closing(get_db()) as conexao, conexao as db:self.assertEqual(db.execute('SELECT estado FROM acesso_comandos WHERE id=?',(cmd2,)).fetchone()['estado'],'falhou')

    def test_permission_remote_and_revocation(self):
        pid,rid,token=self.provision()
        cmd=self.call(self.mod.start_capture,dict(funcionario_id=pid,leitor_id=rid))['comando_id'];self.as_device(token)
        self.call(self.mod.device_scan,dict(comando_id=cmd,cracha_uid='D0C49D',bits=26))
        self.call(self.mod.device_ack,dict(comando_id=cmd,gravado=True))
        REQ.headers.pop('Authorization');REQ.headers['X-CSRF-Token']=self.csrf
        revoke=self.call(self.mod.permissions,dict(funcionario_id=pid,leitor_id=rid,acao='revogar'))
        self.as_device(token)
        poll=self.call(self.mod.device_poll)
        self.assertEqual(poll['comando']['acao'],'remover_cracha')
        self.call(self.mod.device_ack,dict(comando_id=revoke['comando_id'],gravado=True))
        with closing(get_db()) as conexao, conexao as db:self.assertEqual(db.execute('SELECT situacao FROM acesso_permissoes').fetchone()['situacao'],'revogada')

    def test_event_dedup_tenant_and_csrf(self):
        pid,rid,token=self.provision()
        self.as_device(token)
        evt=dict(evento_id='evento-1-xyz',evento='CARTAO_LIDO',cracha_uid='ABCDEF12',epoch=1792773301,fonte_hora='ntp_recuperado')
        self.assertFalse(self.call(self.mod.device_event,evt)['duplicado'])
        self.assertTrue(self.call(self.mod.device_event,evt)['duplicado'])
        with closing(get_db()) as conexao, conexao as db:self.assertEqual(db.execute('SELECT count(*) FROM acesso_eventos').fetchone()[0],1)
        REQ.headers['Authorization']='Bearer errado'
        self.call(self.mod.device_poll,{},401)
        REQ.headers.pop('Authorization',None);REQ.headers['X-CSRF-Token']='wrong'
        self.call(self.mod.create_person,dict(nome='Invasor'),403)
        REQ.headers['X-CSRF-Token']=self.csrf
        SESSION['cliente_id']='empresaB'
        self.call(self.mod.command_status,{},404,'invalid')
        with closing(get_db()) as conexao, conexao as db:self.assertEqual(db.execute('SELECT count(*) FROM acesso_funcionarios').fetchone()[0],1)

if __name__=='__main__':unittest.main(verbosity=2)
