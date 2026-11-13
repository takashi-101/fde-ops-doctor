"""Self-service environment & operational readiness checker for non-IT staff."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class CheckItem:
    name: str
    status: str  # OK | WARN | FAIL
    detail: str
    action_hint: str


def check_python_version(min_major: int = 3, min_minor: int = 10) -> CheckItem:
    ok = (sys.version_info.major, sys.version_info.minor) >= (min_major, min_minor)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return CheckItem(
        name="Python実行環境",
        status="OK" if ok else "FAIL",
        detail=f"現在バージョン: {ver}",
        action_hint="" if ok else f"Python {min_major}.{min_minor}以上へ更新してください。",
    )


def check_disk_space(target_dir: Path, min_free_mb: int = 100) -> CheckItem:
    usage = shutil.disk_usage(target_dir)
    free_mb = usage.free // (1024 * 1024)
    ok = free_mb >= min_free_mb
    return CheckItem(
        name="ディスク空き容量",
        status="OK" if ok else "WARN",
        detail=f"空き容量: {free_mb} MB",
        action_hint="" if ok else "不要なログや一時ファイルを整理してください。",
    )


def check_required_files(base_dir: Path, required_rel_paths: List[str]) -> CheckItem:
    missing = [p for p in required_rel_paths if not (base_dir / p).exists()]
    if not missing:
        return CheckItem("必須ファイル確認", "OK", "すべての設定・手順書が存在します", "")
    return CheckItem(
        name="必須ファイル確認",
        status="FAIL",
        detail=f"不足: {', '.join(missing)}",
        action_hint="引き継ぎフォルダから不足ファイルを配置してください。",
    )


def check_sqlite_integrity(db_path: Path) -> CheckItem:
    if not db_path.exists():
        return CheckItem("SQLite整合性", "WARN", "DBファイル未作成", "初回実行時に自動生成されます。")
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            res = conn.execute("PRAGMA integrity_check;").fetchone()
            ok = res is not None and res[0] == "ok"
            return CheckItem(
                name="SQLite整合性",
                status="OK" if ok else "FAIL",
                detail=f"integrity_check={res[0] if res else 'unknown'}",
                action_hint="" if ok else "直近のバックアップDBから復元してください。",
            )
    except sqlite3.Error as exc:
        return CheckItem("SQLite整合性", "FAIL", str(exc), "DBファイルのアクセス権限または破損を確認してください。")


def run_diagnostics(
    base_dir: Path | str,
    required_files: List[str] | None = None,
    db_path: Path | str | None = None,
) -> dict:
    base = Path(base_dir)
    items = [
        check_python_version(),
        check_disk_space(base),
        check_required_files(base, required_files or []),
    ]
    if db_path is not None:
        items.append(check_sqlite_integrity(Path(db_path)))

    overall = "OK"
    if any(i.status == "FAIL" for i in items):
        overall = "FAIL"
    elif any(i.status == "WARN" for i in items):
        overall = "WARN"

    return {
        "overall_status": overall,
        "checks": [i.__dict__ for i in items],
    }


if __name__ == "__main__":
    print(json.dumps(run_diagnostics("."), ensure_ascii=False, indent=2))
