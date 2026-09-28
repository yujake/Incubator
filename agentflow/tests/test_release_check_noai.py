"""`release_check` 的三态：没给改动集 / 给了且为空 / 给了且有改动；以及 `--skip` 的记账。

这一节钉的是 `P-25`：第一版用 `--changed nargs="*" default=[]` 把"没给"与"给了空"
折叠成同一个 `if not changed`，于是编排层不传 `--changed` 时这一项永远是 unknown
（实测 `UNKNOWN pass=7 fail=0 unknown=1`）—— 也就是说禁 AI 区门在发布链上从来没有
真的生效过。空集与缺输入必须是两件事。

`I-3` 追加的第二组：`--skip` 关掉的项不能被算成"通过"。旧版把跳过的项直接
`continue`（不进报告），于是八项关掉七项得到 `pass=1 fail=0 unknown=0` ⇒
`overall="pass"` + 退出码 0，而那句"这八项都通过了"在本次运行里是假的。

`F10`（第 7 轮修复批）：禁改区那一项的判据从"命中即 fail"改成"按台账判"。这一条
改动的触发者不是代码，而是人的签字 —— 所有者逐行走查之后，`dedup.py` 那一版
拿到了 2 名不同 reviewer 且 `sha256` 与盘上一致。本文件里三条编码了"签字前契约"
的用例因此变红（其中两条在本文件），现按签字后的契约重写，见下面那一节的注释。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import release_check as RC

#: 把仓库根注入 `sys.path`（与 `tests/test_noai_gate.py` 同一个理由：`scripts` 是顶层包，
#: 不这么做时本文件只在"cwd 恰好是仓库根"的跑法下能被导入）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import noai_gate as G  # noqa: E402


def _verdict(changed: list[str] | None) -> str:
    return RC.item_noai(RC.Report(), changed).verdict


def test_no_change_set_is_unknown_not_pass() -> None:
    """没给改动集 ⇒ unknown（没查成），不是 pass（查过了没问题）。"""
    assert _verdict(None) == "unknown"


def test_an_explicitly_empty_change_set_is_pass() -> None:
    """给了改动集而它为空 ⇒ pass：相对于所声明的基线确实没有改动，这一项没有对象可判。"""
    assert _verdict([]) == "pass"


def test_a_clean_change_set_is_pass() -> None:
    """非禁改区路径 ⇒ pass（门不许把无关改动算成命中）。"""
    assert _verdict(["docs/INDEX.md"]) == "pass"


# ------------------------------- `F10`：签字前契约 → 签字后的契约
#
# 所有者 2026-09-27 完成禁改区文件的逐行走查，把签字落进
# `.noai-approvals.json`：当时是 18 个文件、17 条各 2 名不同 reviewer；
# 随后 `A5` 扩容又把 3 条纳入清单并各配 2 名 reviewer。
# 这几个数刻意不在这里钉死 —— 台账会随签字增长，当次读数才是权威。
# 当时的读数（2026-09-27 15:0x 之前，`FIX11` 组 B4 落笔时）：entries 22 条、
# `reviewers` 逐条分布 {0: 2, 2: 20}、元素总数 40 —— 它此后又漂过（`pyproject.toml`
# 由人补签 2/2、`A5` 扩容后的条目陆续补齐），所以这三个数只能当"当时"读，
# 不许当当前值引用。当次读数一律复跑 `python temp\_ledger_snapshot.py` 的汇总行，
# 或直读 `.noai-approvals.json` 的 `entries` / 逐条 `reviewers`。
# 这不是代码变更 ——
# 世界变了。本节改前那两条用例逐字断言「命中禁改区 ⇒ fail」；签字之后
# `src/agentflow/dedup.py` 这一版拿到 2 名不同 reviewer 且 `sha256` 与盘上一致，
# 于是同一条命令判 `pass`，两条用例同时变红（实测见 `temp/FIX6-F1.md` 的 F1-R10 节）。
# 那句话在签字前是真的，在签字后不再是契约。现在的契约是：
#
#   未批准（`unregistered` / `stale` / `insufficient_reviewers`）⇒ fail；
#   有 2 名不同 reviewer 且 `sha256` 与盘上这一版一致 ⇒ 不判 fail。
#
# 判据在 `noai_gate.evaluate_approval`（`scripts/noai_gate.py`，禁改区，本批次不动它）。
# 本节只读真实台账：它是人的签字记录，一个字节都不许由测试改。负控一律打在
# `tmp_path` 下的台账副本上，并先证明注入真的生效（副本路径 + 两处 sha256）。

#: 真实仓库根（`release_check.REPO_ROOT` 就是 `agentflow/`）。
_REAL_ROOT = RC.REPO_ROOT
_REAL_LEDGER = _REAL_ROOT / G.LEDGER_NAME

#: 签字之后已批准的禁改区路径（2 名不同 reviewer + hash 与盘上一致）。
#: 刻意用真实路径：这一条要钉住的正是"真实那一版现在是什么结论"。
_APPROVED_ZONE_PATH = "src/agentflow/dedup.py"

#: 一个永远拿不到批准的禁改区路径：台账自己。判据的第 1 条就是自指
#: （`ledger_self_approval`，与 hash 一致不一致、reviewers 有几个都无关），
#: 所以拿它做负控不会因为将来有人签字而失效。
_UNAPPROVABLE_ZONE_PATH = G.LEDGER_NAME


def _zone_item(changed: list[str], *, ledger: str | None = None) -> RC.Item:
    """跑一次 noai 项（真起 `noai_gate.py` 子进程）。`ledger` 只给负控用。

    `ledger` 参数是 `item_noai` 专为核验留的旁路（`noai_gate.py` 的实现与判据不动，
    只换一份台账文件）；生产路径上它恒为 `None`。
    """
    return RC.item_noai(RC.Report(), changed, ledger=ledger)


def _ledger_copy_with(tmp_path: Path, path: str, mutate) -> tuple[Path, dict, dict]:
    """把真实台账复制到 `tmp_path`，只改 `path` 那一条；返回 (副本, 改前, 改后)。

    `before` 是 `mutate` 之前的深拷贝：负控要先证明"注入真的生效"，
    否则那条用例的读数可能是假绿（改没改成都得到同一个结论）。
    """
    payload = json.loads(_REAL_LEDGER.read_text(encoding="utf-8"))
    entry = next((e for e in payload["entries"] if e.get("path") == path), None)
    assert entry is not None, f"真实台账里没有 {path} 这一条（负控的注入对象不存在）"
    before = json.loads(json.dumps(entry, ensure_ascii=False))
    mutate(entry)
    after = json.loads(json.dumps(entry, ensure_ascii=False))
    copy = tmp_path / G.LEDGER_NAME
    copy.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return copy, before, after


def _approval_of(it: RC.Item, path: str) -> dict:
    """从这一项的 `detail` 里取出 `path` 那一条的台账判定（原样是门的 JSON）。"""
    got = [a for a in (it.detail.get("approvals") or []) if a.get("path") == path]
    assert got, f"门的输出里没有 {path} 这一条：{it.detail}"
    return got[0]


def test_a_zone_change_with_two_reviewers_is_a_human_pass() -> None:
    """正控（签字后的契约）：当前字节 + 真实台账 ⇒ `pass`，通路必须写明是人审。

    改前这一条叫 `test_a_zone_change_is_fail`，断言 `== "fail"`。签字的落点就是这条
    路径（2 名不同 reviewer + hash 与盘上一致），所以它现在必是 `pass`。
    下面两条负控证明它不是"命中禁改区就放行"：同一段判据对未批准的改动仍然是红的。
    """
    it = _zone_item([_APPROVED_ZONE_PATH])
    assert it.verdict == "pass", f"{it.verdict}：{it.notes}"
    assert it.detail.get("pass_path") == "human", (
        f"签字通路必须被读成**人审**（实测 detail={it.detail}）—— "
        "若这里是 `audit`，说明读的是机审通路，与『有 2 名不同 reviewer 签了字』不是一回事"
    )
    a = _approval_of(it, _APPROVED_ZONE_PATH)
    assert a["approval_reason"] == G.REASON_APPROVED, a
    assert a["approval_status"] == "approved", a
    assert a["distinct_reviewers"] >= G.REQUIRED_APPROVALS_ON_HIT == 2, a
    assert a["current_sha256"] == a["entry_sha256"], (
        "正控的前提是 hash 与盘上这一版一致；对不上时这一条应当先红（那一档是 `stale`）"
    )


def test_negative_control_a_zone_change_without_signatures_is_fail(tmp_path: Path) -> None:
    """负控①：把该条目的 `reviewers` 清空 ⇒ 判据必须红（`fail` / 退出码 1）。

    这就是"未批准的禁改区改动"的真实形态：登记过、hash 也对，只是没人签字。
    注入只打在台账副本上。副本路径与两份 sha256 都随断言信息带出来，便于人复核。
    """
    def drop_signatures(entry: dict) -> None:
        entry["reviewers"] = []

    copy, before, after = _ledger_copy_with(tmp_path, _APPROVED_ZONE_PATH, drop_signatures)
    assert before["reviewers"], "注入前提失败：真实台账那一条本来就没有 reviewer 可清"
    assert after["reviewers"] == [], after
    assert G.sha256_file(copy) != G.sha256_file(_REAL_LEDGER), (
        f"注入没有生效：副本 {copy} 与真实台账的字节完全相同"
    )
    it = _zone_item([_APPROVED_ZONE_PATH], ledger=str(copy))
    assert it.verdict == "fail", (
        f"清空 reviewers 之后判据必须红（副本 {copy}、sha256 "
        f"{G.sha256_file(copy)}）—— 实测 {it.verdict}：{it.notes}"
    )
    assert it.detail.get("gate_exit") == 1, it.detail
    assert _approval_of(it, _APPROVED_ZONE_PATH)["approval_reason"] == G.REASON_FEW_REVIEWERS
    text = "\n".join(it.notes)
    assert _APPROVED_ZONE_PATH in text, text
    assert "未获批准" in text, text


def test_negative_control_a_zone_change_whose_hash_drifted_is_fail(tmp_path: Path) -> None:
    """负控②：把该条目的 `sha256` 改一位 ⇒ `stale` ⇒ 判据必须红（`fail`）。

    这一档判的是"被批准的那一版不是盘上这一版"：git 只会说"文件变了"，
    台账能说出"变的不是被批准的那一版"。2 名 reviewer 仍在，仍然不许放行。
    """
    def flip_one_hex_digit(entry: dict) -> None:
        h = str(entry["sha256"])
        entry["sha256"] = ("0" if h[0] != "0" else "1") + h[1:]

    copy, before, after = _ledger_copy_with(tmp_path, _APPROVED_ZONE_PATH, flip_one_hex_digit)
    assert after["sha256"] != before["sha256"], before
    assert len(after["sha256"]) == 64 and after["sha256"] == after["sha256"].lower()
    assert after["sha256"] != G.sha256_file(_REAL_ROOT / _APPROVED_ZONE_PATH), (
        "注入没有生效：改后的 sha256 仍与盘上这一版相同"
    )
    assert G.sha256_file(copy) != G.sha256_file(_REAL_LEDGER)
    it = _zone_item([_APPROVED_ZONE_PATH], ledger=str(copy))
    assert it.verdict == "fail", (
        f"sha256 改一位之后判据必须红（副本 {copy}、sha256 "
        f"{G.sha256_file(copy)}）—— 实测 {it.verdict}：{it.notes}"
    )
    assert it.detail.get("gate_exit") == 1, it.detail
    assert _approval_of(it, _APPROVED_ZONE_PATH)["approval_reason"] == G.REASON_STALE


#: 只跑 noai 一项：其余七项都用 `--skip` 关掉，用例才跑得快且不依赖别的东西。
#:
#:  `I-3` 之后这不再等于"总体 pass"：被跳过的七项按 `unknown` 记账 ⇒ 退出码 2。
#: 所以这一节现在分三组：
#:   - `item_noai()` 的单点三态（不起子进程、不看总判定）—— 判据的主体；
#:   - `item_noai()` 的签字后契约（正控 + 台账副本上的两条负控）—— 见上面那一节；
#:   - `--skip` 的记账（跳过必须留痕且不许算通过）—— `I-3` 的回归判据。
#: 想验证"八项都跑且总判定 pass"是另一件事（那要跑全量测试，属于发布门自己的验收，
#: 见 `tools/release_all.py` 的无人值守路径），不在本文件的成本预算里。
_ONLY_NOAI = ["--skip", "tests", "selftests", "tools", "verify", "lint", "contract", "imports"]


def test_cli_distinguishes_no_change_set_from_an_empty_one(tmp_path: Path) -> None:
    """CLI 面：`--changed-file <空文件>` ⇒ 2（本次跳过了七项）；完全不给也 ⇒ 2。

    两者退出码相同而原因不同，所以这里额外断言"原因"：
    前者是 `skip=7`、后者是 noai 那一项自己报 unknown（没给改动集）。
    """
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    j1 = tmp_path / "a.json"
    assert RC.main([*_ONLY_NOAI, "--changed-file", str(empty), "--json", str(j1)]) == 2
    d1 = json.loads(j1.read_text(encoding="utf-8"))
    assert d1["counts"]["skipped"] == 7, d1["counts"]
    assert d1["skipped"] == ["tests", "selftests", "tools", "verify", "lint", "contract", "imports"]
    assert d1["overall"] == "unknown"
    assert [i["key"] for i in d1["items"]] == ["noai"], "被跳过的项不该混进 items"
    assert d1["items"][0]["verdict"] == "pass", "空改动集在这一项上仍是 pass"

    j2 = tmp_path / "b.json"
    assert RC.main([*_ONLY_NOAI, "--json", str(j2)]) == 2
    d2 = json.loads(j2.read_text(encoding="utf-8"))
    assert d2["items"][0]["verdict"] == "unknown", "没给改动集 ⇒ 这一项没查成"


def test_cli_changed_file_with_an_approved_zone_path_is_a_human_pass(tmp_path: Path) -> None:
    """CLI 面（签字后的契约）：改动集里有已批准的禁改区路径 ⇒ 这一项 `pass`/人审。

    改前这一条叫 `test_cli_changed_file_with_a_zone_path_is_fail`、断言退出码 1（实测
    拿到 2，因为签字之后这一项判 `pass`）。现在同一条命令的读数是：noai 项 `pass`
    且通路写明人审，而总判定仍因 `--skip` 关掉的七项记 `unknown` ⇒ 退出码 2。
    """
    ch = tmp_path / "ch.txt"
    ch.write_text("docs/INDEX.md\nsrc/agentflow/dedup.py\n", encoding="utf-8")
    out = tmp_path / "j.json"
    assert RC.main([*_ONLY_NOAI, "--changed-file", str(ch), "--json", str(out)]) == 2
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["counts"]["skipped"] == 7, d["counts"]
    assert d["overall"] == "unknown", d["overall"]
    item = d["items"][0]
    assert item["verdict"] == "pass", item
    assert item["detail"].get("pass_path") == "human", item["detail"]


def test_negative_control_cli_unapprovable_zone_path_is_still_fail(tmp_path: Path) -> None:
    """CLI 面负控：改动集里有一个永远未获批准的禁改区路径 ⇒ 1（fail）。

    用台账自己：判据第 1 条就是"台账不能批准自己" ⇒ 它恒为 `unapproved`
    （`reviewers` 有几个都不改变这一点），所以这条负控不会因为将来有人签字而失效。
    它挡的正是"把判据改软成命中禁改区就不判 fail"那种改法 —— 那也是 `F10` 的边界：
    未批准的禁改区改动必须仍然以退出码 1 结束。
    """
    ch = tmp_path / "ch.txt"
    ch.write_text(f"docs/INDEX.md\n{_UNAPPROVABLE_ZONE_PATH}\n", encoding="utf-8")
    assert RC.main([*_ONLY_NOAI, "--changed-file", str(ch)]) == 1


def test_cli_unreadable_changed_file_keeps_unknown(tmp_path: Path) -> None:
    """改动集文件读不到 ⇒ 保持 unknown(2)，不许当成"改动集为空 ⇒ pass"。"""
    missing = tmp_path / "nope.txt"
    assert not missing.exists()
    assert RC.main([*_ONLY_NOAI, "--changed-file", str(missing)]) == 2


@pytest.mark.parametrize("flag", ["--changed", "--changed-file"])
def test_both_ways_of_declaring_a_change_set_can_pass(tmp_path: Path, flag: str) -> None:
    """两条路径都能表达"已声明且无命中"：这一项判 pass（总判定另受 `--skip` 影响）。"""
    rep = RC.Report()
    if flag == "--changed":
        assert RC.item_noai(rep, ["docs/INDEX.md"]).verdict == "pass"
    else:
        ch = tmp_path / "ch.txt"
        ch.write_text("docs/INDEX.md\n", encoding="utf-8")
        assert RC.item_noai(rep, ["docs/INDEX.md"]).verdict == "pass"
        assert RC.main([*_ONLY_NOAI, "--changed-file", str(ch), "--json",
                        str(tmp_path / "j.json")]) == 2
        d = json.loads((tmp_path / "j.json").read_text(encoding="utf-8"))
        assert d["items"][0]["verdict"] == "pass"


# --------------------------------------------------------------- `I-3`：`--skip` 的记账


#: `_ONLY_NOAI` 关掉的那七项（顺序与命令行一致）。
_SKIPPED_KEYS = ["tests", "selftests", "tools", "verify", "lint", "contract", "imports"]


def _assert_skip_run_is_unknown(report: RC.Report) -> None:
    """跳过记账的判据本体（正控与负控共用同一段断言，负控才有意义）。

    三件事缺一不可：跳过的项逐个留名、计数对得上、总判定不是 pass。
    第三条是 `T2` 的要害 —— 改前 `--skip` 关掉的项根本不进判据集合，于是
    「八项只跑一项」被打印成「这八项都通过了」并给出退出码 0；
    那条通路当时是被测试背书的（本文件断言 `== 0`），不是被测试拦住的。
    """
    assert report.counts()["skipped"] == len(_SKIPPED_KEYS), report.counts()
    assert sorted(report.skipped) == sorted(_SKIPPED_KEYS), report.skipped
    assert report.overall() == "unknown", (
        "跳过的项必须影响总判定：跳过七项 ⇒ unknown（没查成），"
        "绝不等于通过（`T2`/`I-3`）"
    )


def test_a_skip_run_is_unknown_and_names_every_skipped_item() -> None:
    """正控（`T2`）：跳过的项逐个留名，且总判定是 unknown，不是 pass。"""
    rep = RC.Report()
    rep.skipped.extend(_SKIPPED_KEYS)
    _assert_skip_run_is_unknown(rep)


def test_negative_control_a_skip_recorded_as_pass_turns_the_judgement_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控（`T2`）：把「跳过记 unknown」改回改前的「跳过不进判据集合」⇒ 判据必红。

    注入打在进程内：把 `Report.overall` 换回旧实现（只看已跑的 `items`，
    不看 `skipped`），于是同一段正控断言必须抛 —— 它在旧口径下算出 `pass`。
    这条证明正控不是恒真：它的牙全在「跳过必须影响总判定」这一点上。

    为什么要这样注入而不是复制一份 `release_check.py`：那个文件在 FC-27 禁改区，
    本批次不动它；而"改坏实现 ⇒ 判据变红"这件事可以在进程内等价地做出来。
    """

    def old_overall(self: RC.Report) -> str:
        c = self.counts()
        if c["fail"]:
            return "fail"
        if c["unknown"]:
            return "unknown"
        return "pass"

    monkeypatch.setattr(RC.Report, "overall", old_overall)
    rep = RC.Report()
    rep.skipped.extend(_SKIPPED_KEYS)
    assert rep.overall() == "pass", "夹具前提：旧口径下跳过七项仍然算通过"
    with pytest.raises(AssertionError):
        _assert_skip_run_is_unknown(rep)


def test_skipping_every_item_is_unknown_not_pass() -> None:
    """负控（`I-3` 核心）：八项全跳过 ⇒ 总判定 unknown，不是 pass。

    这一条在改前必红：改前 `items` 是空的，`overall()` 落到 `return "pass"`
    （空集的 `fail`/`unknown` 计数都是 0），于是"一项都没跑"被判成"全部通过"。
    """
    rep = RC.Report()
    rep.skipped.extend(["tests", "selftests", "tools", "verify", "lint", "noai",
                        "contract", "imports"])
    assert rep.counts()["skipped"] == 8
    assert rep.overall() == "unknown"
    assert rep.to_dict()["skipped"][0] == "tests"


def test_one_pass_item_with_nothing_skipped_is_still_pass() -> None:
    """正控：没有跳过时，单项 pass ⇒ 总判定仍是 pass（别把 unknown 扩大化）。"""
    rep = RC.Report()
    rep.add(RC.Item("noai", "禁 AI 区门", "pass", {}, []))
    assert rep.counts()["skipped"] == 0
    assert rep.overall() == "pass"


def test_a_skipped_item_does_not_hide_a_fail() -> None:
    """`fail` 优先于 `skipped`：跳过七项、留下一项 fail ⇒ 仍是 fail(1)，不许被 unknown 掩盖。"""
    rep = RC.Report()
    rep.add(RC.Item("noai", "禁 AI 区门", "fail", {}, []))
    rep.skipped.extend(["tests", "selftests", "tools", "verify", "lint", "contract", "imports"])
    assert rep.overall() == "fail"


def test_release_all_passes_the_change_set_down_to_release_check(tmp_path: Path) -> None:
    """编排层必须把改动集传下去（P-25 的另一半），而不是把那一项一直留在 unknown。"""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools"))
    import release_all as RA

    argv = RA.build_steps(root, None, changed_file=tmp_path / "ch.txt")[0].argv
    assert "--changed-file" in argv, argv
    assert argv[argv.index("--changed-file") + 1].endswith("ch.txt"), argv


# ------------------------------- `R1-1`：pass 说明必须按通路分流（不许替机审宣称"人走过查"）


def _pass_notes(monkeypatch: pytest.MonkeyPatch, approval: dict,
                *, verdict: str = "clean") -> tuple[str, dict, list[str]]:
    """把门的 `--check-approvals --json` 换成给定的一条批准记录，跑 `item_noai`。

    为什么可以替换子进程调用：这一条要判的是发布门这一侧的措辞分流，
    而"哪条通路算批准"的判据在 `noai_gate.evaluate_approval`（唯一实现，另有测试）。
    替换掉之后这一条仍然能红：模拟出来的字段正是门真实 JSON 里的字段名
    （`approval_reason` / `distinct_reviewers`）。
    """
    def fake_run(cmd, *, cwd, timeout=1800.0, env_extra=None):  # noqa: ANN001, ANN202
        argv = list(cmd)
        if "--check-consistency" in argv:
            return {"started": True, "timed_out": False, "exit_code": 0,
                    "stdout": "一致", "stderr": "", "cmd": " ".join(argv)}
        return {"started": True, "timed_out": False, "exit_code": 0,
                "stdout": json.dumps({"verdict": verdict, "approvals": [approval]}),
                "stderr": "", "cmd": " ".join(argv)}

    monkeypatch.setattr(RC, "_run", fake_run)
    it = RC.item_noai(RC.Report(), ["src/agentflow/dedup.py"])
    return it.verdict, it.detail, it.notes


def test_zone_pass_note_says_human_when_two_reviewers_signed(monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：`distinct_reviewers=2` ⇒ 说明写"人审"，且不写"没有人签过字"。"""
    verdict, detail, notes = _pass_notes(monkeypatch, {
        "path": "src/agentflow/dedup.py", "approval_status": "approved",
        "approval_reason": "approved", "distinct_reviewers": 2, "detail": "",
    })
    text = "\n".join(notes)
    assert verdict == "pass", notes
    assert detail["pass_path"] == "human"
    assert "人审" in text and "≥2 名不同 reviewer" in text
    assert "没有任何人类 reviewer 签过字" not in text


def test_zone_pass_note_says_no_human_signature_on_the_audit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`R1-1` 负控：`distinct_reviewers=0`（机审放行）⇒ 说明必须写明"没有任何人类 reviewer 签过字"。

    这一条在改前必红：改前那段说明是无条件的"各 ≥2 名不同 reviewer 完成逐行走查"，
    而机审通路里 `reviewers` 是空的 —— 报告在替一个没人签过字的通路宣称"人走过查了"。
    """
    verdict, detail, notes = _pass_notes(monkeypatch, {
        "path": "src/agentflow/dedup.py", "approval_status": "approved",
        "approval_reason": "approved", "distinct_reviewers": 0, "detail": "",
    })
    text = "\n".join(notes)
    assert verdict == "pass", notes
    assert detail["pass_path"] == "audit"
    assert "没有任何人类 reviewer 签过字" in text
    assert "各 ≥2 名不同 reviewer 完成逐行走查" not in text


def test_zone_pass_note_claims_nothing_when_nothing_hit_the_zone(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`REAUDIT2-R1-1` 负控：改动集一条都没命中禁改区时，不许提台账批准与审计通路。

    这一档的现实形态：改动集里全是普通文件 ⇒ `noai_gate --check-approvals` 返回
    `clean` + `approvals == []` + `ledger == ""`（它压根没读台账，因为没对象可判）。
    旧版（本轮第一版）会落进 `else`，逐字写下"命中路径全部已在台账里获批准…
    通路 = 多维独立审计…没有任何人类 reviewer 签过字" ——
    那是替不存在的台账判定与不存在的审计流程作证，与 `R1-1` 同族。
    """
    # 真实形态：非禁改区路径 ⇒ 门根本不进入逐条判定（这里直接模拟门的输出）。
    def fake_run(cmd, *, cwd, timeout=1800.0, env_extra=None):  # noqa: ANN001, ANN202
        argv = list(cmd)
        if "--check-consistency" in argv:
            return {"started": True, "timed_out": False, "exit_code": 0,
                    "stdout": "一致", "stderr": "", "cmd": " ".join(argv)}
        return {"started": True, "timed_out": False, "exit_code": 0,
                "stdout": json.dumps({"verdict": "clean", "approvals": [], "ledger": "",
                                      "violations": [], "required_approvals": 0}),
                "stderr": "", "cmd": " ".join(argv)}

    monkeypatch.setattr(RC, "_run", fake_run)
    it = RC.item_noai(RC.Report(), ["docs/INDEX.md"])
    text = "\n".join(it.notes)
    assert it.verdict == "pass", it.notes
    assert it.detail["pass_path"] == "no_hits", it.detail
    # 判据：两条通路各自的那句判据句都不许出现（`N 条通路 = 人审` /
    # `通路 = 多维独立审计`）。只断言某个词"不许出现"会被元层面的否定句误伤
    # （实测踩过两次：`不许把它读成'已获批准'`）。
    assert "条通路 =" not in text, text
    assert "多维独立审计" not in text, text
    assert "没有任何人类 reviewer 签过字" not in text, text
    assert "没有对象可判" in text, text


def test_zone_pass_with_an_unexplained_clean_is_unknown_not_pass(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`REAUDIT2-R1-1` 的第二半：门说 `clean` 却一条 `approved` 都没有 ⇒ 按"没查成"记。

    "退出码 0 + 有批准记录 + 没有一条理由码是 `approved`"意味着门与这一侧的读法
    已经对不上。折叠成 pass 就是替一个说不清的结论作证；折叠成 fail 又会把
    "没查成"读成"查了没通过"。这里按 unknown 记。
    """
    verdict, detail, notes = _pass_notes(monkeypatch, {
        "path": "src/agentflow/dedup.py", "approval_status": "approved",
        "approval_reason": "stale", "distinct_reviewers": 2, "detail": "",
    })
    text = "\n".join(notes)
    assert verdict == "unknown", notes
    assert detail["pass_path"] == "unexplained", detail
    assert "条通路 =" not in text, text


def test_every_reason_code_the_gate_can_return_has_a_translation() -> None:
    """`REAUDIT2-R1-2`：门的理由码集合与翻译表必须有交叉断言（不许靠人对齐）。

    判据是双向的：
    - 门能赋给 `approval_reason` 的每一个码（`noai_gate.REASON_*` 的取值，
      去掉登记为"不可达"的那一个）都必须在翻译表里；
    - 翻译表里不许留门已经发不出的码（`ledger_structure` 就是被删掉的那一个）。
    """
    import importlib.util
    import sys

    gate_path = Path(__file__).resolve().parents[1] / "scripts" / "noai_gate.py"
    spec = importlib.util.spec_from_file_location("_noai_gate_for_codes", gate_path)
    gate = importlib.util.module_from_spec(spec)
    sys.modules["_noai_gate_for_codes"] = gate
    spec.loader.exec_module(gate)

    emitted = {
        value for name, value in vars(gate).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    translated = set(RC._APPROVAL_REASON_TEXT)
    missing = sorted(emitted - translated)
    stale = sorted(translated - emitted)
    assert missing == [], f"门会发出的理由码没有翻译：{missing}"
    assert stale == [], f"翻译表里有门发不出的码：{stale}"
    # 反向：这条断言本身要能红 —— 拿掉一个键必须被上面的 missing 抓到。
    assert "approved" in translated and "unregistered" in translated


# ------------------- `R2-R1` / `R2-R2`：`proof_location` 的"两条继续往下判"的形态
#
# 重审（`temp/REAUDIT-R2.json`）实测：`check_proofs` 第四条对"长得像 `名字:数字`"的
# 写法整条 `continue`，于是 `not-a-claim:7`（本文档没有这个 claim_id）也报
# `problems=[]` + "proof_location 都成立"；同时不做工作区包含性检查，
# `../outside.lean` 与工作区外的绝对路径都算"落点成立"。
# 下面这组用例把这两条缺口钉住：修好之前，前两条与后两条都会红。


def _proof_problems(loc: str, ws: Path, *, known_id: str = "claim-known") -> list[str]:
    from agentflow.tools import doc_tools as DT

    def rows_of(table: str):  # noqa: ANN202
        if table == "experiments":
            return [{"experiment_id": "0000", "evidence_kind": "proof"}]
        return [{"claim_id": known_id, "evidence_kind": "proof", "citations": ["exp:0000"]}]

    res = DT.check_proofs(
        rows_of=rows_of,
        claims=[{"claim_id": known_id, "evidence_kind": "proof",
                 "citations": ["exp:0000"], "proof_location": loc}],
        workspace_root=str(ws),
    )
    assert res["checked"] is True
    return [p["kind"] for p in res["problems"]]


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "proofs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "proofs" / "real.lean").write_text("theorem real : True := trivial\n",
                                                   encoding="utf-8")
    (tmp_path.parent / "outside.lean").write_text("theorem o : True := trivial\n",
                                                 encoding="utf-8")
    return tmp_path


def test_proof_location_pointing_at_a_nonexistent_claim_id_is_a_problem(tmp_path: Path) -> None:
    """`R2-R1` 负控：形态像交叉引用、但本文档没有这个 `claim_id` ⇒ 必须报，不许静默跳过。"""
    ws = _ws(tmp_path)
    assert _proof_problems("not-a-claim:7", ws) == ["proof_location_not_found"]
    assert _proof_problems("claim-9b85fc39:12", ws) == ["proof_location_not_found"]


def test_proof_location_self_reference_still_passes(tmp_path: Path) -> None:
    """正控：本文档真实存在的 `claim_id`（裸的 / 带行号两种写法）必须仍然放行。"""
    ws = _ws(tmp_path)
    assert _proof_problems("claim-known", ws) == []
    assert _proof_problems("claim-known:12", ws) == []


def test_proof_location_outside_the_workspace_is_a_problem(tmp_path: Path) -> None:
    """`R2-R2` 负控：`../` 与工作区外的绝对路径都必须是问题（旧版只判 `is_file()`）。"""
    ws = _ws(tmp_path)
    assert _proof_problems("../outside.lean", ws) == ["proof_location_outside_workspace"]
    outside = (tmp_path.parent / "outside.lean").resolve()
    assert _proof_problems(str(outside), ws) == ["proof_location_outside_workspace"]


def test_proof_location_inside_the_workspace_still_passes(tmp_path: Path) -> None:
    """正控（不许回归）：工作区内真实存在的文件（带不带行号）仍然放行；
    工作区内不存在的文件仍然报 `proof_location_not_found`。"""
    ws = _ws(tmp_path)
    assert _proof_problems("proofs/real.lean", ws) == []
    assert _proof_problems("proofs/real.lean:3", ws) == []
    assert _proof_problems("proofs/nope.lean", ws) == ["proof_location_not_found"]


def test_release_all_passes_the_change_set_down_to_release_check(tmp_path: Path) -> None:
    """编排层必须把改动集传下去（P-25 的另一半），而不是把那一项一直留在 unknown。"""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools"))
    import release_all as RA

    argv = RA.build_steps(root, None, changed_file=tmp_path / "ch.txt")[0].argv
    assert "--changed-file" in argv, argv
    assert argv[argv.index("--changed-file") + 1].endswith("ch.txt"), argv
    # 反向：没给改动集时不许伪造一个"空改动集"（那会把没查成伪装成查过了）
    assert "--changed-file" not in RA.build_steps(root, None)[0].argv
