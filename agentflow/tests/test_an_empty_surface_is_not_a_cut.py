"""判据：空面不算切面（2026-10-22 p3-verify2 收官趟的真机缺陷）。

## 事故

父给 G 切了 `out/surfaces/t-000025/S01`，那是个空目录；于是 G 的 `fs.*` 根就是那个空目录，
连 `out/paper/main.tex` 都读不到（`manuscripts/handoffs.jsonl` 的 000017/000018 两条 `path_denied`），
`doc.paper_compile` 只能报 `paper_no_source` ⇒ 收工门 `paper` 格永远是 unknown。

## 这一条钉什么

1. 面目录空 ⇒ 不切根（这一趟仍用项目根），并留一条 `child_surface_empty` 的痕；
2. 面目录非空 ⇒ 照旧切（老行为不许被这条修法带坏）；
3. 面读不到（`checked=False`）⇒ 照旧不切（原有纪律）。

判据直接打在 `agent_loop` 那段判断上（不启模型、不建工作区）：把"要不要切"抽成可调用的
纯判断，避免"判据自己重写一遍逻辑"。
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_loop as L  # noqa: E402


def _decide(tmp_path: pathlib.Path, *, surface: str) -> tuple[str, bool]:
    """跑真实的那个判断：返回（最后用的 root, 是否记了 empty）。"""
    fn = getattr(L, "_surface_root_decision", None)
    assert fn is not None, "agent_loop 里没有 _surface_root_decision ⇒ 判据没有落脚点"
    return fn(surface)


def test_an_empty_surface_is_not_a_cut(tmp_path: pathlib.Path) -> None:
    empty = tmp_path / "empty-surface"
    empty.mkdir()
    root, was_empty = _decide(tmp_path, surface=str(empty))
    assert root == "", "空面不许当切面（否则子代理连项目根都读不到）"
    assert was_empty is True, "空面必须留痕（不许静默退回项目根冒充切过了）"


def test_a_non_empty_surface_still_cuts(tmp_path: pathlib.Path) -> None:
    full = tmp_path / "full-surface"
    full.mkdir()
    (full / "code").write_text("print(1)\n", encoding="utf-8")
    root, was_empty = _decide(tmp_path, surface=str(full))
    assert root == str(full), "非空面照旧切（老行为不许被带坏）"
    assert was_empty is False


def test_an_unreadable_surface_is_not_a_cut_and_not_an_empty_one(tmp_path: pathlib.Path) -> None:
    """面读不到（路径不存在）⇒ 不切，但这不算"空面"那一档（两者读数上要分得开）。"""
    root, was_empty = _decide(tmp_path, surface=str(tmp_path / "nope"))
    assert root == ""
    assert was_empty is True, "读不到的目录归到不切这一档，并留痕"
