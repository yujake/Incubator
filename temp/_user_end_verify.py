"""用户端的**独立验收脚手架**（我自己走一遍人机环，不依赖子任务自己的判据）。

为什么要它：两条实现线各自会写自己的判据，但"判据是它们写的"这件事本身不足以说明
接口对得上 —— 这个脚本从**外面**按规格走一遍：会话形状 → CLI（inbox/answer）→
循环停着 → 续跑 → GUI（HTTP）→ 投影性。任何一步与规格不符，它报"SPEC 不符：…"，
而不是崩掉，方便我逐条定位。

用法（`agentflow/` 下）：
    python -B ..\\temp\\_user_end_verify.py                # 全部腿
    python -B ..\\temp\\_user_end_verify.py channel loop   # 只跑某几条腿

腿：`channel`（事件形状 + CLI）、`loop`（停着/不烧钱/续跑）、`gui`（HTTP 往返）、
`projection`（同一份盘上数据渲染两次一致、改盘则变）。
不联网、不花钱（模型是脚本化的）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1] / "agentflow"
sys.path.insert(0, str(REPO / "src"))

from agentflow import sessions as SS          # noqa: E402
from agentflow import userio as U             # noqa: E402
from agentflow.store import Store             # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, leg: str, what: str) -> None:
    RESULTS.append((bool(ok), leg, what))
    print(("  [ok] " if ok else "  [SPEC 不符] ") + what)


def _ws(name: str = "ws") -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"userend-{name}-"))
    (root / "data").mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    return root


def _events(root: pathlib.Path, sid: str) -> list[dict]:
    ev, _p = SS.read_session(root, sid=sid)
    return ev


_API_FORM = {"form": ""}


def _ask(root: pathlib.Path, *, role: str, question: str, sid: str, header: str = "",
         options: tuple = (), multi_select: bool = False):
    """问一条问题：**新 API 优先，旧 API 兜底**，并记下这次用的是哪一版。

    为什么要兜底：两条实现线并行，GUI 那条可以先验；而"这次走的是哪一版 API"
    必须记下来 —— 否则读数会含糊（同一条 `[ok]` 在两种口径下含义不同）。
    """
    kw = {"timeout_sec": 0.0, "sid": sid}
    try:
        out = U.ask_user(root, role=role, question=question, header=header,
                         options=options, multi_select=multi_select, **kw)
        _API_FORM["form"] = "new"
        return out
    except TypeError:
        flat = tuple(o["label"] if isinstance(o, dict) else o for o in options)
        out = U.ask_user(root, role=role, question=question, options=flat, **kw)
        _API_FORM["form"] = "old"
        return out


# ---------------------------------------------------------------- 腿 1：通道与 CLI

def leg_channel() -> None:
    leg = "channel"
    root = _ws("channel")
    out = U.ask_user(root, role="M", question="用哪个口径？", header="口径",
                     options=["第一档：严格", {"label": "第二档：宽松",
                                              "description": "允许近似"}],
                     timeout_sec=0.0, sid="t")
    check(getattr(out, "state", "") == "pending", leg,
          f"问了没答 ⇒ state 应为 pending，实得 {getattr(out, 'state', None)!r}")
    q = _events(root, "t")
    ask = next((e for e in q if e.get("kind") == "user_question"), None)
    check(ask is not None, leg, "user_question 事件落盘")
    if ask:
        check(str(ask.get("header") or "") == "口径", leg, "事件里有 header")
        opts = ask.get("options") or []
        check(isinstance(opts, list) and all(isinstance(o, dict) for o in opts), leg,
              f"选项落成 {{label,description}}（实得 {opts!r}）")
        check(any("description" in o for o in opts if isinstance(o, dict)), leg,
              "至少一个选项带 description")
    pend = U.pending_questions(root, sid="t")
    check([x.qid for x in pend] == [out.qid], leg, "pending_questions 看得到它")

    cli = None  # 用 _cli() 备用
    r = _cli(root, "inbox")
    check(r.returncode == 0 and out.qid in (r.stdout or ""), leg,
          f"`inbox`（不给 --sid）看得到这条（rc={r.returncode}）")
    check("t" in (r.stdout or ""), leg, "`inbox` 表里有会话号")

    r = _cli(root, "answer", out.qid, "--select", "第二档：宽松", "--sid", "t")
    check(r.returncode == 0, leg, f"`answer --select` 成功（rc={r.returncode}: {r.stderr[:120]})")
    ans = next((e for e in _events(root, "t") if e.get("kind") == "user_answer"), None)
    check(ans is not None, leg, "user_answer 事件落盘")
    if ans:
        check(ans.get("selected") == ["第二档：宽松"], leg,
              f"事件里带 selected（实得 {ans.get('selected')!r}）")
        check("custom" in ans, leg, "事件里有 custom 字段（哪怕是空）")
    replies = U.read_replies(root, sid="t")
    check(bool(replies) and "第二档" in str(replies[0].get("answer")), leg,
          f"read_replies 的统一文本读得回来（实得 {replies[0].get('answer') if replies else None!r}）")
    check(U.pending_questions(root, sid="t") == [], leg, "答完就从待答清单里消失")

    # 负控：答一个不存在的号 ⇒ 退出码 2，且不许落事件
    before = len([e for e in _events(root, "t") if e.get("kind") == "user_answer"])
    r = _cli(root, "answer", "q9999", "乱答", "--sid", "t")
    after = len([e for e in _events(root, "t") if e.get("kind") == "user_answer"])
    check(r.returncode == 2 and before == after, leg,
          f"不存在的号 ⇒ 退出码 2 且不落事件（rc={r.returncode}, {before}→{after}）")

    # 负控：无人值守档 ⇒ 确定性拒绝，问题不许落盘
    root2 = _ws("channel-noask")
    old = getattr(U, "ASK_POLICY", None)
    try:
        U.ASK_POLICY = "never"                      # type: ignore[attr-defined]
        got = U.ask_user(root2, role="M", question="要不要继续？", timeout_sec=0.0, sid="t")
        check(getattr(got, "state", "") == "refused" and got.problem == "ask_refused", leg,
              f"无人值守档 ⇒ refused/ask_refused（实得 {got.to_dict()}）")
        check(U.pending_questions(root2, sid="t") == [], leg, "被拒的问题不落待答清单")
    finally:
        if old is not None:
            U.ASK_POLICY = old                      # type: ignore[attr-defined]


# ---------------------------------------------------------------- 腿 2：循环停着 + 续跑

class _Scripted:
    """照剧本回文本（不联网）。"""

    spec = type("S", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, prompt, *, scope="", system=None, max_tokens=None, tools=None,
                 tool_choice="auto", **kw):
        self.calls += 1
        text = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        return type("R", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                              "error_detail": "", "error_kind": ""})()


def _wire(root: pathlib.Path, gateway, *, sid: str, max_steps: int = 6):
    from agentflow.agent_loop import LlmBackend
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.llmseam import LlmSeam
    from agentflow.tools import build_registry

    st = Store(root)
    st.init()
    seam = LlmSeam(role="M", session_root=root, gateway=gateway, price=(0.0, 0.0), sid=sid)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda role: seam, max_steps=max_steps, store=st, sid=sid)
    cond = Conductor(st, policy=None, backend=backend)
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    return st, cond, built.registry, seam


def leg_gui() -> None:
    leg = "gui"
    try:
        from agentflow import webui
    except Exception as exc:  # noqa: BLE001
        check(False, leg, f"import agentflow.webui 失败：{type(exc).__name__}: {exc}")
        return
    root = _ws("gui")
    _ask(root, role="M", question="要保留哪几处改动？<script>alert(1)</script>",
         header="取舍", options=({"label": "全保留", "description": "三处都留"},
                                 {"label": "回退第二处", "description": "只留两处"}),
         multi_select=True, sid="gui1")
    _ask(root, role="H", question="另一个会话里的一条", sid="gui2")
    print(f"  （这次用的提问 API 形态：{_API_FORM['form']}）")
    srv = webui.serve(root, port=0)
    import threading

    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        check("要保留哪几处改动" in html, leg, "GET / 里出现待答问题")
        check("全保留" in html and "三处都留" in html, leg, "选项的 label 与 description 都在")
        check("&lt;script&gt;" in html and "<script>alert(1)</script>" not in html, leg,
              "用户/模型文本被 HTML 转义")
        check("gui1" in html and "gui2" in html, leg, "跨会话两条都在（不按会话过滤）")
        with urllib.request.urlopen(base + "/api/state", timeout=10) as resp:
            state = json.loads(resp.read().decode("utf-8"))
        check(isinstance(state.get("pending_questions"), list)
              and len(state["pending_questions"]) == 2, leg,
              f"/api/state 报 2 条待答（实得 {len(state.get('pending_questions') or [])}）")

        data = urllib.parse.urlencode({"qid": "q0001", "sid": "gui1",
                                       "selected": "全保留", "custom": ""}).encode()
        req = urllib.request.Request(base + "/answer", data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                code, body = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:      # 3xx 会被 urllib 跟随，4xx/5xx 抛
            code, body = e.code, e.read().decode("utf-8")
        check(code in (200, 303), leg, f"POST /answer 成功（实得 {code}）")
        check(U.pending_questions(root, sid="gui1") == [], leg, "GUI 提交后那条问题消失")
        ans = next((e for e in _events(root, "gui1") if e.get("kind") == "user_answer"), None)
        # 严格口径（DSH）：选项归 `selected`、自写归 `custom`。
        # 这条判据原来写成"selected 或 custom 之一"，于是漏掉了"点了选项却记成自写"
        # 那个真缺陷 —— 松的判据等于没判（这条注释留着，免得下一个人再写松）。
        check(ans is not None and ans.get("selected") == ["全保留"], leg,
              f"选了选项 ⇒ 落在 selected 里（实得 {(ans or {}).get('selected')!r}）")
        check(ans is not None and not str((ans or {}).get("custom") or "").strip(), leg,
              f"只选了选项时 custom 应为空（实得 {(ans or {}).get('custom')!r}）")

        # 负控：不存在的号 ⇒ 4xx，且不落新事件
        n0 = len([e for e in _events(root, "gui2") if e.get("kind") == "user_answer"])
        data = urllib.parse.urlencode({"qid": "q9999", "sid": "gui2", "custom": "x"}).encode()
        req = urllib.request.Request(base + "/answer", data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                bad = resp.status
        except urllib.error.HTTPError as e:
            bad = e.code
        n1 = len([e for e in _events(root, "gui2") if e.get("kind") == "user_answer"])
        check(bad >= 400 and n0 == n1, leg, f"不存在的号 ⇒ 4xx 且不落事件（{bad}, {n0}→{n1}）")
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------- 腿 4：投影而非缓存

def leg_projection() -> None:
    leg = "projection"
    try:
        from agentflow import webui
    except Exception as exc:  # noqa: BLE001
        check(False, leg, f"import agentflow.webui 失败：{type(exc).__name__}: {exc}")
        return
    root = _ws("projection")
    _ask(root, role="M", question="第一条", sid="p1")
    srv = webui.serve(root, port=0)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        def page() -> str:
            with urllib.request.urlopen(base + "/", timeout=10) as r:
                return r.read().decode("utf-8")

        a, b = page(), page()
        check(a == b, leg, "同一份盘上数据渲染两次逐字节一致（投影，不掺页面状态）")
        _ask(root, role="M", question="第二条（新加的）", sid="p1")
        c = page()
        check("第二条" in c and c != a, leg, "盘上多了一条 ⇒ 页面必须变（不许缓存）")

        # 一趟的详情页：把已落盘的事件渲染成可回放的卡片；不存在的 sid ⇒ 404
        SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "审阅并 polish 这篇论文"},
                  sid="p1")
        SS.append(root, {"kind": "agent_step", "role": "M", "index": 0, "shape": "tool",
                         "payload": {"name": "fs_list", "args": {"path": "."}},
                         "result": {"tool": "fs.list", "ok": True, "data": {"total": 3}}}, sid="p1")
        SS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final"}, sid="p1")
        # 交付说明也要在这一页上原样看得到（规格：`out/review/REPORT.md` 存在就渲染）
        rep = root / "out" / "review" / "REPORT.md"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text("# 交付说明\n\n## 一、任务与范围\n\n读数：<b>不该被当 HTML</b>\n",
                       encoding="utf-8", newline="\n")
        with urllib.request.urlopen(base + "/run/p1", timeout=10) as r:
            run_html = r.read().decode("utf-8")
        check("fs.list" in run_html or "fs_list" in run_html, leg,
              "GET /run/<sid> 渲染出步骤卡片（含工具名）")
        check("final" in run_html, leg, "详情页里有停止理由")
        check("交付说明" in run_html, leg, "详情页里显示这一趟的交付说明")
        check("&lt;b&gt;" in run_html, leg, "交付说明按原文渲染（HTML 转义，不当标签）")
        try:
            with urllib.request.urlopen(base + "/run/nope-session", timeout=10) as r:
                missing = r.status
        except urllib.error.HTTPError as e:
            missing = e.code
        check(missing == 404, leg, f"不存在的 sid ⇒ 404（实得 {missing}）")
    finally:
        srv.shutdown()
        srv.server_close()


def leg_tokens() -> None:
    """令牌自洽：APP_CSS 用到的每个 `--dsw-*` 都必须在搬来的 THEME_CSS 里有定义。

    这条是"照搬 DSH 令牌"这件事的机械判据：漏抄一族别名时，浏览器只会静默回退
    （颜色没了、但也看不出错），而人眼很难从一张截图里发现。
    """
    leg = "tokens"
    import re

    try:
        from agentflow.web import assets
    except Exception as exc:  # noqa: BLE001
        check(False, leg, f"import agentflow.web.assets 失败：{type(exc).__name__}: {exc}")
        return
    theme = getattr(assets, "THEME_CSS", "")
    app = getattr(assets, "APP_CSS", "")
    check(bool(theme) and bool(app), leg, "THEME_CSS / APP_CSS 都在")
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", theme))
    used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", app))
    missing = sorted(used - defined)
    check(not missing, leg, f"APP_CSS 用到的令牌全部有定义（缺 {missing}）")
    check(any(t.startswith("--dsw-static-") for t in defined), leg, "搬来了原始色板 --dsw-static-*")
    check(sum(1 for t in defined if t.startswith("--dsw-alias-")) >= 60, leg,
          f"搬来了语义别名（{sum(1 for t in defined if t.startswith('--dsw-alias-'))} 条）")
    check(theme.count("data-ds-dark-theme") >= 2, leg, "明暗两套都在（static + alias 各一段）")
    for t in ("--ds-ease-in-out", "--ds-transition-duration", "--ds-font-family-code"):
        check(t in defined, leg, f"运动/字体令牌在：{t}")
    check("corner-shape" in theme or "--dsw-corner-shape" in defined, leg, "superellipse 圆角那一套在")
    check(not re.search(r"#[0-9a-fA-F]{3,6}\b", app), leg,
          "APP_CSS 里没有字面色值（只许用令牌）")
    check(len(used) >= 8, leg, f"APP_CSS 至少用了 8 个令牌（实得 {len(used)}）")


def _cli(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    """跑一次 CLI 子进程（cwd 与 PYTHONPATH 都要给对，否则 `agentflow.cli` 找不到）。

    第一版漏了 env，于是"CLI 全红"其实是脚手架自己的错 —— 判据红了要先怀疑工具，
    这条注释就是那次教训。
    """
    import os

    env = dict(os.environ)
    env.update({"PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    return subprocess.run([sys.executable, "-B", "-m", "agentflow.cli", "--root", str(root),
                           *args], cwd=str(REPO), env=env, capture_output=True,
                          text=True, encoding="utf-8")


def leg_loop() -> None:
    """停着 / 不烧钱 / 人答了就接着跑 / 续跑 / 拒续。

    这一腿故意分两种等待口径（用户裁定"就停着"）：
      · `user_timeout_sec=0` —— 问了就交还控制权（无人值守与自动化那一档）；
      · 默认（`None` = 一直等）—— **真的阻塞**：人一答，同一趟进程内接着跑完。
    第二种才是用户实测时的形态，所以它单独一条腿、并且在**另一个线程**里跑。
    """
    leg = "loop"
    import threading
    import time

    from agentflow import agent_loop as AL

    ASK = json.dumps({"ask_user": {"question": "三处改动要不要保留？", "header": "取舍",
                                   "options": [{"label": "保留（Recommended）",
                                                "description": "按现状交"},
                                               {"label": "回退", "description": "还原基线"}]}},
                     ensure_ascii=False)
    DONE = json.dumps({"final": "收到回答，收工", "evidence": []}, ensure_ascii=False)
    NEVER = json.dumps({"final": "（若被调用说明没停住）", "evidence": []}, ensure_ascii=False)

    # ---- A. 问了就交还控制权（user_timeout_sec=0）：停住 + 不再调模型 + 落检查点
    root = _ws("loop-stop")
    gw = _Scripted([ASK, NEVER, DONE])
    st, cond, reg, seam = _wire(root, gw, sid="t")
    run = AL.run_role("M", "审阅这篇论文", store=st, registry=reg, conductor=cond, seam=seam,
                      workspace_root=str(root), sid="t", max_steps=6, from_env=False,
                      user_timeout_sec=0.0)
    check(run.stop_reason == "waiting_for_user", leg,
          f"问了没答 ⇒ stop_reason=waiting_for_user（实得 {run.stop_reason!r}）")
    qid = str(getattr(run, "waiting_for", "") or "")
    check(bool(qid), leg, f"run 上记下了卡在哪个 qid（实得 {qid!r}）")
    check(gw.calls == 1, leg, f"停着时不再调模型（调用数 {gw.calls}，应为 1）")
    cp = AL.load_run_checkpoint(root, "M", "t")
    check(isinstance(cp, dict) and str(cp.get("waiting_for") or "") == qid, leg,
          f"停下来时写了检查点并记下在等谁（实得 {cp if not isinstance(cp, dict) else {k: cp.get(k) for k in ('stop_reason','waiting_for','step')}}）")

    # ---- B. 没答就续跑：明确报"还在等"，且不许调模型
    run2 = AL.run_role("M", "审阅这篇论文", store=st, registry=reg, conductor=cond, seam=seam,
                       workspace_root=str(root), sid="t", max_steps=6, from_env=False,
                       resume=True, user_timeout_sec=0.0)
    check(run2.stop_reason in ("waiting_for_user", "still_waiting"), leg,
          f"没答就 --resume ⇒ 明确还在等（实得 {run2.stop_reason!r}）")
    check(gw.calls == 1, leg, f"没答就 --resume 不许再调模型（调用数 {gw.calls}）")

    # ---- C. 任务指纹不符：拒续
    run3 = AL.run_role("M", "换一个完全不同的任务", store=st, registry=reg, conductor=cond,
                       seam=seam, workspace_root=str(root), sid="t", max_steps=6,
                       from_env=False, resume=True, user_timeout_sec=0.0)
    check(run3.stop_reason == "checkpoint_mismatch", leg,
          f"任务指纹不符 ⇒ checkpoint_mismatch（实得 {run3.stop_reason!r}）")
    check(gw.calls == 1, leg, f"拒续时也不许调模型（调用数 {gw.calls}）")

    # ---- D. 答了再续跑：跑到 final，且记下 resumed_from
    check(U.answer_question(root, qid=qid, selected=["保留（Recommended）"], sid="t") == "", leg, "写回答")
    run4 = AL.run_role("M", "审阅这篇论文", store=st, registry=reg, conductor=cond, seam=seam,
                       workspace_root=str(root), sid="t", max_steps=6, from_env=False,
                       resume=True, user_timeout_sec=0.0)
    check(run4.stop_reason == "final", leg, f"答了再续跑 ⇒ final（实得 {run4.stop_reason!r}）")
    starts = [e for e in _events(root, "t") if e.get("kind") == "agent_run_start"]
    check(any("resumed_from" in e for e in starts), leg,
          "续跑那趟的 agent_run_start 带 resumed_from")
    rebuilt = AL.resume_transcript(root, "M", "t", task="审阅这篇论文")
    text = rebuilt[0] if isinstance(rebuilt, tuple) else rebuilt
    check("[第 1 步]" in str(text), leg, "resume_transcript 重建出逐步文本")
    other = AL.resume_transcript(root, "M", "t", task="另一个任务")
    other_text = other[0] if isinstance(other, tuple) else other
    check(str(other_text).strip() == "", leg, "指纹不符时重建为空（不许拿别人的转录续跑）")

    # ---- E. 真的"停着"：默认（一直等）⇒ 阻塞但不烧钱；人一答，同一趟接着跑完
    root2 = _ws("loop-block")
    gw2 = _Scripted([ASK, DONE])
    st2, cond2, reg2, seam2 = _wire(root2, gw2, sid="t")
    box: dict = {}

    def _run_blocking() -> None:
        try:
            box["run"] = AL.run_role("M", "审阅这篇论文", store=st2, registry=reg2,
                                     conductor=cond2, seam=seam2, workspace_root=str(root2),
                                     sid="t", max_steps=6, from_env=False)
        except Exception as exc:  # noqa: BLE001
            box["exc"] = exc

    th = threading.Thread(target=_run_blocking, daemon=True)
    th.start()
    time.sleep(1.5)
    check(th.is_alive(), leg, "默认等待口径下，问了就**阻塞**住（不返回、不空转）")
    check(gw2.calls == 1, leg, f"阻塞期间不烧钱（模型调用数 {gw2.calls}，应为 1）")
    pend = U.pending_questions(root2, sid="t")
    check(len(pend) == 1, leg, f"阻塞期间问题在待答清单里（实得 {len(pend)} 条）")
    if pend:
        check(U.answer_question(root2, qid=pend[0].qid, custom="保留，按现状交", sid="t") == "", leg,
              "「另一个终端」写回答")
    th.join(timeout=25)
    got = box.get("run")
    check(got is not None and not th.is_alive(), leg,
          f"人一答，同一趟就接着跑完（thread alive={th.is_alive()}，异常 {box.get('exc')}）")
    if got is not None:
        check(got.stop_reason == "final", leg, f"接着跑 ⇒ final（实得 {got.stop_reason!r}）")
        check(gw2.calls >= 2, leg, f"答案是接着跑的（模型调用数 {gw2.calls} ≥ 2）")
    check(not any(e.get("kind") == "user_question"
                  for e in _events(root2, "t")[len(_events(root2, "t")):]), leg,
          "回答之后不再有待答问题残留")


def leg_delegated() -> None:
    """非主控角色不许当面问用户（运行时协作纪律：人机通道归主控）。

    依据是我们自己的 `DESIGN-CONDUCTOR.md` §1.1（"它是用户唯一面对的东西"）与
    `capabilities.NON_SUMMONABLE = {"M"}` —— 不是抄 DSH 的 DELEGATED_CALLER。
    两根负控都在：被召唤的一环（G，有父任务号）、以及"顶层但不是主控"。
    """
    leg = "delegated"
    from agentflow import agent_loop as AL

    root = _ws("delegated")
    gw = _Scripted([json.dumps({"ask_user": {"question": "子角色想问一句"}}, ensure_ascii=False),
                    json.dumps({"final": "子角色把未决问题写进结果", "evidence": []},
                               ensure_ascii=False)])
    from agentflow.agent_loop import LlmBackend
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.llmseam import LlmSeam
    from agentflow.tools import build_registry

    st = Store(root)
    st.init()
    seam = LlmSeam(role="G", session_root=root, gateway=gw, price=(0.0, 0.0), sid="t")
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda role: seam, max_steps=4, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    loop = AL.AgentLoop(role="G", session_root=root, registry=built.registry, conductor=cond,
                        seam=seam, workspace_root=str(root), sid="t", store=st)
    out = loop.run("做一件事", my_task_id="t-0001", depth=2)
    check(out.stop_reason != "waiting_for_user", leg,
          f"非主控提问不许把循环停住（实得 {out.stop_reason!r}）")
    check(not [e for e in _events(root, "t") if e.get("kind") == "user_question"], leg,
          "非主控的问题不许落进用户频道")
    blob = json.dumps([s.to_dict() for s in out.steps], ensure_ascii=False)
    check("not_conductor" in blob or "未决" in blob, leg,
          "角色被告知：把未决问题写进结果（不许当面问用户）")
    # 第二根负控：顶层但不是主控（人工直接 run-agent D 那条路）同样被拒
    gw2 = _Scripted([json.dumps({"ask_user": {"question": "顶层 G 想直接问"}},
                                ensure_ascii=False),
                     json.dumps({"final": "写进结果", "evidence": []}, ensure_ascii=False)])
    seam2 = LlmSeam(role="G", session_root=root, gateway=gw2, price=(0.0, 0.0), sid="t2")
    loop2 = AL.AgentLoop(role="G", session_root=root, registry=built.registry, conductor=cond,
                         seam=seam2, workspace_root=str(root), sid="t2", store=st)
    top = loop2.run("顶层做一件事", my_task_id="", depth=2)
    check(top.steps[0].result.get("problem") == "not_conductor", leg,
          f"顶层非主控也被拒（实得 {top.steps[0].result.get('problem')!r}）")
    check(not [e for e in _events(root, "t2") if e.get("kind") == "user_question"], leg,
          "顶层非主控的问题也不许落盘")
    # 正控：主控问得通，而且会停下来等人
    gw3 = _Scripted([json.dumps({"ask_user": {"question": "主控问一句"}}, ensure_ascii=False),
                     json.dumps({"final": "等到了", "evidence": []}, ensure_ascii=False)])
    seam3 = LlmSeam(role="M", session_root=root, gateway=gw3, price=(0.0, 0.0), sid="t3")
    loop3 = AL.AgentLoop(role="M", session_root=root, registry=built.registry, conductor=cond,
                         seam=seam3, workspace_root=str(root), sid="t3", store=st,
                         user_timeout_sec=0.0)
    boss = loop3.run("主控问一句", my_task_id="", depth=2)
    check(boss.stop_reason == "waiting_for_user", leg,
          f"主控必须能问通并停下（实得 {boss.stop_reason!r}）")


LEGS = {"channel": leg_channel, "loop": leg_loop, "gui": leg_gui, "projection": leg_projection,
        "tokens": leg_tokens, "delegated": leg_delegated}


def main(argv: list[str]) -> int:
    want = [a for a in argv if a in LEGS] or list(LEGS)
    for name in want:
        print(f"\n=== 腿：{name} ===")
        try:
            LEGS[name]()
        except Exception as exc:  # noqa: BLE001 —— 任何异常都记成一条不符，继续跑后面的腿
            check(False, name, f"这条腿抛异常：{type(exc).__name__}: {exc}")
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n==== 合计 {len(RESULTS)} 条，不符 {len(bad)} 条 ====")
    for _ok, leg, what in bad:
        print(f"  [{leg}] {what}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
