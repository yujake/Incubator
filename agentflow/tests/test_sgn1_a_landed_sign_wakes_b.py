# -*- coding: utf-8 -*-
"""SGN1：签落地必须「真把 B 叫醒」（真机 `projects/lp-ball-5`，2026-11-17）。

## 现场（只读读数，17:11）

```text
data/tasks.json     157 行；role="B" 的台账号 0 趟
data/statements.json 0 行
b-register@ 板项     0 条（v-resubmit@ 也 0 条）
reports/f-proof-000002.md  签块 signed（sha 50ec23ac…，2026-11-17T16:51:51）
reports/f-proof-000003.md  签块 signed（sha 29508fdf…，2026-11-17T17:05:37）
out/vsigns/               两份签文件（issued.json 两枚）
```

⇒ 签一枚枚落地，一条命题都没被收编，B 一次没被召唤；`acceptance` 必红
（"造"环无来路，也没有登记）。

## 两处断链（这一条判据各钉一条）

1. 未在册那一支从来不接「必须收录」义务：在册那两条支路
   （`land_sign_without_ledger` / `sign_statement`）都调 `_registration_after_vsign`，
   而"没号也能签"这条主路（`_finish_unregistered` → `_issue_and_land_unregistered`）
   一次都没调过。真机的两枚签全在这一支 ⇒ 板项 0 条。
2. 义务开成无主的：就算补上义务，`ensure_registration` 在"那一刻没有 B 在飞"时
   只写 `owner=""` 的板项（`parent_task_id=None`）—— 无主的项不进任何人的收件箱，
   `_ensure_consumer` 判"没有收件人（公共频道/广播）⇒ 没有要跑的人"。于是义务写在板上，
   B 一次也没醒。真机读数：B 台账号 0 趟。

## 判据（先红后绿 + 反真空 + 三态）

| # | 造什么 | 期望 | 改前 |
|---|---|---|---|
| a | 未在册命题 + 正式手稿 + 三转干净（真机形态） | 板上出现 `b-register@<号>@<sha>`（role=B、expects=work），并且台账上出现一趟 `b-awake@<号>@<sha>` 的 B 召唤（任务 id + 时刻），板项就开在它名下；`review_write.registration.wake.state="summoned"` | 红（板项 0 条、B 0 趟） |
| b | 同一枚签重放（再投一次同 sha 的落地） | 板项 1 条、召唤行 1 趟：`existing` + `already`（不重复召唤） | 红（改了也不召 ⇒ 无从"重复"；正控在 a） |
| c | 反真空：把召唤那一行打桩摘掉 | a 的召唤断言必红（`b-awake@` 0 条），而"这一份还没入库"的事实仍在（板项照样开） | —— |
| d | 那一刻 B 在飞 | 板项落进那一趟名下；不新召（`running`） | 红（开成无主） |
| e | 那一刻 B 静默未销号 | 同号继续（`notice` 落进它名下就叫醒它）；不新召（`woken`） | 红（开成无主） |
| f | 执行侧跑不了 B（确定性后端） | `wake.state="skipped"` + 原因；板项照旧在板上（三态：叫不醒 ≠ 没有义务） | ——（SGN1 新增的一档） |

零模型调用（V 的三转用预置回复）；不读写 `projects/`。
"""
from __future__ import annotations

import pathlib

from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import obligations as OBL
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for

from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam, _Seam, _axis

SID = "000002"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              + _DS.render_dependency_section([]))
#: 真机那两枚签的载体名（`reports/f-proof-000002.md` / `…000003.md`）。
REL = f"reports/f-proof-{SID}.md"


class _LoopBackend:
    """「模型驱动那一层」的最小替身（形状同 `agent_loop.LlmBackend`）。

    为什么必须是它：空动作的召唤只在这一层跑得起来（`LlmBackend.call`：`loops` 里没
    登记 `(角色, "")` 也会现造一个循环）；`LocalBackend` 按 `(角色,动作)` 找 handler，
    空动作没有 handler。召唤的判据在 `obligations._executor_can_run` 一处。
    """

    name = "fake-loop"
    loops: dict = {}

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def known_roles(self) -> list[str]:
        return ["B"]

    def call(self, role, action, params, *, token, instance="", task_id=""):
        self.calls.append({"role": role, "action": action,
                           "params": dict(params or {}), "task_id": task_id})
        return {"ok": True, "role": role, "task": str((params or {}).get("task") or "")}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _clean_secretary(st: Store):
    """V 的秘书（p247：轴由秘书给；这一支量的是未在册签的落地）。"""
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                  "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    return SEC.Secretary("V", root=st.root, store=st, seam=seam, enable_model=True)


def _sign_unregistered(st: Store, *, rel: str = REL, parent: str = "t-f1") -> dict:
    """走 V 的真入口：未在册命题 + 正式手稿 ⇒ 三转干净、签落稿上（真机形态）。"""
    agent = AgentV(st, workspace_root=st.root, llm=_ReviewSeam([CLEAN_REPLY]),
                   secretary=_clean_secretary(st))
    with CND.calling_as("t-v1", "V", parent_task_id=parent, parent_role="F"):
        return agent.verify_proof(proof_manuscript=rel)


def _agent_row(st: Store, *, role: str = "B", status: str = "running",
               parent: str = "t-root", depth: int = 2) -> str:
    """落一条代理行（`kind` 空）：B 的台账号用它。"""
    from agentflow.conductor import Conductor

    return Conductor._write_new_row(
        conductor_for(st), {
            "task_id": "", "role": role, "action": "", "called_by": "M",
            "parent_task_id": parent, "depth": depth,
            "input_key": f"@t:{role}:{status}", "status": status,
            "outcome": "ok" if status == "done" else None,
            "refusal_reason": None, "instance": f"{role}#1", "detail": "夹具",
            "error": None, "started_at": "2026-11-17T16:00:00+08:00",
            "ended_at": "2026-11-17T16:10:00+08:00" if status == "done" else None,
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        }, note="probe:agent")


def _register_items(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(OBL.REGISTER_PREFIX)]


def _wake_rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(OBL.REGISTER_WAKE_PREFIX)]


def _pending_rows(st: Store) -> list[dict]:
    """未在册那一支的独立背书（`verifications/pending/<正文 sha>.jsonl`）。"""
    import json

    base = pathlib.Path(st.root) / "verifications" / "pending"
    if not base.is_dir():
        return []
    return [json.loads(ln) for p in sorted(base.glob("*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sha_of(st: Store) -> str:
    rows = _pending_rows(st)
    assert rows, "未在册的签没有落 pending 台账 ⇒ 这一趟走的不是那条主路"
    return str(rows[-1].get("proof_sha256") or "")


# ============================================================ a 签落地 ⇒ 义务 + 召唤
def test_a_a_landed_unregistered_sign_opens_the_duty_and_summons_b(tmp_path):
    """a（真机 lp-ball-5 形态）：未在册的签落地 ⇒ 板上一条义务 + 台账上一趟 B 召唤。"""
    st = _ws(tmp_path)
    cond = conductor_for(st)
    backend = _LoopBackend()
    cond.backend = backend
    _put(st, REL, MANUSCRIPT)

    got = _sign_unregistered(st)
    assert got.get("kind") == "proof_unregistered_signed", got
    sha = _sha_of(st)
    assert sha and sha == got.get("proof_sha256"), (sha, got.get("proof_sha256"))
    key = OBL.register_key(f"{SID}#p1", sha)

    # ---- ① 义务项：真机改前这里是 0 条 ----
    items = _register_items(st)
    assert len(items) == 1, [r.get("input_key") for r in items]
    one = items[0]
    assert one["input_key"] == key, one
    assert str(one.get("role")) == "B", one
    assert str(one.get("expects")) == "work", "收录是要交付的活，不是'知道了'"
    assert str(one.get("item_state")) != "done", one

    # ---- ② 召唤：真机改前 B 一次没被召唤 ----
    wakes = _wake_rows(st)
    assert len(wakes) == 1, [r.get("input_key") for r in wakes]
    w = wakes[0]
    assert w["input_key"] == OBL.register_wake_key(f"{SID}#p1", sha), w
    assert str(w.get("role")) == "B", w
    assert not str(w.get("kind") or ""), "召唤行是台账号（kind 空），不是板项"
    assert str(w.get("called_by")) == "M", w
    assert str(w.get("started_at") or "").strip(), "召唤行必须带时刻"
    assert backend.calls and backend.calls[0]["role"] == "B", backend.calls

    # ---- ③ 板项开在它名下（否则它读了收件箱也看不到这一条） ----
    assert str(one.get("parent_task_id") or "") == str(w["task_id"]), (one, w)

    # ---- ④ 报告里能读到"签落地 ⇒ 已召唤 B（任务 id 与时刻）" ----
    reg = dict((got.get("review_write") or {}).get("registration") or {})
    assert reg.get("state") == "opened", reg
    wake = dict(reg.get("wake") or {})
    assert wake.get("state") == "summoned", wake
    assert str(wake.get("task_id")) == str(w["task_id"]), wake
    assert str(wake.get("at")) == str(w.get("started_at")), wake
    detail = str(got.get("detail") or "")
    assert str(w["task_id"]) in detail, detail
    assert "召唤" in detail or "叫醒" in detail, detail


# ============================================================ b 重放不重复召唤
def test_b_replaying_the_same_landed_sign_never_summons_twice(tmp_path):
    """b：同一枚签被重复投递 / 重放 ⇒ 板项 1 条、召唤 1 趟（幂等键是 statement_id+sha）。"""
    st = _ws(tmp_path)
    cond = conductor_for(st)
    cond.backend = _LoopBackend()
    _put(st, REL, MANUSCRIPT)
    _sign_unregistered(st)
    sha = _sha_of(st)
    first_items = _register_items(st)
    first_wakes = _wake_rows(st)
    assert len(first_items) == 1 and len(first_wakes) == 1, (first_items, first_wakes)

    # 重放两次：同一个 sha 的落地再来一遍（签本身是 idempotent 的）。
    got2 = VR.registration_after_unregistered_sign(
        store=st, root=st.root, manuscript=REL, sha=sha,
        at="2026-11-17T17:05:37+08:00")
    got3 = VR.registration_after_unregistered_sign(
        store=st, root=st.root, manuscript=REL, sha=sha, at="2026-11-17T17:06:00+08:00")
    for reg in (got2, got3):
        assert reg.get("state") == "existing", reg
        assert dict(reg.get("wake") or {}).get("state") == "already", reg
    assert len(_register_items(st)) == 1, [r.get("input_key") for r in _register_items(st)]
    assert len(_wake_rows(st)) == 1, [r.get("input_key") for r in _wake_rows(st)]
    assert _register_items(st)[0]["task_id"] == first_items[0]["task_id"]
    assert _wake_rows(st)[0]["task_id"] == first_wakes[0]["task_id"]


# ============================================================ c 反真空
def test_c_without_the_summon_step_a_is_red(tmp_path, monkeypatch):
    """c 反真空：把召唤那一行打桩摘掉 ⇒ a 的召唤断言红，而"还没入库"这个事实仍在。"""
    stubs: list[dict] = []

    def _no_wake(**kwargs):
        stubs.append(dict(kwargs))
        return {"checked": True, "state": "skipped", "task_id": "", "at": "",
                "key": str(kwargs.get("key") or ""),
                "reason": "反真空：召唤那一行被摘掉了"}

    monkeypatch.setattr(OBL, "_wake_registrar", _no_wake)
    st = _ws(tmp_path)
    conductor_for(st).backend = _LoopBackend()
    _put(st, REL, MANUSCRIPT)

    got = _sign_unregistered(st)
    assert stubs, "连召唤那一步都没被调到 ⇒ 这条反真空测的不是那个写口"
    # a 的两条召唤断言在这里必红：
    assert _wake_rows(st) == [], [r.get("input_key") for r in _wake_rows(st)]
    reg = dict((got.get("review_write") or {}).get("registration") or {})
    assert dict(reg.get("wake") or {}).get("state") != "summoned", reg
    # 而义务本身还在（产物没有被一起摘掉 ⇒ 上面那条红不是因为"什么都没发生"）。
    assert len(_register_items(st)) == 1, _register_items(st)
    gap = OBL.registration_gap(store=st, label=f"{SID}#p1", proof_sha=_sha_of(st))
    assert gap["checked"] is True and gap["gap"] is True, gap


# ============================================================ d B 在飞 ⇒ 不重复召唤
def test_d_a_running_b_gets_the_item_but_no_extra_summon(tmp_path):
    """d：那一刻 B 在飞 ⇒ 板项落进它名下（它下一拍自己读到），不新召一趟。"""
    st = _ws(tmp_path)
    cond = conductor_for(st)
    cond.backend = _LoopBackend()
    running = _agent_row(st, status="running")
    _put(st, REL, MANUSCRIPT)

    got = _sign_unregistered(st)
    one = _register_items(st)[0]
    assert str(one.get("parent_task_id")) == running, one
    assert _wake_rows(st) == [], "B 已经在跑 ⇒ 不许再召一趟（幂等）"
    reg = dict((got.get("review_write") or {}).get("registration") or {})
    wake = dict(reg.get("wake") or {})
    assert wake.get("state") == "running", wake
    assert str(wake.get("task_id")) == running, wake


# ============================================================ e 静默 B ⇒ 同号继续
def test_e_a_silent_b_is_woken_by_the_notice_under_its_own_id(tmp_path):
    """e：那一刻 B 静默未销号 ⇒ `notice` 落进它名下就叫醒它（同号继续，不新召）。"""
    st = _ws(tmp_path)
    cond = conductor_for(st)
    cond.backend = _LoopBackend()
    silent = _agent_row(st, status="done")
    woke: list[dict] = []

    def _resume(task_id, *, role="", item_id="", kind="", previous_status=""):
        woke.append({"task_id": task_id, "role": role, "item_id": item_id,
                     "kind": kind, "previous_status": previous_status})
        return {"started": True, "task_id": task_id, "reason": "夹具：同号继续"}

    cond.resume_runner = _resume
    _put(st, REL, MANUSCRIPT)

    got = _sign_unregistered(st)
    one = _register_items(st)[0]
    assert str(one.get("parent_task_id")) == silent, one
    assert _wake_rows(st) == [], "静默的 B 用同号继续叫醒，不新召"
    assert woke and woke[0]["task_id"] == silent, woke
    assert str(woke[0]["kind"]) == "notice", woke
    reg = dict((got.get("review_write") or {}).get("registration") or {})
    wake = dict(reg.get("wake") or {})
    assert wake.get("state") == "woken", wake
    assert str(wake.get("task_id")) == silent, wake


# ============================================================ f 三态：叫不醒 ≠ 没义务
def test_f_when_the_executor_cannot_run_b_the_duty_still_exists(tmp_path):
    """f：执行侧跑不了 B（确定性后端）⇒ `skipped` + 原因；板项照旧在板上。"""
    st = _ws(tmp_path)
    conductor_for(st)                      # 默认 `LocalBackend`：空动作没有 handler
    _put(st, REL, MANUSCRIPT)

    got = _sign_unregistered(st)
    one = _register_items(st)[0]
    assert str(one.get("role")) == "B" and str(one.get("expects")) == "work", one
    assert _wake_rows(st) == [], "跑不起来就不许在台账里编一趟召唤"
    reg = dict((got.get("review_write") or {}).get("registration") or {})
    wake = dict(reg.get("wake") or {})
    assert wake.get("state") == "skipped", wake
    assert "执行侧" in str(wake.get("reason") or ""), wake
    # 收工读数把"叫不醒"与"没有义务"分开：义务开着、负责人 unknown。
    digest = OBL.registration_digest(st.root, st)
    assert digest["checked"] is True and digest["open"] == 1, digest
    assert digest["unowned"] == 1 and digest["summoned"] == 0, digest
