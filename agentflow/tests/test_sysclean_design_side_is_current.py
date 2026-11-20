# -*- coding: utf-8 -*-
"""SYSCLEAN 路（系统设计侧）：设计文档写的机制与实现一致，废案不留活落点。

## 这份判据为什么存在

设计侧的三份「权威/规范」文档里，有一批条款已被更晚的裁定推翻，却还以现行口气留在正文：

- `DESIGN-ROLES.md` §1.1「E 计算类方法永远拿不到 `proof`」—— 2026-10-23 穷举证明链之后
  不成立（`schema.Experiment.validate` 的现口径是「穷尽四件齐备才许」，不是「永远不许」）；
- 同文 §2.1 E 的接口里还有 `check_formal` —— 2026-10-22 起形式化归 L，E 那一支已摘掉；
- 同文 §2.2 写 `C`/`D`/`F` 子目标「只记 `outcome="no_change"`、本框架尚未接线自动推理」——
  2026-10-26 业主逐字「没有默认开，这个就是 F 的工作方式」之后，F 自己推理，缺缝落 `dead_end`；
- 同文 §2.4 写「H 的工具面全部 `none`/`read`」—— 2026-11-01 只读定义之后，H 有落库代理与
  通用写工具（`write_local`），旧的全称量化不再成立；
- `DEVELOPMENT-SPEC.md` §5.4 标题与表格仍写「计算类拿不到 `proof`」—— 同一条被推翻的裁定；
  它的 §2/§4.1 分层与包布局漏了 `agent_l/`、`specs/`、`agentspec.py` —— 那是 M3 起权限面的真身；
- `docs/SYSTEM-COMPONENTS.md`（生成物）点名的 `AGENT_CLASSES` 已不在 `host.py` 里，依赖表也从
  「四列」改成「三列必填、路径号不进稿」。

这些地方的共同形态是：判据不红。文档不会被 import，符号名写在散文里没人核；
所以这里把每一条做成两向判据 —— 现盘必须干净，喂回旧措辞必须红（反真空）。

## 另一类：零调用但仍活着的公开名字

`tests/test_clean_invariant.py` 的死代码台账只收私有函数（`_name`）；公开的零引用名字
从那条判据下面漏过去。本轮删掉的四个（`identity` 的 `conflict_line` / `rowscope` 的
`OWNER_FIELDS` / `interactions` 的 `ADJUDICATION_POLICY_CODES` / `store` 的
`direct_write_backstop`）就是这一类。判据两向：真身上不许再出现，喂一个"又长回来了"的
假模块必须红。
"""
from __future__ import annotations

import pathlib
import re
import types

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
DESIGN_ROLES = REPO / "DESIGN-ROLES.md"
DEV_SPEC = DOCS / "DEVELOPMENT-SPEC.md"
COMPONENTS = DOCS / "SYSTEM-COMPONENTS.md"
GENERATOR = REPO / "tools" / "write_system_docs.py"


def _text(path: pathlib.Path) -> str:
    assert path.is_file(), f"{path} 不在盘上 ⇒ 判据的对象没了"
    got = path.read_text(encoding="utf-8")
    assert len(got) > 1000, f"{path} 只读到 {len(got)} 字节 ⇒ 读错了文件"
    return got


# ============================================================ DESIGN-ROLES.md

def design_roles_problems(text: str) -> list[str]:
    """`DESIGN-ROLES.md` 里已被裁定推翻、却还以现行口气写着的条款（空 = 干净）。"""
    out: list[str] = []
    if re.search(r"计算类方法\s*\*\*永远\*\*拿不到", text):
        out.append("§1.1 还写着「计算类方法永远拿不到 proof」—— 2026-10-23 穷举证明链已推翻")
    if re.search(r'if self\.method != "formal" and self\.evidence_kind == "proof":\s*\n\s*raise ValueError',
                 text):
        out.append("§1.1 的伪代码还是「计算类 + proof ⇒ 无条件 raise」—— 现口径是先过穷尽四件")
    if "check_formal(claim, *, script_path)" in text:
        out.append("§2.1 还把 check_formal 列在 E 的接口里 —— 2026-10-22 起形式化归 L")
    if re.search(r'记录一条\s*`outcome="no_change"`\s*的轮次', text):
        out.append('§2.2 还写 C/D/F 子目标「只记 outcome="no_change"、尚未接线自动推理」'
                   "—— 2026-10-26 起推理就是 F 的工作方式")
    if "本框架尚未接线自动推理" in text and "2026-10-26" not in text:
        out.append("§2.2 还以现行口气写「本框架尚未接线自动推理」，且没有 2026-10-26 的更正")
    if re.search(r"H 的工具面全部\s*`side_effect", text):
        out.append("§2.4 还写「H 的工具面全部 none/read」—— 2026-11-01 只读定义之后不成立")
    if re.search(r"E 的\s*`formal`\s*方法在本环境无法使用", text):
        out.append("§5.3 还写「E 的 formal 方法在本环境无法使用」—— 形式化已归 L")
    if re.search(r"F 的\s*`owner\s*∈\s*\{C,D,F\}`\s*子目标不会被自动推进", text):
        out.append("§5.4 还写「F 的 C/D/F 子目标不会被自动推进」—— 2026-10-26 已推翻")
    if "close_as" not in text:
        out.append("§2.4 的 verify_fixes 签名缺 close_as（2026-11-15 撤轮数上限后的唯一终态入口）")
    # 角色包 2026-10 起是目录；把顶层 agent_<x>.py 当落点写会让读者找不到文件（明写「不再是」的墓碑合规）。
    for line in text.splitlines():
        for stem in ("agent_e.py", "agent_f.py", "agent_g.py", "agent_h.py"):
            if f"agentflow/src/agentflow/{stem}" in line and "不再是" not in line:
                out.append(f"还把顶层 {stem} 当现存活点写（角色已是 agent_<x>/ 包）")
                break
    return out


def test_design_roles_has_no_superseded_mechanism() -> None:
    """正控：`DESIGN-ROLES.md` 的机制条款与现盘一致（旧口径的清点见函数体）。"""
    problems = design_roles_problems(_text(DESIGN_ROLES))
    assert not problems, "设计文档还留着已被裁定推翻的机制：\n  " + "\n  ".join(problems)


def test_the_design_roles_scanner_sees_old_wording() -> None:
    """反真空：同一把尺子喂旧措辞必须红（否则「干净」可能只是正则没匹配）。"""
    old = (
        "### 1.1 E：计算类方法**永远**拿不到 `proof` 等级（FC-22）\n"
        'if self.method != "formal" and self.evidence_kind == "proof":\n'
        "    raise ValueError(...)\n"
        "check_formal(claim, *, script_path) -> dict\n"
        '| `C`/`D`/`F` | **记录一条 `outcome="no_change"` 的轮次**，`detail` 写明'
        '"需要 C/D/F 的推理，本框架尚未接线自动推理 ⇒ **未推进**" |\n'
        "**H 的工具面全部 `side_effect ∈ {\"none\",\"read\"}`。**\n"
        "3. **E 的 `formal` 方法在本环境无法使用**（无 Lean/Coq）\n"
        "4. **F 的 `owner ∈ {C,D,F}` 子目标不会被自动推进**\n"
        "`agentflow/src/agentflow/agent_e.py`：\n"
        "`agentflow/src/agentflow/agent_h.py`（门引擎）\n"
    )
    got = design_roles_problems(old)
    # 每条各自都要有牙：少一条就说明那条正则只会在真空里绿。
    assert len(got) >= 10, got


# ============================================================ DEVELOPMENT-SPEC.md

def dev_spec_problems(text: str) -> list[str]:
    """`DEVELOPMENT-SPEC.md` 的旧口径与分层/包布局漏项（空 = 干净）。"""
    out: list[str] = []
    if re.search(r"§5\.4[^\n]*计算类\*\*拿不到\*\*", text):
        out.append("§5.4 标题还写「计算类拿不到 proof」—— 2026-10-23 穷举证明链已推翻")
    if "计算类方法（`numeric` / `symbolic` / `exhaustive_search`）不得标 `proof`" in text:
        out.append("§5.4 正文还写「计算类方法不得标 proof」—— 穷尽四件齐备时允许")
    if "穷举" not in text.split("### [规范] §5.4", 1)[-1].split("### [规范] §5.5", 1)[0]:
        out.append("§5.4 整节没有提穷举那一档（现口径的主体）")
    if "… agent_h/ · agent_v/" in text:
        out.append("§2/§4.1 的角色包清单停在 agent_v，漏了 2026-10-22 新设的 agent_l/")
    if re.search(r"^│   ├── agent_a/ … agent_h/ · agent_v/", text, re.M):
        out.append("§4.1 的包布局树还写「agent_a/ … agent_h/ · agent_v/」，漏了 agent_l/")
    # `specs/` 与 `agentspec.py` 是 M3 起权限面的真身，包布局里必须有它们。
    if "agentspec.py" not in text:
        out.append("§4.1 的包布局没有 agentspec.py（声明类型与受控词表的真身）")
    if "| `specs/`" not in text:
        out.append("§4.1 的模块职责边界表没有 specs/ 那一行（逐角色声明的真身）")
    if "用例**现在是红的**" in text:
        out.append("§16.14 还把很久以前那批读数过期写成「现在是红的」—— 那两条用例后来已复绿")
    if "不写业务策略；不互相 import" in text:
        out.append("§4.2 还写 tools/*.py「不互相 import」—— 现盘有 5 处单向依赖（复用同一判据）")
    return out


def test_dev_spec_matches_the_current_evidence_grade_and_layout() -> None:
    """正控：规范文档的证据等级口径与分层/包布局跟得上实现。"""
    problems = dev_spec_problems(_text(DEV_SPEC))
    assert not problems, "开发规范与实现漂移：\n  " + "\n  ".join(problems)


def test_the_dev_spec_scanner_sees_old_wording() -> None:
    """反真空：旧标题 + 旧正文 + 旧包布局必须一起被读出来。"""
    old = (
        "### [规范] §5.4 纪律 4：证据等级（`proof` / `cross_check` / `heuristic`；"
        "计算类**拿不到** `proof`）\n"
        "**计算类方法（`numeric` / `symbolic` / `exhaustive_search`）不得标 `proof`**；\n"
        "│   ├── agent_a/ … agent_h/ · agent_v/   角色包\n"
        "那几条用例**现在是红的**，红的理由是**读数过期**\n"
        "| `tools/*.py` | 原子动作 | 不写业务策略；不互相 import |\n"
    )
    got = dev_spec_problems(old)
    assert len(got) >= 6, got


# ============================================================ DESIGN-CONDUCTOR / DESIGN-TOOLS

DESIGN_CONDUCTOR = REPO / "DESIGN-CONDUCTOR.md"
DESIGN_TOOLS = REPO / "DESIGN-TOOLS.md"
DESIGN_INTERACTIONS = REPO / "DESIGN-INTERACTIONS.md"


def interactions_design_problems(text: str) -> list[str]:
    """`DESIGN-INTERACTIONS.md` 里点名的已不存在文件 / 过期缺省值（空 = 干净）。"""
    out: list[str] = []
    for line in text.splitlines():
        if "agent_c.py" in line and not any(m in line for m in ("不存在", "不再", "已拆", "历史")):
            out.append("把顶层 agent_c.py 当现存活点写 —— 角色已拆成 agent_c/ 包")
    if re.search(r"`max_gap_requests_per_run`\s*（默认 3）", text):
        out.append("I3 还写 max_gap_requests_per_run 默认 3 —— 现读 30（`interactions.DEFAULTS`）")
    if "agent_c/" not in text:
        out.append("读不到指向 agent_c/ 包的现行落点 ⇒ 读者会照着旧路径去找")
    return out


def test_interactions_design_points_at_the_current_package() -> None:
    """正控：`DESIGN-INTERACTIONS.md` 的落点与上限读数跟得上实现。"""
    problems = interactions_design_problems(_text(DESIGN_INTERACTIONS))
    assert not problems, "设计文档与实现漂移：\n  " + "\n  ".join(problems)


def test_the_interactions_scanner_sees_old_wording() -> None:
    """反真空：旧文件路径 + 旧默认值 / 缺新落点都必须被读出来。"""
    old = ("实测这些方法都在 `agentflow/src/agentflow/agent_c.py`\n"
           "- 最多提交 `max_gap_requests_per_run`（默认 3）\n")
    assert len(interactions_design_problems(old)) >= 3, interactions_design_problems(old)


def conductor_problems(text: str) -> list[str]:
    """`DESIGN-CONDUCTOR.md` 里停在被更晚裁定推翻的形态（空 = 干净）。"""
    out: list[str] = []
    if "26 条召唤边" in text:
        out.append("§3.1 还写「实测 26 条召唤边」—— 现读 32 条（B07/B08）")
    if re.search(r"(?m)^M → A B C D E F G H\s*$", text):
        out.append("§3.1 的 M 出边还含 F（现表不含 F / V / L）")
    if re.search(r"(?m)^H → G\b", text):
        out.append("§3.1 还写着 H → G（2026-11-11 起 H 的出边是 A / E）")
    if re.search(r"(?m)^F → A B C D E\s*#", text):
        out.append("§3.1 的 F 出边还是 A B C D E（2026-11-07 删 F→B、加 F→D）")
    if "V →" not in text or "L → C" not in text:
        out.append("§3.1 的边表漏了 V / L 两行")
    if re.search(r"`max_concurrency`\s*（默认 4）", text):
        out.append("§1.3 还写 max_concurrency 默认 4 —— 现默认 None = 不设限")
    if "默认 3：`M(1) → A(2) → B(3)`" in text:
        out.append("§1.2 还写深度默认 3 —— 2026-11-05 起 max_chain_depth=6")
    if "`M` 是**确定性的策略执行者**" in text:
        out.append("§8 问题 1 还写「M 是确定性的策略执行者、不做 LLM 推理」—— M 与其余角色"
                   "同一个 agent_loop")
    return out


def tools_problems(text: str) -> list[str]:
    """`DESIGN-TOOLS.md` 里点名已撤模块/工具的地方（空 = 干净）。"""
    out: list[str] = []
    # 只咬「当现存事实写」的那一类：明写「已删 / 不存在 / 撤除」的历史说明是合规的墓碑。
    marks = ("不存在", "已删", "撤除", "已撤", "历史")
    for line in text.splitlines():
        if "conjecture_tools.py" in line and not any(m in line for m in marks):
            out.append("把 conjecture_tools.py 当现存模块写（该模块 2026-11-13 撤除）")
        if "install_d_tools" in line and not any(m in line for m in marks):
            out.append("把 install_d_tools 当现存入口写（agent_d.py 已拆成 agent_d/ 包）")
        if "conjecture.register_conjecture" in line and not any(m in line for m in marks):
            out.append("把 conjecture.register_conjecture 当现存工具写（该工具已撤除）")
    if re.search(r"正式版共 \*\*16\*\* 张表", text):
        out.append("§2 还写「正式版共 16 张表」—— 表数以当次现算为准（现 17）")
    return out


def test_conductor_design_matches_the_current_edges_and_limits() -> None:
    """正控：`DESIGN-CONDUCTOR.md` 的边表 / 上限 / M 的定位跟得上当前实现。"""
    problems = conductor_problems(_text(DESIGN_CONDUCTOR))
    assert not problems, "设计文档与实现漂移：\n  " + "\n  ".join(problems)


def test_tools_design_does_not_name_retired_tools() -> None:
    """正控：`DESIGN-TOOLS.md` 不把已撤模块 / 工具当现存事实写。"""
    problems = tools_problems(_text(DESIGN_TOOLS))
    assert not problems, "设计文档与实现漂移：\n  " + "\n  ".join(problems)


def test_the_conductor_and_tools_scanners_see_old_wording() -> None:
    """反真空：两份设计文档的旧形态必须被读出来。"""
    old_conductor = (
        "实测 26 条召唤边\n"
        "M → A B C D E F G H\n"
        "H → G            # 审校发现问题\n"
        "F → A B C D E    # 攻坚需要一切\n"
        "`max_concurrency`（默认 4）\n"
        "深度有限（默认 3：`M(1) → A(2) → B(3)` 已到底）\n"
        "`M` 是**确定性的策略执行者**（不做 LLM 推理）\n"
    )
    assert len(conductor_problems(old_conductor)) >= 6, conductor_problems(old_conductor)
    old_tools = (
        "| `agentflow/src/agentflow/tools/conjecture_tools.py` | "
        "`conjecture.register_conjecture`（由 `agent_d.py::install_d_tools` 另挂） | 1 |\n"
        "（实测：正式版共 **16** 张表）\n"
    )
    assert len(tools_problems(old_tools)) >= 3, tools_problems(old_tools)


# ============================================================ SYSTEM-COMPONENTS.md

def components_problems(text: str, generator_text: str) -> list[str]:
    """生成物与生成器里点名的死符号 / 旧机制（空 = 干净）。

    生成物是 `tools/write_system_docs.py` 渲染的：两边一起核，只改产物会在下次
    重生成时被覆盖（`tests/test_system_docs_are_generated.py` 已按这个理由钉过一次）。
    """
    out: list[str] = []
    for label, body in (("SYSTEM-COMPONENTS.md", text), ("write_system_docs.py", generator_text)):
        if "AGENT_CLASSES" in body:
            out.append(f"{label} 还点名 AGENT_CLASSES —— host.py 里已经没有这个符号")
        if "四列依赖表" in body:
            out.append(f"{label} 还把 depsection 说成「四列依赖表」—— 2026-11-13 起三列必填、"
                       "路径号是第四列且不进稿")
    if "四列依赖表" in generator_text and "三列" not in generator_text:
        out.append("生成器改完「四列」却没有说「三列」——半改比不改更难发现")
    return out


def test_the_components_doc_and_its_generator_name_live_symbols() -> None:
    """正控：生成物与生成器不点名死符号、不写旧机制。"""
    problems = components_problems(_text(COMPONENTS), _text(GENERATOR))
    assert not problems, "组件文档/生成器与实现漂移：\n  " + "\n  ".join(problems)


def test_the_components_scanner_sees_the_dead_symbol() -> None:
    """反真空：把死符号 / 旧机制塞回生成器 ⇒ 同一把尺子必须红。"""
    old = ("build_role_registry 按角色裁面；AGENT_CLASSES 把 specs 里 class_path "
           "指向的实现类实例化。\n"
           "manuscripts（write 与 row_of 与 read_rows，带解析缓存）、depsection（四列依赖表解析）")
    got = components_problems(old, old)
    assert len(got) >= 4, got


# ============================================================ 零调用公开名字

#: 本轮删掉的零调用公开名字：模块名 -> (被删的名字, 该模块仍在用的邻居符号)。
REMOVED_PUBLIC: dict[str, tuple[str, str]] = {
    "agentflow.identity": ("conflict_line", "resolve_identity"),
    "agentflow.rowscope": ("OWNER_FIELDS", "write_refusal"),
    "agentflow.interactions": ("ADJUDICATION_POLICY_CODES", "adjudicate_contradiction"),
    "agentflow.store": ("direct_write_backstop", "direct_write_route"),
    # 猜想疑问句判据换实现（按词 → 按形态）：旧词表零调用，替身必须还在。
    "agentflow.schema": ("CONJECTURE_QUESTION_WORDS", "CONJECTURE_QUESTION_MARKS"),
}


def dead_public_problems(modules: dict[str, object]) -> list[str]:
    """真身上还有这些零调用名字 ⇒ 它们又长回来了（或本轮没删干净）。"""
    out: list[str] = []
    for mod_name, (gone, live) in REMOVED_PUBLIC.items():
        mod = modules.get(mod_name)
        if mod is None:
            out.append(f"{mod_name} 读不到 ⇒ 判据失去对象")
            continue
        if hasattr(mod, gone):
            out.append(f"{mod_name}.{gone} 还在 —— 零调用公开名字不该留在真身上")
        if not hasattr(mod, live):
            out.append(f"{mod_name}.{live} 不见了 —— 这条判据的'邻居仍在'反真空失效")
    return out


def test_no_zero_call_public_name_is_left_on_the_real_modules() -> None:
    """正控：四个零调用公开名字已从真身删掉，且同模块的活符号仍在（反真空）。"""
    import importlib

    modules = {name: importlib.import_module(name) for name in REMOVED_PUBLIC}
    problems = dead_public_problems(modules)
    assert not problems, "零调用公开名字还在（或邻居符号被误删）：\n  " + "\n  ".join(problems)


def test_the_dead_public_scanner_sees_a_resurrected_name() -> None:
    """反真空：喂一个"又长回来了"的假模块 ⇒ 必须点名它。"""
    fake = types.SimpleNamespace()
    for mod_name, (gone, live) in REMOVED_PUBLIC.items():
        setattr(fake, mod_name, types.SimpleNamespace(**{gone: 1, live: 1}))
    got = dead_public_problems({name: getattr(fake, name) for name in REMOVED_PUBLIC})
    assert len(got) == len(REMOVED_PUBLIC), got
    assert all("还在" in one for one in got), got


def test_the_policy_codes_match_their_producer() -> None:
    """`interactions` 的注释里那份「D 会产出的策略码」必须与生产者一致。

    改前 `ADJUDICATION_POLICY_CODES` 写 `quota_exhausted`，而 `agent_d/adjudicate.py`
    产出的是 `budget_exhausted`（同一份文件里 `ADJUDICATION_CODES` 也写对了）——
    「本词表里没有它」那句解释因此指着两个不同的码。常量本身零调用，已删；
    留下的是生产者那一侧核对。
    """
    src = (REPO / "src" / "agentflow" / "interactions.py").read_text(encoding="utf-8")
    d_src = (REPO / "src" / "agentflow" / "agent_d" / "adjudicate.py").read_text(encoding="utf-8")
    for code in ("weak_only_signal", "inflight_limit", "budget_exhausted"):
        assert code in src, f"interactions 的说明里没有生产者真实产出的 {code}"
        assert code in d_src, f"D 的裁决实现里没有 {code}（演示这条判据的对象没了）"
    assert "quota_exhausted" not in src, "interactions 还写着没有任何生产者的 quota_exhausted"
