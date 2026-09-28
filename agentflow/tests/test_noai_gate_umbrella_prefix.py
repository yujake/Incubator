"""`R2-N2` 的回归判据：伞形仓库前缀不许把"台账里登记过的路径"读成"从没登记"。

## 缺陷（2026-09-26 本轮跑 `release_all --since HEAD` 时实测）

本仓库的 `.git` 在上一级（交付物在 `agentflow/` 子目录里），所以
`git diff --name-only` 给出的是仓库根相对路径（形如 `agentflow/.noai-paths`）。
`tools/release_all.py` 把这些原样交给 `scripts/noai_gate.py --check-approvals --paths …`，
而旧版 `_repo_rel_key` 走 `(repo / "agentflow/.noai-paths")` ⇒ 指向
`agentflow/agentflow/...`（不存在）⇒ 键落回 `agentflow/.noai-paths`，
而台账里的键是 `.noai-paths` ⇒ 门报 `unregistered`（"从没登记"）。

实测对照（同一个文件、同一版内容）：

    --paths .noai-paths             ⇒ unapproved / insufficient_reviewers（0/2 名 reviewer）
    --paths agentflow/.noai-paths   ⇒ unapproved / unregistered   ← 键错了

`unregistered` 在报告里读作"这个文件从来没登记过"，而真相是"它登记过、只是没人签字"。
两种情形的处置完全不同（前者要 `--baseline`，后者要 `--approve`），所以这不是措辞问题。

## 本文件守什么

1. 两种写法给出同一个键（也就是同一档理由）；
2. 真没登记过的路径仍然能报出"没登记"这一档 —— 别把判据做成"永远报 insufficient"。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

GATE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "noai_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("_gate_for_prefix_tests", GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load()
REPO = GATE.resolve().parents[1]


def test_umbrella_prefixed_path_maps_to_the_same_key_as_the_bare_one() -> None:
    """关键判据：`agentflow/<p>` 与 `<p>` 必须给出同一个台账键。

    这条在改前必红：改前前者是 `agentflow/.noai-paths`，后者是 `.noai-paths`。
    """
    bare = G._repo_rel_key(".noai-paths", REPO)
    prefixed = G._repo_rel_key(f"{REPO.name}/.noai-paths", REPO)
    assert bare == prefixed == ".noai-paths", (bare, prefixed)


def test_the_prefixed_form_resolves_to_the_real_file() -> None:
    """`_target_path` 也要同意同一个答案（否则"读 hash"与"查键"两处会分家）。"""
    bare = G._target_path(".noai-paths", REPO)
    prefixed = G._target_path(f"{REPO.name}/.noai-paths", REPO)
    assert bare.resolve() == prefixed.resolve() == (REPO / ".noai-paths").resolve()
    assert bare.is_file()


def test_a_genuinely_unregistered_zone_path_still_reports_unregistered() -> None:
    """负控：清单里没有的路径仍必须报 `unregistered`（别把判据做成永远 insufficient）。

    用清单里确实不存在的路径（`docs/` 下的一个 md）当样本 ——
    它连 `check_paths` 都不命中，所以这里直接查台账键。
    """
    key = G._repo_rel_key("docs/INDEX.md", REPO)
    assert key == "docs/INDEX.md"
    ledger = G.load_ledger(G.ledger_default_path(REPO))
    assert ledger.entry_for(key) is None, "夹具前提：这个路径不该在台账里"


def test_the_prefixed_form_of_a_never_registered_path_is_also_absent() -> None:
    """伞形前缀 + 从没登记过的路径 ⇒ 两种写法都查不到（前缀处理不是"什么都查得到"）。"""
    bare = G._repo_rel_key("docs/INDEX.md", REPO)
    prefixed = G._repo_rel_key(f"{REPO.name}/docs/INDEX.md", REPO)
    assert bare == prefixed == "docs/INDEX.md"
    ledger = G.load_ledger(G.ledger_default_path(REPO))
    assert ledger.entry_for(prefixed) is None


def test_a_path_whose_first_segment_merely_looks_like_the_repo_is_untouched() -> None:
    """边界：只在第一段恰好等于仓库目录名时才剥一层。

    `agentflow/agentflow/x` 这种"仓库里真有同名子目录"的情形不许被误剥成 `agentflow/x`
    —— 那会把两条不同的路径折叠成一个键。这里用盘上真实存在的
    `agentflow/src/...` 形态的反例判：`src/agentflow/verify.py` 的首段是 `src`，
    不是仓库名，所以必须原样保留。
    """
    assert G._repo_rel_key("src/agentflow/verify.py", REPO) == "src/agentflow/verify.py"
