"""「两层参数对齐是假的」这一族：约束必须从真身派生，判据必须能红。

## 这一组守什么（审计 D 线的缺陷 1 / 2 / 3 / 4 / 6 / 7，基线 `0545860`）

审计的一句话是："单层加字段、两层当对齐；判据看 `[]` 就认为一致"。实测三处：

- `G.write_mapping` 的动作面只有 `project: _S` 与 `rows: _ARR_OBJ`，而工具面
  （`doc.write_mapping`）有 `project.minLength=1 / maxLength=300`、`rows.minItems=1`
  与每行必填六格（kind/label/env_no/ledger_id/proof_no/file）；
- `V.verify_proof` 的动作面 `proof_no` 只有 `_I`，工具面有 `minimum=1`；
- `B.register_statement.proofs` 根本没有工具层（整条动作没有同名工具），
  于是"工具面没有它"被读成"两层一致"（unknown 冒充通过）。

而 `capabilities.param_type_divergences()` 当时返回 `[]`，因为它只比 `type` / `items.type`，
并且 `_module_constants` 解析不出嵌套在 `items` 里写的常量名（`doc_tools._MAPPING_ROW_PARAMS`）
—— 那条 array 连"两侧都有 `items.type`"的前提都不成立，就被"一侧只写 `{type: array}` 不报"
的豁免放过了。

## 判据的分工（这一组不重复 `capabilities` 里的断言）

导入期的第 [9] 条已经断言"没有未登记的约束不对称"、[9b] 断言登记表两个方向都对得上、
[9c] 断言"参数真身在工具层"的那几对逐键相等。这里做的是导入期做不到的三件事：

1. 改前红：把三处约束按审计时的样子拿掉（合成一张改前表）⇒ 判据必须报出来，
   且报的就是那三处（证明它不是恒真、也不是报别的）；
2. 反真空：把工具面（真身）改一格 ⇒ 判据必须红（证明它消费的是派生结果，
   不是两份手抄碰巧相同）；把登记删掉 ⇒ 必须红；
3. 读数自证：模块表与 `tools._MODULES` 的差集、`tools_read` 与工具总数的等式、
   handler 覆盖率 —— 这些是"判据真的走遍了"的证据（P16：空集永远是子集）。
"""

from __future__ import annotations

import ast
import copy
import importlib
from dataclasses import replace

import pytest

from agentflow import capabilities as C
from agentflow import tools as T

#: 审计点名的三处（改前的声明面）。键是 `(角色, 动作, property)`，值是"工具面有、动作面没有"的约束键。
_AUDITED_DIVERGENCES: dict[tuple[str, str, str], set[str]] = {
    ("G", "write_mapping", "project"): {"minLength", "maxLength"},
    ("G", "write_mapping", "rows"): {"minItems", "items.required"},
    ("V", "verify_proof", "proof_no"): {"minimum"},
}


def _drop_constraints(spec: C.ActionSpec, prop: str, keys: tuple[str, ...]) -> C.ActionSpec:
    """深拷贝一条动作声明，并把它某个 property 上的几个约束键拿掉（只动副本）。

    支持 `items.required` 这种点号写法（它住在 `items` 里面，不是 property 的顶层键）。
    """
    params = copy.deepcopy(dict(spec.params or {}))
    declared = params["properties"][prop]
    for key in keys:
        head, _, tail = key.partition(".")
        if tail:
            declared.get(head, {}).pop(tail, None)
        else:
            declared.pop(key, None)
    return replace(spec, params=params)


def _pre_fix_action_table() -> dict[str, tuple[C.ActionSpec, ...]]:
    """审计时（基线 `0545860`）的动作表：三处约束都还没有。

    其余动作照今天的声明原样带上 —— 这样"报出来的就是那三处"才是一个有信息量的结论：
    如果判据把别的也报出来，说明这张合成表本身错了（或者判据在别的格上也有假红）。
    """
    table: dict[str, tuple[C.ActionSpec, ...]] = {}
    for role, specs in C.CAPABILITIES.items():
        updated = []
        for spec in specs:
            if (role, spec.action) == ("G", "write_mapping"):
                spec = _drop_constraints(spec, "project", ("minLength", "maxLength"))
                spec = _drop_constraints(spec, "rows", ("minItems", "items.required"))
            elif (role, spec.action) == ("V", "verify_proof"):
                spec = _drop_constraints(spec, "proof_no", ("minimum",))
            updated.append(spec)
        table[role] = tuple(updated)
    return table


def _tool_faces_with(**overrides: dict) -> dict[str, dict]:
    """真实工具约束面的一份可变副本（`工具名 -> {property: {约束键: 值}}` 的替换）。"""
    faces = copy.deepcopy(C._tool_param_faces())
    for tool_name, patch in overrides.items():
        props = faces[tool_name]["properties"]
        for prop, keys in patch.items():
            props[prop].update(keys)
    return faces


# ---------------------------------------------------------------- 一、改前红

def test_the_three_audited_divergences_are_caught_by_the_new_comparison() -> None:
    """改前红：把三处约束拿掉 ⇒ 判据必须报出那三处（且只报那三处）。

    这条是整个文件的核心：`param_type_divergences()` 在审计当时返回 `[]`，
    而上面这三处是真实分歧。合成表 = 审计时的声明面，判据 = 修好之后的判据；
    两者一碰，报出来的必须正好是 `_AUDITED_DIVERGENCES` 里那三对。
    """
    faces = C._tool_param_faces()
    divergences = C.param_type_divergences_for(_pre_fix_action_table(), faces)
    reported: dict[tuple[str, str, str], set[str]] = {}
    for d in divergences:
        role_action, _, tool_name = d.where.partition(" <-> ")
        role, _, action = role_action.partition(".")
        for (e_role, e_action, prop), keys in _AUDITED_DIVERGENCES.items():
            if (role, action) != (e_role, e_action):
                continue
            if f"property {prop!r}" not in d.message:
                continue
            reported[(role, action, prop)] = {
                key for key in keys if f"'{key}'" in d.message
            }
    assert reported == _AUDITED_DIVERGENCES, {
        "报出来的": sorted(f"{r}.{a}.{p} <- {sorted(k)}" for (r, a, p), k in reported.items()),
        "审计点名但没报的": sorted(
            f"{r}.{a}.{p} <- {sorted(k)}"
            for (r, a, p), k in _AUDITED_DIVERGENCES.items()
            if (r, a, p) not in reported
        ),
        "多说出来的（判据在别的格上有假红，或合成表带进了别的差）": [
            d.where for d in divergences
            if not any(f"{r}.{a}" == d.where.partition(" <-> ")[0]
                       and f"property {p!r}" in d.message
                       for (r, a, p) in _AUDITED_DIVERGENCES)
        ],
    }
    # 三处都必须以 error 级报（不是 warning/info）：参数门判错的后果是静默的。
    assert all(d.level == "error" for d in divergences), {(d.where, d.level) for d in divergences}


def test_the_array_exemption_no_longer_swallows_a_nested_items_constant() -> None:
    """改前红（缺陷 1 的另一半）：`items` 写成模块级常量名时，`items.required` 必须仍读得出来。

    `doc_tools._MAPPING_ROW_PARAMS` 就是这种写法。旧读法只解析 `params=` 那一层的 Name，
    于是 `items` 是一个 `ast.Name` ⇒ 两侧 `items.type` 都读成 `None` ⇒ 连"两侧都声明了
    `items.type`"的前提都不成立，那条 array 被豁免整条吞掉。这里直接问派生结果。
    """
    derived = C.action_params_from_tool("G", "write_mapping")
    assert derived is not None, "`G.write_mapping` 必须唯一匹配到 `doc.write_mapping`"
    rows = derived["properties"]["rows"]
    assert rows.get("minItems") == 1, rows
    assert rows.get("items.required") == [
        "env_no", "file", "kind", "label", "ledger_id", "proof_no"
    ], rows
    # 对照：同一份读法读 `project` 的边界（字面量那一支）。
    project = derived["properties"]["project"]
    assert (project.get("minLength"), project.get("maxLength")) == (1, 300), project


# ---------------------------------------------------------------- 二、修后为空（但读得出来）

def test_today_there_are_no_unregistered_constraint_asymmetries() -> None:
    """修后：真实树上没有未登记的约束不对称，且覆盖率读数非零。

    为什么"为空"必须配读数：空集永远是子集（P16）。所以这里同时钉 `compared` /
    `keys_compared` 两个正数 —— 判据真的逐对、逐键比过，`[]` 才是证据。
    """
    assert C.param_type_divergences() == [], [
        (d.where, d.message[:120]) for d in C.param_type_divergences()
    ]
    coverage = C.param_type_coverage()
    assert coverage["compared"] > 0, coverage
    assert coverage["keys_compared"] > 0, coverage
    assert coverage["unread"] == [], coverage["unread"]
    # 登记表两个方向都必须对得上（新长出来的红、补齐了没删也红）。
    assert C.unregistered_tool_only_constraints() == [], C.unregistered_tool_only_constraints()
    assert C.stale_tool_only_constraint_entries() == [], C.stale_tool_only_constraint_entries()


def test_the_tool_only_constraint_registry_is_exactly_what_is_computed_today() -> None:
    """登记表与实测逐条相同（两个方向），并且每条都写了理由。

    这条防的是"登记表变成万能豁免"：把 `_KNOWN_TOOL_ONLY_CONSTRAINTS` 当成免死金牌、
    往里加一条就静默——两个方向的差集断言让它加不了、也删不掉（删了 stale 会红）。
    """
    computed = C.tool_only_constraints()
    assert computed, "实测一个工具面独有约束都没有 ⇒ 扩表没有对象，这条判据失去意义"
    assert set(computed) == set(C._KNOWN_TOOL_ONLY_CONSTRAINTS), {
        "未登记": sorted(set(computed) - set(C._KNOWN_TOOL_ONLY_CONSTRAINTS)),
        "登记但不再成立": sorted(set(C._KNOWN_TOOL_ONLY_CONSTRAINTS) - set(computed)),
    }
    for key, keys in computed.items():
        assert keys == set(C._KNOWN_TOOL_ONLY_CONSTRAINTS[key][0]), (key, keys)
        assert C._KNOWN_TOOL_ONLY_CONSTRAINTS[key][1].strip(), f"{key} 没写理由"


# ---------------------------------------------------------------- 三、反真空：改真身必须红

def test_changing_the_tool_side_turns_the_criterion_red() -> None:
    """反真空①：把工具层（真身）的 `minItems` 从 1 改成 2 ⇒ 判据必须红。

    它证明的是"动作面的约束是从工具层派生/对拍的"，不是"两份手抄碰巧相同"：
    改真身的那一侧，判据立刻不对称。同一份改动必须让"真身在工具层"那条断言也红
    （[9c]`param_derivation_violations`），因为那才是登记过的那两对。
    """
    faces = _tool_faces_with(**{"doc.write_mapping": {"rows": {"minItems": 2}}})
    divergences = C.param_type_divergences_for(C.CAPABILITIES, faces)
    hits = [d for d in divergences if d.where.startswith("G.write_mapping")]
    assert hits, "把工具面 `rows.minItems` 改成 2 之后判据仍然全绿 ⇒ 它根本没读工具面"
    assert any("minItems" in d.message for d in hits), hits
    violations = C.param_derivation_violations(C.CAPABILITIES, faces)
    assert any("G.write_mapping" in v and "minItems" in v for v in violations), violations


def test_dropping_one_action_side_constraint_turns_the_criterion_red() -> None:
    """反真空②：把动作面的 `proof_no.minimum` 删掉 ⇒ 判据必须红（且点名那一格）。

    这是审计 D-3 的原始形态：动作面只写 `_I`、工具面有 `minimum=1`，而判据返回 `[]`。
    """
    table = dict(C.CAPABILITIES)
    table["V"] = tuple(
        _drop_constraints(spec, "proof_no", ("minimum",)) if spec.action == "verify_proof" else spec
        for spec in C.CAPABILITIES["V"]
    )
    divergences = C.param_type_divergences_for(table, C._tool_param_faces())
    hits = [d for d in divergences if d.where.startswith("V.verify_proof")]
    assert hits, "把动作面的 `proof_no.minimum` 删掉之后判据仍然全绿 ⇒ 它是恒真的"
    assert any("proof_no" in d.message and "minimum" in d.message for d in hits), hits


def test_the_derivation_reads_tool_source_not_a_handwritten_copy() -> None:
    """反真空③：派生真的读工具源码 —— 用一棵合成的模块 AST 直接问读法。

    为什么不靠 monkeypatch：`monkeypatch` 一个函数名不等于被测判据接在正确的位置上。
    这里把一段"改了 `minItems` 的工具声明"解析成 AST，喂给同一个读法（`_declared_param_faces`），
    读出来的必须就是改后的值 —— 读得到 ⇒ 派生来自源码；读不到 ⇒ 它是抄来的第二份。
    """
    source = (
        "from .base import tool\n"
        "_ROW = {\"type\": \"object\", \"required\": [\"a\", \"b\"]}\n"
        "@tool(\"doc.write_mapping\", \"合成样本\", {\n"
        "    \"type\": \"object\",\n"
        "    \"properties\": {\n"
        "        \"rows\": {\"type\": \"array\", \"minItems\": 7, \"items\": _ROW},\n"
        "    },\n"
        "    \"required\": [\"rows\"],\n"
        "})\n"
        "def _sample():\n"
        "    return None\n"
    )
    faces = dict(C._declared_param_faces(ast.parse(source)))
    assert "doc.write_mapping" in faces, faces
    rows = faces["doc.write_mapping"]["properties"]["rows"]
    assert rows["minItems"] == 7, rows
    assert rows["items.required"] == ["a", "b"], rows


# ---------------------------------------------------------------- 四、动作面独有参数（B.register_statement.proofs）

def test_the_action_only_registry_names_the_proofs_gap() -> None:
    """审计 D-4：`B.register_statement.proofs` 没有工具层，必须登记成"动作面独有参数"。

    "没有工具层"不是"两层一致"：这条动作的 schema 就是动作声明本身
    （`table.create` 那条通用写口被 `store.direct_write_refusal` 挡住，
    拒信里指的 `own.register_statement` 路由没有独立的工具 schema），
    所以 `proofs` 是唯一落点 —— 但这件事必须被写下来，否则它落在 unknown。
    """
    entry = C._KNOWN_ACTION_ONLY_PARAMS.get(("B", "register_statement"))
    assert entry is not None, "`B.register_statement` 没有登记在动作面独有参数表里"
    props, why = entry
    assert "proofs" in props, sorted(props)
    assert why.strip(), "登记没写理由"
    assert "没有同名工具" in why, why
    # 第二栏的口径：登记集合必须等于动作面声明的集合（这是这一格的牙，见下一条）。
    spec = C.find_action("B", "register_statement")
    assert spec is not None
    declared = {str(p) for p in ((spec.params or {}).get("properties") or {})}
    assert props == declared, {
        "动作面有、登记里没有": sorted(declared - set(props)),
        "登记里有、动作面没有": sorted(set(props) - declared),
    }
    # 它今天没有工具层（所以逐 property 计算那一路看不见它）。
    assert C.param_missing_in_tools().get(("B", "register_statement")) is None
    assert "B.register_statement" in C.param_missing_in_tools_coverage()["unmatched"]


def test_deleting_the_action_only_registration_turns_the_criterion_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反真空④：把 `proofs` 从登记里删掉 ⇒ `unregistered` 非空（红）。

    这就是"删登记必红"，也是这一格最看重的一条：登记不再是注释，而是"登记集合 ==
    动作面声明的集合"这条等式。删掉 `proofs` 之后等式立刻不成立。

    注意"删一个 property"与"删整对登记"是两件事：后者只丢掉逐 property 的可见性，
    而"这条动作没有工具层"这个对级事实仍然钉在 `_KNOWN_UNMATCHED_ACTIONS`
    与第 [7] 条的两向断言上（见本用例最后一段）。
    """
    entry = C._KNOWN_ACTION_ONLY_PARAMS[("B", "register_statement")]
    trimmed = dict(C._KNOWN_ACTION_ONLY_PARAMS)
    trimmed[("B", "register_statement")] = (frozenset(entry[0] - {"proofs"}), entry[1])
    monkeypatch.setattr(C, "_KNOWN_ACTION_ONLY_PARAMS", trimmed)
    bad = C.unregistered_missing_in_tools()
    assert bad, "删掉 `proofs` 这条登记之后 unregistered 仍然为空 ⇒ 这条判据是恒真的"
    assert any("B.register_statement" in line and "proofs" in line for line in bad), bad
    # 对级事实另有落点：整对登记被删掉时，"这条动作没有工具层"仍由第 [7] 条钉着
    # （`_KNOWN_UNMATCHED_ACTIONS` 与对账面的 unmatched 集合逐条相等）。
    unmatched = {d.where for d in C.declaration_divergences()
                 if d.code == "two_layer_name_unmatched"}
    assert "B.register_statement" in unmatched
    assert "B.register_statement" in C._KNOWN_UNMATCHED_ACTIONS


def test_forgetting_a_new_action_side_property_turns_the_criterion_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反真空⑤：给"没有工具层"的那条动作的动作面加一格而不登记 ⇒ 必须红。

    这条比"删登记"更强：它管的是将来 —— 谁给 `B.register_statement` 加参数
    （或给任何一条"没有工具层"的动作加参数）而忘了登记，判据必须响。
    """
    spec = C.find_action("B", "register_statement")
    assert spec is not None
    params = copy.deepcopy(dict(spec.params or {}))
    params["properties"]["brand_new_parameter"] = {"type": "string"}
    grown = replace(spec, params=params)
    table = {**C.CAPABILITIES, "B": tuple(
        grown if s.action == "register_statement" else s for s in C.CAPABILITIES["B"]
    )}
    bad = C.unregistered_missing_in_tools(table, C._tool_param_faces())
    assert any("brand_new_parameter" in line for line in bad), bad
    # 过期方向：动作面把 `proofs` 删掉而登记还留着 ⇒ 也要红（登记表必须自我清理）。
    shrunk = _drop_constraints(spec, "proofs", ())
    params = copy.deepcopy(dict(shrunk.params or {}))
    params["properties"].pop("proofs", None)
    shrunk = replace(shrunk, params=params)
    table = {**C.CAPABILITIES, "B": tuple(
        shrunk if s.action == "register_statement" else s for s in C.CAPABILITIES["B"]
    )}
    stale = C.stale_action_only_entries(table, C._tool_param_faces())
    assert any("B.register_statement" in line and "proofs" in line for line in stale), stale


def test_the_matched_pair_gaps_are_registered_exactly() -> None:
    """第一栏：真有工具面的那 6 对、9 个 property 必须逐条登记（多一个少一个都红）。

    甲方案的口径（2026-10-22 业主裁定）：逐 property 计算只对"唯一匹配到工具"的 23 对做；
    没有工具层的那 39 条动作不进这一路（否则会得到 42 对 111 个 property 的清单，
    与 `_KNOWN_UNMATCHED_ACTIONS` 重复登记同一个事实）。
    """
    computed = C.param_missing_in_tools()
    registered = {
        key: sorted(value[0]) for key, value in C._KNOWN_ACTION_ONLY_PARAMS.items()
        if key in computed
    }
    assert computed == {key: sorted(computed[key]) for key in computed}, "返回值必须已排序"
    assert registered == computed, {
        "未登记": {k: v for k, v in computed.items() if k not in registered},
        "登记但不再缺": {k: v for k, v in registered.items()
                        if sorted(computed.get(k, [])) != v},
    }
    # 反真空：这一路真的比过 23 对（不是 0 对）。
    coverage = C.param_missing_in_tools_coverage()
    assert coverage["pairs_with_tool"] == len(C.two_layer_reconciliation()["compared"]), coverage
    assert coverage["pairs_with_tool"] > 0, coverage


# ---------------------------------------------------------------- 五、模块表同源（审计 D-6）

def test_the_module_table_is_derived_from_the_tools_registry() -> None:
    """模块表必须派生自 `tools._MODULES`，差集就是那张"多读一个模块"的登记表。

    审计 D-6 的形态：`capabilities._TOOL_MODULES` 是手抄的 14 项，注释却写着"与
    `tools._MODULES` 同源"—— 实测少 `text_tools` / `manuscript_tools`、多 `conjecture_tools`。
    于是 `tools_read=77` 而工具层有 95 件，读数说不出那 18 件的差从哪来。
    """
    assert set(C._TOOL_MODULES) == set(T._MODULES) | set(C._TOOL_MODULE_EXTRAS), {
        "`:MODULES` 有、本表没读": sorted(set(T._MODULES) - set(C._TOOL_MODULES)),
        "本表读了、两份名单都没说": sorted(
            set(C._TOOL_MODULES) - set(T._MODULES) - set(C._TOOL_MODULE_EXTRAS)
        ),
        "额外登记了但不在名单里": sorted(set(C._TOOL_MODULE_EXTRAS) - set(C._TOOL_MODULES)),
    }
    for module, why in C._TOOL_MODULE_EXTRAS.items():
        assert why.strip(), f"额外读 {module} 没写理由"
    assert len(set(C._TOOL_MODULES)) == len(C._TOOL_MODULES), "模块名单里有重复项"


def test_the_tools_read_reading_explains_the_gap_to_the_tool_count() -> None:
    """读数必须自己算得出 `tools_read` 与工具总数的关系（审计 D-6 的治本）。

    等式：`tools_in_registry_modules - tools_unread + tools_read_but_not_registered
    = tools_read`。今天是 `118 - 16 + 0 = 102`：
    16 件读不出是因为 `table_tools` / `fs_tools` 的 `params` 是 `_obj(...)` 调用
    （不是字典字面量）。"读到但不注册"那一格现在是 0：2026-10-27 把
    `conjecture_tools` 加进 `tools._MODULES` 之后，它不再属于"读到、但装配不到"那一族。
    """
    coverage = C.param_type_coverage()
    assert coverage["modules_missing"] == [], coverage["modules_missing"]
    assert coverage["tools_in_registry_modules"] > 0, coverage
    assert coverage["tools_unread"], (
        "一件读不出的都没有 ⇒ 这个读数没有解释力（它今天必须解释那 16 件）"
    )
    assert coverage["tools_read_but_not_registered"] == [], (
        "读到但不注册的清单必须为空：`conjecture_tools` 曾在里面挂了两天，"
        "2026-10-27 已进 `tools._MODULES`。再有新条目就说明又有一个模块被写了却没人装配："
        f"{coverage}"
    )
    assert (
        coverage["tools_in_registry_modules"]
        - len(coverage["tools_unread"])
        + len(coverage["tools_read_but_not_registered"])
        == coverage["tools_read"]
    ), coverage
    # 读不出的那些必须真的是"params 不是字典字面量"，而不是文件缺失（unknown 的两种来源要分开）。
    for name in coverage["tools_unread"]:
        prefix = name.split(".")[0]
        assert prefix in ("table", "fs"), (
            f"{name} 读不出约束面，而它不属于已知的那两个模块（table / fs）⇒ 情况变了，"
            "要么修读法，要么更新这条判据"
        )


# ---------------------------------------------------------------- 六、handler 覆盖（审计 D-7）

def test_every_role_with_actions_is_covered_by_the_handler_check() -> None:
    """`test_capabilities_two_layer` 的 handler 判据必须覆盖全部动作（含 V）。

    审计 D-7：那张 `ROLE_MODULE` 只有 A–H，而 V 有三条动作 ⇒ 实测覆盖 59/62，
    而 `if role not in ROLE_MODULE: continue` 让少掉的三条静默跳过（判据看起来在跑）。
    """
    from tests.test_capabilities_two_layer import ROLE_MODULE

    roles_with_actions = sorted(r for r, specs in C.CAPABILITIES.items() if specs)
    missing = sorted(set(roles_with_actions) - set(ROLE_MODULE))
    assert not missing, f"这些角色有动作而 handler 判据没覆盖：{missing}"
    assert "V" in ROLE_MODULE, "V 的三条动作没有被 handler 判据看过（审计 D-7）"
    module_name, class_name = ROLE_MODULE["V"]
    cls = getattr(importlib.import_module(module_name), class_name, None)
    assert cls is not None, f"{class_name} 不在 {module_name}"
    covered = sum(len(C.CAPABILITIES[role]) for role in ROLE_MODULE)
    total = C.two_layer_reconciliation()["total"]
    # 实测（2026-10-22）：62 / 62。不写死这个数：动作增删会让它漂，等式不会。
    assert covered == total, f"handler 判据只覆盖 {covered} / {total} 个动作"
