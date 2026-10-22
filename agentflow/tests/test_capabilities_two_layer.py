"""`G-19`：两层声明的对账面不许静默缩小。

实测背景（`D-9` 更正；当次观测 2026-09-26 19:0x）：`declaration_divergences()` 返回的条目全部是"没有比对"（`two_layer_name_unmatched`：
两层名字对不上 ⇒ 三态里的 unknown），warning 0、error 0。那个条数刻意不写死 —— 手抄的数字会过期（`R4-AN-2` 实测到它从 32 漂到 33），等式不会：
它等于 `len(two_layer_reconciliation()['unmatched'])`，也等于 `_KNOWN_UNMATCHED_ACTIONS` 的条数，
而 `assert_capabilities()` 第 [7] 条的两条断言（`new_unmatched` 与 `stale` 都为空）钉着这个相等。
要读当次数就跑 `python -c "from agentflow import capabilities as C; print(C.two_layer_reconciliation())"`。（本文件原来写"33
条 + 1 条 warning"，那条 warning `two_layer_external_imprecise` 在 B3 收官后已经不存在了 —— 与 `capabilities.py` 里同一处注释一起更正。）

而"第 [7] 条只过滤 `error`"那一版确实曾经是恒真的：门看起来接上了，实际上绝大多数动作根本没有被两层比对过。今天第 [7] 条钉的是"没比对"登记表的双向相等、第 [7b]
条钉的是"三格互斥且穷尽"这个结构本身（`R4-AN-3` 之后第 [7] 条还真的读 warning），所以"静默少比对"有判据看着了。

所以这一节钉的不是"再严一点"，而是"不许静默地少比对"：新出现的"没比对"必须显式登记，登记表里已经对上的必须删掉。"""

from __future__ import annotations

import copy
import importlib
import re
from pathlib import Path

import pytest

from agentflow import capabilities as C

#: `D-8`：角色 -> (模块名, 类名)；用来断言动作表里的符号名真的存在。
#:
#: 审计 D-7：这张表原来只有 A–H 八个角色，而能力表有九个（V 的 `verify_proof` /
#: `list_verifications` / `read_proof` 三条动作因此从来没被这条判据看过：实测覆盖 59/62）。
#: 现在补上 V，并由 `test_every_handler_name_exists_as_a_class_method` 亲自断言
#: "覆盖数 == 对账面的动作总数"—— 少一个角色时它会红，而不是悄悄少看三条。
ROLE_MODULE: dict[str, tuple[str, str]] = {
    "A": ("agentflow.agent_a", "AgentA"),
    "B": ("agentflow.agent_b", "AgentB"),
    "C": ("agentflow.agent_c", "AgentC"),
    "D": ("agentflow.agent_d", "AgentD"),
    "E": ("agentflow.agent_e", "AgentE"),
    "F": ("agentflow.agent_f", "AgentF"),
    "G": ("agentflow.agent_g", "AgentG"),
    "H": ("agentflow.agent_h", "AgentH"),
    "V": ("agentflow.agent_v", "AgentV"),
}
_STALE_REF = re.compile(r"agent_[a-h]\.py:\d+")
_CAPS = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "capabilities.py"


def test_the_action_table_no_longer_uses_file_line_references() -> None:
    """`D-8` 正控：动作表注释里不许再有 `文件:行号`（历史说明用占位写法 `<模块>.py:<行>`）。

    改前这里有一整片 `agent_a.py:306 run_once / agent_a.py:484 run`，实测全部过期
    （`AgentA.run_once` 实际在 367、`AgentA.run` 在 553）。行号易失，符号名不会。
    """
    text = _CAPS.read_text(encoding="utf-8")
    i = text.index("动作表")
    stale = sorted(set(_STALE_REF.findall(text[i: i + 3000])))
    assert stale == [], f"动作表里还有过期的 `文件:行号`：{stale}"


def test_every_handler_name_exists_as_a_class_method() -> None:
    """`D-8` 正控（核心）：每个动作的 `handler_name` 必须真的是那个类的方法。

    覆盖数不写死（手抄的数字会过期）：它必须等于 `two_layer_reconciliation()['total']` ——
    也就是对账面里的动作总数。审计 D-7 实测这里是 59/62：`ROLE_MODULE` 少了 V，
    而 `if role not in ROLE_MODULE: continue` 把少掉的三条静默跳过了。
    """
    missing: dict[str, list[str]] = {}
    checked = 0
    for role, specs in C.CAPABILITIES.items():
        if role not in ROLE_MODULE:
            continue
        mod_name, cls_name = ROLE_MODULE[role]
        cls = getattr(importlib.import_module(mod_name), cls_name, None)
        assert cls is not None, f"{cls_name} 不在 {mod_name}"
        for spec in specs:
            name = getattr(spec, "handler_name", None)
            checked += 1
            if name and not hasattr(cls, str(name)):
                missing.setdefault(role, []).append(str(name))
    assert checked > 0, "一个动作都没查到（夹具/表结构变了）"
    assert missing == {}, f"这些 handler_name 在对应类里找不到：{missing}"
    # 反真空（审计 D-7 的牙）：覆盖数必须等于对账面的动作总数 —— 少登记一个角色就会红。
    total = C.two_layer_reconciliation()["total"]
    roles_with_actions = sorted(r for r, specs in C.CAPABILITIES.items() if specs)
    assert checked == total, (
        f"只核了 {checked} / {total} 个动作 —— `ROLE_MODULE` 少登记了角色："
        f"{sorted(set(roles_with_actions) - set(ROLE_MODULE))}。"
        "少掉的那几个角色的动作从来没被这条判据看过（审计 D-7 实测 59/62）"
    )


def test_a_wrong_handler_name_is_caught() -> None:
    """`D-8` 负控：把某个 `handler_name` 改错 ⇒ 上面那条判据必须变红（用深拷贝，不动真表）。"""
    role = "A"
    specs = copy.deepcopy(list(C.CAPABILITIES[role]))
    assert specs, "前提：角色 A 有动作"
    bad = "definitely_not_a_method"
    cls = getattr(importlib.import_module(ROLE_MODULE[role][0]), ROLE_MODULE[role][1])
    assert not hasattr(cls, bad), "夹具前提：这个假名字不该存在"
    renamed = [type(s)(**{**s.__dict__, "handler_name": bad}) for s in specs]
    assert not all(hasattr(cls, str(s.handler_name)) for s in renamed), (
        "把 handler_name 改错之后判据仍然全绿 ⇒ 这条判据是恒真的"
    )


def test_the_registry_matches_todays_unmatched_set_exactly() -> None:
    """登记表必须与实测的"没比对"集合逐条相同 —— 两个方向都要查。"""
    unmatched = {d.where for d in C.declaration_divergences() if d.code == "two_layer_name_unmatched"}
    assert unmatched == set(C._KNOWN_UNMATCHED_ACTIONS), {
        "新增（必须先登记，否则导入失败）": sorted(unmatched - C._KNOWN_UNMATCHED_ACTIONS),
        "已对上（必须删登记，否则表会烂成噪音）": sorted(C._KNOWN_UNMATCHED_ACTIONS - unmatched),
    }


def test_an_empty_registry_makes_the_import_assertion_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """负控一：登记表被清空（等价于"对账面缩小"）⇒ 断言必须炸。"""
    monkeypatch.setattr(C, "_KNOWN_UNMATCHED_ACTIONS", frozenset())
    with pytest.raises(AssertionError, match="对账面在缩小"):
        C.assert_capabilities()


def test_a_phantom_registry_entry_makes_the_import_assertion_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控二：登记表里多一条对不上的幽灵 ⇒ 断言必须炸（防登记表烂成噪音）。"""
    monkeypatch.setattr(C, "_KNOWN_UNMATCHED_ACTIONS", C._KNOWN_UNMATCHED_ACTIONS | {"Z.ghost"})
    with pytest.raises(AssertionError, match="登记表会烂成噪音"):
        C.assert_capabilities()


def test_there_are_no_error_level_divergences_today() -> None:
    """把"今天 error 级不一致为 0"写成断言：它是事实，不是巧合。

    作用：哪天有人把能力层声明改小（真实的不一致），这条会在测试里先红一次，
    而不是只在 `import agentflow.capabilities` 时炸 —— 让人一眼看出是"新出现的不一致"。
    """
    hard = [d for d in C.declaration_divergences() if d.level == "error"]
    assert hard == [], [(d.where, d.message[:80]) for d in hard]


def test_the_cross_check_actually_compares_at_least_one_action() -> None:
    """对账面的下限：对账必须是一个分区，且至少有一个动作真的被两层比对过。

    没有这条，一个"匹配全线失效"的实现（所有动作都进 unmatched）也会因为上面那条恒真的 error 断言而看起来正常 —— 这正是 `G-19` 的形态。

    D-3 裁决把它加固成分区判据（`capabilities.two_layer_reconciliation`）：动作表里的每一个动作都必须恰好落进 `compared` / `unmatched`
    / `ambiguous` 三格之一 —— 也就是"三格互斥且穷尽"，判据读的是 `recon["total"]`，不写死动作条数（`R4-AN-2` 的形态：手抄的数字会过期，等式不会）。
    为什么不能只钉 `compared > 0`：钉死任何一个具体的数都会变成一条"任何正当的工具增减都让它红"的断言（`DEVELOPMENT.md` §6 的 P15 反面）。分区结构自我维护 ——
    哪一格变了都必然在 `len(...)` 之和或互斥性上露出来。"""
    recon = C.two_layer_reconciliation()
    compared, unmatched, ambiguous = recon["compared"], recon["unmatched"], recon["ambiguous"]
    assert len(compared) + len(unmatched) + len(ambiguous) == recon["total"], recon
    assert not (set(x for x, _ in compared) & set(unmatched)) and not (
        set(x for x, _ in compared) & set(ambiguous)) and not (set(unmatched) & set(ambiguous)), recon
    assert compared, "两层比对一条都没做成 ⇒ 对账面是空的，而门会显示为通过"
    # `ambiguous` 今天实测为 0；这一格不在 `_KNOWN_UNMATCHED_ACTIONS` 里，
    # 所以它必须由分区断言亲自看着（见下面那条负控）。
    assert ambiguous == [], ambiguous


def test_the_partition_assertion_catches_an_ambiguous_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：把某个动作弄成 `ambiguous` ⇒ 分区断言必须红（它原来没有任何闸门）。

    造法：让 `_candidates` 对 `H.verify_fixes` 返回两个候选。为什么打桩的是
    `_candidates` 而不是往工具表里塞一个同名工具：真实工具表是按名字索引的
    dict（`_tool_side_effects()` 的返回类型），同名键会互相覆盖，塞不出"两个
    同名工具"。而 `_candidates` 正是"能不能唯一对上"这条判据的唯一落点 ——
    打桩它确定的正是被测命题本身："候选从 1 个变 2 个时，分区断言会不会红"。

    为什么这条负控必须有：`_KNOWN_UNMATCHED_ACTIONS` 只管 `unmatched`，
    `ambiguous` 那一格今天恰好是 0、且不在任何登记表里 ⇒ 它是一条真的
    "对账面可以静默缩小"的缝（`G-19` 的同族形态）。
    """
    real = C._candidates

    def two_candidates(spec: C.ActionSpec, tools: object) -> list[str]:
        if (spec.role, spec.action) == ("H", "verify_fixes"):
            return ["review.verify_fixes", "verify.verify_fixes"]
        return real(spec, tools)  # type: ignore[arg-type]

    monkeypatch.setattr(C, "_candidates", two_candidates)
    recon = C.two_layer_reconciliation()
    assert recon["ambiguous"] == ["H.verify_fixes"], recon
    with pytest.raises(AssertionError, match="歧义"):
        C.assert_capabilities()


def test_the_partition_assertion_catches_an_empty_compared_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：对账面上一个动作都没比对上 ⇒ 分区断言必须红。

    造法：两步打桩，逼出"匹配全线失效"这一种失败。第一步把 `_candidates` 打桩成"一个都匹配不上" ⇒ 每个动作都掉进 `unmatched`（`compared` 空、`ambiguous` 空）。
    第二步把 `_KNOWN_UNMATCHED_ACTIONS` 打桩成"全部动作" ⇒ 让第 [7] 条那两条登记表断言（新增未登记 / 登记表烂成噪音）在这条负控下恰好都不触发，于是唯一会红的就是第 [7b]
    条的分区断言。

    为什么必须做第二步：伪造一张能力表很容易在第 [1]/[2]/[6] 条先炸，于是"负控命中了别的断言"，变成假证明（我第一版就是这样，报错落在第 [2] 条上）。这里的打桩让 [1]–[6]
    与本条要测的命题之外的一切都保持真实，被改变的只有"匹配"这件事本身 —— 而"匹配全线失效"正是这条负控要测的（`G-19`：所有动作都进 unmatched，门却看起来正常）。"""
    monkeypatch.setattr(C, "_candidates", lambda spec, tools: [])
    monkeypatch.setattr(C, "_KNOWN_UNMATCHED_ACTIONS",
                        frozenset(f"{r}.{s.action}" for r, specs in C.CAPABILITIES.items()
                                  for s in specs))
    recon = C.two_layer_reconciliation()
    assert recon["compared"] == [] and recon["ambiguous"] == [], recon
    assert len(recon["unmatched"]) == recon["total"] and recon["total"] > 0, recon
    with pytest.raises(AssertionError, match="对账面是空的"):
        C.assert_capabilities()


#: `N 个动作` 这类手抄读数（`R4-AN-2` 的形态）。
_HAND_COPIED_COUNT_RE = re.compile(r"(\d+)\s*个动作")
#: 明示"这一处是历史观测"的记号；带它的行豁免（当次观测允许留痕）。
_HISTORICAL_MARKERS = ("S1", "S2", "当次", "当时", "历史", "原写", "原值", "旧版", "改前", "观测")


def test_the_text_does_not_hand_copy_the_action_count() -> None:
    """`R4-AN-2` 同族（`F4` 追加的判据）：本文件的文字里不许手抄"动作总数"。

    为什么值得一条判据：这个缺陷的形态不是"某处数字写错一次"，而是同一条不变量
    随着能力表增减反复漂移 —— `F4` 实测它从 32 漂到 33，本文件当时写着 48 而实测是 49。
    所以处置与 `capabilities.py` 同一口径：数字从真实产出里取
    （`C.two_layer_reconciliation()["total"]`），文字里只写那个等式，不抄数。
    带历史记号的行（`当次`/`当时`/`观测`/`原写`…）豁免：当次观测允许留痕，
    但它必须一眼看得出是历史读数，而不是当前值。
    """
    text = Path(__file__).read_text(encoding="utf-8")
    bad: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(mark in line for mark in _HISTORICAL_MARKERS):
            continue
        if _HAND_COPIED_COUNT_RE.search(line):
            bad.append(f":{i} {line.strip()[:90]}")
    assert not bad, (
        "这些地方手抄了动作条数（手抄的数字会过期，等式不会）："
        + "；".join(bad)
        + "。请改成从 `C.two_layer_reconciliation()['total']` 取，"
        "或写成『与能力表实测读数一致』这种可复跑的措辞"
    )


def test_no_declared_id_param_caps_below_the_current_id_width():
    """声明面里不许有比当前编号宽度还短的上界（2026-10-14 真机读数）。

    真机上一次就现形：`V.verify_proof` / `V.read_proof` 的 `statement_id` 当时写着
    `minLength=4, maxLength=4` —— 而业主 2026-10-14 已把编号宽度改成六位
    （`schema.ID_DIGITS`）。后果是一条正当的调用被拒：
    `V.verify_proof 的参数不合法：statement_id. 长度最多 4`，
    而 B 的秘书据此判「重试不会成功」，一次真跑的复核链因此白等一轮。

    判据用唯一那处宽度判（`schema.ID_DIGITS`），所以下一次改宽度时这一条会自己跟上：
    任何 `*_id` 参数声明的 `maxLength` 都必须 ≥ 当前宽度。下界不判（旧数据是 4 位、
    盘上仍可读，所以 `minLength=4` 是对的）。"""
    from agentflow import capabilities as C
    from agentflow import schema as S

    width = len(S.format_id(0))
    assert width == S.ID_DIGITS, (width, S.ID_DIGITS)
    bad: list[str] = []
    for role, specs in C.CAPABILITIES.items():
        for spec in specs:
            props = (getattr(spec, "params", {}) or {}).get("properties") or {}
            for name, sub in props.items():
                if not str(name).endswith("_id") or not isinstance(sub, dict):
                    continue
                cap = sub.get("maxLength")
                if isinstance(cap, int) and cap < width:
                    bad.append(f"{role}.{spec.action} 的 {name}: maxLength={cap} < {width}")
    assert not bad, "这些声明的长度上界比当前编号宽度还短（正当调用会被拒）：\n  " + "\n  ".join(bad)
    # 反真空：这一条真的扫到了东西（否则它可能一行都没看）
    scanned = sum(1 for specs in C.CAPABILITIES.values() for spec in specs
                  for name in ((getattr(spec, "params", {}) or {}).get("properties") or {})
                  if str(name).endswith("_id"))
    assert scanned >= 20, f"只扫到 {scanned} 个 *_id 参数 ⇒ 扫描面可能坏了"
