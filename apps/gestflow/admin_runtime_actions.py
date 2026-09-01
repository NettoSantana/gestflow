# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\admin_runtime_actions.py
# Último recode: 2026-09-01 20:12 (America/Bahia)
# Motivo: Corrigir a exibição da ação Excluir usuário na rota real /configuracoes/usuarios, preservando as regras de segurança existentes.

from __future__ import annotations

import re
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


def _usuario_tem_vinculos_criticos(runtime: Any, usuario_id: int) -> list[str]:
    empresa_id = runtime.empresa_logada_id()
    tabelas_ignoradas = {
        "usuarios",
        "usuario_recuperacao_senha",
        "notificacoes",
    }
    vinculos: list[str] = []

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

            tem_empresa_id = "empresa_id" in colunas
            for coluna in colunas_usuario:
                sql = f'SELECT 1 FROM "{tabela}" WHERE "{coluna}" = ?'
                parametros: list[Any] = [usuario_id]
                if tem_empresa_id:
                    sql += ' AND "empresa_id" = ?'
                    parametros.append(empresa_id)
                sql += " LIMIT 1"
                if conn.execute(sql, parametros).fetchone() is not None:
                    vinculos.append(tabela)
                    break

    return sorted(set(vinculos))


def _excluir_usuario(runtime: Any, usuario_id: int):
    usuario = runtime.buscar_usuario_configuracoes_por_id(usuario_id)
    if usuario is None:
        return _redirecionar_usuarios(
            runtime,
            erro="Usuário não encontrado nesta empresa.",
        )

    usuario_logado_id = runtime.usuario_logado_id()
    if usuario_logado_id and int(usuario_logado_id) == int(usuario_id):
        return _redirecionar_usuarios(
            runtime,
            erro="Você não pode excluir o próprio usuário logado.",
        )

    perfil = str(usuario.get("perfil") or "").strip().lower()
    status = str(usuario.get("status") or "").strip().lower()
    if (
        status == "ativo"
        and perfil in {"administrador", "super_admin"}
        and runtime.contar_administradores_ativos_empresa(usuario_id) == 0
    ):
        return _redirecionar_usuarios(
            runtime,
            erro="A empresa precisa manter ao menos um administrador ativo.",
        )

    vinculos = _usuario_tem_vinculos_criticos(runtime, usuario_id)
    if vinculos:
        return _redirecionar_usuarios(
            runtime,
            erro=(
                "Este usuário possui histórico ou vínculos no sistema e não pode ser excluído. "
                "Use Desativar acesso para preservar a integridade dos registros."
            ),
        )

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
        f"Excluiu usuário {usuario.get('nome') or usuario_id}",
        runtime.request.path,
        registro_id=usuario_id,
    )
    return _redirecionar_usuarios(
        runtime,
        sucesso="Usuário excluído com sucesso.",
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
    return (
        f'<form method="post" action="/configuracoes/usuarios/{usuario_id}/excluir" '
        'style="display:inline;" '
        'onsubmit="return confirm(\'Excluir definitivamente este usuário? Esta ação não pode ser desfeita.\');">'
        '<button type="submit" class="btn-action btn-delete">Excluir</button>'
        "</form>"
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

        if path.startswith("/financeiro/"):
            html = html.replace('title="Excluir título manual"', 'title="Excluir título"')
            html = html.replace('aria-label="Excluir título manual"', 'aria-label="Excluir título"')
            html = html.replace(
                "Excluir definitivamente este título manual?",
                "Excluir definitivamente este título?",
            )

        response.set_data(html)
        return response
