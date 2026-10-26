# -*- coding: utf-8 -*-
"""判据：形式化这一档在 F 侧的三道门（立项拒 / 台账残留不派 E / 没有第二条边）。

## 口径（业主 2026-10-27 逐字）

「我们现在不准边研究边 lean，我在 L 侧已经描述很清楚了什么时候能派 L」。
`specs/l.py` 把理由登记在那儿：只有 B 可以派 L（B 是 `statements` 的唯一登记方，形式化的
成本由那个登记证明的人判断），「F → L」那条边「本批曾开又撤回：F 的攻坚是流水线的一环，
挂在它下面就是把形式化变成流水线的一步」。

⇒ F 这一侧的正确行为不是"派给谁"，而是"这个形状不该在这里"。

## 三道门（一条判据一道，缺一道就漏一条路）

1. 立项那一层：`create_plan` 的子目标里出现 `method="formal"` 或 `owner="L"` ⇒ 整笔受控
   拒绝（`formal_is_not_f_todo`，一行都不写库），拒信逐字带回那条裁定。主路在这一层。
2. 台账残留那一层：一行已经被别的路径（人手改盘、旧计划）写成 `owner="L"` 的子目标，
   读数看得到它、`_deploy` 也不把它派给 E（受控码 `formal_edge_missing`）。
   这一层守的是"改前留下的行"与"将来 schema 被放宽那天"，不是主要理由。
3. 权限面那一层：`capabilities.ALLOWED_EDGES` 里出现任何 `X->L`（X 不是 B）⇒ 红。
   业主的裁定是"只有 B 派 L"，而这道门是唯一能防"哪天有人手滑开一条边"的判据。

## 为什么第 2 道门还要留

`_is_formal_subgoal` 的 docstring 早就写着：`owner="L"` 那一格经 `create_plan` 写不进来，
但 `_deploy` 读的是台账里的行 —— 一行被别的路径写进来时必须同样落"F 派不出去"，
而不是掉进"owner 不在 SUBGOAL_OWNERS 里"的 `PlanError`。这道门同时证明另一件事：
即便有人绕过立项，形式化也不会被降级成 E 的数值检查。

## 第 2 道门同时是一条"另一条路也堵着"的读数

`schema.SUBGOAL_OWNERS` 今天没有 L，所以这种行连回写都过不去：`F.step` 在 `_write_plan`
那一步受控拒绝（`PlanError`，一行都不写）。判据按 `schema.SUBGOAL_OWNERS` 现算分两支写 ——
词表哪天被裁定放宽，这一支自动转到强的那一半，不用回来改判据。
但这句话只是旁证：主路是第 1 道门（立项就拒）。
"""
from __future__ import annotations

import json

import pytest

from agentflow import capabilities as CAP
from agentflow import schema as S
from agentflow.agent_f import AgentF, PlanError
from agentflow.store import Store

#: 这一条的子目标原文（判据只关心形状那两格，原文保持与真机同一句）。
SUBGOAL_TEXT = "把这条命题形式化"

#: 立项那一层的受控码（与 `agent_f/create_plan.py::FORMAL_IS_NOT_F_TODO` 同源）。
FORMAL_IS_NOT_F_TODO = "formal_is_not_f_todo"

#: 唯一被允许有入边的角色（业主 2026-10-27：「F到L本就没边，L是B侧唯一派」）。
ONLY_DISPATCHER_OF_L = "B"


def _f(store: Store) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root})


def _plan_with_one_subgoal(store: Store, *, owner: str) -> tuple[AgentF, str]:
    """按一个合法 owner 建一行计划，返回 (F, plan_id)。

    只用合法 owner 建：`create_plan` 那一侧"写不进 L"由另一条判据单独钉
    （`test_create_plan_writes_owner_l_exactly_when_the_vocabulary_has_it`），
    这里要用的是"台账里已经有一行"这个起点。
    """
    f = _f(store)
    out = f.create_plan("难题：把这条命题形式化", "PK-OWNER-L", subgoals=[
        {"sid": "s1", "text": SUBGOAL_TEXT, "owner": owner,
         "testable": "判据夹具：这一步做完能一句话判它成立或不成立"},
    ])
    assert out["created"] is True, out
    return f, str(out["plan_id"])


def _rewrite_owner(store: Store, plan_id: str, *, from_owner: str, to_owner: str) -> None:
    """直接改表文件里那一格 owner —— 绕开 `create_plan` 与 schema 校验的那条路。

    为什么走得通：`Store.read` 是"无锁快照读"（每次读都重新解析表文件），所以改盘即生效；
    也就是 `_is_formal_subgoal` docstring 说的"一行被别的路径（人手改盘）写成 owner=L"。
    """
    path = store.data / S.TABLES["attack_plans"]["file"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    touched = 0
    for row in doc["rows"]:
        if str(row.get("plan_id")) != plan_id:
            continue
        for sg in row.get("subgoals") or []:
            if str(sg.get("owner")) == from_owner:
                sg["owner"] = to_owner
                touched += 1
    assert touched == 1, f"夹具没改到那一格（改了 {touched} 处）⇒ 下面的断言全是空转"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _reading_text(out: dict) -> str:
    """那一轮受控读数的人话：`step` 给 `reason`（由 `detail` 合成），`_deploy` 只给 `detail`。

    两个入口共用同一份散文（`step` 只是把 `detail` 抄进 `reason`），所以判据读同一段文字 ——
    不因为走了哪个入口而判得不一样。
    """
    return str(out.get("reason") or out.get("detail") or "")


def _assert_no_experiment_and_a_controlled_product(out: dict, store: Store) -> None:
    """形式化那一档在 F 这一侧唯一的受控结局（与 `test_agent_f.py` 那把尺子同一口径）。

    三件：① 一条实验行都没有；② 受控产物与受控码；③ 落点账（该派谁 / 边在不在 /
    今天谁派得动），全部现读权限面真身。
    """
    assert store.rows("experiments") == [], (
        "形式化子目标在 E 那里落了实验行 ⇒ 它被派给 E 了（这正是这条判据要防的降级）")
    assert out["action"] == "dead_end", f"不是受控产物，而是 {out['action']!r}"
    assert out["outcome"] == "no_change", "这一轮什么都没做成 ⇒ outcome 只能是 no_change"
    facts = out.get("formal_dispatch") or {}
    assert facts.get("code") == "formal_edge_missing", (
        f"受控码不对（{facts.get('code')!r}）⇒ 调用方读不到'这是缺一条边'这一类失败")
    assert facts.get("role") == "L", f"形式化该落到 L，读数给的是 {facts.get('role')!r}"
    assert facts.get("edge_exists") == ("L" in CAP.ALLOWED_EDGES["F"]), (
        "edge_exists 没有跟着 ALLOWED_EDGES 走（那是把一句文案写死进了读数）")
    inbound = sorted(r for r, outs in CAP.ALLOWED_EDGES.items() if "L" in outs)
    assert facts.get("dispatchable_by") == inbound, (
        f"dispatchable_by 与权限面的入 L 边不一致：{facts.get('dispatchable_by')} vs {inbound}")
    assert inbound, "权限面里没有任何角色能派 L ⇒ 这个读数没有意义（反真空）"
    text = _reading_text(out)
    assert "L" in text, "读数没有点名该派给谁"
    assert inbound[0] in text, "读数没有点名'需要谁派'"
    assert "数值检查" in text, (
        "读数没有说清'不许退回 E 做数值检查'—— 那句话正是这条账要防的降级")


# ============================================================ 1 读数看得到它
def test_the_readout_shows_an_owner_l_subgoal(store: Store) -> None:
    """读数那一半：`F.status` 的子目标清单里，owner 那一格读出来就是 "L"。"""
    f, pid = _plan_with_one_subgoal(store, owner="E")
    before = f.status(pid)
    assert before["checked"] is True, before
    assert [s["owner"] for s in before["subgoals"]] == ["E"], (
        "改盘之前读到的 owner 不是 E ⇒ 这条夹具证明不了'改盘之后变的正是那一格'")

    _rewrite_owner(store, pid, from_owner="E", to_owner="L")

    got = f.status(pid)
    assert got["checked"] is True, got
    assert [s["owner"] for s in got["subgoals"]] == ["L"], (
        f"台账里那一行已经是 owner=L，而读数读出来的是 "
        f"{[s['owner'] for s in got['subgoals']]} ⇒ 这一格没被看见")
    assert got["subgoal_counts"] == {"todo": 1}, (
        f"owner=L 的子目标没有被数进状态计数：{got['subgoal_counts']}")


# ============================================================ 2 不派 E（行为那一半）
def test_f_does_not_dispatch_an_owner_l_subgoal_to_e(store: Store) -> None:
    """行为那一半：`_deploy` 拿到 owner="L" 的子目标 ⇒ 受控死路，一条实验行都不留。

    为什么判在 `_deploy` 而不是 `step`：落地那一半今天被 schema 卡住（下一条判据钉它），
    而"形式化不派 E"这件事发生在 `_deploy` 里 —— 它就是 `step` 用的那一个分派入口，
    所以这一半今天已经成立，不该跟着落地那一半一起红。
    """
    f, pid = _plan_with_one_subgoal(store, owner="E")
    _rewrite_owner(store, pid, from_owner="E", to_owner="L")

    row = f._plan_row(pid)
    sg = dict(row["subgoals"][0])
    assert sg["owner"] == "L", f"夹具没造出 owner=L 的子目标：{sg.get('owner')!r}"
    out = f._deploy(sg, plan=row)

    _assert_no_experiment_and_a_controlled_product(out, store)
    facts = out.get("formal_dispatch") or {}
    assert facts.get("owner_vocab") == list(S.SUBGOAL_OWNERS), (
        f"owner 词表那份读数没有跟着 schema 走：{facts.get('owner_vocab')} vs "
        f"{list(S.SUBGOAL_OWNERS)}")
    assert facts.get("owner_writable") == ("L" in S.SUBGOAL_OWNERS), (
        "owner_writable 是写死的（它必须现算 schema.SUBGOAL_OWNERS）")
    if "L" in S.SUBGOAL_OWNERS:
        assert "写得进来" in str(facts.get("note") or ""), facts.get("note")
    else:
        assert "写不进来" in str(facts.get("note") or ""), (
            f"词表里没有 L，而读数没说清 owner=L 写不进来：{facts.get('note')}")


# ============================================================ 3 落地那一半按词表现算
def test_step_lands_or_refuses_according_to_the_owner_vocabulary(store: Store) -> None:
    """落地那一半：词表里有 L ⇒ `step` 真的写回这一轮；没有 ⇒ 受控拒绝且不留实验行。

    两档都判，是因为"今天写不回来"是 schema 的现状、不是这条判据的结论：schema 放宽那天，
    这一条会自动要求 `step` 把 owner=L 的那一轮落成死路（届时它是红的来源只有一个 ——
    实现没跟上词表）。
    """
    f, pid = _plan_with_one_subgoal(store, owner="E")
    _rewrite_owner(store, pid, from_owner="E", to_owner="L")

    if "L" in S.SUBGOAL_OWNERS:
        out = f.step(pid)
        _assert_no_experiment_and_a_controlled_product(out, store)
        sg = f.status(pid)["subgoals"][0]
        assert sg["status"] == "blocked", f"子目标没有被标成卡点：{sg['status']!r}"
        assert "L" in str(sg.get("blocked_reason") or ""), (
            f"卡点里没写该派给谁：{sg.get('blocked_reason')!r}")
        assert sg["experiment_ids"] == [] and sg["proof_experiment_ids"] == [], (
            "子目标上落了实验号 ⇒ 它被派给 E 了")
        return

    # 今天这一档：回写校验的是整行，那一格 owner=L 不在词表里 ⇒ 受控拒绝
    with pytest.raises(PlanError) as ei:
        f.step(pid)
    message = str(ei.value)
    assert "owner" in message, f"拒信没有点名坏在哪一格：{message}"
    # 拒信要把当天那份词表逐条列出来（现算，不写死）—— 这正是"为什么写不进来"的读数。
    missing = [o for o in S.SUBGOAL_OWNERS if f"'{o}'" not in message]
    assert not missing, f"拒信没有列出词表里的这些取值：{missing}；{message}"
    assert "'L'" in message, f"拒信没有点名被拒的那个取值：{message}"
    assert store.rows("experiments") == [], (
        "被拒的那一轮仍然落了实验行 ⇒ 受控拒绝发生在派给 E 之后，那是更坏的一种")
    assert [s["owner"] for s in f.status(pid)["subgoals"]] == ["L"], (
        "拒绝之后盘上那一格被改成了别的 owner ⇒ 这是静默改盘，不是受控拒绝")


# ============================================================ 4 负控：owner 那一格
def test_putting_the_owner_back_to_e_makes_the_formal_path_go_away(store: Store) -> None:
    """负控：同一份夹具、同一条子目标，只把 owner 改回 "E" ⇒ 形式化那一支不出现。

    没有这一条，上面那条可以靠"凡是子目标都落死路"变绿 —— 那时它证明的不是
    "owner=L 被认出来了"，而是"这条判据什么都没在看"。
    """
    f, pid = _plan_with_one_subgoal(store, owner="E")
    row = f._plan_row(pid)
    sg = dict(row["subgoals"][0])
    assert sg["owner"] == "E"
    out = f._deploy(sg, plan=row)

    assert out["action"] != "dead_end", (
        f"owner=E 的子目标也走了形式化那一支（action={out['action']!r}）⇒ "
        "那说明死路不是 owner 那一格带来的")
    assert (out.get("formal_dispatch") or {}).get("code") != "formal_edge_missing", (
        "owner=E 的子目标也拿到了 formal_edge_missing")
    with pytest.raises(AssertionError):
        _assert_no_experiment_and_a_controlled_product(out, store)


# ============================================================ 5 判定那一格本身
def test_the_judgement_catches_owner_l_not_only_method_formal() -> None:
    """判定那一格：`owner="L"` 与 `method="formal"` 各自都算形式化，且收窄处没有放宽。

    `name` / `imports` 单独出现不算形式化（`_is_formal_subgoal` 的 docstring 写着为什么）：
    给了它们却没写 `method` 是形状错误，该由 E 那一侧用自己的理由码原话拒绝。
    """
    from agentflow.agent_f import core as FC

    assert FC._is_formal_subgoal({"owner": "L"}) is True, (
        "owner=L 没有被判成形式化 ⇒ 它会掉进 _deploy 末尾那句"
        "'owner 不在 SUBGOAL_OWNERS 里'的 PlanError，而不是落成受控死路")
    assert FC._is_formal_subgoal({"owner": "E", "method": "formal"}) is True
    assert FC._is_formal_subgoal({"owner": "e", "method": " FORMAL "}) is True, (
        "判定没有做大小写与空白归一")
    assert FC._is_formal_subgoal({"owner": "E"}) is False
    assert FC._is_formal_subgoal({"owner": "E", "name": "f_probe", "imports": []}) is False, (
        "只给 name / imports 也被判成形式化 ⇒ 那一条收窄被放宽了")


# ============================================================ 6 立项那一层（两种写法都拒）
def test_create_plan_refuses_a_formal_subgoal_whichever_way_it_is_written(
        store: Store) -> None:
    """立项那一层：`method="formal"` 与 `owner="L"` 两种写法都整笔受控拒绝，一行不落库。

    为什么要两种写法各判一次：`_is_formal_subgoal` 认两格，而模型可能只写其中一格 ——
    只拦 `method` 就等于留着"写 owner=L 绕过去"的门；只拦 `owner` 则连最常见的写法都漏。
    判据是按"这个形状"拦的，不是按某个键拦的。
    """
    f = _f(store)
    base = {"sid": "s1", "text": SUBGOAL_TEXT,
            "testable": "判据夹具：这一步做完能一句话判它成立或不成立"}
    cases = (
        ("PK-OWNER-L-METHOD", dict(base, owner="E", method="formal")),
        ("PK-OWNER-L-OWNER", dict(base, owner="L")),
    )
    for key, sg in cases:
        out = f.create_plan("难题", key, subgoals=[dict(sg)])
        assert out.get("ok") is False, (
            f"子目标 {sg} 没有被受控拒绝：ok={out.get('ok')!r} kind={out.get('kind')!r}")
        assert out.get("kind") == FORMAL_IS_NOT_F_TODO, (
            f"受控码不对（{out.get('kind')!r}）⇒ 调用方读不到'这个形状不该在 F 这里'")
        assert out.get("created") is False and not out.get("plan_id"), out
        text = f"{out.get('error') or ''} {out.get('reason') or ''}"
        for want in ("只有 B 能派 L", "不是 F 的活", "specs/l.py"):
            assert want in text, (
                f"拒信里没有 {want!r} —— 对着改的人不知道该往哪走：{text}")
    assert store.rows("attack_plans") == [], (
        "被拒的计划落了库 ⇒ 之后每一轮 step 都会在同一个坏行上再死一次")
    assert store.rows("experiments") == [], "形式化没走到执行那一层，不许留实验行"


# ============================================================ 7 正控：别的形状照建
def test_a_non_formal_subgoal_still_creates_a_plan(store: Store) -> None:
    """正控：`method="numeric"` 与"不写 method"都照常建计划（拒的不是"这一笔"）。"""
    f = _f(store)
    numeric = f.create_plan("难题", "PK-NUMERIC", subgoals=[
        {"sid": "s1", "text": "数值验证 m<=32", "owner": "E", "method": "numeric",
         "testable": "判据夹具：这一步做完能一句话判它成立或不成立"}])
    assert numeric.get("created") is True and numeric.get("plan_id"), numeric
    plain = f.create_plan("难题", "PK-PLAIN", subgoals=[
        {"sid": "s1", "text": "让 C 做结构分析", "owner": "C",
         "testable": "判据夹具：这一步做完能一句话判它成立或不成立"}])
    assert plain.get("created") is True and plain.get("plan_id"), plain
    assert len(store.rows("attack_plans")) == 2, [r.get("plan_id") for r in store.rows("attack_plans")]


# ============================================================ 8 权限面：只有 B 派得动 L
def test_no_edge_reaches_l_except_from_b() -> None:
    """权限面：`ALLOWED_EDGES` 里出现任何 `X->L`（X 不是 B）⇒ 红。

    业主 2026-10-27 逐字：「F到L本就没边，L是B侧唯一派」。`specs/l.py` 把每一条"为什么不
    开"都登记在那儿了 —— 但那是文案，改权限面的人是改 `specs/l.py` 的 `edges`，改完
    这条判据必须当场响。没有这一格，"哪天有人手滑开一条边"只能靠读 diff 才发现。
    """
    inbound = sorted(role for role, outs in CAP.ALLOWED_EDGES.items() if "L" in outs)
    assert inbound == [ONLY_DISPATCHER_OF_L], (
        f"入 L 的边是 {inbound}，而业主的裁定是「只有 B 派 L」"
        f"（多出来的那几条要么是手滑、要么是裁定变了 —— 两者都必须先过人审）")
    assert "L" not in (CAP.ALLOWED_EDGES.get("F") or frozenset()), (
        "F->L 这条边被开出来了：`specs/l.py` 已逐条登记为什么不开"
        "（F 的攻坚是流水线的一环，挂它下面就是把形式化变成流水线的一步）")
