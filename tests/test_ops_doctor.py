import dataclasses
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ops_doctor import CheckItem, run_diagnostics
from ops_doctor.checker import (
    check_disk_space,
    check_python_version,
    check_required_files,
    check_sqlite_integrity,
)

MB = 1024 * 1024


def _make_healthy_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")


def _disk(free_bytes: int):
    """shutil.disk_usage の戻り値の代わり（free だけを使う）。"""
    return mock.patch("ops_doctor.checker.shutil.disk_usage", return_value=SimpleNamespace(free=free_bytes))


class TestOpsDoctor(unittest.TestCase):
    def test_detects_missing_file_and_healthy_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "app.db"
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

            res_fail = run_diagnostics(base, required_files=["config.json"], db_path=db)
            self.assertEqual(res_fail["overall_status"], "FAIL")

            (base / "config.json").write_text("{}", encoding="utf-8")
            res_ok = run_diagnostics(base, required_files=["config.json"], db_path=db)
            self.assertEqual(res_ok["overall_status"], "OK")


class TestCheckPythonVersion(unittest.TestCase):
    def test_normal_current_python_meets_default_minimum(self) -> None:
        item = check_python_version()
        self.assertEqual(item.name, "Python実行環境")
        self.assertEqual(item.status, "OK")
        self.assertEqual(item.action_hint, "")
        v = sys.version_info
        self.assertEqual(item.detail, f"現在バージョン: {v.major}.{v.minor}.{v.micro}")

    def test_boundary_minimum_equal_to_current_is_ok(self) -> None:
        v = sys.version_info
        self.assertEqual(check_python_version(v.major, v.minor).status, "OK")

    def test_boundary_minimum_one_minor_above_current_fails(self) -> None:
        v = sys.version_info
        item = check_python_version(v.major, v.minor + 1)
        self.assertEqual(item.status, "FAIL")
        self.assertEqual(item.action_hint, f"Python {v.major}.{v.minor + 1}以上へ更新してください。")


class TestCheckDiskSpace(unittest.TestCase):
    def test_normal_real_disk_reports_free_mb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            item = check_disk_space(Path(tmp), min_free_mb=0)
        self.assertEqual(item.name, "ディスク空き容量")
        self.assertEqual(item.status, "OK")
        self.assertRegex(item.detail, r"^空き容量: \d+ MB$")

    def test_boundary_exactly_minimum_is_ok(self) -> None:
        with _disk(100 * MB):
            item = check_disk_space(Path("."), min_free_mb=100)
        self.assertEqual((item.status, item.detail), ("OK", "空き容量: 100 MB"))

    def test_boundary_one_byte_below_minimum_warns(self) -> None:
        # MB は切り捨てで計算されるため、1バイト足りないだけで 99 MB になる
        with _disk(100 * MB - 1):
            item = check_disk_space(Path("."), min_free_mb=100)
        self.assertEqual((item.status, item.detail), ("WARN", "空き容量: 99 MB"))
        self.assertEqual(item.action_hint, "不要なログや一時ファイルを整理してください。")

    def test_error_missing_directory_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                check_disk_space(Path(tmp) / "no_such_dir")


class TestCheckRequiredFiles(unittest.TestCase):
    def test_normal_all_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "docs").mkdir()
            (base / "config.json").write_text("{}", encoding="utf-8")
            (base / "docs" / "runbook.md").write_text("手順", encoding="utf-8")
            item = check_required_files(base, ["config.json", "docs/runbook.md"])
        self.assertEqual(item, CheckItem("必須ファイル確認", "OK", "すべての設定・手順書が存在します", ""))

    def test_normal_missing_files_listed_in_given_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "b.txt").write_text("x", encoding="utf-8")
            item = check_required_files(base, ["c.txt", "b.txt", "a.txt"])
        self.assertEqual(item.status, "FAIL")
        self.assertEqual(item.detail, "不足: c.txt, a.txt")
        self.assertEqual(item.action_hint, "引き継ぎフォルダから不足ファイルを配置してください。")

    def test_boundary_empty_list_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(check_required_files(Path(tmp), []).status, "OK")

    def test_boundary_directory_counts_as_present(self) -> None:
        # 存在だけを確かめるため、同名のフォルダでも OK になる
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.json").mkdir()
            self.assertEqual(check_required_files(Path(tmp), ["config.json"]).status, "OK")


class TestCheckSqliteIntegrity(unittest.TestCase):
    def test_normal_healthy_db_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            _make_healthy_db(db)
            item = check_sqlite_integrity(db)
        self.assertEqual(item, CheckItem("SQLite整合性", "OK", "integrity_check=ok", ""))

    def test_boundary_missing_db_warns_and_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            item = check_sqlite_integrity(db)
            self.assertFalse(db.exists())
        self.assertEqual(item.status, "WARN")
        self.assertEqual(item.detail, "DBファイル未作成")

    def test_boundary_empty_file_is_ok(self) -> None:
        # 0バイトのファイルは、SQLite では空のデータベースとして扱われる
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "empty.db"
            db.write_bytes(b"")
            self.assertEqual(check_sqlite_integrity(db).status, "OK")

    def test_error_non_sqlite_file_fails_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "broken.db"
            db.write_bytes(b"this is not a sqlite database" * 50)
            item = check_sqlite_integrity(db)
        self.assertEqual(item.status, "FAIL")
        self.assertIn("not a database", item.detail)
        self.assertEqual(item.action_hint, "DBファイルのアクセス権限または破損を確認してください。")

    def test_error_integrity_check_not_ok_fails(self) -> None:
        conn = mock.MagicMock()
        conn.execute.return_value.fetchone.return_value = ("*** in database main ***",)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            db.write_bytes(b"")
            with mock.patch("ops_doctor.checker.sqlite3.connect", return_value=conn):
                item = check_sqlite_integrity(db)
        self.assertEqual(item.status, "FAIL")
        self.assertEqual(item.detail, "integrity_check=*** in database main ***")
        self.assertEqual(item.action_hint, "直近のバックアップDBから復元してください。")
        conn.close.assert_called_once()

    def test_error_integrity_check_without_result_fails(self) -> None:
        conn = mock.MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            db.write_bytes(b"")
            with mock.patch("ops_doctor.checker.sqlite3.connect", return_value=conn):
                item = check_sqlite_integrity(db)
        self.assertEqual((item.status, item.detail), ("FAIL", "integrity_check=unknown"))


class TestRunDiagnostics(unittest.TestCase):
    def test_normal_all_ok_without_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _disk(10_000 * MB):
            (Path(tmp) / "config.json").write_text("{}", encoding="utf-8")
            res = run_diagnostics(tmp, required_files=["config.json"])
        self.assertEqual(res["overall_status"], "OK")
        self.assertEqual(
            [c["name"] for c in res["checks"]],
            ["Python実行環境", "ディスク空き容量", "必須ファイル確認"],
        )
        self.assertEqual(set(res["checks"][0]), {"name", "status", "detail", "action_hint"})

    def test_normal_db_path_adds_sqlite_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _disk(10_000 * MB):
            db = Path(tmp) / "app.db"
            _make_healthy_db(db)
            res = run_diagnostics(Path(tmp), db_path=str(db))
        self.assertEqual(len(res["checks"]), 4)
        self.assertEqual(res["checks"][3]["name"], "SQLite整合性")
        self.assertEqual(res["overall_status"], "OK")

    def test_boundary_required_files_none_is_same_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _disk(10_000 * MB):
            self.assertEqual(run_diagnostics(tmp), run_diagnostics(tmp, required_files=[]))

    def test_boundary_warn_only_gives_overall_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _disk(10_000 * MB):
            res = run_diagnostics(tmp, db_path=Path(tmp) / "app.db")
        self.assertEqual(res["overall_status"], "WARN")

    def test_boundary_low_disk_gives_overall_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _disk(0):
            res = run_diagnostics(tmp)
        self.assertEqual(res["overall_status"], "WARN")
        self.assertEqual(res["checks"][1]["status"], "WARN")

    def test_boundary_fail_takes_priority_over_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _disk(0):
            res = run_diagnostics(tmp, required_files=["config.json"], db_path=Path(tmp) / "app.db")
        self.assertEqual([c["status"] for c in res["checks"]], ["OK", "WARN", "FAIL", "WARN"])
        self.assertEqual(res["overall_status"], "FAIL")

    def test_error_missing_base_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                run_diagnostics(Path(tmp) / "no_such_dir")


class TestCheckItem(unittest.TestCase):
    def test_error_check_item_is_immutable(self) -> None:
        item = CheckItem("n", "OK", "d", "")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.status = "FAIL"  # type: ignore[misc]


class TestExampleScript(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / "examples" / "run_example.py"), *args],
            capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT,
        )

    def test_normal_sample_reports_missing_file_and_missing_db(self) -> None:
        proc = self._run("examples/sample_site.json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        res = json.loads(proc.stdout)
        self.assertEqual(res["overall_status"], "FAIL")
        by_name = {c["name"]: c for c in res["checks"]}
        self.assertEqual(by_name["必須ファイル確認"]["detail"], "不足: contacts.csv")
        self.assertEqual(by_name["SQLite整合性"]["status"], "WARN")

    def test_error_missing_spec_argument_exits_with_usage(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr)


if __name__ == "__main__":
    unittest.main()
