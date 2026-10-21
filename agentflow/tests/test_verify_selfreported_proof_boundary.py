"""`selfreported_proof` 的证据上界：判据读的是 `notes` 里的声明名。

## 这个文件登记的是哪条边界（`R2b-AN-2-A`）

`verify.verify_all` 的 `selfreported_proof` 判据读的"被检查的声明名"来自`notes`（写入点
`agent_e._declared_name_note`）。`notes` 是可写的自由文本，而判据不校验它等于本行的 `claim_key` / `verifier_subject_key`，所以这条判据能到的一层是"这条
proof 行的依据可以被读出来"，不是"这条依据就是本行命题的"。

本文件做两件事：

1. 把判据真正管得住的形态钉住（哪些必须报、哪些不许报），
其中的防误伤那两条同时是"为什么不补交叉判据"的实测理由 ——生产路径上声明名与 `claim_key` 可以合法地毫不相干（`agent_f.py` 把子目标的 `name` 传给 E，而
`claim_key` 可能是`problem_key#sid`；`.lean` 文件名也可以与命题名无关）。补一条"要求 `verifier_subject_key` 也出现在输出里"的交叉判据会把这两条合规输入判成"自报"，正是
§41.1 记过的"判据过窄 ⇒ 红掉合规输入"。

2. 把"这条上界已经如实登记"变成一条会红的断言：上界写在判据旁边的注释里
（`verify.py` 的 `verify_all`），删掉那段说明就会让第 6 条用例红。没有它，"如实写进注释"这句话与"注释被顺手删掉"在测试里长得一样。
"""

from __future__ import annotations

import inspect

import pytest
from conftest import TS
from agentflow import schema as S
from agentflow import verify as V


# ============================================================ 夹具


def _proof_row(store, eid: str, key: str, output: str, notes: str = "") -> None:
    """落一行 `evidence_kind='proof'` 的形式化实验。

    `verifier_subject_key` 逐字等于 `claim_key`（`schema.Experiment.validate`
    的硬约束），所以夹具里两者永远同值 —— 那正是这条判据读不出"本行命题"
    的原因：本行自己声称的命题名是 `key`，而检查器结论里印的是别的名字。
    """
    row = S.Experiment(
        experiment_id=eid,
        claim=f"命题 {eid}",
        claim_key=key,
        method="formal",
        evidence_kind="proof",
        result="supports",
        negation_kind="not_proved",
        verifier_output=output,
        verifier_subject_key=key,
        notes=notes,
        created_at=TS,
    )
    row.validate()
    with store.tx("experiments", actor="test", note="selfreported_proof 夹具") as tx:
        tx.upsert("experiments", row.to_dict())


def _reported(store) -> set[str]:
    """判据命中的实验 id 集合（只取 `selfreported_proof` 这一条判据）。"""
    return {i.row_id for i in V.verify_all(store).issues if i.code == "selfreported_proof"}


# ============================================================ 判据管得住的形态


def test_a_self_reported_proof_is_reported(store):
    """正控：`claim_key` 只是输出里的子串（`'L'` 在 `'Lean4: no goals'` 里）⇒ 必须报。

    这是 `R2-AN-2` 的出发点：旧判据 `verifier_subject_key in verifier_output`
    对这条完全自报的行判"通过"。
    """
    _proof_row(store, "0000", "L", "Lean4: no goals")
    assert "0000" in _reported(store)


def test_a_name_that_only_appears_in_an_unrelated_warning_is_reported(store):
    """正控：名字只出现在一句与结论无关的告警里 ⇒ 必须报。

    读法必须认"绑了名字的公理诊断"（`formalgw.concluded_names`），
    不能认"名字在输出里出现过"。
    """
    _proof_row(store, "0000", "foo", "Lean4: warning: unused variable 'foo'; no goals")
    assert "0000" in _reported(store)


def test_a_proof_without_any_readable_diagnostic_is_reported(store):
    """正控（必然报）：输出里没有那条命名诊断 ⇒ 报。"""
    _proof_row(store, "0000", "ZZZ", "'other_lemma' does not depend on any axioms")
    assert "0000" in _reported(store)


# ============================================================ 防误伤（也是"不补交叉判据"的理由）


def test_a_hyphen_claim_key_with_an_underscore_declared_name_is_accepted(store):
    """防误伤（§41.1 的正控）：`claim_key='probe-eq'` 而声明名是 `probe_eq` ⇒ 不许报。

    Lean 标识符不许带连字符，所以两者不同是生产路径上的正常形态。
    把判据绑到 `claim_key` 上会把每一条合规的 proof 行判成"自报"。
    """
    _proof_row(
        store, "0000", "probe-eq", "'probe_eq' does not depend on any axioms",
        notes="[formal] 检查器状态 'verified'；声明名 probe_eq；脚本 proofs/probe_eq.lean；imports=[]",
    )
    assert "0000" not in _reported(store)


def test_a_declared_name_unrelated_to_the_claim_key_is_accepted(store):
    """防误伤（`R2b-AN-2-A` 的边界读数）：声明名与 `claim_key` 毫不相干 ⇒ 不许报。

    `agent_f.py` 把子目标的 `name` 直接传给 E（`:874`），而 `claim_key` 可能是
    `problem_key#sid`（`:864`）；`.lean` 文件名同样可以与命题名无关
    （`agent_e.py` 的 `str(name or path.stem)`）。要求 `claim_key` 也出现在
    检查器输出里的那种交叉判据会红掉这一条 —— 所以那条判据没有采纳，
    改成把上界如实登记（见下面那条守卫用例）。
    """
    _proof_row(
        store, "0000", "P12#3", "'lemma_foo' does not depend on any axioms",
        notes="[formal] 检查器状态 'verified'；声明名 lemma_foo；脚本 proofs/lemma_foo.lean；imports=[]",
    )
    assert "0000" not in _reported(store)


def test_a_missing_declared_name_falls_back_to_the_subject_key(store):
    """三态：`notes` 里读不到声明名（历史行 / 手工行）⇒ 退回本行自称的命题名。

    两个方向都要有：退回之后名字真在输出里 ⇒ 不报；不在 ⇒ 报。
    """
    _proof_row(store, "0000", "probe-eq", "'probe-eq' does not depend on any axioms")
    _proof_row(store, "0001", "probe-eq", "'something_else' does not depend on any axioms")
    hits = _reported(store)
    assert "0000" not in hits
    assert "0001" in hits


# ============================================================ 上界本身要有断言点


def test_the_evidence_ceiling_is_registered_next_to_the_criterion():
    """    守卫：`selfreported_proof` 的证据上界必须写在判据旁边，且写明它到不了哪一层。

    为什么断言在源码文本上：这条修复的形态就是"如实登记边界"（`R2b-AN-2-A`的两个可选方向里的第二个）。如果没有任何断言看着它，"注释被删掉"与"注释还在"在测试里完全一样 ——
    那正是本仓反复登记的"零断言点"形态。

    判据的意图是"这段说明与判据在同一个函数里"，而不是"文件里某处有这句话"。所以这里不写死函数名，而是现算判据的落点：哪个函数体里同时出现了`selfreported`（判据用的读数）与
    `R2b-AN-2-A`（边界登记）。`draft/36` 的 T-5 把 `verify_all`（1175 行）拆成了 12 个 `_check_*`，这条判据因此在拆分后当场红过一次 —— 当时它写死
    `inspect.getsource(V.verify_all)`。写死函数名会让每一次重排都假红；现算落点则既保住意图、又经得起搬家。
    """
    import inspect

    def _holds_the_criterion(fn) -> bool:
        src = inspect.getsource(fn)
        return "selfreported" in src and "R2b-AN-2-A" in src

    candidates = [V.verify_all] + [getattr(V, n) for n in dir(V) if n.startswith("_check_")]
    holder = next((f for f in candidates if _holds_the_criterion(f)), None)
    assert holder is not None, (
        "没有任何函数把「判据」（引用 `selfreported`）与「边界登记」（`R2b-AN-2-A`）放在一起 —— "
        "`T-5` 的拆分把它俩分家了，或者登记被删了")
    src = inspect.getsource(holder)
    assert "证据上界" in src, "判据旁缺少'证据上界'那一段（上界到不了'依据属于本行'）"
    assert "自由文本" in src, "边界登记必须点明 `notes` 是可写自由文本"


def test_the_hyphen_underscore_control_would_be_lost_by_a_cross_check(store):
    """自校（守上面那条防误伤不是恒真）：同夹具把输出换成别的名字 ⇒ 必须报。

    证明"不许报"来自输入形态（输出里真有那个声明名的诊断），
    而不是来自"这一档夹具永远不报"。
    """
    _proof_row(
        store, "0000", "probe-eq", "'not_the_declared_one' does not depend on any axioms",
        notes="[formal] 检查器状态 'verified'；声明名 probe_eq；脚本 proofs/probe_eq.lean；imports=[]",
    )
    assert "0000" in _reported(store)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
