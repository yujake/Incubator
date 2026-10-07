"""W0 拆包的「公开面不变」机械对账器（scratch 探针，不入库；被引用时登记进 .gitignore §14）。

用法（两趟）：
    # ① 拆包前（master，webui.py 还是单文件）抓基线
    python -B temp/_verify_w0.py capture
    # ② 拆包后（webui/ 包）对账 —— 默认在 master 上量
    python -B temp/_verify_w0.py check
    # ③ 想在**某条线的工作树**上先量一遍（基线仍取自 master 那一份）：
    $env:VERIFY_REPO="D:\Incubator\temp\wt-w0"; python -B temp/_verify_w0.py check

它量的是**同一个真实工作区**上的同一批读数，不读源码文本猜语义：
  · 模块级公开名 + **结构化签名**（参数名/种类/默认值，逐个比）
  · `snapshot(ws)` 的顶层键，以及 sessions/runs/orphans/pending_questions/ledger/last_run
    各层键的并集（结构变了就露）
  · 源码里出现过的 URL 字面量集合（路由空间；**只作参考打印**，因为 Q1 起 `/run/` 变成
    `/run/{sid}`、静态前缀是新加的 —— 这类"表示法变化"不该当硬错）
  · `render_root(state)` 与 `render_run(root, sid, state)` 的**页面形状**（class 集 + 标签计数）

**四类判定**（我踩过的坑都在这里）：
  1. **硬**：公开名消失 / 参数被删或改名 / `snapshot()` 顶层键变 / 各层键并集变。
  2. **软**：只**新增**了带默认值的关键字参数、返回注解变、URL 字面量的增删、页面形状变 ——
     打印出来给人判（W0 的 T1 就是"给 `serve()` 加关键字参数"，那是设计要的，不是破坏）。
  3. **本次不可比**：真实工作区**不在这棵树里**（`agentflow/projects/` 是运行数据面、不入库，
    一条线的新工作树里必然没有它）⇒ `state_shape` 与页面形状**跳过**并大声说明，
    不算红也不算绿（否则会拿"空工作区"去比"有数据的工作区"，得出一堆假差异 —— 我踩过）。
  4. **零命中**：`snapshot()` 在**存在**的工作区上读出来是空的 ⇒ 那是硬错（读模型坏了），
     不是"不可比"。

为什么页面只比形状不比字节哈希：页面带 `generated_at` 时间戳与"N 分钟前"的年龄串，
每次渲染都变 ⇒ 哈希必然漂移，拿它当判据只会天天红。
"""

from __future__ import annotations

import inspect
import json
import os
import pathlib
import re
import sys

# 基线永远抓在 **master** 上（那个 JSON 是拆包前的读数，别被 `VERIFY_REPO` 带跑）；
# `VERIFY_REPO` 只改"这一趟要去哪个树里量"。
REPO = pathlib.Path(os.environ.get("VERIFY_REPO") or r"D:\Incubator")
SRC = REPO / "agentflow" / "src"
WS = REPO / "agentflow" / "projects" / "p9b-post-fix-replay"
OUT = pathlib.Path(r"D:\Incubator\temp\_w0_public_face.json")

sys.path.insert(0, str(SRC))

import agentflow.webui as webui  # noqa: E402


def _keys_of(rows) -> list[str]:
    out: set[str] = set()
    if isinstance(rows, list):
        for one in rows:
            if isinstance(one, dict):
                out |= set(one.keys())
    return sorted(out)


def _param_view(p: inspect.Parameter) -> dict:
    default = "<必填>"
    if p.default is not inspect.Parameter.empty:
        default = repr(p.default)
    return {"name": p.name, "kind": p.kind.name, "default": default}


def public_names(mod) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in dir(mod):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue
        # 拆包后 `agentflow.webui` 是包，函数住在 `agentflow.webui.state` 等子模块里，
        # 由 __init__.py 再导出 —— 所以前缀匹配而不是全等，否则会误判成"公开名全丢"。
        if not getattr(obj, "__module__", "").startswith("agentflow.webui"):
            continue
        try:
            sig = inspect.signature(obj)
            params = [_param_view(p) for p in sig.parameters.values()]
            ret = str(sig.return_annotation)
        except (TypeError, ValueError):
            params, ret = [], "<no signature>"
        out[name] = {"params": params, "return": ret}
    return dict(sorted(out.items()))


def url_literals(paths: list[pathlib.Path]) -> list[str]:
    pat = re.compile(r'"(/[A-Za-z0-9_./\-{}]*)"')
    seen: set[str] = set()
    for p in paths:
        for m in pat.finditer(p.read_text(encoding="utf-8")):
            seen.add(m.group(1))
    return sorted(seen)


def module_files() -> list[str]:
    out: list[str] = []
    one = SRC / "agentflow" / "webui.py"
    if one.is_file():
        out.append("agentflow/src/agentflow/webui.py")
    pkg = SRC / "agentflow" / "webui"
    if pkg.is_dir():
        for p in sorted(pkg.rglob("*.py")):
            out.append(str(p.relative_to(REPO)).replace("\\", "/"))
    return out


def _html_shape(html: str) -> dict:
    classes: set[str] = set()
    for m in re.finditer(r'class="([^"]*)"', html):
        classes |= {c for c in m.group(1).split() if c}
    tags: dict[str, int] = {}
    for m in re.finditer(r"<([a-zA-Z][a-zA-Z0-9]*)", html):
        t = m.group(1).lower()
        tags[t] = tags.get(t, 0) + 1
    return {"classes": sorted(classes), "tags": dict(sorted(tags.items())), "len": len(html)}


def fingerprint(with_workspace: bool) -> dict:
    files = module_files()
    out: dict = {
        "workspace": str(WS),
        "workspace_present": WS.is_dir(),
        "module_files": files,
        "public_names": public_names(webui),
        "url_literals": url_literals([REPO / f for f in files]),
    }
    if not with_workspace:
        return out
    state = webui.snapshot(WS)
    out["snapshot_top_keys"] = sorted(state.keys())
    runs = state.get("runs") or []
    sid = runs[0].get("sid") if runs and isinstance(runs[0], dict) else None
    run_html = None
    if sid:
        code, html = webui.render_run(WS, sid, state)
        run_html = {"status": code, **_html_shape(html)}
    out["state_shape"] = {
        "sessions": {"n": len(state.get("sessions") or []), "keys": _keys_of(state.get("sessions"))},
        "runs": {"n": len(runs), "keys": _keys_of(runs)},
        "orphans": {"n": len(state.get("orphans") or []), "keys": _keys_of(state.get("orphans"))},
        "pending_questions": {"n": len(state.get("pending_questions") or []),
                              "keys": _keys_of(state.get("pending_questions"))},
        "orphan_summary": sorted((state.get("orphan_summary") or {}).keys()),
        "ledger": sorted((state.get("ledger") or {}).keys()),
        "last_run": sorted((state.get("last_run") or {}).keys()) if state.get("last_run") else [],
        "problems_n": len(state.get("problems") or []),
    }
    out["render_root"] = _html_shape(webui.render_root(state))
    out["render_run"] = run_html
    return out


def _diff_names(base: dict, now: dict, hard: list[str], soft: list[str]) -> None:
    gone = sorted(set(base) - set(now))
    if gone:
        hard.append(f"公开名消失: {gone}")
        print(f"  硬  公开名消失: {gone}")
    fresh = sorted(set(now) - set(base))
    if fresh:
        soft.append(f"新增公开名: {fresh}")
    for name in sorted(set(base) & set(now)):
        b, n = base[name], now[name]
        if b == n:
            continue
        b_names = [p["name"] for p in b["params"]]
        n_names = [p["name"] for p in n["params"]]
        if b_names != n_names[: len(b_names)]:
            hard.append(f"{name} 的参数表变了: {b_names} → {n_names}")
            print(f"  硬  {name} 的参数表变了: {b_names} → {n_names}")
            continue
        added = n["params"][len(b["params"]):]
        if added and all(p["default"] != "<必填>" for p in added):
            soft.append(f"{name} 只新增了带默认值的参数: {[p['name'] for p in added]}")
            print(f"  软  {name} 只新增了带默认值的参数: {[p['name'] for p in added]}")
        elif added:
            hard.append(f"{name} 新增了必填参数: {[p['name'] for p in added]}")
            print(f"  硬  {name} 新增了必填参数: {[p['name'] for p in added]}")
        if b["return"] != n["return"]:
            soft.append(f"{name} 的返回注解变了: {b['return']} → {n['return']}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "capture":
        now = fingerprint(with_workspace=True)
        OUT.write_text(json.dumps(now, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"基线已写 {OUT}")
        print(f"  模块文件: {now['module_files']}")
        print(f"  公开名: {len(now['public_names'])} 个；URL 字面量: {len(now['url_literals'])} 个")
        print(f"  snapshot 顶层键: {now['snapshot_top_keys']}")
        print(f"  render_root: {now['render_root']['len']} 字节 / "
              f"{len(now['render_root']['classes'])} 个 class")
        return 0

    if not OUT.is_file():
        print(f"没有基线 {OUT} —— 先跑 capture")
        return 2
    base = json.loads(OUT.read_text(encoding="utf-8"))
    comparable = WS.is_dir()
    now = fingerprint(with_workspace=comparable)

    print(f"基线 {OUT}")
    print(f"这一趟量的树: {REPO}（模块文件 {len(now['module_files'])} 个）")
    hard: list[str] = []
    soft: list[str] = []

    _diff_names(base["public_names"], now["public_names"], hard, soft)
    if base["public_names"] == now["public_names"]:
        print("  ok  公开名与签名逐参数一致")

    if comparable:
        for label in ("snapshot_top_keys", "state_shape", "render_root", "render_run"):
            if base.get(label) == now.get(label):
                print(f"  ok  {label}")
                continue
            if label == "snapshot_top_keys":
                hard.append(label)
                print(f"  硬  {label} 变了: 基线={base.get(label)}")
                print(f"      现在={now.get(label)}")
            else:
                soft.append(label)
                print(f"  软  {label} 变了:")
                print(f"      基线={base.get(label)}")
                print(f"      现在={now.get(label)}")
        if not (now.get("state_shape") or {}).get("runs", {}).get("n"):
            hard.append("工作区存在但 snapshot 读出 0 趟运行")
            print("  硬  工作区存在但 snapshot 读出 0 趟运行 —— 那是读模型坏了，不是'不可比'")
    else:
        print(f"  跳过 state_shape / 页面形状：真实工作区不在这棵树里（{WS}）")
        print("       —— `agentflow/projects/` 是运行数据面、不入库，一条线的新工作树里必然没有它。")
        print("       —— 这不是红也不是绿：合并进 master 后（数据面在那里）必须再量一次。")

    if base.get("url_literals") != now.get("url_literals"):
        only_base = sorted(set(base.get("url_literals") or []) - set(now.get("url_literals") or []))
        only_now = sorted(set(now.get("url_literals") or []) - set(base.get("url_literals") or []))
        soft.append("url_literals")
        print(f"  软  url_literals 变了（只作参考）：只在基线={only_base} 只在现在={only_now}")
    else:
        print("  ok  url_literals")

    print()
    if hard:
        print(f"结论：**有硬变化** {hard} ⇒ 拆包不许动这些，先查是谁动的，别合并")
        return 1
    print(f"结论：硬读数全同 ✓" + (f"；软变化 {len(soft)} 处需人判：{soft}" if soft else "（且无软变化）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
