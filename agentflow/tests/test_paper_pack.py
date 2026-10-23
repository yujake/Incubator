"""论文段的提示词（⑥）与 24 条断言的验收判据（⑦）（`draft/28` §189；`draft/117` 改写）。

## 这一组守什么

`draft/28` §184.5 的第 6、7 步，以及终点门槛 A 里那两句可机械判的话（"交付说明与 ACCEPTANCE.md 对齐"、"5 条判据无一条 judge_not_wired"）。

1. 提示词段只给该看的角色：论文段里有 P1–P11 的判据表位置、claims 台账语义、
期刊体例与完成定义。它给 M/G/H；给 A/B/C/E/F 是噪音 —— 而噪音会稀释它们真正要看的东西。这一条用"该有的都有、不该有的都没有"两个方向钉住。
2. 结论强于引文：机械半（`faculty_checks.claim_strength_findings`）逐条比对
"这条断言说了多强"与"它挂的证据等级"，语义半（`judges` 的`claims.conclusion_strength`）带负控准入。两半都由判据本体检查，不靠我口头保证。

## 2026-10-13 这一轮改了什么（业主裁定：「paper_package 里那些东西都是古早废案了，
## 我们要智能体写文章」）

段里凡是"项目自带渲染脚本 / 机械产的附录与四张表 / 渲染锚 0 漂移 / 派 `G.paper_package`"的句子都换成了"正文由智能体自己写 → `doc.paper_compile` 编 → 核回执里的
`tex_sha256`"。两条判据因此换了对象（不是被删）：`PACK_FOLLOW_FACTS` 从"点名让包跟上那个动作"改成"点名让 PDF 跟上那份正文的工具与回执"，"核锚的时机"那条改成"重编的时机"。
另有一条纪律随机制一起消失（不是被删）：旧段要求"会写台账的动作（`H.verify_fixes`）排在最后一次重渲染之前"—— 那是因为旧锚把台账行也算进 `files` 维度；现在回执只认`main.tex`，写台账不再让
PDF 过期，所以那句话既不对也没用了。退场面见 `draft/117`。
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest

from agentflow import agent_prompts as AP
from agentflow import faculty_checks as FC
from agentflow import judges as JG
from agentflow import schema as S
from agentflow.deliver import gate
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

# ============================================================ ⑥ 提示词段


def _registry(store: Store):
    return build_registry(store=store, workspace_root=store.root,
                          roles=tuple(S.ROLES)).registry


def _prompt(role: str, store: Store) -> str:
    return AP.system_prompt(role, registry=_registry(store), task="只读重放一次论文包")


def test_the_review_role_is_told_where_the_paper_is(store: Store):
    """判据（业主 2026-10-13：「H 要能对论文进行只读审核，至于论文在哪可在派活时告诉它」）。

    H 的工具面全量只读 ⇒ 它审论文靠 `fs.read`，所以落点必须由派活给（不是靠它猜、
    也不是靠框架新加一件工具）。这条判据钉住三件事在 H 读得到的地方：
    ① 落点由派活告诉它；② 它只读（一个字都不改）；③ 报告落到框架定的 `out/review/`。
    """
    text = _prompt("H", store)
    for fact in ("由派活告诉你", "out/paper/main.tex", "fs.read", "读是你的全部手段",
                 "out/review/<doc_id>-review.md", "review_files"):
        assert fact in text, f"H 的提示词里没有 {fact!r}"


def test_the_paper_section_goes_to_the_roles_that_touch_the_paper(store: Store):
    """正控：M（统筹交付）/ G（写正文并编译）/ H（审校）看得到这一段。

    `R6`：这条判据原先钉的是旧字面量 `完成定义（五条全过才算交付`，而那个"五条"是
    手抄计数（真身 = `closing.DEFAULT_CHECKS` 的 8 格）⇒ 改成钉新口径：
    这一段不许写死条数（格数以 `conductor.closing` 的当次读数为准），并把这个
    "不许写死"本身变成判据 —— 比原来那条更难满足（写了旧数量就红）。
    """
    for role in AP.PAPER_PACK_ROLES:
        text = _prompt(role, store)
        assert "论文（你参与的那份交付物）" in text, role
        assert "完成定义" in text, role
        assert "五条全过" not in text, f"{role}：完成定义里还写着旧的手抄条数（五条全过）"
        assert "收工门八格全过" in text, f"{role}：完成定义里没写清真身格数（八格）与「以读数给」的口径"


def test_the_paper_pack_style_section_speaks_to_the_right_role(store: Store):
    """`R6` 缺陷 4（收件人错）：体例那一节对 M 用第二人称、对 G/H 不许用第二人称。

    事实：`PAPER_PACK` 无条件注入 M/G/H，而第八节原文是"体例由你（M）裁定" ⇒
    G/H 读到时"你"就是它自己，会以为体例归自己定。修法是条件渲染：
    - M：得完整那节（含"体例由你（M）裁定"）；
    - G/H：得一句"报告体例由 M 裁定，不是你的活"，且不出现"由你（M）"。

    负控（同一条里）：把条件渲染去掉（三个角色都拿完整段）⇒ G/H 那两条断言必红。
    """
    tex = {r: _prompt(r, store) for r in AP.PAPER_PACK_ROLES}
    assert "体例由你（M）裁定" in tex["M"], "M 该拿到完整那节（含第二人称的体例裁定）"
    for role in ("G", "H"):
        assert "报告体例由 M 裁定" in tex[role], f"{role}：没拿到「体例归 M」那一句"
        assert "体例由你（M）裁定" not in tex[role], (
            f"{role}：提示词里还有第二人称的体例表述（由你（M））—— G/H 会把「你」读成自己")
        # 其余各节对 G/H 仍应保留（这一改只换第八节的标题行，不截断后文）
        assert "完成定义" in tex[role], f"{role}：换标题行时把后面的节也弄丢了"
    # 反负控：把条件渲染换回"三个角色都给完整段" ⇒ G/H 那两条必须红
    naive = {r: AP.PAPER_PACK for r in AP.PAPER_PACK_ROLES}
    bad = [r for r in ("G", "H") if "体例由你（M）裁定" in naive[r]]
    assert bad == ["G", "H"], "反负控失效：完整段喂给 G/H 时判据认不出第二人称"


@pytest.mark.parametrize("role", ["A", "B", "C", "D", "E", "F"])
def test_other_roles_do_not_get_the_paper_pack_section(store: Store, role: str):
    """负控（不许扩大化）：不碰论文包的角色看不到这一段 —— 噪音会稀释它们要看的东西。"""
    text = _prompt(role, store)
    assert "out/paper/ACCEPTANCE.md" not in text, role
    assert "完成定义（五条全过才算交付" not in text, role


def test_the_paper_pack_section_carries_the_four_required_facts(store: Store):
    """判据（内容）：交付物段必须说到的事 —— 交付物是正文、哪里能改、判据表、台账语义、工作循环。

    这一条在 `goal-a5334ee8` 的第一刀之后改过一次（旧版要的是 `ctexart` 与五个标记 ——
    那是评审摘要时代的产物）。用户对 §228 那轮的判词是「你觉得这个产出是论文吗？」：
    摘要里凑齐五个标记与"一篇更好的论文"是两件事，判据必须钉后者。
    """
    text = _prompt("G", store)
    for fact in ("由智能体自己写出来的论文正文", "可改、该改", "只读基线", "appendix.tex",
                 "out/paper/ACCEPTANCE.md", "P1–P11", "逐条回应那十行",
                 "cross_check", "不构成证明", "结论不许强于它挂的证据",
                 "doc.paper_compile", "COMPILE-RECEIPT.json",
                 "正文与 PDF 对得上", "正文有内容级的改动", "review_findings", "依据",
                 # 2026-10-13 业主的四条口径（③②⑤）：只在成文阶段写论文 / H 的落点由派活给 /
                 # 成文阶段所有角色都可能有任务 / review 报告的落点与它的读数
                 "但只在成文阶段写", "H 审论文", "靠派活告诉它",
                 "成文阶段所有角色都可能有任务", "review_files",
                 "审校这条链的中心是 B / H / V"):
        assert fact in text, f"论文段里没有 {fact!r}"
    # 第七节（摄取与派活的三条纪律，`draft/37` §48 的真机读数）：这三句是行为口径，
    # 不是说明文字 —— 上一趟真机正是在这三处各栽了一次（通配吃掉配套文档 /
    # 出处指到配套文档 / 把"没核"写成 false）。
    for fact in ("登记要指到论文本体", "unsupported_format", "source_lit_id",
                 "quote_verified", "不传（= 还没查）"):
        assert fact in text, f"论文包段里没有 {fact!r}"
    # 第八节（交付说明的体例归 M，R9 / 裁决 1）：框架不再自带节名清单，
    # 也不再逐节核（旧判据 `report_shape` 的九节那一半与 `report_sections_have_readings`
    # 都已废）。留在提示词里的只有三条与体例无关的硬要求 + 收工门怎么跑。
    # 这条断言跟着 R9 改：它此前要的是"九节形状 / 六、体例与表述 / 九、诚实边界 / 分栏"
    # —— 那几句正是被废除的判据在提示词里的复述（P-02）。
    #
    # `R6` 缺陷 4：第八节的收件人要对 —— 这一段注入 M/G/H，而"体例由你（M）裁定"
    # 是对 M 说的（G/H 读到会把"你"当成自己）。本用例取的是 G 的提示词 ⇒
    # 这里断言 G 侧口径（M 侧由 `test_the_paper_pack_style_section_speaks_to_the_right_role` 覆盖）。
    assert "报告体例由 M 裁定" in text, "G 没拿到「体例归 M」那一句"
    assert "体例由你（M）裁定" not in text, "G 的提示词里有第二人称的体例表述 —— 它会以为体例归自己定"
    # 第九节（无人值守那一档的口径，`draft/37` §66）：判据在这一档上是 fail，
    # 而"fail 不是缺陷、也不许靠不问绕开"这件事必须写在模型看得到的地方 ——
    # 否则下一趟的主控只会看到一格红读数，然后去猜是不是自己问错了。
    for fact in ("无人值守", "停在等待用户", "--resume", "甲/乙/丙"):
        assert fact in text, f"论文包段里没有 {fact!r}"
    # 第十节（报告里的台账引用必须真的存在，`draft/37` §70）：第十四趟真机六条判据全绿、
    # 收工门 can_close=true，而交付说明点了三条不存在的 statements 行 ——
    # 口径必须写在模型看得到的地方，否则它只会又一次把"打算做的"写成"做完的"。
    for fact in ("必须真的在盘上", "不许写成已登记", "outcome=refused", "回查台账"):
        assert fact in text, f"论文包段里没有 {fact!r}"


def test_the_paper_pack_section_is_versioned(store: Store):
    """判据（可追溯）：段变了版本号就要动 —— 提示词版本是审计记录里的一栏。

    p23 → p24（`draft/37` §16 P2）：本轮给 A/B/C/D/H/M 六个角色加了审阅线的口径（命中校验与定位确认、命题台账三件套、缺口→检索请求、初步数学审阅+可挽救性、采信规则、
    每跳写清提示词+目标变更必须 ask_user）。段变了，这一格必须跟着动。

    p24 → p25（`draft/37` §42）：用户裁定的两句 + ④ 的提示词那半 + ① 的口径（M 的交付说明落点、`emphasis['手']` 由 denied 改 minor、
    已在项目里别再`ensure_project`、"外部论文不是我方稿件"）。

    判据只要求"不早于 p24"：版本还会前进（P3/P4 之后还有刀），而这条要守的是"P2 那批口径属于 p24 及以后"，不是把版本钉死在今天。原来这里写的是 `== "p24"`（与它自己的意图相反：
    任何一次正当的段改动都会让它红，而红之后人会去改数字，而不是去看段）—— 2026-10-02 一并改成下界的写法。
    """
    assert int(AP.PROMPT_VERSION[1:]) >= 24, AP.PROMPT_VERSION


#: 这一段的四轮真机读数，每一轮都逼出一句必须写进提示词的话（`draft/37` §58/§59、`draft/117`）：
#: ① 2026-10-01（`projects/p3-review`）：只说"让包跟上"不够 —— 主控派 `G.build_document`（两次
#: `invalid_params`），包一个字节没变、锚报 `drifted`，21 步打完收工 ⇒ 段里要点名走哪条路径。
#: ② 同批第二次（`p3-review-20261001-220936`）：点名动作走通了，但 `H.verify_fixes` 排在 G 之后又改了
#: `review_findings`、锚当场变回 `drifted` ⇒ 段里要写"会写台账的动作排在最后一次重渲染之前"。 ③ 第三次（`...-221654`）：锚一致但 `main.tex` 一字未变 ⇒ 要写"核验证明的主路径"（当时算在
#: E 的形式化核验上；2026-10-24 之后那段改成"回执的四样 + 由 B 逐条安排"，所以这一条
#: 现在只剩"回执核什么"那半，`E.check_formal` 与"不注入任何库"两个 needle 随旧正文一起退场）。
#: ④ 第四次（2026-10-03）：连派三次 `G.revise` 都没让包跟上（它动的是稿件 markdown）⇒ 于是加了 `G.paper_package`；2026-10-13 业主裁定（`draft/117`）那一整条退场、正文由智能体自己写：段里改点名
#: "正文怎么进去（`fs.write`）/ 用哪件工具编（`doc.paper_compile`）/ 核什么（`COMPILE-RECEIPT.json` 的
#: `tex_sha256`）"，外加"没有建论文包这个动作"这个反例；②那条顺序纪律随机制消失（不是被删，是没了对象）。
PACK_FOLLOW_FACTS = ("fs.write", "doc.paper_compile", "COMPILE-RECEIPT.json",
                     "tex_sha256", "build_document", "G.revise",
                     '没有"建论文包"这个动作', "最后一次改正文")


def pack_follow_problems(text: str) -> list[str]:
    """只做一件事：段里有没有"让 PDF 跟上正文要走哪条路"这件事（空 = 有）。负控跑的就是它。"""
    return [f"论文段里没有 {fact!r}" for fact in PACK_FOLLOW_FACTS if fact not in text]


def test_the_paper_pack_names_the_tool_that_keeps_the_pdf_current(store: Store):
    """判据：段里必须点名"正文怎么进去、用哪件工具编、核哪个读数"，并说清哪些动作不会。

    为什么要写到这个粒度：`G.build_document` / `G.revise` / `G.render` 只动台账与稿件
    markdown，它们既不改 `out/paper/main.tex`、也编不出 PDF。一个字不写清，
    主控就会去派那个看起来最像"把论文弄出来"的动作，而它不会。
    """
    problems: list[str] = []
    for role in ("M", "G"):
        problems += [f"{role}：{p}" for p in pack_follow_problems(_prompt(role, store))]
    assert not problems, "；".join(problems)


def test_the_pack_follow_judge_catches_a_section_without_the_tool() -> None:
    """负控：把主路径那件工具名从段里拿掉 ⇒ 同一个检查函数必须报出来（否则那条判据是装饰）。

    拿掉的是 `doc.paper_compile`（2026-10-13 之后唯一能编 PDF 的那一件），
    而不是仍然作为反例留在段里的 `G.revise` / `build_document`
    （拿掉反例不改变"路在哪"这个事实，判据不该因此报错：这两件事是分开的）。
    """
    good = AP.PAPER_PACK
    assert pack_follow_problems(good) == [], "正控输入下必须干净"
    assert pack_follow_problems(good.replace("doc.paper_compile", "某个工具")), \
        "主路径工具名被拿掉却没报"
    assert pack_follow_problems(good.replace("build_document", "另一个动作")), "反例没报"
    assert pack_follow_problems("论文要编出 PDF。"), "空话连篇的段没报"


def test_the_paper_pack_says_the_pdf_must_be_rebuilt_after_the_edits(store: Store):
    """判据：最后一次改正文之后必须重编，这句必须在段里（不然"已完成"会与盘上产物分家）。

    来历（旧口径下实测，2026-09-30）：一轮跑出 `documents +3`、`experiments +4`，而
    `out/paper/main.pdf` 一个字节没变 —— 台账动了、包没跟上。现在那两件事不再耦合
    （回执只认 `main.tex`），但"改了正文不重编"这一形态一模一样地还在：收工门那一格
    会报 `paper_pdf_is_stale`，而它读的就是回执里的 `tex_sha256`。所以这句话要写成
    收工前的动作，而不是一句原则。
    """
    text = _prompt("G", store)
    for fact in ("doc.paper_compile", "COMPILE-RECEIPT.json", "tex_sha256",
                 "paper_pdf_is_stale", "最后一次改正文"):
        assert fact in text, f"论文段里没有 {fact!r}"
    # 负控：这句话不能只写给"读了论文段"的角色 —— M 才是决定收工的人。
    assert "paper_pdf_is_stale" in _prompt("M", store), "主控的提示词里没有这条收工判据"


# ============================================================ ⑥ 验收表解析（真机抓到的缺陷）


def test_the_acceptance_parser_does_not_read_not_ok_as_ok(tmp_path: pathlib.Path):
    """负控（测试当场抓到的解析缺陷）：`不成立` 不许被读成 `成立`。

    第一版判的是 `"成立" in cells[2]` —— 而 `"不成立"` 里含「成立」这个子串，
    于是写着「不成立」的那一行被数成成立（实测 2026-09-29：跑完真实验收，
    REPRO_RESULT 说 9/10，而解析出来的 `ok_count` 是 10）。这正是
    "看起来查过了、其实读反了"的形态。
    """
    from agentflow.tools.conductor_tools import _parse_acceptance

    doc = tmp_path / "ACCEPTANCE.md"
    doc.write_text(
        "# 最终验收：P1–P11 逐条读数\n\n结论：**有不成立的条目**（1/2）\n\n"
        "| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n"
        "| P1 | 甲 | 成立 | 读数甲 |\n"
        "| P2 | 乙 | **不成立** | 读数乙 |\n",
        encoding="utf-8")
    got = _parse_acceptance(doc)
    assert [r["ok"] for r in got["rows"]] == [True, False], got["rows"]
    assert got["ok_count"] == 1 and got["not_ok_count"] == 1, got


def test_the_acceptance_parser_reports_a_bad_table_as_a_problem(tmp_path: pathlib.Path):
    """负控（三态）：表被写坏时 `rows` 为空而 `problems` 非空 —— 空表 ≠ 解析失败。"""
    from agentflow.tools.conductor_tools import _parse_acceptance

    doc = tmp_path / "ACCEPTANCE.md"
    doc.write_text("# 验收\n\n结论：成立\n\n这张表不见了\n", encoding="utf-8")
    got = _parse_acceptance(doc)
    assert got["rows"] == [] and got["problems"], got


# ============================================================ ⑦ 机械半


def test_claim_strength_ignores_a_theorem_name_and_a_negation():
    """负控（测试当场抓到的两个误报）：定理的名字与否定式都不算"说得比证据强"。

    第一版我自己写了一组力度词（含裸的「证明」「定理」），于是：① `服从中心极限定理`
    —— 那是一个定理的名字，不是"我证明了它"；② `不构成证明` —— 这句话明说不是证明。
    两条都会被判成超证据。修法不是把词表调细，而是不另立词表：转发
    `claimanatomy` 已有的那条判据（见 `test_the_strength_criterion_has_exactly_one_implementation`）。
    """
    got = FC.claim_strength_findings([
        {"claim_id": "N1", "text": "主坐标的涨落服从中心极限定理", "evidence_kind": "cross_check"},
        {"claim_id": "N2", "text": "数值上与公式一致（不构成证明）", "evidence_kind": "cross_check"},
        {"claim_id": "N3", "text": "该恒等式没有被证明，只是数值一致", "evidence_kind": "cross_check"},
    ])
    assert got["verdict"] == "within_evidence", got
    assert got["overclaimed"] == [] and got["problem_count"] == 0, got


def test_claim_strength_flags_a_claim_stronger_than_its_evidence():
    """正控（要抓的形态）：证据是 cross_check，正文却写着「证明了」。

    断言按"台账里已经躺着一条"来造 —— 合规的构造器会拒收它（见下面那条判据），
    而这一格要拦的正是"从别处写进来的那一行"（迁移、直接落库、判据晚于行）。
    """
    got = FC.claim_strength_findings([
        {"claim_id": "C1", "text": "我们证明了主坐标的涨落服从中心极限定理",
         "evidence_kind": "cross_check"},
    ])
    assert got["verdict"] == "overclaimed" and got["problem_count"] == 1, got
    assert got["overclaimed"][0]["claim_id"] == "C1", got
    assert got["overclaimed"][0]["codes"] == ["overclaim"], got["overclaimed"][0]
    assert got["criterion_source"] == "claimanatomy.overclaim", got


def test_the_strength_criterion_has_exactly_one_implementation():
    """判据（不许两份实现）：这条机械半转发 `claimanatomy`，不另立词表。

    怎么判：同一个"超证据"的文本，`claimanatomy` 的合规构造器必须拒收它，
    而 `claim_strength_findings` 必须判出它 —— 两件事指向同一份判据。
    """
    from agentflow.tools.doc_tools import compose_claim

    text = "我们证明了该涨落服从中心极限定理"
    with pytest.raises(ValueError, match="overclaim"):
        compose_claim(text=text, citations=["lit:0001"], evidence_kind="cross_check",
                      section="§1")
    assert FC.claim_strength_findings(
        [{"claim_id": "C1", "text": text, "evidence_kind": "cross_check"}]
    )["verdict"] == "overclaimed"


def test_claim_strength_accepts_strong_words_only_with_proof_level():
    """负控（不许误报）：同样的措辞挂 proof 级证据时不算强于证据。"""
    got = FC.claim_strength_findings([
        {"claim_id": "C2", "text": "该恒等式已被形式化证明", "evidence_kind": "proof"},
    ])
    assert got["verdict"] == "within_evidence" and got["overclaimed"] == [], got


def test_claim_strength_separates_cannot_judge_from_within_evidence():
    """负控（三态）：没有证据等级的断言记 `unjudgeable`，不许折成"没问题"。"""
    got = FC.claim_strength_findings([{"claim_id": "C3", "text": "随便一句话"}])
    assert got["verdict"] == "unjudgeable", got
    assert got["missing_evidence"] and got["overclaimed"] == [], got
    # 两栏分开报：判不了的条数与超证据的条数不能混成一个数字
    assert got["total"] == 1, got


def test_claim_strength_is_quiet_on_a_clean_ledger():
    """正控（干净的台账）：温和措辞 + cross_check ⇒ within_evidence。"""
    got = FC.claim_strength_findings([
        {"claim_id": "C4", "text": "数值上与公式一致（不构成证明）", "evidence_kind": "cross_check"},
        {"claim_id": "C5", "text": "反例搜索未找到反例", "evidence_kind": "cross_check"},
    ])
    assert got["verdict"] == "within_evidence" and got["problem_count"] == 0, got


# ============================================================ ⑦ 语义半（判据本体）


def test_the_new_criterion_is_registered_with_negative_controls():
    """判据（准入）：新判据在表里，且带 ≥2 条负控（没有负控的判据不许进表）。

    负控不是"格式错"：两条都是真实会出现的坏形态 —— 一条把 cross_check 写成"证明"，
    一条把"数值一致"写成"对一切维数必然成立"。
    """
    assert "claims.conclusion_strength" in JG.CRITERIA, sorted(JG.CRITERIA)
    crit = JG.CRITERIA["claims.conclusion_strength"]
    assert crit.faculty == "能思辨", crit.faculty
    assert crit.pass_verdicts == ("within_evidence",), crit.pass_verdicts
    assert "{artifact}" in crit.template, "模板里没有 {artifact} ⇒ 判据看不到被审文本"
    negatives = JG.NEGATIVE_CONTROLS.get(crit.id, ())
    assert len(negatives) >= 2, negatives
    assert not JG.registry_problems(), JG.registry_problems()


def test_the_judge_is_not_wired_without_a_seam(tmp_path: pathlib.Path):
    """负控（三态）：没有接线时这条判据必须落 `judge_not_wired`（不是"通过"）。"""
    got = JG.judge("claims.conclusion_strength", "| 断言 | 证据等级 |\n|---|---|\n| A | cross_check |",
                   seam=None)
    assert got.problem == "judge_not_wired" and got.ok is False, got.to_dict()


# ============================================================ ⑦ 接进交付闸门


class _Fixed:
    """替身模型：从提示词里读出这条判据允许的判定，返回第一个（各判据的通过档）。

    为什么不写死一个判定：`deliver.gate` 默认跑全部判据，而每条判据的词表不同 ——
    写死 `within_evidence` 会让另外五条落 `judge_bad_verdict`（那正是第一版测试的样子，
    它把"替身不会答题"读成了"判据有问题"）。
    """

    spec = type("S", (), {"model": "fake"})()

    _first_verdict = re.compile(r"^\s*([a-z_]{3,}) = ", re.M)

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """按提示词里列出的判定词表作答（取第一个 = 该判据的通过档）。"""
        found = self._first_verdict.findall(prompt or "")
        verdict = found[0] if found else "within_evidence"
        return type("R", (), {"ok": True, "tokens_in": 3, "tokens_out": 3,
                              "error_detail": "", "error_kind": "",
                              "text": '{"verdict": "%s", "why": "替身：按词表首项作答",'
                                      ' "findings": []}' % verdict})()


def _store_with_claim(store: Store, text: str, level: str) -> Store:
    """往库里放一条带断言的文件行。

    走直接落库而不是 `doc_tools.compose_claim`：合规构造器会拒收"超证据"的断言
    （`inconsistent_status`），而闸门要拦的正是"从别处写进来的那一行"。
    这也顺带证明了这条判据不是摆设：它挡的是已经在库里的东西。
    """
    claim = {"claim_id": "C1", "text": text, "evidence_kind": level,
             "citations": ["lit:0001"], "section": "§1",
             "disclaimer": "" if level == "proof" else "数值交叉验证，不构成证明"}
    with store.tx("documents", "counters", actor="test") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0000", kind="paper", title="P2 断言台账", status="draft",
            claims=[claim], markdown_path=None, created_at=S.now_iso(),
            created_by="test").to_dict())
    return store


def test_the_gate_reports_claim_strength_as_a_mechanical_finding(store: Store):
    """判据（接线）：闸门的机械半会逐条查"结论强于证据"，并把它落成工作项。"""
    _store_with_claim(store, "我们证明了该涨落服从中心极限定理", "cross_check")
    seam = LlmSeam(role="H", session_root=store.root, gateway=_Fixed(), price=(0.0, 0.0), sid="t")
    res = gate("paper-claims", "# 稿子\n\n一句。\n", session_root=store.root, seam=seam,
               criteria=["claims.conclusion_strength"], store=store)
    kinds = [m["kind"] for m in res.mechanical]
    assert "claim_strength" in kinds, res.to_dict()
    assert any(w.source == "mechanical:claim_strength" for w in res.work_items), (
        [w.to_dict() for w in res.work_items])


def test_the_gate_picks_up_the_new_criterion_by_default(store: Store):
    """判据（默认集）：不给 `--criterion` 时新判据也在里面（否则它会静默地不被跑）。"""
    seam = LlmSeam(role="H", session_root=store.root, gateway=_Fixed(), price=(0.0, 0.0), sid="t")
    res = gate("paper-default", "# 稿子\n\n一句。\n", session_root=store.root, seam=seam,
               store=store)
    judged = [c["criterion"] for c in res.criteria]
    assert "claims.conclusion_strength" in judged, judged
    assert not res.unknown_criteria, res.unknown_criteria
