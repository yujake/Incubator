"""写作期探针：把一个 D 问题推进到 needs_evidence，观察台账的产生与 verify 检查。

流程：造数据集 → 跑 pipeline（C+D）→ 再让 D 从全部已登记报告 ingest（含 cold）
→ 那个"完全孤立概念"的问题必然证据不足 → 提交 gap → 台账产生。
随后跑 verify，观察 ledger_* 检查项是否生效。

用法：python tools/probe_gap_ledger.py [目标工作区]

## 默认落点不在仓库里（`R3` 的副作用，`draft/28` 83.5 第 1 条）

改前这里是 `dest = ... else ROOT / "gapprobe"` —— 不带参数跑一次就往仓库里写
16 个产物文件，把"谁在写被审对象"这件事搅浑（实测：一次窗口污染，16 个
`gapprobe/data/*.json`）。现在照抄 `scripts/release_check.py::_artifact_path()`
的口径：主落点仓外（`ROOT.parent / "temp"`，仓库根是 `agentflow/`，所以它落在
工作区根下的 `temp/`），建不出来就退到 `tempfile.mkdtemp()`。落点会打印出来，
产物在哪仍然找得到。

## 缺输入以清晰消息 + 非零退出码收场（`draft/28` 83.5 第 2 条）

"源数据不存在"是可预期的输入缺失（三态纪律：这是 `unknown`，不是 `fail`，
更不是崩溃）。改前它在 `src / "concepts.json"` 那一行抛 `FileNotFoundError`
traceback；现在开跑前先逐张核源表，缺哪张就指名道姓地报出来并以退出码 2 收场
（2 = 没查成；0 = 跑通；1 = 跑通了但结论出乎预期 —— 本探针今天不用 1）。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentflow import schema as S  # noqa: E402
from agentflow.agent_d import AgentD, install_d_tools  # noqa: E402
from agentflow.pipeline import run_pipeline  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools.research_tools import LEDGER_FILE  # noqa: E402

#: 本探针直接拷的三张源表（在 `--src` 指到的目录里找）。
SEED_TABLES = ("concepts", "relations", "literature")

#: 主落点：仓外（工作区根下的 `temp/`，本机即 `ROOT.parent / "temp"`）——
#: `ROOT` 是 `agentflow/`，工作区根在它上一级。
ARTIFACT_DIR = ROOT.parent / "temp"

#: 退出码：0 = 跑通；2 = 没查成（输入缺失等可预期原因）。不许把它们折叠成同一个数。
EXIT_OK = 0
EXIT_UNKNOWN = 2


def _artifact_path() -> tuple[pathlib.Path, str]:
    """选一个不落在仓库里的落点（`release_check._artifact_path()` 的同一条口径）。

    1. 首选 `ARTIFACT_DIR / "gapprobe"`（工作区根相对即 `temp/` 下的 `gapprobe/` 子目录）；
    2. 它建不出来（权限 / 磁盘 / 只读文件系统，Windows 上路径带 NUL 时抛的是
       `ValueError` 而不是 `OSError`）⇒ 回退到 `tempfile.mkdtemp()`。

    绝不回退到 `ROOT / "gapprobe"`：那正是改前那个"跑一次就往仓里写 16 个文件"
    的落点，而它会让"这次审计窗口里被审对象变了没有"这个问题再也答不清楚。
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        fallback = pathlib.Path(tempfile.mkdtemp(prefix="agentflow-gapprobe-"))
        return fallback, (
            f"主落点 temp/ 建不出来（{type(exc).__name__}: {exc}）⇒ 落点回退到系统"
            f"临时目录 {fallback}（不回退到仓库里：那个落点会让探针自己改被审对象）"
        )
    return ARTIFACT_DIR / "gapprobe", ""


def _seed_dir() -> tuple[pathlib.Path | None, str]:
    """找那三张源表所在目录，并给出一句可读的说明（找不到就返回 None）。"""
    cand = ROOT / "pipelinedemo" / "data"
    missing = [t for t in SEED_TABLES if not (cand / f"{t}.json").is_file()]
    if not missing:
        return cand, f"源表来自 {cand}"
    return None, (
        f"源数据不存在：{cand} 里缺 {missing}（要的是 "
        f"{[f'{t}.json' for t in SEED_TABLES]}）。\n"
        f"  这是可预期的输入缺失，不是崩溃 —— 请先用 "
        f"`python tools/make_demo_dataset.py` 造出数据集，"
        f"或把 [目标工作区] 与 --src 指到一个已有这三张表的目录。\n"
        f"  （退出码 {EXIT_UNKNOWN} = 没查成；不许把它读成'查过了、没问题'。）"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    src_override = None
    if "--src" in args:
        i = args.index("--src")
        if i + 1 >= len(args):
            print("--src 需要一个目录参数", file=sys.stderr)
            return EXIT_UNKNOWN
        src_override = pathlib.Path(args[i + 1]).resolve()
        del args[i:i + 2]
    if args:
        dest = pathlib.Path(args[0]).resolve()
        dest_note = "落点由调用方显式指定"
    else:
        dest, dest_note = _artifact_path()
    if dest_note:
        print(f"[probe_gap_ledger] {dest_note}", file=sys.stderr)

    if src_override is not None:
        src = src_override
        missing = [t for t in SEED_TABLES if not (src / f"{t}.json").is_file()]
        if missing:
            print(
                f"源数据不存在：--src {src} 里缺 {missing}（可预期的输入缺失）。"
                f"退出码 {EXIT_UNKNOWN} = 没查成。",
                file=sys.stderr,
            )
            return EXIT_UNKNOWN
        src_note = f"源表来自 --src {src}"
    else:
        found, src_note = _seed_dir()
        if found is None:
            print(src_note, file=sys.stderr)
            return EXIT_UNKNOWN
        src = found

    print(f"[probe_gap_ledger] 落点 {dest}；{src_note}")
    if dest.exists():
        import shutil

        shutil.rmtree(dest)
    st = Store(dest)
    st.init(force=True)

    # 直接拷那三张表（省掉造数据）。源表存在性已在上面核过 ⇒ 这里不会再抛
    # FileNotFoundError（改前正是在这一行崩掉的）。
    with st.tx(*SEED_TABLES, actor="probe", note="seed") as tx:
        for t in SEED_TABLES:
            for r in json.loads((src / f"{t}.json").read_text(encoding="utf-8"))["rows"]:
                tx.upsert(t, r)
    # `c-7`：以前这里直接调私有的 `st._atomic_write(...)` —— 既不拿写者锁、也不进事务，
    # 与并发 `tx` 的 `alloc_id` 争同一份 counters ⇒ 计数器漂移（跳号，严重时撞号被
    # `upsert` 静默覆盖）。现在走公开入口 `Store.set_counters()`（它内部拿同一把写者锁）。
    st.set_counters({"lit": 9, "concept": 10, "relation": 15, "question": 0, "report": 0},
                    actor="probe", note="probe_gap_ledger 夹具：把计数器拨到指定位置")

    print("===== 1. 跑 C 的 cold 分析（产生一个'孤立概念'的研究点） =====")
    out = run_pipeline(
        st,
        request="研究冷门概念",
        gap_rounds=1,
        config={"agent_d": {"dedup_by_origin": True}},
        resume=False,
    )
    print(json.dumps({"report_ids": out["report_ids"], "questions": out["questions"],
                      "requests_submitted": out.get("requests_submitted")},
                     ensure_ascii=False, indent=2))

    print("\n===== 2. 让 D 从全部已登记报告 ingest（含 paths 与 cold） =====")
    d = AgentD(st, config={"dedup_by_origin": False}, tools=install_d_tools(st))
    for r in st.rows("analysis_reports"):
        res = d.run_round(r)
        print(f"  报告 {r['report_id']} kind={r['kind']} ingested={res.get('ingested')} "
              f"submitted={res.get('submitted')} assessed="
              f"{[(a['question_id'], a['criteria']) for a in res.get('assessed', [])]}")

    print("\n===== 3. research_questions 现状 =====")
    for r in st.rows("research_questions"):
        print(f"  {r['question_id']} status={r['status']} priority={r['priority']} "
              f"waiting={r['waiting_request_ids']} rels={r['related_relation_ids']}")
        print(f"      gap_reason={(r.get('gap_reason') or '')[:160]}")

    print("\n===== 4. search_requests 现状 =====")
    for r in st.rows("search_requests"):
        print(f"  {r['request_id']} submitted_by={r.get('submitted_by')} mode={r['mode']} "
              f"done={r['done']} outcome={r.get('outcome')} topic={r['topic']!r}")
        print(f"      description={(r.get('description') or '')[:200]}")

    lp = dest / "data" / LEDGER_FILE
    print(f"\n===== 5. 台账 {LEDGER_FILE} 存在={lp.exists()} =====")
    if lp.exists():
        print(lp.read_text(encoding="utf-8"))

    print("\n===== 6. verify（观察 ledger_* 检查） =====")
    from agentflow.verify import verify_all

    rep = verify_all(st)
    # `VerifyReport` 上的是 `errors` / `warnings` 两个 property（列表），
    # 不是 `error_count()` / `warning_count()` 两个方法 —— 改前这两行会让探针
    # 在最后一步以 AttributeError 崩掉（本探针"跑一次留下半个产物"这个形态
    # 与 §83.5 要治的问题是同一类：崩溃点读起来像"内部出错"，其实是调用方
    # 用错了 API）。这里按 property 读，并把两个数字分开报。
    print(f"  错误 {len(rep.errors)} / 警告 {len(rep.warnings)}；checked={rep.checked}")
    for i in rep.issues:
        # `Issue` 的字段是 table / row_id（没有 `where` 这个属性 —— 改前这里
        # 也会 AttributeError，同族于上面那两个错方法名）。
        print(f"  - [{i.level}] {i.code} {i.table}:{i.row_id}: {i.message[:150]}")

    print("\n===== 7. 删掉台账后再 verify（受控偏离的代价：退化为可能重复提问一次） =====")
    if lp.exists():
        lp.unlink()
    rep2 = verify_all(st)
    print(f"  错误 {len(rep2.errors)} / 警告 {len(rep2.warnings)}")
    for i in rep2.issues:
        print(f"  - [{i.level}] {i.code} {i.table}:{i.row_id}: {i.message[:150]}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
