# minport — Test Cases

## P: Import 解析 (8 cases)

| ID | テストケース | 期待結果 |
|----|------------|---------|
| P-1 | `from X.Y.Z import Name` を正しく抽出 | module_path="X.Y.Z", name="Name" |
| P-2 | `from X.Y import Name as Alias` を抽出 | alias="Alias" |
| P-3 | `from X.Y import A, B, C` を個別に抽出 | 3つの ImportStatement |
| P-4 | `import X.Y.Z`（from なし）は無視 | 抽出しない |
| P-5 | `from . import Name`（相対 import）は無視 | 抽出しない |
| P-6 | `from X import Name`（1階層）は短縮余地なし | 抽出するが違反にならない |
| P-7 | 複数行に渡る import（`\` や括弧継続）を正しく抽出 | 正しい行番号 |
| P-8 | コメント行・文字列内の import は無視 | 抽出しない |

## R: re-export 解析 (17 cases)

| ID | テストケース | 期待結果 |
|----|------------|---------|
| R-1 | `__init__.py` に `from .module import Name` がある | Name は親パッケージから import 可能 |
| R-2 | `__init__.py` に `from .module import Name as Name` がある | 同上（PEP 484 明示的 re-export） |
| R-3 | `__init__.py` に `__all__ = ["Name"]` がある | Name は親パッケージから import 可能 |
| R-4 | `__init__.py` に re-export がない | 短縮不可 |
| R-5 | 多段 re-export: `X/__init__.py` → `X.Y/__init__.py` → `X.Y.Z.module` | 最短パスは `X` |
| R-6 | `__all__` に Name が含まれない | 短縮不可 |
| R-7 | `from .module import Name` はあるが `__all__` に含まれない場合 | 短縮可能（`__all__` なしなら暗黙的に公開） |
| R-8 | `__all__` が存在し Name が含まれない場合 | 短縮不可（`__all__` が存在すれば明示的制御） |
| R-9 | サードパーティの `__init__.py` を AST 解析 | 正しく re-export を検出 |
| R-10 | サードパーティのパッケージが見つからない | スキップ（エラーにならない） |
| R-11 | 循環 re-export がある場合 | 無限ループせずに処理完了 |
| R-12 | `from .module import *` による re-export | 検出しない（スコープ外） |
| R-13 | `Foo = _impl._Foo` 形式の代入が `__all__` に含まれる | Name は親パッケージから import 可能 |
| R-13b | 代入 re-export があっても `__all__` が無い | 短縮不可（安全側） |
| R-13c | `Foo = 1` のような非属性アクセス RHS | 代入 re-export として扱わない |
| R-13d | `Foo: type = _impl._Foo` 形式の注釈付き代入が `__all__` に含まれる | Name は親パッケージから import 可能 |
| R-13e | `Foo: int = 1` のような注釈付き非属性 RHS | 代入 re-export として扱わない |

## D: 違反検出 (10 cases)

| ID | コードパターン | 期待結果 |
|----|--------------|---------|
| D-1 | `from X.Y.Z import Name` で `X.Y` に re-export あり | **検出**: `from X.Y import Name` を推奨 |
| D-2 | `from X.Y.Z import Name` で `X` に re-export あり | **検出**: 最短の `from X import Name` を推奨 |
| D-3 | `from X.Y import Name` で短縮余地なし | 検出しない |
| D-4 | `from X import Name`（既に最短） | 検出しない |
| D-5 | 1ファイルに複数の短縮可能 import | **全て検出**、各行番号を正確に報告 |
| D-6 | 違反ゼロのファイル | 報告なし |
| D-7 | `from X.Y.Z import Name as Alias` が短縮可能 | **検出**: alias を保持したまま推奨 |
| D-8 | `from X.Y.Z import A, B` で A のみ短縮可能 | A のみ検出、B は検出しない |
| D-9 | 同名が複数の短いパスに存在（名前衝突） | 検出しない（安全側） |
| D-10 | `from __future__ import annotations` 等の特殊 import | 検出しない |

## F: 自動修正 (8 cases)

| ID | テストケース | 期待結果 |
|----|------------|---------|
| F-1 | 単一の import 行を短縮 | 行が書き換わる |
| F-2 | alias 付き import を短縮 | `from X import Name as Alias` に書き換え |
| F-3 | 複数名 import の一部のみ短縮可能 | 短縮可能な名前だけ別行に分離して短縮 |
| F-4 | 修正後のファイルが構文的に正しい | `ast.parse` が通る |
| F-5 | `--fix` なしでは書き換えない | ファイル変更なし |
| F-6 | 修正対象がないファイル | ファイル変更なし |
| F-7 | 名前衝突がある場合は修正しない | ファイル変更なし |
| F-8 | 修正結果の FixResult が正しい件数を返す | files_modified, fixes_applied |

## S: サードパーティ解析 (6 cases)

| ID | テストケース | 期待結果 |
|----|------------|---------|
| S-1 | インストール済みパッケージの re-export を検出 | 短縮を推奨 |
| S-2 | 未インストールパッケージの import | スキップ（エラーなし） |
| S-3 | サードパーティの `__init__.py` を AST 解析 | re-export を正しく検出 |
| S-4 | C 拡張のみのパッケージ（`.so`/`.pyd`） | スキップ |
| S-5 | namespace package（`__init__.py` なし） | スキップ |
| S-6 | サードパーティの `__all__` を尊重 | `__all__` にない名前は短縮しない |

## CLI: CLI (8 cases)

| ID | テストケース | 期待結果 |
|----|------------|---------|
| CLI-1 | 違反なしのディレクトリ | exit code 0 |
| CLI-2 | 違反ありのディレクトリ | exit code 1 |
| CLI-3 | `--fix` で修正 | exit code 0、ファイルが書き換わる |
| CLI-4 | `--help` | ヘルプ表示 |
| CLI-5 | 存在しないパス | exit code 2 |
| CLI-6 | `--exclude` で除外 | 対象ファイルがスキップされる |
| CLI-7 | `--src` でソースルート指定 | import 解決に使用 |
| CLI-8 | `pyproject.toml` の `[tool.minport]` 読み込み | 設定反映 |

## E: エッジケース (10 cases)

| ID | テストケース | 期待結果 |
|----|------------|---------|
| E-1 | 空ファイル | エラーなし |
| E-2 | 構文エラーのあるファイル | スキップ + 警告 |
| E-3 | バイナリファイル | スキップ |
| E-4 | `from __future__ import annotations` | 対象外 |
| E-5 | `from typing import TYPE_CHECKING` 等の typing import | 通常通り検査 |
| E-6 | `if TYPE_CHECKING:` ブロック内の import | 通常通り検査 |
| E-7 | 1000行超のファイル | 正常動作 |
| E-8 | 同じ名前を異なるパスから import（ファイル内重複） | 各行を個別に評価 |
| E-9 | `# minport: ignore` インライン抑制 | 抑制される |
| E-10 | symlink 先のファイル | 重複検出しない |

## テスト構造

```
tests/
├── conftest.py
├── test_import_parser.py      # P-1〜P-8
├── test_reexport_resolver.py  # R-1〜R-13e
├── test_detection.py          # D-1〜D-10
├── test_fixer.py              # F-1〜F-8
├── test_third_party.py        # S-1〜S-6
├── test_cli.py                # CLI-1〜CLI-8
├── test_edge_cases.py         # E-1〜E-10
└── fixtures/
    ├── project/               # プロジェクト内 re-export テスト用
    └── third_party/           # サードパーティ模擬
```

合計: 67 cases
