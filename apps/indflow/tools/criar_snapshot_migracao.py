# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\tools\criar_snapshot_migracao.py
# Último recode: 2026-08-31 11:14 (America/Bahia)
# Motivo: Criar snapshot SQLite consistente do IndFlow antigo sem interromper a operação dos ESPs durante a preparação da migração.

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from _migration_common import collect_summary, ensure_parent, railway_default_db_path, write_json_atomic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cria um snapshot consistente do SQLite do IndFlow usando sqlite3.Connection.backup()."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Banco de origem. Padrao: INDFLOW_DB_PATH ou /data/indflow.db no Railway.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/data/migracao/indflow_snapshot.db"),
        help="Arquivo de snapshot. Padrao: /data/migracao/indflow_snapshot.db",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifesto JSON. Padrao: <output>.manifest.json",
    )
    parser.add_argument("--pages", type=int, default=512, help="Paginas por passo do backup SQLite.")
    parser.add_argument("--sleep", type=float, default=0.02, help="Pausa entre passos do backup SQLite.")
    return parser


def create_snapshot(source: Path, output: Path, pages: int, sleep: float) -> None:
    source = source.resolve()
    output = output.resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Banco de origem nao encontrado: {source}")
    if source == output:
        raise ValueError("Origem e snapshot nao podem ser o mesmo arquivo")

    ensure_parent(output)
    tmp = output.with_name(output.name + ".tmp")
    try:
        tmp.unlink(missing_ok=True)
    except TypeError:
        if tmp.exists():
            tmp.unlink()

    src_uri = f"file:{source.as_posix()}?mode=ro"
    src = sqlite3.connect(src_uri, uri=True, timeout=60)
    dst = sqlite3.connect(str(tmp), timeout=60)
    try:
        src.backup(dst, pages=max(1, int(pages)), sleep=max(0.0, float(sleep)))
        dst.execute("PRAGMA wal_checkpoint(FULL)")
        dst.commit()
    finally:
        dst.close()
        src.close()

    check = sqlite3.connect(str(tmp), timeout=30)
    try:
        result = [str(r[0]) for r in check.execute("PRAGMA integrity_check").fetchall()]
    finally:
        check.close()

    if result != ["ok"]:
        try:
            tmp.unlink()
        except Exception:
            pass
        raise RuntimeError(f"Snapshot reprovado no integrity_check: {result}")

    os.replace(tmp, output)


def main() -> int:
    args = build_parser().parse_args()
    source = Path(args.source) if args.source else railway_default_db_path()
    output = Path(args.output)
    manifest_path = Path(args.manifest) if args.manifest else Path(str(output) + ".manifest.json")

    create_snapshot(source, output, args.pages, args.sleep)
    manifest = collect_summary(output, include_sha256=True)
    manifest["source_name"] = source.name
    manifest["snapshot_path"] = str(output)
    write_json_atomic(manifest_path, manifest)

    result = {
        "ok": True,
        "source": str(source),
        "snapshot": str(output),
        "manifest": str(manifest_path),
        "sha256": manifest.get("sha256"),
        "size_bytes": manifest.get("size_bytes"),
        "table_count": manifest.get("table_count"),
        "integrity_ok": manifest.get("integrity_ok"),
        "markers": manifest.get("markers"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
