# minport — Project Instructions

Python の `from ... import ...` 文を最短パスに正規化するリンター + 自動修正ツール。re-export チェーンを辿り、より短い import パスが存在する場合に警告・修正する。

この文書は**設計判断の記録**と**コードから復元できない意図**のみを扱う。ユーザ向けの使い方・CLI・設定項目は [README.md](README.md) を参照。

## Scope

### やらないこと

- `import X.Y.Z` 形式（`from` なしの import）の書き換え
- 名前衝突の自動解決（同名が複数パスに存在する場合は修正しない）
- ランタイム import による検証

## Architecture

### 依存方向

```
cli.py → checker.py → _import_parser.py
                    → _reexport_resolver.py
                    → _fixer.py
```

`_models.py` は他のモジュールに依存しない leaf module。`checker.py` がファサードとして各コンポーネントを組み立てる。

### Protocol ベース DI

各コンポーネントは `typing.Protocol` で依存先を定義し、具象実装を直接 import しない。テスト時の差し替えと依存方向の一方向性を確保するため。

## Algorithm

### 最短パス探索

1. 対象ファイルから `from X.Y.Z import Name` を全て抽出
2. `X.Y.Z` のモジュールパスを分解: `["X", "X.Y", "X.Y.Z"]`
3. 短い順に各候補パスについて、そのモジュールの名前空間に `Name` が re-export されているか AST 解析で確認
4. 見つかればそれが最短パス → 元のパスより短ければ違反として報告
5. 名前衝突（同名が複数パスに存在）がある場合は報告しない

### re-export 検出パターン

`__init__.py` 内の以下を認識:

- `from .submodule import Name` — 明示的 re-export
- `from .submodule import Name as Name` — PEP 484 準拠の明示的 re-export
- `from .submodule import *` — ワイルドカード re-export（再帰的に解決、ターゲットの `__all__` を尊重、循環検出あり）
- `__all__ = ["Name", ...]` — `__all__` による公開 API 宣言

### サードパーティ解析

`importlib.util.find_spec` でインストール済みパッケージの `__init__.py` を特定し、AST 解析で re-export を確認する。**ランタイム import は行わない**（副作用を避けるため）。

## 設計判断の記録

### 出力

違反 0 件でも `Found 0 errors (checked N files).` を出力する。チェック対象が 0 件だった状況（glob ミスなど）をユーザが検知できるようにするため。

### 安全性

- `--fix` は元ファイルを直接書き換える。git 管理下での使用を前提とし、diff 確認はユーザ側の責務。
- 名前衝突がある場合は修正しない（保守的に倒す）。自動修正の誤りより未修正の方が害が少ないという判断。
- 構文エラーファイルは警告してスキップする（全体を止めない）。

### ランタイム依存ゼロ

標準ライブラリのみで動作させる。ライブラリ依存を入れるかはこの制約に対する明示的な議論を経て判断する。

### CVE 対応方針

`pip-audit` を PR CI に入れない。理由: 単一の dev-dep CVE で全 PR がブロックされる運用リスク（#35 で具体化）の方が、CVE 検知遅延リスクより大きい。ランタイム依存ゼロのため dev-dep CVE はユーザに直接影響しない。

代替として Renovate (`renovate.json`) の `vulnerabilityAlerts.automerge: true` で OSV DB ベースの CVE を自動修正 PR 化し、GitHub Dependabot alerts を fallback として併用する。

## コーディング原則（プロジェクト固有）

ツールで強制できない・グローバル規約を上書きする項目のみ記載。ruff / ty の設定詳細は `pyproject.toml` を参照。

- **`Any` 禁止**: `object` または Protocol を使う
- **`# noqa` / `type: ignore` は最終手段**: 警告は設計で解決する。使う場合は PR で理由を明記
- **`cast()` は最小限**: 使う場合は理由をコメントに書く

## Git / リリース

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- main への直接 push 禁止
- SemVer: v1.0.0 未満は `feat:` → minor, `fix:` → patch、breaking change は極力避ける

リリースは Release Please + PyPI Trusted Publisher で自動化（`.github/workflows/release.yml`）。Conventional Commits から CHANGELOG とバージョンバンプ PR を自動生成し、マージで PyPI へ OIDC 公開される。

---

その他の情報は以下を参照:

- ユーザ向け README: [README.md](README.md)
- 依存・ツール設定: `pyproject.toml`
- CI / CD ワークフロー: `.github/workflows/`
- テストケース概要: [docs/test-cases.md](docs/test-cases.md)
