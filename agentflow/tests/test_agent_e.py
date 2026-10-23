"""智能体 E（`agent_e.py` + `tools/verify_tools.py`）的性质测试。

E 的核心是"产出证据，不产出结论"。这里锁住六条最容易悄悄做错的性质：

- 正常脚本能被登记，且 `code_hash` / `exit_code` 如实落库（可复现性绑定）；
- 脚本自报 `evidence_kind="proof"` 必须被降级（负控：让被判定的对象自己
  当判官，等于没有判官）；
- 崩溃 / 超时 / 无结论行一律 `inconclusive`（负控：不得把崩溃写成支持）；
- `Experiment` 的 schema 硬约束逐条生效（直接对 schema 构造，不经 E）；
- `evidence_for` 的三态：没查 ≠ 查了没有，且 `proved` 只在有 proof 级
  证据时为真（FC-22）；
- `check_formal` 的受控理由必须按具体理由分开：无后端 ⇒ `no_backend`，
  有后端但没给源码 ⇒ `no_script`（把两者折叠成 `checked is False`
  会把"本机有 Lean"报成"本机没有 Lean"）；
- 路径越界被拒绝。

全部离线、确定性：不联网、不依赖仓库里的任何外部文件，脚本都是现写现跑。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.agent_e import AgentE, ExperimentError, _derive
from agentflow.store import Store
from agentflow.tools import verify_tools as VT

TS = "2026-01-01T00:00:00+00:00"

#: 一个"诚实"的探针脚本：只报告观察结果，不声称证据等级之外的东西。
HONEST_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"grid": 64, "max_err": 1e-9},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""

#: 一个"越权"的探针脚本：它自己声称这是证明。数值实验拿不到 proof（FC-22）。
LYING_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "proof",
    "observations": {"points": 100000},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""


#: 只报结论与 `data`、不报 `bound`/`strategy`/`scaling` 的脚本（真机 T2 第 9 趟的形态）。
DATA_ONLY_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "data": {"n_vertices": 30, "degrees": [3], "girth": 8},
    "counterexample": None,
}))
"""


# ============================================================ 辅助


def write_script(store: Store, rel: str, body: str) -> str:
    """在工作区里写一个脚本，返回相对路径。

    必须落在 `store.root` 内（它同时是 E 的 workspace_root）：
    越界的路径应当被 E 拒绝，测试要用另一条路径专门验证那件事。
    """
    p = Path(store.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


@pytest.fixture(autouse=True)
def _lean_side_hard_off_is_lifted(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文件测的是「被保留的实现」，不是 E 的动作面。

    业主 2026-10-22 晚裁定把 E 的 Lean 侧写死关闭（`agent_e._support.E_LEAN_SIDE_HARD_OFF`）：
    动作面在 `run_experiment(method='formal')` 与 `check_formal` 的第一句就回
    `formal_moved_to_l`。那一层由 `tests/test_e_lean_side_is_hard_off.py` 的五条判据守。

    而本文件里这一批用例要守的是「代码先不删」那一半：`_record_formal` 与
    `_CheckFormal` 的实现体仍然逐字有用（L 的 `_CheckFormalL` 继承的就是它，
    `formal_tools` 也直接调同一份函数）。所以这里把那个字面量临时放开，让它们继续量
    被保留的那条路 —— 放开是显式的、每个用例结束后由 monkeypatch 还原。
    """
    from agentflow.agent_e import _support as SUP

    monkeypatch.setattr(SUP, "E_LEAN_SIDE_HARD_OFF", False, raising=True)


def make_e(store: Store, **cfg) -> AgentE:
    return AgentE(store, config=dict(cfg), workspace_root=store.root)


def add_experiment(store: Store, **kw) -> dict:
    """直接插一条合法的 experiments 行（供"证明过/没证明过"两态用）。"""
    fields = {
        "experiment_id": "0000",
        "claim": "某命题",
        "claim_key": "K",
        "method": "numeric",
        "evidence_kind": "cross_check",
        "result": "supports",
        "negation_kind": "not_proved",
        "created_at": TS,
    }
    fields.update(kw)
    row = S.Experiment(**fields)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    return row.to_dict()


# ============================================================ [1a] R-01：四条硬要求前移


#: 一个会留下脚印的脚本：跑起来就会创建 `code/ran.marker`。
#: 判据靠它证明"子进程到底起没起"（R-01 的全部意义就在这一步上）。
MARKER_PROBE = """
import json, pathlib
d = pathlib.Path("code")
d.mkdir(parents=True, exist_ok=True)
(d / "ran.marker").write_text("ran", encoding="utf-8")
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {"n": 3}, "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 3}, "strategy": "brute force", "scaling": {"3": 0.1},
}))
"""


def _marker(store: Store) -> Path:
    return Path(store.root) / "code" / "ran.marker"


def test_r01_a_bad_for_question_id_is_refused_before_the_subprocess(store):
    """R-01：`for_question_id` 不是 4 位号 ⇒ 脚本一次都不跑（真机：52 次失败 / 110.7 分钟 / 0 行）。

    旧口径下这条要等脚本跑完、`Experiment.validate()` 才拒 —— 十分钟的脚本白跑。
    """
    rel = write_script(store, "probes/marker.py", MARKER_PROBE)
    assert not _marker(store).exists()
    with pytest.raises(ExperimentError) as exc:
        make_e(store).run_experiment("某命题", "k-1", rel, for_question_id="q-1")
    assert "跑脚本之前" in str(exc.value), exc.value
    assert "4 位" in str(exc.value), exc.value
    assert not _marker(store).exists(), "子进程在参数不合格时**一次都不许起**"
    assert store.rows("experiments") == [], "被拒的实验不许留下行"


def test_r01_exhaustive_search_without_a_certificate_is_refused_before_the_subprocess(store):
    """R-01：穷举类不给 `certificate` ⇒ 同样在起子进程之前拒（证书是这类结论的全部说服力）。"""
    rel = write_script(store, "probes/marker2.py", MARKER_PROBE)
    with pytest.raises(ExperimentError) as exc:
        make_e(store).run_experiment("某命题", "k-2", rel, method="exhaustive_search")
    assert "跑脚本之前" in str(exc.value) and "certificate" in str(exc.value), exc.value
    assert not _marker(store).exists()

    # 反负控：把证书与边界都补齐 ⇒ 它照常跑起来（判据不是"一律拒"）
    out = make_e(store).run_experiment(
        "某命题", "k-2", rel, method="exhaustive_search",
        certificate={"kind": "enumeration_bound", "detail": "n<=3 全枚举"},
        search_bound={"B": "n<=3"})
    assert out["recorded"] is True, out
    assert _marker(store).exists(), "参数合格时子进程必须真的跑（否则这条反负控是空转）"


def test_r01_the_preflight_and_the_row_validation_are_one_judgement(store):
    """口径只有一处：`schema.experiment_preflight_problems` 与 `Experiment.validate()` 同源。

    两半：① 同一条坏参数在两处得到同一句话；② 行级 validate 仍然拦得住
    （前移不是"把判据搬走"）。preflight 覆盖不到的那些（结果/证书内容一致性）留在行级。
    """
    problems = S.experiment_preflight_problems(method="exhaustive_search", certificate=None)
    assert problems and "certificate" in problems[0], problems
    with pytest.raises(ValueError) as exc:
        S.Experiment(experiment_id="0000", claim="c", claim_key="k", method="exhaustive_search",
                     result="inconclusive", evidence_kind="heuristic",
                     negation_kind="not_searched_here", created_at=TS).validate()
    assert problems[0] in str(exc.value), (problems[0], str(exc.value))
    assert S.experiment_preflight_problems(method="numeric", certificate=None) == []
    assert S.experiment_preflight_problems(method="numeric", for_question_id="q-1"), \
        "4 位号那一条必须在 preflight 里（它与 certificate 那几条同一处口径）"


# ============================================================ [1] 正常路径


def test_run_experiment_records_row_with_hash_and_exit_code(store):
    """跑一个真实的小脚本 ⇒ 登记成功，`code_hash` 非空、`exit_code == 0`。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    out = make_e(store).run_experiment("对 n<=64 的网格 Spec K(m)=[-m,m]", "SpecK(m)=[-m,m]", rel)

    assert out["recorded"] is True
    assert out["exit_code"] == 0
    assert out["result"] == "supports"
    assert out["evidence_kind"] == "cross_check"
    assert out["negation_kind"] == "not_proved", "数值支持只能导致 not_proved（不是 disproved）"
    assert out["code_hash"], "给了 code_path 就必须有 code_hash"
    assert out["experiment_id"] == S.format_id(0)

    rows = store.rows("experiments")
    assert len(rows) == 1
    row = rows[0]
    # 哈希必须是那个文件内容的哈希（不是随便一个非空字符串）
    assert row["code_hash"] == hashlib.sha256((Path(store.root) / rel).read_bytes()).hexdigest()[:16]
    assert row["code_path"] == "probes/honest.py", "记录的必须是工作区内相对路径"
    # E-11：`observations` 里多了一条框架自己的读数 `conclusion_source`
    # （结论从哪来：`line` / `json_key` / `missing` / …）；脚本自报的那几个键逐字不动。
    assert {k: v for k, v in row["observations"].items() if k != "conclusion_source"} == {
        "grid": 64, "max_err": 1e-9}
    assert row["observations"]["conclusion_source"] == "line", row["observations"]
    assert row["created_by"] == "agent-E"


def test_the_script_data_is_kept_and_a_missing_bound_is_named(store):
    """判据（`draft/39` §6.27 的 D38）：脚本自报的 `data` 要进台账；没有界/策略/成本曲线要说出来。

    真机读数（T2 第 9 趟 `p6k`）：脚本打的是
    `REPRO_RESULT: {"result": "supports", "counterexample": null, "data": {…}}` ——
    `data`（这次核的是哪个对象）不在读侧认识的键里 ⇒ 台账 `observations` 空、
    `search_bound` 空（14 条实验里 0 条有界），"核的是哪个图"只留在
    `out/experiments/*.log` 里 —— 于是"同一份读数被当成几份证据"这件事在台账上不可见。
    """
    rel = write_script(store, "probes/data_only.py", DATA_ONLY_PROBE)
    out = make_e(store).run_experiment("核一个具体的图", "data-only", rel, method="numeric")

    row = store.rows("experiments")[0]
    assert row["observations"]["data"] == {"n_vertices": 30, "degrees": [3], "girth": 8}, row
    assert "没有留下界/策略/成本曲线" in out["notes"], out["notes"]


def test_the_same_data_supporting_another_claim_is_named(store):
    """判据（D39）：同脚本 + 同 `data` + 另一条 claim ⇒ 行里点名"同一份证据"。

    真机读数（T2 第 9 趟）：一个脚本被派 9 次、claim 分别是 W(2)/W(3)/W(4)…，
    而 9 条 `data` 逐字相同（30 顶点 / 度 3 —— 始终是同一个图）⇒ 台账上九条 `supports`，
    手稿把它们当九份独立证据引。负控：同一条 claim 上重跑（复现）不点这个名。
    """
    rel = write_script(store, "probes/data_only2.py", DATA_ONLY_PROBE)
    e = make_e(store)
    first = e.run_experiment("W(2) 那条断言", "gq-w2", rel, method="numeric")
    second = e.run_experiment("W(3) 那条断言", "gq-w3", rel, method="numeric")
    third = e.run_experiment("W(3) 那条断言（复现）", "gq-w3", rel, method="numeric")

    assert "同一份证据" not in first["notes"], first["notes"]
    assert "同一份证据" in second["notes"], second["notes"]
    assert "exp:0000" in second["notes"], second["notes"]
    assert "同一份证据" not in third["notes"], "同一条 claim 上的复现是正当的"


def test_code_hash_is_reused_from_verify_tools_not_reimplemented(store):
    """哈希只有一份实现：工具的 `verify.code_hash` 与 E 写进表的值必须一致。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    e = make_e(store)
    got = e.tools.call("verify.code_hash", path=rel)
    assert got.ok
    out = e.run_experiment("同一份脚本", "same-script", rel)
    assert got.data["code_hash"] == out["code_hash"] == VT.code_hash(Path(store.root) / rel)


# ============================================================ [2] 负控：自报 proof


def test_script_self_reported_proof_is_downgraded_and_noted(store):
    """负控：脚本自报 `evidence_kind="proof"` ⇒ 降级为 `cross_check`，且 notes 记录这次越权。

    FC-22 的运行期那一半：schema 拦得住"存进去的谎话"，拦不住"脚本以为自己证明了"。
    两半都要有 —— 只靠 schema 的话，脚本的越权会被静默改写成 cross_check 而不留痕，
    于是没人能解释"为什么这条记录的等级比脚本里写的低"。
    """
    rel = write_script(store, "probes/lying.py", LYING_PROBE)
    out = make_e(store).run_experiment("数值实验不得自称证明", "selfclaimed-proof", rel, method="numeric")

    assert out["evidence_kind"] == "cross_check", "脚本自报 proof 必须被拒绝"
    assert out["result"] == "supports"
    assert "proof" in out["notes"]
    assert "降级" in out["notes"] and "cross_check" in out["notes"]
    # 落库的那一行也必须是降级后的值（不能只在返回值里降级）
    assert store.rows("experiments")[0]["evidence_kind"] == "cross_check"


def test_formal_method_keeps_proof_only_because_schema_requires_verifier_output(store):
    """反误伤：`method="formal"` 时脚本自报 proof 不被降级为 cross_check。

    注意：这个用例在 `P-8` 之前断言的是"E 的 run_experiment 不产生 verifier_output，
    所以这条记录仍会因'proof 必须有检查器输出'被 schema 拒"。那句话描述的是
    缺陷本身（`P-8`：形式化路径一个证据形状字段都不传 ⇒ E 永远登记不了一条
    proof 级实验），不是判据。修好之后形式化路径改走检查器
    （正控见 `tests/test_agent_e_formal_path.py`），所以这里断言的是两件仍然成立的事：

    1. 降级规则只针对计算类方法（直接量 `_derive`，原判据逐字保留）；
    2. `method="formal"` 而产物不是 `.lean` ⇒ 当场拒绝，且一行都不写
       —— 这不是放宽 FC-22，而是把"形式化路径的输入"钉死。
    """
    rel = write_script(store, "probes/lying.py", LYING_PROBE)
    lying_stdout = "REPRO_RESULT: " + json.dumps(
        {"result": "supports", "evidence_kind": "proof", "observations": {},
         "counterexample": None, "negation_kind": "not_proved"}
    )
    # ---- 1. 降级规则只针对计算类方法（`_derive` 是唯一权威表述）
    assert _derive(0, lying_stdout, method="numeric")["evidence_kind"] == "cross_check"
    assert _derive(0, lying_stdout, method="symbolic")["evidence_kind"] == "cross_check"
    assert _derive(0, lying_stdout, method="exhaustive_search")["evidence_kind"] == "cross_check"
    assert _derive(0, lying_stdout, method="formal")["evidence_kind"] == "proof"
    # ---- 2. 非 .lean 产物在形式化路径上被拒绝（不是"跑完再让 schema 拒"）
    with pytest.raises(ExperimentError) as ei:
        make_e(store).run_experiment("形式化方法", "formal-claim", rel, method="formal")
    assert ".lean" in str(ei.value)
    assert store.rows("experiments") == [], "被拒绝的形式化实验不得留下任何行"


# ============================================================ [3] 负控：崩溃 / 超时 / 无结论


def test_crash_is_inconclusive_not_support(store):
    """负控：`exit_code != 0` ⇒ `inconclusive` + `no_local_evidence`（崩溃不得写成支持）。"""
    rel = write_script(
        store,
        "probes/crash.py",
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'cross_check'}))\n"
        "raise SystemExit(3)\n",
    )
    out = make_e(store).run_experiment("崩溃脚本", "crash", rel)
    assert out["exit_code"] == 3
    assert out["result"] == "inconclusive", "崩溃被写成了正面结论"
    assert out["negation_kind"] == "no_local_evidence"
    # 即使脚本已经打印了 supports，也不能被采信：exit_code 优先
    assert store.rows("experiments")[0]["result"] == "inconclusive"


def test_missing_repro_result_line_is_inconclusive_with_notes(store):
    """脚本不打印 `REPRO_RESULT` 行 ⇒ `inconclusive` + `no_local_evidence`，notes 说明原因。"""
    rel = write_script(store, "probes/silent.py", "print('nothing structured here')\n")
    out = make_e(store).run_experiment("没有结构化结论", "silent", rel)
    assert out["result"] == "inconclusive"
    assert out["negation_kind"] == "no_local_evidence"
    assert "未给出结构化结论" in out["notes"]
    assert out["exit_code"] == 0, "脚本自己是正常退出的 —— 失败的是'没有结论'，不是'跑崩了'"


def test_broken_json_conclusion_is_inconclusive_and_attributed(store):
    """`REPRO_RESULT` 行不是合法 JSON ⇒ 不认这条结论，且 notes 归因到"JSON 坏了"。

    FC-15：`没写结论` 与 `写坏了结论` 必须能分开计数 —— 它们的修法完全不同。
    """
    rel = write_script(store, "probes/badjson.py", "print('REPRO_RESULT: {not json')\n")
    out = make_e(store).run_experiment("坏 JSON", "badjson", rel)
    assert out["result"] == "inconclusive"
    assert "JSON" in out["notes"]
    assert "未给出结构化结论" not in out["notes"], "这两种失败必须可归因分离"


def test_a_conclusion_printed_as_a_json_key_is_read_and_recorded(store):
    """回归夹具（`draft/37` §126）：把结论打印成 「JSON 键」的那种形状也要读出来。

    真机读数（T2 第 4 趟）：主控写的那份 `scripts/rmk.py` stdout
    逐字是 `{ "REPRO_RESULT": { "result": "refutes", "claim": ... } }`
    —— 它「给出了结论」，只是写成"JSON 对象里的一个键"，而行首形态的判据认不出它 ⇒ 那条实验落成 `inconclusive`，稿子拿不到它自己算出来的证否。

    这条判据钉两件事：① 读得出来（`result=refutes` 且带反例）；② 「留痕」（notes 里写明这次用的是 JSON 键形态，因为协议正身是单独一行）。"""
    rel = write_script(store, "probes/keyform.py",
                       "import json\n"
                       "print(json.dumps({'REPRO_RESULT': "
                       "{'result': 'refutes', 'counterexample': {'m': 3, 'k': 3}}}))\n")
    out = make_e(store).run_experiment("键形态结论", "keyform", rel)
    assert out["result"] == "refutes", out
    assert out["negation_kind"] == "disproved", out
    # 反例落在「实验行」上（`run_experiment` 的返回值只给结论面）
    assert store.rows("experiments")[0]["counterexample"] == {"m": 3, "k": 3}, \
        store.rows("experiments")[0]
    assert "JSON 键形态" in out["notes"], out["notes"]


def test_two_conclusion_shapes_at_once_are_refused(store):
    """负控（E-11 改口径后重写）：两种形态同时出现且内容不一致 ⇒ 仍然不许当结论用。

    旧口径是"多于一行 ⇒ 整条不认"；新口径（主控裁定）是"取最后一份但按没结论记"：
    两端都不许 —— 既不许读成"没打印"，也不许读成"有结论"（那正是 E-11 要治的形态）。
    判据三半：`result` 仍是 `inconclusive`；行上 `conclusion_source == "multiple"`；
    逐字留痕里说清"内容不同 ⇒ 取最后一份"与"前几份与它不一致"。
    """
    rel = write_script(store, "probes/twoshapes.py",
                       "import json\n"
                       "print('REPRO_RESULT: ' + json.dumps({'result': 'supports'}))\n"
                       "print(json.dumps({'REPRO_RESULT': {'result': 'refutes'}}))\n")
    out = make_e(store).run_experiment("两种形态", "twoshapes", rel)
    assert out["result"] == "inconclusive", out
    assert "内容不同" in out["notes"] and "取" in out["notes"], out["notes"]
    obs = store.rows("experiments")[0]["observations"]
    assert obs["conclusion_source"] == "multiple", obs
    assert obs["last_result_seen"] == "refutes", obs


def test_e11_multiple_identical_conclusions_are_accepted_with_a_reading(store):
    """E-11 正控：脚本把同一份结论打印多次 ⇒ 认它，且读数里写明"有 2 份、内容一致"。"""
    rel = write_script(store, "probes/twice.py",
                       "import json\n"
                       "line = 'REPRO_RESULT: ' + json.dumps({'result': 'supports'})\n"
                       "print(line)\nprint(line)\n")
    out = make_e(store).run_experiment("重复打印", "twice", rel)
    assert out["result"] == "supports", out
    assert "打印了 2 次" in out["notes"], out["notes"]
    assert store.rows("experiments")[0]["observations"]["conclusion_source"] == "line"


def test_e11_a_missing_protocol_line_has_its_own_reading(store):
    """E-11：`exit=0` 却没打协议行 ⇒ "脚本没按协议打印"是独立读数，不是"实验没结论"。

    反负控同时钉住三档两两不同（`missing` / `bad_json` / `line`）——
    折回同一档就等于这条读数白加。
    """
    rel = write_script(store, "probes/silent.py", "print('done')\n")
    out = make_e(store).run_experiment("没打协议行", "silent", rel)
    assert out["result"] == "inconclusive", out
    assert store.rows("experiments")[0]["observations"]["conclusion_source"] == "missing"

    bad = write_script(store, "probes/badjson.py", "print('REPRO_RESULT: {not json')\n")
    make_e(store).run_experiment("坏 JSON", "badjson", bad)
    assert store.rows("experiments")[-1]["observations"]["conclusion_source"] == "bad_json"

    good = write_script(store, "probes/good.py",
                        "import json\nprint('REPRO_RESULT: ' + json.dumps({'result': 'supports'}))\n")
    make_e(store).run_experiment("正常", "good", good)
    seen = {str(r["observations"].get("conclusion_source")) for r in store.rows("experiments")}
    assert seen == {"missing", "bad_json", "line"}, seen


def test_timeout_is_inconclusive_and_reason_is_visible(store):
    """超时（`time.sleep` + 小 timeout）⇒ `inconclusive`，且原因在 notes 里可见。"""
    rel = write_script(store, "probes/slow.py", "import time\ntime.sleep(30)\n")
    out = make_e(store).run_experiment("超时脚本", "slow", rel, timeout=1)
    assert out["result"] == "inconclusive"
    assert out["negation_kind"] == "no_local_evidence"
    assert out["exit_code"] is None, "超时的进程是被杀掉的，没有正常退出码"
    assert "超时" in out["notes"]
    assert out["runtime_sec"] is not None and out["runtime_sec"] < 20


def test_path_escaping_is_refused(store, tmp_path):
    """负控：`script_path` 越出工作区 ⇒ 拒绝（相对越界与绝对路径都拒）。"""
    outside = Path(store.root).parent / "outside_probe.py"
    outside.write_text(HONEST_PROBE, encoding="utf-8")
    e = make_e(store)
    with pytest.raises(ExperimentError) as ei:
        e.run_experiment("越界脚本", "escape-rel", "../outside_probe.py")
    assert "越出工作区" in str(ei.value)
    with pytest.raises(ExperimentError):
        e.run_experiment("越界脚本", "escape-abs", str(outside))
    assert store.rows("experiments") == [], "被拒绝的实验不得留下任何行"


def test_missing_script_is_refused_before_any_write(store):
    """脚本不存在 ⇒ 当场抛（不是登记一条 inconclusive —— 那会把'没跑'记成'跑了没结论'）。"""
    with pytest.raises(ExperimentError):
        make_e(store).run_experiment("不存在的脚本", "missing", "probes/nope.py")
    assert store.rows("experiments") == []


# ============================================================ [4] schema 硬约束负控（不经 E）


def _experiment(**kw) -> S.Experiment:
    fields = {
        "experiment_id": "0000",
        "claim": "c",
        "claim_key": "k",
        "method": "numeric",
        "created_at": TS,
    }
    fields.update(kw)
    return S.Experiment(**fields)


def test_schema_rejects_numeric_experiment_claiming_proof():
    """负控：`method="numeric"` + `evidence_kind="proof"` ⇒ `validate()` 抛（FC-22 的机械落地）。"""
    row = _experiment(method="numeric", evidence_kind="proof", verifier_output="fake checker output")
    with pytest.raises(ValueError) as ei:
        row.validate()
    assert "不得声称" in str(ei.value)


def test_schema_accepts_formal_proof_with_verifier_output():
    """防误伤：`method="formal"` + `evidence_kind="proof"` + 非空 `verifier_output` ⇒ 通过。

    `R2-AN-2` 的夹具处置：这条 `verifier_output` 从前写的是 `"Lean 4: no goals"`
    —— 那种输出里没有绑定被检查声明名的诊断，于是它是一句假话
    （行标着 `proof`，而依据读不出来）。它今天不经过 `verify_all`（本用例只调
    `row.validate()`），所以变严的审计判据并没有红它；但夹具说假话这件事本身要改
    （`draft/28` §41.4：改夹具，不许放宽判据）。这里换成检查器真跑过时打印的形态：
    `'<声明名>' does not depend on any axioms`（声明名 = 本行的 `verifier_subject_key`）。
    """
    row = _experiment(
        method="formal",
        evidence_kind="proof",
        verifier_output="'k' does not depend on any axioms",
        # 新硬约束（来自对 DeepMath 的观摩）：检查器输出必须绑定到它管的那个命题。
        # 没有它时，"把命题 A 的检查器输出粘到命题 B 的行上"在结构上合法。
        verifier_subject_key="k",
        result="supports",
        negation_kind="not_proved",
        exit_code=0,
    )
    row.validate()  # 不抛即通过


def test_schema_rejects_refutes_without_counterexample():
    """负控：`result="refutes"` 但 `counterexample` 为空 ⇒ 抛（证否必须可复核）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(result="refutes", counterexample=None, negation_kind="disproved").validate()
    assert "counterexample" in str(ei.value)


def test_schema_rejects_refutes_with_wrong_negation_kind():
    """负控：`result="refutes"` 且 `negation_kind != "disproved"` ⇒ 抛（FC-25）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(result="refutes", counterexample={"m": 7}, negation_kind="not_proved").validate()
    assert "disproved" in str(ei.value)


def test_schema_rejects_supports_without_negation_kind():
    """负控：`result="supports"` 且 `negation_kind=None` ⇒ 抛（三种否定必须分类）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(result="supports", negation_kind=None).validate()
    assert "negation_kind" in str(ei.value)


def test_schema_rejects_code_path_without_code_hash():
    """负控：`code_path` 非空但 `code_hash` 空 ⇒ 抛（没有哈希的"可复现"只是口号）。"""
    with pytest.raises(ValueError) as ei:
        # 其余字段都填成合法的，好让校验走到 code_hash 那一条
        # （否则会先被 result/negation_kind 的约束拦下，测到的就不是这条规则了）
        _experiment(result="supports", negation_kind="not_proved", code_path="probes/x.py", code_hash="").validate()
    assert "code_hash" in str(ei.value)


def test_schema_rejects_crash_recorded_as_support():
    """负控：`exit_code=1` 且 `result="supports"` ⇒ 抛（崩溃不得被写成支持）。"""
    with pytest.raises(ValueError) as ei:
        _experiment(exit_code=1, result="supports", negation_kind="not_proved").validate()
    assert "inconclusive" in str(ei.value)


# ============================================================ [5] evidence_for 三态与 FC-22


def test_evidence_for_three_states(store):
    """三态：没查（`checked=False`）/ 查了没有（`checked=True, experiments=[]`）/ 查到了。"""
    e = make_e(store)
    not_checked = e.evidence_for()
    assert not_checked["checked"] is False
    assert not_checked["experiments"] == []
    assert not_checked["best_evidence_kind"] is None
    # errors-1（登记在 draft/28）：三态里 proved 在"没查"这一支必须是 None，
    # 不是 False —— 否则只读 proved 的调用方分不清"没查"与"查了没有 proof 级证据"。
    assert not_checked["proved"] is None, not_checked
    assert "没查" in not_checked["reason"]

    none_found = e.evidence_for("不存在的命题键")
    assert none_found["checked"] is True
    assert none_found["experiments"] == []
    assert none_found["best_evidence_kind"] is None
    assert none_found["proved"] is False
    assert "没有" in none_found["reason"], "必须是'查了、没有'的语义"

    add_experiment(store, claim_key="K", evidence_kind="cross_check")
    found = e.evidence_for("K")
    assert found["checked"] is True
    assert len(found["experiments"]) == 1
    assert found["best_evidence_kind"] == "cross_check"
    assert found["proved"] is False, "cross_check 永远不算已证明"
    # FC-10：结果分档计数，不许只给一个布尔
    assert found["result_counts"] == {"supports": 1, "refutes": 0, "inconclusive": 0}
    assert found["negation_counts"]["not_proved"] == 1


def test_evidence_for_proved_only_with_proof_level_experiment(store):
    """`proved` 只在存在 `evidence_kind == "proof"` 的实验时为真（FC-22 的 gate）。"""
    e = make_e(store)
    add_experiment(store, experiment_id="0000", claim_key="K", method="numeric", evidence_kind="cross_check")
    add_experiment(store, experiment_id="0001", claim_key="K", method="symbolic", evidence_kind="heuristic")
    assert e.evidence_for("K")["proved"] is False

    add_experiment(
        store,
        experiment_id="0002",
        claim_key="K",
        method="formal",
        evidence_kind="proof",
        # `R2-AN-2` 的夹具处置：从前是 `"Lean 4: no goals"` —— 没有绑声明名的诊断，
        # 这句话不足以支撑 `proof` 级（依据读不出来）。本用例只查 `evidence_for`
        # 的判定与列出，变严的审计判据没有红它，但假话要改成检查器真跑过的形态。
        verifier_output="'K' does not depend on any axioms",
        # 新硬约束：检查器输出必须绑定到它管的命题（否则能把 A 的输出贴到 B 上）
        verifier_subject_key="K",
        exit_code=0,
    )
    got = e.evidence_for("K")
    assert got["proved"] is True
    assert got["best_evidence_kind"] == "proof"
    assert len(got["experiments"]) == 3, "三种等级的实验都要被列出（不是只列最强的）"


def test_evidence_for_filters_by_question_id(store):
    """`for_question_id` 只在精确相等时命中：不同问题的实验不得互相背书。"""
    add_experiment(store, experiment_id="0000", claim_key="K", for_question_id="0001")
    add_experiment(store, experiment_id="0001", claim_key="K", for_question_id="0002")
    e = make_e(store)
    assert len(e.evidence_for("K")["experiments"]) == 2
    only_1 = e.evidence_for(for_question_id="0001")
    assert [r["experiment_id"] for r in only_1["experiments"]] == ["0000"]
    assert e.evidence_for(for_question_id="0009")["experiments"] == []


# ============================================================ [6] check_formal 的三态


def test_check_formal_without_backend_is_not_checked_not_failed(store, monkeypatch):
    """无后端 ⇒ `checked=False, reason="no_backend"`，不是 `verified=False`。

    把"没验证"与"验证没过"折叠成同一个 `False`，下游就会把"本环境没有证明检查器"
    读成"这个命题被证伪了" —— 这正是本项目反复踩到的三态坑。
    """
    monkeypatch.setattr(
        VT,
        "detect_verifier",
        lambda: {"checked": True, "available": [], "available_names": [], "reason": "（测试注入：无检查器）"},
    )
    got = make_e(store).check_formal("1 + 1 = 2")
    assert got["checked"] is False
    assert got["reason"] == "no_backend"
    assert got["verified"] is None, "没验证必须是 None，不能是 False"
    assert got["verifier_output"] == ""
    # 反误伤：这个返回值不能被读成"验证失败"
    assert got["reason"] != "verification_failed"


def test_check_formal_with_backend_and_no_source_is_no_script_not_no_backend(store, monkeypatch):
    """有后端 + 调用方没给源码 ⇒ `no_script`，不是 `no_backend`。

    `checked=False` 有两种来源：环境侧"没查成"（`no_backend` / `timeout` /
    `tool_crashed`）与调用方侧"没给源码"（`no_script`）。两者的处置完全不同
    —— 前者要去装检查器，后者要把参数补上。把判据写成 `checked is False`
    就会把后者读成前者：那正是"本机装了 Lean，却被报成没有 Lean"这个
    安静的错误（自检 `agent_e.selftest` 里曾逐字犯过）。
    """
    monkeypatch.setattr(
        VT, "detect_verifier",
        lambda: {"checked": True, "available": [{"name": "lean", "path": "lean",
                                                 "version": "Lean 4.7.0"}],
                 "available_names": ["lean"], "reason": "（测试注入：有检查器）"},
    )
    got = make_e(store).check_formal("1 + 1 = 2")
    assert got["reason"] == "no_script", got
    assert got["reason"] != "no_backend", "有后端时不许报成'环境里没有检查器'"
    assert got["checked"] is False
    assert got["verified"] is None, "没查成必须是 None，不能是 False"
    assert "没有给" in got["detail"] and "script_path" in got["detail"]


def test_check_formal_with_backend_and_a_source_really_calls_the_bridge(store, monkeypatch):
    """正控：有后端 + 给了源码 ⇒ 真的转发给 `formalgw.check_lean`（不提前收口）。

    与上一条合起来才说明 `no_script` 是"源码缺席"这一支的结论，而不是
    任何一次调用的兜底结论。替身打在 `formalgw` 上（工具层是在函数体里
    惰性 import 它的 —— 顶层互引会成环），所以打断的是真正的转发目标。
    """
    from agentflow import formalgw as FG

    seen: dict = {}

    def _spy(source, *, name, imports, timeout_sec, source_path=None):
        seen.update(source=source, name=name, imports=imports,
                    timeout_sec=timeout_sec, source_path=source_path)
        return {"status": "verified", "reason": "（测试注入：假结论）",
                "evidence": {"checked": True, "proved": True, "evidence_kind": "proof"}}

    monkeypatch.setattr(
        VT, "detect_verifier",
        lambda: {"checked": True, "available": [{"name": "lean", "path": "lean",
                                                 "version": "Lean 4.7.0"}],
                 "available_names": ["lean"], "reason": "（测试注入：有检查器）"},
    )
    monkeypatch.setattr(FG, "check_lean", _spy)
    src = "theorem one_plus_one : 1 + 1 = 2 := rfl\n"
    got = make_e(store).check_formal("1 + 1 = 2", source=src, name="one_plus_one",
                                     imports=(), timeout_sec=7)
    assert seen["source"] == src and seen["name"] == "one_plus_one"
    assert seen["imports"] == () and seen["timeout_sec"] == 7.0
    assert seen["source_path"] is None
    assert got["reason"] == "verified" and got["verified"] is True
    assert got["checked"] is True


# ============================================================ [7] 事务性与事件日志


def test_one_run_writes_exactly_one_row_and_one_event(store):
    """一次 `run_experiment` 只产生一行 `experiments`，且 `events.jsonl` 有对应 upsert。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    before = len(store.read_events())
    make_e(store).run_experiment("一次实验", "one-row", rel)
    after = store.read_events()

    assert len(store.rows("experiments")) == 1
    new = after[before:]
    upserts = [e for e in new if e.get("op") == "upsert" and e.get("table") == "experiments"]
    assert len(upserts) == 1, f"应当恰好有一条 experiments upsert，实际 {len(upserts)}"
    assert upserts[0]["row"]["claim_key"] == "one-row"
    assert upserts[0]["actor"] == "agent-E"
    # alloc_id 也必须留下痕迹（ID 发号与建行同事务，是可审计的）
    assert any(e.get("table") == "counters" for e in new)


def test_second_run_allocates_the_next_id(store):
    """两次实验拿到两个不同的 ID（ID 发号在持锁事务内，不许撞号）。"""
    rel = write_script(store, "probes/honest.py", HONEST_PROBE)
    e = make_e(store)
    a = e.run_experiment("第一次", "k1", rel)
    b = e.run_experiment("第二次", "k2", rel)
    assert {a["experiment_id"], b["experiment_id"]} == {S.format_id(0), S.format_id(1)}
    assert len(store.rows("experiments")) == 2


# ============================================================ [8] 工具层


def test_verify_tools_registered_with_honest_side_effects(store):
    """工具层的三个新工具必须注册，且 `side_effect` 如实声明（FC-07）。

    为什么 `verify.run_experiment` 的角色不含 `H`（这条断言后来被收紧了）：原断言写的是"三个工具的角色都是 {E,F,G,H}"，
    那编码的是一条更弱的规则"角色的声明只要包含需要它的人就行"；
    但 `H` 是只读角色（`agentflow.tools.READ_ONLY_ROLES`）：审校者若手里有"跑实验并落库"的能力，它就同时是"发现者"与"执行者"，
    于是"发现问题"与"掩盖问题"在结构上无法区分。

    实测过这个漏洞真的存在：`table.*` / `fs.*` 把 `write_local` 工具声明给了全部角色，按角色装配出来的 H 工具面里出现了 `table.update`。现在的防线有两道：①
    工具声明本身正确（本断言守它）；② `ToolRegistry.for_role` 对只读角色结构性剥掉所有写工具（`test_tools_base.py` 守它）。"""
    e = make_e(store)
    names = set(e.tools.names())
    assert {"verify.run_experiment", "verify.evidence_for", "verify.list_experiments"} <= names
    # 保留已有的三个工具（有人在并行做验收测试，会用到）
    assert {"verify.code_hash", "verify.detect_verifier", "verify.check_formal"} <= names
    assert e.tools.get("verify.run_experiment").side_effect == "write_local"
    assert e.tools.get("verify.evidence_for").side_effect == "read"
    assert e.tools.get("verify.list_experiments").side_effect == "read"
    # 只读工具：需要它的角色都能拿到
    for name in ("verify.evidence_for", "verify.list_experiments"):
        assert set(e.tools.get(name).roles) == {"E", "F", "G", "H"}, "角色即权限面"
    # 写工具：只读角色 H 被排除（否则"审校者能改数据"）
    assert set(e.tools.get("verify.run_experiment").roles) == {"E", "F", "G"}, (
        "verify.run_experiment 是 write_local，角色声明里不能有只读角色 H。"
        "（`for_role` 也会拦下它，但声明本身必须对 —— 只靠拦截会让声明与事实长期不一致）"
    )


def test_run_experiment_tool_goes_through_the_same_implementation(store):
    """工具入口与 `AgentE.run_experiment` 必须写出同一种记录（不许两套口径）。"""
    rel = write_script(store, "probes/keyed.py", HONEST_PROBE)
    reg = make_e(store).tools
    got = reg.call("verify.run_experiment", claim="经工具跑的实验", claim_key="via-tool", script_path=rel)
    assert got.ok, got.error
    assert got.data["recorded"] is True
    assert got.data["evidence_kind"] == "cross_check"

    rows = store.rows("experiments")
    assert len(rows) == 1
    assert rows[0]["claim_key"] == "via-tool"
    assert rows[0]["code_hash"] == VT.code_hash(Path(store.root) / rel)
    assert rows[0]["created_by"] == "agent-E"

    ev = reg.call("verify.evidence_for", claim_key="via-tool")
    assert ev.ok and ev.data["checked"] is True and len(ev.data["experiments"]) == 1
    listed = reg.call("verify.list_experiments")
    assert listed.ok and listed.data["total"] == 1


def test_verify_store_tools_fail_closed_when_not_wired():
    """FC-08 负控：未接线（没有 store）时必须显式失败，不得返回空数据。

    "我们没接上存储"与"存储里没有实验结果"在调用方眼里必须长得不一样 ——
    否则"没查"会被读成"查了没有"，而后者是一个会被引用的结论。
    """
    from agentflow.tools.base import ToolRegistry

    empty = ToolRegistry(name="no-store")
    VT.register(empty, store=None, root=None)
    for name in ("verify.run_experiment", "verify.evidence_for", "verify.list_experiments"):
        res = empty.call(
            name,
            role="E",  # `P-14`：这张表代表 E（`verify.*` 的写侧含 E）
            **{
                "verify.run_experiment": {"claim": "c", "claim_key": "k", "script_path": "s.py"},
                "verify.evidence_for": {"claim_key": "k"},
                "verify.list_experiments": {},
            }[name],
        )
        assert res.ok is False, f"{name} 未接线时返回了成功"
        assert res.meta.get("kind") == "not_wired"
        assert res.data is None, "未接线不得返回空数据"


# ============================================================ [9] 自检


def test_module_selftest_passes_offline():
    """模块自检必须能在不联网、不依赖外部文件的情况下跑通（返回 0 个失败）。

    刻意不复用 `store` 夹具：自检自己建临时工作区，因此这里能顺带证明
    "它不依赖测试环境的任何既有状态"。`agent_e.selftest()` 的流程是
    正常脚本 → 自报 proof → 崩溃 → 无结论 → 路径越界 → 超时 → 三态 → 事务性 →
    check_formal（无后端 ⇒ `no_backend`；有后端且没给源码 ⇒ `no_script`，
    有后端且给了源码 ⇒ 真的跑一次检查器）。
    """
    from agentflow import agent_e

    assert agent_e.selftest() == 0


# ============================================================ 采自本地先例的两条硬约束
#
# 这两条来自对本地先例的只读观摩（`draft/14-…-Danus.md`、`draft/15-…-dsh数学模式与DeepMath.md`）：
# 它们各有一个我们结构上真的缺的东西，且成本很小、不改变我们的架构。


def test_proof_requires_verifier_subject_key_matching_the_claim(store):
    """验证工具必须与上下文绑定（采自 DeepMath）。

    DeepMath 的做法是"验证工具绑定上下文，越界调用直接 raise"。
    我们此前 `verifier_output` 是一个自由字符串 —— 于是把"命题 A 的检查器输出"
    粘到"命题 B 的记录行"上，结构上完全允许，而且没有任何地方会报错。
    这不是理论风险：任何"批量跑一堆检查、再批量写记录"的实现都会踩到它。
    """
    store.init()
    base = dict(experiment_id="0000", claim="P", claim_key="P", method="formal",
                evidence_kind="proof",
                # `R2-AN-2` 的夹具处置：从前是 `"Lean 4: no goals"`（没有绑声明名的
                # 诊断 ⇒ 一句假话）。本用例只查 schema 的硬约束 2b，
                # 变严的审计判据没有红它，但夹具仍然要写成检查器真跑过的形态。
                verifier_output="'P' does not depend on any axioms",
                result="supports", negation_kind="not_proved", created_at=TS)
    # 缺 verifier_subject_key ⇒ 拒
    with pytest.raises(ValueError, match="verifier_subject_key"):
        S.Experiment(**base).validate()
    # 管的是别的命题 ⇒ 拒
    with pytest.raises(ValueError, match="不一致"):
        S.Experiment(**{**base, "verifier_subject_key": "Q"}).validate()
    # 管的就是本命题 ⇒ 过
    S.Experiment(**{**base, "verifier_subject_key": "P"}).validate()


def test_exhaustive_search_requires_a_certificate_and_a_bound(store):
    """搜索类结论必须携带证书（采自 dsh 数学模式）。

    穷举/可满足性这类结论的说服力全部来自"证书"：
    "在 B 内没有反例"若不说清 B 是什么、怎么搜的，就只是一句无法复核的话 ——
    它看起来是结论，实际上是一个没有定义域的断言。
    """
    store.init()
    base = dict(experiment_id="0000", claim="范围内无反例", claim_key="no-ce",
                method="exhaustive_search", evidence_kind="cross_check",
                result="supports", negation_kind="not_proved", created_at=TS)
    with pytest.raises(ValueError, match="certificate"):
        S.Experiment(**base).validate()
    # 有证书但没边界 ⇒ 仍拒（证书脱离边界没有意义）
    with pytest.raises(ValueError, match="search_bound"):
        S.Experiment(**{**base, "certificate": {"kind": "enumeration_bound"}}).validate()
    # 证书 + 边界 ⇒ 过
    S.Experiment(**{
        **base,
        "certificate": {"kind": "enumeration_bound", "detail": {"box": 3}},
        "search_bound": {"m": [3, 4, 5], "radius": 3},
    }).validate()


def test_numeric_method_still_does_not_need_a_certificate(store):
    """防误伤：`numeric`（连续采样）不是搜索类，不该被要求给证书。

    把"必须给证书"扩大到 `numeric` 会逼着实现者编一个没有意义的 `search_bound`，
    那会让这条约束退化成填表练习。
    """
    store.init()
    S.Experiment(experiment_id="0000", claim="c", claim_key="k", method="numeric",
                 evidence_kind="cross_check", result="supports", negation_kind="not_proved",
                 created_at=TS).validate()


# ============================================================ `R2-AN-3`：docstring vs 常量
#
# 缺陷形态：模块 docstring 第 3 条（"没查成"）只列了四项，而 `_NOT_CHECKED_REASONS`
# 是五项（少 `source_unreadable` 与 `param_error`）—— 同一份文件里两处互相矛盾，
# 而没有任何一条测试会因此变红（`draft/28` §40.3 的 C1/C3 读数）。
# 修法是把"docstring 里那一档"做成一个机器可核的读法（`_docstring_not_checked_reasons`），
# 导入期断言 + 下面两条用例共用它（判据本体只有一处，`FC-03`）。
#
# 这两条用例守两个方向：正控（当前 docstring 必须覆盖常量）与负控
# （把 docstring 换回改前的四项 ⇒ 判据必须红）。负控是内存注入，
# 不动文件 —— 注入是否生效由它自己核对（改前文本与当前 docstring 必须不同，
# 且改前文本正是 `draft/28` §40.3 记的那一版）。

#: 改前（`R2-AN-3` 修法之前）docstring 的第 3 条，逐字取自备份
#: `temp/batchS-agent_e.py.bak`。它只列四项。
_DOCSTRING_ITEM3_BEFORE = (
    "3. 没查成（`timeout` / `import_unavailable` / `no_backend` / `tool_crashed`）⇒ 同上，\n"
    "   且 `notes` 里写明是哪一种。三态纪律：没查成绝不等于查了通过。\n"
)


def _swap_docstring_item3(doc: str, new_item3: str) -> str:
    """把 docstring 的第 3 条换成 `new_item3`（内存注入用；找不到锚点就抛）。"""
    start = doc.find("3. 没查成")
    end = doc.find("4. `method", start)
    assert start >= 0 and end > start, "锚点不见了：docstring 的编号被改过"
    return doc[:start] + new_item3 + doc[end:]


def test_module_docstring_covers_every_not_checked_reason():
    """正控（`R2-AN-3`）：docstring 第 3 条必须覆盖 `_NOT_CHECKED_REASONS` 全部五项。

    为什么需要它：这条清单的唯一来源是 `_NOT_CHECKED_REASONS`，
    docstring 只是它的一个读法。导入期断言守着同一个判据，
    这条用例再把"判据本身"钉住（导入期断言被 `-O` 关掉时它仍然在）。
    """
    import agentflow.agent_e as AE

    found = AE._docstring_not_checked_reasons(AE.__doc__ or "")
    missing = set(AE._NOT_CHECKED_REASONS) - found
    assert missing == set(), (
        f"模块 docstring 第 3 条没有覆盖 _NOT_CHECKED_REASONS，缺 {sorted(missing)}；"
        f"docstring 里读到的是 {sorted(found)}"
    )
    # 判据的非平凡性自校：它必须真的能读出东西（空集会让上面那条断言靠缺失通过）
    assert found, "读法返回了空集 ⇒ 这条正控没有在检查任何东西"


def test_docstring_guard_negative_control_four_item_version_goes_red():
    """负控（`R2-AN-3`）：把 docstring 第 3 条换回改前的四项 ⇒ 判据必须红。

    这条负控同时守两件事：
    ① 被测对象 —— 判据对"少列两项"这一形态敏感（不是恒真）；
    ② 判据自己 —— 同一份输入再加一条"必然通过"的形态（把清单补全）校一遍，
       否则"红"可能只是注入把 docstring 弄坏了。

    注入只发生在内存里（不动 `agent_e.py`）；注入的生效由两条指纹核对：
    注入后的文本必须与当前 docstring 不同，且替换掉的那一段正是当前实现里的第 3 条。
    """
    import agentflow.agent_e as AE

    current = AE.__doc__ or ""
    assert AE._docstring_not_checked_reasons(current) >= set(AE._NOT_CHECKED_REASONS), (
        "前置条件不成立：当前 docstring 本身就没过判据 ⇒ 这条负控证明不了任何东西"
    )

    injected = _swap_docstring_item3(current, _DOCSTRING_ITEM3_BEFORE)
    # 指纹①：注入确实改了文本（否则"判据红了"与注入无关）
    assert injected != current, "注入没有生效（文本没变）"
    # 指纹②：改前那一段确实是"四项"（与 §40.3 的 C1 读数一致）
    before_found = AE._docstring_not_checked_reasons(injected)
    missing_before = set(AE._NOT_CHECKED_REASONS) - before_found
    # 判据红了：`R2-AN-3` 那两项必须缺（这是这条负控的靶子）。
    # 2026-10-12 起断言从"等于那两项"改成"包含那两项"：受控词表后来又加了
    # `lean_disabled`（业主的 Lean 开关），历史文本当然也缺它 ——
    # 把等式写死会让一条负控自己因为"词表长大"而变红，
    # 而它要证明的性质（缺项必红）一点没变。
    assert {"source_unreadable", "param_error"} <= missing_before, missing_before
    assert missing_before, "历史那一段竟然覆盖了全部理由 ⇒ 这条负控是空的"

    # 同一判据的"必然通过"一侧：把清单补全 ⇒ 判据不红（证明红的来源是缺项而不是文本损坏）。
    # 清单现算自 `_NOT_CHECKED_REASONS`，不再手抄那五项：2026-10-12 加
    # `lean_disabled` 那一档时，这一侧的夹具因为抄死在文本里而当场变红 ——
    # 一条"必然通过"的负控自己过期，等于这条判据白守（手抄清单是同一个病的两种形态）。
    fixed = _swap_docstring_item3(
        current,
        "3. 没查成（" + " / ".join(f"`{r}`" for r in AE._NOT_CHECKED_REASONS) + "）⇒ 同上。\n",
    )
    assert AE._docstring_not_checked_reasons(fixed) >= set(AE._NOT_CHECKED_REASONS)
