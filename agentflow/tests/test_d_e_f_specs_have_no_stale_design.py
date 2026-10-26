# -*- coding: utf-8 -*-
"""判据：D / E / F 三格的过时设计残留（2026-10-25 审计 G/D/E/F/S 那一批）。

## 每一条对上一个审计条目

| 条目 | 守的那件事 |
|---|---|
| G1 / G2 | D 的 policy 不再点 `conductor.summon`（D 没有这件工具）；派 C/派 B 走循环的 `summon` 形状 |
| G3 | 销号用 `retire_child(child_name=…)`，不是 `task_id=` |
| G4 | E 不再被教「写 `statements` 的 `proof_text`」；结论落 `verifications/<命题号>.jsonl`（文件，不是表） |
| G5 | F 不再点 `verify.read_proof`（V 专属）；改成「请 V 用 `read_proof` 读回再问你」 |
| ④ | 销号只有一套口径：`retire` 形状是旧路、指向 `conductor.retire_child` |
| D4 | 研究手稿是七节（成果概述在最前） |
| D5 | 论文对应表归 G 写；D 只把那一行的格凑齐 |
| F1 | 预算写「四类键」，不再叫「三维预算」 |
| F4 | `attack_plans` 子目标状态六档 |
| E7 | `numeric` 是实验方法，不是证据档（证据档是 `cross_check` / `heuristic`） |
| S4 | `block` 不是 `done` 的下一档 —— 画成两个并列出口 |
| S5 | 五位（谁签）与四档等级拆成两句 |
| E3 / E4 | E 的 policy 只剩一句「形式化以 V 的签与 B 的台账为准」；「与形式化」半句与重复的整条都删了 |
| E5 | 技能书索引末尾那句形式化口径不再发给 E |
| E6 | `exhaustive` 是顶格参数，不在 `observations` 里 |
| E8 | E 的工具面 0 件 `formal.*` / `detect_verifier`；它的提示词里也没有 `formal.` 记号 |
| D6 / F3 / F5 | F 只写证明手稿与那一节 `## 依赖`；`statements` 那一行交给 B 登记（2026-10-26 裁定：作者只写内容，登记由收方读稿产生） |
| F6 | 形式化那一档只能由用户指定 |
| F7 | 「收件板」→「工作项板」 |
| F8 | E 的职责句不再带「攻坚」 |

## 判据（正控逐条 / 渲染完好 / 反真空）

每条正控都直接读渲染出来的提示词或 `ROLE_BRIEFS` 的 policy（真身是 `specs/<role>.py`），
失败信息以 `[条目号]` 开头。`test_zz_rendered_prompts_are_not_corrupted` 是判据 d：
三份提示词里不出现 `⏎`、不出现退格造成的残字。
"""
from __future__ import annotations

import pytest

from agentflow import agent_prompts as AP
from agentflow.tools import build_registry

ROLES = ("D", "E", "F")
_TASK = "把这一件活做完"
_ROOT = "D:/x"


@pytest.fixture(scope="module")
def registry():
    return build_registry().registry


@pytest.fixture(scope="module")
def prompts(registry) -> dict[str, str]:
    return {r: AP.system_prompt(r, registry=registry, task=_TASK, workspace_root=_ROOT)
            for r in ROLES}


def _policy(role: str) -> str:
    return "\n".join(str(x) for x in AP.ROLE_BRIEFS[role].policy)


def _flat(text: str) -> str:
    """去掉空白 —— 判「读到的意思」，不判排版换行。"""
    return "".join(str(text).split())


def _has(text: str, needle: str) -> bool:
    return _flat(needle) in _flat(text)


# ============================================================ G1 / G2
def test_g1_g2_d_does_not_name_conductor_summon(prompts) -> None:
    """G1/G2：D 的 policy 与渲染提示词里没有 `conductor.summon`；派 C/派 B 走 summon 形状。"""
    policy = _policy("D")
    assert not _has(policy, "`conductor.summon`"), (
        "[G1/G2] D 的 policy 又点名了 `conductor.summon` —— 那是 M 的工具，D 上只有循环的 "
        "`summon` 形状；照做只会 `unknown_tool`")
    assert _has(policy, "`summon` 形状派 C"), "[G1] D 的 policy 里读不到「用 `summon` 形状派 C」"
    assert _has(policy, "`summon` 形状派 B"), "[G2] D 的 policy 里读不到「用 `summon` 形状派 B」"
    assert not _has(prompts["D"], "conductor.summon"), (
        "[G1/G2] D 的渲染提示词里还印着 conductor.summon（工具目录之外的 policy 段没清干净）")


# ============================================================ G3 / ④
def test_g3_and_d1_retire_uses_child_name_and_one_path(prompts) -> None:
    """G3/④：销号参数是 `child_name`；`retire` 形状标成旧路并指向 `conductor.retire_child`。"""
    policy = _policy("D")
    assert "retire_child(child_name=" in policy, (
        "[G3] D 的 policy 仍写着 retire_child(task_id=…) —— 新写的一律用 child_name")
    assert "retire_child(task_id=" not in policy, "[G3] D 的 policy 里还有 task_id= 那种旧写法"
    assert "旧路" in policy and "conductor.retire_child" in policy, (
        "[④] D 的 policy 没有把 `retire` 形状标成旧路、也没有指向唯一入口 conductor.retire_child")
    # 形状表那一侧：无论措辞是「旧路」还是「两个入口同一落点」，都必须指向同一件工具 ——
    # 这一格只钉"落点是 conductor.retire_child"，不钉另一个并行批次怎么改那半句措辞。
    assert "conductor.retire_child" in AP.COLLAB_SHAPES_TEXT, (
        "[④] 形状表那一侧（COLLAB_SHAPES_TEXT）没有把销号指向 conductor.retire_child")
    assert "旧路" in AP.COLLAB_SHAPES_TEXT or "同一落点" in AP.COLLAB_SHAPES_TEXT, (
        "[④] 形状表那一侧既没把 retire 标成旧路、也没说它和工具是同一落点")


# ============================================================ G4 / E3
def test_g4_e_does_not_write_statements_or_call_a_verifications_table(prompts) -> None:
    """G4/E3：E 的正文交 B（由 D 派 B 登记）；结论落 `verifications/<命题号>.jsonl`。"""
    policy = _policy("E")
    assert not _has(policy, "`statements` 表的 `proof_text`"), (
        "[G4] E 的 policy 仍在教它写 `statements` 的 `proof_text` —— E 的写集只有 experiments")
    assert _has(policy, "交 B") and _has(policy, "由 **D** 派 B 登记进"), (
        "[G4] E 的 policy 没有写清「正文交 B（由 D 派 B 登记）」")
    assert _has(policy, "`verifications/<命题号>.jsonl`"), (
        "[G4] E 的 policy 没有把结论落点写成 `verifications/<命题号>.jsonl`")
    assert not _has(policy, "`verifications` 表"), (
        "[G4] E 的 policy 仍说「verifications 表」—— 那是一份文件，不是表")
    assert "与形式化（" not in policy, (
        "[E3] E 的 policy 里还有「与形式化（…）」那半句（形式化侧已清干净）")


# ============================================================ G5
def test_g5_f_does_not_name_vs_read_proof(prompts) -> None:
    """G5：F 不再点 `verify.read_proof`，改成请 V 用 `read_proof` 读回再问。"""
    policy = _policy("F")
    assert "verify.read_proof" not in policy, (
        "[G5] F 的 policy 仍点名 `verify.read_proof` —— 那是 V 的工具（F 面上没有）")
    assert _has(policy, "请 V 用 `read_proof` 读回那一签再问你"), (
        "[G5] F 的 policy 没有写「请 V 用 `read_proof` 读回那一签再问你」")
    assert "verify.read_proof" not in prompts["F"], "[G5] 渲染提示词里还有 verify.read_proof"


# ============================================================ D4
def test_d4_the_manuscript_is_seven_sections(prompts) -> None:
    """D4：手稿七节，成果概述在第一 —— policy / 交付句 / 技能索引三处同口径。"""
    assert _has(prompts["D"], "成果概述 / 定义与已知 / 已确定的结论 / 尝试与失败 / "
                              "例子与反例 / 未解问题 / 下一步七节"), (
        "[D4] D 的交付句（deliverable）还是六节，或成果概述不在最前")
    assert _has(prompts["D"], "reports/RESEARCH.md 七节"), (
        "[D4] 技能书索引里那句 summary 还是「六节」")


# ============================================================ D5
def test_d5_the_mapping_table_belongs_to_g(prompts) -> None:
    """D5：论文对应表归 G 写；D 只把那一行的格凑齐。"""
    policy = _policy("D")
    assert _has(policy, "论文对应表归 G 写"), "[D5] D 的 policy 没有写「论文对应表归 G 写」"
    assert not _has(policy, "论文对应表 `out/paper/MAPPING.json` 那一行"), (
        "[D5] D 的 policy 仍把 MAPPING.json 的那一行算成自己写的")
    assert "doc.write_mapping" not in policy, (
        "[D5] D 的 policy 点了 `doc.write_mapping` —— 那是 G 的工具（也不该带组前缀）")


# ============================================================ F1
def test_f1_the_budget_is_four_keys_not_three_dimensions(prompts) -> None:
    """F1：预算写「四类键」，不再叫「三维预算」。"""
    from agentflow.specs import f as F_SPEC

    spec = next(s for s in F_SPEC.ACTIONS if s.action == "create_plan")
    props = (getattr(spec, "params", {}) or {}).get("properties", {}) or {}
    desc = str((props.get("budget", {}) or {}).get("description", ""))
    assert "三维预算" not in desc, "[F1] F.create_plan 的 budget 描述还叫「三维预算」"
    assert "四类键" in desc, "[F1] F.create_plan 的 budget 描述里没有「四类键」"


# ============================================================ F4
def test_f4_the_subgoal_status_vocabulary_is_six(prompts) -> None:
    """F4：`attack_plans` 子目标状态六档（不是三档）。"""
    from agentflow import agent_skills as AS

    body = "\n".join(s.body for s in AS.skills_for("F"))
    assert _has(body, "状态只用六档"), "[F4] 技能书里仍写「状态只用三档」"
    for label in ("待做", "在推", "有支持未证", "已证", "卡住", "已放弃"):
        assert _has(body, label), f"[F4] 六档里读不到「{label}」"


# ============================================================ E7
def test_e7_numeric_is_a_method_not_an_evidence_tier(prompts) -> None:
    """E7：`numeric` 不是证据档；证据档是 `cross_check` / `heuristic`。"""
    from agentflow import agent_skills as AS

    body = "\n".join(s.body for s in AS.skills_for("E"))
    assert _has(body, "`numeric` 是实验方法、不是证据档"), (
        "[E7] 技能书里仍把 `numeric` 写成「证据的一档」")
    assert _has(body, "落 `cross_check` / `heuristic`"), "[E7] 没有写清证据档的两档"


# ============================================================ S4
def test_s4_block_is_not_the_next_step_after_done(prompts) -> None:
    """S4：`block` 不是 `done` 的下一档 —— 画成两个并列出口。"""
    text = prompts["D"]
    assert _has(text, "两个并列出口"), "[S4] 板那一段没有把 done / block 画成两个出口"
    assert _has(text, "`block` 不是 `done` 的下一档"), "[S4] 没有明说 block 不是 done 的下一档"


# ============================================================ S5
def test_s5_five_bits_and_four_grades_are_two_sentences(prompts) -> None:
    """S5：五位说谁签、四档等级另起一句。"""
    text = prompts["D"]
    assert _has(text, "五个证据位") and _has(text, "这五位只回答「谁签过字」"), (
        "[S5] 五位那一段没有把「谁签」单独成句")
    assert _has(text, "四档等级"), "[S5] 等级那一段没有写成「四档等级」的独立一句"


# ============================================================ E4 / E5 / E6 / E8
def test_e4_the_duplicate_formal_line_is_gone(prompts) -> None:
    """E4：E 的 policy 只剩一句形式化口径（重复的整条已删）。"""
    lines = [str(x) for x in AP.ROLE_BRIEFS["E"].policy if "形式化" in str(x)]
    assert len(lines) == 1, (
        f"[E4] E 的 policy 里还有 {len(lines)} 条讲形式化的（应只剩「形式化以 V 的签与 B 的台账为准」"
        "那一条）：\n  - " + "\n  - ".join(lines))
    assert "形式化要不要做由用户指定" not in _policy("E"), (
        "[E4] 那条重复的「形式化要不要做由用户指定…」还在")


def test_e5_the_skill_index_does_not_send_the_formal_line_to_e() -> None:
    """E5：技能书索引末尾那句形式化口径不再发给 E（受众收窄）。"""
    from agentflow import agent_skills as AS

    assert "形式化以 V 的签与 B 的台账为准" not in AS.index_block("E"), (
        "[E5] E 的技能书索引里还有那句形式化口径（它的 Lean 侧已清干净）")
    assert "形式化以 V 的签与 B 的台账为准" in AS.index_block("M"), (
        "[E5] 收窄过头了：M 的技能书索引里也没有那句（它仍然需要）")


def test_e6_exhaustive_is_a_top_level_parameter(prompts) -> None:
    """E6：`exhaustive` 是顶格参数，不在 `observations` 里。"""
    policy = _policy("E")
    assert "`observations` 里的 `exhaustive`" not in policy, (
        "[E6] E 的 policy 仍说 `observations` 里的 `exhaustive` —— 它其实是顶格参数")
    assert _has(policy, "**顶格参数**，不是塞进 `observations` 里"), (
        "[E6] E 的 policy 没有写清 exhaustive 是顶格参数")


def test_e8_e_has_no_formal_tool_and_no_formal_token(prompts, registry) -> None:
    """E8：E 的工具面 0 件 formal.* / detect_verifier；提示词里也没有 formal.* 记号。"""
    surface = {str(s.name) for s in registry.for_role("E")}
    assert not [n for n in surface if n.startswith("formal.")], (
        f"[E8] E 的工具面上出现了 formal.*：{sorted(n for n in surface if n.startswith('formal.'))}")
    assert "verify.detect_verifier" not in surface, "[E8] E 的工具面上出现了 detect_verifier"
    assert "formal." not in prompts["E"], "[E8] E 的提示词里还有 formal.* 记号"
    assert "verify.detect_verifier" not in prompts["E"], (
        "[E8] E 的提示词里还印着 detect_verifier")


# ============================================================ D6 / F3 / F5
#: 被 2026-10-26 裁定推翻的那几句原话（逐字，不从当前文本拼 —— 拼出来的"旧版"会随修好一起变好）。
#: 它们一个都不许再出现在 F 的 policy 与渲染提示词里。
_F_STALE_STATEMENTS: tuple[str, ...] = (
    "那一行由你写",
    "你自己落成 `statements`",
    "你落 `statements` 那一行",
)

#: D 那一侧被推翻的那一句（同一批裁定：F 自产的证明也由 B 登记）。
_D_STALE_STATEMENT = "F 自己产出的证明由 F 自己落那一行"


def _f_statement_problems(policy: str, prompt: str, d_policy: str) -> list[str]:
    """D6 / F3 / F5 的尺子（正控与负控共用同一份 —— 负控要证明的正是"它在这种形态下必红"）。"""
    problems: list[str] = []
    if not _has(policy, "交给 **B 登记**"):
        problems.append("[F3/F5] F 的 policy 里读不到「交给 B 登记」"
                        "（2026-10-26：作者只写内容，登记由收方读稿产生）")
    if not _has(policy, "你不写那张表"):
        problems.append("[F3/F5] F 的 policy 里读不到「你不写那张表」"
                        "⇒ 读的人还会以为 `statements` 在它的写集里")
    for line in _F_STALE_STATEMENTS:
        if _has(policy, line):
            problems.append(f"[F3/F5] F 的 policy 里还有旧口径原话 {line!r}")
        if _has(prompt, line):
            problems.append(f"[F3/F5] F 的渲染提示词里还印着旧口径 {line!r}")
    if not _has(d_policy, "**文献侧**定理与证明由 **B** 收进"):
        problems.append("[D6] D 的 policy 没有把 B 的 statements 登记限定在文献侧")
    if not _has(d_policy, "F 自己产出的证明也由 B 登记"):
        problems.append("[D6] D 的 policy 没跟上 2026-10-26 的裁定："
                        "F 自产的证明也由 B 登记")
    if _has(d_policy, _D_STALE_STATEMENT):
        problems.append(f"[D6] D 的 policy 里还有被推翻的那句 {_D_STALE_STATEMENT!r}")
    return problems


def test_d6_f3_f5_f_hands_the_statements_row_to_b(prompts) -> None:
    """D6/F3/F5：F 不自己落 `statements` 那一行 —— 它交给 B 登记。

    ## 改前那一条守着什么，它为什么过期了

    本条改前叫 `test_d6_f3_f5_f_writes_the_statements_row_itself`：它断言 F 的 policy 里有
    「你自己落成 `statements` 一行」，并且断言提示词里不许出现「由 B 登记」。那是 2026-10-25
    的口径（B 只收文献侧，F 自产的证明由 F 自己落那一行）。

    2026-10-26 的裁定把它整个翻了过来：作者只写内容，登记由收方读稿产生 —— 与「V 读你的
    手稿再签字」同一个逻辑。于是 `specs/f.py` 的三处 policy 改成「交给 B 登记」，
    `WRITE_SETS["F"]` 也拿掉了 `statements` 那一格（秘书那一层只认
    `secretary.STATEMENT_WRITER_ROLES = ("B",)`）。

    代码没有回退：policy 与写集两处都按新口径改了，而且
    `tests/test_f_hands_propositions_to_b.py` 在正面钉着它。红的是本判据 —— 它断的是被推翻
    的旧口径的原话，于是 HEAD 上它一直红着、而没有人回来管。那正是这类判据最贵的死法：
    红着的判据与坏掉的代码在报告里长得一样。所以这一格改成钉新口径。

    ## 新口径钉三件

    ① F 的 policy 里读得到「交给 B 登记」与「你不写那张表」；
    ② 那三句旧原话一句都不许留（policy 与渲染提示词两个面都判）；
    ③ D 那一侧同一口径：文献侧由 B 收进、F 自产的证明也由 B 登记。

    负控：把旧原话塞进这份文本的副本 ⇒ 同一个尺子必须点红
    （`test_d6_putting_the_old_wording_back_goes_red`）。
    """
    problems = _f_statement_problems(_policy("F"), prompts["F"], _policy("D"))
    assert not problems, "\n".join(problems)


def test_d6_putting_the_old_wording_back_goes_red(prompts) -> None:
    """负控：把旧口径的原话塞回去 ⇒ 上面那个尺子必须点红（三类各一次）。

    只断言"今天的文本里没有某个串"无法区分"改好了"与"这句话本来就不在这份文本里" ——
    改前那条判据正是后者：它要的串在改后的 policy 里永远不会有，所以它只会一直红。
    """
    clean = _f_statement_problems(_policy("F"), prompts["F"], _policy("D"))
    assert clean == [], f"干净的那一份就有问题，下面的负控证明不了什么：{clean}"

    # ① 把 F 那三句旧原话塞回 policy 的副本
    dirty_f = _policy("F") + "\n" + "\n".join(_F_STALE_STATEMENTS)
    problems = _f_statement_problems(dirty_f, prompts["F"], _policy("D"))
    stale_hits = [p for p in problems if "旧口径原话" in p]
    assert len(stale_hits) == len(_F_STALE_STATEMENTS), (
        f"塞回 {len(_F_STALE_STATEMENTS)} 句旧原话，尺子只点出 {len(stale_hits)} 句：{problems}")

    # ② 把 D 那句「F 自己落那一行」塞回 D 的 policy 副本
    dirty_d = _policy("D") + "\n" + _D_STALE_STATEMENT
    problems = _f_statement_problems(_policy("F"), prompts["F"], dirty_d)
    assert any(_D_STALE_STATEMENT in p for p in problems), (
        f"D 的 policy 里塞回了那句被推翻的话，尺子却没点出来：{problems}")

    # ③ 把「交给 B 登记」从副本里抠掉 ⇒ "缺新口径"这一半也要点红（不是只判旧串）
    cut = _policy("F").replace("交给 **B 登记**", "自己处理")
    problems = _f_statement_problems(cut, prompts["F"], _policy("D"))
    assert any("交给 B 登记" in p for p in problems), (
        f"把新口径那句抠掉之后尺子没点红，说明它只在判旧串：{problems}")


# ============================================================ F6
def test_f6_formal_is_only_by_user_instruction(prompts) -> None:
    """F6：形式化那一档只能由用户指定。"""
    assert _has(prompts["F"], "只能由用户指定"), (
        "[F6] F 的提示词里读不到「形式化只能由用户指定」")


# ============================================================ F7
def test_f7_the_board_is_called_a_work_item_board(prompts) -> None:
    """F7：「收件板」→「工作项板」。"""
    policy = _policy("F")
    assert "工作项板" in policy, "[F7] F 的 policy 里没有「工作项板」"
    assert "收件板" not in policy, "[F7] F 的 policy 里还有「收件板」"


# ============================================================ F8
def test_f8_es_duty_has_no_attack_word(prompts) -> None:
    """F8：E 的职责句删掉「攻坚」。"""
    assert "攻坚" not in AP.ROLE_BRIEFS["E"].duty, (
        f"[F8] E 的 duty 还带着「攻坚」：{AP.ROLE_BRIEFS['E'].duty!r}")
    assert AP.ROLE_BRIEFS["E"].duty.startswith("数值实验"), AP.ROLE_BRIEFS["E"].duty


# ============================================================ 判据 d 渲染完好
@pytest.mark.parametrize("role", ROLES)
def test_zz_rendered_prompts_are_not_corrupted(role: str, prompts) -> None:
    """d：三份提示词里不出现 `⏎`、不出现退格造成的残字。"""
    text = prompts[role]
    for bad, why in (("⏎", "换行被写成可见的 ⏎"), ("\x08", "退格字符残留"),
                     ("\ufffd", "替换字符（编码坏了）")):
        assert bad not in text, f"{role} 的提示词里有 {bad!r}：{why}"
