# -*- coding: utf-8 -*-
"""L 的汇报与升级、以及 E 那一侧的接缝（四条判据 D9–D11 与 F16）。

## 这一份判什么

裁定的第四句有两跳：L 把形式化困难按受控形态交回 B；B 判断缺陷严重时通知 D 开展
研究。两跳都必须落在"对方真的收到了"上（收件箱里的 `agent_message`），不是落在
日志里，也不是落在返回值里。第五句（E 的 Lean 侧写死停用）只有在"工具面没有入口、
而桥接层函数还在"这两件事同时成立时才算落到位。

| 编号 | 判据 | 改前红（本文件加进来之前的那棵树） |
|---|---|---|
| D9 | L 判"漏一步"⇒ B 的收件箱里真有一条汇报（点名 stmt_id 与失败类型）；检查器自己那一档（源码编译不过）不汇报（负控） | 改前没有 `agent_l` / `proofreport`，`formalize` 的失败只落在返回值里，一条消息都没有 ⇒ B 的收件箱是空的 |
| D10 | B 覆盖 canonical（旧文进 `proof_history`）之后重新过 V ⇒ 旧签转 stale、新签是新号；L 再形式化那一版 ⇒ 12/12 之外那一档真的变成 verified | 前半（canonical / 新旧签）改前就有，是正控；红的是与 L 相连的那两格（L 判失败与新证明形式化 ⇒ 改前 ImportError） |
| D11 | 两跳分开钉：第一跳（代码） L 判 `statement_mismatch` ⇒ B 的收件箱里一条汇报、`severity="research"` 原样带上；第二跳（模型）B 走 `summon` 形状派 D —— 边在 / D 可召唤 / `policy.check` 放行，而 D 的收件箱一条都没有（这一跳不经收件箱） | 改前这一格调 `B.escalate_proof_research`：它不在 `ACTIONS` 里（模型调到它只会 `unknown_action`）、src 0 个调用方 ⇒ 那个入口已退场（改前红：`hasattr(AgentB, …)` 为真）；两跳的正控改前就绿，它守的是"迁移没有把升级这条路一起删掉" |
| F16 | E 的工具面没有 `verify.check_formal`，但 `verify_tools.check_formal` 的函数实体仍在且可调用 | 改前 `verify.check_formal` 那件工具的 `roles` 是 `_ROLES_WRITE`（E/F/G）⇒ "E 的工具面上没有它"当场红；函数实体一直在 |

## 真 Lean 与零模型

D9 与 D10 要真跑检查器（本机那一版，绝对路径）；跑不动时如实 `skip` 并写明原因。
D11 与 F16 里的递送/工具面判据不需要检查器：D11 的两次 formalize 都在写盘之前被
受控拒绝（转述 vs 实测正文），F16 只在"本机有 lean 且自检 usable"时调一次函数实体。

模型一次都不调：V 的那个"模型"是照剧本回答的替身（`_Seam`），写死的结论只用于让
V 走完它自己的解析与落账路径。

## 临时文件

工作区全部在 `tmp_path` 下自建；探针文件一个都不写。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import agent_loop as AL
from agentflow import depsection as _DS
from agentflow import proofreport as PR
from agentflow import schema as S
from agentflow import settings as SET
from agentflow import verifications as VR
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import verify_tools as VT

#: 被形式化的那条命题（B 登记的原文）。
CLAIM = "forall n : Nat, n + 0 = n"
#: 转述过的那一句：意思一样，一个字符都不同。
PARAPHRASE = "对任意自然数 n，n 加零还是 n。"
#: 命题台账里那一行的编号与标题。
STMT_ID = "000001"
LABEL = "加零不改变自然数"
#: 会话号（收件箱按它分文件；不由环境变量决定，判据才可复现）。
SID = "t"

#: 证明链的步数（空行分段 ⇒ `split_proof_steps` 切出 12 步）。
STEPS = 12

#: 本机那一版真 Lean（绝对路径；PATH 上的 lean 可能是另一个东西）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path, seed_statement_row

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()


# ============================================================ 夹具


def _reset_readings() -> None:
    """清掉 `leantoolchain` 的自检缓存与提示词那个 lru_cache（配置重载口）。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _lean_env(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """把 Lean 开关钉到某一档；开着时同时把检查器指到本机那一版（绝对路径）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1" if on else "0")
    if on and HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    _reset_readings()


def _skip_unless_usable(ws: pathlib.Path) -> None:
    """真检查器不可用时如实 skip（原因写清：文件不在 / 自检不是 usable）。"""
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=ws)
    if str(reading.get("state")) != "usable":
        pytest.skip(
            f"Lean 自检不是 usable（state={reading.get('state')}；"
            f"problems={reading.get('problems')}）⇒ 这一条要真跑检查器，跳过（不伪装通过）")


def _proof_text(steps: int = STEPS) -> str:
    """`steps` 步的证明链：一步一段。"""
    return "\n\n".join(f"第 {k} 步：把第 {k - 1} 步的结论代入一次并化简。"
                       for k in range(1, steps + 1))


def _source(mapped: int = STEPS, *, false_statement: bool = False) -> str:
    """Lean 源码：`-- step k` 标出前 `mapped` 步的落点。

    `false_statement=True` 造一份"编译不过"的源码（`n + 1 = n`）：那是检查器自己
    那一档失败，用来判"不该汇报给 B"的负控。
    """
    claim = "n + 1 = n" if false_statement else "n + 0 = n"
    lines = [
        "import Init.Data.Nat.Basic",
        "",
        "namespace LProbe",
        "",
        "/-- 一条自产命题。 -/",
        f"theorem add_zero_probe (n : Nat) : {claim} := by",
        "  rfl",
    ]
    for k in range(1, mapped + 1):
        lines.append(f"-- step {k}")
    lines += ["", "end LProbe", ""]
    return "\n".join(lines)


def _workspace(tmp_path: pathlib.Path, *, steps: int = STEPS) -> tuple[Store, pathlib.Path]:
    """建一个工作区，并让 B 登记一条命题（`proof_text` 是 `steps` 步的证明链）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    with st.tx("statements", actor="agent-B") as tx:
        tx.upsert("statements", {
            "stmt_id": STMT_ID,
            "label": LABEL,
            "statement": CLAIM,
            "statement_full": CLAIM,
            "proof_text": _proof_text(steps),
            "evidence_kind": "heuristic",
            "status": "active",
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
            "origin": "own_result", "derived_from": ["999999"],
            "quote_reason": "自产命题（这一组判据不涉及外部原文）",
        }, note="probe:statement")
    return st, ws


def _agent_l(st: Store, ws: pathlib.Path):
    """L 的真实现（零模型；会话落点显式给，递送判据才可复现）。"""
    from agentflow.agent_l import AgentL

    return AgentL(st, workspace_root=ws, config={"session_root": str(ws), "sid": SID})


def _agent_b(st: Store, ws: pathlib.Path):
    """B 的真实现（零模型：这条路只碰 store 与会话）。"""
    from agentflow.agent_b import AgentB

    return AgentB(st, extractor=None, extract_text=None,
                  config={"session_root": str(ws), "sid": SID})


def _inbox(ws: pathlib.Path, role: str) -> list[dict]:
    """某个角色的收件箱（`agent_loop.read_messages` 是收件箱的唯一读法）。"""
    msgs, problems = AL.read_messages(ws, role, sid=SID)
    assert problems == [], problems
    return [dict(m) for m in msgs]


class _Seam:
    """照剧本回答的替身模型缝（V 要一个"模型"，这里给一份写死的结论）。

    这不是模型调用：`ask` 只从清单里取下一句写死的话，没有网络、没有计费。
    """

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: object) -> object:
        from types import SimpleNamespace

        self.prompts.append(prompt)
        text = self.replies.pop(0) if self.replies else ""
        return SimpleNamespace(text=text, problem="" if text else "judge_not_wired")


def _verdict_json(verdict: str, *, step: int = 0) -> str:
    """V 的结论（"有毛病"必须带 findings，见 `verifications.parse_verdict`）。"""
    if verdict == "成立":
        return json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)
    return json.dumps({
        "verdict": verdict,
        "defect_step": step,
        "findings": [{"level": "error", "step": step, "kind": "缺一步",
                      "detail": f"第 {step} 步没有依据"}],
    }, ensure_ascii=False)


class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _VSecretarySeam:
    """V 的秘书那一档的假缝（`ask_json` 形状）：照剧本签。

    业主 2026-10-29：连续 3 次「成立」之后才轮到秘书发签 ⇒ 这一条要签上就必然
    经过秘书那一关（`v_reply_defect` 判有没有缺陷、`sign_issuance` 判发不发）。
    """

    wired = True

    def __init__(self, issuance: str = "签发") -> None:
        self.issuance = issuance
        self.seen: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.seen.append(str(note))
        kind = str(note).split(":", 1)[-1]
        answers = {"v_reply_defect": {"decision": "没问题", "reason": "夹具：读不出缺陷"},
                   "sign_issuance": {"decision": self.issuance,
                                     "reason": "夹具：按连续读数发签"}}
        return dict(answers.get(kind, {})), _Call()


def _v_secretary(store: Store, *, issuance: str = "签发"):
    """V 的秘书（带判断面）。"""
    from agentflow import secretary as SEC

    return SEC.Secretary("V", root=store.root, store=store,
                         seam=_VSecretarySeam(issuance), enable_model=True)


def _own_statement() -> dict:
    """B 登记自产命题时那几格（`register_statement` 的硬要求）。"""
    return {
        "statement_full": CLAIM,
        "statement_text": CLAIM,
        "origin": "own_result", "derived_from": ["999999"],
        "doc_id": S.format_id(0),
        "quote_reason": "我方自产命题，没有外部引文要比对",
        "kind": "conjecture",
        "label": LABEL,
    }


# ============================================================ D9 汇报到 B


def test_d9_a_missed_step_reaches_b_inbox_not_only_the_log(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D9：L 判"漏一步"⇒ B 的收件箱里真有一条汇报（含 stmt_id 与失败类型）。

    改前红：改前没有 `agent_l` / `proofreport`，`formalize` 的失败只落在返回值里
    （那时连 `coverage` 都没有），B 的收件箱是空的 ⇒ 第一条 `len(hits) == 1` 红。

    负控（同一个用例里）：检查器自己那一档（源码编译不过）不汇报 —— 那份源码是 L
    写的，B 改不动它；把这一类也投给 B，只会让收件箱退化成一张杂事清单。

    反真空：汇报不是"返回里有 `report` 这一格"就算数 —— 下面按
    `agent_loop.read_messages` 读 B 的收件箱，并把 `msg_id` 与返回值里那一格对上。
    """
    _lean_env(monkeypatch, True)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    agent = _agent_l(st, ws)

    data = agent.formalize(CLAIM, source=_source(STEPS - 1), statement_id=STMT_ID)
    coverage = dict(data.get("coverage") or {})
    assert coverage.get("unmapped") == [STEPS], coverage
    report = dict(data.get("report") or {})
    assert report.get("state") == "reported", report
    payload = dict(report.get("payload") or {})
    assert payload.get("statement_id") == STMT_ID, payload
    assert payload.get("failure_type") == "unfaithful_step", payload
    assert int(payload.get("step") or 0) == STEPS, payload
    assert str(payload.get("suggestion") or "").strip(), payload

    inbox = [m for m in _inbox(ws, "B") if str(m.get("from")) == "L"]
    assert len(inbox) == 1, inbox
    hit = inbox[0]
    assert str(hit.get("msg_id") or "") == str(report.get("msg_id") or ""), (hit, report)
    body = json.dumps(hit, ensure_ascii=False)
    assert STMT_ID in body, body
    assert "unfaithful_step" in body, body
    assert f"第 {STEPS} 步" in body, body
    assert dict(hit.get("formal_failure") or {}).get("failure_type") == "unfaithful_step", hit

    # ---- 负控：检查器自己那一档（编译不过）不打扰 B
    broken = agent.formalize(CLAIM, source=_source(false_statement=True),
                             statement_id=STMT_ID)
    assert broken.get("checker_status") == "failed", broken.get("checker_status")
    assert broken.get("reason") == "compile_error", broken.get("reason")
    skip = dict(broken.get("report") or {})
    assert skip.get("state") == "skipped", skip
    assert skip.get("reason") == "checker_fault", skip
    assert str(skip.get("msg_id") or "") == "", skip
    still = [m for m in _inbox(ws, "B") if str(m.get("from")) == "L"]
    assert len(still) == 1, f"检查器自己那一档也投了消息：{still}"


# ============================================================ D10 重签


def test_d10_b_rewrites_the_proof_then_v_signs_again(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D10：V 先审新稿拿签（签块落稿）→ B 再收录 ⇒ 旧正文进 `proof_history`。

    2026-11-02 业主把次序定成「V 签先放在手稿里，让 B 录入」（`draft/179`）之后，
    改前的 `B 登记正文 → V 判 → B 改稿` 这条环在 strict 下不可达：改稿那一笔没有签
    就被准入闸整笔拒。现在的形态是：L 判失败 ⇒ F 把补好的稿交 V ⇒ V 连判三转、
    签块盖回稿 ⇒ B 拿着「稿里正文 + 手稿签块」收录（旧正文留进 `proof_history`）。

    反真空：签的是新稿那一份（`manuscript_sign_standing` 的 sha/连续次数都要对得上，
    不是"有块就算"）；旧台账那一签盖的是旧正文 ⇒ 新正文上仍读 stale；第三次形式化
    的结论必须真的翻成 verified（不是"没报错"）。
    """
    from agentflow import evidencebits as EB
    from agentflow import vsigns as VS
    from agentflow.agent_v import AgentV

    _lean_env(monkeypatch, True)
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    _skip_unless_usable(ws)
    b = _agent_b(st, ws)

    # 旧稿是"已在册、还没有 V 签"的历史形态（真机 own_result 行就是这么来的）：
    # strict 下无签正文经 `register_statement` 写不进去 ⇒ 夹具直接铺行，读侧判据不变。
    old_proof = _proof_text(STEPS)
    seeded = seed_statement_row(
        st, proof_text=old_proof, statement_full=CLAIM, statement_text=CLAIM,
        kind="conjecture", label=LABEL, origin="own_result",
        doc_id=S.format_id(0), line_range={"start": 1},
        quote_reason="我方自产命题，没有外部引文要比对",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=old_proof,
                        kind="conjecture"))
    sid = str(seeded.get("stmt_id") or "")
    assert sid, seeded

    v1 = AgentV(st, workspace_root=ws, llm=_Seam([_verdict_json("有毛病", step=STEPS)]))
    # 2026-11-04（业主裁定 甲）：在册命题的 V 审必须带手稿（签块 / `## 依赖` /
    # 按号寻址三样只在文件上）。这一趟判的是旧稿「有毛病」⇒ 落的是旧稿那一份；
    # 判据一个字没改（下面仍按 verdict / verification_id 判）。
    old_rel = _DS.manuscript_relpath(statement_id=sid)
    assert old_rel, sid
    old_path = ws / old_rel
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(
        "# F 的证明手稿：加零不改变自然数\n\n"
        f"## 命题\n\n{CLAIM}\n\n"
        f"## 证明\n\n{old_proof}\n\n"
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")
    signed1 = v1.verify_proof(sid, proof_text=old_proof, proof_manuscript=old_rel)
    assert signed1.get("checked") is True, signed1
    assert signed1.get("verdict") == "有毛病", signed1
    assert str(signed1.get("verification_id") or "").startswith("v-"), signed1

    # ---- L 形式化第一版：第 12 步没有落点 ⇒ unknown + 汇报（这就是 B 要改的理由）
    agent = _agent_l(st, ws)
    one = agent.formalize(CLAIM, source=_source(STEPS - 1), statement_id=sid)
    assert one.get("status") == "unknown", (one.get("status"), one.get("reason"))
    assert dict(one.get("coverage") or {}).get("unmapped") == [STEPS]
    assert dict(one.get("report") or {}).get("state") == "reported", one.get("report")

    # ---- 新稿先过 V：一次调用连判三转（3 转「成立」⇒ 签块盖回手稿）
    #
    # 「连续 3 次」是 V 判完接着再判（2026-10-30 业主口径），不是 F 送三次；未在册那一支
    # 的终局是稿上的签块（没有命题行可翻 ⇒ `signed_bit3=False` 是诚实的）。
    new_proof = _proof_text(STEPS - 1)
    #: 稿名按「这一条命题的稿」命名（`depsection.manuscript_relpath` 是唯一命名口径）：
    #: 签块第 9 格的手稿号要能映射回在册的这一条，B 收录时才认得出这一块是谁的。
    man_rel = _DS.manuscript_relpath(statement_id=sid)
    assert man_rel, sid
    man_text = ("# F 的证明手稿：加零不改变自然数\n\n"
                "- 计划：0000 · 子目标：s1\n\n"
                f"## 命题\n\n{CLAIM}\n\n"
                f"## 证明\n\n{new_proof}\n\n"
                "## 依赖\n\n"
                "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                "|---|---|---|---|\n"
                "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
    man_path = ws / man_rel
    man_path.parent.mkdir(parents=True, exist_ok=True)
    man_path.write_text(man_text, encoding="utf-8")

    #: p247（2026-11-06）：轴只由秘书给 —— 这一趟的三转 clean 必须由秘书那一问判出，
    #: 不再是 V 的 `verdict` 字面。夹具因此显式装一名带判断面的秘书（不是放宽判据：
    #: 它正是生产里 `AgentV._secretary` 惰性装配的那一格，只是测试不给真模型）。
    v2 = AgentV(st, workspace_root=ws, llm=_Seam([_verdict_json("成立")] * 3),
                secretary=_v_secretary(st))
    # 2026-11-03 件一：未在册正判的块由收方秘书落 —— 先挂上"V 由 F 派出来"的身份。
    from agentflow import conductor as CND

    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        signed2 = v2.verify_proof(proof_manuscript=man_rel)
    assert signed2.get("checked") is True, signed2
    assert signed2.get("kind") == "proof_unregistered_signed", signed2
    assert signed2.get("verdict") == "成立", signed2
    passes = signed2.get("review_passes") or []
    assert [p["pass"] for p in passes] == [1, 2, 3], passes
    block = VS.manuscript_sign_standing(man_path.read_text(encoding="utf-8"),
                                        proof_sha=VR.text_sha(new_proof))
    assert block.get("state") == "signed", block
    assert (block.get("streak"), block.get("need")) == (3, 3), block
    assert block.get("proof_sha256") != signed1.get("proof_sha256"), (
        block.get("proof_sha256"), signed1.get("proof_sha256"))

    # ---- B 收录：正文取自稿里那一份，签由手稿签块认下（准入闸照常判）
    second = b.register_statement(**_own_statement(), proof_text=new_proof,
                                  proof_manuscript=man_path.read_text(encoding="utf-8"))
    assert second.get("ok") is True, second
    assert second.get("canonical_written") is True, second
    row = next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)
    history = [dict(item) for item in (row.get("proof_history") or [])]
    assert [str(item.get("text") or "") for item in history] == [old_proof], history
    assert str(row.get("proof_text") or "") == new_proof

    # 旧台账那一签盖的是旧正文 ⇒ 新正文上仍是 stale（旧签不借光）；新签在手稿签块里。
    standing = VR.review_standing(ws, statement_id=sid, proof_text=new_proof, proof_no=1)
    assert standing.get("state") == "stale", standing
    assert standing.get("in_sync") is False, standing
    block_now = VS.manuscript_sign_standing(man_path.read_text(encoding="utf-8"),
                                            proof_sha=VR.text_sha(new_proof))
    assert block_now.get("state") == "signed", block_now
    assert (block_now.get("streak"), block_now.get("need")) == (3, 3), block_now

    # ---- L 再形式化这一版：覆盖逐条接上 ⇒ 结论真的翻成 verified
    two = agent.formalize(CLAIM, source=_source(STEPS - 1), statement_id=sid)
    assert dict(two.get("coverage") or {}).get("unmapped") == [], two.get("coverage")
    assert two.get("status") == "verified", (two.get("status"), two.get("reason"),
                                             two.get("detail"))
    assert dict(two.get("report") or {}).get("state") == "skipped", two.get("report")


# ============================================================ D11 升级到 D


def test_d11_the_upgrade_to_d_is_the_summon_path_not_an_inbox_message(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D11：两跳各钉各的 —— 第一跳是代码（L→B 收件箱），第二跳是模型（B→D 走 `summon`）。

    ## 为什么这一格在 2026-11-20 换了被测对象（PROOFCHAN，不是放宽判据）

    改前这一格调 `B.escalate_proof_research`：它不在 `specs/b.py` 的 `ACTIONS` 里
    ⇒ 模型照它调只会拿到 `unknown_action`；src 里 0 个调用方，只有测试在调。而模型侧
    真正的路早在 2026-11-05（审计② 第 ⑪ 条）就锚到 `summon` 形状了。那个程序入口已退场，
    所以这一格把两跳拆开、各自钉死，强度不减：

    - 第一跳（代码，活的）：L 判「与台账对不上」⇒ B 的收件箱里真有一条汇报，
      `severity="research"` 是 L 的读数，原样带到 B 手上（B 才有判断的素材）；
    - 第二跳（模型，提示词教的）：B 走 `summon` 形状派 D —— 边 / 可召唤 / 闸三层
      都放行；而 D 的收件箱一条都没有：这一跳不再经收件箱（改前那条"研究请求"
      是收件箱消息，改后 `summon` 是派活，两者不是一件事）；
    - 仍然绕不开边表：摘掉 L 与 B 两向的边 ⇒ 同一次汇报当场
      `refused/no_collab_edge`、一行都不写（`proofreport.deliver` 的那道闸是唯一一份；
      改前这条控制钉在 B→D 上，现在钉在仍然活着的那一跳上）；
    - 负控（普通缺陷）：`severity` 普通的那一档照样汇报给 B（L 不替 B 判），而提示词
      明写「普通缺陷不进 D 的收件箱」—— 程序侧的 severity 闸随入口一起退场，所以这一档
      只剩提示词这一处，直接钉它的原话；
    - 反真空：受控拒绝那一档（失败类型不在词表）⇒ `refused/invalid_params`，零写入。

    零 Lean：两趟 formalize 都在写盘与起检查器之前被受控拒绝（转述 vs 实测正文）。
    """
    _lean_env(monkeypatch, False)
    st, ws = _workspace(tmp_path)
    agent = _agent_l(st, ws)

    # ---- 第一跳：L 判"与台账对不上"⇒ B 的收件箱里一条汇报（severity 是读数）
    b_before = len(_inbox(ws, "B"))
    d_before = len(_inbox(ws, "D"))
    bad = agent.formalize(PARAPHRASE, source=_source(), statement_id=STMT_ID)
    assert bad.get("refused") is True, bad.get("refused")
    report = dict(bad.get("report") or {})
    payload = dict(report.get("payload") or {})
    assert report.get("state") == "reported", report
    assert payload.get("failure_type") == "statement_mismatch", payload
    assert payload.get("severity") == "research", payload
    assert PR.severity_for(str(payload.get("failure_type"))) == "research"
    inbox_b = _inbox(ws, "B")
    assert len(inbox_b) == b_before + 1, inbox_b
    hit = inbox_b[-1]
    assert str(hit.get("from")) == "L", hit
    assert STMT_ID in str(hit.get("body") or ""), hit.get("body")
    assert "research" in str(hit.get("body") or ""), (
        "L 的汇报正文里必须带上它建议的严重度读数 —— B 靠这一格决定要不要派 D")

    # ---- 第二跳：B 走 `summon` 形状派 D（边 / 可召唤 / 闸三层都放行）
    from agentflow import capabilities as C
    from agentflow import policy as P
    from agentflow.agentspec import builtin_registry

    assert "D" in C.ALLOWED_EDGES["B"], sorted(C.ALLOWED_EDGES["B"])
    assert "D" not in C.NON_SUMMONABLE, sorted(C.NON_SUMMONABLE)
    assert "D" in builtin_registry().summonable_roles()
    assert P.check(P.Policy(), P.Decision(frm="B", to="D", action="")) is None
    # 而这一跳不再经收件箱：整趟下来 D 的收件箱一条都没有
    assert d_before == 0 and _inbox(ws, "D") == [], (
        f"D 的收件箱被写了东西：{_inbox(ws, 'D')} —— 改后升级走 summon，不经收件箱")

    # ---- 负控 1：普通缺陷那一档 —— L 照样汇报（B 才有判断素材），D 的收件箱不动
    normal = agent.report_to_b(statement_id=STMT_ID, failure_type="unfaithful_step",
                               step=STEPS, severity=PR.severity_for("unfaithful_step"))
    assert normal.get("state") == "reported", normal
    assert dict(normal.get("payload") or {}).get("severity") == "normal", normal.get("payload")
    assert len(_inbox(ws, "B")) == b_before + 2
    assert _inbox(ws, "D") == [], "普通缺陷那一档也被写成 D 的收件箱消息了"
    # 提示词那一处的负控（B 被明写「普通缺陷不进 D 的收件箱」）由
    # `tests/test_proofchan_upgrade_is_the_summon_path.py` 在 Lean 开着那一档逐字钉着
    # —— 本文件跑在关档，PROOF_CHANNEL 整段被换成 `*_NO_LEAN`，这里渲染不出那一句。

    # ---- 仍然绕不开边表：把 L 与 B 之间那条边整个摘掉（两向都摘：准入看任一方向有边）
    assert AL.message_admission("L", "B") == "", AL.message_admission("L", "B")
    patched = {role: frozenset(targets) for role, targets in C.ALLOWED_EDGES.items()}
    patched["L"] = patched["L"] - {"B"}
    patched["B"] = patched["B"] - {"L"}
    monkeypatch.setattr(C, "ALLOWED_EDGES", patched)
    before_blocked = len(_inbox(ws, "B"))
    blocked = agent.report_to_b(statement_id=STMT_ID, failure_type="statement_mismatch",
                                severity="research")
    assert blocked.get("state") == "refused", blocked
    assert blocked.get("reason") == "no_collab_edge", blocked
    assert len(_inbox(ws, "B")) == before_blocked, "没有 L→B 这条边，汇报仍然送到了"

    # ---- 反真空：受控拒绝那一档零写入（词表外的失败类型）
    monkeypatch.undo()
    before_bad = len(_inbox(ws, "B"))
    invalid = agent.report_to_b(statement_id=STMT_ID, failure_type="不认识的类型",
                                severity="research")
    assert invalid.get("state") == "refused", invalid
    assert invalid.get("reason") == "invalid_params", invalid
    assert len(_inbox(ws, "B")) == before_bad, "受控拒绝也写了东西"


# ============================================================ F16 E 的接缝


def test_f16_e_has_no_verify_check_formal_yet_the_function_is_callable(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F16：E 的工具面没有 `verify.check_formal`，而函数实体仍在且可调用。

    2026-10-23 晚裁定（「E 侧与 Lean 相关的工具和动作都该清干净」）之后这一条又前进
    一格：工具那一件整条删除（改前的形态是 `roles=()` 的空壳），注册表里都没有它；
    而函数实体 `VT.check_formal` 仍在 —— 那一半是正控：删的是"E 的工具面那一件"，
    不是把桥接层实现删掉（L 的 `_CheckFormalL` 与 `formal.check_formal` 都经它）。

    三层各判一次：注册表里没有它（`get` 抛）、任何角色拿不到（`for_role` 全空）、
    而函数实体真跑一次仍然给 `verified`（真 Lean；跑不动就如实 skip）。
    """
    _lean_env(monkeypatch, True)
    st, ws = _workspace(tmp_path)
    reg = build_registry(store=st, workspace_root=ws).registry

    assert "verify.check_formal" not in set(reg.names()), (
        f"`verify.check_formal` 还在注册表里：{reg.names()}")
    from agentflow.tools.base import ToolError

    with pytest.raises(ToolError):
        reg.get("verify.check_formal")

    for role in tuple(S.ROLES) + (S.CONDUCTOR_ROLE,):
        face = {tool.name for tool in reg.for_role(role)}
        assert "verify.check_formal" not in face, f"{role} 的工具面上还有它"

    # ---- 函数实体仍在且可调用（真 Lean 跑一次；跑不动就如实 skip）。
    # `checker_name` 必须给：桥接层会往源码尾部追加一条 `#print axioms <名字>`，
    # 而内联源码没有"文件名词干"可以取（不给它时那个追加行是空的 ⇒ 一条真定理被
    # 记成 compile_error）。
    _skip_unless_usable(ws)
    callable_res = VT.check_formal(CLAIM, source=_source(),
                                   checker_name="LProbe.add_zero_probe", root=ws)
    assert callable_res.ok is True, callable_res.error
    data = dict(callable_res.data or {})
    assert data.get("verified") is True, data
    assert data.get("reason") == "verified", data
    assert data.get("exit_code") == 0, data
    assert str(data.get("verifier_output") or "").strip(), data
