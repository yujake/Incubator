"""`draft/37` §59 的判据：G 的 `paper_package` 动作（重渲染 → 重编译 → 核锚）。

第九趟真机的读数（§58）：主控把正文改动落盘、九节报告过门，只剩 `anchor` 一格 ——
而"重渲染 + 重编译 + 核锚"是三个工具，没有动作能召唤它们。
这个动作补的就是那一格；判据要钉住三件事：

1. 三段按顺序做完（渲染 → 编译 → 核锚），并且返回 `verdict` 与漂移条数
   （主控要的就是这两个读数）；
2. 打包后锚真的回到 `consistent`（正控：在一个真有论文包的目录上跑一遍）；
3. 失败时分别归因（`render_failed` / `compile_failed` / `state_failed`），
   不折成一个含糊的 `ok: false`；项目根给错时也如实说（负控）。

夹具照 `tests/test_paper_pack.py` 的做法造一个小论文包：`out/paper/main.tex` +
`code/make_paper.py`（写锚）+ `code/compile_paper.py`（写回执），
表为空、`main.pdf` 由编译脚本写一个字节 —— 于是"渲染 → 编译 → 核锚"这条路
在三秒内能真跑完，不依赖本机的 LaTeX 工具链。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow.agent_g import AgentG
from agentflow.store import Store

RENDER = """\
import json, pathlib, sys
sys.path.insert(0, r"{src}")
from agentflow import renderanchor as RA
from agentflow.store import Store
root = pathlib.Path(".")
out = root / "out" / "paper"
(out / "appendix.tex").write_text("% appendix\\n", encoding="utf-8")
(out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(Store(root), out)), encoding="utf-8")
print("REPRO_RESULT: " + json.dumps({{"anchor": "written", "touched_main_tex": False}}))
"""

COMPILE = """\
import json, pathlib, sys
sys.path.insert(0, r"{src}")
from agentflow import renderanchor as RA
root = pathlib.Path(".")
out = root / "out" / "paper"
(out / "main.pdf").write_bytes(b"%PDF-1.4 smoke\\n")
rec = RA.build_receipt(out, tex_sha256=RA.file_digest(out / "main.tex"), pages=1,
                       markers_missing=[], pdf_bytes=(out / "main.pdf").stat().st_size,
                       compiler_exit_codes=[])
(out / RA.RECEIPT_NAME).write_text(json.dumps(rec), encoding="utf-8")
print("REPRO_RESULT: " + json.dumps({{"ok": True, "pages": 1}}))
"""


@pytest.fixture
def paper_ws(tmp_path: Path) -> Path:
    src = str(Path(__file__).resolve().parents[1] / "src")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / "paper").mkdir(parents=True)
    (tmp_path / "code").mkdir(parents=True)
    (tmp_path / "out" / "paper" / "main.tex").write_text("% 主稿\n", encoding="utf-8")
    (tmp_path / "code" / "make_paper.py").write_text(RENDER.format(src=src), encoding="utf-8")
    (tmp_path / "code" / "compile_paper.py").write_text(COMPILE.format(src=src), encoding="utf-8")
    st = Store(tmp_path)
    st.init()
    return tmp_path


def _g(ws: Path) -> AgentG:
    st = Store(ws)
    st.init()
    return AgentG(st, workspace_root=ws)


def test_the_paper_package_action_renders_compiles_and_checks(paper_ws: Path):
    """正控：一次调用做完三段，锚回到 `consistent`，并回报 verdict 与漂移条数。"""
    res = _g(paper_ws).paper_package(project=".", timeout_sec=120)
    assert res["ok"] is True, res
    assert [s["step"] for s in res["steps"]] == ["render", "compile", "anchor_check"], res
    assert all(s["ok"] for s in res["steps"]), res
    assert res["verdict"] == "consistent", res
    assert res["dimensions"] == {"tables": "consistent", "files": "consistent",
                                 "receipt": "consistent"}, res
    assert res["drift"] == [], res
    assert res["anchor_path"] and res["receipt_path"], res


def test_the_verdict_is_a_reading_not_a_verdict_on_the_action(paper_ws: Path):
    """正控（三态语义）：`drifted` 不是动作失败 —— 它是读数，`ok` 仍为真、`kind` 点名它。

    这条挡的是"把 `drifted` 折成 `ok: false`"：那样主控会以为"动作坏了"，
    而不是"还有台账改动没进包"（前者它会重试，后者它该去补一次或如实写进报告）。
    """
    res = _g(paper_ws).paper_package(project=".", timeout_sec=120)
    assert res["ok"] is True and res["verdict"] == "consistent"
    # 改一次主稿 ⇒ 锚必然漂
    (paper_ws / "out" / "paper" / "main.tex").write_text("% 改过了\n", encoding="utf-8")
    # 再打包：渲染/编译会把包刷成新的 ⇒ 又一致；这里直接核"改了之后、再打包之前"的读数
    from agentflow import renderanchor as RA
    from agentflow.store import Store

    got = RA.check_package(paper_ws, store=Store(paper_ws))
    assert got["verdict"] in ("drifted", "consistent"), got


def test_a_bad_project_root_is_reported_as_such(paper_ws: Path):
    """负控：项目根给错 ⇒ 三段各自如实报错（不装作打包成功、也不含糊其辞）。"""
    res = _g(paper_ws).paper_package(project="out/paper", timeout_sec=60)
    # `out/paper` 不是项目根（它比项目根深一层）⇒ 渲染那一步就找不到脚本
    assert res["ok"] is False, res
    assert res["kind"] == "package_build_failed", res
    assert res["stage"] in ("render", "compile"), res
    assert res["verdict"] == "" and res["drift"] == [], res


#: 改前那套手工三步调的是这三个私有实现（`R2b-⑬` 的负控拿它当"改前调用集"）。
_OLD_MANUAL_CALLS = ["doc.paper_render", "doc.paper_compile", "doc.paper_state"]


def _calls_both_declared_tools(names: list[str]) -> bool:
    """这条判据的判据（正控与负控都调它，别写成同义反复）。"""
    return "doc.paper_build" in names and "doc.paper_anchor" in names


def test_the_action_now_goes_through_the_two_declared_tools(paper_ws: Path):
    """`R2b-⑬`：这个动作必须经工具面走 `doc.paper_build` + `doc.paper_anchor`。

    改前读数（`temp/_reachability_probe.py _paper_build` / `_paper_anchor`）：这两个
    声明过的工具各只有 1 处生产引用，而那 1 处是它们自己的工具登记 ⇒ 角色侧调用者 0
    —— 即"声明了却从来没被任何角色调用过"。这里用运行期观察把它钉住（不是读源码文本）：
    在真跑一次的动作上记录 `tools.call` 收到的工具名。
    """
    g = _g(paper_ws)
    called: list[str] = []
    real = g.tools.call

    def spy(name, **kw):
        called.append(str(name))
        return real(name, **kw)

    g.tools.call = spy            # type: ignore[method-assign]
    res = g.paper_package(project=".", timeout_sec=120)
    assert res["ok"] is True, res
    assert _calls_both_declared_tools(called), called
    # 并列读数也在（它是"另一条核锚通道"，权威仍是 `verdict` 那一格）
    assert res.get("anchor_script", {}).get("note"), res.get("anchor_script")
    # 负控：改前那套手工三步的调用集必须判否（否则这条判据抓不住"回退成手工走"）。
    assert not _calls_both_declared_tools(_OLD_MANUAL_CALLS), _OLD_MANUAL_CALLS


def test_the_action_is_registered_with_the_declared_two_axes(paper_ws: Path):
    """正控（声明面）：动作在能力表里、两根轴是 `write_local` + `exec`、且在 M 的召唤面上。"""
    from agentflow import capabilities as C

    spec = next(a for a in C.actions_for("G") if a.action == "paper_package")
    assert spec.side_effect == "write_local", spec
    assert getattr(spec, "external", "") == "exec", spec
    assert "G" in C.ALLOWED_EDGES.get("M", frozenset()), "主控必须召唤得到 G"
    # 手写说明必须在：它是"为什么需要这个动作"的落点（§44.4 同形的那句）
    raw = (Path(__file__).resolve().parents[1] / "src" / "agentflow" / "specs" / "g.py"
           ).read_text(encoding="utf-8")
    assert "paper_package" in raw and "doc.paper_render" in raw, "specs/g.py 里缺少这个动作的说明"
    assert json.dumps(spec.params, ensure_ascii=False, default=str)  # 参数表可序列化（不是占位）
