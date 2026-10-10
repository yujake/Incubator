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
        from ..tools import doc_tools as DT  # noqa: F401

        root = getattr(self.store, "root", None)
        sec = float(timeout_sec) if timeout_sec is not None else 300.0
        out: dict[str, Any] = {"project": project or ".", "timeout_sec": sec}

        # ---- `R2b-⑬`：不再手工串三件私有实现 —— 改调工具面 `doc.paper_build`
        #
        # 它内部就是 render → compile → anchor_check（`paperbuild.build`），顺序与这里
        # 原来那三段逐字一致，权威读数同样来自 `renderanchor.anchor_check`。
        # （本文件此前写"不直接调 `paperbuild.build`：它要项目脚本支持 `--check`"——
        # 那是旧口径：`--check` 那条路是 `doc.paper_anchor`，不是 `build`。）
        res = self.tools.call("doc.paper_build", project=project or ".",
                              render_script=render_script, compile_script=compile_script,
                              timeout_sec=sec)
        self.tool_calls.append({"tool": "doc.paper_build", "ok": res.ok, "error": res.error})
        # 成功时载荷在 `data` 里；失败时 `fail(..., **got)` 把同一份读数放进 `meta`
        # （`tools/base.fail` 的契约）⇒ 漂移这一档的读数不会因为我们改走工具面而丢掉。
        payload = dict(res.data) if isinstance(res.data, Mapping) else dict(res.meta or {})
        steps = [dict(s) for s in (payload.get("steps") or [])]
        names = [str(s.get("step") or "") for s in steps]
        out["steps"] = [{"step": n, "ok": bool(s.get("ok"))} for n, s in zip(names, steps)]
        for name in ("render", "compile"):
            one = next((s for s in steps if str(s.get("step")) == name), {})
            out[name] = {"ok": bool(one.get("ok")), "kind": str(one.get("kind") or ""),
                         "error": str(one.get("error") or one.get("problem") or "")}
            if not out[name]["ok"]:
                # 失败时把脚本自己的话带出来（T3 第 5 趟 `t3e` 的真机读数）。
                #
                # 那一趟 M 只看到「脚本没打印 `REPRO_RESULT:` 结论行 ⇒ 结论读不到」，
                # 于是把它误诊成"本工作区没有 `source/` 基线"（渲染器 docstring 里那句
                # "out/paper/main.tex 从 source/main.tex 逐字复制"），并据此改了交付形式
                # —— 而真正的原因藏在脚本的 stderr 里（`out/paper/` 目录不存在 ⇒ 写锚时
                # `FileNotFoundError`），它当时就在 `render` 这一步的读数里，只是被这一层
                # 抹掉了。与 `draft/39` §6.45（D56）同一条纪律："没查成"必须带上原因，
                # 否则下一步的动作会照着猜出来的原因走。
                out[name].update({
                    "exit_code": one.get("exit_code"),
                    "timed_out": bool(one.get("timed_out")),
                    "script": str(one.get("script") or ""),
                    "script_path": str(one.get("script_path") or ""),
                    "repro_found": one.get("repro_found"),
                    "stdout_tail": str(one.get("stdout_tail") or "")[-600:],
                    "stderr_tail": str(one.get("stderr_tail") or "")[-600:],
                    "note": "这一步没走成；脚本自己的 stdout/stderr 尾巴就在这两格里"
                            "（先看它们，别照着『可能的原因』猜）",
                })
        if not res.ok and (not names or names[-1] != "anchor_check"):
            stage = names[-1] if names else "render"
            out.update({"ok": False, "kind": "package_build_failed", "stage": stage,
                        "verdict": "", "drift": [],
                        "note": f"{stage} 没走成 ⇒ 后面两步不再做（读了旧包没有意义）"})
            return out

        anchor = dict(payload.get("anchor") or {})
        verdict = str(anchor.get("verdict") or "")
        # `doc.paper_anchor`：另一条核锚机制的读数（项目脚本 `--check` 那条）。
        # 它不是这一格的权威（权威是上面 `renderanchor` 那一份），只作为并列读数记下来
        # —— 这一笔同时把"声明了却从来没有生产调用者"那笔账还掉（`R2b-⑬`）。
        try:
            res_a = self.tools.call("doc.paper_anchor", project=project or ".",
                                    script=render_script, timeout_sec=sec)
            self.tool_calls.append({"tool": "doc.paper_anchor", "ok": res_a.ok,
                                    "error": res_a.error})
            meta_a = dict(res_a.meta or {})
            out["anchor_script"] = {
                "ok": bool(res_a.ok), "kind": str(meta_a.get("kind") or ""),
                "verdict": str(meta_a.get("verdict") or ""),
                "why": str(meta_a.get("why") or res_a.error or "")[:200],
                "note": "另一条核锚通道（脚本 --check）；权威读数在 `verdict` 那一格"}
        except Exception as exc:  # noqa: BLE001 - 并列读数坏了不许带走主读数
            # `kind` 这一格不是装饰：并列读数自己炸了仍然是"执行了、没成功"（`failed`），
            # 不是"这次调用不成立"（`refused`）—— 而这一格正是 `tests/test_refusals.py`
            # 用来把两者分开的登记键（没有它，那一行会被扫成 `kind=""`，
            # 于是这一条读数既没登记、又会被台账记成 ok）。
            out["anchor_script"] = {"ok": False, "kind": "anchor_script_failed",
                                    "problem": f"{type(exc).__name__}: {exc}"}

        if not steps or not verdict:
            out.update({"ok": False, "kind": "state_failed", "verdict": "", "drift": [],
                        "error": str(res.error or "核锚那一步没给出读数")})
            return out
        out.update({
            "ok": True,
            # `verdict` 是三态：`consistent` / `drifted` / `unknown`。
            # `drifted` 不是这个动作失败 —— 它是读数（说明包与台账还不是同一时点）。
            "kind": "" if verdict == "consistent" else "anchor_not_consistent",
            "verdict": verdict,
            "dimensions": anchor.get("dimensions"),
            "drift": list(anchor.get("drift") or [])[:10],
            "problems": list(anchor.get("problems") or [])[:5],
            "anchor_path": anchor.get("anchor_path"),
            "receipt_path": anchor.get("receipt_path"),
            "rendered_at": anchor.get("rendered_at"),
            "compiled_at": anchor.get("compiled_at"),
            "note": ("三段都做完了（经 `doc.paper_build` 一次走完）：`verdict=consistent` 才能写"
                     "「包与库同一时点」；`drifted` 要如实写进交付说明（它说明还有台账改动没进包）。"),
        })
        return out
