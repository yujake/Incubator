"""角色 G 的动作 `paper_package`（`draft/37` §59）：一次把论文包重渲染 → 重编译 → 核锚。

## 为什么需要这个动作（第九趟真机的读数）

第九趟主控把四处正文改动落盘了（`fs.edit`）、九节报告也过门了，只剩 `anchor` 一格：
`out/paper/main.tex` 的 sha 变了，而 `RENDER-ANCHOR.json` 里 `files.main.tex` 还是旧 sha、
`tables` 全 0 行 ⇒ `renderanchor` 判 `drifted`。主控自己诊断对了（它读了锚文件），
然后连派三次 `G.revise` —— 三次都没用，因为：

- `G.revise` / `G.refresh_markdown` / `G.render` 动的是稿件 markdown
  （`documents/<id>.md`），不是论文包；
- 能重渲染重编译的是三个工具：`doc.paper_render` / `doc.paper_compile` / `doc.paper_state`
  —— 而它们没有任何动作可以召唤。

于是"锚回到 `consistent`"在今天的编排层结构上做不到：与 §44.4（A/B 缺登记动作）
同一个形态，只是这次缺的是 G 这一边。这个动作补的就是那一格 ——
一次做完三件事，并把 `verdict` 与漂移条数一起回报（主控要的就是这两个读数）。

## 三件事的顺序不是随意的

`render → compile → state` 的顺序与 `doc.paper_build` 一致，理由在
`paperbuild` 的 docstring 里：锚的三维是"源表 / 渲染出的源文件 / 编译回执"，
先渲染再编译，最后核的那一次才回答"这份 PDF 是不是从磁盘上这份 tex 编的"。
把 `state` 放在最前面会让读数关于旧包（`draft/37` §16 那条"核锚的时机"）。

## 失败也要有读数

三段各自的失败分别归 `render_failed` / `compile_failed` / `state_failed`
（不折成一个 `ok: false`）—— 因为处置完全不同：渲染失败要查脚本与源表，
编译失败要查 LaTeX 工具链，而"核出来是 drifted"本身不是失败（它是读数）。
"""
from __future__ import annotations

from ._support import Any, Mapping, Path

class _PaperPackage:
    def paper_package(self, *, project: str = ".", timeout_sec: float | None = None,
                      render_script: str = "", compile_script: str = "") -> dict:
        """重渲染 → 重编译 → 核锚；返回三段各自的读数与最后的 `verdict`。

        `project` 是项目根（相对工作区；`.` = 工作区自己就是项目根）——
        与 `conductor.closing` 的 `project_dir` 同一口径（给论文包目录会把 `out/paper`
        拼两次，那是 2026-10-02 实测过的调用姿势错误）。
        """
        from ..tools import doc_tools as DT

        root = getattr(self.store, "root", None)
        sec = float(timeout_sec) if timeout_sec is not None else 300.0
        out: dict[str, Any] = {"project": project or ".", "timeout_sec": sec}

        # 顺序：渲染 → 编译 → 核锚（三段各自的实现都只有一份 —— `doc_tools` 里那三条，
        # 它们转发给 `paperbuild`）。为什么不直接调 `paperbuild.build`：它的第三段是
        # `anchor_check`（要项目脚本支持 `--check`），而本项目论文包的
        # `code/make_paper.py` 只写锚、不认 `--check`；核锚那条路的权威读数是
        # `doc.paper_state`（`renderanchor` 直接读锚文件）—— 与主控手上那份读数同源。
        rendered = DT._paper_render(root, project or ".", render_script, sec)
        out["render"] = {"ok": bool(rendered.ok), "kind": rendered.meta.get("kind", ""),
                         "error": rendered.error or ""}
        if not rendered.ok:
            out.update({"ok": False, "kind": "package_build_failed", "stage": "render",
                        "verdict": "", "drift": [],
                        "note": "渲染没走成 ⇒ 后面两步不再做（读了旧包没有意义）"})
            return out

        compiled = DT._paper_compile(root, project or ".", compile_script, sec)
        out["compile"] = {"ok": bool(compiled.ok), "kind": compiled.meta.get("kind", ""),
                          "error": compiled.error or ""}
        if not compiled.ok:
            out.update({"ok": False, "kind": "package_build_failed", "stage": "compile",
                        "verdict": "", "drift": [],
                        "note": "编译没走成 ⇒ 锚那一格不核（核了也是关于旧包的）"})
            return out
        out["steps"] = [{"step": "render", "ok": True}, {"step": "compile", "ok": True}]

        state = DT._paper_state(root, project or ".")
        if not state.ok:
            out.update({"ok": False, "kind": "state_failed", "verdict": "",
                        "drift": [], "error": state.error or ""})
            return out
        data = dict(state.data or {})
        out["steps"].append({"step": "anchor_check", "ok": data.get("verdict") == "consistent"})
        out.update({
            "ok": True,
            # `verdict` 是三态：`consistent` / `drifted` / `unknown`。
            # `drifted` 不是这个动作失败 —— 它是读数（说明包与台账还不是同一时点）。
            "kind": "" if data.get("verdict") == "consistent" else "anchor_not_consistent",
            "verdict": data.get("verdict"),
            "dimensions": data.get("dimensions"),
            "drift": list(data.get("drift") or [])[:10],
            "problems": list(data.get("problems") or [])[:5],
            "anchor_path": data.get("anchor_path"),
            "receipt_path": data.get("receipt_path"),
            "rendered_at": data.get("rendered_at"),
            "compiled_at": data.get("compiled_at"),
            "note": ("三段都做完了：`verdict=consistent` 才能写「包与库同一时点」；"
                     "`drifted` 要如实写进交付说明（它说明还有台账改动没进包）。"),
        })
        return out
