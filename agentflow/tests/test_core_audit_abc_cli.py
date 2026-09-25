"""核心审计修复的回归测试：`agent_a` / `agent_b` / `agent_c` / `cli`（FC-AUDIT 子任务）。

## 这个文件在钉什么

本轮修的都是"不报错的错"这一类缺陷 —— 静默折叠、写死的第二份名单、
退出码恒定、以及"没做"被读成"做了"。所以这里的用例一律遵守两条：

1. 断言打在行为上，不打在实现上。例如断言"`verify` 在有 error 时退出码非 0"，
   而不是"调用了某个函数"；断言"`--role E` 能列出 E 的工具"，而不是"choices 来自 ROLES"。
2. 每条修复都要有负控（`DEVELOPMENT.md` §5.1：只有正向的断言，一个永远报错的
   实现也能全绿）。负控的形态是"不该触发时确实没触发"：空表不该报"查过了没有"、
   合法参数不该抛、干净数据退出码必须是 0。

## 三态纪律在本文件里的落点

修过若干"两态折叠成两态"的地方（`None` 同时表示"没做"和"做了没结果"），所以这里
显式断言三态可区分：

- `AnalysisReport.ok`：空关系表（`ok=False`）≠ 查过了没有（`ok=True` + 空结果）；
- `AgentB` 取文献：队列空 / 全被别人占着 / 全被放弃 是三个不同的 `skipped_reason`；
- `cli verify` 退出码：0 通过 / 1 发现问题 / 2 没查成（`StoreError`）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentflow import agent_a, agent_b, cli
from agentflow import schema as S
from agentflow.agent_a import AgentA, ClaimOutcome
from agentflow.agent_b import AgentB
from agentflow.agent_c import AgentC
from agentflow.store import Store, StoreError
from agentflow.tools.base import ToolRegistry

from conftest import add_concept, add_literature, add_relation, add_request, write_library_file

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"


# --------------------------------------------------------------------------- 小工具


def _ws(tmp_path: Path, name: str = "ws") -> Store:
    st = Store(tmp_path / name)
    st.init()
    return st


def _mutate(store: Store, table: str, fn) -> None:
    """直接改快照文件，模拟"外部脚本/人工把数据改坏了"（与 test_verify.py 同法）。"""
    path = store.data / S.TABLES[table]["file"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc["rows"])
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_module(mod: str) -> subprocess.CompletedProcess:
    """跑 `python -m agentflow.<mod>`（release_check 第 2 项用的同一条命令）。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONPATH": str(_SRC)}
    return subprocess.run(
        [sys.executable, "-m", f"agentflow.{mod}"],
        cwd=str(_SRC), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=600,
    )


class _StubExtractor:
    """确定性抽取器替身（不联网、不过模型），用于让 B 的主路径可被断言。"""

    def __init__(self, concepts=(), relations=()):
        self.concepts, self.relations = list(concepts), list(relations)
        self.seen_meta: list[dict] = []

    def extract(self, doc, lit_id, meta):
        self.seen_meta.append(dict(meta))
        return list(self.concepts), list(self.relations)


class _TextDoc:
    """最小文档替身：`check_quote` 只要求 `pages`（可选 `text_at`）。"""

    def __init__(self, text: str):
        self.pages = [text]


def _add_leased_literature(
    store: Store,
    lit_id: str,
    *,
    claimed_by: str | None = None,
    lease_until: str | None = None,
    mine_attempts: int = 0,
    path: str | None = None,
    processed: bool = False,
) -> None:
    """插一行文献并直接指定租约字段（conftest 的 `add_literature` 不支持它们）。

    这些字段是 B 的并发控制面（`claimed_by` / `lease_until` / `mine_attempts`），
    而本轮修的正是"这三种状态被压成一个 None"——所以测试必须能精确构造它们。
    """
    row = S.Literature(
        lit_id=lit_id, title=f"Leased {lit_id}", type="J", summary="", path=path,
        processed=processed, source_request_ids=[], dedup_key=f"title:leased {lit_id}|*",
        added_at="2026-01-01T00:00:00+00:00", claimed_by=claimed_by,
        lease_until=lease_until, mine_attempts=mine_attempts,
    )
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="test_leased")


# =========================================================================== cli：角色清单


def test_cli_tools_role_accepts_roles_from_schema(tmp_path: Path, capsys) -> None:
    """`--role` 的候选必须覆盖 `schema.ROLES` 的全部角色。

    这一条是 `DEVELOPMENT.md` §10-D2（标高）记的缺陷：函数体从 `ROLES` 读，
    而 argparse 层写死 `["A","B","C","D"]` ⇒ `tools --role E` 被 argparse 以
    退出码 2 拒掉。E/F/G/H 都已有工具，所以这不是"多此一举的参数校验"，
    而是"角色即权限面"这句可打印事实只覆盖了 A–D。
    """
    st = _ws(tmp_path)
    for role in ("E", "H"):
        rc = cli.main(["--root", str(st.root), "tools", "--role", role])
        out = capsys.readouterr().out
        assert rc == 0, f"角色 {role} 应当被接受"
        assert f"角色 {role} 可用工具" in out


def test_cli_tools_role_negative_control_still_rejects_unknown_role(tmp_path: Path) -> None:
    """负控：放开的只是词表内的角色；`--role Z` 必须仍被拒（退出码 2）。

    没有这条，"choices 检查整个被删掉"也能通过上面那条正向断言。
    """
    st = _ws(tmp_path)
    with pytest.raises(SystemExit) as ei:
        cli.main(["--root", str(st.root), "tools", "--role", "Z"])
    assert ei.value.code == 2


# =========================================================================== cli：status


def test_cli_status_lists_every_table_declared_in_schema(tmp_path: Path, capsys) -> None:
    """`status` 必须按 `S.TABLES` 逐张报告 —— 不是写死的 4 张。

    原先写死 `("search_requests","literature","concepts","relations")`，而
    `Store.stats()` 返回全部 15 张 ⇒ 另外 11 张（analysis_reports / experiments /
    documents / …）在"库长什么样"的第一入口里一个字都不显示。
    这里往 `usage_ledger`（不在旧名单里）插一行，并断言它带真实行数出现。
    """
    st = _ws(tmp_path)
    ledger = st.data / S.TABLES["usage_ledger"]["file"]
    ledger.write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": [{"usage_id": "0000"}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    assert cli.main(["--root", str(st.root), "status"]) == 0
    out = capsys.readouterr().out
    missing = [t for t in S.TABLES if t not in out]
    assert not missing, f"这些表在 status 输出里不见了：{missing}"
    assert "usage_ledger" in out and "行数=1" in out, out


def test_cli_status_negative_control_reports_zero_rows_instead_of_hiding_tables(
    tmp_path: Path, capsys
) -> None:
    """负控：空库也要把表名全部列出来（只是行数为 0），不许"没数据就不显示"。"""
    st = _ws(tmp_path)
    assert cli.main(["--root", str(st.root), "status"]) == 0
    out = capsys.readouterr().out
    assert sum(1 for t in S.TABLES if t in out) == len(S.TABLES)
    assert "行数=0" in out


# =========================================================================== cli：submit


def test_cli_submit_uses_the_single_id_allocator(tmp_path: Path, capsys) -> None:
    """取号必须走 `interactions.next_prefixed_id`（max+1），不是 `len(rows)+i+1`。

    构造：表里只有 `r-0005`。唯一判据给 `r-0006`；旧的 `len+1` 写法会给 `r-0002`
    （而且它没有上限，行数过万会静默产出 `r-10000`）。
    """
    from agentflow import interactions as X

    st = _ws(tmp_path)
    add_request(st, "r-0005")
    expected_first = X.next_prefixed_id(st.rows("search_requests"), "request_id", "r")
    assert expected_first == "r-0006", "前置条件：唯一判据应当给 r-0006"

    rc = cli.main(["--root", str(st.root), "submit", "--topic", "群论", "--by", "cli-test"])
    out = capsys.readouterr().out
    ids = sorted(r["request_id"] for r in st.rows("search_requests"))
    assert rc == 0 and "r-0006" in out and ids == ["r-0005", "r-0006"], out


def test_cli_submit_negative_control_batch_ids_do_not_collide(tmp_path: Path, capsys) -> None:
    """负控：一次交多条时不许撞号（旧写法在 n 被 while 改过之后确实会错）。"""
    st = _ws(tmp_path)
    add_request(st, "r-0001")
    payload = tmp_path / "batch.json"
    payload.write_text(json.dumps([{"topic": "a"}, {"topic": "b", "mode": "broad"}, {"topic": "c"}]),
                       encoding="utf-8")

    assert cli.main(["--root", str(st.root), "submit", "--file", str(payload)]) == 0
    capsys.readouterr()
    ids = sorted(r["request_id"] for r in st.rows("search_requests"))
    assert ids == ["r-0001", "r-0002", "r-0003", "r-0004"], ids
    assert len({r["request_id"] for r in st.rows("search_requests")}) == 4


def test_cli_submit_invalid_batch_writes_nothing_and_exits_2(tmp_path: Path, capsys) -> None:
    """非法输入 ⇒ 退出码 2 + stderr 说明，且整批一条不写（不是"写了一半"）。

    第 2 条 topic 为空会让 `SearchRequest.validate()` 抛 —— 事务是"异常即不提交"，
    所以这里断言的是"原子性"，而不是"某一行被跳过"。
    """
    st = _ws(tmp_path)
    payload = tmp_path / "bad.json"
    payload.write_text(json.dumps([{"topic": "ok"}, {"topic": "  "}]), encoding="utf-8")

    rc = cli.main(["--root", str(st.root), "submit", "--file", str(payload)])
    err = capsys.readouterr().err
    assert rc == 2, "非法输入必须以退出码 2 结束（而不是 traceback 或 0）"
    assert "整批未写入" in err and "不合法" in err, err
    assert st.rows("search_requests") == [], "事务失败后不许留下半批"


def test_cli_submit_precise_without_content_is_a_readable_failure(tmp_path: Path, capsys) -> None:
    """`--mode precise` 缺 `--content` ⇒ 退出码 2 + 一行原因（不是 traceback）。"""
    st = _ws(tmp_path)
    rc = cli.main(["--root", str(st.root), "submit", "--mode", "precise", "--topic", "群论"])
    err = capsys.readouterr().err
    assert rc == 2 and "content_description" in err, err
    assert st.rows("search_requests") == []


def test_cli_submit_negative_control_valid_precise_request_succeeds(tmp_path: Path, capsys) -> None:
    """负控：给了 content 的 precise 请求必须成功（否则上面那条只是"永远失败"）。"""
    st = _ws(tmp_path)
    rc = cli.main(["--root", str(st.root), "submit", "--mode", "precise",
                   "--topic", "群论", "--content", "交换律在群上的表述"])
    capsys.readouterr()
    rows = st.rows("search_requests")
    assert rc == 0 and len(rows) == 1 and rows[0]["mode"] == "precise"


# =========================================================================== cli：repair


def _drifted_store(tmp_path: Path) -> Store:
    """造一个 `related_concepts` 被改坏（仍升序）的自洽库 —— verify 报 related_drift。"""
    st = _ws(tmp_path)
    write_library_file(st, "0000/source.txt", "text")
    add_request(st, "r-0001", done=True, result_lit_ids=["0000"])
    add_literature(st, "0000", path="0000/source.txt", processed=True, source_request_ids=["r-0001"],
                   dedup_key="title:t|*")
    add_concept(st, "0000", "group", related_concepts=[])
    add_concept(st, "0001", "abelian group", related_concepts=[])
    add_relation(st, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True,
                 description="d", group_key="0000|0001")
    return st


def test_cli_repair_refuses_to_act_without_the_explicit_flag(tmp_path: Path, capsys) -> None:
    """`--related` 原先是个被忽略的开关：不带它也会重写 concepts 表。

    一个"声明了却不起作用"的选项比没有更危险 —— 调用方以为在做只读检查，实际已经
    改了知识表。这里断言 fail-closed：退出码 2、stderr 说明、表的字节一个都没动。
    """
    st = _drifted_store(tmp_path)
    before = (st.data / "concepts.json").read_bytes()

    rc = cli.main(["--root", str(st.root), "repair"])
    err = capsys.readouterr().err
    assert rc == 2 and "--related" in err, err
    assert (st.data / "concepts.json").read_bytes() == before, "没给开关就不许写知识表"


def test_cli_repair_related_recomputes_the_derived_field(tmp_path: Path, capsys) -> None:
    """负控（也是正向）：显式给 `--related` 时必须真的把派生态修好。"""
    st = _drifted_store(tmp_path)
    rc = cli.main(["--root", str(st.root), "repair", "--related"])
    capsys.readouterr()
    rows = {r["concept_id"]: r for r in st.rows("concepts")}
    assert rc == 0
    assert rows["0000"]["related_concepts"] == ["0001"]
    assert rows["0001"]["related_concepts"] == ["0000"]


# =========================================================================== cli：verify 退出码


def test_cli_verify_exit_code_is_nonzero_when_errors_exist(tmp_path: Path, capsys) -> None:
    """查过了、发现问题必须退出码 1 —— 校验器的默认行为要能当门用。

    原先只有 `--strict` 才返回非零 ⇒ `agentflow verify` 在库确实有 error 时
    退出码仍是 0，"未报错"被读成"无问题"（`draft/17` §6.3 的教训）。
    """
    st = _drifted_store(tmp_path)
    _mutate(st, "relations", lambda rows: rows[0].__setitem__("lit_id", "0009"))  # dangling_lit

    rc = cli.main(["--root", str(st.root), "verify"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "**有错误**" in out


def test_cli_verify_negative_control_clean_data_exits_zero(clean_store: Store, capsys) -> None:
    """负控：自洽数据必须退出码 0（否则上面那条只是"永远返回 1"）。

    用 `clean_store`（conftest 里那份 verify 零错误零警告的数据集）——本文件其他
    用例用的 `_drifted_store` 故意带 `related_drift` 警告，不能拿来当"干净"的负控。
    """
    assert cli.main(["--root", str(clean_store.root), "verify"]) == 0
    assert cli.main(["--root", str(clean_store.root), "verify", "--strict"]) == 0
    capsys.readouterr()


def test_cli_verify_strict_promotes_warnings_and_default_does_not(tmp_path: Path, capsys) -> None:
    """三态：`error` 一律失败；`warning` 只在 `--strict` 下算失败。

    这条把"0 通过 / 1 发现问题"里的两级分开，避免"退出码非 0"被含糊地当成一种失败。
    """
    st = _drifted_store(tmp_path)  # concepts.related_concepts=[] ⇒ related_drift（warning）

    assert cli.main(["--root", str(st.root), "verify"]) == 0
    out = capsys.readouterr().out
    assert "WARN" in out and "ERR " not in out, out
    assert cli.main(["--root", str(st.root), "verify", "--strict"]) == 1
    capsys.readouterr()


# =========================================================================== cli：run-a / run-b


def test_cli_run_a_exit_code_reflects_terminal_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    """`run-a` 的终局失败（gave_up / search_failed）必须退出码非 0。

    只 monkeypatch `AgentA.run` 的返回值（不改它的实现）：这里测的是 CLI 的
    退出码映射，而不是 AgentA 的行为。配置里把 provider 换成未知名字 + 关掉下载，
    保证这条用例不碰网络。
    """
    st = _ws(tmp_path)
    (st.root / "config.yaml").write_text("agent_a:\n  download: false\n  providers: [selftest]\n",
                                         encoding="utf-8")
    monkeypatch.setattr(AgentA, "run",
                        lambda self, max_requests=None: {"gave_up": 1, "outcome": None})
    assert cli.main(["--root", str(st.root), "run-a", "--once"]) == 1
    capsys.readouterr()


def test_cli_run_a_negative_control_normal_run_exits_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    """负控：正常收敛（含"队列空"）必须退出码 0 —— "没做"不是失败。"""
    st = _ws(tmp_path)
    (st.root / "config.yaml").write_text("agent_a:\n  download: false\n  providers: [selftest]\n",
                                         encoding="utf-8")
    monkeypatch.setattr(AgentA, "run", lambda self, max_requests=None: {
        "gave_up": 0, "outcome": None, "skipped_reason": "no_pending_request"})
    assert cli.main(["--root", str(st.root), "run-a", "--once"]) == 0
    capsys.readouterr()


def test_cli_run_b_exit_code_reflects_extraction_failures(tmp_path: Path, monkeypatch, capsys) -> None:
    """`run-b`：有文献抽取失败（未置 processed，会重试）⇒ 退出码 1。"""
    st = _ws(tmp_path)
    monkeypatch.setattr(AgentB, "run", lambda self, max_docs=None: {"failed": 2, "processed": 3})
    assert cli.main(["--root", str(st.root), "run-b", "--once"]) == 1
    err = capsys.readouterr().err
    assert "抽取失败" in err, err


def test_cli_run_b_negative_control_no_failures_exits_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    """负控：没有抽取失败 ⇒ 0（包括"队列空"这一轮）。"""
    st = _ws(tmp_path)
    monkeypatch.setattr(AgentB, "run", lambda self, max_docs=None: {
        "failed": 0, "processed": 0, "skipped_reason": "no_unprocessed_literature"})
    assert cli.main(["--root", str(st.root), "run-b", "--once"]) == 0
    capsys.readouterr()


# =========================================================================== cli：analyze


def test_cli_analyze_exits_1_when_no_conclusion_was_reached(tmp_path: Path, capsys) -> None:
    """分派失败/没数据 ⇒ 退出码 1 + stderr 结论，且不崩（persist 会拒表外 kind）。

    `AnalysisReport.ok=False` 的含义是"这次没能给出结论"，与"分析完成、结论是没找到"
    是两件事；退出码必须能区分，否则调用方下一步的动作完全相反。
    """
    st = _ws(tmp_path)
    rc = cli.main(["--root", str(st.root), "analyze", "--text", "今天天气不错"])
    err = capsys.readouterr().err
    assert rc == 1, err
    assert "分析未给出结论" in err and "关键词未命中" in err, err
    assert "无法分派" in err, f"人话结论也要给出来（否则调用方不知道该换什么说法）：{err}"
    assert st.rows("analysis_reports") == [], "kind=unknown 的报告不该进表（persist 的硬规则）"


def test_cli_analyze_negative_control_success_registers_a_report(tmp_path: Path, capsys) -> None:
    """负控：有数据的正常分析必须退出码 0 并且登记一行报告（失败与成功都要能区分）。"""
    st = _drifted_store(tmp_path)  # 1 条关系 ⇒ hottest 有可统计对象
    rc = cli.main(["--root", str(st.root), "analyze", "--kind", "hottest"])
    out = capsys.readouterr().out
    assert rc == 0, out
    rows = st.rows("analysis_reports")
    assert len(rows) == 1 and rows[0]["kind"] == "hottest"
    assert "报告已登记" in out


# =========================================================================== cli：load_config


def test_cli_load_config_reports_the_real_yaml_error(tmp_path: Path) -> None:
    """解析失败必须报真正的那个错误（YAML 语法），不许伪装成 JSON 错误。

    旧写法把 `import yaml` 与 `safe_load` 放在同一个 `try` 里：yaml 装上了，
    但这个文件语法不对，于是掉进 `except` 去试 JSON，最后报的是 JSON 的
    `Expecting value: line 1 column 1` —— 一次 YAML 缩进错误被说成"文件格式完全不对"，
    排查方向被彻底带偏。
    """
    (tmp_path / "config.yaml").write_text("agent_a:\n  providers: [a\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        cli.load_config(tmp_path)
    msg = str(ei.value)
    assert "YAML" in msg, msg
    assert "JSON" not in msg, f"不许把 YAML 错误报成 JSON 错误：{msg}"


def test_cli_load_config_negative_controls(tmp_path: Path) -> None:
    """负控：文件不存在 ⇒ `{}`（不是错误）；JSON 配置文件仍能读（YAML 是 JSON 超集）。"""
    assert cli.load_config(tmp_path) == {}
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"agent_a": {"providers": ["fixture"]}}), encoding="utf-8")
    assert cli.load_config(tmp_path, str(p)) == {"agent_a": {"providers": ["fixture"]}}


# =========================================================================== agent_a


def test_claim_outcome_claimed_is_false_and_true_without_truthiness_folding() -> None:
    """`ClaimOutcome.claimed` 是"取到了没"的唯一读法（零测试提及的公开 API）。

    断言它如实反映 `request is None`，而不是"空 dict 也算取到"这类真值折叠。
    """
    assert ClaimOutcome().claimed is False
    assert ClaimOutcome(request={"request_id": "r-0001"}).claimed is True
    assert ClaimOutcome(request={}).claimed is True, "取到了但行是空的 ≠ 没取到（两个概念）"


def test_agent_a_selftest_passes_and_actually_checks_something(capsys) -> None:
    """`python -m agentflow.agent_a` 的自检必须真的在检查（而不是输出 0 行、退出码 0）。

    `scripts/release_check.py` 第 2 项按退出码判定；在补 `__main__` 之前，
    `agent_a` 输出 0 行、退出码 0，旧判据会把它读成"自检通过"。
    """
    assert agent_a._selftest() == 0
    out = capsys.readouterr().out
    assert out.count("[PASS]") >= 15, out
    assert "[FAIL]" not in out and "项通过" in out


def test_agent_a_selftest_negative_control_can_fail(monkeypatch, capsys) -> None:
    """负控：把取任务顺序的唯一判据打断后，自检必须返回非零。

    没有这条，"自检永远返回 0"也能通过上面那条正向断言 —— 而"永远通过的自检"
    比没有自检更坏（它会签发一个假的绿灯）。
    """
    from agentflow import agent_a as A

    monkeypatch.setattr(A.X, "order_pending_requests", lambda rows, **kw: [])
    assert agent_a._selftest() == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out


def test_agent_a_module_runs_as_a_script_with_nonempty_output() -> None:
    """`python -m agentflow.agent_a` 的可运行契约：退出码 0 且有真实输出。"""
    r = _run_module("agent_a")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout and "自检" in r.stdout
    assert "[FAIL]" not in r.stdout


# =========================================================================== agent_b


def test_agent_b_selftest_passes_and_actually_checks_something(capsys) -> None:
    """`python -m agentflow.agent_b` 的自检必须真的在检查（同 agent_a 的理由）。"""
    assert agent_b._selftest() == 0
    out = capsys.readouterr().out
    assert out.count("[PASS]") >= 12 and "[FAIL]" not in out, out


def test_agent_b_selftest_negative_control_can_fail(monkeypatch, capsys) -> None:
    """负控：让租约判据恒真（"所有租约都过期"）后，自检必须返回非零。"""
    from agentflow import agent_b as B

    monkeypatch.setattr(B, "lease_expired", lambda *a, **kw: True)
    assert agent_b._selftest() == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_agent_b_module_runs_as_a_script_with_nonempty_output() -> None:
    """`python -m agentflow.agent_b` 的可运行契约。"""
    r = _run_module("agent_b")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout and "自检" in r.stdout
    assert "[FAIL]" not in r.stdout


def test_agent_b_claim_states_are_three_distinguishable_values(store: Store) -> None:
    """取文献的三态：队列空 / 全被别人占着 / 全被放弃，必须是三个不同的 `skipped_reason`。

    这正是本轮修的缺陷：`_claim()` 原先返回 `dict | None`，`run_once()` 无论哪种情况
    都写 `no_unprocessed_literature` —— 于是"有活，只是在别人手里"被报成"队列空了"，
    运维会以为没事可做。
    """
    from agentflow.store import make_lease

    b = AgentB(store, extractor=_StubExtractor(), extract_text=lambda p: _TextDoc("x"),
               config={"lease_seconds": 900, "max_attempts": 3})

    empty = b.run_once()
    assert empty.skipped_reason == "no_unprocessed_literature"

    _add_leased_literature(store, "0000", claimed_by="agent-B-other", lease_until=make_lease(900))
    leased = b.run_once()
    assert leased.skipped_reason == "pending_literature_all_leased"
    assert leased.skipped_lease_active == 1 and leased.gave_up == 0

    _add_leased_literature(store, "0001", mine_attempts=3)
    gave = b.run_once()
    assert gave.skipped_reason == "no_claimable_literature" and gave.gave_up == 1

    assert len({empty.skipped_reason, leased.skipped_reason, gave.skipped_reason}) == 3, \
        "三态不许压成同一个值"


def test_agent_b_run_once_negative_control_empty_queue_is_not_reported_as_leased(
    store: Store,
) -> None:
    """负控：真空队列必须报 `no_unprocessed_literature`，不许错报成"全被别人占着"。"""
    b = AgentB(store, extractor=_StubExtractor(), extract_text=lambda p: _TextDoc("x"),
               config={"lease_seconds": 900})
    res = b.run_once()
    assert res.skipped_reason == "no_unprocessed_literature"
    assert res.skipped_lease_active == 0 and res.gave_up == 0


def test_agent_b_batch_run_exposes_the_claim_audit_fields(store: Store) -> None:
    """`run()` 的返回必须带 `skipped_lease_active` / `gave_up`（否则"为什么没干活"不可观察）。"""
    from agentflow.store import make_lease

    _add_leased_literature(store, "0000", claimed_by="agent-B-other", lease_until=make_lease(900))
    b = AgentB(store, extractor=_StubExtractor(), extract_text=lambda p: _TextDoc("x"),
               config={"lease_seconds": 900, "max_attempts": 3})
    out = b.run(max_docs=None)
    assert out["skipped_reason"] == "pending_literature_all_leased"
    assert out["skipped_lease_active"] == 1 and out["gave_up"] == 0
    assert "reprocess" in out, "run() 仍然要跑定向重抽取"


def test_agent_b_seed_read_failure_is_visible_to_the_extractor(store: Store, monkeypatch) -> None:
    """概念表读不出来时，抽取器必须收到 `seed_concepts_error`，不许静默退化成空种子。

    后果链条（模块自己的 docstring 写的）：没有种子 ⇒ 定义句只产出一个概念名 ⇒
    关系因 `len(concept_ids) < 2` 全部被丢弃 ⇒ 症状是"文献处理完了却一条关系都没新增"，
    而且没有任何报错。种子内容只是提示，但"读不到"这件事必须被看见。
    """
    write_library_file(store, "0000/a.txt", "An abelian group is a group.")
    add_literature(store, "0000", path="0000/a.txt")

    real_rows = store.rows

    def fake_rows(table: str):
        if table == "concepts":
            raise StoreError("selftest：概念表读不出来")
        return real_rows(table)

    monkeypatch.setattr(store, "rows", fake_rows)
    ext = _StubExtractor()
    b = AgentB(store, extractor=ext, extract_text=lambda p: _TextDoc("An abelian group is a group."),
               config={"lease_seconds": 900})
    b.run_once()
    meta = ext.seen_meta[0]
    assert "seed_concepts_error" in meta, meta
    assert "概念表读不出来" in meta["seed_concepts_error"]


def test_agent_b_seed_negative_control_no_error_key_when_the_table_is_readable(store: Store) -> None:
    """负控：能读到概念表时不许出现 `seed_concepts_error`（这个键的存在本身就是告警）。"""
    write_library_file(store, "0000/a.txt", "An abelian group is a group.")
    add_literature(store, "0000", path="0000/a.txt")
    ext = _StubExtractor()
    b = AgentB(store, extractor=ext, extract_text=lambda p: _TextDoc("An abelian group is a group."),
               config={"lease_seconds": 900})
    b.run_once()
    meta = ext.seen_meta[0]
    assert "seed_concepts_error" not in meta, meta


# =========================================================================== agent_c


@pytest.mark.parametrize("kind", ["hottest", "cold", "gaps"])
def test_analyzer_ok_is_false_when_there_is_no_relation_data(tmp_path: Path, kind: str) -> None:
    """关系表为空时 `ok=False` —— 与 `AnalysisReport.ok` 的 docstring 一致。

    docstring 逐字写着 "False 表示'这次没能给出结论'（概念解析不到、关系表为空等）"，
    而实现原先返回默认的 `ok=True`：工具层返回的就是 `.to_dict()`，调用方 `if res["ok"]`
    会把"数据还没进来"读成"统计做完了、结果为空"。docstring 与实现矛盾时以实现为准改
    的一方是 docstring，这里反过来：代码错了，因为 docstring 的三态语义才是设计。
    """
    st = _ws(tmp_path)
    add_concept(st, "0000", "group")
    c = AgentC(st)
    rep = {"hottest": c.hottest, "cold": c.cold, "gaps": c.gaps}[kind]()
    assert rep.ok is False, f"{kind} 在空关系表上不许报 ok=True"
    assert "关系表为空" in rep.summary
    assert rep.error and "关系表为空" in rep.error
    assert rep.payload  # 结论仍然是可读的（不是空对象）


@pytest.mark.parametrize("kind", ["hottest", "cold", "gaps"])
def test_analyzer_ok_negative_control_true_when_data_exists(tmp_path: Path, kind: str) -> None:
    """负控：有数据时 `ok` 必须为 True（否则上面那条只是"永远 False"）。"""
    st = _drifted_store(tmp_path)
    c = AgentC(st)
    rep = {"hottest": c.hottest, "cold": c.cold, "gaps": c.gaps}[kind]()
    assert rep.ok is True, f"{kind} 在有关系数据时应当给出结论"


def test_service_limit_rejects_a_non_integer_instead_of_silently_capping(tmp_path: Path) -> None:
    """`contradictions(limit="三")` 必须抛，而不是静默按服务上限算。

    静默的后果：返回的 `meta["limit"]` 是上限值，调用方以为"我限了 3 条"，
    实际拿到的是"能取多少取多少" —— 一个读不懂的参数被读成另一个值。
    """
    st = _drifted_store(tmp_path)
    with pytest.raises(ValueError) as ei:
        AgentC(st).contradictions(limit="三")
    assert "limit" in str(ei.value)
    with pytest.raises(ValueError):
        AgentC(st).structural_duplicates(limit="三")


def test_service_limit_negative_control_valid_and_none_are_honored(tmp_path: Path) -> None:
    """负控（三态）：`limit=1` 生效；`limit=None` 用上限；两者都不抛。"""
    from agentflow.agent_c import SERVICE_MAX_CONTRADICTIONS

    st = _drifted_store(tmp_path)
    c = AgentC(st)
    assert c.contradictions(limit=1)["limit"] == 1
    assert c.contradictions(limit=None)["limit"] == SERVICE_MAX_CONTRADICTIONS
    assert c.structural_duplicates(limit=1)["checked"] is True


def test_service_depth_rejects_a_non_integer_and_honors_valid_values(tmp_path: Path) -> None:
    """`neighbors` 的 `depth` / `max_nodes` 同一口径：读不懂就抛，合法就照用。"""
    st = _drifted_store(tmp_path)
    c = AgentC(st)
    with pytest.raises(ValueError):
        c.neighbors("0000", depth="深")
    with pytest.raises(ValueError):
        c.neighbors("0000", max_nodes="多")
    ok = c.neighbors("0000", depth=2)
    assert ok["checked"] is True and ok["depth"] == 2
    assert c.neighbors("0000")["depth"] == 1, "不传时用默认口径（不是失败）"


def test_score_weights_typo_fails_closed_and_valid_override_applies(tmp_path: Path) -> None:
    """`score_weights` 写错必须当场炸；写对必须生效。

    权重是评分判据本身：静默退回默认值 ⇒ 报告照常产出、口径已悄悄变掉、
    没有任何地方会暴露这件事。
    """
    st = _drifted_store(tmp_path)
    with pytest.raises(ValueError) as ei:
        AgentC(st, config={"score_weights": {"hop": "high"}})
    assert "score_weights" in str(ei.value)

    c = AgentC(st, config={"score_weights": {"hop": 9.0}})
    assert c.weights["hop"] == 9.0
    assert c.weights["quote_true"] > 0, "未覆盖的权重仍取默认值"


def test_service_ceiling_config_typo_fails_closed_and_missing_key_uses_default(tmp_path: Path) -> None:
    """配置读法的三态：键不在用默认；键在但读不动抛。

    旧写法把两者都压成"用 default"，于是 `service_max_nodes:"很多"` 静默按 5 跑 ——
    "上限"这类值的静默漂移不报错，它只是让结果悄悄变了。
    """
    from agentflow.agent_c import SERVICE_MAX_NODES

    st = _drifted_store(tmp_path)
    c_bad = AgentC(st, config={"service_max_nodes": "很多"})
    with pytest.raises(ValueError) as ei:
        c_bad.neighbors("0000")
    assert "service_max_nodes" in str(ei.value)

    c_ok = AgentC(st, config={})
    res = c_ok.neighbors("0000", max_nodes=10 ** 6)
    assert res["checked"] is True
    assert res["max_nodes"] == SERVICE_MAX_NODES, "没配这个键 ⇒ 用默认上限"


def test_service_tool_names_resolve_the_documented_collision(tmp_path: Path) -> None:
    """`graph.neighbors`（低层）与 `graph.svc_neighbors`（服务版）必须并存且契约不同。

    这是 INVENTORY 4.5#11 点的那处"自陈的命名冲突"：早期 docstring 说它未决，
    而实现已经用 `svc_*` 解决；同一份 docstring 里两段互相矛盾。这里钉住实现侧
    的结论：两个名字同时存在，服务版带 `checked` 三态，低层版没有。
    """
    from agentflow.tools.graph_tools import register as register_graph_tools

    st = _drifted_store(tmp_path)
    reg = ToolRegistry(name="audit-collision")
    register_graph_tools(reg, store=st)
    added = AgentC(st).register_tools(reg)

    names = set(reg.names())
    assert {"graph.neighbors", "graph.svc_neighbors"} <= names
    assert "graph.svc_neighbors" in added and "graph.svc_relations_between" in added
    low, svc = reg.get("graph.neighbors"), reg.get("graph.svc_neighbors")
    assert low.summary != svc.summary, "两个名字必须是两种契约，不能互相覆盖"
    assert "checked" in svc.returns and "checked" not in low.returns

    service = reg.call("graph.svc_neighbors", concept_id="0000")
    lowlevel = reg.call("graph.neighbors", concept_id="0000")
    assert "checked" in service.data and "nodes" in service.data
    assert "checked" not in lowlevel.data and "neighbors" in lowlevel.data


def test_agent_c_writes_only_analysis_reports_and_never_the_knowledge_tables(tmp_path: Path) -> None:
    """只读角色的写入面：跑四个分析器 + persist 之后，三张知识表逐字节不变。

    这是 C 的硬规则（DESIGN §2）：一旦 C 能写知识表，它就成了绕过 B 引文逐字回验的
    写入路径。顺带钉住另一个边界：`gaps()` 默认 `submit_requests=False` 时
    `search_requests` 也不许动（I3 的写入口只在编排层显式开启）。
    """
    st = _drifted_store(tmp_path)
    c = AgentC(st)
    before = {t: (st.data / S.TABLES[t]["file"]).read_bytes()
              for t in ("literature", "concepts", "relations", "search_requests")}

    c.hottest(top_n=3).persist()
    c.cold(top_n=3).persist()
    c.gaps(limit=3).persist()
    c.contradictions()
    c.structural_duplicates()
    c.neighbors("0000")

    after = {t: (st.data / S.TABLES[t]["file"]).read_bytes() for t in before}
    for table in before:
        assert before[table] == after[table], f"{table} 被 C 改动了（C 必须只读）"
    assert len(st.rows("analysis_reports")) == 3, "它自己的产出（analysis_reports）应当照常登记"


# =========================================================================== 交叉：cli 不越权


def test_cli_never_writes_the_knowledge_tables_for_readonly_subcommands(tmp_path: Path, capsys) -> None:
    """`status` / `tools` / `verify` 是只读子命令：跑完三张知识表必须逐字节不变。

    一个"顺手初始化/顺手修一下"的入口会让"看一眼"变成一次写入 —— 而它不会报错。
    """
    st = _drifted_store(tmp_path)
    before = {t: (st.data / S.TABLES[t]["file"]).read_bytes() for t in ("concepts", "relations")}

    assert cli.main(["--root", str(st.root), "status"]) == 0
    assert cli.main(["--root", str(st.root), "verify"]) in (0, 1)
    capsys.readouterr()

    after = {t: (st.data / S.TABLES[t]["file"]).read_bytes() for t in before}
    assert before == after
