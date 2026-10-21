"""`draft/37` §63 的判据（修法 B）：「会话身份是装配期的显式输入」。

## 撞出来的那一处假绿（第 11 趟真机）

主控在第 28 步调 `conductor.closing`，拿回来 `can_close: true, failed: []`；而「同一次运行」外部带 `sid=real11` 的读数报
`failed: ['user_pending']`。病因不在判据上：工具体此前按 `sid=None` 走到 `sessions/<今天>.jsonl`（`session_path` 的缺省值），而那一趟的提问落在
`sessions/real11.jsonl`。"没问过"与"问了还没答"于是长得一模一样 —— 而且「只在运行内」长得一样，外面怎么看都是对的。这正是 §62 通过之后仍然要修的那一条。

## 判据的方向（为什么是"相等"而不是"更严"）

修法 B 的主张是"装配期知道这一趟是谁，就一路带到判据里"。它的可判形态是「两个入口、同一个读数」：运行内 `conductor.closing` 与外部`check_closing(sid=...)` 必须逐格相同。
加上三条负控把"折叠"堵住：

1. 装配期「没」给 sid ⇒ `user_pending` 记 `unknown` —— 而不是回落到缺省会话。
负控的一半是"缺省会话里真的有提问"：旧代码会读到它并报 `pass`/`fail`，新代码必须报"没查成"（三态纪律：没查成不许折成查过了）。
2. 别的 sid 的提问不算这一趟的（``other-run`` 里的 `q0001` 不影响 `real63`）。
3. `host.wired_llm_conductor` 这条「产品路径」必须把身份带下去；
没给 `sid` 时它解析成缺省会话号（老跑法不许因此漏判）。
"""
from __future__ import annotations

import inspect
from pathlib import Path

from agentflow import closing as CL
from agentflow import host
from agentflow import sessions as SS
from agentflow import store as S
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

SID = "real63"
QUESTION = {
    "kind": "user_question", "role": "M", "qid": "q0001",
    "text": "这四处改动要不要保留？", "options": ["保留", "回退"], "timeout_sec": 60.0,
}
ANSWER = {"kind": "user_answer", "qid": "q0001", "answer": "保留", "by": "user", "role": "M"}


def _ws(tmp_path: Path, *, sid: str | None, answered: bool = False) -> Path:
    """一个最小工作区 + 一段会话记录（提问按 `sid` 落，`None` = 缺省会话）。

    这一组判据读的是「会话身份」那两格；夹具刻意是最小工作区 ⇒
    收工门里新加的 `substance`（实质产出，`draft/37` §86）在这份夹具上是
    预期为 fail 的（它本来就没有产出）—— 相关的断言把这一格显式排除掉，
    而不是靠"整份门恰好没有别的红"来间接表达。
    """
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    st = S.Store(tmp_path)
    st.init()
    SS.append(tmp_path, QUESTION, sid=sid)
    if answered:
        SS.append(tmp_path, ANSWER, sid=sid)
    return tmp_path


def _store(ws: Path) -> S.Store:
    st = S.Store(ws)
    st.init()
    return st


def _in_run(ws: Path, *, sid: str | None, answered: bool = False, **build_kw):
    """走装配路径（`build_registry` + `registry.call`）拿运行内读数。"""
    st = _store(ws)
    built = build_registry(store=st, workspace_root=ws, session_root=ws, sid=sid, **build_kw)
    assert "conductor.closing" in built.registry.names(), built.skipped
    res = built.registry.call("conductor.closing", role="M", project_dir="", report_path="")
    assert res.ok, res.error
    return st, res.data


def _codes(data: dict) -> set[str]:
    return {str(f.get("code")) for f in data.get("findings") or []}


# ---------------------------------------------------------------- 正控：两处相等

def test_in_run_reading_equals_the_outside_reading(tmp_path: Path):
    """正控（本文件的核心判据）：运行内读数 == 外部带 sid 的读数，逐格相等。

    相等本身可能是"两个空读数相等"，所以末尾再加一条反真空：
    这一格确实是 `fail`（那一趟真的在等用户）。
    """
    ws = _ws(tmp_path / "ws", sid=SID)
    st, data = _in_run(ws, sid=SID)
    outside = CL.check_closing(st, project_dir="", report_path="", sid=SID)

    for name in CL.DEFAULT_CHECKS:
        assert data["status"][name] == outside.status[name], (
            f"{name}：运行内 {data['status'][name]!r} vs 外部 {outside.status[name]!r}"
            " —— 两个入口读的必须是同一段会话（§63）")
    assert data["failed"] == outside.failed, (data["failed"], outside.failed)
    assert data["unknowns"] == outside.unknowns, (data["unknowns"], outside.unknowns)
    assert bool(data["can_close"]) == outside.can_close

    # 反真空：这一格真不是 pass，否则上面的"相等"证明不了任何事。
    assert outside.status["user_pending"] == "fail", outside.to_dict()
    assert data["status"]["user_pending"] == "fail", data["status"]
    assert data["readings"]["user_pending"]["pending"] == [
        {"qid": "q0001", "role": "M", "text": QUESTION["text"][:80]}], data["readings"]


def test_both_readings_flip_together_after_the_user_answers(tmp_path: Path):
    """正控：用户答完之后，两个入口一起翻成 `pass`（不是只有一个翻）。"""
    ws = _ws(tmp_path / "ws", sid=SID, answered=True)
    st, data = _in_run(ws, sid=SID)
    outside = CL.check_closing(st, project_dir="", report_path="", sid=SID)
    assert data["status"]["user_pending"] == "pass", data["status"]
    assert outside.status["user_pending"] == "pass", outside.to_dict()
    assert data["failed"] == outside.failed, (data["failed"], outside.failed)
    assert set(data["failed"]) <= {"substance"}, data["failed"]  # substance 是这份夹具预期的红


# -------------------------------------------- 负控：没有身份 ⇒ 没查成，不是 pass

def test_without_session_identity_the_cell_is_unknown(tmp_path: Path):
    """负控（堵住假绿的那一半）：装配期没给 sid ⇒ `unknown`，且「不读」缺省会话。

    这条的杀伤力在下半段：缺省会话文件里「真的有一个待答问题」
    ——旧代码（按 `sid=None` 读）会看见它；如果新代码"看不见 ⇒ 没有待答 ⇒ pass"，
    那就是把同一处假绿换了个方向（§62 的五条纪律里 `unknown` 不是通过）。
    """
    default_sid = SS.session_id()
    ws = _ws(tmp_path / "ws", sid=default_sid)
    st, data = _in_run(ws, sid=None)

    assert data["status"]["user_pending"] == "unknown", data["status"]
    assert "no_session_identity" in _codes(data), _codes(data)
    assert data["can_close"] is False, data

    # 负控的负控：同一份工作区、外部带缺省 sid 读，那一格「是」 fail
    # ⇒ 上面那个 unknown 不是"文件里没东西"，而是"这次调用没有身份"。
    outside = CL.check_closing(st, project_dir="", report_path="", sid=default_sid)
    assert outside.status["user_pending"] == "fail", outside.to_dict()


def test_the_judge_itself_has_the_third_input(tmp_path: Path):
    """判据层的三态：`sid=NO_SESSION` 与 `sid=None` 必须是两个不同的输入。

    `sid=None` = 读缺省会话（运维口径，合法）；`NO_SESSION` = 没有身份。
    两者折叠起来就会重演 §63 的假绿，所以这条判据直接钉在 `check_closing` 上。
    """
    ws = _ws(tmp_path / "ws", sid=SS.session_id())
    st = _store(ws)
    assert CL.check_closing(st, sid=CL.NO_SESSION).status["user_pending"] == "unknown"
    assert CL.check_closing(st, sid=None).status["user_pending"] == "fail"
    assert CL.NO_SESSION == "", "NO_SESSION 的取值改了 ⇒ `session_path` 的缺省回落会重新生效"


def test_a_question_in_another_session_does_not_count(tmp_path: Path):
    """负控：别的 sid 的提问不算这一趟的（两处入口都必须是 `pass`）。"""
    ws = _ws(tmp_path / "ws", sid="other-run-63")
    st, data = _in_run(ws, sid=SID)
    outside = CL.check_closing(st, project_dir="", report_path="", sid=SID)
    assert data["status"]["user_pending"] == "pass", data["status"]
    assert outside.status["user_pending"] == "pass", outside.to_dict()


# ------------------------------------------------- 产品路径：接线必须把身份带下去

def test_host_wiring_threads_the_session_identity(tmp_path: Path):
    """正控：`host.wired_llm_conductor` 这条产品路径把身份带到了工具体里。

    上面那些判据都直接调 `build_registry`。真机走的是这条函数 ——
    装配层漏传一个参数，前面全绿而真机照旧假绿（§63 的教训就是"两个入口"）。
    """
    ws = _ws(tmp_path / "ws", sid="host63")
    st = _store(ws)
    wiring = host.wired_llm_conductor(st, session_root=ws, sid="host63",
                                      workspace_root=str(ws))
    assert wiring["sid"] == "host63", wiring["sid"]
    res = wiring["registry"].call("conductor.closing", role="M", project_dir="", report_path="")
    assert res.ok, res.error
    assert res.data["status"]["user_pending"] == "fail", res.data["status"]
    assert "waiting_for_user" in _codes(res.data), _codes(res.data)


def test_host_wiring_resolves_the_default_session_id(tmp_path: Path):
    """正控（老跑法不许漏判）：不给 `sid` 时解析成缺省会话号，缺省会话里的提问看得见。"""
    default_sid = SS.session_id()
    ws = _ws(tmp_path / "ws", sid=None)
    st = _store(ws)
    wiring = host.wired_llm_conductor(st, session_root=ws, workspace_root=str(ws))
    assert wiring["sid"] == default_sid, wiring["sid"]
    res = wiring["registry"].call("conductor.closing", role="M", project_dir="", report_path="")
    assert res.data["status"]["user_pending"] == "fail", res.data["status"]


# --------------------------------------------------------------- 声明面（装配清单）

def test_the_closing_tool_declares_the_session_dependency():
    """装配清单必须声明 `session`：漏了它，`_call_register` 会当场抛（不许静默降级）。"""
    deps = {fn.__tool_spec__.name: d for fn, d in CT._TOOL_FUNCTIONS}
    assert deps["conductor.closing"] == ("store", "session"), deps["conductor.closing"]
    assert "session" in inspect.signature(CT.register).parameters, (
        "`register` 不收 `session` ⇒ `_call_register` 的签名反射传不进来，"
        "而工具会退回『没有会话身份』——真机里就是 §63 那次假绿")
    from agentflow.tools import build_registry as _br

    params = inspect.signature(_br).parameters
    assert "session_root" in params and "sid" in params, (
        "装配入口必须收会话身份这两个参数（§63 修法 B）")
