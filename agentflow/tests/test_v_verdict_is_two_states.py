# -*- coding: utf-8 -*-
"""V 的结论只有两态（业主 2026-11-01 裁定，逐字见下）。

```text
「不应该有『看不出来』，『看不出来错』就是没毛病，没有『看不出来对』」
```

## 要落成的口径（业主 2026-11-01 + 2026-11-06 p247 第三次收紧）

```text
A. V 自己的判词只是陈述：成立 / 有毛病 / 判不了 / 看不出来 都原样落盘。
   p247 逐字：「不做折档」「不许按词面把判不了 / 看不出来 / 拿不准 / 我无法判断
   折成任何一态」。轴（clean / fault）由 V 的秘书读回复后语义判定；
   没有秘书轴的行不签、不算票。
B. 历史台账行里的 verdict="看不出来" 原样读出（不折档、不算票、不签）——
   p247 把 2026-11-02 的「按成立读并计票」也取消了（本文件 s3：3 → 2）。
C. specs/v.py 的 policy 第一段写成两态并逐字写那两句（这一份的 s4 钉渲染面）。
D. 三转连判机制不变：秘书判 clean 才继续；判 fault 立刻终止并打回 F；
   V 的判词本身不再构成一条打回（p247）。
```

## 四条判据（每条都先红后绿）

| # | 它守什么 | 改前为什么红 |
|---|---|---|
| s1 | 模型回「看不出来」⇒ 台账那一行原样是 `看不出来`（不折成成立/有毛病）；没有秘书轴 ⇒ 不签 | 改前 `parse_verdict` 把它折成 `成立` |
| s2 | 模型回「我无法判断这份证明对不对」⇒ 同样原样落行、不折档、不签；结构不合法才是"没查成" | 改前折成成立 / 或把词表外写法当成没查成 |
| s3 | 手写的 `verdict="看不出来"` 历史行：读得出（盘上那四个字不动）、不折档、不算票、不签 | 改前按成立读并计票（数出 3）；p247 收紧成 2 |
| s4 | 渲染后的 V 提示词（system + 冷启动，含技能索引摘要）里只剩两态那两句；`看不出来` 只许出现在"不存在……这一档"那句否定式里 | 两处都写着三态 / 让模型"信息不足就写看不出来" |
| s5 | `verify.verify_proof` 给模型看的那段声明文字（`summary` ＋ `returns`，`returns` 会拼进 function-calling 的 description）里不再出现 `看不出来`；而"`checked=False` ⇒ 没查成、不落台账行"这条约束一字不许丢 | `returns` 里那句「绝不拿「看不出来」冒充「审过了」」指着已经取消的那一档；模型读到的是一档它产不出的结论 |

反真空各一条：s1/s2 的模型回复是真的经 `AgentV.verify_proof` 走一遍（不是直调
`parse_verdict` 拼一个 dict）；s3 的历史行是手写进台账的（写侧已经收不了那一格）；
s4 的判据函数喂一份"换回三态"的探针提示词必须当场报错。

零真模型调用（缝是替身），零网络。
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

SID = "000007"
PROOF = "1. 由定义直接得到。\n2. 由第 1 步得到结论。"

#: 业主逐字要求写进 policy 的两句（C 段）。s4 逐字核它们出现在渲染后的提示词里。
TWO_STATES = ("成立（没找到缺陷 —— 不要求你证明它正确）"
              "/ 有毛病（找到了缺陷，必须指到步号与原句）")
NO_THIRD = "『看不出错』就是成立；不存在『看不出来』这一档，也不存在『看不出对』这回事"

#: `看不出来` 这四个字唯一允许留在 V 可见面上的形态：那一句否定式本身（业主逐字要求
#: 写「不存在『看不出来』这一档」）。除此之外任何一处出现都算"这一档还在"，s4 会点名。
ALLOWED_CARRIER = NO_THIRD


# ------------------------------------------------------------------ 夹具

class _Call:
    """`llmseam.SeamCall` 的替身：V 的审阅只读 `.text` / `.ok`。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """离线缝：按顺序回预置文本，并把真正递出去的提示词抄一份（s4 读它）。"""

    wired = True

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        call = _Call()
        call.text = self.replies.pop(0) if self.replies else ""
        return call


def _agent(root: pathlib.Path, reply: str) -> tuple[AgentV, _Seam]:
    """一个"没有秘书"的 V（发签那一条不在本文件的判据里）。"""
    seam = _Seam([reply])
    agent = AgentV(None, workspace_root=root, llm=seam, secretary=None)
    # 夹具：不让它去现造秘书（这台机器上没有 V 的秘书 key ⇒ 现造也是 None）
    agent._secretary_tried = True
    agent.secretary_problem = "夹具：这一趟没有 V 的秘书"
    return agent, seam


def _ledger(root: pathlib.Path, sid: str = SID) -> list[dict]:
    rows, problems = VR.list_verifications(root, statement_id=sid, limit=None)
    assert not problems, problems
    return rows


def _folded(root: pathlib.Path, reply: str) -> dict:
    """跑一趟真审阅，返回（唯一的）那一行台账 + 返回值。

    2026-11-08：在册命题必须有一份手稿（V 只对手稿负责）；storeless 这一路仍只落台账。
    """
    from agentflow import depsection as _DS

    rel = f"reports/f-proof-{SID}.md"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 证明手稿（夹具）\n\n- 命题号：stmt:{SID}\n\n"
        f"## 命题\n\n（夹具命题）\n\n## 证明\n\n{PROOF}\n\n"
        + _DS.render_dependency_section([]),
        encoding="utf-8")
    agent, _seam = _agent(root, reply)
    out = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=rel)
    assert out["checked"] is True, out
    rows = _ledger(root)
    assert len(rows) == 1, rows
    return {"out": out, "row": rows[0]}


# ------------------------------------------------------------------ s1

def test_s1_a_hedged_verdict_lands_as_a_statement_not_a_state(tmp_path):
    """s1（p247）：模型回「看不出来」⇒ 台账原样留住这句陈述；没有轴 ⇒ 不签。

    三件事各断一次（少一条这条判据就只是"它没报错"）：
    ① 台账那一行的 `verdict` 是 `看不出来` —— 不许折成 `成立` 或 `有毛病`；
    ② 这一行没有 `secretary_judge` ⇒ `secretary_axis` 是空串（没有轴，不是 clean）；
    ③ `read_verdict` 原样返回，`row_signable` 为假（轴只能由秘书给）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    got = _folded(root, '{"verdict": "看不出来", "why": "信息不足", "findings": []}')
    row, out = got["row"], got["out"]

    assert out["verdict"] == "看不出来", out
    assert row["verdict"] == "看不出来", "台账那一行被折档了" + str(row)
    # ② 没有秘书 ⇒ 没有轴（不是 clean）
    assert VR.secretary_axis(row) == "", row
    assert VR.secretary_judged(row) is False, row
    # ③ 只取字段、不产轴
    assert VR.read_verdict(row) == "看不出来", row
    assert VR.row_signable(row) is False, "没有秘书轴却签得住 ⇒ 字面又当成了 clean"
    # 这一签不翻位
    assert out["signed_bit3"] is False, out


# ------------------------------------------------------------------ s2

def test_s2_i_cannot_judge_stays_a_statement_and_is_not_signed(tmp_path):
    """s2（p247）：模型回「我无法判断这份证明对不对」⇒ 原样落成陈述，不折档、不签。

    反真空：同一套夹具喂一句结构不合法的话（"大概成立" 不是 JSON）⇒ 不落行
    （那是"没查成"）；而词表外但结构合法的写法（"大概成立" 包在 JSON 里）只是陈述，
    也不折档。
    """
    root = tmp_path / "ws"
    root.mkdir()
    got = _folded(root, json.dumps(
        {"verdict": "我无法判断这份证明对不对", "why": "证明里有一个记号没定义"},
        ensure_ascii=False))
    row, out = got["row"], got["out"]
    assert out["verdict"] == "我无法判断这份证明对不对", out
    assert row["verdict"] == "我无法判断这份证明对不对", row
    assert VR.secretary_axis(row) == "", row
    assert VR.row_signable(row) is False, row

    # 反真空：结构不合法仍然"没查成"（不落行）
    other = tmp_path / "ws2"
    other.mkdir()
    from agentflow import depsection as _DS2

    rel2 = f"reports/f-proof-{SID}.md"
    path2 = other / rel2
    path2.parent.mkdir(parents=True, exist_ok=True)
    path2.write_text(
        f"# 证明手稿（夹具）\n\n- 命题号：stmt:{SID}\n\n"
        f"## 命题\n\n（夹具命题）\n\n## 证明\n\n{PROOF}\n\n"
        + _DS2.render_dependency_section([]),
        encoding="utf-8")
    agent, _seam = _agent(other, "大概成立")
    bad = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=rel2)
    assert bad["checked"] is False and bad["reason"] == "unparsable", bad
    assert _ledger(other) == [], "结构不合法却落了一行台账"


# ------------------------------------------------------------------ s3

def _legacy_row(root: pathlib.Path, *, verdict: str = "看不出来",
                proof_text: str = PROOF) -> dict:
    """手写一行"2026-11-01 之前写下的"台账行（`verdict="看不出来"`）。

    为什么必须手写：写侧（`parse_verdict` / `record_verification`）已经收不了那一格了
    —— 它现在只认两态。要量"读侧读得出历史行、且它既不算票也不清零"，只能按老版本的
    形状把那一行直接追加进台账（`_append_verification` 是那一行的唯一落盘实现）。
    刻意不借 `record_verification` 造底稿：那会顺手多落一行"成立"，把票数改了。
    """
    legacy = {
        "verification_id": "v-legacy-000001",
        "statement_id": SID, "stmt_id": SID, "proof_no": 1,
        "verifier": "agent-V", "verdict": verdict, "defect_step": None,
        "quote": "", "why": "（历史行：信息不足，当年写的是看不出来）",
        "findings": [], "unresolved_errors": 0, "citation_checks": [],
        "proof_sha256": VR.text_sha(proof_text), "proof_chars": len(proof_text),
        "round": 3, "used_faces": [], "submission_id": "",
        "at": "2026-10-31T00:00:00+08:00",
    }
    VR._append_verification(VR.verification_ledger_path(root, SID), legacy)
    return legacy


def test_s3_a_historical_row_stays_a_statement_and_does_not_count(tmp_path):
    """s3（p247）：历史行（`verdict="看不出来"`）原样读得出，但不折档、不算票、不签。

    业主 2026-11-06 第三次收紧：「V 的判词只是陈述」「不做折档」。所以：
    ① 读得出：台账里三行都在，历史行那四个字原样还在盘上（不许被"顺手迁移"改掉）；
    ② 不算票：`成立, 成立, 看不出来` 的连续次数是 2 —— 只有前两行有秘书轴（夹具给的
       clean）；历史行没有轴 ⇒ 不算票、也不清零；
    ③ 第 3 位不动：`row_signable(legacy)` 为假、`bit3_payload(legacy, streak=3)` 为空。
    """
    root = tmp_path / "ws"
    root.mkdir()
    for _i in (1, 2):
        VR.record_verification(root, statement_id=SID, proof_text=PROOF,
                               verdict={"verdict": "成立", "findings": []},
                               verifier="agent-V",
                               secretary_judge={"checked": True, "axis": "clean",
                                                "decision": "没问题", "reason": "夹具"})
    holds2 = VR.consecutive_holds(root, SID)
    assert holds2["streak"] == 2, holds2

    legacy = _legacy_row(root)

    # ① 读得出：三行都在，历史行逐字还在
    rows = _ledger(root)
    assert len(rows) == 3, rows
    assert [r["verdict"] for r in rows] == ["成立", "成立", "看不出来"], rows
    text = VR.verification_ledger_path(root, SID).read_text(encoding="utf-8")
    assert '"verdict": "看不出来"' in text, "历史行被改写了（台账是追加式的，不许迁移）"
    assert VR.read_verdict(legacy) == "看不出来", "历史行被折档了"

    # ② 不算票：2（历史行没有轴）
    holds = VR.consecutive_holds(root, SID)
    assert holds["checked"] is True, holds
    assert holds["streak"] == 2, (
        f"历史行被算成票了（{holds['streak']}）：p247 的轴只由秘书给，"
        "老行的陈述不产生轴")
    assert holds["rows"] == 3, holds

    # ③ 第 3 位：这一行不够格签，凭据为空
    assert VR.row_signable(legacy) is False, "历史行仍被判成够格签第 3 位"
    assert VR.bit3_payload(legacy) == {}, VR.bit3_payload(legacy)
    assert VR.bit3_payload(legacy, streak=3) == {}, VR.bit3_payload(legacy, streak=3)

    # 补：它后面再来一票（有 clean 轴）就是第 3 票
    VR.record_verification(root, statement_id=SID, proof_text=PROOF,
                           verdict={"verdict": "成立", "findings": []},
                           verifier="agent-V",
                           secretary_judge={"checked": True, "axis": "clean",
                                            "decision": "没问题", "reason": "夹具"})
    assert VR.consecutive_holds(root, SID)["streak"] == 3, VR.consecutive_holds(root, SID)


# ------------------------------------------------------------------ s4

def _v_prompt() -> str:
    """渲染后的 V 提示词（system 那一份：`specs/v.py` 的职责文 + 技能索引）。"""
    return AP.system_prompt("V", registry=build_registry().registry)


def _cold() -> str:
    """V 的真实审阅入口（`verifications.cold_start_prompt`）。"""
    return VR.cold_start_prompt("对任意正整数 n，R(3,4)=9。", PROOF, readonly_facts="- 夹具")


def _state_problems(text: str) -> list[str]:
    """渲染面里"这一档还在不在"的判据本体（s4 的两份文本共用它）。

    只看 `看不出来` 这四个字出现的每一行：允许的唯一载体是业主逐字要求写的那句
    否定式（`不存在『看不出来』这一档`）—— 其余每一行都点名报出来。这样既钉住
    "三态那一档没了"，又不会把业主原话里的引号内容误判成"这一档还在"。
    """
    bad: list[str] = []
    if TWO_STATES not in text:
        bad.append("没有写清两态（成立 = 没找到缺陷 / 有毛病 = 找到了缺陷）："
                   f"缺那一句 {TWO_STATES!r}")
    if NO_THIRD not in text:
        bad.append(f"没有写清「看不出错就是成立、不存在看不出来这一档」那一句：缺 {NO_THIRD!r}")
    for line in text.splitlines():
        if "看不出来" in line and ALLOWED_CARRIER not in line:
            bad.append(f"这一行还留着『看不出来』那一档：{line.strip()[:160]}")
    return bad


def test_s4_the_rendered_prompts_carry_only_two_states():
    """s4：渲染后的 V 提示词只有两态，且不再有『看不出来』这一档。

    两份文本都判（`system_prompt("V")` = 职责文 + 技能索引；`cold_start_prompt` = V 每次
    审阅真正读到的入口）：两态那两句必须逐字在，`看不出来` 只许出现在那句否定式里。

    反真空：把同一份文本里的那句否定式换回改前的三态那一行 ⇒ `_state_problems` 必须
    当场报出"这一行还留着"，否则这条判据只是"文本很长"。
    """
    system_text = _v_prompt()
    cold_text = _cold()
    # 反真空锚：两份都得是真的渲染出来的长文本（不是空串 / 占位）
    assert len(system_text) > 5000, len(system_text)
    assert len(cold_text) > 500, len(cold_text)

    for name, text in (('system_prompt("V")', system_text), ("cold_start_prompt", cold_text)):
        bad = _state_problems(text)
        assert bad == [], f"{name}：\n" + "\n".join(bad)

    # 正控：负控那两个探针不是"恒不报"（把否定式换回改前三态那一行 ⇒ 必报）
    old = "三态：`成立` / `有毛病` / `看不出来`"
    for name, text in (('system_prompt("V")', system_text), ("cold_start_prompt", cold_text)):
        probe = text.replace(NO_THIRD, old)
        assert probe != text, f"{name} 里没有那句否定式 ⇒ 负控打不中（判据是假绿）"
        assert _state_problems(probe), f"{name} 的负控失效：换回三态之后判据没报"

    # 两份文本各自都要有两态那两句（不是只有其中一份改到了）
    assert TWO_STATES in system_text and TWO_STATES in cold_text
    assert NO_THIRD in system_text and NO_THIRD in cold_text


# ------------------------------------------------------------------ s5

def _tool_face(name: str = "verify.verify_proof") -> str:
    """一件工具「模型看得见的那段文字」：`summary` ＋ `returns`。

    为什么 `returns` 与提示词算同一类面（不是"实现细节"）：`verify_tools.py` 自己
    那段注释逐字写着它的去向 ——「`returns` 会拼进 function-calling 的 description
    ⇒ 模型看得到，声明里没有的字段它就不知道存在」。既然提示词那一侧已经收成两态，
    这段文字里再留着旧档，模型读到的就是一档它自己产不出的结论。
    """
    spec = build_registry().registry.get(name)
    assert spec is not None, f"工具面里没有 {name} ⇒ 这条判据失去对象"
    return "\n".join([str(spec.summary or ""), str(spec.returns or "")])


def _tool_face_problems(text: str) -> list[str]:
    """工具声明面里"旧档还在不在"（s5 的判据本体，与 s4 同一把尺子、对象不同）。

    两件事各判一次：
    ① `看不出来` 这四个字一次都不许出现 —— 与 s4 不同，这里不留「否定式」那个
       例外：声明面是按键与用途写的，没有给「不存在某一档」留位置；真要在声明面里
       写它，读的人只会以为那一档存在过且仍可用；
    ② 语义不许缩水：`checked=False` 那一档必须仍被写成"没查成"且"不落台账行"。
       只删旧档不补这一句，等于把"这一档不许被读成审过、没问题"这条约束也一起删掉
       —— 那比不删更坏（模型会把 `checked=False` 读成"审过了、只是没毛病"）。
    """
    bad: list[str] = []
    for line in text.splitlines():
        if "看不出来" in line:
            bad.append(f"这一行还留着『看不出来』那一档：{line.strip()[:200]}")
    if "checked=False" not in text:
        bad.append("声明面里没有 `checked=False` 这一档 ⇒ 它被整段删掉了，不是改了措辞")
    if "没查成" not in text:
        bad.append("`checked=False` 没有写成「没查成」⇒ 读的人会把它读成别的意思")
    if "不落台账行" not in text:
        bad.append("`checked=False` 那一档没有写清「不落台账行」（这一档唯一的硬后果）")
    return bad


def test_s5_the_tool_declaration_face_does_not_name_the_retired_state():
    """s5：`verify.verify_proof` 的声明面（`summary` ＋ `returns`）里不再有旧档。

    这一条守的是模型那一侧的可见面。改前 `returns` 末尾写着「此时不落台账行，
    绝不拿「看不出来」冒充「审过了」」—— 而 V 从 2026-11-01 起只产 `成立` / `有毛病`
    两态，`看不出来` 那一档已经不存在。留着这句话的代价不是"多一句废话"：
    模型看到的是"我这一档的结论有可能落在『看不出来』"，而它根本产不出那个值；
    同时"`checked=False` 不许被读成审过了"这条约束被绑在了一个不存在的档上。

    反真空两条：
    1) 声明面必须是真的那份（长度锚），否则"没出现这四个字"在一个空串上恒真；
    2) 把改前那句措辞塞回去 ⇒ `_tool_face_problems` 必须当场报（探针打不中就是假绿）。
    """
    text = _tool_face()
    assert len(text) > 500, len(text)

    bad = _tool_face_problems(text)
    assert bad == [], "\n".join(bad)

    # 正控：把改前那句措辞塞回去 ⇒ 必报（且报的是"还留着那一档"，不是别的原因）
    probe = text.replace("「没查成」冒充", "「看不出来」冒充")
    assert probe != text, "声明面里找不到「没查成」冒充「审过了」那句 ⇒ 探针打不中（判据是假绿）"
    hit = _tool_face_problems(probe)
    assert hit, "塞回旧档措辞之后判据没报 ⇒ 它没在量这四个字"
    assert any("看不出来" in x for x in hit), hit

    # 反真空②：只删旧档、把"没查成 / 不落台账行"一起删掉的那一版同样必报
    gutted = text.replace("没查成", "").replace("不落台账行", "")
    assert _tool_face_problems(gutted), (
        "把 `checked=False` 那两格约束一起删掉而判据没红 ⇒ 它只钉了字面，没钉语义"
    )
