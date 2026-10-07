# -*- coding: utf-8 -*-
"""从 Python 侧生成前端的唯一类型来源 `ui/src/types.ts`（裁定 M2）。

## 为什么是生成物而不是手写

`draft/75 §1.3` 的每一个字段都来自盘上的真读数（`file:line` 级出处）。手写一份
TS 接口就是第二份口径：后端加一个键、前端没跟上时，`tsc` 只会觉得"少了一个可选
字段"，一声不吭。把类型交给这里生成之后，判据可以问一个更硬的问题：
生成物里的键集合与后端在夹具工作区上真读出来的键集合是不是同一批
（`tests/test_webui_contracts.py` 的 C 条）。手改生成物 ⇒ 新鲜度判据必红。

## 本批（W0）覆盖到哪

只覆盖后端此刻真的给得全的那些面：`snapshot()` 的读模型
（`StateSnapshot` / `SessionRow` / `PendingQuestion` / `RunRow` / `OrphanRow` /
`LedgerReading` / `ReportReading`），加上三态词表两个（`Tri` / `ReportTri`）。
W1 的 `readers.py` 会补齐其余面的读数，那时在这里加一段表就行。

其余接口以 TODO 注释留在文件里，并逐条写明还缺哪一个 reader —— 不留空话：
判据要能看出"这个类型为什么还没有"。这些 TODO 只在注释里，不是真正的接口声明
（只有 `render_types()` 里 `_TYPES` 表上的条目才会被生成），所以它们不会被 C 条
误当成"前端多出来的键"。

## 命名（同 `emit_theme.py`）

lint 的 R003 会点"同一个公开名在多个模块里各有一份独立实现"：本包两个生成器
做的事不同，谁也不是谁的转发，所以名字各自具体（`render_types` / `write_types`），
入口私有（`_main`，由 `__main__` 块调用）—— `main` 这个名字在 `cli.py` 已经是
"整套命令行"的入口了。

## 确定性

同样的表一定产出逐字节相同的文件（LF、末尾一个换行、无时间戳、无随机）：
新鲜度判据按字节比对，这是它的前提。

## 用法

    python -m agentflow.web.emit_types
"""

from __future__ import annotations

import argparse
import pathlib
from typing import Sequence

__all__ = ["REPO_REL", "TYPES_PATH_LABEL", "render_types", "write_types"]

#: 相对交付包根（`agentflow/`）的落点。
REPO_REL = ("ui", "src", "types.ts")

#: 生成物头部必须出现的那句（判据读它：手改生成物的人先得把这句话删掉才敢改）。
TYPES_PATH_LABEL = "生成物，勿手改"

#: 文件头。逐字包含 :data:`TYPES_PATH_LABEL` —— 这是"这是一份生成物"的唯一声明点。
_HEADER = """\
// {label}；改 `agentflow/web/emit_types.py` 再重跑：
//   python -m agentflow.web.emit_types
//
// 唯一类型来源（`draft/75 §1` 的 C3 契约）：字段名逐字对应后端它自己的键，
// 不许在这里改名，也不许把后端一定会给的键写成可选。对齐由两条判据守着：
//   - 名字层：`tests/test_webui_contracts.py` 的 C 条（生成物键集合 vs 后端真读数）；
//   - 类型层：`pnpm typecheck`（`tsc --noEmit`，配 `strict` + `noUncheckedIndexedAccess`）。
//
// 手改本文件的任何一处都会让 C 条与新鲜度判据变红 —— 那是刻意的。
""".format(label=TYPES_PATH_LABEL)

#: 三态词表。两套并存是裁定 N1（不许互相顶替）：
#: `computed / unreadable / not_applicable` 是 reviewaccept 那一套（其余面用），
#: `ok / missing / unknown` 只给「交付说明」那一格用。两者在前端都映射到
#: 组件 `TriState` 的三种视觉态，但字符串本身不通用。
_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("Tri", '"computed" | "unreadable" | "not_applicable"',
     "三态（reviewaccept 词表）：算出来了 / 没查成 / 用不着"),
    ("ReportTri", '"ok" | "missing" | "unknown"',
     "交付说明那一格专用的三态（`webui/state.py` 的 `_read_report`）"),
)

#: 逐接口的字段表。每一项 `(TS 名字, 后端出处, ((字段, TS 类型), ...))`。
#: 出处写的是"这个键是从哪段程序读出来的"，不是行号（行号会漂）。
_TYPES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("OptionRow",
     "option_view() —— 一个选项的渲染视图（注意：快照里的 `options` 是这一族对象，"
     "不是裸字符串；`draft/75 §1.3` 那里写的 `string[]` 与盘上读数不一致，以这里为准）",
     (("label", "string"), ("description", "string"), ("multi", "boolean"))),
    ("OrphanGroup",
     "orphan_summary() 的 `groups[]` 元素 —— 按会话分组的「轮次之外的零散事件」",
     (("sid", "string"), ("count", "number"), ("kinds", "string[]"),
      ("first_ts", "string"), ("last_ts", "string"),
      ("first_index", "number"), ("last_index", "number"))),
    ("OrphanSummary",
     "orphan_summary() —— 「轮次之外的零散事件」的汇总读数",
     (("count", "number"), ("groups", "OrphanGroup[]"))),
    ("StateSnapshot",
     "snapshot() —— 工作区盘上事实的只读投影（返回键逐字见它的 docstring）",
     (("root", "string"), ("generated_at", "string"),
      ("sessions", "SessionRow[]"), ("pending_questions", "PendingQuestion[]"),
      ("runs", "RunRow[]"), ("orphans", "OrphanRow[]"),
      ("orphan_summary", "OrphanSummary"), ("last_run", "RunRow | null"),
      ("ledger", "LedgerReading"), ("problems", "string[]"))),
    ("SessionRow",
     "snapshot() 的 `sessions[]` —— 一段会话的读盘读数",
     (("sid", "string"), ("path", "string"), ("events_seen", "number"),
      ("events_listed", "number | null"), ("bad_lines", "number"),
      ("first_ts", "string"), ("last_ts", "string"), ("last_kind", "string"),
      ("last_seq", "number"), ("pending", "number"), ("runs", "number"),
      ("orphans", "number"))),
    ("PendingQuestion",
     "snapshot() 的 `pending_questions[]` —— 一条待答问题（全局，不按会话过滤）",
     (("qid", "string"), ("sid", "string"), ("role", "string"), ("ts", "string"),
      ("timeout_sec", "number | null"), ("text", "string"),
      ("options", "OptionRow[]"), ("multi", "boolean"), ("index", "number"))),
    ("RunRow",
     "snapshot() 的 `runs[]` —— 一趟运行（一条 agent_run_start 到它之后的 agent_run_end）",
     (("sid", "string"), ("role", "string"), ("task", "string"),
      ("start_index", "number"), ("start_ts", "string"), ("steps", "number"),
      ("llm_calls", "number"), ("usd", "number | null"), ("unknown_usd", "number"),
      ("stop_reason", "string"), ("final_chars", "number | null"),
      ("summons", "number | null"), ("messages", "number | null"),
      ("elapsed_sec", "number | null"), ("last_shape", "string"),
      ("end_index", "number | null"), ("end_ts", "string"),
      ("waiting_on", "string[]"), ("waiting", "boolean"),
      ("events_in_run", "number"))),
    ("OrphanRow",
     "snapshot() 的 `orphans[]` —— 轮次之外的一条零散事件（不许折成一趟运行）",
     (("sid", "string"), ("index", "number"), ("kind", "string"),
      ("ts", "string"), ("role", "string"))),
    ("LedgerReading",
     "snapshot() 的 `ledger` —— 台账（第二个独立读数）",
     (("path", "string"), ("events", "number | null"), ("tables", "number | null"),
      ("note", "string"), ("tables_note", "string"))),
    ("ReportReading",
     "_read_report() —— 交付说明 `out/review/REPORT.md` 的读数（二元组 status/text 的字典口径）",
     (("status", "ReportTri"), ("text", "string"))),
    ("CheckpointSpend",
     "检查点里的花销子树（`agent_loop` 写的 `runs/agent-<角色>-<sid>.json`）",
     (("calls", "number"), ("tokens_in", "number"), ("tokens_out", "number"),
      ("usd", "number | null"), ("unknown_usd_calls", "number"))),
    ("Checkpoint",
     "一趟的检查点文件（`runs/agent-<角色>-<sid>.json`；本批没有 reader ⇒ 判据 C 不覆盖它）",
     (("role", "string"), ("sid", "string"), ("task", "string"),
      ("fingerprint", "string"), ("step", "number"), ("stop_reason", "string"),
      ("waiting_for", "string[]"), ("spend", "CheckpointSpend"), ("at", "string"))),
    ("WriteResult",
     "写面端点的统一回执（W3/W4 才有生产者 ⇒ 判据 C 不覆盖它；`id`/`extra` 只是"
     "「有就带上」的两栏，所以写成可选）",
     (("ok", "boolean"), ("tri", "Tri"), ("reason", "string"),
      ("id?", "string"), ("extra?", "Record<string, unknown>"))),
)

#: 本批刻意不生成的接口：逐条写明缺哪一个 reader。
#: 不写成"注释掉的 interface" —— 那会让读者以为它已经在了；这里是明确的欠账清单。
_UNEMITTED: tuple[tuple[str, str], ...] = (
    ("RunView",
     "缺 `webui/readers.py` 的「一趟详情」适配器（W1）；本批 ROUTES 里没有 "
     "`GET /api/run/{sid}`，所以它没有生产者"),
    ("EvidenceView",
     "缺 `readers.evidence_chain(store)`（W1）：`store.rows(\"statements\"/\"conjectures\"/"
     "\"experiments\"/\"review_findings\")` 的适配器"),
    ("ArtifactsView",
     "缺 `readers.artifact_ledger` / `readers.handoffs` / `readers.run_products`（W1）："
     "`artifacts.read_ledger` · `manuscripts.rows` · 六件产物那一路"),
    ("AcceptanceView",
     "缺 `readers.acceptance(root, ...)`（W1）：`reviewaccept.check_review` 的逐条读数"),
    ("MachineView",
     "缺 `readers.machine_readings(root)`（W1）：`toolchain.toolchain_report()` 与 "
     "`settings.load_settings()`（key 走 `ModelSpec.redacted()`）"),
    ("TaskRow", "缺 `store.rows(\"tasks\")` 的适配器（W1 的 readers 那一面）"),
    ("SearchRequestRow", "缺 `store.rows(\"search_requests\")` 的适配器（W1）"),
    ("ConjectureRow", "缺 `store.rows(\"conjectures\")` 的适配器（W1）"),
    ("ExperimentRow", "缺 `store.rows(\"experiments\")` 的适配器（W1）"),
    ("ArtifactRow", "缺 `artifacts.read_ledger` 的行适配器（W1）"),
    ("HandoffRow", "缺 `manuscripts.rows` 的行适配器（W1）"),
    ("SecretaryDecision", "缺 `secretary.decisions_path` 的读法（W1）"),
    ("AcceptanceCheck", "缺 `closing.py` 的 ACCEPTANCE-CHECKS 读者（W1）"),
    ("ReportStyle", "缺 `out/review/REPORT-STYLE.json` 的读者（W1）"),
    ("UsageRow", "缺 `store.rows(\"usage_ledger\")` 的适配器（W1）"),
)


def _default_target() -> pathlib.Path:
    """默认落点（由本文件的位置推出来，不看当前工作目录）。"""
    return pathlib.Path(__file__).resolve().parents[3].joinpath(*REPO_REL)


def _render_interface(name: str, source: str, fields: tuple[tuple[str, str], ...]) -> str:
    """一个接口的 TS 正文（注释里写出处；字段一行一个，判据按行解析）。"""
    lines = [f"/** 出处：{source}。 */", f"export interface {name} {{"]
    for field, ts in fields:
        lines.append(f"  {field}: {ts};")
    lines.append("}")
    return "\n".join(lines)


def render_types() -> str:
    """生成物的正文（纯函数：不碰盘，判据与写盘共用它）。"""
    parts: list[str] = [_HEADER]
    for name, ts, note in _ALIASES:
        parts.append(f"/** {note}。 */\nexport type {name} = {ts};\n")
    for name, source, fields in _TYPES:
        parts.append(_render_interface(name, source, fields) + "\n")
    todo = ["// " + "-" * 74,
            "// 欠账清单：这些接口本批不生成（没有真读数就没有类型）。",
            "// 每一条都写明缺哪一个 reader —— W1 补上读数之后，把它们搬进上面的表。",
            "// " + "-" * 74]
    for name, why in _UNEMITTED:
        todo.append(f"// TODO {name}：{why}。")
    parts.append("\n".join(todo) + "\n")
    return "\n".join(parts)


def write_types(target: str | pathlib.Path | None = None) -> pathlib.Path:
    """把正文写到 `target`（缺省 = 前端工程里的落点），返回落点。"""
    path = pathlib.Path(target) if target is not None else _default_target()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_types())
    return path


def _main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：写文件并打印落点与字节数。"""
    ap = argparse.ArgumentParser(
        prog="python -m agentflow.web.emit_types",
        description="从 Python 侧的表生成前端唯一类型来源 ui/src/types.ts")
    ap.add_argument("--target", default="", help="写到哪个文件（缺省 = 前端工程里的落点）")
    args = ap.parse_args(list(argv) if argv is not None else None)
    path = write_types(args.target or None)
    print(f"{path}（{path.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
