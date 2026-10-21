"""命令行入口。

设计意图：把"能跑起来的最小操作集"固定成几个动词，避免每次都写一次性脚本 ——
一次性脚本正是这类系统后来无法复现的根源。

    python -m agentflow init / submit / run-a / run-b / status / verify / rebuild / repair / demo
    python -m agentflow run --topic "..." --budget-usd 5 --out DIR   # 端到端一条命令
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from . import schema as S
from . import conceptrows as CR   # 并表过渡层：老表写完同步一份新标准（两处同号）
from . import tty
from .console import pin_utf8
from .store import Store, StoreError
from .verify import verify_all

#: 不给 `--root` 时的工作区根：`src/agentflow/cli.py` 的 `parents[2]` = 仓库里的 `agentflow/`。
#: （2026-09-30 更正：这一行原写 `# test/test1/` —— 那是 cli.py 还住在原型
#: `test/test1/src/agentflow/` 时的解析结果，搬到正式版之后注释没跟着改。）
DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def _non_negative_int(raw: str) -> int:
    """argparse 的 `type=`：负数在用法错阶段就被拒（退出码 2 = "没查成"）。

    为什么要这一条（`FINAL-R5-06`）：库层对负 `max_calls` 是显式拒绝（抛 `ValueError`），
    但 CLI 层不接住它 ⇒ 未捕获异常 + traceback + 退出码 1，而 1 在本项目的三态里
    是"查过了、有问题"，真相是"一次都没跑"。用法错本来就该退 2。
    """
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"必须 >= 0（收到 {raw}）")
    return value


def _non_negative_float(raw: str) -> float:
    """argparse 的 `type=`：负数上限在用法错阶段就被拒（与本文件的 `_non_negative_int` 同一个理由）。

    为什么上限不许是负数：`reviewaccept` 把上限与花销做 `>` 比较，负上限会让
    "花了零元"也判成超上限 —— 那是一个看着像"判据红"的用法错。
    用法错退 2（"没查成"），不许让它伪装成 1（"查过了、有问题"）。
    """
    value = float(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"必须 >= 0（收到 {raw}）")
    return value


# ---------------------------------------------------------------- 配置装载


def load_config(root: Path, path: str | None = None) -> dict:
    """读配置。文件不存在 ⇒ 空配置（不是错误，这是"全用默认值"的正常形态）。

    解析失败时只报真正的那个错误。旧写法把 `import yaml` 与 `safe_load`
    放在同一个 `try` 里，于是"YAML 装上了、但这个文件语法不对"会掉进
    `except Exception` 去试 JSON，最后报出来的是JSON 的错误（`Expecting
    value: line 1 column 1 …`）—— 一次 YAML 缩进错误被伪装成"这文件根本不是
    配置格式"，排查方向被彻底带偏。报错的准确性是诊断能力的一部分。
    """
    p = Path(path) if path else (root / "config.yaml")
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # 环境里已装；没有则回退 JSON
    except ImportError:
        # 没有 yaml 依赖时才谈得上"按 JSON 读"，此时报的 JSON 错误才是真原因。
        try:
            return json.loads(text)
        except Exception as e:
            raise SystemExit(f"配置解析失败（{p}；本机无 yaml 依赖，按 JSON 解析）：{e}") from e
    try:
        # YAML 是 JSON 的超集 ⇒ 这里对 .json 配置同样成立，不需要再回退。
        return yaml.safe_load(text) or {}
    except Exception as e:
        raise SystemExit(f"配置解析失败（{p}）：YAML 语法错误：{e}") from e


def make_store(root: Path | None = None) -> Store:
    root = Path(root or DEFAULT_ROOT).resolve()
    return Store(root)


# ---------------------------------------------------------------- 子命令


def cmd_init(args) -> int:
    st = make_store(args.root)
    st.init(force=args.force)
    print(f"[init] 已初始化：{st.data}")
    return 0


def cmd_submit(args) -> int:
    """把一个或一批搜索请求登记进 `search_requests`。

    两条纪律：
    1. 取号只用 `interactions.next_prefixed_id`（全项目唯一的 `r-NNNN` 判据）。本函数原先自己数
       `len(rows) + i + 1` 并靠 `while` 撞号重试 —— 那是第二份取号判据，语义与 `next_prefixed_id`
       的 `max+1` 不同：表里只有 `r-0001`/`r-0003` 时，一个发 `r-0002`、另一个发 `r-0004`
       （`DEVELOPMENT.md` §3 纪律 2："ID 分配器只有一处；新增第二份 = 违规"）。旧写法还没有上限：
       行数过万时会静默产出 `r-10000` 这种越出 4 位空间的号。
    2. 输入不合法 ⇒ 整批不写 + 退出码 2。`row.validate()` 的 `ValueError` 原先在事务中途炸出，
       调用方拿到的是一个 traceback；而"你给的 mode/topic 不合法"是调用方错误，应当以一行说明 +
       非零退出码结束。事务本身是"异常即不提交"，所以这里 catch 之后可以如实说"整批未写入"。
    """
    from . import interactions as X

    try:
        if args.file:
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
            items = payload["rows"] if isinstance(payload, dict) and "rows" in payload else payload
        else:
            items = [{"topic": args.topic, "mode": args.mode, "content_description": args.content or ""}]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"[submit] 读取提交清单失败（{args.file}）：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if not isinstance(items, list):
        print(f"[submit] 提交清单必须是数组（或 {{\"rows\": [...]}}），收到 {type(items).__name__}", file=sys.stderr)
        return 2

    st = make_store(args.root)
    st.init()
    added: list[str] = []
    try:
        with st.tx("search_requests", actor=args.by, note="submit") as tx:
            rows = tx.rows("search_requests")
            for i, it in enumerate(items):
                if not isinstance(it, Mapping):
                    raise ValueError(f"第 {i + 1} 条不是对象：{it!r}")
                # 取号：唯一判据。`rows` 就是事务内的活列表，upsert 之后下一轮能看见新行。
                rid = X.next_prefixed_id(rows, "request_id", "r")
                row = S.SearchRequest(
                    request_id=rid,
                    timestamp=it.get("timestamp") or S.now_iso(),
                    topic=(it.get("topic") or "").strip(),
                    mode=it.get("mode") or "topical",
                    content_description=it.get("content_description") or "",
                    done=bool(it.get("done", False)),
                    submitted_by=it.get("submitted_by") or args.by,
                )
                row.validate()
                tx.upsert("search_requests", row.to_dict(), note="submitted")
                added.append(rid)
    except (ValueError, TypeError) as e:
        print(f"[submit] 请求不合法，整批未写入：{e}", file=sys.stderr)
        return 2
    print(f"[submit] 已提交 {len(added)} 条：{', '.join(added)}")
    return 0


def _build_providers(cfg: dict, names: list[str], root: Path):
    """按配置构造 provider。import 放在这里，避免无网络环境下 `agentflow status` 也去连网。"""
    from . import providers as P

    out = []
    for n in names:
        n = n.strip().lower()
        if n == "openalex":
            out.append(P.OpenAlexProvider(mailto=(cfg.get("search") or {}).get("mailto") or None,
                                          min_interval=(cfg.get("download") or {}).get("min_interval_seconds", 1.0)))
        elif n == "crossref":
            out.append(P.CrossrefProvider(min_interval=(cfg.get("download") or {}).get("min_interval_seconds", 1.0)))
        elif n == "doaj":
            out.append(P.DoajProvider())
        elif n == "europepmc":
            out.append(P.EuropePmcProvider())
        elif n == "fixture":
            out.append(P.FixtureProvider(root / "demo" / "fixtures" / "candidates.json"))
        else:
            print(f"[warn] 未知 provider：{n}（跳过）", file=sys.stderr)
    return out


def cmd_run_a(args) -> int:
    """跑一轮 A。

    退出码：0 = 这一轮正常收敛（含"队列空了"与"搜索到了但零命中"两种有效结论），
    1 = 终局失败。"搜索失败"与"超次数放弃"都不是成功：
    `AgentA.run` 把它们写成 `outcome="search_failed"` / `gave_up`，而"队列空"写成
    `skipped_reason`。原先这里恒返回 0，于是"这一轮所有请求都因为搜不到而放弃"
    在脚本看来与"一切正常"完全一样 —— 正是"未报错被读成无问题"的形态。
    """
    from .agent_a import AgentA
    from . import fetch as F

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    names = (args.provider.split(",") if args.provider else (cfg.get("agent_a") or {}).get("providers", ["openalex"]))
    providers = _build_providers(cfg, names, root)
    downloader = F.default_downloader(cfg.get("download") or {}) if (cfg.get("agent_a") or {}).get("download", True) else None
    agent = AgentA(st, providers=providers, downloader=downloader, config=dict(cfg.get("agent_a") or {}))
    out = agent.run(max_requests=args.max if args.once else None)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 1 if _run_a_failed(out) else 0


def _run_a_failed(out: Mapping) -> bool:
    """`AgentA.run()` 的返回是否表示终局失败（三态里的"失败"，不是"没做"）。"""
    return bool(out.get("gave_up")) or out.get("outcome") == "search_failed"


def _summarize_drop_reasons(reasons, *, top: int = 4) -> str:
    """把"抽取阶段被剔除的关系"的原因聚合成一行（`quote_not_found × 8`）。

    为什么不是逐条打：真跑实测 8 条剔除原因全是同一个码，于是终端上出现 8 行
    一模一样的 `quote_not_found` —— 那既占屏又读不出"到底为什么"。
    聚合成计数之后，同一份信息一行读完；`top` 之外的原因折算成"另有 N 类"，
    所以它不会因为截断而变成一句不完整的话。
    """
    counts: dict[str, int] = {}
    for raw in reasons or []:
        key = str(raw).strip() or "(空原因)"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    head = "、".join(f"{name} × {n}" for name, n in ordered[:top])
    rest = len(ordered) - len(ordered[:top])
    return head + (f"（另有 {rest} 类原因）" if rest else "")


def cmd_run_b(args) -> int:
    """跑一轮 B。

    退出码：0 = 没有抽取失败；1 = 至少一篇文献的抽取抛了异常。
    `AgentB` 刻意不把这类文献置 `processed`（留给租约到期重试，见模块 docstring
    第 4 条），也就是说"这一轮没干成"—— 那必须能从退出码上看见，
    否则定时任务会把"每轮都在重试同一篇"当成持续成功。
    """
    from . import host as _H
    from .agent_b import AgentB
    from .extract import extract_text

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    # 抽取器只有一处装配（`host.b_extractor`）：
    # 此前这里写死 `RuleExtractor()` ⇒ `B.run_once` 永远拒抽（`R-56`），
    # 于是"跑一轮 B"这条命令结构上不可能真的抽取出东西（2026-10-03，`draft/37` §83）。
    _notes: list[str] = []
    agent = AgentB(
        st,
        extractor=_H.b_extractor(st, config=cfg, notes=_notes),
        extract_text=extract_text,
        config=dict(cfg.get("agent_b") or {}),
    )
    for _n in _notes:
        print(f"[run-b] {_n}", file=sys.stderr)
    out = agent.run(max_docs=args.max if args.once else None)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    if out.get("failed"):
        print(f"[run-b] 有 {out['failed']} 篇文献抽取失败（未置 processed，等租约到期重试）", file=sys.stderr)
        return 1
    return 0


def cmd_status(args) -> int:
    st = make_store(args.root)
    st.init()
    s = st.stats()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
        return 0
    print(tty.paint(f"工作区 {s['root']}", "bold"))
    print("")
    # 表名清单必须来自 `S.TABLES`，不许在这里写死。
    # 这里原先写死 `("search_requests", "literature", "concepts", "relations")`，
    # 而 `Store.stats()` 明明返回全部表（当时 15 张，加 `conjectures` 后为 16）——
    # 于是"库长什么样"的第一入口静默地不显示另外 11 张（analysis_reports / experiments /
    # documents / tasks …）。
    # 写死的第二份名单还会在表被改名/删除时以 `KeyError` 崩掉（`s[t]`），
    # 而不是如实报告。与 `cmd_tools` 里那句"角色清单必须来自 ROLES"同一个道理。
    rows = []
    for t in S.TABLES:
        info = s[t]
        extra = " ".join(f"{k}={v}" for k, v in info.items() if k != "count")
        rows.append((t, str(info["count"]), extra))
    rows.append(("events", str(s["events"]["appended"]), "追加日志"))
    for line in tty.table(("表", "行数", "其它"), rows, aligns=("left", "right", "left")):
        print(line)
    return 0


def cmd_verify(args) -> int:
    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    extract_text = None
    if args.deep:
        from .extract import extract_text as _et

        extract_text = _et
    # 关键：引文复核参数必须与 agent_b 写入时用的同一份配置，否则 --deep
    # 会用更严的规则重算，把写入时合规的引文报成 quote_not_found（假报警）。
    bcfg = cfg.get("agent_b") or {}
    rep = verify_all(
        st,
        deep=args.deep,
        extract_text=extract_text,
        quote_widen=int(bcfg.get("quote_widen_pages", 1)),
        allow_fulltext_quote_fallback=bool(bcfg.get("allow_fulltext_quote_fallback", False)),
    )
    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2, default=str))
    else:
        print(f"{tty.badge('ok' if rep.ok else 'failed')}  校验完成  "
              f"错误 {len(rep.errors)} / 警告 {len(rep.warnings)}")
        for i in rep.issues:
            tone = "red" if i.level == "error" else "yellow"
            print(tty.bullet(tty.paint(f"[{i.level}] {i.table}/{i.row_id or '-'} "
                                       f"{i.code}: {i.message}", tone)))
    # 退出码三档，与 `scripts/lint_rules.py` / `noai_gate.py` 同一口径：
    #   0 = 通过（无错误，且 --strict 下也无警告）
    #   1 = 查过了、发现问题（error 一律失败；--strict 时 warning 也算失败）
    #   2 = 没查成（StoreError，由 `main` 统一处理）
    # 原先只有 `--strict` 才返回非零 ⇒ `agentflow verify` 在库确实有 error 时
    # 退出码仍是 0。"未报错"被读成"无问题"，正是 `draft/17` §6.3 记的那条教训，
    # 也是本项目把 linter/门禁的退出码做成三档的理由。校验器的默认行为必须能当门用。
    if rep.errors:
        return 1
    return 1 if (args.strict and rep.warnings) else 0


def cmd_rebuild(args) -> int:
    st = make_store(args.root)
    if not st.events_path.exists():
        print("[rebuild] 没有 events.jsonl，无法重建")
        return 1
    out = st.rebuild(backup=not args.no_backup)
    print(f"[rebuild] 已从事件日志重建：应用 {out['applied']} 条，跳过 {out['skipped']} 条")
    # ---- R-06 的可见面（`46-01 §2.2(b)` STEP-3 逐字："明细没有人看得见就等于没做"）
    #
    # `skipped` 那个整数一直有，但没有人知道跳过了什么：重建完照样打印
    # "已重建：应用 N 条"，而"N 条为什么没进去"一个字都不说 —— 读的人据此
    # 以为重建是完整的（`verify` 的 `rebuild` 相关读数也只看得到那个整数）。
    # 所以这里把 `store.rebuild` 新增的两键（`skipped_by_reason` / `skipped_details`）
    # 打出来。三态纪律：非空才打印 —— 干净的重建不许多出噪音，
    # 否则"有跳过"这件事会在满屏输出里贬值。
    by_reason = dict(out.get("skipped_by_reason") or {})
    if by_reason:
        detail = "、".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
        print(f"[rebuild] 跳过的分类计数：{detail}")
        for row in list(out.get("skipped_details") or [])[:5]:
            print(f"[rebuild]   跳过明细：{row}")
        if len(list(out.get("skipped_details") or [])) > 5:
            print(f"[rebuild]   （另有 {len(list(out.get('skipped_details') or [])) - 5} 条明细未打印）")
    print(f"[rebuild] counters = {out['counters']}")
    return 0


def cmd_repair(args) -> int:
    """按 verify 的派生规则修复 related_concepts（唯一允许的"自动修复"，因为它完全可派生）。

    `--related` 原先是一个被忽略的开关：函数体从不读 `args.related`，
    于是"不带参数跑一次"也会照样重写 concepts 表。一个声明了却不起作用的选项
    比没有更危险 —— 调用方以为自己在做只读检查，实际上知识表已经被改了。
    这里 fail-closed：没有显式指名要重算什么，就一行都不写并以退出码 2 说明。
    """
    from . import dedup as D

    if not args.related:
        print(
            "[repair] 需要显式指定重算目标。本命令会写 concepts 表，因此不接受"
            "'不带参数就默认全做'：请用 `repair --related`（重算 related_concepts）。",
            file=sys.stderr,
        )
        return 2

    st = make_store(args.root)
    # 并表落刀之后这一格随老表退役：`related_concepts` 是老表专有的一列，
    # 新标准里"哪些概念相关"由 `relations` 表本身回答（读侧用同一个
    # `derive_related_concepts` 现算）⇒ 没有可重算的落点。这里受控退出 + 指路，
    # 而不是让 `tx("concepts")` 抛一句"未知表"（读的人拿到那句话不知道下一步做什么）。
    if not CR.legacy_present(st).get("present"):
        print(
            "[repair] `--related` 随并表退役（S1r）：`related_concepts` 是老表专有的一列，"
            "新标准里那件事由 `relations` 表管，读侧现算，没有可重算的落点。"
            "处置：要核对图与关系的偏离，用 `agentflow verify`（`related_drift` 那一档）；"
            "要重放老库，用 `agentflow rebuild`（它会折叠并逐条落 `out/migrate-map.jsonl`）。",
            file=sys.stderr,
        )
        return 2
    with st.tx(*CR.tables_for_concept_write("relations"), actor="repair", note="related") as tx:
        rels = tx.rows("relations")
        changed = 0
        for c in CR.view_tx(tx, shape="legacy")["rows"]:
            want = D.derive_related_concepts(c["concept_id"], rels, include_suspect=True)
            if c.get("related_concepts") != want:
                c["related_concepts"] = want
                c["updated_at"] = S.now_iso()
                # 一处调用办两件事（老表那份 + 新标准那份，同号）—— 见 `conceptrows`
                CR.upsert_legacy_shaped(tx, c, actor="repair", note="related_recomputed")
                changed += 1
    print(f"[repair] related_concepts 重算了 {changed} 行")
    return 0


def cmd_tools(args) -> int:
    """列出工具层装配情况（按角色）。

    这个命令存在的意义：工具层的权限面是设计的一部分（A 拿不到 D 的工具等），
    但它默认是隐式的 —— 加一条命令把它变成可打印的事实，才好在评审时核对。
    """
    from agentflow.tools import ROLES, TOOL_ROLES, build_registry

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    # 角色清单必须来自 `TOOL_ROLES`（= 可被召唤的 A–H + 主控 M），不许在这里写死。
    # 这里原先写死 `("A","B","C","D")`，于是 E/F/G/H 落地之后，本命令会
    # 一边报告"工具总数 55"，一边只列 4 个角色的工具数 —— 而"角色即权限面"
    # 恰恰是靠这条命令变成可打印的事实的。写死名单让那句"评审时可核对"落空。
    # 现在补的是同族缺口：用 `ROLES` 会让主控的 8 件编排面工具在普查里完全不出现
    # （实测 2026-09-28：总数 63，而各角色表里没有 M）—— 那正是"主控有没有手"
    # 这个问题的答案，不能被漏掉。
    build = build_registry(store=st, workspace_root=root, roles=tuple(ROLES))
    if args.json:
        print(json.dumps(build.summary(), ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"工具总数：{len(build.registry)}（已装模块 {len(build.loaded)}：{', '.join(build.loaded) or '无'}）")
    if build.skipped:
        print("未装上的模块（并行开发中属正常）：")
        for s in build.skipped:
            print(f"  - {s['module']} [{s['stage']}] {s['error'][:80]}")
    role = args.role
    if role:
        specs = build.registry.for_role(role)
        print(f"\n角色 {role} 可用工具（{len(specs)} 个）：")
        for s in sorted(specs, key=lambda x: x.name):
            flag = " ⚠需审批" if s.needs_approval else ""
            print(f"  {s.name:28} [{s.side_effect}]{flag}  {s.summary[:60]}")
    else:
        # 只读角色的写工具泄漏必须一眼可见：它是"审校者手里有没有刀"的直接答案。
        from agentflow.tools import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE

        by_role = {r: len(build.registry.for_role(r)) for r in TOOL_ROLES}
        print(f"\n各角色工具数：{by_role}")
        leaks = {
            r: [s.name for s in build.registry.for_role(r) if s.side_effect in SIDE_EFFECTS_WRITE]
            for r in READ_ONLY_ROLES
        }
        print(f"只读角色写工具泄漏：{leaks}（{'空 = 正常' if not any(leaks.values()) else '!! 有泄漏'}）")
        if build.registry.role_filter_notes:
            print(f"⚠️ 有工具的 roles 声明需要纠正（行为已被 for_role 拦下）：")
            for r, notes in build.registry.role_filter_notes.items():
                print(f"  [{r}] {notes[0][:140]}")
        print("（用 --role A 查看具体清单）")
    return 0


def _build_agent_c(root: Path, cfg: dict):
    from agentflow.agent_c import AgentC

    st = make_store(root)
    st.init()
    return st, AgentC(st, config=cfg.get("agent_c") or {})


def cmd_analyze(args) -> int:
    """运行 C 的关系分析（四类需求之一）。"""
    root = Path(args.root or DEFAULT_ROOT).resolve()
    cfg = load_config(root, args.config)
    st, c = _build_agent_c(root, cfg)

    if args.text:
        rep = c.handle(args.text)
    elif args.kind == "paths":
        if not (args.a and args.b):
            print("[analyze] kind=paths 需要 --a 与 --b（概念代号或概念名）", file=sys.stderr)
            return 2
        a = _resolve_concept(st, args.a)
        b = _resolve_concept(st, args.b)
        if a is None or b is None:
            names = [f"{r['concept_id']}={r['name']}"
                     for r in CR.view(st, shape="legacy")["rows"]]
            print(f"[analyze] 无法解析概念：a={args.a!r} b={args.b!r}\n  现有概念：{names}", file=sys.stderr)
            return 2
        rep = c.paths(a, b, max_paths=args.max_paths, max_len=args.max_len, request=args.request or "")
    elif args.kind == "hottest":
        rep = c.hottest(top_n=args.top_n, request=args.request or "")
    elif args.kind == "cold":
        rep = c.cold(top_n=args.top_n, request=args.request or "")
    elif args.kind == "gaps":
        rep = c.gaps(limit=args.top_n, request=args.request or "")
    else:
        print(f"[analyze] 未知 kind={args.kind}", file=sys.stderr)
        return 2

    # `rep.ok is False` 表示"这次没能给出结论"（概念解析不到、关系表为空……），
    # 与"分析完成、结论是没找到"是两件事（见 `AnalysisReport.ok` 的 docstring）。
    # 必须在 `persist()` 之前分流：`persist()` 明确拒绝登记 kind 不在受控词表里的
    # 报告（`kind="unknown"` 就是分派失败），先 persist 会以 ValueError 崩出一个
    # traceback —— 而"这条需求我听不懂"是一句应当被读到的结论，不是崩溃。
    # 代价是失败报告不落表：这是 `persist()` 自己的硬规则（表外 kind 会让 D 无法处理），
    # 不是这里偷偷跳过。人读的 markdown 与机器可读的退出码照给。
    if not rep.ok:
        if rep.markdown:
            print(rep.markdown)
        # error 是受控的机器可读原因，summary 是人话结论；两条都给 ——
        # 只给 error 会把"该怎么办"丢掉（例如 error="关键词未命中"，
        # 而 summary 会列出可用的说法示例）。
        detail = str(rep.error or "")
        if rep.summary and rep.summary not in detail:
            detail = f"{detail}；{rep.summary}" if detail else rep.summary
        print(f"[analyze] 分析未给出结论（kind={rep.kind}）：{detail}", file=sys.stderr)
        return 1

    row = rep.persist()
    print(rep.markdown)
    # `persist()` 返回的是登记行（report_id / markdown_path / abs_path），
    # 不含 `kind` —— kind 是报告对象自己的属性。这里曾经误用 row['kind'] 而 KeyError。
    print(f"\n[analyze] 报告已登记：report_id={row.get('report_id')} kind={rep.kind} "
          f"markdown={row.get('markdown_path')}")
    if rep.warnings:
        print(f"[analyze] 告警 {len(rep.warnings)} 条：")
        for w in rep.warnings:
            print(f"  - {w}")
    if rep.truncated:
        print("[analyze] ⚠ 搜索被预算截断（结果可能不完整）")
    return 0


def _resolve_concept(st, token: str) -> str | None:
    """把用户给的东西解析成概念代号：既接受 4 位代号，也接受概念名（走 dedup 的规范化匹配）。

    概念行读合成视图（并表过渡期：老表 + 新标准 `kind="concept"`，同号去重）：
    只读老表会让"新标准写进来的概念"在这条命令里解析不到（用户看到一个存在的概念
    被报成"解析不了"）。
    """
    from agentflow import dedup as D

    rows = CR.view(st, shape="legacy")["rows"]
    if S.is_valid_id(token) and any(r["concept_id"] == token for r in rows):
        return token
    hit = D.find_concept(rows, token)
    return hit["concept_id"] if hit else None


def cmd_pipeline(args) -> int:
    """把 A→B→C→D 串起来跑（DESIGN-TOOLS.md §5）。"""
    from . import host as H
    from agentflow.agent_a import AgentA
    from agentflow.agent_b import AgentB
    from agentflow.extract import extract_text
    from agentflow.pipeline import run_pipeline
    from agentflow import fetch as F

    root = Path(args.root or DEFAULT_ROOT).resolve()
    cfg = load_config(root, args.config)
    st = make_store(root)
    st.init()

    # `run_pipeline` 用 agent_a/agent_b 是否为 None 来表达"这轮要不要真的去检索"，
    # 而不是另设一个布尔开关 —— 这样"不检索"就是"没接上 A/B"，语义只有一处。
    agent_a = agent_b = None
    if not args.no_search:
        names = (cfg.get("agent_a") or {}).get("providers", ["openalex"])
        agent_a = AgentA(
            st,
            providers=_build_providers(cfg, names, root),
            downloader=F.default_downloader(cfg.get("download") or {}),
            config=dict(cfg.get("agent_a") or {}),
        )
        agent_b = AgentB(
            st,
            extractor=H.b_extractor(st, config=cfg),
            extract_text=extract_text,
            config=dict(cfg.get("agent_b") or {}),
        )

    out = run_pipeline(
        st,
        request=args.request,
        gap_rounds=args.gap_rounds,
        config=cfg,
        agent_a=agent_a,
        agent_b=agent_b,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_demo(args) -> int:
    from .demo import run_demo

    return run_demo(Path(args.root or DEFAULT_ROOT).resolve(), reset=not args.keep)


def cmd_run(args) -> int:
    """端到端跑一个主题：`run_topic` 的退出码就是这个进程的退出码。

    为什么工作区默认落在临时目录：`run` 会写 `usage_ledger`（真花钱的账），
    而默认写进演示数据目录 `test/test1/` 会让每次试跑都污染那份必须保持干净的
    数据。临时目录加"把实际路径打印出来"是这一步的诚实形态 ——
    "产物在哪"必须能从输出里读到，而不是靠人猜一个默认值。

    `--model` 只覆盖模型名：key / base_url / 超时 / 重试一律来自环境变量
    （`spec_from_env`），命令行不许传 key —— argv 会进 shell 历史与进程列表。
    """
    import tempfile

    from .modelgw import spec_from_env
    from .runflow import run_topic

    # 顶层参数 `--root` 必须写在子命令之前（argparse 的位置规则），
    # 缺省时给一个临时工作区（理由见上面的 docstring）。
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="agentflow-run-"))
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="agentflow-run-out-"))
    spec = spec_from_env()
    if args.model:
        spec = replace(spec, model=args.model)
    st = make_store(root)
    st.init()
    res = run_topic(
        st,
        topic=args.topic,
        budget_usd=args.budget_usd,
        out_dir=out,
        spec=spec,
        max_calls=args.max_calls,
        prompt_version=args.prompt_version,
        now=args.now,
        # `--fulltext` 缺省关闭：开机就批量下载开放全文是网络与磁盘的实质开销，
        # 必须由调用方显式要。关闭时产物里会如实写"没有发起全文获取"，
        # 而不是让读者以为"取了、但没有开放全文"。
        fulltext=bool(args.fulltext),
        # `--lean` 缺省关闭：它会真的起 Lean 检查器（先装、再跑，可能是分钟级）。
        # 关闭时"没有形式化验证证据"这件事照样写进未接线清单 ——
        # 少写它会让读者把"没有 proof 级证据"读成"证明了但没写下来"。
        lean=bool(args.lean),
        # 裸 `run` 没有项目根，所以逐页正文默认内联；要"同一本书只存一份"
        # 就显式给一个落点（依据 `draft/30` §T0-7）。
        text_store_dir=getattr(args, "text_store_dir", None),
    )
    # 两个数字、两种口径，必须分开印（`G-4`）：
    # - `spent_usd_this_run` 是本次运行花掉的（`--budget-usd` 判的就是它）；
    # - `spent_usd` 是该工作区账本累计（`usage_ledger` 跨运行求和，属于工作区）。
    # 只印累计值时，"这次运行烧光了预算"与"这个工作区历史上一共花了多少"会是
    # 同一个数字 —— 一个长期使用的工作区会让每一次 run 看起来都超预算。
    # 老版本（返回值里还没有这个键时）退回累计值：不猜，但也不隐藏它缺了。
    this_run = res.get("spent_usd_this_run", res["spent_usd"])
    # 检索三态与断言台账摘要必须打到 stdout：它们是"这次的结论有没有外部依据"
    # 的直接答案。只写在 JSON 里，等于要人先去读文件才知道该不该相信这份报告。
    counts = res["claims"]
    lean = res.get("lean") or {}
    print("")
    for line in tty.panel(
        "端到端跑一个主题",
        [("退出码", f"{_exit_badge(res['exit_code'])}（{res['reason']}）"),
         ("模型调用", f"{res['calls']} 次；本次已花 {this_run} 美元"
                      f"（本次预算 {args.budget_usd}）；该工作区账本累计 {res['spent_usd']} 美元"),
         ("检索", f"{res['retrieval_status']}；断言 {counts['total']} 条"
                  f"（逐字通过 {counts['verified']}：摘要级 {counts.get('verified_abstract', 0)}、"
                  f"全文级 {counts.get('verified_fulltext', 0)}；未验证 {counts['unverified']}）"),
         ("Lean", f"开启={'是' if lean.get('enabled') else '否'}；"
                  f"跑过={'是' if lean.get('ran') else '否'}；"
                  f"proof 级证据 {lean.get('proved', 0)} 条 —— {lean.get('reason')}"),
         ("六件产物", "、".join(res["artifacts"]))],
        # 路径放进 `verbatim`：它是要被抄下来 `cd` 进去的，截断了就等于没打印。
        verbatim=[("工作区：", str(root)), ("产物目录：", res["out_dir"])],
        tone="green" if int(res["exit_code"]) == 0 else "yellow",
    ):
        print(line)
    # `not_wired` 必须打到 stdout：它是"这次有哪些事确定没做"的直接答案，
    # 只写在 JSON 里等于要人先去读文件才知道不该相信这份报告。
    man = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
    for item in man["not_wired"]:
        print(tty.bullet(tty.paint(f"未接线：{item['name']} —— {item['reason']}", "yellow")))
    return int(res["exit_code"])


# ---------------------------------------------------------------- 证据面（T0-7）


def _evidence_verify(run_dir: Path) -> int:
    """核一个运行目录里的全文引用：逐条比对 `text_ref`，并重算引文命中页。

    为什么必须能独立核：`text_ref` 把"证据正文在哪"从产物内部搬到了产物外部，
    搬出去就必须有工具回答"这条引用还对不对" —— 否则搬出去等于把可复核性也搬走了。
    三态：0 = 查过、都对得上；1 = 查过了、有坏引用或页号不符；2 = 没查成。
    """
    from . import fulltextstore as FS

    ev_path = run_dir / "evidence.json"
    if not ev_path.is_file():
        print(f"[evidence] 没查成：{ev_path} 不存在", file=sys.stderr)
        return 2
    try:
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[evidence] 没查成：读不了 {ev_path}（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 2

    # 运行目录形如 <项目根>/out/run-N ⇒ 项目根是上两级；`allowed_dir` 用它把
    # "引用只许指向本项目的正文库"这条结构判据钉死。
    allowed = run_dir.parent.parent / FS.STORE_DIR_NAME
    rows: list[tuple[str, str, str]] = []
    bad = 0
    for src in ev.get("sources") or []:
        sid = str(src.get("source_id") or "?")
        ref = (src.get("fulltext") or {}).get("text_ref")
        if not isinstance(ref, dict):
            rows.append((sid, "-", "内联或没有全文（不是引用形态）"))
            continue
        rep = FS.verify_ref(ref, allowed_dir=allowed)
        if not rep["ok"]:
            bad += 1
            rows.append((sid, "坏", rep["problem"]))
        else:
            rows.append((sid, "好", f"{rep['pages']} 页 / {rep['chars']} 字"))

    rows = _verify_quotes(run_dir, ev, rows)
    bad += sum(1 for r in rows if r[1] == "页不符")
    for line in tty.table(("来源", "引用", "读数/理由"), rows, aligns=("left", "left", "left")):
        print(line)
    print(tty.bullet(f"引用 {len(rows)} 条；坏 {bad} 条。台账：{ev_path}"))
    return 1 if bad else 0


def _verify_quotes(run_dir: Path, ev: Mapping, rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """把 `claims.json` 里登记的页号与我方独立搜出来的页号对一遍（不调用被审对象）。

    独立复核的意义：`claims.json` 的页号是被审实现给的；这里用朴素规范化
    （NFKC + 折叠空白）自己搜一遍，两处一致才算"这条引用可复核"。
    """
    import unicodedata

    from . import fulltextstore as FS

    claims_path = run_dir / "claims.json"
    if not claims_path.is_file():
        return rows
    try:
        # 2026-10-17（IO #9）：`claims.json` 顶层可能是数组（手写/半途写坏）——
        # `.get` 会抛 AttributeError，而这一支只接 OSError/ValueError。
        _doc = json.loads(claims_path.read_text(encoding="utf-8"))
        claims = (_doc.get("claims") if isinstance(_doc, dict) else None) or []
    except (OSError, ValueError):
        return rows
    pages_by_sid: dict[str, list[str]] = {}
    for src in ev.get("sources") or []:
        ref = (src.get("fulltext") or {}).get("text_ref")
        if isinstance(ref, dict):
            pages, _why = FS.load(ref)
            pages_by_sid[str(src.get("source_id") or "?")] = pages
    if not pages_by_sid:
        # 内联形态的产物：本工具不复算页号（它只复算引用形态）。
        # 这里必须如实说"没复算" —— 绝不许把"没查成"写成"页不符"：
        # 那会把一次读取能力的缺失记成产物的缺陷。
        rows.append(("（全部来源）", "未复算",
                     "产物是内联形态；要复算页号请先 `evidence migrate --apply`"))
        return rows

    def _norm(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())

    for c in claims:
        quote = str(c.get("quote") or "")
        rec_page = (c.get("locator") or {}).get("page") if isinstance(c.get("locator"), dict) else None
        if not quote or rec_page is None:
            continue
        found = None
        for _sid, pages in pages_by_sid.items():
            for idx, page in enumerate(pages, start=1):
                if _norm(quote) and _norm(quote) in _norm(page):
                    found = idx
                    break
            if found:
                break
        state = "页一致" if found == rec_page else "页不符"
        rows.append((f"claims/{c.get('claim_id') or '?'}", state,
                     f"登记 {rec_page} / 我方独立搜到 {found}"))
    return rows


def _evidence_store(project_dir: Path) -> int:
    """盘一个项目的正文库：几个文件、多少字节、每个文件被几份产物引用。

    空目录与"零字节"必须分开说 —— 把空库读成"没问题"正是这一层最常见的误读。
    """
    from . import fulltextstore as FS

    store_dir = project_dir / FS.STORE_DIR_NAME
    rows = FS.inventory(store_dir)
    if not rows:
        print(tty.bullet(f"正文库：空（{store_dir} 不存在或没有任何 store 文件）"))
        return 0
    referenced: dict[str, int] = {}
    for ev_path in sorted(project_dir.glob("out/run-*/evidence.json")):
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for src in ev.get("sources") or []:
            ref = (src.get("fulltext") or {}).get("text_ref")
            if isinstance(ref, dict) and ref.get("path"):
                key = Path(str(ref["path"])).name
                referenced[key] = referenced.get(key, 0) + 1
    table = [(Path(r["path"]).name, "好" if r["ok"] else "坏",
              f"{r['bytes']} B / {r['pages']} 页 / 被 {referenced.get(Path(r['path']).name, 0)} 份产物引用",
              r["problem"]) for r in rows]
    for line in tty.table(("store 文件", "自校验", "读数", "问题"), table):
        print(line)
    print(tty.bullet(f"共 {len(rows)} 个 / {sum(int(r['bytes']) for r in rows)} 字节；落点 {store_dir}"))
    return 1 if any(not r["ok"] for r in rows) else 0


def _evidence_migrate(project_dir: Path, *, apply: bool) -> int:
    """把历史产物里的内联正文迁成引用形态；默认 dry-run。

    为什么默认只 dry-run：这一步改的是历史证据本体（产物里那一段正文），
    "改证据"这种事必须由人显式点头（`--apply`），而且每一份都要先备份。
    """
    from . import fulltextstore as FS

    store_dir = project_dir / FS.STORE_DIR_NAME
    todo: list[tuple[Path, int, int]] = []
    for ev_path in sorted(project_dir.glob("out/run-*/evidence.json")):
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(tty.bullet(tty.paint(f"跳过（读不了）：{ev_path}", "yellow")))
            continue
        n = 0
        saved = 0
        for src in ev.get("sources") or []:
            full = src.get("fulltext") or {}
            pages = [str(p) for p in (full.get("text_pages") or [])]
            if pages and not full.get("text_ref"):
                n += 1
                saved += len(json.dumps(pages, ensure_ascii=False, default=str).encode("utf-8"))
        if n:
            todo.append((ev_path, n, saved))

    if not todo:
        print(tty.bullet("没有需要迁移的产物（都已经没有内联正文）"))
        return 0
    total = sum(s for _p, _n, s in todo)
    for line in tty.table(("产物", "内联来源数", "可省字节"),
                          [(str(p.relative_to(project_dir)), str(n), str(s)) for p, n, s in todo]):
        print(line)
    if not apply:
        print(tty.bullet(f"dry-run：将写 {total} 字节进 {store_dir}，"
                         f"改写 {len(todo)} 份产物（加 --apply 才动盘；动盘前逐份备份）"))
        return 0

    stamp = S.now_iso().replace(":", "").replace("-", "")[:15]
    backup_dir = Path(str(store_dir.parent / "temp")) / f"evidence-migrate-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for ev_path, _n, _s in todo:
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        backup = backup_dir / f"{ev_path.parent.name}-evidence.json"
        backup.write_bytes(ev_path.read_bytes())
        for src in ev.get("sources") or []:
            full = src.get("fulltext") or {}
            pages = [str(p) for p in (full.get("text_pages") or [])]
            if not (pages and not full.get("text_ref")):
                continue
            ref = FS.put(pages, store_dir=store_dir, pdf_sha256=str(full.get("sha256") or ""),
                         pdf_path=str(full.get("path") or ""), pdf_bytes=int(full.get("bytes") or 0),
                         backend=str(full.get("backend") or ""))
            full.pop("text_pages", None)
            full.pop("text", None)
            full["text_ref"] = ref
            full["chars"] = int(ref.get("chars") or 0)
            full["text_store"] = "ref"
        ev_path.write_text(json.dumps(ev, ensure_ascii=False, indent=1, default=str) + "\n",
                           encoding="utf-8", newline="\n")
        done += 1
    print(tty.bullet(f"已迁移 {done} 份产物；备份在 {backup_dir}"))
    return 0


def cmd_evidence(args) -> int:
    """证据面三件事：核引用 / 盘正文库 / 迁移历史产物（依据 `draft/30` §T0-7）。

    三态（与全仓同一条纪律）：0 = 查过、都对得上；1 = 查过了、有坏引用；
    2 = 没查成（目标不在 / 读不了）。
    """
    target = Path(args.target)
    if args.action == "verify":
        return _evidence_verify(target)
    if args.action == "store":
        if not target.is_dir():
            print(f"[evidence] 没查成：{target} 不是目录", file=sys.stderr)
            return 2
        return _evidence_store(target)
    if not target.is_dir():
        print(f"[evidence] 没查成：{target} 不是目录", file=sys.stderr)
        return 2
    return _evidence_migrate(target, apply=bool(args.apply))


# ---------------------------------------------------------------- 入口


def cmd_artifacts(args) -> int:
    """产物归属：登记 / 列出 / 核对 / 问归属 / 找没归属的 / 渲染成表。

    三态（与全仓同一条纪律）：0 = 查过、都对得上；1 = 查过了、有变了的产物；
    2 = 没查成（路径不给 / 越界 / 文件不存在 / 核对里有读不出来的）。

    `record` 是唯一写的动作，而且先核文件后写台账 —— 一条钉不住内容的登记
    不是弱证据，是假证据（见 `agentflow.artifacts` 的模块 docstring）。
    """
    from . import artifacts as A

    root = args.root
    action = args.action
    targets = list(args.target or [])

    if action == "record":
        if len(targets) != 1:
            print("[artifacts] 没查成：record 只收一个路径", file=sys.stderr)
            return 2
        if not args.producer.strip():
            print("[artifacts] 没查成：record 必须给 --producer（不知道是谁产的，"
                  "这条登记没有归属可言）", file=sys.stderr)
            return 2
        try:
            entry = A.record(root, path=targets[0], producer=args.producer, kind=args.kind,
                             task_id=args.task_id, exit_code=args.exit_code, note=args.note)
        except A.ArtifactError as e:
            print(f"[artifacts] 拒收：{e}", file=sys.stderr)
            return 2
        print(tty.bullet(f"已登记 {entry['path']} ← {entry['producer']}"
                         f"（{entry['kind']}，{entry['bytes']} 字节，{entry['sha256'][:16]}）"))
        return 0

    if action == "owners":
        if len(targets) != 1:
            print("[artifacts] 没查成：owners 只收一个路径", file=sys.stderr)
            return 2
        try:
            rows = A.owners_of(root, targets[0])
        except A.ArtifactError as e:
            print(f"[artifacts] 没查成：{e}", file=sys.stderr)
            return 2
        if not rows:
            print(tty.bullet(f"{targets[0]} 在台账里**没有**归属登记 —— "
                             "这不是'没人产过'，是'没人登记过'（两件事必须分开说）"))
            return 1
        for line in tty.table(("生产者", "类别", "召唤", "时刻", "sha256"),
                              [(r["producer"], r["kind"], r.get("task_id") or "—",
                                r["at"], str(r["sha256"])[:16]) for r in rows]):
            print(line)
        return 0

    if action == "unowned":
        if not targets:
            print("[artifacts] 没查成：unowned 至少要给一个路径（目录会被展开成里面的文件）",
                  file=sys.stderr)
            return 2
        files: list[Path] = []
        for t in targets:
            p = Path(t)
            if not p.is_absolute():
                p = Path(str(root)) / p
            if p.is_dir():
                files += [q for q in sorted(p.rglob("*")) if q.is_file()]
            elif p.is_file():
                files.append(p)
            else:
                print(f"[artifacts] 没查成：{t} 既不是文件也不是目录", file=sys.stderr)
                return 2
        try:
            missing = A.unowned(root, files)
        except A.ArtifactError as e:
            print(f"[artifacts] 没查成：{e}", file=sys.stderr)
            return 2
        print(tty.bullet(f"查了 {len(files)} 个文件，其中 {len(missing)} 个**没有**归属登记"))
        for m in missing:
            print(tty.bullet(m))
        return 1 if missing else 0

    if action == "list":
        rows = A.list_artifacts(root, producer=args.producer or None,
                                task_id=args.task_id or None, kind=args.kind or None)
        if not rows:
            print(tty.bullet("台账里没有匹配的记录 —— 目录里没有台账文件也是这一种"
                             "（'还没登记过'，不是'登记过、没问题'）"))
            return 0
        for line in tty.table(("路径", "生产者", "类别", "召唤", "sha256"),
                              [(r["path"], r["producer"], r["kind"], r.get("task_id") or "—",
                                str(r["sha256"])[:16]) for r in rows]):
            print(line)
        return 0

    if action == "report":
        text = A.render_markdown(root)
        if args.out:
            out_path = Path(args.out)
            if not out_path.is_absolute():
                out_path = Path(str(root)) / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8", newline="\n")
            print(tty.bullet(f"已写 {args.out}（{len(text.encode('utf-8'))} 字节）"))
        else:
            print(text)
        return 0

    # ---- verify（默认动作）
    records, bad = A.read_ledger(root)
    checks = A.verify_entries(root, records)
    counts: dict[str, int] = {}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    bad_statuses = ("changed", "missing", "unreadable", "not_a_file")
    if not records and not bad:
        print(tty.bullet("台账里一条记录都没有 —— **没查成**，不是'都对得上'"
                         "（先 `artifacts record` 登记，别把空台账读成绿灯）"))
        return 2
    for c in checks:
        if c["status"] in bad_statuses:
            print(tty.bullet(f"{c['status']}：{c['path']}"
                             f"（台账 {c['sha256'][:16] or '—'} / 盘上 {c['sha256_now'][:16] or '—'}）"))
    for b in bad:
        print(tty.bullet(f"台账坏行：{b}"))
    print(tty.bullet(f"核对 {len(checks)} 条：{counts}；坏行 {len(bad)}"))
    if bad or any(counts.get(s) for s in bad_statuses):
        return 1
    return 0


def cmd_project(args) -> int:
    """项目式用法：一个项目一个文件夹（`projects/project1`…），冷/热启动按文件夹在不在。

    为什么把它做成一个动词而不是让人记一串 `--root`：项目工作区、本地书架、
    冷热启动这三件事是一起被用到的（"在这个项目上、用这些书、接着上次跑"），
    拆成散参数就会出现"库指到 A、产物写到 B、书来自 C"这种没人能复核的组合。

    这里是唯一把 `--projects-dir` 与 `--start` 翻译成动作的地方；
    真正的判定与执行在 `agentflow.projects`（那里有它自己的负控自检）。
    """
    from . import projects as P

    root = P.projects_dir(args.projects_dir)
    try:
        if args.action == "list":
            rows = P.list_projects(root)
            print(tty.paint(f"projects 落点 {root}", "grey"))
            if not rows:
                print(tty.bullet("还没有任何项目；第一次跑会自动取 project1。"))
            else:
                for line in tty.table(
                    ("项目", "状态", "冷/热", "上次", "说明"),
                    [(r["name"], _state_badge(r["state"]), f"{r['cold_runs']}/{r['warm_runs']}",
                      str(r["last_mode"] or "-"), r["why"]) for r in rows],
                    aligns=("left", "left", "right", "left", "left"),
                ):
                    print(line)
            return 0

        if args.action == "create":
            if not args.paper:
                print("[project] 没查成：`create` 要 `--paper <那篇外部论文>`"
                      "（它是这个项目的输入；不给就不知道该铺什么）", file=sys.stderr)
                return 2
            res = P.create_review_project(root, paper=args.paper, name=args.name)
            seeded = res["seeded"]
            for line in tty.panel(
                f"建好项目：{res['project']['name']}",
                [("落点", res["project"]["path"]),
                 ("只读基线", ", ".join(seeded["source"])),
                 ("可改正文", seeded["manuscript"] or "(还没写：G 的活)")],
                body=[seeded["note"] or "论文已铺好：source/ 只读，out/paper/main.tex 可改。",
                      "下一步：`agentflow --root <工作区> run-agent M --task …` 派活。"],
                tone="green",
            ):
                print(line)
            return 0

        if args.action == "plan":
            info = P.plan(root, args.name, start=args.start, books_dir=args.books,
                          topic=args.topic or "")
            pj = info["project"]
            print("")
            for line in tty.panel(
                f"计划：{pj['name']}",
                [("会新建文件夹吗", "会（冷启动）" if info["will_create"] else "不会（热启动，复用）"),
                 ("判据", f"请求 {pj['requested']} ⇒ 判定 {tty.badge(pj['mode'])}（{pj['reason']}）"),
                 ("本地书架", info["books_dir"] or "(没给 --books)"),
                 ("主题", info["topic"] or "(没给 --topic ⇒ 只登记、不调模型)")],
                body=[info["note"], "这一步只说明会怎么做，不写任何字节。"],
                verbatim=[("落点：", pj["path"]), ("产物目录：", f"out/run-{info['run_index']}")],
                tone="cyan",
            ):
                print(line)
            return 0

        res = P.run_project(
            root, name=args.name, start=args.start, topic=args.topic or "",
            books_dir=args.books, books_limit=args.books_limit,
            budget_usd=args.budget_usd, max_calls=args.max_calls,
            retrieval_limit=args.retrieval_limit, fulltext=not args.no_fulltext,
            extract=bool(args.extract), extract_rounds=args.extract_rounds,
            lean=bool(args.lean),
            now=args.now,
            # 不给就由 `run_project` 用项目根下的 `.fulltext/`（T0-6 的默认）
            text_store_dir=getattr(args, "text_store_dir", None),
        )
    except (P.ProjectExists, P.ProjectMissing, P.ProjectNotAWorkspace) as exc:
        # 三态：这三条都是"这一步没做成"（用法/前提不满足），不是"跑过了、结论是失败"。
        print(f"[project] 没查成：{exc}", file=sys.stderr)
        return 2

    pj, run, result = res["project"], res["run"], res["result"]
    emit = print
    emit("")
    for line in tty.panel(
        f"项目 {pj['name']}",
        [("本次启动", f"{tty.badge(pj['mode'])}  {pj['reason']}")],
        verbatim=[("落点：", pj["path"]),
                  ("产物目录：", run.get("out_dir") or "(本次没跑模型那一步)")],
        tone="cyan",
    ):
        emit(line)

    ing = run.get("ingest") or {}
    if ing:
        counts = ing.get("counts") or {}
        emit("")
        for line in tty.rule("本地书架"):
            emit(line)
        rows = [(k, str(v)) for k, v in counts.items() if v or k in ("ingested", "already_present")]
        for line in tty.table(("登记结局", "本数"), rows, aligns=("left", "right")):
            emit(line)
        # 这两个数只覆盖"本次真的处理过的那几本"：热启动时全部 already_present，
        # 于是它们会是 0 —— 那不是"这些书没有文本层"，所以必须写清口径。
        emit(tty.bullet(
            f"本次处理的书里：有文本层 {ing.get('text_layer_ok')} 本 / 共 {ing.get('pages_total')} 页"
            f"（已登记的 {counts.get('already_present', 0)} 本没有重抽，故不计入）"))

    ex = run.get("extraction") or {}
    if ex:
        emit("")
        for line in tty.rule("模型读书（概念 / 关系，引文逐字回验）"):
            emit(line)
        if ex.get("error"):
            emit(tty.bullet(tty.paint(f"失败：{ex['error']}", "red")))
        else:
            for line in tty.table(
                ("读数", "值"),
                [("读懂的书", ex.get("processed")),
                 ("失败的轮次", ex.get("failed")),
                 ("新建概念", ex.get("concepts_created")),
                 ("新增关系", ex.get("relations_added")),
                 ("引文过验", ex.get("quotes_verified")),
                 # 这两行是两个阶段，不是一个数的两种说法：
                 # `relations_dropped` = 模型的引文在原文里根本找不到（抽取阶段就丢了）；
                 # `quotes_failed` = 活到落库那一步、带页码窗口的回验没过。
                 # 只打后者会让"日志里剔了 7 条、框里写 0"同时出现在一份输出里。
                 ("抽取阶段剔除", ex.get("relations_dropped")),
                 ("引文未过（已剔除）", ex.get("quotes_failed")),
                 ("无法判定", ex.get("quotes_unknown"))],
                aligns=("left", "right"),
            ):
                emit(line)
            if ex.get("relations_dropped"):
                # 这里不用 Markdown 的星号强调：`tty` 那一层不做 Markdown 渲染，
                # 星号会原样打到终端上（要强调就用 `tty.paint`，或把话写进句子里）。
                emit(tty.bullet(
                    "「抽取阶段剔除」="
                    + tty.paint(str(ex.get("relations_dropped")), "bold")
                    + " 指的是：模型给的关系里有这么多条的引文在原文里逐字找不到"
                    "（详见下面的剔除原因与日志）—— 它们没有进库，所以"
                    "「新增关系 + 抽取阶段剔除」才是模型一共提了多少条关系"))
                why = _summarize_drop_reasons(ex.get("drop_reasons"))
                if why:
                    emit(tty.bullet("剔除原因：" + tty.paint(why, "yellow")))
            for err in (ex.get("errors") or [])[:5]:
                emit(tty.bullet(tty.paint(json.dumps(err, ensure_ascii=False, default=str)[:150], "yellow")))
            mdl = ex.get("model") or {}
            if mdl:
                # 这一步的花销不在 `--budget-usd` 的口径里（那个额度是主题作答那一跑的），
                # 所以必须单独打出来 —— 否则"预算没超"会被读成"这次没花多少钱"。
                emit(tty.bullet(
                    f"这一步的模型花销 {tty.paint(str(mdl.get('charged_usd')) + ' USD', 'bold')}"
                    f" / {mdl.get('calls')} 次调用 / tokens in {mdl.get('tokens_in')} "
                    f"out {mdl.get('tokens_out')}（不在 --budget-usd 的额度里："
                    "那个额度只管主题作答那一跑，这里的上界是轮数=本数）"))
                if mdl.get("uncharged_calls"):
                    emit(tty.bullet(tty.paint(
                        f"其中 {mdl['uncharged_calls']} 笔没有入账（meter 未接线或判重放）"
                        "—— 那不是 0 元，是没记上", "yellow")))
            if ex.get("store_counts"):
                emit(tty.bullet(f"库里现在：{ex['store_counts']}"))

    for n in run.get("notes") or []:
        emit(tty.bullet(tty.paint(n, "yellow")))

    if result:
        emit("")
        for line in tty.panel(
            "这一跑的结果",
            [("退出码", f"{_exit_badge(result.get('exit_code'))}（{result.get('reason')!r}）"),
             ("模型调用", f"{result.get('calls')} 次 / 本次花费 {result.get('spent_usd_this_run')} USD"),
             ("Lean", (lambda ln: f"开启={'是' if ln.get('enabled') else '否'}；"
                                 f"跑过={'是' if ln.get('ran') else '否'}；"
                                 f"proof 级证据 {ln.get('proved', 0)} 条"
                                 f"（片段 {ln.get('snippets', 0)} 个）")(result.get("lean") or {})),
             ("六件产物", ", ".join(result.get("artifacts") or []) or "(无)")],
            verbatim=[("产物目录：", run.get("out_dir") or "(无)")],
            tone="green" if result.get("exit_code") == 0 else "yellow",
        ):
            emit(line)
    else:
        print("[project] 本次没有跑模型那一步（没给 --topic）")
    return int(result.get("exit_code", 0)) if result else 0


# ---------------------------------------------------------------- 交互台

#: 主菜单：(按键, 说明, 处理函数名)。每一项都收 `(ask, out)` 两个口子（缺省 `input`/`print`），好让整台菜单能用
#: 脚本化输入在测试里驱动、不必真占一个终端（判据一律要能离线、确定性地跑）。
#: ---- 废案留痕（`R8`-A-1；出处 `draft/65` §2 与 `draft/65a` §A-1）----
#: 原先第 5 项是"离线自检"：`MENU` → `SHELL_ACTIONS["5"]` → `_shell_demo` → `main(["demo", "--keep"])`。
#: `draft/41-H:55` 把它写成设计；`demo.py` 由 `tests/test_demo_end_to_end.py` 6 条钉住（`draft/48-09:890` 的"唯一不需要 key 的端到端路径"），真机面零实例见 `draft/48-09:893`。
#: 淘汰与处置（`draft/44:95` L-04h、`draft/48-09:878-880`）：`demo.py` 不删、只从 `MENU` 摘掉入口，改为文档说明
#: `python -m agentflow.cli demo`。教训：新增主入口 X 时只加子命令、没加菜单格 ⇒ 同批把 X 加进 `MENU`，
#: 并写元判据断言 `"X" in MENU 文本`（判据在 `tests/test_r8_retired_entries.py`）。
MENU: tuple[tuple[str, str, str], ...] = (
    ("1", "项目：列出 / 计划 / 运行（冷启动或热启动）", "project"),
    ("2", "端到端跑一个主题（联网检索；需要模型 key）", "run"),
    ("3", "看数据状态 / 校验全局不变量", "status"),
    ("4", "看某个角色的工具面（只读角色看不到写工具）", "tools"),
)


def _ask_text(ask, prompt: str, default: str = "") -> str:
    """问一行自由文本；空输入就用缺省值（缺省值会显示在提示里）。"""
    tail = f" [{default}]" if default else ""
    got = str(ask(f"{prompt}{tail}: ") or "").strip()
    return got or default


def _ask_yes(ask, prompt: str, *, default: bool = False) -> bool:
    got = str(ask(f"{prompt} ({'Y/n' if default else 'y/N'}): ") or "").strip().lower()
    if not got:
        return default
    return got in ("y", "yes", "是", "1")


def _shell_project(ask, out) -> int:
    """菜单第 1 项：项目式用法。把用户答的几件事翻成 `project run` 的 argv。"""
    out("")
    for line in tty.rule("项目"):
        out(line)
    rows = _project_rows()
    if rows:
        for line in tty.table(("项目", "状态", "冷/热", "上次"),
                              [(r["name"], _state_badge(r["state"]),
                                f"{r['cold_runs']}/{r['warm_runs']}", str(r["last_mode"] or "-"))
                               for r in rows]):
            out(line)
        out(tty.paint("  提示：输入一个已存在的项目名 = 热启动（复用它的库与产物）", "grey"))
    else:
        out(tty.paint("  还没有任何项目；第一次跑会自动取 project1。", "grey"))

    name = _ask_text(ask, "  项目名（回车 = 自动取下一个）")
    books = _ask_text(ask, "  本地书架目录（回车 = 不用本地书，例如 D:\\books）")
    topic = _ask_text(ask, "  研究主题（回车 = 只做登记与冷/热启动，不调模型）")
    if not books and not topic:
        # 三个问题全按回车 ⇒ 这一步什么都不会做，却会新建一个项目文件夹。
        # 那正是"手滑建出一堆空项目"的来源（2026-09-28 实测：一次菜单冒烟测试
        # 就这么建出了 project2，项目卡里 run-1 的 result 是 None）。
        # 缺省必须是"不建"：新建目录是不可逆的动作，不该由三次回车触发。
        if not _ask_yes(ask, "  什么都没填 —— 这会只新建一个空项目文件夹（登记 0 本、不调模型）。"
                             "确定要建吗", default=False):
            out(tty.paint("  （没有建任何东西）", "grey"))
            return 0
    argv = ["project", "run"]
    if name:
        argv += ["--name", name]
    if books:
        argv += ["--books", books]
    if topic:
        argv += ["--topic", topic]
    if books and _ask_yes(ask, "  先让模型把书读一遍（抽概念/关系，逐字回验）", default=False):
        argv += ["--extract", "--extract-rounds",
                 _ask_text(ask, "  最多读几本（一轮一本）", "7")]
    out(tty.paint("  即将执行：agentflow " + " ".join(argv), "grey"))
    out("")
    return main(argv)


def _shell_run(ask, out) -> int:
    """菜单第 2 项：联网的端到端主题跑（`agentflow run`）。"""
    out("")
    for line in tty.rule("端到端跑一个主题（联网检索）"):
        out(line)
    topic = _ask_text(ask, "  研究主题")
    if not topic:
        out(tty.paint("  没给主题 ⇒ 什么都没做（这一步没有缺省主题，编一个会让产物对不上）", "yellow"))
        return 2
    budget = _ask_text(ask, "  预算（美元，调用前检查）", "0.5")
    calls = _ask_text(ask, "  最多调用几次模型", "2")
    out("")
    return main(["run", "--topic", topic, "--budget-usd", budget, "--max-calls", calls])


def _shell_status(ask, out) -> int:
    out("")
    for line in tty.rule("数据状态"):
        out(line)
    rc = main(["status"])
    if _ask_yes(ask, "  顺便校验全局不变量（verify）", default=True):
        out("")
        rc = max(rc, main(["verify"]))
    return rc


def _shell_tools(ask, out) -> int:
    out("")
    for line in tty.rule("角色工具面"):
        out(line)
    out(tty.paint("  可用角色：" + " ".join(S.ROLES), "grey"))
    role = _ask_text(ask, "  角色", "H")
    out("")
    return main(["tools", "--role", role])


# `R8`-A-1 的退场点：这里原有 `def _shell_demo(ask, out) -> int:`（删于 2026-10-07）。
# 它原先只做一件事：打三行提示，然后 `main(["demo", "--keep"])`。
# `demo` 子命令原样保留（唯一不需要模型 key 的端到端路径，`tests/test_demo_end_to_end.py`
# 6 条钉住；`draft/48-09:899` 逐字"不许删 `demo.py`"）⇒ 摘掉的只是交互台的入口，
# 命令仍然可达（`python -m agentflow.cli demo`）。四块留痕见 `MENU` 上方那一段。


#: 菜单按键 -> 处理函数。键就是 `MENU` 里那个按键。
SHELL_ACTIONS = {
    "1": _shell_project,
    "2": _shell_run,
    "3": _shell_status,
    "4": _shell_tools,
    # `R8`-A-1：这里原有 `"5": _shell_demo,`（连同 `MENU` 第 5 项一起摘掉，见上方留痕）。
}


def _state_badge(state: str) -> str:
    """把项目文件夹的四态翻成徽标（`workspace` 之外的三态都是"还不能直接用"）。"""
    mapping = {"workspace": "ok", "absent": "cold", "empty": "cold", "not_a_project": "unknown"}
    return tty.badge(mapping.get(state, state))


def _project_rows() -> list[dict]:
    from . import projects as P

    try:
        return P.list_projects(P.projects_dir(None))
    except Exception:  # noqa: BLE001 - 列表读不出来不该让菜单崩掉
        return []


def shell(ask=input, out=print) -> int:
    """不带参数运行 `agentflow` 时进的那一屏：一份菜单，而不是一串用法错误。

    两个口子（`ask` / `out`）缺省是真的终端输入输出；测试传脚本化的替身。
    退出：`q` / 回车（空输入）/ EOF / Ctrl-C 都算正常退出（0）——
    "用户不想继续了"不是错误。
    """
    out("")
    for line in tty.panel(
        "agentflow · 面向数学研究的多智能体协同框架",
        [("这是什么", "主控 M 按需唤起 A–H 八个角色；产物带可复核的证据链"),
         ("先读什么", "README.md §1–§3；规范是 DEVELOPMENT.md 与 docs/ROLE-SPECS.md"),
         ("现状", "全部代码由 AI 编写，禁改区改动未经人逐行走查（见 HANDOFF）")],
        tone="cyan",
    ):
        out(line)
    out("")
    while True:
        for key, text, _fn in MENU:
            out(f"  {tty.paint(key, 'bold', 'cyan')}) {text}")
        out(f"  {tty.paint('q', 'bold', 'cyan')}) 退出")
        try:
            choice = str(ask(tty.paint("请选择", "bold") + " > ") or "").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("")
            return 0
        if choice in ("", "q", "quit", "exit", "0"):
            out(tty.paint("（退出）", "grey"))
            return 0
        action = SHELL_ACTIONS.get(choice)
        if action is None:
            out(tty.paint(f"  没有这一项：{choice!r}（可用：{'/'.join(k for k, _t, _f in MENU)}/q）",
                          "yellow"))
            continue
        try:
            rc = action(ask, out)
        except (EOFError, KeyboardInterrupt):
            out("")
            return 0
        out("")
        out(tty.paint(f"  （上一步退出码 {rc}）", "grey"))
        out("")


def _exit_badge(code: Any) -> str:
    """退出码徽标：0/1/2 对应本项目的三态，不许把 2 折成 1。

    0 = 成功产出（绿）· 1 = 查过了、发现问题（红）· 2 = 没查成（黄）。
    第一版写成 `success if code == 0 else failed`，于是"没 key ⇒ 退出码 2"被画成了
    红色的 failed —— 那正是本项目反复强调不许折叠的那一档：
    它说的是"这一次没查成"，要做的动作是去配 key 或重试，而不是去查结论。
    """
    text = str(code)
    key = {"0": "success", "1": "failed", "2": "not_checked"}.get(text, text)
    return f"{tty.badge(key)}  {text}"


#: 产品路径上造模型缝的唯一入口。测试可以 monkeypatch 它来注入替身模型
#: （这样"CLI 这条路"能在离线单测里被真跑一遍，而不是只测库层）。
def _agent_seam_factory(role: str, *, root: Path, sid: str | None, usd_budget: float | None,
                        store: Any = None):
    """按角色造一个模型缝（key 与端点一律来自环境变量）。

    `store` 给定时，缝同时把每次调用记进 `usage_ledger`（`draft/37` §64）：
    `run-agent` 这条路此前「没有任何地方记账」，钱只活在内存与会话事件里 ——
    于是账本对一次真花了 0.289069 美元的运行报"0.000000"，而按账本判上限的
    `reviewaccept.within_cost_cap` 据此报"没超上限"（假绿）。
    不给 `store` ⇒ `meter=None` ⇒ 如实报"没有入账"（不是记一笔零）。
    """
    from . import budget as B
    from .llmseam import LlmSeam
    from .tokenmeter import TokenMeter

    # `budget_of`：每一次花钱之前现读这一趟的总预算（业主 2026-10-12：
    # 「用户可追加预算，运行消耗的钱从总预算里实时扣除」）。`usd_budget`（命令行给的）
    # 是寄存器缺席时的兜底 —— 两者都在 `budget.limit_usd` 里合一，别在这里再判一次。
    read_limit = (lambda: B.limit_usd(root, fallback=usd_budget))
    meter = TokenMeter(store, budget_usd=usd_budget) if store is not None else None
    return LlmSeam.for_role(role, session_root=root, sid=sid, usd_budget=usd_budget,
                            meter=meter, budget_of=read_limit)


def _parse_drive(items) -> tuple[dict, str]:
    """把 `--drive 角色.动作` 解析成接线表；不合法就返回 `(空表, 理由)`。"""
    table: dict[tuple[str, str], dict] = {}
    for item in items or []:
        role, _, action = str(item).partition(".")
        if not role or not action:
            return {}, f"--drive 要写成 角色.动作（收到 {item!r}）"
        table[(role, action)] = {}
    return table, ""


#: 单趟 `run-agent` 的退出码分类表（业主 2026-10-19 重排；`--help`、`cmd_run_agent` 的
#: docstring、`_run_agent_exit_code` 的 docstring 三处同口径，逐档都对得上这里）。
#: 为什么是一张表而不是一串 `if`：这是防漏，不是风格 —— 新增一个 `stop_reason` 时若有人忘了来这张
#: 表登记，它就落进 `EXIT_CODE_WHEN_UNKNOWN`（= 1，行为异常），一次当场可见的异常；写成 `if` 链时
#: 新取值会静默落到最后的 `return 1`（1 曾经就是"其余"这一档）。判据
#: `tests/test_run_agent_exit_code_table.py` 从源码里现扫 `stop_reason` 的取值集合与这张表对拍，少一条就红。
#: 六档：0 正常完成（给了 `final`）· 1 行为异常 · 2 研究启动失败（连跑都没开始）· 3 等待用户
#: （`--resume` 接着跑）· 4 正常且中途停止 —— 用户叫停（强停与优雅停同档）＋ 预算耗尽 · 5 正常且自行停止但没有 final。
EXIT_CODE_BY_STOP: dict[str, int] = {
    # ---- 0 正常完成（给了 final）
    "final": 0,
    # ---- 3 等待用户（人答完 --resume 接着跑）
    "waiting_for_user": 3,
    # ---- 2 研究启动失败（连跑都没开始）：一步模型都没调就交回去了
    "checkpoint_mismatch": 2,      # 拿 A 的进度续 B（两件事混成一条）
    "no_checkpoint": 2,            # 检查点读不到、会话记录也重建不出任何一步
    "already_finished": 2,         # 上一趟已 final ⇒ 续跑没有意义
    "resume_no_transcript": 2,     # 会话记录里重建不出那一步 ⇒ 不许从第 1 步重跑
    # ---- 4 系统行为正常且中途停止：有人（用户 / 父 / 钱）把它叫停，不是它自己想停
    "budget": 4,                   # 预算耗尽（优雅停，可 --resume）
    "stop_file": 4,                # 停机开关（优雅停：做完第 N 步再收工）
    "force_stop": 4,               # 停机开关 + force（强停，同样不等待收尾地收工）
    "ask_cancelled": 4,            # 问用户的等待被当前轮次的取消信号中止
    # `interrupted_by_parent`：父角色对某一个孩子当前那一轮下的 `stopctl.request_interrupt`
    #   默认理由码（`stopctl.INTERRUPT_REASON`）。归 4 而不是 5：停意是外面叫的
    #   （父是受权的叫停者，与"用户叫停"同一族），不是这个循环自己判定该收工；
    #   而且这一档也写了收尾说明、可 `--resume`。若归 5，读的人会以为是它自己决定
    #   收工、于是去等召唤者的下一步，而其实是召唤者叫它停的。
    "interrupted_by_parent": 4,
    # ---- 5 系统行为正常且自行停止，但没有 final
    "no_progress_limit": 5,        # 同调用 + 同读数连击到上限：这一趟没有新事实
    # `escalated`：交给召唤者、本趟自行收工（语义由另一条线落地；这里先登记，
    #   因为它属于"它自己决定停"这一族 —— 与 `no_progress_limit` 同档，不是异常）。
    "escalated": 5,
    # ---- 1 行为异常（只留给"真出事"）
    "not_wired": 1,                # 没接线（没有 key / 没进登记表）
    "model_auth_failed": 1,        # 模型没认这把 key
    "model_timeout": 1,            # 模型没返回（超时）
    "model_unreachable": 1,        # 没连上模型（网络 / DNS）
    "model_output_limit": 1,       # 思考吃光输出预算
    "bad_json_limit": 1,           # 坏 JSON 连击
    "bad_args_limit": 1,           # 坏参数连击
    # `no_notify`：收工不带 notify 表、连打回三次（L-05e 之后循环不再产生它 ——
    #   它已降级成读数；这一格留给旧会话记录，取值本身仍是"协议不遵"⇒ 异常）。
    "no_notify": 1,
}

#: 没登记的 `stop_reason` 一律归这里。不许改成 0：那会把"新增了一档而没人归类"
#: 读成"做完了"—— 一次新故障变成绿灯，且没有任何地方会红。
EXIT_CODE_WHEN_UNKNOWN: int = 1

#: 已知 `stop_reason` 的清单（表里登记过的那些）。
#:
#: 刻意从表派生而不是手抄第二份：手抄一份会与表两处漂移，而"两处漂移"恰恰是这条
#: 纪律想治的病。真正独立的那一腿在判据里 —— 它从 `agent_loop.py` 的源码现扫
#: 生产点，与这里对拍（少一条就红）。
KNOWN_STOP_REASONS: frozenset[str] = frozenset(EXIT_CODE_BY_STOP)


def _run_agent_exit_code(run) -> int:
    """单趟 `run-agent` 的退出码：查 :data:`EXIT_CODE_BY_STOP` 那张表，不做 `if` 链。

    - `0` 正常完成（给了 final）；
    - `1` 行为异常（只留给"真出事"）；
    - `2` 研究启动失败（连跑都没开始）；
    - `3` 等待用户（人答完 --resume 接着跑）；
    - `4` 系统行为正常且中途停止（用户叫停 —— 强停与优雅停 —— ＋ 预算耗尽）；
    - `5` 系统行为正常且自行停止，但没有 final。
    为什么 4 与 5 必须分成两档：都不是异常，但下一步该谁动不同（4 是"有人叫停"：人 / 父 / 钱，加预算
    或人答完即可 `--resume`；5 是"它自己判定收工"：原地打转 / `escalated` 交给召唤者）。未登记的
    `stop_reason` 一律 1（安全侧）：落进 1 会当场被看见，落进 0 会把新故障读成"做完了"（`--help` 与 `cmd_run_agent` 的 docstring 必须同口径；业主 2026-10-19 重排）。
    """
    return EXIT_CODE_BY_STOP.get(str(getattr(run, "stop_reason", "") or ""),
                                 EXIT_CODE_WHEN_UNKNOWN)


#: 多轮驱动层（`--rounds N`）特有的结束形态 —— 它们刻意不进
#: :data:`EXIT_CODE_BY_STOP`：那张表说的是"一趟循环为什么停"，而这两个说的是
#: "多轮驱动为什么收"。混进去会让判据的生产点对拍（它扫的是 `agent_loop.py` 的
#: `LoopRun`）多出两条永远对不上的档，于是那张表就不再是"循环的口径"。
#:
#: 只有 `resumed_done` 能直接映射；`rounds` 还要读"最后那一轮有没有 final"，
#: 所以它由 :func:`_autonomy_exit_code` 单独判（见那里）。
AUTONOMY_ONLY_EXIT_CODE: dict[str, int] = {
    # 续跑完成：这一程要补的轮数在上一段已经跑完（`autonomy` 直接交回）
    "resumed_done": 0,
}


def _rounds_has_final(auto) -> bool:
    """轮数用完那一档要读的东西：最后那一轮到底有没有交出结论。"""
    reports = list(getattr(auto, "reports", None) or [])
    return bool(reports) and bool(str(getattr(reports[-1], "final", "") or "").strip())


def _autonomy_exit_code(auto) -> int:
    """多轮驱动层（`--rounds N`）的退出码：查同一张表，只多"轮数用完"这一档。

    业主 2026-10-19 裁定（这条是根因，不是特例）：同一件事不许在两处有两套口径。改前这一层自成一条
    `if` 链（`rounds`/`stop_file`/`resumed_done ⇒ 0`、`其余 ⇒ 1`），于是同一个 `budget` 在单趟是 4、
    在多轮是 1，`stop_file` 在单趟是 4、在多轮是 0 —— 两种口径都会漂，而且漂了没有任何东西会红。
    现在：所有 `stop_reason` 一律查 :data:`EXIT_CODE_BY_STOP`，未登记的落进 :data:`EXIT_CODE_WHEN_UNKNOWN`。
    表里没有、只有这一层有的两种形态：`rounds`（轮数用完）最后那一轮产出了 final ⇒ `0`；没有 final
    ⇒ `5`（正常且自行停止、但没有 final）—— 轮数用完不等于做完了，把它读成 0 会让"跑到上限但一句话
    没说"看起来像成功。`resumed_done`（续跑发现这一程已跑完）⇒ `0`（见 `AUTONOMY_ONLY_EXIT_CODE`）。
    判据：`tests/test_run_agent_exit_code_table.py::test_the_two_layers_read_the_same_table` 把同一组
    `stop_reason` 分别喂给两个入口、逐条断言退出码相等；负控把这一层改回写死 `budget ⇒ 1` ⇒ 当场红。
    """
    reason = str(getattr(auto, "stop_reason", "") or "")
    if reason == "rounds":
        return 0 if _rounds_has_final(auto) else 5
    if reason in AUTONOMY_ONLY_EXIT_CODE:
        return AUTONOMY_ONLY_EXIT_CODE[reason]
    return EXIT_CODE_BY_STOP.get(reason, EXIT_CODE_WHEN_UNKNOWN)


def _sid_suffix(sid: str | None) -> str:
    """`--sid <号>` 那一段（空 sid 就整段不出现）。

    为什么不写成 `--sid {sid or ''}`：没给 sid 时那样会打印出一个光秃秃的 `--sid`，
    人照抄会被 argparse 判成"缺少参数"（退出码 2）—— 与 `--root` 写错位置同族。
    打印给人敲的命令，必须是「照抄就能跑」的那一版。
    """
    return f" --sid {sid}" if sid else ""


def _waiting_notice(run, *, root: Path, sid: str | None) -> str:
    """停在等用户时那一行醒目提示：停在谁身上、下一步该敲什么。

    三件事逐条给出来（问题号 + 问题原文前 80 字 + 三条命令），因为这一刻的读者
    手里只有终端：只给"waiting_for_user"这个词，她还得自己去翻待答清单。

    三条命令一律把 `--root` 写在子命令「之前」：`--root` 是顶层参数，argparse 不许它
    出现在动词后面。此前这三条写在后面，实测照抄会得到
    `error: unrecognized arguments: --root …` 且退出码 2（看着像命令不存在）。
    判据 `tests/test_user_channel_stop_and_resume.py::
    test_the_commands_printed_in_the_hint_actually_run` 会把这里打出来的命令
    逐条真跑一遍，所以这条顺序不许再漂。
    """
    from . import userio as U

    qid = run.waiting_for or "（没有记到问题号）"
    text = ""
    for q in U.pending_questions(root, sid=sid):
        if q.qid == qid:
            text = q.text[:80]
            break
    sid_arg = _sid_suffix(sid)
    return (f"停在等待用户：{qid} {text}；下一步："
            f"`agentflow --root {root} inbox{sid_arg}` / "
            f"`agentflow --root {root} answer {qid} \"<回答>\"{sid_arg}` / "
            f"`agentflow --root {root} run-agent --resume …{sid_arg}`")


def cmd_run_agent(args) -> int:
    """真跑一次角色循环（顶层角色走它自己的循环；`--drive` 决定被召唤的子角色）。

    退出码是「六档」，逐档由 :data:`EXIT_CODE_BY_STOP` 那张表定（`--help` 与 `_run_agent_exit_code` 的 docstring 与这里同口径；业主 2026-10-19 重排）：
    - `0` 正常完成（`stop_reason="final"`，给了结论）；
    - `1` 行为异常（只留给"真出事"：没接线 / 模型没认 key / 没返回 / 连不上 / 输出吃光 / 坏 JSON
      超限 / 坏参数超限 / 没 notify，以及任何没登记的新 `stop_reason` —— 没登记一律归 1，安全侧）；
    - `2` 研究启动失败（检查点读不到 / 任务指纹不符 / 上一趟已收工 / 会话记录里重建不出那一步）；
    - `3` 等待用户（`ask_user` 问了人、还停在等回答；人答完（`agentflow answer`）之后用 `--resume`）；
    - `4` 系统行为正常且中途停止（用户叫停（强停与优雅停）与预算耗尽统一这一档；加预算或人答完即可 `--resume`）；
    - `5` 系统行为正常且自行停止，但没有 final（原地打转 / `escalated` 交给召唤者）。
    `--rounds N` 那条多轮路径查的是同一张表（`_autonomy_exit_code`），只多两档多轮特有形态：轮数
    用完且最后那轮给了 final ⇒ 0、没给 final ⇒ 5；续跑发现这一程已跑完（`resumed_done`）⇒ 0。
    ## 三个"花钱的判断类能力"开关：默认全关，互不连带 —— `--semantic-review`（H 的语义判据）/ `--attack-reasoning`（F 的攻坚推理）/ `--experiment-reasoning`（E 的写脚本推理，S-10(a) 的 `author_script`）。三条同一条纪律：环境里有 key 也不改变行为。
    `--attack-reasoning` 不连带打开 E 的缝（两个开关各自可解释：F 想这一步怎么打、E 把判据写成
    一份能跑的脚本）。代价必须知道：只开 F 的缝时，F 需要脚本的那一轮写不出来 ⇒ 落
    `dead_end(缺工具)` 并上报 `missing_input`（缺的是 E 的缝）。改前它是静默的 `no_change`（真机
    `projects/mp4` 计划 000003 的 r1/r2 逐字："子目标 sg1 有判据但没有脚本，而 E 没能把它写出来
    （no_seam）⇒ 未推进"）——"有判据没脚本"与"跑了但没结果"在读数上从此分得开。
    """
    from . import agent_loop as AL
    from . import autonomy as AU
    from . import host as H

    table, why = _parse_drive(getattr(args, "drive", None))
    if why:
        print(f"[run-agent] 用法错：{why}", file=sys.stderr)
        return 2
    if bool(getattr(args, "subagents", False)):
        # `--subagents`（2026-09-30）：把所有已声明的角色动作都交给模型驱动 ——
        # "各角色像主控的 subagent"这句话的部署开关。
        #
        # 为什么是一个显式开关而不是默认值：默认驱动一切会把"确定性代码"的活
        # （A 的检索编排、B 的按行整理、D 的图计算…）也换成模型调用，
        # 而 `host.DEFAULT_LLM_LOOPS` 的注释写着装配期纪律："不许因为环境里有 key
        # 就改变行为"。所以默认仍是"只跑确定性动作"，要 subagent 语义就明说。
        # 真机实测（`temp/live-collab-fanout-20260930-145743.txt`）：把确定性动作
        # `B.run_once` 交给 LLM 循环会替换掉那份确定性整理 —— 3 个 B 实例各烧
        # 7–8 步、以 bad_json_limit 收场、概念与关系一条没涨。批量消化这类活应当
        # 让角色跑确定性动作（并发由实例轴给），只把"判断类"动作交给模型。
        from . import capabilities as _C
        from . import schema as _S

        for _role in _S.ROLES:
            for _spec in _C.actions_for(_role):
                table.setdefault((_role, _spec.action), {"max_steps": args.max_steps})
        print(tty.paint(f"[run-agent] --subagents：已把 {len(table)} 个 (角色,动作) 交给模型驱动"
                        "（含确定性动作 —— 那会被 LLM 循环替换，见 --help 的说明）", "bold"))
    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()

    # ---- 会话身份在这一刻定下，之后整趟不再漂移（`draft/37` §63，修法 B）
    #
    # 为什么要在装配之前解析出来：`sessions.append(..., sid=None)` 的缺省值是
    # 「写入那一刻」的 `session_id()`（环境变量优先，否则当天日期）。此前 `run-agent`
    # 把 `sid=None` 一路传下去，于是"这一趟是哪一段会话"谁都没说清 ——
    # 运行内 `conductor.closing` 按缺省读，读到的可能不是这一趟写的那一段：
    # 实测第 11 趟（`--sid real11`）运行内报 `can_close: true`，而外部带 sid 的
    # 读数报 `failed: ['user_pending']` —— 假绿，且只在运行内出现。
    # 解析一次、之后原样带下去，工具面与写入面读的就是同一个文件；
    # 顺带把"跨零点的一趟会被劈成两个会话文件"这件事也去掉了
    # （缺省 sid 按天，而一趟可以有 3600 秒墙钟）。
    from . import sessions as SS

    if not getattr(args, "sid", None):
        args.sid = SS.session_id()

    def seam_for(role_name: str):
        return _agent_seam_factory(role_name, root=root, sid=args.sid,
                                   usd_budget=args.budget_usd, store=st)

    seam = seam_for(args.role)
    if not seam.wired:
        # 2026-10-19 口径：2 = 研究启动失败（连跑都没开始）。这句里刻意不再出现"没查成"
        # —— 同一句话里两种标签并存时，读的人会拿旧的那一种去解释 2。
        print("[run-agent] 研究启动失败：没有接模型（环境变量 AGENTFLOW_MODEL_API_KEY 与 "
              "agentflow/settings.json 的 model.api_key 都没有值）—— "
              "这是研究启动失败（退出码 2），不是「跑过了没问题」", file=sys.stderr)
        return 2

    loops = {key: {"max_steps": args.max_steps} for key in table}
    # ---- A 的检索后端（2026-09-30 修）
    #
    # 为什么必须在这里建：`wired_llm_conductor` 一直收 `providers=`，但从来没有人传 ⇒
    # `_Builder.status()` 把 A 判成 `no_provider`、A 不进登记表 ⇒ 任何角色唤起 A 都落
    # `refused/not_wired`。真机实测（`draft/28` §201）：G 明明按协议唤起了 A，
    # 拿回来的却是"A 没有接线（registry 里没有它）"—— 文献检索这条最重要的协同边
    # 在协同运行里从来就没接上过。用户口径："A 的文献检索必须要通关。"
    #
    # 口径与 `run-a` 逐字一致（`cmd_run_a` 那三行）：先看 `--provider`，再看配置里的
    # `agent_a.providers`，都没有才用 openalex。不一致的默认值本身就是"凌乱"的一种，
    # 所以这里刻意复用同一段逻辑（`_build_providers`）而不是再写一遍。
    # `args` 在测试里常是手搭的 `Namespace`（那些用例只关心循环本身），所以三个新参数
    # 一律 `getattr(..., None)` 取 —— 缺了就当"没给"，而不是让整个 `run-agent` 崩在属性上。
    cfg = load_config(root, getattr(args, "config", None))
    prov_names = (str(args.provider).split(",") if getattr(args, "provider", None)
                  else (cfg.get("agent_a") or {}).get("providers", ["openalex"]))
    providers = _build_providers(cfg, list(prov_names), root)
    # 墙钟可配（`draft/37` §16 P0）：不给 `--wall-clock-sec` 时用 `Policy` 的缺省值，
    # 于是"这次运行能给多久"从写死的 900 秒变成一个显式参数。
    from .policy import Policy

    wall = getattr(args, "wall_clock_sec", None)
    # 2026-10-18（缺陷 ⑳，业主口径「墙钟可以干脆不设」）：`--wall-clock-sec 0` ⇒ 不设上限。
    # 真机证据（`projects/t2y`，T2）：我没有传这个参数，于是用了 `default=3600.0`，
    # 1 小时整被切断 —— 而切断的那一刻 M 正要派 B 去登记命题：
    #   t-000009 E ← refused「墙钟截止已过（wall_clock_sec=3600.0）」
    #   t-000010 B ← refused 同上
    # 结果就是 `conjectures 3 / statements 0`：研究工作做完了，收尾那一步被墙钟砍掉。
    # 0（或负数）显式表示"不设上限"，与"我没传"区分开（后者仍走缺省 3600）。
    if wall is not None and float(wall) <= 0:
        wall = None
    # `Policy.usd_budget` 必须拿到同一个数（业主 2026-10-12 的预算轴；只读调查发现
    # 这一格此前从来没被灌过 —— 改前 `Policy(wall_clock_sec=wall)`，
    # 于是 `conductor` 那个全局 meter 的 `budget_usd=None`、
    # 「编排层的全局 USD 守卫实际不受 --budget-usd 约束」）。
    # 与别处同一条取值口径：命令行给的数 > 无（不限）—— 寄存器那一档由
    # `budget.limit_usd` 在每一次闸门上现读，不在这里预先合并。
    usd_cap = getattr(args, "budget_usd", None)
    pol = Policy(wall_clock_sec=wall, usd_budget=usd_cap) if wall is not None \
        else Policy(usd_budget=usd_cap)
    # `--stop-file` 接给谁（`draft/37` §125）：「单趟」那一档接进步循环（它此前根本
    # 没有停机点 —— 真机实测：用户叫停后继续跑完 60 多个任务、烧掉 $0.98，最后被强杀，
    # 台账里没有 `agent_run_end`、盘上没有步检查点）；多轮自主跑那一档照旧由
    # `autonomy._stop_before_round` 在「每轮之间」查，两处不叠加（避免"一轮跑到一半
    # 停下"把那一轮的汇报与检查点弄成半截）。
    multi_round = bool(args.rounds and args.rounds > 1)
    wiring = H.wired_llm_conductor(st, loops=loops, session_root=root, sid=args.sid,
                                   max_steps=args.max_steps, usd_budget=args.budget_usd,
                                   workspace_root=str(root), seam_factory=seam_for,
                                   providers=providers, config=cfg, policy=pol,
                                   semantic_review=bool(getattr(args, "semantic_review", False)),
                                   attack_reasoning=bool(getattr(args, "attack_reasoning", False)),
                                   experiment_reasoning=bool(
                                       getattr(args, "experiment_reasoning", False)),
                                   stop_file=(None if multi_round
                                              else getattr(args, "stop_file", None)))
    if not providers:
        # 三态：A 这条路这一轮是没接线（不是"没有文献"）。说清楚，别让人去猜。
        print(tty.paint(
            "[run-agent] 注意：A 没有接任何检索后端 ⇒ 唤起 A 会如实落 refused/not_wired"
            "（想离线验证就用 --provider fixture）", "yellow"))
    if args.rounds and args.rounds > 1:
        auto = AU.run_autonomous(args.role, args.task, store=st, registry=wiring["registry"],
                                 conductor=wiring["conductor"], session_root=root,
                                 seam=seam, rounds=args.rounds, report_every=args.report_every,
                                 usd_budget=args.budget_usd, max_steps=args.max_steps,
                                 sid=args.sid, from_env=False, resume=bool(args.resume),
                                 stop_file=args.stop_file,
                                 user_timeout_sec=getattr(args, "user_wait_sec", None))
        print(tty.paint(f"角色 {args.role} 自主跑完 {auto.rounds_done} 轮"
                        + (f"（其中 {auto.resumed_from} 轮是上一段做过的）"
                           if auto.resumed_from else ""), "bold"))
        print(f"  检查点：{auto.checkpoint}")
        for rep in auto.reports:
            print(f"  第 {rep.index} 轮：{rep.stop_reason}"
                  f"{'（汇报已发公共频道）' if not rep.report_sent else '（汇报未发出：' + rep.report_sent + '）'}")
        print(f"  停止原因：{auto.stop_reason}；用量：{auto.spend}")
        for note in auto.notes:
            print(f"  注：{note}")
        # 退出码：同一张表（业主 2026-10-19 裁定；改前这一层自成一条 if 链，
        # 于是 `budget` 单趟 4 / 多轮 1、`stop_file` 单趟 4 / 多轮 0 —— 两套口径都会漂）。
        # 只有"轮数用完"（`rounds`）要看最后那一轮有没有 final，见 `_autonomy_exit_code`。
        # `checkpoint_mismatch`（拿 A 的进度续 B）同样查表 ⇒ 2 研究启动失败，
        # 不是"跑过了有问题" —— 它不再需要一条自己的分支。
        code = _autonomy_exit_code(auto)
        # 停在等用户（`draft/37` §72）：自主多轮那一层的停止判据现在有这一档了 ——
        # 上一轮停在等用户、而那个问题「还挂着」时，它不会开下一轮（`autonomy.py`
        # 的 `_stop_before_round`，判据在 `tests/test_resume_after_answer.py`）。
        # 退出码与单趟同档：3 = 停在等待用户（既不是完成也不是失败）。
        if auto.stop_reason == "waiting_for_user":
            pending = [r.index for r in auto.reports if r.stop_reason == "waiting_for_user"]
            print(tty.paint(
                f"[run-agent] 停在等待用户：第 {pending} 轮问了人、还停在等回答 —— "
                "后续轮次**没有**再开（不许替人把取舍定了）。"
                f"用 `agentflow --root {root} inbox{_sid_suffix(args.sid)}` 看，"
                f"答完再用 `--resume` 接着跑。", "bold"))
            return code
        # 已上报召唤者（`conductor.escalate`，业主 2026-10-19「父子天然双向」）：
        # 多轮驱动这一层的停止理由是从最后一轮抄上来的（`autonomy._stop_before_round`），
        # 所以它也会是 `escalated`。退出码从同一张表取（`EXIT_CODE_BY_STOP`），
        # 不在这里另写一个 5 —— 两处各写一个数字正是本文件已经治过的那种漂移。
        if auto.stop_reason == "escalated":
            print(tty.paint(
                "[run-agent] 已上报召唤者：最后一轮把孩子卡住的那件事写进了父的收件箱，"
                "后续轮次**没有**再开（不许替父把判断定了）。"
                "等父处理完再 `--resume` 接着跑。", "bold"))
            return code
        return code

    run = AL.run_role(args.role, args.task, store=st, registry=wiring["registry"],
                      conductor=wiring["conductor"], seam=seam, session_root=root,
                      workspace_root=str(root), sid=args.sid, max_steps=args.max_steps,
                      usd_budget=args.budget_usd, from_env=False,
                      user_timeout_sec=getattr(args, "user_wait_sec", None),
                      ask_policy=("unattended" if bool(getattr(args, "no_ask", False)) else None),
                      # `draft/37` §125：单趟这一档把停止开关接进步循环（多轮那一档
                      # 由 autonomy 在每轮之间查，两处不叠加）。
                      stop_file=(str(getattr(args, "stop_file", "") or "")
                                 if not multi_round else ""),
                      resume=bool(getattr(args, "resume", False)))
    code = _run_agent_exit_code(run)
    if args.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, default=str))
        if code == 3:
            # JSON 那一份必须保持可解析 ⇒ 那行醒目提示走 stderr
            print(_waiting_notice(run, root=root, sid=args.sid), file=sys.stderr)
        return code
    print(tty.paint(f"角色 {args.role} 的循环：{run.stop_reason}", "bold"))
    for step in run.steps:
        print(f"  [{step.index}] {step.shape}"
              + (f"：{json.dumps(step.payload, ensure_ascii=False, default=str)[:160]}" if step.payload else "")
              + (f"  ⇒ {step.problem}" if step.problem else ""))
    if run.final:
        # 停在等用户那一档不截断：这条结论里带的是「下一步该敲什么」，
        # 而工作区路径一长，400 字就会把它切在半个命令上（实测：切在
        # `…\AppData\Lo`）—— 而人恰恰要照抄这几条命令。其余各档照旧截断。
        text = run.final if run.stop_reason == "waiting_for_user" else run.final[:400]
        print(f"  结论：{text}")
    print(f"  唤起：{run.summons}；留言：{run.messages_sent}；用量：{run.spend}")
    if code == 3:
        print(tty.paint(_waiting_notice(run, root=root, sid=args.sid), "bold"))
    if code == 2:
        print(tty.paint(f"[run-agent] 没查成：{run.final}", "yellow"), file=sys.stderr)
    return code


def _ago(stamp: str) -> str:
    """一个时间戳距现在多久（人话）；读不出来时如实说读不出来。

    为什么这个读数值得占一列：人打开 `inbox` 最想先知道的是"它等了多久" ——
    等了 3 秒与等了 3 小时，下一步的动作完全不同（再等等 vs 去答）。
    """
    from datetime import datetime

    raw = str(stamp or "").strip()
    if not raw:
        return "（没有时间戳）"
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return f"（时间戳读不出来：{raw[:20]}）"
    now = datetime.now(when.tzinfo) if when.tzinfo is not None else datetime.now()
    delta = (now - when).total_seconds()
    if delta < 0:
        return f"未来 {abs(delta):.0f} 秒（时间戳比现在晚）"
    for limit, unit, div in ((60, "秒", 1), (3600, "分钟", 60), (86400, "小时", 3600)):
        if delta < limit:
            return f"{delta / div:.0f} {unit}"
    return f"{delta / 86400:.0f} 天"


def _option_text(option: Any) -> str:
    """一个选项渲染成一栏：`label — description`（没有说明就只给 label）。"""
    label = str(getattr(option, "label", "") or "")
    description = str(getattr(option, "description", "") or "")
    return f"{label} — {description}" if description else label


def _latest_run_stop(root: Path, *, sids: list[str] | None = None) -> str:
    """最近一趟的停止理由（读最新的 `agent_run_end` 事件）；读不到就说读不到。

    为什么它跟着"没有待回答的问题"一起打印：人打开 `inbox` 最常问的两句话是
    "它在等什么"与"它跑完了吗"。前一句由待答清单回答，后一句只有
    `agent_run_end` 里的 `stop_reason` 回答得出来 —— 而"什么都没有"这个输出
    对第二句话是不回答的（读者会把它读成"没事发生"）。
    """
    from . import sessions as SS

    want = list(sids) if sids else [str(r.get("sid") or "") for r in SS.list_sessions(root)]
    best: tuple[str, str, dict] | None = None
    for sid in want:
        if not sid:
            continue
        events, _problems = SS.read_session(root, sid=sid)
        for event in events:
            if event.get("kind") != "agent_run_end":
                continue
            ts = str(event.get("ts") or "")
            if best is None or ts >= best[0]:
                best = (ts, sid, event)
    if best is None:
        return ("最近一趟的停止理由：读不到（这些会话里没有 agent_run_end 事件 —— "
                "要么还没跑过，要么会话记录被挪走了）")
    ts, sid, event = best
    waiting = str(event.get("waiting_for") or "")
    extra = f"，停在等 {waiting}" if waiting else ""
    return (f"最近一趟（会话 {sid}，角色 {event.get('role')}，{ts}）的停止理由："
            f"{event.get('stop_reason')}（步数 {event.get('steps')}）{extra}")


def cmd_inbox(args) -> int:
    """列出等着用户回答的问题（只读）。

    不给 `--sid` 时扫这个工作区的「所有」会话。为什么面板是全局的：提问正阻塞着
    某一趟运行，而那一趟的会话可能不在人当前看的地方 —— 只在某一个会话里给入口，
    就会在它正阻塞模型的时候恰好不可达（这条界面纪律抄自 DSH 的 `dsh-client-ui-user-questions`，
    而它在我们自己的结构里同样成立：`DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」，
    所以人需要一个不挑会话的入口）。而真机每一趟都有自己的 sid ⇒ 只看缺省会话
    会把"它在等什么"读成"没有待答"。
    退出码 0 = 查过了（有待答与没有待答都算查过了）。
    """
    from . import userio as U

    root = Path(args.root or DEFAULT_ROOT).resolve()
    sid = getattr(args, "sid", None)
    sids = [sid] if sid else U.session_ids_with_questions(root)
    rows = [(s, q) for s in sids for q in U.pending_questions(root, sid=s)]
    if args.json:
        print(json.dumps([{**q.to_dict(), "sid": s} for s, q in rows],
                         ensure_ascii=False, indent=2, default=str))
        return 0
    if not rows:
        print(tty.bullet("没有待回答的问题。"))
        print(tty.bullet(_latest_run_stop(root, sids=sids or None)))
        return 0
    for line in tty.table(("会话号", "问题号", "谁在问", "问了多久", "问题", "选项"),
                          [(s, q.qid, q.role, _ago(q.ts), q.text[:60],
                            "、".join(_option_text(o) for o in q.options) or "—")
                           for s, q in rows]):
        print(line)
    print(tty.bullet(f"用 `agentflow --root {root} answer <问题号> \"<回答>\"`"
                     f"（选选项用 `--select`，"
                     f"写正文用 `--custom`）回答；共 {len(rows)} 条"))
    print(tty.bullet(_latest_run_stop(root, sids=sids)))
    return 0


def cmd_answer(args) -> int:
    """代用户回答一个问题（写一条 `user_answer`）。

    「没查成」分三种，处置方向不同，所以分开报（折成一句"失败了"会让人不知道该改哪一个）：
    - 没有这个号：列出当前待答的号（它可能在别的会话里 ⇒ 用 `--sid` 指名）；
    - 已经有回答：谁、什么时候、答了什么（不许覆盖 —— 回答是 append-only 的审计面）；
    - 写失败：原样报出失败原因。
    回答内容三档来源（等价于 DSH 的回答形状）：`--select <label>`（可重复，可 0/n 个）、
    `--custom <正文>`、以及 `--text` 位置参数（等价于 `--custom`，老调用方照旧）。
    退出码：0 = 写成了；2 = 没查成（上面三种，或没给回答内容）。
    """
    from . import userio as U

    root = Path(args.root or DEFAULT_ROOT).resolve()
    sid = getattr(args, "sid", None)
    pend = {q.qid: q for q in U.pending_questions(root, sid=sid)}
    if args.qid not in pend:
        answered = [r for r in U.read_replies(root, sid=sid) if r["qid"] == args.qid]
        if answered:
            last = answered[-1]
            print(f"[answer] 没查成：{args.qid} 已经有回答了 —— {last['by']} 在 "
                  f"{last['ts']} 答的是「{str(last['answer'])[:80]}」⇒ 不许覆盖"
                  "（要改主意就让它再问一次：回答是 append-only 的审计面，"
                  "而续跑读的是最新那一条）", file=sys.stderr)
            return 2
        print(f"[answer] 没查成：没有 {args.qid} 这个问题"
              f"（当前待答：{sorted(pend) or '现在是空的'}）。"
              f"若它落在别的会话里，用 `agentflow --root {root} inbox` 看会话号，"
              "再用 `--sid` 指名",
              file=sys.stderr)
        return 2
    selected = [str(x) for x in (getattr(args, "select", None) or [])]
    custom = str(getattr(args, "custom", None) or "")
    legacy = getattr(args, "text", None)
    if not custom and legacy:
        custom = str(legacy)
    if not selected and not custom:
        print("[answer] 没查成：没给回答内容 —— 用 `--select <选项>`（可重复）、"
              "`--custom <正文>`，或位置参数 <正文>", file=sys.stderr)
        return 2
    problem = U.answer_question(root, qid=args.qid, selected=selected, custom=custom, sid=sid)
    if problem:
        print(f"[answer] 没写成：{problem}", file=sys.stderr)
        return 2
    question = pend[args.qid]
    print(tty.bullet(f"已回答 {args.qid}：{(custom or '、'.join(selected))[:80]}"))
    unknown = [x for x in selected if x not in question.option_labels]
    if unknown:
        # 不是错误（回答可以是自由的），但要说出来：label 与选项对不上时，
        # 模型下一趟读到的就是一句它认不出的选项 —— "照写"与"写得对"是两件事。
        print(tty.paint(f"  注意：{unknown} 不在这个问题的选项里"
                        f"（选项：{'、'.join(question.option_labels) or '（没有选项）'}）—— "
                        "已照写，但模型可能读不懂这个 label", "yellow"))
    print(tty.bullet(f"下一步：`agentflow --root {root} run-agent "
                     f"--role {question.role} "
                     f"--task \"<原任务原文>\" --resume{_sid_suffix(sid)}`"
                     "（它走的是自主多轮就再加 `--rounds N`）"))
    return 0


def cmd_doctor(args) -> int:
    """体检：这台机器现在能做哪些事（「不发起任何模型调用」，不花钱）。

    为什么要有它（2026-10-03 的现场）：形式化那一条腿能不能跑，取决于两件外部事实 ——
    有没有检查器、它是不是被找得到 —— 而这两件事此前「只能通过跑一趟真机」才知道，
    并且查不出来的形态是"报告里只剩一句没核到"（用户的原话：这是坏的）。
    这一条命令把那些事实变成跑之前就能读到的三态读数。

    退出码三态：`0` 都齐（能跑，且形式化也能做）；`1` 查过了、有缺（例如没有模型 key、
    或者没找到证明检查器 —— 缺什么就少做什么，不是"跑不成"）；`2` 没查成
    （探测本身不成立：`checked=False`，例如显式配置指了一个不存在的路径）。
    """
    from . import toolchain as TC

    rep = TC.toolchain_report()
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    else:
        prov = rep["provers"]
        print(tty.paint("这台机器的体检", "bold"))
        print(tty.bullet(("模型 key：已配置" if rep["model"]["key_present"]
                          else "模型 key：**没配**（设 AGENTFLOW_MODEL_API_KEY，或写进 "
                               "agentflow/settings.json 的 model.api_key）")
                         + f"；base={rep['model']['base_url']}；model={rep['model']['model']}"))
        if prov["available"]:
            for row in prov["available"]:
                print(tty.bullet(f"证明检查器：{row['name']}（{row['source']}）"
                                 f" ⇒ {row['path']}；{row['version'] or '（版本读不到）'}"))
        else:
            print(tty.bullet(f"证明检查器：一个都没找到。找过 —— {'；'.join(prov['looked_in'])}"))
            print(tty.bullet("缺了它，形式化那一条腿只能如实报「没核到」；"
                             "要真做，就把它指出来："
                             "`AGENTFLOW_LEAN_BIN=<lean.exe 或它所在的目录>`"))
        if prov["probe_errors"]:
            print(tty.paint("探测没做成：" + "；".join(prov["probe_errors"]), "yellow"))
        ml = rep["mathlib"]
        print(tty.bullet("Mathlib：" + (f"{ml.get('root')}"
                                       f"（{'与钉住的一致' if ml.get('pinned_match') else '与钉住的不一致'}）"
                                       f" ⇒ import Mathlib {ml.get('import_mathlib')}"
                                       if ml.get("root") else str(ml.get("reason")))))
        if ml.get("root"):
            # D70（`draft/83` §7）：文件面读数不算数 —— 真编译过一次才算。
            # 真机读数（2026-10-08）：依赖包的 junction 在环境搬迁后悬空，
            # umbrella 在、而 `import Mathlib` 报 `unknown package 'Std'`，
            # 上面那一行照样写"可用"。
            print(tty.bullet("Mathlib 实测（真编译一次 `import Mathlib`）："
                             + str(ml.get("import_mathlib_measured"))))
        print(tty.bullet("结论：" + ("这一趟能做形式化核验（proof 级证据可达）"
                                     if rep["can_do_formal"] else
                                     "这一趟做不了形式化核验（会如实报没核到）")))
    if not rep["provers"]["checked"]:
        return 2
    return 0 if (rep["model"]["key_present"] and rep["can_do_formal"]) else 1


def cmd_web(args) -> int:
    """起用户端网页（本地小服务）。退出码 0 = 正常停止（Ctrl-C），2 = 没查成。

    它只是把 CLI 的参数翻成 `agentflow.webui.run()` 的 argv —— 实现在那一个模块里，这里不重写第二份
    （`R003` 防的正是"同一个公开名两处各有一份实现"）。`cli.main` 是命令总入口，`webui.run` 是这一个
    子命令的实现；两者的名字因此不同。
    两个开关按裁定 T1 加（`--allow-writes` 题 C2、`--no-settings-write` 题 E1）。W3/W4 之后它们真的
    改变行为，两条都在 `writes.authorize()` 的矩阵里：`--allow-writes` 是第 3 层（不开 ⇒ `/api/` 下那六条写端点
    403），`--no-settings-write` 是第 4 层（只关 `POST /api/settings`）。`getattr` 的默认值是为了让
    直接构造 `Namespace` 的老调用方（
    `tests/test_webui.py::test_the_cli_web_subcommand_forwards_to_the_module_entry`）照旧能跑：
    缺这两个字段就当"没给"。
    """
    from . import webui

    root = Path(args.root or DEFAULT_ROOT).resolve()
    argv = ["--root", str(root), "--host", str(args.host), "--port", str(int(args.port))]
    if args.open:
        argv.append("--open")
    if args.json:
        argv.append("--json")
    if args.token:
        argv += ["--token", str(args.token)]
    if getattr(args, "allow_writes", False):
        argv.append("--allow-writes")
    if getattr(args, "no_settings_write", False):
        argv.append("--no-settings-write")
    return webui.run(argv)


def cmd_budget(args) -> int:
    """这一趟的总预算：看、设、追加（业主 2026-10-12 的预算轴）。退出码：0 做成了 / 2 没查成。

    三种用法（`budget` 模块是唯一实现，这里只做台面）：
    - `agentflow budget` / `--status`：读一格读数 —— 总额度、已花、剩余、追加历史、三态。「已花」不
      来自寄存器：唯一权威账是 `usage_ledger`（`tokenmeter.spent()`）。
    - `agentflow budget --set 5`：设一个总额度（覆盖式；第一次设预算用这个）。
    - `agentflow budget --add 2 --note "让它跑完"`：追加（运行期生效：下一次花钱之前的那个闸门就会
      现读到新上限 —— 不需要重启、不需要重跑）。
    为什么要有这一条命令：改前"跑到一半加钱"在结构上没有入口（`Policy` 是 frozen、`LlmSeam.usd_budget`
    与 `TokenMeter.budget_usd` 只在构造期注入），唯一的办法是重跑一次。
    """
    from . import budget as B
    from .tokenmeter import TokenMeter

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    try:
        meter = TokenMeter(st)
        spent = meter.spent().get("usd")
    except Exception:  # noqa: BLE001 —— 账本读不出来时"已花"记 unknown（不许折成 0）
        spent = None
    wrote = False
    if getattr(args, "set_usd", None) is not None:
        got = B.write_initial(root, float(args.set_usd), by=str(getattr(args, "by", "user") or "user"),
                              note=str(getattr(args, "note", "") or ""))
        print(f"[budget] 设总额度：{json.dumps(got, ensure_ascii=False, default=str)}")
        wrote = True
        if not got.get("ok"):
            return 2
    if getattr(args, "add_usd", None) is not None:
        got = B.add_usd(root, float(args.add_usd), by=str(getattr(args, "by", "user") or "user"),
                        note=str(getattr(args, "note", "") or ""))
        print(f"[budget] 追加：{json.dumps(got, ensure_ascii=False, default=str)}")
        wrote = True
        if not got.get("ok"):
            return 2
    snap = B.reading(root, spent_usd=spent, fallback=getattr(args, "fallback_usd", None))
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
    else:
        total = "不限量" if snap["total_usd"] is None else f"${snap['total_usd']:.6f}"
        used = "没查成" if snap["spent_usd"] is None else f"${snap['spent_usd']:.6f}"
        left = "—" if snap["remaining_usd"] is None else f"${snap['remaining_usd']:.6f}"
        print(tty.paint(f"[budget] {root}", "bold"))
        print(f"  总预算：{total}（来源 {snap['source']}）；已花：{used}；剩余：{left}"
              + ("（**已超**）" if snap["exceeded"] else ""))
        print(f"  追加历史 {len(snap['added'])} 条；寄存器：{snap['path']}"
              + (f"；问题：{snap['problem']}" if snap["problem"] else ""))
        if not wrote and snap["total_usd"] is None:
            # 三态纪律：没设过预算 ≠ 预算充足。把"下一步怎么做"写出来，别让人猜。
            print("  （这一趟没有设过预算 ⇒ 不限量。要设：`agentflow budget --set 5`；"
                  "要追加：`agentflow budget --add 2`）")
    return 0


def cmd_stop(args) -> int:
    """停一趟正在跑的 `run-agent`（`draft/37` §128）。退出码：0 做成了 / 2 没查成。

    两种停法（用户口径："优雅停止还要提醒那些 Agent 把发起的进程一起停掉，还要写个强制停止是直接杀掉"）：
    - 「缺省（优雅）」：写停机开关 `<工作区>/.agentflow-stop`。正在跑的那一趟在「步与步之间」看到它 ⇒
      收工（写运行记录与 `final`）；E 正在跑的实验子进程也在 0.2 s 内被终止（每步都看这个开关；
      多轮自主跑则在「每轮之间」看到它）。
    - 「`--force`（强制）」：先落开关（`force=true`，留痕"谁在什么时候强杀"），再按进程登记
      `<工作区>/runs/*.pid` 把那些进程「连子孙一起」 `taskkill /T /F` —— 直接杀掉。为什么必须"连子
      孙"：Windows 上杀父进程不带子进程（实测：包装进程被杀之后 python 子进程又跑了 12 分钟）。
    `--status` 只读当前状态（开关在不在、登记里哪些进程还活着、开关文件坏了没有、最近几次叫停）。`draft/37` §140 之后：开关是一次性信号 —— 停一趟、记一笔（`runs/stop-history.jsonl`）、撤走，所以"停完接着 `--resume`"这条路不再需要人工 `--clear`。
    退出码（`draft/39` §3.11 D25，用户裁定，2026-10-05）：
    | 码 | 含义 | 驱动器该怎么办 |
    |---|---|---|
    | `0` | 这次调用新写了开关（或 `--clear` 真的撤掉了一把） | 可以清（它是我写的） |
    | `3` | 盘上已有一把别人写的开关（本次只可能追加 `force` 升级） | 不许清，只能追加升级 |
    | `4` | 没有开关（`--clear` 时无可撤；无需清） | 什么都不用做 |
    | `2` | 没做成（强制停时一个进程都没杀掉 —— 受限环境的常见形态） | 读原话，别读成"停住了" |
    为什么"别人的开关一律不许清"要写成一个码：驱动器此前只看"命令成没成功"，于是它会把用户刚落的开关顺手撤掉（"停完就清"），而那正是"用户叫停"这件事在系统里消失的形态。
    """
    from . import stopctl

    root = Path(args.root or DEFAULT_ROOT).resolve()
    if getattr(args, "status", False):
        state = stopctl.read_stop(root)
        live = stopctl.live_pids(root)
        print(f"[stop] 工作区：{root}")
        print(f"[stop] 开关：{stopctl.stop_path(root)}"
              f"（{'在' if state is not None else '不在'}）")
        if state is not None:
            print(f"[stop] 开关内容：{json.dumps(state, ensure_ascii=False, default=str)}")
        history = stopctl.stop_history(root, limit=5)
        if history:
            print(f"[stop] 已被消费的叫停（最近 {len(history)} 次）：")
            for h in history:
                print(f"[stop]   {h.get('at', '?')} by={h.get('by', '?')} "
                      f"reason={h.get('reason', '?')}"
                      f"{'，force' if h.get('force') else ''}"
                      f" ⇒ 由 sid={h.get('consumed_by_sid') or '（无 sid）'} 在 "
                      f"{h.get('consumed_at', '?')} 收工时用掉")
        print(f"[stop] 登记着的活进程：{len(live)} 个"
              + ("：" + "、".join(f"{p['role']}#{p['pid']}" for p in live) if live else ""))
        # D07（`draft/39` §2）：显式回答"在跑的循环：有/没有" —— 只报 pid 登记时，
        # 登记为空会让读者把"一把没人消费的开关"读成"没事"。
        loops = stopctl.running_loops(root)
        detail = "、".join(f"{r['role']}（sid={r['sid']}，起于 {r['since']}）"
                           for r in loops["running"])
        print(f"[stop] 在跑的循环：{loops['answer']}"
              + (f"：{detail}" if detail else "")
              + (f"；另有 {len(loops['live'])} 个登记着的活进程"
                 if loops["live"] and not detail else ""))
        if loops["unreadable_sessions"]:
            print(f"[stop] 有 {len(loops['unreadable_sessions'])} 段会话读不出来"
                  f"（{loops['unreadable_sessions']}）⇒ 这一路没查成，别读成「没在跑」",
                  file=sys.stderr)
        return 0

    force = bool(getattr(args, "force", False))
    if bool(getattr(args, "clear", False)):
        # 撤开关：§140 之后"接着跑"不再需要它（开关被消费时就撤走了）；这一条留给
        # "刚写完发现写错了"那种"在生效之前撤销"的用法。
        gone = stopctl.clear_stop(root)
        print(f"[stop] 停机开关{'已撤' if gone else '本来就不在'}：{stopctl.stop_path(root)}")
        return 0 if gone else 4
    state, outcome = stopctl.request_stop_detail(
        root, reason=str(getattr(args, "reason", "") or "user"),
        by="user", force=force, sid=getattr(args, "sid", None))
    mine = outcome == "created"
    print(f"[stop] 停机开关{'已落' if mine else '已在盘上'}：{state['path']}"
          f"（reason={state['reason']}{'，force' if state['force'] else ''}）")
    if not mine:
        print(f"[stop] 这把开关不是你写的（{state.get('by', '?')} 在 {state.get('at', '?')} 落的）"
              f"⇒ 退出码 3：只追加升级、**不许清**", file=sys.stderr)
    if not force:
        if mine:
            print("[stop] 优雅停止：正在跑的那一趟会在下一步之前收工"
                  "（E 的实验子进程也会被终止）；多轮自主跑在每轮之间收工")
        return 0 if mine else 3
    killed = stopctl.kill_registered(root)
    print(f"[stop] 强制停止：按登记杀了 {killed['killed']}/{len(killed['requested'])} 个进程"
          + (f"（{killed['requested']}）" if killed["requested"] else "（登记里没有活进程）"))
    for res in killed["results"]:
        print(f"  - pid {res['pid']}：killed={res['killed']} via={res['via']} {res['detail'][:120]}")
    if killed.get("kept"):
        # `draft/37` §140：杀不成就把登记留着 —— 否则 `--status` 会报"0 个活进程"（假绿）。
        print(f"[stop] 这些进程没杀掉，登记保留（`--status` 会照实报它们在册）：{killed['kept']}")
    if killed["requested"] and not killed["killed"]:
        print("[stop] 注意：一个都没杀掉（受限环境常见：taskkill 被拒、os.kill 也被拒）——"
              "读数里给了原话，不要把它读成「停住了」。停机开关仍然有效："
              "那一趟会在下一个步检查点收工（`stop_reason=force_stop`）", file=sys.stderr)
        return 2
    return 0 if mine else 3


def cmd_status_report(args) -> int:
    """项目状态报告（`draft/39` §4）：只读台账与手稿，零模型调用，不打断任何循环。

    退出码：`0` 报告已落盘 / `2` 没查成（工作区不在盘上、或收集时读不到）。

    为什么它不是"问 M 一句"：`ask_user` 那条路是反向的（让 M 停下来等人），
    而用户中途想知道情况时，正确的形态是旁路观测 —— 读盘 → 出报告，谁都不停。
    """
    from . import statusreport as SR
    from .store import Store

    root = Path(getattr(args, "root", None) or DEFAULT_ROOT).resolve()
    if not root.is_dir():
        print(f"[unknown] 工作区不在盘上：{root} —— 没查成，不是「没有状态」", file=sys.stderr)
        return 2
    try:
        store = Store(root)
    except Exception as exc:  # noqa: BLE001 —— 打不开工作区 ⇒ 没查成
        print(f"[unknown] 打开工作区失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    report, md_path, json_path = SR.write_status_report(
        store, root, out_dir=getattr(args, "out", None),
        since=str(getattr(args, "since", "") or ""))
    print(f"[status-report] 报告已落盘：{md_path}")
    print(f"[status-report] 机器可读那一份：{json_path}")
    print("[status-report] 产出：" + "、".join(
        f"{k} {v['count']}" for k, v in report["tables"].items() if v["count"]))
    print(f"[status-report] 交接账本：{report['manuscripts']['rows']} 行"
          f"（模型填 {report['manuscripts']['model_authored']} / 派生 "
          f"{report['manuscripts']['derived']}）")
    infl = report["in_flight"]
    print(f"[status-report] 在飞任务：{infl['running_tasks']}；在跑的循环："
          f"{'有' if infl['running_loops'] else '没有'}；停机开关："
          f"{'在' if infl['stop_switch'] else '不在'}")
    print("[status-report] 下一步（从读数派生）：")
    for line in report["next_steps"]:
        print(f"  - {line}")
    return 0


def cmd_closing(args) -> int:
    """跑收工门（`draft/37` §16 P3）。退出码：0 可交付 / 1 被拦住 / 2 没查成。

    三态（与 `noai_gate` 同一套口径）：`unknown` 那一档绝不是通过 —— "没查成"（没给项目根、报告还没写）与"查过了有问题"必须给不同的退出码，否则 CI 会把两者读成同一件事。
    ## 收工门之后再接一段内容级验收（`draft/37` §17.3，题 6 选 A = 接线）：这一层此前在生产面上一次
    都没被调用过；现在它的唯一生产调用者是这里（只读、零模型调用、不落任何台账）。为什么挑这个出
    口：收工门问的正是"这份交付能不能交"，而 `reviewaccept` 问的是同一份交付的同一个问题（只是判据
    在内容层）；两者的入参（`project_dir` / `report_path` / `session_root` / `sid`）本来就是同一批，
    而那批入参在这里已经收齐了 ⇒ 不新开面、不新开子命令（子命令数被 `test_user_quickstart` /
    `test_doc_code_consistency` 逐字钉着）。
    两件事刻意分开、读数分栏打：退出码仍只由收工门定（`tri_state_exit_code`）—— 把内容级验收并进
    退出码等于偷偷改门的强度（那是裁定题）；`unknown` 不折平：六条各自打"通过/不通过/没查成"，
    辅助读数照原样打出，并逐字说明"它们不构成通过"。
    `--acceptance-sid` 缺省传 `closing.NO_SESSION`（"这次调用没有会话身份"），于是「三态分支」那一格
    是"没查成" —— 不折进 `sid=None` 的"读缺省会话"，那正是 §58/§63 记过两次的假绿形态。
    ## 退出码由 M 的判据定（业主 2026-10-09）：「是否收工不要用机械判据，由 M 制定的目标是否达成
    为准」⇒ 退出码（0 可交付 / 1 被拦住 / 2 没查成）跟着 M 的判据走：运行内 M 交判据那一次已经把它
    落到 `out/review/m-verdicts.jsonl`，这里缺省读那一份；`--goal-met` / `--goal-not-met` 是"人/CI
    代述 M 的说法"的显式入口。没有判据 ⇒ 2（"没人判过"既不是"可以交"也不是"被拦住"）。八格照旧
    逐格现算并打出来，但它们是读数。
    """
    from . import closing as CL
    from .store import Store

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = Store(root)
    project = args.project_dir or ""
    report = args.report or (str(Path(project) / "out" / "review" / "REPORT.md")
                             if project else "")
    rep = CL.check_closing(st, project_dir=project, report_path=report,
                           goal=str(getattr(args, "goal", "") or ""),
                           goal_met=getattr(args, "goal_met", None),
                           basis=str(getattr(args, "basis", "") or ""))
    for name in CL.DEFAULT_CHECKS:
        state = rep.status.get(name, "?")
        mark = {"pass": "通过", "fail": "拦住", "unknown": "没查成"}.get(state, state)
        print(tty.bullet(f"{name}：{mark}"))
    for f in rep.findings:
        print(f"  [{f.level}] {f.code}：{f.detail}")
    print(rep.summary())
    if getattr(args, "no_review_acceptance", False):
        # 关掉是显式的：它让"零调用的那段历史"仍可复现，也方便对拍接线前后的读数。
        print("[review-acceptance] 这一次没跑（`--no-review-acceptance`）—— "
              "这一格是「没查成」，不是「内容级验收通过了」")
        return CL.tri_state_exit_code(rep)
    _print_review_acceptance(st, project=project, report=report,
                             cap_usd=getattr(args, "cap_usd", None),
                             sid=(getattr(args, "acceptance_sid", None)
                                  or CL.NO_SESSION))
    return CL.tri_state_exit_code(rep)


def _print_review_acceptance(store, *, project: str, report: str,
                             cap_usd: float | None, sid: str) -> None:
    """把内容级验收（`draft/37` §17.3 的六条）打到人能读的地方（只读）。

    `reviewaccept` 读的是同一批入参：`project_dir` / `report_path` / `session_root`（不给就用
    `store.root`，与 `check_closing` 同一条口径）/ `sid`。
    为什么六条要逐条打而不是只打一个 `passed`：这一层的三态纪律就写在判据本身里（"没查成"与"查过
    了没问题"必须分得开，`unknown` 会挡住 `passed`）；只打一个布尔值，等于把这条纪律在出口上又折平。
    为什么辅助读数也要逐条打（哪怕一个都不参与判定）：§17.3 逐字禁止拿它们当通过 —— 而"禁止"要能
    被读的人看见才有意义；它们与判据分栏给出，末尾再写一句它们不构成通过。
    这一段只读盘：`check_review` 走 `store.rows` / `sessions.read_session` / `userio` 的读口 /
    `papercompile.receipt_matches_tex`，一处都不写。
    """
    from . import reviewaccept as RX

    acc = RX.check_review(store, project_dir=project, report_path=report,
                          cost_cap_usd=cap_usd, sid=sid)
    readings = acc.to_dict()
    mark = {"pass": "通过", "fail": "不通过", "unknown": "没查成"}
    print("")
    print(tty.paint("[review-acceptance] 内容级验收（§17.3；只读，零模型调用）", "bold"))
    for key, name in RX.CRITERIA:
        state = readings["criteria"].get(key, "?")
        print(tty.bullet(f"{name}：{mark.get(state, state)}"))
        note = readings["details"].get(key) or ""
        if note:
            print(f"    {note}")
    print(f"  passed（只看上面这几条）＝{readings['passed']}")
    if readings["failed"]:
        print(f"  没通过的：{'、'.join(readings['failed'])}")
    print("  ── 辅助读数（§17.3 逐字禁止拿来当通过：它们都很容易变，证明不了内容）")
    for key, label in RX.AUXILIARY_SIGNALS:
        print(f"    {label}＝{readings['auxiliary'].get(key)}")
    for key, value in readings["readings"].items():
        print(f"    （判据读数）{key}＝{value}")
    print(f"  {acc.summary()}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentflow",
                                description="面向数学研究的多智能体协同框架（正式版；A–H + 主控 M）")
    p.add_argument("--root", default=None,
                   help="工作区根（不给就用 DEFAULT_ROOT = 本仓库的 `agentflow/`）")
    p.add_argument("--config", default=None, help="配置文件路径（默认 <root>/config.yaml）")
    # 呈现层的两个开关。为什么做成顶层开关而不是每条命令各带一个：
    # "这次输出别带颜色"是终端的事，不是某个子命令的事；散在各处就会出现
    # "project 支持而 run 不支持"这种随命令而变的怪现象。
    p.add_argument("--no-color", action="store_true",
                   help="关掉颜色（管道里本来就会自动关；这个开关是给『想强制关』的人）")
    p.add_argument("--plain", action="store_true",
                   help="纯 ASCII 输出（制表符/勾号都不画；老终端或想粘到邮件里时用）")
    p.add_argument("--compact", action="store_true", help="少画框、少空行")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("init", help="初始化数据目录与空表")
    sp.add_argument("--force", action="store_true", help="覆盖已有数据（危险）")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("submit", help="提交搜索请求")
    sp.add_argument("--topic", required=False)
    sp.add_argument("--mode", default="topical", choices=list(S.SEARCH_MODES))
    sp.add_argument("--content", default="")
    sp.add_argument("--by", default="cli")
    sp.add_argument("--file", default=None, help="从 JSON 文件批量提交（{rows:[...]} 或 [...]）")
    sp.set_defaults(func=cmd_submit)

    sp = sub.add_parser("run-a", help="运行 A 智能体")
    sp.add_argument("--once", action="store_true", help="只处理一条请求")
    sp.add_argument("--max", type=int, default=1)
    sp.add_argument("--provider", default=None, help="逗号分隔，如 fixture 或 openalex,crossref")
    sp.set_defaults(func=cmd_run_a)

    sp = sub.add_parser("run-b", help="运行 B 智能体")
    sp.add_argument("--once", action="store_true", help="只整理一篇文献")
    sp.add_argument("--max", type=int, default=1)
    sp.set_defaults(func=cmd_run_b)

    sp = sub.add_parser("status", help="查看各表统计")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("verify", help="校验全局不变量（error ⇒ 退出码 1）")
    sp.add_argument("--deep", action="store_true", help="重新打开文献复核引文（慢）")
    sp.add_argument("--strict", action="store_true", help="警告也算失败（error 一律失败）")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("rebuild", help="从 events.jsonl 重建快照")
    sp.add_argument("--no-backup", action="store_true")
    sp.set_defaults(func=cmd_rebuild)

    sp = sub.add_parser("repair", help="重算派生字段")
    sp.add_argument("--related", action="store_true", help="重算 related_concepts")
    sp.set_defaults(func=cmd_repair)

    sp = sub.add_parser("demo", help="离线端到端演示（不访问网络）")
    sp.add_argument("--keep", action="store_true", help="保留上次演示数据")
    sp.set_defaults(func=cmd_demo)

    # ---- 工具层与新智能体（DESIGN-TOOLS.md）
    sp = sub.add_parser("tools", help="列出工具层按角色的装配情况")
    # 角色清单必须来自 `S.ROLES`，不许在这里写死（与 `cmd_tools` 函数体同一条纪律）。
    # 这里原先写死 `choices=["A", "B", "C", "D"]`：函数体修了、参数层没修，于是
    # E/F/G/H 落地之后 `tools --role E` 被 argparse 以退出码 2 拒掉
    # （实测 `invalid choice: 'E'`）——"角色即权限面"的可打印事实只覆盖 A–D。
    # 用 `S.ROLES`（schema 是角色名单的唯一来源，`tools.ROLES` 就是它）而不是
    # 在这里 import `tools`：这样 `cli --help` / 其它子命令不必为了一张词表去装配工具层。
    sp.add_argument("--role", default=None, choices=list(S.ROLES), help="只看某个角色的工具")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_tools)

    sp = sub.add_parser("analyze", help="C：关系分析（四类需求）")
    sp.add_argument("--kind", default="hottest", choices=list(S.REPORT_KINDS))
    sp.add_argument("--a", default=None, help="kind=paths：起点概念（代号或名字）")
    sp.add_argument("--b", default=None, help="kind=paths：终点概念（代号或名字）")
    sp.add_argument("--top-n", type=int, default=5, help="hottest/cold 取前几名；gaps 的 limit")
    sp.add_argument("--max-paths", type=int, default=5)
    sp.add_argument("--max-len", type=int, default=4, help="路径最大跳数")
    sp.add_argument("--request", default="", help="原始需求原文（登记在报告里便于审计）")
    sp.add_argument("--text", default=None, help="直接用自然语言需求，走 C.handle() 分派")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("pipeline", help="编排：C→D→(A→B→D 复查) 循环")
    sp.add_argument("--request", required=True, help="自然语言分析需求")
    sp.add_argument("--gap-rounds", type=int, default=2)
    sp.add_argument("--no-search", action="store_true", help="不跑 A/B（只做静态分析）")
    sp.set_defaults(func=cmd_pipeline)

    # 端到端一条命令。退出码即 `run_topic` 的三态：0 / 1 / 2。
    sp = sub.add_parser("run", help="端到端跑一个主题（检索→作答→逐字回验→记账→熔断→六件产物）")
    sp.add_argument("--topic", required=True, help="研究主题")
    sp.add_argument("--budget-usd", type=float, default=1.0,
                    help="美元上限（每次调用之前检查，达线即停 —— 单跑可能超出至多一次调用，"
                         "超出量写在 cost.json 的 budget_overshoot_usd 里）")
    sp.add_argument("--out", default=None, help="产物目录（默认新建临时目录并打印路径）")
    sp.add_argument("--max-calls", type=_non_negative_int, default=3,
                    help="最多调用几次模型（库层拒绝负数；这里让它在用法错阶段就以退出码 2 结束）")
    sp.add_argument("--model", default=None, help="只覆盖模型名（key/base_url 一律来自环境变量）")
    # `choices` 让非法版本走 argparse 的用法错（退出码 2 = "没查成"），而不是穿到库层抛
    # ValueError + traceback ⇒ 退出码 1（那在本项目的三态里是"查过了、有问题"）。
    # 延迟 import：`agentflow.cli` 的顶层不许拉起 runflow（它依赖一长串模块）。
    from .runflow import PROMPT_VERSIONS as _PROMPT_VERSIONS

    sp.add_argument("--prompt-version", default="v1", choices=list(_PROMPT_VERSIONS),
                    help="prompt 模板版本（写进清单）")
    sp.add_argument("--fulltext", action="store_true",
                    help="获取开放全文（逐条下载；回验因此可能到达全文级）")
    sp.add_argument("--lean", action="store_true",
                    help="对答复里的 Lean 代码块真跑证明检查器（需要环境里已装 Lean；"
                         "只有 verified 才算 proof 级证据）")
    # `--now` 只为自动化测试注入固定时间戳：产物里的时间戳可复现，断言才稳得住。
    sp.add_argument("--now", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--text-store-dir", default=None,
                    help="逐页正文的内容寻址落点（不给就内联在产物里；给了同一本书只存一份，"
                         "依据 draft/30 §T0-7）")
    sp.set_defaults(func=cmd_run)

    # 项目式用法：`projects/<名字>` 一个项目一个文件夹，冷/热启动按文件夹在不在。
    sp = sub.add_parser(
        "project",
        help="项目工作区：list / plan / run（一个项目一个文件夹，冷启动还是热启动看文件夹在不在）",
    )
    sp.add_argument("action", choices=["list", "plan", "run", "create"],
                    help="list 列出现有项目；plan 只说明这次会怎么跑（不写字节）；"
                         "run 真跑；create 正常地建一个审阅型项目（--paper 给那篇外部论文）")
    sp.add_argument("--name", default=None,
                    help="项目名（缺省=自动取下一个 projectN；run 时也接受已有名字=热启动）")
    sp.add_argument("--projects-dir", default=None,
                    help="projects 落点（缺省：由本包位置推出的工作区根下的 projects/；"
                         "也可用环境变量 AGENTFLOW_PROJECTS_DIR 或设置文件的 "
                         "workspace.projects_dir 覆盖）")
    sp.add_argument("--start", default="auto", choices=["auto", "cold", "warm"],
                    help="auto=看文件夹在不在（缺省）；cold=必须不存在；warm=必须已存在且初始化过")
    sp.add_argument("--books", default=None,
                    help=r"本地书架目录（例如 D:\books）：里面的 PDF 会被登记进项目库")
    sp.add_argument("--books-limit", type=_non_negative_int, default=None,
                    help="本次最多登记几本（超出的一本都不登记，清单里写明理由）")
    sp.add_argument("--paper", default=None,
                    help="审阅型项目要铺进去的那篇外部论文（.pdf；同目录有同名 .tex 就一并铺成"
                         "只读基线与可改正文）—— 只对 `project create` 有意义")
    sp.add_argument("--topic", default=None, help="研究主题（给了才会调模型；缺省只做登记）")
    sp.add_argument("--budget-usd", type=float, default=0.5,
                    help="这一次运行的美元额度（每次调用之前检查）")
    sp.add_argument("--max-calls", type=_non_negative_int, default=2, help="最多调用几次模型")
    sp.add_argument("--retrieval-limit", type=_non_negative_int, default=7,
                    help="最多取几条本地来源进材料段（一本书算一条）")
    sp.add_argument("--no-fulltext", action="store_true",
                    help="不取全文（引文只会在 1200 字符的摘要窗口里比对，回验强度更低）")
    # `--lean` 与 `run` 那个动词同一口径：默认关；关着时"没有任何形式化验证证据"
    # 照样写进未接线清单。没有这个开关时，本地书架这条主路径上永远拿不到 proof 级证据。
    sp.add_argument("--lean", action="store_true",
                    help="对答复里的 Lean 代码块真跑证明检查器（需要环境里已装 Lean；"
                         "只有 verified 才算 proof 级证据）")
    sp.add_argument("--extract", action="store_true",
                    help="先让模型把库里还没抽过的书读一遍（概念/关系；每条关系的引文"
                         "逐字回验，找不到的当场剔除并计数）")
    sp.add_argument("--extract-rounds", type=_non_negative_int, default=1,
                    help="模型抽取最多跑几轮 —— 一轮只处理至多一本书（agent_b.run_once 的契约），"
                         "所以 7 本书要 --extract-rounds 7")
    sp.add_argument("--now", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--text-store-dir", default=None,
                    help="覆盖逐页正文的落点（不给就用 <项目根>/.fulltext，见 T0-6 的默认）")
    sp.set_defaults(func=cmd_project)

    # 证据面工具：核引用、盘 store、把历史内联产物迁成引用形态（依据 draft/30 §T0-7）。
    sp = sub.add_parser(
        "evidence",
        help="证据面：verify 核一个运行的全文引用 / store 盘一个项目的正文库 / migrate 迁移历史产物",
    )
    sp.add_argument("action", choices=["verify", "store", "migrate"],
                    help="verify <run_dir>；store <project_dir>；migrate <project_dir> [--apply]")
    sp.add_argument("target", help="verify 给运行目录；store/migrate 给项目目录")
    sp.add_argument("--apply", action="store_true",
                    help="migrate 真的改写产物（缺省只 dry-run：这一步改的是历史证据本体）")
    sp.set_defaults(func=cmd_evidence)

    # 产物归属登记（依据 draft/28 §153 的 A3/A4 与 R-52）：谁在哪个路径产出了什么。
    sp = sub.add_parser(
        "artifacts",
        help="产物归属：record 登记 / list 列出 / verify 核对哈希 / owners 问这个路径归谁 / "
             "unowned 找出**没有**归属的路径 / report 渲染成表",
    )
    sp.add_argument("action",
                    choices=["record", "list", "verify", "owners", "unowned", "report"],
                    help="record <路径>；owners <路径>；unowned <目录或文件…>；"
                         "report 把台账渲染成 markdown（--out 给文件，否则打到 stdout）")
    sp.add_argument("target", nargs="*", default=[],
                    help="record/owners 给一个路径；unowned 给一个或多个路径（目录会被展开成文件）")
    sp.add_argument("--producer", default="", help="record：谁产的（角色名 / 工具名 / M）")
    sp.add_argument("--kind", default="file", help="record：产物类别（script / report / paper / …）")
    sp.add_argument("--task-id", default="", help="record：这次产出属于哪一次召唤")
    sp.add_argument("--exit-code", type=int, default=None,
                    help="record：产生它的那次执行的退出码（没跑过就别给，不许拿 0 冒充）")
    sp.add_argument("--note", default="", help="record：人读的补充")
    sp.add_argument("--out", default=None, help="report：写到这个文件（缺省打到 stdout）")
    sp.set_defaults(func=cmd_artifacts)

    sp = sub.add_parser(
        "run-agent", help="真跑一次角色循环（模型驱动；退出码六档：0 正常完成 / 1 行为异常 / "
                          "2 研究启动失败 / 3 等待用户 / 4 正常且中途停止 / "
                          "5 正常且自行停止但没有 final）",
        description="真跑一次角色循环。退出码六档："
                    "0 = 正常完成（这一趟给了 final）；"
                    "1 = 行为异常（只留给「真出事」：没接线 / 模型没认 key / 没返回 / "
                    "连不上 / 输出吃光 / 坏 JSON 超限 / 坏参数超限 / 没 notify，以及任何"
                    "没登记的新 stop_reason —— 没登记一律归 1）；"
                    "2 = 研究启动失败（连跑都没开始：检查点读不到 / 任务指纹不符 / "
                    "上一趟已收工 / 会话记录里重建不出那一步）；"
                    "3 = 等待用户（问了人、还停在等回答 —— 既不是完成也不是失败，"
                    "人答完用 --resume 接着跑那一步之后）；"
                    "4 = 系统行为正常且中途停止（用户叫停 —— 强停与优雅停 —— 与预算耗尽"
                    "统一这一档，可 --resume）；"
                    "5 = 系统行为正常且自行停止，但没有 final（原地打转 / "
                    "escalated 交给召唤者）。")
    sp.add_argument("role", choices=list(S.ROLES) + [S.CONDUCTOR_ROLE],
                    help="顶层角色（M = 主控，其余 = A–H）")
    sp.add_argument("--task", required=True, help="这次要做的事（给角色的任务描述）")
    sp.add_argument("--drive", action="append", default=[],
                    help="把某个 (角色.动作) 交给模型驱动，可重复；不写则不改变确定性行为")
    sp.add_argument("--subagents", action="store_true",
                    help="把**所有已声明的角色动作**都交给模型驱动（=「各角色像 subagent」）；"
                         "注意它会替换掉确定性动作（例如 B 的按行整理），批量消化这类活建议"
                         "改用「确定性动作 + 同角色多实例并发」（`conductor.summon_many`）")
    sp.add_argument("--semantic-review", action="store_true",
                    help="给 H 接上语义判据（「结论是否强于引文」）；不写则那一格如实报「没查」")
    sp.add_argument("--attack-reasoning", action="store_true",
                    help="给 F 接上攻坚推理（`attack.step` 真的推一轮：归约/论证/实验请求/死路）；"
                         "不写则 F 的 step 只会落 `dead_end(缺工具)` 并如实说「未接线」"
                         "（与 `--semantic-review` 同一条纪律：默认确定性，环境里有 key 也不改行为）。"
                         "**它不连带打开 E 的缝**：只开这一条时，F 需要脚本的那一轮必然因 "
                         "E 没有缝（`no_seam`）而卡住 —— 要整条通就同时给 "
                         "`--experiment-reasoning`")
    sp.add_argument("--experiment-reasoning", action="store_true",
                    help="给 E 接上写脚本的推理（`author_script`：按子目标带来的判据写一份核验"
                         "脚本，例如一个能在 N<=8 上手算核对的玩具例子，然后照常真跑一次）；"
                         "不写则 E 只回 `no_seam`（没接线），"
                         "F 那一轮落 `dead_end(缺工具)` 并向召唤者上报 `missing_input`"
                         "（缺的是 E 的缝，不是脚本）。"
                         "**它不被 `--attack-reasoning` 连带打开**：两个开关各自可解释"
                         "（F 想这一步怎么打 / E 把判据写成能跑的脚本）—— 而只开 F 的话，"
                         "F 需要脚本时必然因 E 无缝而卡住（真机读数：`projects/mp4` 计划 "
                         "000003 的 r1/r2 全是 `no_change`，原因逐字是 `no_seam`）。"
                         "默认关（与 `--semantic-review` / `--attack-reasoning` 同一条纪律）")
    sp.add_argument("--provider", default=None,
                    help="A 的检索后端，逗号分隔（openalex/crossref/doaj/europepmc/fixture）；"
                         "缺省按配置 `agent_a.providers`，再缺省 openalex —— 与 `run-a` 同口径。"
                         "A 没有后端就不会进登记表：那时任何角色唤起 A 都会如实落 "
                         "`refused/not_wired`（没查成，不是「这个主题没有文献」）。"
                         "想离线验证这条链路就写 `--provider fixture`")
    #: 默认 30（`draft/37` §16 P0）：默认 6 的时候，一个被驱动的动作连"读完一段正文"都不够
    #: —— 真机实测 G 拿了 151 步、89 次在读，最后还是没能落盘一处改动，而框架默认只给 6 步。
    #: 它是报告阈值、不是闸（裁定 12-K）：超过它只会向上报一次账，不强制收工。
    sp.add_argument("--max-steps", type=_non_negative_int, default=30,
                    help="每满几步向父代理报一次步数账（不设步数闸：超了不强制收工）")
    #: 墙钟（`policy.wall_clock_sec`）默认 900 秒：真机里第 8 次派活就是被它挡下的（`deadline_exceeded`）。
    #: 放成可配而不是写死：长任务（审一篇论文）该给一小时量级，短任务仍可以压到几分钟。
    # 2026-10-18（业主口径，逐字）：「不传就是无限制，传多少时间就是多少」。
    # 所以 default 从 3600.0 改成 None（不设上限）。真机代价（`projects/t2y`）：
    # 我没传这个参数 ⇒ 用了缺省 3600 ⇒ 1 小时整切断，而那一刻 M 正要派 B 登记命题
    # （`t-000010 B refused：墙钟截止已过（wall_clock_sec=3600.0）`）⇒ `conjectures 3 / statements 0`。
    sp.add_argument("--wall-clock-sec", type=float, default=None,
                    help="这次运行的墙钟上限（秒）。**不给 = 不设上限**；给了多少就是多少"
                         "（到点后新召唤一律被拒，已在跑的走协作式取消；<=0 同样视为不设）")
    sp.add_argument("--rounds", type=_non_negative_int, default=1,
                    help="跑几轮（>1 走自主轮：按 --report-every 向公共频道汇报）")
    sp.add_argument("--report-every", type=_non_negative_int, default=1, help="每几轮汇报一次")
    sp.add_argument("--budget-usd", type=float, default=None, help="美元上限（在每次请求之前检查）")
    sp.add_argument("--sid", default=None, help="会话号（默认当天）")
    sp.add_argument("--resume", action="store_true",
                    help="从检查点续跑：`--rounds >1` 时只跑没做过的轮（任务指纹不一致会被拒）；"
                         "单趟时接着上一趟停下的那一步之后（上一趟停在等用户或步数用尽都能接）。"
                         "指纹不一致 ⇒ 退出码 2")
    sp.add_argument("--user-wait-sec", type=float, default=None,
                    help="问用户时等多久（秒）：缺省 = 一直等到有人答（等待期间不产生 token "
                         "开销，等的是磁盘上的回答事件）；`0` = 登记问题后立刻停下来等"
                         "（退出码 3）。用户裁定「问了就停」，所以不再有 30 秒那一档默认值")
    sp.add_argument("--no-ask", action="store_true",
                    help="无人值守档：问用户被确定性拒绝（不落问题、不停循环，按最保守的做法"
                         "继续并把这件事写进结论）。三态口径：没人在场是「没查成」，"
                         "不是「通过」，更不许降级成「问一下试试」")
    sp.add_argument("--stop-file", default=None,
                    help="停止开关（人可随时按停）：这个文件一出现就停 —— 单趟运行时在"
                         "**步与步之间**查（做完当前这一步再收工，留步检查点与运行记录）；"
                         "`--rounds > 1` 时在**每轮之间**查（当前这一轮跑完再停）")
    sp.add_argument("--json", action="store_true", help="把运行记录打成 JSON")
    sp.set_defaults(func=cmd_run_agent)

    sp = sub.add_parser("budget",
                        help="这一趟的总预算：看 / 设 / 追加（业主 2026-10-12：不限制步数只限预算，"
                             "运行消耗实时从总预算里扣除，扣完自动优雅停）")
    sp.add_argument("--status", action="store_true", help="只读：总额度 / 已花 / 剩余 / 追加历史")
    sp.add_argument("--set", dest="set_usd", type=float, default=None,
                    help="设一个总额度（覆盖式；第一次设预算用它）")
    sp.add_argument("--add", dest="add_usd", type=float, default=None,
                    help="追加一笔额度（运行期生效：下一个闸门就受新上限约束）")
    sp.add_argument("--by", default="user", help="谁加的（写进追加历史，默认 user）")
    sp.add_argument("--note", default="", help="一句话说明（写进追加历史）")
    sp.add_argument("--fallback-usd", type=float, default=None,
                    help="寄存器缺席时按这个数显示（不给就是不限量）")
    sp.add_argument("--json", action="store_true", help="打成 JSON（给网页/脚本读）")
    sp.set_defaults(func=cmd_budget)

    sp = sub.add_parser("stop",
                        help="停一趟正在跑的 run-agent（`draft/37` §128）：缺省优雅停，"
                             "`--force` 直接杀掉（连子进程）")
    sp.add_argument("--reason", default="user", help="停机理由码（默认 user）")
    sp.add_argument("--force", action="store_true",
                    help="强制停止：不等待收尾，并按进程登记把子进程连子孙一起杀掉")
    sp.add_argument("--sid", default=None, help="这一趟的会话号（写进停机开关，便于核对）")
    sp.add_argument("--status", action="store_true",
                    help="只看状态：开关在不在、登记里哪些进程还活着")
    sp.add_argument("--clear", action="store_true",
                    help="撤掉停机开关（接着跑之前要先撤，否则下一趟第 0 步就收工）")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("inbox", help="列出等着用户回答的问题（只读；不给 --sid 就扫全部会话）")
    sp.add_argument("--sid", default=None,
                    help="只查这一个会话；不给则扫该工作区所有会话（真机每一趟都有自己的 "
                         "sid，只看缺省会话会把「它在等什么」读成「没有待答」）")
    sp.add_argument("--json", action="store_true", help="打成 JSON")
    sp.set_defaults(func=cmd_inbox)

    sp = sub.add_parser("answer", help="代用户回答一个问题（写 user_answer；回答是 append-only 的）")
    sp.add_argument("qid", help="问题号（见 `agentflow inbox`）")
    sp.add_argument("text", nargs="?", default=None,
                    help="回答正文（等价于 --custom；与 --select 可以同时给）")
    sp.add_argument("--select", action="append", default=None,
                    help="选中的选项 label，可重复（DSH 的 selected：0/1/n 个）")
    sp.add_argument("--custom", default=None,
                    help="补充或覆盖的正文（DSH 的 custom：对多选是补充、对单选是覆盖）")
    sp.add_argument("--sid", default=None, help="问题所在会话号（见 `agentflow inbox`）")
    sp.set_defaults(func=cmd_answer)

    # 格数不手抄：判据真身是 `closing.DEFAULT_CHECKS`，这里现读它的长度
    # （`draft/63` §3 #3 的口径：这类定值随代码变，手抄一份就是给自己留一个会过期的数 ——
    # 真机读数里它已经漂过一次：手抄"五条"而真身是 8 格）。
    from . import closing as _CL

    sp = sub.add_parser(
        "closing",
        help=f"跑收工门（draft/37 §16 P3 的 {len(_CL.DEFAULT_CHECKS)} 格；退出码 0/1/2）")
    sp.add_argument("--project-dir", default="",
                    help="项目根目录（正文与编译回执在 <它>/out/paper/；不给 ⇒ 论文那一格是「没查成」）")
    sp.add_argument("--report", default="",
                    help="报告路径（不给且没给 --project-dir ⇒ 报告形状那一格是「没查成」）")
    # 内容级验收（`draft/37` §17.3）那一段的入参：只影响那一段的读数，
    # 不影响退出码（退出码仍然只由收工门定）。三个都给缺省值 ——
    # 缺省时那几格记「没查成」，不折成通过。
    sp.add_argument("--cap-usd", type=_non_negative_float, default=None,
                    help="这一趟的成本上限（美元）—— 内容级验收的「在成本上限内」用；"
                         "不给 ⇒ 那一格是「没查成」")
    sp.add_argument("--acceptance-sid", default=None,
                    help="这一趟的会话号（内容级验收的「三态分支」那一格用；"
                         "不给 ⇒ 那一格是「没查成」，不按缺省会话读）")
    sp.add_argument("--no-review-acceptance", action="store_true",
                    help="不跑收工门之后的那个内容级验收读数（缺省就跑）")
    # M 的判据（业主 2026-10-09：「是否收工不要用机械判据，由 M 制定的目标是否达成为准」）：
    # 缺省 = 读运行内落盘的那一份（`out/review/m-verdicts.jsonl`）；显式给这里三个
    # 开关就按命令行这一份判（人/CI 代述 M 的说法时用）。都不给又没有落盘的那一份
    # ⇒ 退出码 2（「没人判过」），不是 0 也不是 1。
    sp.add_argument("--goal", default="", help="（M 的判据）这一趟的目标，一句话")
    sp.add_argument("--basis", default="", help="（M 的判据）凭什么这么判：读数/交付物路径")
    _met = sp.add_mutually_exclusive_group()
    _met.add_argument("--goal-met", dest="goal_met", action="store_true", default=None,
                      help="（M 的判据）目标达成了 ⇒ 收工（退出码 0）")
    _met.add_argument("--goal-not-met", dest="goal_met", action="store_false",
                      help="（M 的判据）没达成 ⇒ 不退（退出码 1）")
    sp.set_defaults(func=cmd_closing)

    # 项目状态报告（`draft/39` §4）：只读 + 零模型调用 —— 用户中途想知道情况时用它，
    # 而不是去问 M 一句（那条路会让 M 停下来等人，正好与"不打断协作"相反）。
    sp = sub.add_parser("status-report",
                        help="项目状态报告（只读台账与手稿；落 out/review/STATUS-<ts>.{md,json}）")
    sp.add_argument("--since", default="", help="只统计这个 ISO 时间前缀之后的读数（如 2026-10-05）")
    sp.add_argument("--out", default="", help="报告落哪个目录（缺省 <工作区>/out/review）")
    sp.set_defaults(func=cmd_status_report)

    # 用户端网页：给人看"它在等什么、跑到哪了、上一趟干了什么"，并让人在那里回答问题。
    # 它是「只读投影」（每次请求都从盘上现读），唯一的写路径是 `POST /answer` → `userio.answer_question`。
    sp = sub.add_parser("web", help="起用户端网页（本地小服务：待回答面板 / 运行态 / 事件回放）")
    sp.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认只监听本机；给 0.0.0.0 才会被别的机器访问）")
    sp.add_argument("--port", type=int, default=8788, help="端口（0 = 让系统给一个空闲端口）")
    sp.add_argument("--open", action="store_true", help="起来之后用默认浏览器打开")
    sp.add_argument("--json", action="store_true",
                    help="只打印一行 URL 的 JSON（起后台任务时用它拿确切地址）")
    sp.add_argument("--token", default="",
                    help="访问口令（也可用环境变量 AGENTFLOW_WEB_TOKEN；给了就必须带上）")
    # 裁定 T1：只加这两个开关。W3/W4 之后它们真的接线（`writes.authorize()` 的第 3/4 层），
    # 下面两句 help 逐字说明它们各管哪一面 —— 免得读 help 的人以为"缺省只读"是"还没接线"。
    sp.add_argument("--allow-writes", action="store_true",
                    help="允许写面（起一趟 / 插话 / 答问 / 叫停 / 改设置 / 改预算）；"
                         "缺省只读，不开这一档时写端点一律 403")
    sp.add_argument("--no-settings-write", action="store_true",
                    help="关掉设置写面（只关 POST /api/settings，其余写面照旧）")
    sp.set_defaults(func=cmd_web)

    # 体检：跑之前先知道这台机器能做哪些事（有没有 key / 有没有证明检查器 / Mathlib 对不对得上）。
    # 它不发起任何模型调用 —— 于是"形式化能不能做"这件事在花钱之前就有一个可读的三态读数。
    sp = sub.add_parser("doctor", help="体检：这台机器能做哪些事（不花钱；0 齐 / 1 有缺 / 2 没查成）")
    sp.add_argument("--json", action="store_true", help="把体检结果打成 JSON")
    sp.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    # 先把输出编码钉住再做任何事：GBK 控制台编不出摘要里的 `⇒` ⇒ print 抛异常 ⇒ 进程以 1
    # 结束，而 1 是"查过了、发现问题"。那会把 `run` 无 key 的受控码 2（没跑成）反转成 1。
    pin_utf8()
    raw = list(sys.argv[1:] if argv is None else argv)
    # 不带任何参数 ⇒ 进交互台。理由：这套工具的动词与开关多到"不看文档就用不起来"，
    # 而它的主要用户是研究者，不是每天敲这串命令的人。给一个菜单不是为了炫技，
    # 是为了让"能用"这件事不依赖记忆。
    if not raw:
        return shell()
    parser = build_parser()
    args = parser.parse_args(raw)
    tty.set_style(color=False if (args.no_color or args.plain) else None,
                  charset="ascii" if args.plain else None)
    if args.cmd is None:
        return shell()
    try:
        return args.func(args)
    except StoreError as e:
        print(f"[store 错误] {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # `FINAL-R5-02`：`agentflow run` 的取消此前是不可达的，而且被中断的那一跑在磁盘上
        # 与"从来没跑过"同形（`KeyboardInterrupt` 是 `BaseException`，穿出 `except Exception`）。
        # 这里按三态纪律把它记成"没查成"（退出码 2），并逐字说清"产物可能不完整" ——
        # 不假装六件产物已经写齐（那要靠真正的取消面才能做到，见 run_topic 的 docstring）。
        print("[已中断] 本次没有跑完（Ctrl-C）⇒ 退出码 2 = 没查成；"
              "产物目录里可能只有部分文件，不许当成一次正常运行的读数。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
