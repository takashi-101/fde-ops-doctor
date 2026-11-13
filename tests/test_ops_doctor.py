import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ops_doctor import run_diagnostics


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


if __name__ == "__main__":
    unittest.main()
