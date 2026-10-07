"""W0 拆包的「公开面不变」机械对账器（scratch 探针，不入库；被引用时登记进 .gitignore §14）。

用法（两趟）：
    # ① 拆包前（master HEAD，webui.py 还是单文件）抓基线
    python -B temp/_verify_w0.py capture
    # ② 拆包后（webui/ 包）对账
    python -B temp/_verify_w0.py check

它量的是**同一个真实工作区上的同一批读数**，不读源码文本猜语义：
  · 模块级公开名 + 签名（webui 的公开面）
  · `snapshot(ws)` 的顶层键，以及 sessions/runs/orphans/pending_questions/ledger/last_run
    各层键的并集（结构变了就露）
  · 源码里出现过的 URL 字面量集合（路由空间）
  · `render_root(state)` 与 `render_run(root, sid, state)` 的 sha256 与长度（HTML 面）

为什么用「键并集 + HTML 哈希」而不是逐字段值：值会随真实工作区变动（时间戳、花费），
键与 HTML 形状才是拆包不该动的部分。HTML 哈希若变，脚本会打 `HTML 变了` 并给长度差，
由人判「是不是 W0 有意改的」—— 不自动算过。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re
import sys

REPO = pathlib.Path(r"D:\Incubator")
SRC = REPO / "agentflow" / "src"
WS = REPO / "agentflow" / "projects" / "p9b-post-fix-replay"
OUT = REPO / "temp" / "_w0_public_face.json"

sys.path.insert(0, str(SRC))

import agentflow.webui as webui  # noqa: E402


def _keys_of(rows) -> list[str]:
    out: set[str] = set()
    if isinstance(rows, list):
        for one in rows:
            if isinstance(one, dict):
                out |= set(one.keys())
    return sorted(out)


def _sig(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "<no signature>"


def _html_shape(html: str) -> dict:
    """HTML 面的**形状**（不是逐字节哈希）。

    为什么不哈希：页面里带 `generated_at` 时间戳与"N 分钟前"的年龄字符串，
    每次渲染都会变 —— 哈希必然漂移，拿它当判据只会天天红。形状（用了哪些
    class、各标签出现多少次）才是拆包不该动的部分；长度只作参考打印。
    """
    classes: set[str] = set()
    for m in re.finditer(r'class="([^"]*)"', html):
        classes |= {c for c in m.group(1).split() if c}
    tags: dict[str, int] = {}
    for m in re.finditer(r"<([a-zA-Z][a-zA-Z0-9]*)", html):
        t = m.group(1).lower()
        tags[t] = tags.get(t, 0) + 1
    return {"classes": sorted(classes), "tags": dict(sorted(tags.items())), "len": len(html)}


def public_names(mod) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in dir(mod):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if inspect.isfunction(obj) or inspect.isclass(obj):
            # 拆包后 `agentflow.webui` 是包，函数住在 `agentflow.webui.state` 等子模块里，
            # 由 __init__.py 再导出 —— 所以前缀匹配而不是全等，否则会误判成"公开名全丢"。
            if not getattr(obj, "__module__", "").startswith("agentflow.webui"):
                continue  # 只是被 import 进来的别人的东西
            out[name] = _sig(obj)
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


def fingerprint() -> dict:
    state = webui.snapshot(WS)
    root_html = webui.render_root(state)
    runs = state.get("runs") or []
    sid = runs[0].get("sid") if runs and isinstance(runs[0], dict) else None
    run_html = None
    if sid:
        code, html = webui.render_run(WS, sid, state)
        run_html = {"status": code, **_html_shape(html)}
    files = module_files()
    return {
        "workspace": str(WS),
        "module_files": files,
        "public_names": public_names(webui),
        "snapshot_top_keys": sorted(state.keys()),
        "state_shape": {
            "sessions": {"n": len(state.get("sessions") or []), "keys": _keys_of(state.get("sessions"))},
            "runs": {"n": len(runs), "keys": _keys_of(runs)},
            "orphans": {"n": len(state.get("orphans") or []), "keys": _keys_of(state.get("orphans"))},
            "pending_questions": {"n": len(state.get("pending_questions") or []),
                                  "keys": _keys_of(state.get("pending_questions"))},
            "orphan_summary": sorted((state.get("orphan_summary") or {}).keys()),
            "ledger": sorted((state.get("ledger") or {}).keys()),
            "last_run": sorted((state.get("last_run") or {}).keys()) if state.get("last_run") else [],
            "problems_n": len(state.get("problems") or []),
        },
        "url_literals": url_literals([REPO / f for f in files]),
        "render_root": _html_shape(root_html),
        "render_run": run_html,
    }


def _diff(label: str, base, now, out: list[str]) -> None:
    if isinstance(base, dict) and isinstance(now, dict) and "classes" in base:
        # HTML 形状：比 class 与标签计数，长度只报不作判。
        print(f"  len  {label}: 基线 {base.get('len')} → 现在 {now.get('len')}（只作参考，页面含时间戳/年龄）")
        base = {k: v for k, v in base.items() if k != "len"}
        now = {k: v for k, v in now.items() if k != "len"}
    if base == now:
        print(f"  ok   {label}")
        return
    out.append(label)
    print(f"  变了 {label}")
    if isinstance(base, dict) and isinstance(now, dict):
        for k in sorted(set(base) | set(now)):
            if base.get(k) != now.get(k):
                print(f"       {k}: 基线={base.get(k)!r}")
                print(f"       {k}: 现在={now.get(k)!r}")
    elif isinstance(base, list) and isinstance(now, list):
        print(f"       只在基线: {sorted(set(map(str, base)) - set(map(str, now)))}")
        print(f"       只在现在: {sorted(set(map(str, now)) - set(map(str, base)))}")
    else:
        print(f"       基线={base!r}")
        print(f"       现在={now!r}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    now = fingerprint()
    if mode == "capture":
        OUT.write_text(json.dumps(now, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"基线已写 {OUT}")
        print(f"  模块文件: {now['module_files']}")
        print(f"  公开名: {len(now['public_names'])} 个；URL 字面量: {len(now['url_literals'])} 个")
        print(f"  snapshot 顶层键: {now['snapshot_top_keys']}")
        print(f"  render_root: {now['render_root']['len']} 字节 / {len(now['render_root']['classes'])} 个 class")
        return 0

    if not OUT.is_file():
        print(f"没有基线 {OUT} —— 先跑 capture")
        return 2
    base = json.loads(OUT.read_text(encoding="utf-8"))
    print(f"基线 {OUT}（工作区 {base['workspace']}）")
    print(f"现在模块文件: {now['module_files']}")
    changed: list[str] = []
    for label in ("public_names", "snapshot_top_keys", "state_shape", "url_literals",
                  "render_root", "render_run"):
        _diff(label, base.get(label), now.get(label), changed)
    hard = [c for c in changed if c in ("public_names", "snapshot_top_keys", "state_shape",
                                        "url_literals", "render_root", "render_run")]
    print()
    if hard:
        print(f"结论：公开面/页面形状**有硬变化** {hard} —— 拆包不许动这些（除非裁定明说）")
        return 1
    print("结论：公开面与页面形状逐项一致 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
