# minport — Project Instructions

Python の `from ... import ...` 文を最短パスに正規化するリンター + 自動修正ツール。
re-export チェーンを辿り、より短い import パスが存在する場合に警告・修正する。

**関連ドキュメント:**
- [docs/test-cases.md](docs/test-cases.md) — テストケース全量リスト (62 cases)

## Project Overview

`from X.Y.Z import Name` のように冗長な import パスを、re-export を辿って最短形に正規化する CLI ツール。PyPI (`pip install minport`) で公開。ライセンスは MIT。

### 想定ユースケース

```python
# Before
from pydantic.fields import FieldInfo
from sqlalchemy.orm.session import Session
from myproject.domain.user.models import User

# After (minport check --fix)
from pydantic import FieldInfo
from sqlalchemy.orm import Session
from myproject.domain import User
```

冗長な import パスは：
- 可読性を損なう
- 内部リファクタリング時に壊れやすい（re-export は公開 API、内部パスは実装詳細）
- コードベース全体で同じ名前に対して異なるパスが混在する原因になる

## Scope

### やること

- `from X.Y.Z import Name` に対して、より短い `from X import Name` や `from X.Y import Name` が有効かを検証
- プロジェクト内パッケージの `__init__.py` re-export チェーンの解析
- サードパーティパッケージの re-export 解析（インストール済みパッケージの `__init__.py` を AST 解析）
- CLI (`minport check`, `minport check --fix`)
- `--fix` による自動書き換え
- `pyproject.toml` の `[tool.minport]` 設定サポート

### やらないこと

- `import X.Y.Z` 形式（`from` なしの import）の書き換え
- 名前衝突の自動解決（同名が複数パスに存在する場合は修正しない）
- ワイルドカード import (`from X import *`) の解析
- ランタイム import による検証

## Architecture

### コンポーネント構成

```
src/minport/
├── __init__.py             # Public API: __version__
├── _models.py              # データモデル（frozen dataclass）
├── _import_parser.py       # AST から import 文を抽出・解析
├── _reexport_resolver.py   # re-export チェーンを辿って最短パスを算出
├── _fixer.py               # ソースコード書き換え（行ベース置換）
├── checker.py              # チェッカーファサード
└── cli.py                  # CLI エントリーポイント
```

### 設計原則

**インターフェースに依存する設計（Protocol ベース DI）**

各コンポーネントは `typing.Protocol` で依存先を定義し、具象実装を直接 import しない。

**依存方向**

```
cli.py → checker.py → _import_parser.py
                     → _reexport_resolver.py
                     → _fixer.py
```

`_models.py` は他のモジュールに依存しない（leaf module）。
`checker.py` がファサードとして各コンポーネントを組み立てる。

## Data Model

```python
@dataclass(frozen=True)
class ImportStatement:
    """解析された from import 文"""
    module_path: str           # "package.submodule.internal"
    name: str                  # "ClassName"
    alias: str | None          # "as Alias" がある場合
    file_path: Path
    line: int
    col: int

@dataclass(frozen=True)
class Violation:
    """検出された違反"""
    file_path: Path
    line: int
    col: int
    original_path: str
    shorter_path: str
    name: str
    code: str                  # "MP001"
    message: str

@dataclass(frozen=True)
class CheckResult:
    """チェック結果"""
    violations: tuple[Violation, ...]
    files_checked: int
    files_skipped: int

@dataclass(frozen=True)
class FixResult:
    """修正結果"""
    files_modified: int
    fixes_applied: int
```

## Error Code

| コード | 名前 | 説明 |
|--------|------|------|
| MP001 | shorter-import-available | より短い import パスが利用可能 |

## Algorithm

### 最短パス探索

1. 対象ファイルから `from X.Y.Z import Name` を全て抽出
2. `X.Y.Z` のモジュールパスを分解: `["X", "X.Y", "X.Y.Z"]`
3. 短い順に各候補パスについて:
   a. 対応する `__init__.py` またはモジュールファイルを特定
   b. そのモジュールの名前空間に `Name` が re-export されているか AST 解析で確認
   c. 見つかればそれが最短パス → 元のパスより短ければ違反として報告
4. 名前衝突（同名が複数パスに存在）がある場合は報告しない

### re-export 検出パターン

`__init__.py` 内の以下を認識：
- `from .submodule import Name` — 明示的 re-export
- `from .submodule import Name as Name` — PEP 484 準拠の明示的 re-export
- `__all__ = ["Name", ...]` — `__all__` による公開 API 宣言

### サードパーティ解析

- `importlib.util.find_spec` でインストール済みパッケージの `__init__.py` を特定
- AST 解析で re-export を確認（ランタイム import は行わない）

## Quality Rules

### Ruff — 全ルール適用、抑制を最小化

```toml
[tool.ruff.lint]
select = ["ALL"]
ignore = ["D1", "COM812", "ISC001", "D203", "D213"]
```

**原則: `# noqa` を書く前に設計を見直す。** ruff の警告はコードの設計・構造で解決する。`# noqa` は「ルールが文脈的に不適切」な場合のみ、理由コメント付きで使用。ignore への追加は PR で理由を明記する。

### ty / pyright — 厳格な型チェック

ty (Astral製) を優先。利用不可なら pyright strict で代替。

**型に関する原則:**
- 全 public 関数・メソッドに型アノテーション
- `Any` 禁止 — `object` または Protocol を使う
- `cast()` は最小限、理由をコメントで明記
- `type: ignore` 禁止 — 型エラーは設計で解決
- Union より Protocol / Overload を優先

## Coding Style

### 全般

- **イミュータビリティ優先**: `@dataclass(frozen=True)` / `NamedTuple` でデータを表現
- **1 ファイル 200〜400 行**、上限 800 行
- **1 関数 50 行以内**、ネスト 4 段以内。早期 return
- **副作用を最小化**し、純粋関数を優先

### 命名

- 意図を明確に表現。省略より可読性
- boolean は `is_`, `has_`, `should_`, `can_` で始める
- `_` prefix の private モジュールは内部実装。public API は `__init__.py` で re-export

### エラー処理

- 外部入力はシステム境界でバリデーション
- 内部コード間は Protocol の型で保証（余分なバリデーション不要）
- 構文エラーファイルはスキップ + 警告（全体を止めない）

### 依存管理

- ランタイム依存: **ゼロ**（標準ライブラリのみ）
- 開発依存: `pytest`, `pytest-cov`, `ruff`, `ty`, `pip-audit`, `pre-commit`

## Git Conventions

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- コミットメッセージは目的（why）を簡潔に
- main への直接 push 禁止

## CI/CD

### CI (`.github/workflows/ci.yml`)

PR ごとに lint / typecheck / test / audit を並列実行。`all-checks-pass` をブランチ保護の required check にする。Python 3.11 + 3.12 + 3.13 + 3.14 マトリクステスト。開発は 3.14。

### CD (`.github/workflows/release.yml`)

Release Please + PyPI Trusted Publisher:
1. Conventional Commits → Release Please が CHANGELOG + バージョンバンプ PR 自動作成
2. Release PR マージ → GitHub Release + tag
3. `publish` ジョブが OIDC 認証で PyPI に自動公開

### Versioning Policy (SemVer)

v1.0.0 未満: `feat:` → minor, `fix:` → patch, breaking change は避ける
v1.0.0 以降: breaking change は `feat!:` で major バンプ

### pre-commit

ruff check/format + ty check をローカルでも実行。

## Development Commands

```bash
uv sync                                    # セットアップ
uv run ruff check src/ tests/ --fix        # lint
uv run ruff format src/ tests/             # format
uv run ty check src/                       # 型チェック
uv run pytest --cov=minport                # テスト + カバレッジ
uv run pip-audit                           # セキュリティ監査
```

## CLI

```bash
minport check src/                       # チェック
minport check src/ --fix                 # チェック + 自動修正
minport check src/ --src src/            # ソースルート指定
minport check src/ --exclude "tests/*"   # 除外
```

### 出力

```
src/app/service.py:3:1: MP001 `from pydantic.fields import FieldInfo` can be shortened to `from pydantic import FieldInfo`
Found 1 error (1 fixable with `minport check --fix`).
```

## Configuration

### pyproject.toml

```toml
[tool.minport]
src = ["src"]                    # import 解決のソースルート
exclude = ["tests/*"]            # 除外パターン（glob）
```

### pyproject.toml 完全版

```toml
[project]
name = "minport"
version = "0.0.0"
description = "A Python linter that finds unnecessarily long import paths and suggests shorter alternatives"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [{ name = "KinjiKawaguchi" }]
keywords = ["linter", "static-analysis", "import", "refactoring", "code-quality"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Software Development :: Quality Assurance",
    "Typing :: Typed",
]
dependencies = []

[project.urls]
Homepage = "https://github.com/KinjiKawaguchi/minport"
Repository = "https://github.com/KinjiKawaguchi/minport"
Issues = "https://github.com/KinjiKawaguchi/minport/issues"

[project.scripts]
minport = "minport.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/minport"]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-cov>=6.0", "ruff>=0.12", "ty>=0.0.1", "pip-audit>=2.0", "pre-commit>=4.0"]
```

### 安全性

- `--fix` は元ファイルを直接書き換える（git diff で確認推奨）
- 名前衝突がある場合は修正しない（安全側に倒す）
- 構文エラーファイルはスキップ

## README.md 構成仕様

1. バッジ行: PyPI version, Python versions, CI status, License
2. 1行説明
3. Problem: 冗長な import パスの実例
4. Quick Start: インストール + 最小例
5. Usage: CLI コマンド
6. Configuration: pyproject.toml 設定例
7. Rules: MP001 の説明
8. Algorithm: 最短パス探索の概要
9. Limitations: 現在の制約
10. Contributing: 開発環境セットアップ + DeepWiki リンク
11. License: MIT
