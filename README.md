# FDE Ops Doctor（非エンジニア現場向け 環境診断・一次切り分けツール）

[![tests](https://github.com/takashi-101/fde-ops-doctor/actions/workflows/tests.yml/badge.svg)](https://github.com/takashi-101/fde-ops-doctor/actions/workflows/tests.yml)

FDE（顧客の現場に入り、導入を担当するエンジニア）が現場を離れた後に、引き継ぎ先の担当者が環境の異常を一次切り分けするための診断ツールです。Python のバージョン、ディスクの空き容量、必須ファイルの有無、SQLite（ファイル1つで動くデータベース）の整合性の4項目を確かめ、項目ごとの判定（OK・WARN・FAIL）と対処の一言を JSON で返します。

## 30秒で読む要点
- **なぜ作ったか**：担当者が替わっても運用が回るようにするためです。導入した人に問い合わせる前に、引き継ぎ先の担当者が最初の4項目を自分で確かめられます。
- **確かめるのは4項目です**：Python が 3.10 以上か、空き容量が 100 MB 以上か、指定したファイルがそろっているか、SQLite の `PRAGMA integrity_check`（SQLite に組み込まれた破損検査）が `ok` を返すか。
- **判定は3段階です**：問題のある項目には対処の一言（`action_hint`）が付きます。全体の判定は、FAIL が1つでもあれば FAIL、FAIL が無く WARN があれば WARN、それ以外は OK です。
- **標準ライブラリだけで動きます**：外部との通信や有料APIは使いません。テストは28件（正常・境界・異常）です。

## 見本を動かす
```
python examples/run_example.py examples/sample_site.json
```
`examples/site_a/`（架空の現場フォルダ）には `config.json` と `runbook.md` だけを置き、`contacts.csv` と SQLite のファイルはわざと置いていません。そのため、必須ファイル確認は FAIL、SQLite整合性は WARN、全体は FAIL になります。

実行結果（Windows・Python 3.14.6 で実行。Python のバージョンと空き容量は実行環境によって変わります）：
```json
{
  "overall_status": "FAIL",
  "checks": [
    {
      "name": "Python実行環境",
      "status": "OK",
      "detail": "現在バージョン: 3.14.6",
      "action_hint": ""
    },
    {
      "name": "ディスク空き容量",
      "status": "OK",
      "detail": "空き容量: 122923 MB",
      "action_hint": ""
    },
    {
      "name": "必須ファイル確認",
      "status": "FAIL",
      "detail": "不足: contacts.csv",
      "action_hint": "引き継ぎフォルダから不足ファイルを配置してください。"
    },
    {
      "name": "SQLite整合性",
      "status": "WARN",
      "detail": "DBファイル未作成",
      "action_hint": "初回実行時に自動生成されます。"
    }
  ]
}
```
判定の結果にかかわらず、終了コードは 0 です。

## 判定の内容
| 項目（`name`） | 関数（既定値） | OK | WARN | FAIL |
|---|---|---|---|---|
| Python実行環境 | `check_python_version(min_major=3, min_minor=10)` | 実行中の Python が指定以上 | ― | 指定未満 |
| ディスク空き容量 | `check_disk_space(target_dir, min_free_mb=100)` | `target_dir` のあるドライブの空きが指定以上 | 指定未満 | ― |
| 必須ファイル確認 | `check_required_files(base_dir, required_rel_paths)` | すべて存在する | ― | 1つ以上無い（`detail` に無いものを並べる） |
| SQLite整合性 | `check_sqlite_integrity(db_path)` | `integrity_check` の結果が `ok` | ファイルが無い | 結果が `ok` 以外、または SQLite のエラー（SQLite でないファイルなど） |

空き容量は 1 MB = 1024 × 1024 バイトで計算し、端数は切り捨てます。

`run_diagnostics(base_dir, required_files=None, db_path=None)` は、上の関数を既定値で呼び、次の形の辞書を返します。`db_path` を渡したときだけ SQLite整合性を確かめます。
```
{"overall_status": "OK" | "WARN" | "FAIL", "checks": [{"name", "status", "detail", "action_hint"}, ...]}
```

## 設定ファイルの形式（`examples/run_example.py`）
| キー | 内容 | 見本の値 |
|---|---|---|
| `base_dir` | 診断するフォルダ。設定ファイルのあるフォルダからの相対パス | `site_a` |
| `required_files` | 必須ファイルの一覧。`base_dir` からの相対パス（省略可） | `["config.json", "runbook.md", "contacts.csv"]` |
| `db_path` | SQLite のファイル。設定ファイルのあるフォルダからの相対パス（省略可。省略すると SQLite整合性は確かめません） | `site_a/data/app.db` |

## テスト（28件）
```
python -m unittest discover -s tests -v
```
- 正常：各項目の OK、`db_path` を渡したときに項目が4つになること、見本の実行結果。
- 境界：Python のバージョンが指定と同じ・1つ上、空き容量がちょうど 100 MB と 1 バイト不足（99 MB）、必須ファイルの一覧が空、同名のフォルダ、0 バイトの SQLite ファイル、DB ファイルが無いとき（WARN、ファイルは作らない）、FAIL と WARN が混在したときの全体判定。
- 異常：SQLite でないファイル、`integrity_check` の結果が `ok` 以外・結果なし、存在しない `base_dir`（`FileNotFoundError`）、`CheckItem` の書き換え、設定ファイルの指定漏れ。

## 制約
- 閾値（Python 3.10、空き容量 100 MB）は `run_diagnostics` からは変えられません。変えるときは個別の関数を呼びます。
- 必須ファイルは「そのパスが存在するか」だけを確かめます。中身や、ファイルかフォルダかは確かめません。
- `base_dir` が存在しないと、空き容量の確認で `FileNotFoundError` が発生し、結果を返しません。
- SQLite整合性は `PRAGMA integrity_check` の1行目だけを見ます。0 バイトのファイルは、SQLite では空のデータベースとして扱われるため OK になります。
- DB ファイルが無いときの対処の一言は「初回実行時に自動生成されます。」ですが、このツールはファイルを作りません。DB を使うアプリケーションが作る前提の文言です。

## ファイル構成
```
src/ops_doctor/
  checker.py          4項目の確認と run_diagnostics
examples/
  run_example.py      設定ファイルを読み、run_diagnostics の結果を表示
  sample_site.json    見本の設定ファイル
  site_a/             架空の現場フォルダ（config.json、runbook.md）
tests/                ユニットテスト
```

## 根拠（学習）

| 求められる力 | 機能 | 裏付けになる学習（発行元・名称・発行日） | 照会先（Credly） |
|---|---|---|---|
| データ活用（Python・SQL・BI） | SQLiteファイルの整合性確認 | Amazon Web Services Training and Certification「AWS Educate Getting Started with Databases - Training Badge」2025年6月1日 | https://www.credly.com/badges/0f3404b3-6419-4d48-934f-507f0364e032 |
| クラウドと閉域の基盤 | 運用環境の一次切り分け（Pythonの版・空き容量・設定ファイル） | Amazon Web Services Training and Certification「AWS Educate Getting Started with Cloud Ops - Training Badge」2025年6月1日 | https://www.credly.com/badges/872f51f0-225c-4b24-af97-298964ac2dba |

「求められる力」の分け方は、[プロフィール](https://github.com/takashi-101) の「FDE・AXで求められる力と、その根拠」と同じです。

## ライセンス
MIT
