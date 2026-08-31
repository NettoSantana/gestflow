# Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\tools\validar_snapshot_migracao.py
# Último recode: 2026-08-31 11:14 (America/Bahia)
# Motivo: Validar integridade, hash, schema e contagens do snapshot antes de instalar dados migrados no novo IndFlow/GestFlow.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _migration_common import collect_summary, compare_summary_to_manifest, read_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Valida um snapshot SQLite da migracao do IndFlow.")
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("/data/migracao/indflow_snapshot.db"),
        help="Snapshot a validar.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifesto criado junto do snapshot. Padrao: <snapshot>.manifest.json",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    snapshot = Path(args.snapshot)
    manifest_path = Path(args.manifest) if args.manifest else Path(str(snapshot) + ".manifest.json")

    summary = collect_summary(snapshot, include_sha256=True)
    errors: list[str] = []
    manifest = None

    if manifest_path.is_file():
        manifest = read_manifest(manifest_path)
        errors.extend(compare_summary_to_manifest(summary, manifest))
    else:
        errors.append(f"Manifesto nao encontrado: {manifest_path}")

    result = {
        "ok": len(errors) == 0,
        "snapshot": str(snapshot),
        "manifest": str(manifest_path),
        "errors": errors,
        "sha256": summary.get("sha256"),
        "integrity_ok": summary.get("integrity_ok"),
        "table_count": summary.get("table_count"),
        "critical_tables": summary.get("critical_tables"),
        "markers": summary.get("markers"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
