# -*- coding: utf-8 -*-
"""子目标必须带可检验形式：立项那一次就拒，不许拖到花钱闸才死。

## 改前是什么形态（真机读数，业主已看过）

```text
PLAN 000000 round1 action=dead_end product=dead_end
detail="子目标 a（owner=F）：花钱之前的闸门没过：子目标没有可检验形式（testable 空）"
```

D 立计划时模型一个 `testable` 同义键都没写 ⇒ 计划照样落库 ⇒ 等到 `step` 里
`attackround.pre_spend_gate` 才把它判成 `dead_end(缺定义)` ⇒ F 一次推理都没发，
预算全烧在"每条子目标各死一轮"上，而模型从头到尾没被问过一句"怎么算做成了"。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 空 testable | `create_plan` 整笔受控拒绝（`subgoal_without_testable`）且台账零写入 | 改前照建不误，到 `step` 才 `dead_end` |
| b 同义键 | `check` / `criterion` / `acceptance` 归一成 `testable` 后照常建（正控：别把正常路径弄坏） | 改前不认这些键（归一后仍是空） |
| c 反真空 | 把归一打桩成空 ⇒ b 必红（于是 b 的绿来自归一，不是来自"随便给个值就过"） | —— |

## 为什么不是"自动编一个 testable"

那是替研究定标准：把"不知道该判什么"伪装成"已经能判"。与 `_spec_from_testable`
那段拒绝凭空造 `params` 是同一条理由 —— 所以这里只认"模型真的写过一次"。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF
from agentflow.store import Store

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}

#: 逐字要求的那句话（拒信必须写清"怎么算做成了"与"花钱闸会在推理之前挡掉"）。
MESSAGE_SHOULD = "计划里每一条都要写\"怎么算做成了\""
MESSAGE_WHY = "否则花钱闸会在推理之前把它挡掉，F 一次都跑不起来"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _f(store: Store) -> AF.AgentF:
    return AF.AgentF(store, config={"workspace_root": store.root})


def test_a_subgoal_without_testable_refuses_the_whole_plan_and_writes_nothing(
        tmp_path: pathlib.Path) -> None:
    """a 判据：空可检验形式 ⇒ 整笔拒 + 零写入（不是"先建成功、到 attack 才 dead_end"）。

    改前红：这条断言在改前拿不到 `ok=False`（`create_plan` 会照建，返回
    `created=True` + 一个 `plan_id`），而那一行随后在 `step` 里落
    `dead_end(缺定义)` —— 真机读数就是本文件开头那两行。
    """
    store = _ws(tmp_path)
    f = _f(store)
    out = f.create_plan("难题：证某个小结论", "PK-NO-TESTABLE", budget=dict(BUDGET),
                        subgoals=[{"sid": "a", "text": "证第一步", "owner": "F"}])

    assert out.get("ok") is False, out
    assert out.get("kind") == "subgoal_without_testable", out
    assert out.get("created") is False and out.get("plan_id") is None, out
    # 拒信逐字：点名字目标号、说清"每一条都要写怎么算做成了"、说清后果（F 一次都跑不起来）
    err = str(out.get("error") or "")
    assert "子目标 a 没有可检验形式（testable）" in err, err
    assert MESSAGE_SHOULD in err, err
    assert MESSAGE_WHY in err, err
    # 零写入：整笔计划一行都不许落
    assert store.rows("attack_plans") == [], store.rows("attack_plans")


def test_a_synonym_key_is_normalized_and_the_plan_is_created(tmp_path: pathlib.Path) -> None:
    """b 判据（正控）：模型写的是同义键（`check` / `criterion` / `acceptance`）⇒ 照常建。

    归一之后落进子目标自己的 `testable` 那一格 —— 下游（`pre_spend_gate` / 提示词 /
    手稿）只读那一格，于是"模型真写过一次"这件事在立项时就已经成立。
    """
    for key in ("check", "criterion", "acceptance"):
        store = _ws(tmp_path / key)
        f = _f(store)
        out = f.create_plan("难题", f"PK-{key}", budget=dict(BUDGET),
                            subgoals=[{"sid": "a", "text": "证第一步", "owner": "F",
                                       key: "枚举 n<=18 全过"}])
        assert out.get("ok") is True and out.get("created") is True, (key, out)
        row = store.rows("attack_plans")[0]
        assert row["subgoals"][0]["testable"] == "枚举 n<=18 全过", (key, row["subgoals"])
        # 归一之后别名键不再透传（下游只读 `testable` 一处）
        assert key not in row["subgoals"][0], (key, row["subgoals"])


def test_stubbing_the_normalization_out_turns_b_red(tmp_path: pathlib.Path,
                                                    monkeypatch) -> None:
    """c 判据（反真空）：把归一打桩成"永远丢掉 testable" ⇒ b 必红。

    证明 b 的绿来自"同义键被真的归一了"，而不是来自"随便给个键就能过"：
    归一一旦不认那些键，同一笔调用就必须被拒。
    """
    store = _ws(tmp_path)
    f = _f(store)

    real = AF.AgentF._normalize_subgoal

    def drop_testable(raw, index):
        row = dict(real(raw, index))
        row.pop("testable", None)
        return row

    monkeypatch.setattr(AF.AgentF, "_normalize_subgoal", staticmethod(drop_testable))
    out = f.create_plan("难题", "PK-STUB", budget=dict(BUDGET),
                        subgoals=[{"sid": "a", "text": "证第一步", "owner": "F",
                                   "check": "枚举 n<=18 全过"}])
    assert out.get("ok") is False and out.get("kind") == "subgoal_without_testable", (
        "归一被打桩成空之后，同一笔调用居然还是建成了 ⇒ b 那条判据是真空的", out)
