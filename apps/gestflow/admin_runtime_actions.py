# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\admin_runtime_actions.py
# Último recode: 2026-09-01 20:18 (America/Bahia)
# Motivo: Permitir excluir usuário preservando histórico, mostrando previamente os vínculos encontrados e removendo o usuário das listas e do acesso.

from __future__ import annotations

import html as html_lib
import re
import secrets
import urllib.parse
from typing import Any


def _redirecionar_usuarios(runtime: Any, *, erro: str = "", sucesso: str = ""):
    if hasattr(runtime, "redirecionar_configuracoes_usuarios"):
        return runtime.redirecionar_configuracoes_usuarios(
            erro=erro,
            sucesso=sucesso,
        )

    parametros = {}
    if erro:
        parametros["erro"] = erro
    if sucesso:
        parametros["sucesso"] = sucesso
    destino = runtime.url_for("configuracoes")
    if parametros:
        destino += "?" + urllib.parse.urlencode(parametros)
    return runtime.redirect(destino)


def _rotulo_vinculo_usuario(tabela: str) -> str:
    rotulos = {
        "usuario_atividades": "Histórico de atividades",
        "configuracoes_modulos_auditoria": "Auditoria de configurações",
        "configuracoes_operacoes_automaticas": "Operações automáticas",
        "gestao_atividades_historico": "Histórico de gestão de atividades",
        "registros_ponto": "Registros de ponto",
        "agendamentos": "Agendamentos",
        "assistente_conversas": "Conversas do assistente",
    }
    if tabela in rotulos:
        return rotulos[tabela]

    return tabela.replace("_", " ").strip().title() or tabela


def _listar_vinculos_usuario(runtime: Any, usuario_id: int) -> list[dict[str, Any]]:
    empresa_id = runtime.empresa_logada_id()
    tabelas_ignoradas = {
        "usuarios",
        "usuario_recuperacao_senha",
        "notificacoes",
    }
    vinculos: list[dict[str, Any]] = []

    with runtime.conectar_db() as conn:
        tabelas = [
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]

        for tabela in tabelas:
            if tabela in tabelas_ignoradas:
                continue

            colunas = [
                str(row["name"])
                for row in conn.execute(f'PRAGMA table_info("{tabela}")').fetchall()
            ]
            colunas_usuario = [
                coluna
                for coluna in colunas
                if coluna == "usuario_id" or coluna.endswith("_usuario_id")
            ]
            if not colunas_usuario:
                continue

            condicoes = " OR ".join(
                f'"{coluna}" = ?'
                for coluna in colunas_usuario
            )
            parametros: list[Any] = [usuario_id] * len(colunas_usuario)
            sql = f'SELECT COUNT(*) AS total FROM "{tabela}" WHERE ({condicoes})'

            if "empresa_id" in colunas:
                sql += ' AND "empresa_id" = ?'
                parametros.append(empresa_id)

            row = conn.execute(sql, parametros).fetchone()
            quantidade = int(row["total"] or 0) if row is not None else 0
            if quantidade <= 0:
                continue

            vinculos.append(
                {
                    "tabela": tabela,
                    "rotulo": _rotulo_vinculo_usuario(tabela),
                    "quantidade": quantidade,
                }
            )

    return sorted(
        vinculos,
        key=lambda item: (
            str(item.get("rotulo") or "").lower(),
            str(item.get("tabela") or "").lower(),
        ),
    )


def _validar_exclusao_usuario(runtime: Any, usuario_id: int):
    usuario = runtime.buscar_usuario_configuracoes_por_id(usuario_id)
    if usuario is None:
        return None, "Usuário não encontrado nesta empresa."

    status = str(usuario.get("status") or "").strip().lower()
    if status == "excluido":
        return None, "Este usuário já foi excluído."

    usuario_logado_id = runtime.usuario_logado_id()
    if usuario_logado_id and int(usuario_logado_id) == int(usuario_id):
        return None, "Você não pode excluir o próprio usuário logado."

    perfil = str(usuario.get("perfil") or "").strip().lower()
    if (
        status == "ativo"
        and perfil in {"administrador", "super_admin"}
        and runtime.contar_administradores_ativos_empresa(usuario_id) == 0
    ):
        return None, "A empresa precisa manter ao menos um administrador ativo."

    return usuario, ""


def _url_revisar_exclusao_usuario(usuario_id: int) -> str:
    return "/configuracoes/usuarios?" + urllib.parse.urlencode(
        {"excluir_usuario": int(usuario_id)}
    )


def _excluir_usuario(runtime: Any, usuario_id: int):
    usuario, erro = _validar_exclusao_usuario(runtime, usuario_id)
    if erro:
        return _redirecionar_usuarios(runtime, erro=erro)

    vinculos = _listar_vinculos_usuario(runtime, usuario_id)
    preservar_historico = str(
        runtime.request.form.get("preservar_historico") or ""
    ).strip() == "1"

    if vinculos and not preservar_historico:
        return runtime.redirect(_url_revisar_exclusao_usuario(usuario_id))

    empresa_id = runtime.empresa_logada_id()

    with runtime.conectar_db() as conn:
        conn.execute(
            "DELETE FROM usuario_recuperacao_senha WHERE empresa_id = ? AND usuario_id = ?",
            (empresa_id, usuario_id),
        )
        conn.execute(
            "DELETE FROM notificacoes WHERE empresa_id = ? AND usuario_id = ?",
            (empresa_id, usuario_id),
        )

        if vinculos:
            email_excluido = (
                f"excluido-{empresa_id}-{usuario_id}-"
                f"{secrets.token_hex(6)}@gestflow.local"
            )
            senha_hash = runtime.generate_password_hash(secrets.token_urlsafe(32))
            agora = runtime.agora_empresa().isoformat(timespec="seconds")
            cursor = conn.execute(
                """
                UPDATE usuarios
                SET nome = ?,
                    email = ?,
                    senha_hash = ?,
                    perfil = ?,
                    status = ?,
                    ultimo_login = '',
                    sessao_versao = COALESCE(sessao_versao, 1) + 1,
                    atualizado_em = ?
                WHERE id = ? AND empresa_id = ?
                """,
                (
                    "Usuário excluído",
                    email_excluido,
                    senha_hash,
                    "excluido",
                    "excluido",
                    agora,
                    usuario_id,
                    empresa_id,
                ),
            )
        else:
            cursor = conn.execute(
                "DELETE FROM usuarios WHERE id = ? AND empresa_id = ?",
                (usuario_id, empresa_id),
            )

        if cursor.rowcount != 1:
            conn.rollback()
            return _redirecionar_usuarios(
                runtime,
                erro="Não foi possível excluir o usuário.",
            )

        conn.commit()

    runtime.registrar_atividade_usuario(
        "exclusao",
        "configuracoes",
        (
            f"Excluiu usuário {usuario.get('nome') or usuario_id} preservando histórico"
            if vinculos
            else f"Excluiu usuário {usuario.get('nome') or usuario_id}"
        ),
        runtime.request.path,
        registro_id=usuario_id,
    )

    return _redirecionar_usuarios(
        runtime,
        sucesso=(
            "Usuário excluído com sucesso. O histórico foi preservado."
            if vinculos
            else "Usuário excluído com sucesso."
        ),
    )

def _excluir_titulo_financeiro(runtime: Any, titulo_id: int):
    titulo = runtime.buscar_financeiro_titulo_por_id(titulo_id)
    destino = runtime.destino_lista_financeiro_titulo(titulo)

    if titulo is None:
        return runtime.redirect(destino)

    empresa_id = runtime.empresa_logada_id()
    with runtime.conectar_db() as conn:
        conn.execute(
            """
            DELETE FROM financeiro_titulo_historico
            WHERE empresa_id = ? AND titulo_id = ?
            """,
            (empresa_id, titulo_id),
        )
        conn.execute(
            """
            DELETE FROM notificacoes
            WHERE empresa_id = ?
              AND origem = 'financeiro_titulo'
              AND origem_id = ?
            """,
            (empresa_id, titulo_id),
        )
        cursor = conn.execute(
            """
            DELETE FROM financeiro_titulos
            WHERE id = ? AND empresa_id = ?
            """,
            (titulo_id, empresa_id),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            mensagem = urllib.parse.quote("Não foi possível excluir o título.")
            return runtime.redirect(f"{destino}?erro={mensagem}")
        conn.commit()

    runtime.registrar_atividade_usuario(
        "exclusao",
        "financeiro",
        f"Excluiu título financeiro {titulo_id}",
        runtime.request.path,
        registro_id=titulo_id,
    )
    mensagem = urllib.parse.quote("Título financeiro excluído com sucesso.")
    return runtime.redirect(f"{destino}?sucesso={mensagem}")


def _form_excluir_usuario(usuario_id: str) -> str:
    href = html_lib.escape(
        _url_revisar_exclusao_usuario(int(usuario_id)),
        quote=True,
    )
    return (
        f'<a href="{href}" class="btn-action btn-delete" '
        'title="Revisar e excluir usuário">Excluir</a>'
    )


def _injetar_exclusao_usuario(runtime: Any, html: str) -> str:
    usuario_logado_id = str(runtime.usuario_logado_id() or "")

    padrao = re.compile(
        r'(<form method="post" action="/configuracoes/usuarios/(?P<id>\d+)/status" '
        r'style="display:inline;">.*?</form>)',
        re.DOTALL,
    )

    def adicionar(match: re.Match[str]) -> str:
        usuario_id = match.group("id")
        if usuario_id == usuario_logado_id:
            return match.group(1)
        return match.group(1) + _form_excluir_usuario(usuario_id)

    return padrao.sub(adicionar, html)


def _painel_revisao_exclusao_usuario(runtime: Any) -> str:
    try:
        usuario_id = int(runtime.request.args.get("excluir_usuario") or 0)
    except (TypeError, ValueError):
        usuario_id = 0

    if usuario_id <= 0:
        return ""

    usuario, erro = _validar_exclusao_usuario(runtime, usuario_id)
    if erro:
        mensagem = html_lib.escape(erro)
        return (
            '<div class="config-alert error" '
            'style="margin:14px 0 16px;">'
            f"{mensagem}"
            "</div>"
        )

    vinculos = _listar_vinculos_usuario(runtime, usuario_id)
    nome = html_lib.escape(str(usuario.get("nome") or f"Usuário {usuario_id}"))
    email = html_lib.escape(str(usuario.get("email") or ""))
    total = sum(int(item.get("quantidade") or 0) for item in vinculos)

    if vinculos:
        itens = "".join(
            (
                '<li style="padding:8px 0;border-bottom:1px solid #e2e8f0;">'
                f'<strong>{html_lib.escape(str(item["rotulo"]))}</strong> '
                f'<span style="color:#64748b;">({html_lib.escape(str(item["tabela"]))})</span>'
                f'<span style="float:right;font-weight:900;">{int(item["quantidade"])} registro(s)</span>'
                "</li>"
            )
            for item in vinculos
        )
        resumo = (
            f"Foram encontrados {total} registro(s) vinculado(s) em "
            f"{len(vinculos)} área(s). Esses registros não serão apagados."
        )
        botao = "Excluir preservando histórico"
        aviso = (
            "O acesso será removido, o usuário desaparecerá da lista e os registros antigos "
            "continuarão apontando para “Usuário excluído”."
        )
    else:
        itens = (
            '<li style="padding:8px 0;color:#166534;font-weight:800;">'
            "Nenhum histórico ou vínculo foi encontrado."
            "</li>"
        )
        resumo = "Este usuário pode ser excluído definitivamente."
        botao = "Excluir definitivamente"
        aviso = "Não há registros históricos que precisem ser preservados."

    preservar = "1" if vinculos else "0"
    return (
        '<section style="margin:14px 0 18px;padding:16px;border:1px solid #f59e0b;'
        'border-radius:14px;background:#fffbeb;">'
        '<div style="display:flex;justify-content:space-between;gap:14px;'
        'align-items:flex-start;flex-wrap:wrap;">'
        "<div>"
        '<strong style="display:block;font-size:15px;color:#92400e;">Revisar exclusão de usuário</strong>'
        f'<div style="margin-top:4px;font-weight:900;color:#0f172a;">{nome}</div>'
        f'<div style="font-size:12px;color:#64748b;">{email}</div>'
        "</div>"
        '<a href="/configuracoes/usuarios" class="btn-action btn-view" '
        'style="text-decoration:none;">Cancelar</a>'
        "</div>"
        f'<p style="margin:12px 0 6px;color:#334155;font-weight:800;">{html_lib.escape(resumo)}</p>'
        f'<p style="margin:0 0 10px;color:#64748b;font-size:12px;">{html_lib.escape(aviso)}</p>'
        '<ul style="margin:0 0 14px;padding:0;list-style:none;">'
        f"{itens}"
        "</ul>"
        f'<form method="post" action="/configuracoes/usuarios/{usuario_id}/excluir" '
        'onsubmit="return confirm(\'Confirmar a exclusão deste usuário?\');">'
        f'<input type="hidden" name="preservar_historico" value="{preservar}">'
        '<button type="submit" class="btn-action btn-delete" '
        'style="padding:9px 14px;font-weight:900;">'
        f"{html_lib.escape(botao)}"
        "</button>"
        "</form>"
        "</section>"
    )


def _injetar_painel_revisao_usuario(runtime: Any, html: str) -> str:
    painel = _painel_revisao_exclusao_usuario(runtime)
    if not painel:
        return html

    marcador = '<div class="list-toolbar-paginada'
    indice = html.find(marcador)
    if indice >= 0:
        return html[:indice] + painel + html[indice:]

    marcador = '<section class="'
    indice = html.find(marcador)
    if indice >= 0:
        return html[:indice] + painel + html[indice:]

    return painel + html

def instalar_acoes_administrativas(runtime: Any) -> None:
    app = runtime.app
    if getattr(app, "_gestflow_acoes_administrativas_instaladas", False):
        return
    app._gestflow_acoes_administrativas_instaladas = True

    normalizar_financeiro_original = runtime._normalizar_status_financeiro

    def normalizar_financeiro_com_exclusao(titulo: dict[str, Any]) -> dict[str, Any]:
        normalizado = normalizar_financeiro_original(titulo)
        normalizado["pode_excluir"] = True
        return normalizado

    runtime._normalizar_status_financeiro = normalizar_financeiro_com_exclusao

    listar_usuarios_original = runtime.listar_usuarios_configuracoes

    def listar_usuarios_sem_excluidos(*args, **kwargs):
        usuarios = listar_usuarios_original(*args, **kwargs)
        return [
            usuario
            for usuario in usuarios
            if str(usuario.get("status") or "").strip().lower() != "excluido"
        ]

    runtime.listar_usuarios_configuracoes = listar_usuarios_sem_excluidos

    def excluir_financeiro_titulo_runtime(titulo_id: int):
        return _excluir_titulo_financeiro(runtime, titulo_id)

    app.view_functions["excluir_financeiro_titulo"] = excluir_financeiro_titulo_runtime

    endpoint_excluir_usuario = "excluir_usuario_configuracoes_runtime"
    if endpoint_excluir_usuario not in app.view_functions:

        @app.post(
            "/configuracoes/usuarios/<int:usuario_id>/excluir",
            endpoint=endpoint_excluir_usuario,
        )
        def excluir_usuario_configuracoes_runtime(usuario_id: int):
            perfil = str(runtime.session.get("usuario_perfil") or "").strip().lower()
            if perfil not in {"administrador", "super_admin"}:
                return _redirecionar_usuarios(
                    runtime,
                    erro="Somente administradores podem excluir usuários.",
                )
            return _excluir_usuario(runtime, usuario_id)

    @app.after_request
    def _ajustar_acoes_administrativas_response(response):
        if response.direct_passthrough:
            return response

        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            return response

        path = str(runtime.request.path or "")
        if path not in {
            "/configuracoes",
            "/configuracoes/usuarios",
            "/financeiro/receber",
            "/financeiro/pagar",
            "/financeiro/fluxo-caixa",
        }:
            return response

        html = response.get_data(as_text=True)

        if path in {
            "/configuracoes",
            "/configuracoes/usuarios",
        }:
            html = _injetar_exclusao_usuario(runtime, html)
            if path == "/configuracoes/usuarios":
                html = _injetar_painel_revisao_usuario(runtime, html)

        if path.startswith("/financeiro/"):
            html = html.replace('title="Excluir título manual"', 'title="Excluir título"')
            html = html.replace('aria-label="Excluir título manual"', 'aria-label="Excluir título"')
            html = html.replace(
                "Excluir definitivamente este título manual?",
                "Excluir definitivamente este título?",
            )

        response.set_data(html)
        return response
