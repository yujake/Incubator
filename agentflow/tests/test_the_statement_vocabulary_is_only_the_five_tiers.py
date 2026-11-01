# -*- coding: utf-8 -*-
"""判据：判档那一问只有**两态** —— 有 T0–T4，或者这一格根本没查成。

## 业主裁定（2026-11-01，两刀）

第一刀：「审美轴三格（合格 / 太平凡 / 判不了）是 T0 到 T4 的老设计，可以退场了，
直接只用 T0 到 T4」。

第二刀：「应该不会有"判不了"的情况，毕竟语义切割已经很明确了」。

所以最终形态（定稿）：

- `STATEMENT_VERDICTS` = `("T0","T1","T2","T3","T4")`，从 `NONTRIVIALITY_LEVELS` 派生；
  **没有 null、没有"判不了"、没有旧三格**；
- 档位只有两种结局：**有 T0–T4**，或者**这一格根本没查成**
  （`checked=False` + reason；要重试 / 要重交 / 要人看）；
- "判不了"不是一种判定结果，是**我们没拿到判定** —— 它必须长成 `checked=False`，
  而且**不许落一条 `nontriviality: null` 的行**冒充"判过了但没档"；
- 概念 / 定义行仍是 `not_applicable`：那是"这一问对它不成立"，不是"没查成"，两回事；
- 旧台账里的三个旧词只在 `_tier_from_legacy_decision()` 一处折算（读旧行）。

## 这一组钉七条

1. 词表 == 五档（从档位轴派生）；
2. `src/` 里等于旧三格的字面量只许出现在 `_tier_from_legacy_decision()`（本模块严格；
   别处只允许已登记的其它轴）—— 反泄漏；
3. 假缝回 `{"decision": null}` / 旧词 / 坏 JSON ⇒ 一律 `checked=False`，且**没有档位行**；
4. 假缝回 `{"decision": "T2"}` ⇒ `checked=True`、档位 2、档位台账一行、决定台账 `decision="T2"`；
5. 反真空：把词表 monkeypatch 回旧三格 ⇒ 1 必红；
6. 概念行 ⇒ `not_applicable`（不进 3 的 `checked=False`）；
7. 正文被截断 ⇒ `checked=False` + 点名叫你"拆段重交"，且没有档位行、不落"未判"行。

## 反真空

不调模型：全部用假缝（直接替换 `seam.ask_json`）。每条都断言盘上的那一行。
"""
from __future__ import annotations

import ast
import json
import pathlib
import types

import pytest

from agentflow import secretary as SEC

OLD = ("合格", "太平凡", "判不了")
STATEMENT = "命题：任意有限群 G 的 Sylow p-子群两两共轭。"
PROOF = "证明：先取一个 Sylow p-子群 P，再对任一 Q 用轨道计数与共轭作用证明 |G:N_G(P)| ≡ 1 mod p。∎"
CONCEPT = "概念：Sylow p-子群（有限群 G 的阶为 p 的幂的极大子群）。"


class _Seam:
    """假缝：回一份预置 JSON，或直接抛异常（零模型调用）。"""

    def __init__(self, reply: dict | None = None, *, boom: bool = False) -> None:
        self.reply = dict(reply or {})
        self.boom = boom
        self.calls = 0

    def ask_json(self, prompt, **kw):
        self.calls += 1
        if self.boom:
            raise TimeoutError("假缝：超时")
        return dict(self.reply), types.SimpleNamespace(ok=True, problem="", detail="")


def _judge(tmp_path: pathlib.Path, seam: _Seam, *, proof: str = PROOF):
    boss = SEC.Secretary(role="B", root=tmp_path, seam=seam, enable_model=True)
    return boss.judge_statement(statement_full=STATEMENT, proof_text=proof,
                                task_id="t-000001")


def _tier_rows(tmp_path: pathlib.Path) -> list[dict]:
    path = SEC.nontriviality_path(tmp_path)
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _decision_rows(tmp_path: pathlib.Path) -> list[dict]:
    path = SEC.decisions_path(tmp_path, "B")
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- ① 词表
def _vocabulary_problem() -> str:
    """①的本体：返回空串 = 词表就是五档、且两处是同一张表（⑤ 拿它当负控）。"""
    want = tuple(SEC.nontriviality_label(level) for level in SEC.NONTRIVIALITY_LEVELS)
    if want != ("T0", "T1", "T2", "T3", "T4"):
        return f"档位轴的显示名不是 T0..T4：{want!r}"
    if SEC.STATEMENT_VERDICTS != want:
        return f"词表不是五档：{SEC.STATEMENT_VERDICTS!r}"
    if SEC.JUDGE_VERDICTS["statement_aesthetic"] is not SEC.STATEMENT_VERDICTS:
        return "JUDGE_VERDICTS 里那一格不是同一张表（两处两个名字）"
    if [w for w in OLD if w in SEC.STATEMENT_VERDICTS]:
        return f"词表里还有旧词：{[w for w in OLD if w in SEC.STATEMENT_VERDICTS]}"
    return ""


def test_the_vocabulary_is_derived_from_the_tier_axis() -> None:
    """① 词表 = 档位轴的显示名；三个旧词一个都不在，且与 JUDGE_VERDICTS 是同一张表。"""
    assert _vocabulary_problem() == "", _vocabulary_problem()


# ---------------------------------------------------------------- ② 只许一处
def test_the_old_words_live_only_in_the_legacy_decision_reader() -> None:
    """② 本模块里"恰好等于旧词"的字符串常量只许落在 `_tier_from_legacy_decision()`。

    别的模块里的命中各属别的轴（V 判词折成"成立" / 状态标签 / 错误桶名），这里只要求
    "没有新模块/新函数开始产生这三个词"：旧词命中的模块集合必须是已登记的那几个。
    """
    tree = ast.parse(pathlib.Path(SEC.__file__).read_text(encoding="utf-8"))
    readers = [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_tier_from_legacy_decision"]
    assert len(readers) == 1, f"读旧行的折算口应当只有一处：{[n.name for n in readers]}"
    lo, hi = readers[0].lineno, readers[0].end_lineno
    outside = [f"{n.lineno}:{n.value!r}" for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and n.value in OLD and not (lo <= n.lineno <= hi)]
    assert outside == [], (
        "旧词作为词表取值又出现在别处（写侧/题面/闸门）—— 它们只许在 "
        "`_tier_from_legacy_decision` 里被折算：\n  " + "\n  ".join(outside))

    # 别的模块：只许已登记的那几个（V 判词折档 / 状态标签 / 门禁显示 / 错误桶名）。
    registered = {"verifications.py", "conductor.py", "gates.py", "errorstats.py"}
    src_root = pathlib.Path(SEC.__file__).resolve().parents[1]
    seen: dict[str, int] = {}
    for path in sorted(src_root.rglob("*.py")):
        try:
            other = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        hits = [n for n in ast.walk(other)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in OLD]
        if hits:
            seen[path.name] = len(hits)
    strange = {name: count for name, count in seen.items() if name not in registered}
    assert strange == {}, (
        "这三个词作为字面量出现在未登记的模块里（新的一处'同一件事两个名字'）：\n  "
        + "\n  ".join(f"{k}:{v}" for k, v in sorted(strange.items())))

    # 反真空：那个函数真的在、真的能按旧行折算（不是把词删光换一个空函数）。
    assert SEC._tier_from_legacy_decision({"decision": "太平凡"}) == 0
    assert SEC._tier_from_legacy_decision({"decision": "合格",
                                          "judge": {"nontriviality": 2}}) == 2
    assert SEC._tier_from_legacy_decision({"decision": "判不了"}) is None
    assert SEC._tier_from_legacy_decision({"decision": "T3"}) == 3


# ---------------------------------------------------------------- ③ 没拿到判定
def test_a_judge_without_a_usable_decision_is_not_a_tier(tmp_path: pathlib.Path) -> None:
    """③ null / 旧词 / 坏 JSON / 调用失败 / 缺证明正文 ⇒ 一律"没查成"，且没有档位行。

    "判不了"不是第四档，也不是一条 `nontriviality: null` 的行：它是**我们没拿到判定**。
    台账上它只长成 `checked=False` + `decision="没查成"`，处置是"重试 / 重交 / 人看"。
    """
    cases = {
        "null": _Seam({"decision": None, "reason": "定不了"}),
        "旧词": _Seam({"decision": "合格", "reason": "收"}),
        "坏 JSON": _Seam({"decision": "T9"}),
        "调用失败": _Seam(boom=True),
    }
    for label, seam in cases.items():
        root = tmp_path / label.replace(" ", "_")
        got = _judge(root, seam)
        assert got["checked"] is False, (label, got)
        assert _tier_rows(root) == [], f"{label}：没查成却留下了一条档位行"
        assert _decision_rows(root)[0]["decision"] == SEC.JUDGE_UNCHECKED, (label, _decision_rows(root))

    # 缺证明正文（读数一项都取不到）：同样是"没查成"，不是一条"未判"的档位行。
    root = tmp_path / "no_proof"
    got = _judge(root, _Seam({"decision": "T2"}), proof="")
    assert got["checked"] is False, got
    assert _tier_rows(root) == [], "缺证明正文却留下了一条档位行"
    assert _decision_rows(root)[0]["decision"] == SEC.JUDGE_UNCHECKED
    assert "证明正文" in str(_decision_rows(root)[0]["reason"]), _decision_rows(root)[0]


# ---------------------------------------------------------------- ④ 有档
def test_a_tier_reaches_both_ledgers(tmp_path: pathlib.Path) -> None:
    """④ `{"decision":"T2"}` ⇒ checked=True、档位 2、档位台账一行、决定台账 decision="T2"。"""
    got = _judge(tmp_path, _Seam({"decision": "T2", "reason": "方法平凡但工作量大"}))
    assert (got["checked"], got["decision"], got["nontriviality"], got["label"]) == \
        (True, "T2", 2, "T2"), got
    rows = _tier_rows(tmp_path)
    assert len(rows) == 1, rows
    assert (rows[0]["nontriviality"], rows[0]["label"]) == (2, "T2"), rows[0]
    assert _decision_rows(tmp_path)[0]["decision"] == "T2"
    assert _decision_rows(tmp_path)[0]["judge"]["checked"] is True


# ---------------------------------------------------------------- ⑤ 反真空
def test_a_retired_vocabulary_put_back_makes_the_vocabulary_check_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 把 JUDGE_VERDICTS 里那一格 monkeypatch 回旧三格 ⇒ ① 的本体必红。"""
    assert _vocabulary_problem() == "", _vocabulary_problem()
    monkeypatch.setitem(SEC.JUDGE_VERDICTS, "statement_aesthetic", OLD)
    problem = _vocabulary_problem()
    assert problem, "词表换回三格之后 ① 仍然判干净 ⇒ 那条检查没有在读 JUDGE_VERDICTS"


# ---------------------------------------------------------------- ⑥ 概念行
def test_a_concept_row_is_not_applicable_not_unchecked(tmp_path: pathlib.Path) -> None:
    """⑥ 概念行 ⇒ `not_applicable`（结构上不需要判），不是 ③ 的"没查成"。"""
    boss = SEC.Secretary(role="B", root=tmp_path, seam=None, enable_model=True)
    got = boss.judge_statement(statement_full=CONCEPT, kind="concept")
    assert got["checked"] is True, got
    assert got["applicable"] is False, got
    assert got["nontriviality"] is None and got["nontriviality_tri"] == "not_applicable", got
    rows = _tier_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["applicable"] is False, rows
    assert _decision_rows(tmp_path) == [], "概念行不经过判词，不该写决定台账"


# ---------------------------------------------------------------- ⑦ 截断
def test_a_truncated_proof_is_unchecked_and_leaves_no_tier_row(tmp_path: pathlib.Path) -> None:
    """⑦ 正文被截断 ⇒ checked=False + 点名叫你拆段重交；不发调用、不落档位行。"""
    seam = _Seam({"decision": "T3"})
    huge = "证明：" + "推导。" * 8000           # > PROOF_BODY_CAP
    got = _judge(tmp_path, seam, proof=huge)
    assert got["checked"] is False, got
    assert seam.calls == 0, "正文已经被截断，仍然把它发去判档（白花一次调用）"
    assert _tier_rows(tmp_path) == [], "截断却留下了一条档位行"
    reason = str(_decision_rows(tmp_path)[0]["reason"])
    assert "截断" in reason and "拆段" in reason, reason
    assert _decision_rows(tmp_path)[0]["decision"] == SEC.JUDGE_UNCHECKED
