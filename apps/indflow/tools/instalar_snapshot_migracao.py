# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\tools\instalar_snapshot_migracao.py
# Último recode: 2026-08-31 11:14 (America/Bahia)
# Motivo: Instalar de forma atômica e idempotente um snapshot validado no banco do novo IndFlow/GestFlow antes do servidor Flask abrir conexões.

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from _migration_common import (
    collect_summary,
    compare_summary_to_manifest,
    ensure_parent,
    railway_default_db_path,
    read_manifest,
    sha256_file,
    write_json_atomic,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Instala um snapshot validado no banco ativo do novo IndFlow.")
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("/data/migracao/indflow_snapshot.db"),
        help="Snapshot previamente enviado ao volume novo.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifesto do snapshot. Padrao: <snapshot>.manifest.json",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Banco ativo. Padrao: INDFLOW_DB_PATH ou /data/indflow.db no Railway.",
    )
    parser.add_argument(
        "--marker",
        type=Path,
        default=Path("/data/migracao/snapshot_instalado.json"),
        help="Marcador que impede reaplicacao em restart futuro.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Obrigatorio para efetivamente substituir o target.",
    )
    return parser


def _backup_existing_db(target: Path) -> Path | None:
    if not target.is_file() or target.stat().st_size <= 0:
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = target.parent / "migracao" / f"pre_import_{stamp}.db"
    ensure_parent(backup)

    src = sqlite3.connect(f"file:{target.resolve().as_posix()}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(str(backup), timeout=60)
    try:
        src.backup(dst, pages=512, sleep=0.02)
        dst.commit()
    finally:
        dst.close()
        src.close()

    return backup


def _atomic_install(snapshot: Path, target: Path) -> None:
    ensure_parent(target)
    tmp = target.with_name(target.name + ".migration.tmp")
    try:
        tmp.unlink(missing_ok=True)
    except TypeError:
        if tmp.exists():
            tmp.unlink()

    shutil.copy2(snapshot, tmp)
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, target)


# O Procfile pode executar este script antes do waitress quando
# INDFLOW_MIGRATION_APPLY_ON_START=1. O marcador torna a operacao one-shot.
def main() -> int:
    args = build_parser().parse_args()
    snapshot = Path(args.snapshot)
    manifest_path = Path(args.manifest) if args.manifest else Path(str(snapshot) + ".manifest.json")
    target = Path(args.target) if args.target else railway_default_db_path()
    marker = Path(args.marker)

    if not args.confirm:
        print(json.dumps({"ok": False, "error": "Use --confirm para instalar o snapshot."}, ensure_ascii=False))
        return 2

    # Se a primeira instalação já foi concluída, qualquer restart futuro deve
    # seguir em frente sem reaplicar o snapshot e sem voltar dados no tempo.
    if marker.is_file():
        try:
            marker_data = read_manifest(marker)
        except Exception:
            marker_data = {}
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "migracao_ja_aplicada",
                    "snapshot_sha256": marker_data.get("snapshot_sha256"),
                    "target": str(target),
                    "marker": str(marker),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if not snapshot.is_file():
        print(json.dumps({"ok": False, "error": f"Snapshot nao encontrado: {snapshot}"}, ensure_ascii=False))
        return 2
    if not manifest_path.is_file():
        print(json.dumps({"ok": False, "error": f"Manifesto nao encontrado: {manifest_path}"}, ensure_ascii=False))
        return 2

    manifest = read_manifest(manifest_path)
    snapshot_summary = collect_summary(snapshot, include_sha256=True)
    errors = compare_summary_to_manifest(snapshot_summary, manifest)
    if errors:
        print(json.dumps({"ok": False, "stage": "validate_snapshot", "errors": errors}, ensure_ascii=False, indent=2))
        return 3

    snapshot_sha = str(snapshot_summary.get("sha256") or "")

    if snapshot.resolve() == target.resolve():
        print(json.dumps({"ok": False, "error": "Snapshot e target nao podem ser o mesmo arquivo."}, ensure_ascii=False))
        return 2

    backup_path = _backup_existing_db(target)
    _atomic_install(snapshot, target)

    target_summary = collect_summary(target, include_sha256=True)
    post_errors = compare_summary_to_manifest(target_summary, manifest)
    if post_errors:
        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": "validate_target_after_install",
                    "errors": post_errors,
                    "backup": str(backup_path) if backup_path else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 5

    marker_payload = {
        "snapshot_sha256": snapshot_sha,
        "target_sha256_after_install": sha256_file(target),
        "snapshot": str(snapshot),
        "target": str(target),
        "backup_before_install": str(backup_path) if backup_path else None,
        "installed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    write_json_atomic(marker, marker_payload)

    result = {
        "ok": True,
        "installed": True,
        "snapshot": str(snapshot),
        "snapshot_sha256": snapshot_sha,
        "target": str(target),
        "backup_before_install": str(backup_path) if backup_path else None,
        "marker": str(marker),
        "table_count": target_summary.get("table_count"),
        "markers": target_summary.get("markers"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
