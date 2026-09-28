"""`E-6` 的回归判据：验收程序的三态不许被折叠成两态。

## 缺陷（2026-09-26 全面体检 · 子代理 E 发现）

`test/test2/run_acceptance.py` 的 `Runner._Ctx.__exit__` 旧实现是：

```python
if self.p.ok is None:
    self.p.ok = True
```

而 `Phase.ok` 的契约（`Phase` 类的 docstring 逐字）是三态：
`True` 通过 / `False` 失败 / `None` 未执行（"没跑"与"跑了没过"是两件事）。
那一行把 `None` 折叠成 `True`，于是：

1. 阶段里 `if missing: p.ok = None; return`（"未接线"）被记成 PASS；
2. `summary['not_run']` 恒为 0，终结打印里 `{None: 'N/A '}` 成了死分支；
3. 退出码只看 `return 0 if s['failed'] == 0 else 1` ⇒ 全部阶段都没接线也能 exit 0。

## 本文件守什么（两条判据，都不依赖真跑验收）

1. `__exit__` 不再替调用方下结论：只跑 `with` 块、块内一条断言都不做 ⇒ `ok` 保持 `None`。
2. "通过"这件事现在只由 `checkpoint()` 写：过 ⇒ `True`（除非已被标红），
   不过 ⇒ `False`，且此后再过也不许把 `False` 改回 `True`。
   （这一条是修法本身的另一半：把 `__exit__` 的兜底撤掉之后，
   若 `checkpoint()` 不写 `True`，全量验收会变成"10 个阶段全部 `N/A`" ——
   实测过，见 `temp/r2-e6-out2.txt`。）

## 为什么不用"跑一遍验收程序"当判据

那条路要起一个写 `test/test2/acceptance-run/` 的子进程（越出 `temp/` 的边界），
而且它跑一次要 2 分多钟。三态判据是本文件的对象，在进程内就能判定。
端到端那一条另有两份实测记录：`temp/r2-e6-out5.txt`（全量 ⇒ exit 0）
与 `temp/r2-e6-out6.txt`（`--phases P9` 单独跑 ⇒ exit 2）。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

#: 验收程序在伞形仓库的上一级（`D:\Incubator\test\test2\`），不在 agentflow 包里。
#: 所以按文件路径加载，不写 `import run_acceptance`（那要求把 test/test2 加进 sys.path）。
ACCEPTANCE = pathlib.Path(__file__).resolve().parents[2] / "test" / "test2" / "run_acceptance.py"


def _load():
    assert ACCEPTANCE.is_file(), f"找不到验收程序：{ACCEPTANCE}"
    spec = importlib.util.spec_from_file_location("_acceptance_for_e6_tests", ACCEPTANCE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


RA = _load()


def test_a_phase_that_asserts_nothing_stays_none() -> None:
    """负控（核心）：块内一条断言都没有 ⇒ `ok` 必须是 `None`，不是 `True`。

    这条在改前必红：改前 `__exit__` 会把 `None` 写成 `True`。
    """
    run = RA.Runner(store=None)
    with run.phase("PX", "负控：什么都不判") as p:
        pass
    assert p.ok is None, f"没有断言证据的阶段不许被写成 {p.ok!r} —— 那是把'没做'读成'通过'"
    assert p.to_dict()["ok"] is None


def test_an_exception_in_the_block_is_false_not_none() -> None:
    """负控 2：块内抛异常 ⇒ `ok=False`（"跑了没过"），且不许被折叠成 `None`。"""
    run = RA.Runner(store=None)
    with run.phase("PY", "负控：抛异常") as p:
        raise RuntimeError("注入的失败")
    assert p.ok is False, p.ok
    assert p.error and "注入的失败" in p.error


def test_a_passing_checkpoint_marks_the_phase_true() -> None:
    """正控：有一条通过的可判定断言 ⇒ 这一阶段算"跑了且过"。"""
    run = RA.Runner(store=None)
    with run.phase("PZ", "正控：一条断言通过") as p:
        run.checkpoint(p, True, "注入的通过断言")
    assert p.ok is True, "有断言通过却被记成未执行 ⇒ 全量验收会退化成全部 N/A"


def test_a_failing_checkpoint_marks_the_phase_false() -> None:
    """负控 3：断言不过 ⇒ `ok=False`，且失败不会被后面的通过断言洗掉。"""
    run = RA.Runner(store=None)
    with run.phase("PW", "负控：先失败后通过") as p:
        run.checkpoint(p, False, "注入的失败断言")
        assert p.ok is False
        run.checkpoint(p, True, "这一条通过，但不许把失败改回通过")
    assert p.ok is False, f"失败被后续的通过断言覆盖成 {p.ok!r} ⇒ 红绿取决于断言顺序"
    assert any("注入的失败断言" in n for n in p.notes), p.notes


def test_both_states_coexist_in_one_run() -> None:
    """一条把三态放在同一轮里的判据：pass / fail / 未断言 必须互不折叠。"""
    run = RA.Runner(store=None)
    with run.phase("A", "通过") as pa:
        run.checkpoint(pa, True, "ok")
    with run.phase("B", "失败") as pb:
        run.checkpoint(pb, False, "not ok")
    with run.phase("C", "未断言") as pc:
        pass
    summary = {
        "passed": sum(1 for x in run.phases if x.ok is True),
        "failed": sum(1 for x in run.phases if x.ok is False),
        "not_run": sum(1 for x in run.phases if x.ok is None),
    }
    assert summary == {"passed": 1, "failed": 1, "not_run": 1}, summary


@pytest.mark.parametrize("rel", ["run_acceptance.py"])
def test_the_exit_code_reads_the_third_state(rel: str) -> None:
    """判据的文本级守卫：退出码那一行必须同时看 `failed` 与 `not_run`。

    为什么要有文本级断言：退出码那条分支在 `main()` 里，进程内测它要真跑一遍验收。
    而这条判据最容易的退化方式恰恰是"有人把 `not_run` 那一支删掉、只留 `failed`"
    —— 那在 diff 里只是一行，任何端到端测试都会照旧通过（因为全量跑 `not_run=0`）。
    """
    text = ACCEPTANCE.read_text(encoding="utf-8")
    assert 'if s["failed"]:' in text, "退出码分支找不到（判据的落点变了，请更新本用例）"
    assert 'if s["not_run"]:' in text, (
        "退出码只看 failed ⇒ 全部阶段没接线也能 exit 0（E-6 复发）"
    )
    assert "return 2" in text, "第三态必须映射到退出码 2（没查成），不是 0"
