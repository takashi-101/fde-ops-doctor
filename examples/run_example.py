"""設定ファイル（JSON）を読み、run_diagnostics の結果を JSON で表示します。

使い方: python examples/run_example.py examples/sample_site.json

設定ファイルのキー:
  base_dir        診断するフォルダ（設定ファイルのあるフォルダからの相対パス）
  required_files  base_dir からの相対パスで書いた必須ファイルの一覧（省略可）
  db_path         SQLite ファイル（設定ファイルのあるフォルダからの相対パス、省略可）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ops_doctor import run_diagnostics  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="設定ファイルを読み、環境診断の結果を JSON で表示します。")
    parser.add_argument("spec", type=Path, help="設定ファイル（JSON）のパス")
    args = parser.parse_args(argv)

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    here = args.spec.resolve().parent
    db = spec.get("db_path")
    result = run_diagnostics(
        here / spec["base_dir"],
        required_files=spec.get("required_files"),
        db_path=here / db if db else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
