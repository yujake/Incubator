# -*- coding: utf-8 -*-
"""判据：E 写的 ②③ 真的落在盘上，且"没有那份读数"就标不成 proof（业主 2026-10-23 晚）。

业主原话（逐字）：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」。

## 这一组守四条

1. 一次穷举实验跑完，E 的 ②③（程序设计思路 / 穷举论证）真的落在
   `out/experiments/<实验号>/exhaustion.md`：路径是相对仓库根的稳定落点、字节数与
   sha256 与盘上那份逐字对得上，且返回值里读得到那个路径（B 登记、G 引用都靠它）；
2. 负控：报告没落成（真注入：落点被一个同名文件占住 ⇒ 写不进去）⇒ 那条证据标不成
   proof，读数里逐条写着缺什么；schema 那一层同样拒一条"没有落盘事实的 proof 行"；
3. 反真空：把"报告存在性检查"打桩成恒真 ⇒ 第 2 条必红（同一次注入下它会被标成 proof）；
4. 三块齐的判据与 G 那一侧同源：`numerictheorem.blocks_missing` 认为那份读数三块齐全
   （同一件事不写第二份口径）。

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 一个真的"穷举"脚本：它报三件事实（exhaustive / 搜索空间 / ②③ 两段人话），
#: 而等级不由它自己说。搜索空间的数字在代码里真的出现（判据靠这一点区分
#: "报告里报了一个数"与"代码里真的搜了那么多"）。
EXHAUSTIVE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form "
                        "去掉对称性重数，再按 3-子集/4-子集的对称性剪枝；K_9 的每个染色都落在枚举里，"
                        "无一遗漏；边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None,
    "negation_kind": "not_proved",
    "bound": {"n": 9},
    "strategy": "canonical form + symmetry breaking",
}))
"""
#: 一个"不完全"的脚本：只有扫描点数，没有任何穷尽证据。
PARTIAL_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"points": 100000, "grid": 64},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""
SCRIPT_REL = "code/enum_ramsey34.py"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _e(store: Store) -> AgentE:
    return AgentE(store, config={}, workspace_root=store.root)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run(store: Store, body: str = EXHAUSTIVE_PROBE, rel: str = SCRIPT_REL) -> dict:
    _write(store, rel, body)
    return _e(store).run_experiment("R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", rel,
                                    method="numeric")


def _block_the_landing(store: Store) -> pathlib.Path:
    """真注入：把第一条实验的落点目录变成一个同名文件 ⇒ 报告写不进去。

    这是"报告没落成"的真实故障（不是打桩）：`land_report` 会拿到一个 OSError，
    于是那条证据的落盘事实是 ok=false、字节数 0、没有 sha256。
    """
    out_dir = pathlib.Path(store.root) / ER.REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    blocker = out_dir / S.format_id(0)
    blocker.write_text("这不是目录", encoding="utf-8")
    assert blocker.is_file()
    assert not blocker.is_dir()
    return blocker


# ------------------------------------------------------------------ ① 报告真的落盘


def test_1_the_two_blocks_really_land_on_disk_with_a_stable_relative_path(
        tmp_path: pathlib.Path) -> None:
    """① E 的 ②③ 落成一份可核的读数：路径稳定、字节数与 sha256 与盘上逐字对得上。"""
    store = _store(tmp_path)
    out = _run(store)
    eid = out["experiment_id"]
    rel = ER.report_relpath(eid)
    assert rel == f"out/experiments/{eid}/exhaustion.md", rel
    path = pathlib.Path(store.root) / rel
    assert path.is_file(), f"报告没有落盘：{rel}"
    text = path.read_text(encoding="utf-8")
    # 路径是相对仓库根的稳定落点（不是绝对路径、不是随手起的名字）
    assert out["report_path"] == rel, out["report_path"]
    assert not pathlib.Path(out["report_path"]).is_absolute()
    assert ER.is_report_relpath(out["report_path"])
    # 字节数与 sha256 记的是"读回来"的事实，不是"我调了写函数"这个意图
    assert out["report_bytes"] == len(text.encode("utf-8")) == path.stat().st_size
    assert out["report_sha256"] == _sha(text)
    assert len(out["report_sha256"]) == 64
    # ②③ 两块都在，且署名与读数编号都在（G 那一侧按同一批记号核）
    assert ER.BLOCK_DESIGN in text and ER.BLOCK_EXHAUSTION in text, text[:400]
    assert ER.AUTHOR_MARKER in text and f"exp:{eid}" in text
    blocks, missing = ER.blocks_of(text)
    assert missing == [], missing
    assert blocks[ER.DESIGN] > 0 and blocks[ER.ENUMERATION] > 0, blocks
    # 与 G 那一侧的"三块齐全"判据同源（同一件事不写第二份口径）
    from agentflow import numerictheorem as NT

    assert NT.blocks_missing(text) == [], NT.blocks_missing(text)
    # 落盘事实写在行上（`schema` 是纯的，只能读行上的事实）
    row = [r for r in store.rows("experiments") if r["experiment_id"] == eid][0]
    facts = ER.report_facts(row)
    assert facts["path"] == rel and facts["ok"] is True, facts
    assert facts["bytes"] == out["report_bytes"] and facts["sha256"] == out["report_sha256"]
    assert ER.landing_problems(row) == [], ER.landing_problems(row)
    # 落盘之后这条证据才够 proof（V 签、E 写 ②③）
    assert out["evidence_kind"] == "proof", out
    assert out["signed_by"] == NP.PROOF_SIGNER == "V", out
    assert out["proof_authors"] == [NP.NUMERIC_AUTHOR] == ["E"], out


def test_1b_the_column_and_the_report_say_the_same_two_blocks(tmp_path: pathlib.Path) -> None:
    """① 的第二半：证明栏里的 ②③ 与盘上那份读数逐字一致（两处不一致 = 两个人写的话）。"""
    store = _store(tmp_path)
    out = _run(store)
    row = [r for r in store.rows("experiments") if r["experiment_id"] == out["experiment_id"]][0]
    column = NP.proof_column(row)
    parts = NP.parse_proof_column(column)
    assert parts["problems"] == [], parts
    report = ER.read_report(store.root, out["report_path"])
    assert report["ok"] is True, report
    assert parts["design"] in report["text"], "证明栏里的程序设计在报告里读不到"
    assert parts["enumeration"] in report["text"], "证明栏里的穷举论证在报告里读不到"
    assert parts["script"] == SCRIPT_REL


# ------------------------------------------------------------------ ② 负控：报告缺 ⇒ 不 proof


def test_2_a_failed_landing_cannot_be_proof_and_says_what_is_missing(
        tmp_path: pathlib.Path) -> None:
    """② 负控：报告没落成 ⇒ 那条证据标不成 proof，读数里逐条写着缺什么。"""
    store = _store(tmp_path)
    _block_the_landing(store)
    out = _run(store)
    assert out["evidence_kind"] != "proof", out
    assert out["evidence_kind"] == NP.SUPPORTED_ONLY_KIND, out
    assert out["report_problems"], "没落成必须逐条写清缺什么（不是只说一句'不合格'）"
    row = store.rows("experiments")[-1]
    facts = ER.report_facts(row)
    assert facts["ok"] is False, facts
    assert ER.landing_problems(row), ER.landing_problems(row)
    signature = NP.signature_of(row)
    assert signature["problems"], "签名里要点名缺哪一块"
    assert NP.is_signed_exhaustion(row) is False
    # 那条证据的 ① 程序与 exhaustive 都在 —— 唯一缺的就是那份落盘读数
    # （所以"不 proof"这件事只能压在这一格上，判据把它钉住）
    assert any("②③" in p or "落盘" in p or "报告" in p for p in ER.landing_problems(row))


def test_2b_schema_refuses_a_proof_row_without_any_landing_facts(
        tmp_path: pathlib.Path) -> None:
    """② 的另一半：手写一条"没有落盘事实的 proof 行" ⇒ 写入期就炸（schema 是纯的，读行上的事实）。"""
    with pytest.raises(ValueError) as ei:
        S.Experiment(
            experiment_id=S.format_id(1), claim="R(3,4)=9", claim_key="ramsey34=9",
            method="numeric", evidence_kind="proof", result="supports",
            negation_kind="not_proved", code_path=SCRIPT_REL, code_hash="deadbeef",
            exit_code=0,
            observations={"exhaustive": True, "design": "d", "enumeration": "e",
                          "search_space": {"n": 9}},
            certificate={"kind": "enumeration_bound"},
            search_bound={"n": 9},
            created_at="2026-10-23T00:00:00+08:00",
        ).validate()
    assert "不得声称" in str(ei.value), ei.value
    assert "②③" in str(ei.value) or "落盘" in str(ei.value), ei.value


def test_2c_an_incomplete_experiment_still_cannot_be_proof(tmp_path: pathlib.Path) -> None:
    """② 的第三半（与报告无关的那条负控，反真空）：只有扫描点数的实验仍是 cross_check。"""
    store = _store(tmp_path)
    out = _run(store, PARTIAL_PROBE, "code/scan_points.py")
    assert out["evidence_kind"] == "cross_check", out
    # 报告照样落盘（E 写了"没有给出"这两块），但它缺 ②③ ⇒ 落盘本身不能把证据升级
    assert out["report_path"], "报告落盘与证据等级是两件事：落盘不该被这条负控挡住"
    row = store.rows("experiments")[-1]
    problems = ER.landing_problems(row)
    assert problems and any("程序设计" in p for p in problems), problems


# ------------------------------------------------------------------ ⑤ 反真空


def test_5_stub_the_report_check_to_true_and_the_negative_control_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把"报告存在性检查"打桩成恒真 ⇒ ② 必红（同一次注入下会被标成 proof）。"""
    # 先证明真判据下它是红的
    store = _store(tmp_path / "real")
    _block_the_landing(store)
    real = _run(store)
    assert real["evidence_kind"] == NP.SUPPORTED_ONLY_KIND, real

    # 再把判据打桩成恒真：同一次故障注入必须被"标成 proof"（否则 ② 那一条是空转的）
    monkeypatch.setattr(ER, "landing_problems", lambda row: [], raising=True)
    store2 = _store(tmp_path / "stubbed")
    _block_the_landing(store2)
    stubbed = _run(store2)
    assert stubbed["evidence_kind"] == "proof", (
        "打桩之后它仍然是 cross_check ⇒ ② 压的不是这条判据（改前红没有出处）")
    assert stubbed["report_problems"], "落盘那件事本身仍然是失败的（打桩只骗过了等级判定）"
