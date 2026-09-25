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
from .store import Store, StoreError
from .verify import verify_all

DEFAULT_ROOT = Path(__file__).resolve().parents[2]  # test/test1/


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

    1. 取号只用 `interactions.next_prefixed_id`（全项目唯一的 `r-NNNN` 判据）。
       本函数原先自己数 `len(rows) + i + 1` 并靠一个 `while` 撞号重试 —— 那是第二份
       取号判据，语义与 `next_prefixed_id` 的 `max+1` 不同：表里只有 `r-0001`/`r-0003`
       时，一个发 `r-0002`、另一个发 `r-0004`（`DEVELOPMENT.md` §3 纪律 2：
       "ID 分配器只有一处；新增第二份 = 违规"）。旧写法还没有上限：
       行数过万时会静默产出 `r-10000` 这种越出 4 位空间的号。
    2. 输入不合法 ⇒ 整批不写 + 退出码 2。`row.validate()` 的 `ValueError` 原先
       在事务中途炸出，调用方拿到的是一个 traceback；而"你给的 mode/topic 不合法"
       是调用方错误，应当以一行说明 + 非零退出码结束。事务本身是"异常即不提交"，
       所以这里 catch 之后可以如实说"整批未写入"。
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
        print(f"[submit] 请求不合法，**整批未写入**：{e}", file=sys.stderr)
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
    agent = AgentA(st, providers=providers, downloader=downloader, config={**(cfg.get("agent_a") or {}), **(cfg.get("lease") or {})})
    out = agent.run(max_requests=args.max if args.once else None)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if _run_a_failed(out) else 0


def _run_a_failed(out: Mapping) -> bool:
    """`AgentA.run()` 的返回是否表示终局失败（三态里的"失败"，不是"没做"）。"""
    return bool(out.get("gave_up")) or out.get("outcome") == "search_failed"


def cmd_run_b(args) -> int:
    """跑一轮 B。

    退出码：0 = 没有抽取失败；1 = 至少一篇文献的抽取抛了异常。
    `AgentB` 刻意不把这类文献置 `processed`（留给租约到期重试，见模块 docstring
    第 4 条），也就是说"这一轮没干成"—— 那必须能从退出码上看见，
    否则定时任务会把"每轮都在重试同一篇"当成持续成功。
    """
    from .agent_b import AgentB
    from .extract import extract_text
    from .llm import RuleExtractor

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    agent = AgentB(
        st,
        extractor=RuleExtractor(),
        extract_text=extract_text,
        config={**(cfg.get("agent_b") or {}), **(cfg.get("lease") or {})},
    )
    out = agent.run(max_docs=args.max if args.once else None)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out.get("failed"):
        print(f"[run-b] 有 {out['failed']} 篇文献抽取失败（未置 processed，等租约到期重试）", file=sys.stderr)
        return 1
    return 0


def cmd_status(args) -> int:
    st = make_store(args.root)
    st.init()
    s = st.stats()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    print(f"根目录：{s['root']}")
    # 表名清单必须来自 `S.TABLES`，不许在这里写死。
    # 这里原先写死 `("search_requests", "literature", "concepts", "relations")`，
    # 而 `Store.stats()` 明明返回全部 15 张表 —— 于是"库长什么样"的第一入口
    # 静默地不显示另外 11 张（analysis_reports / experiments / documents / tasks …）。
    # 写死的第二份名单还会在表被改名/删除时以 `KeyError` 崩掉（`s[t]`），
    # 而不是如实报告。与 `cmd_tools` 里那句"角色清单必须来自 ROLES"同一个道理。
    for t in S.TABLES:
        info = s[t]
        extra = " ".join(f"{k}={v}" for k, v in info.items() if k != "count")
        print(f"  {t:20} 行数={info['count']:<5} {extra}")
    print(f"  {'events':20} {s['events']['appended']} 条")
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
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"校验完成：{'通过' if rep.ok else '**有错误**'}  "
              f"错误 {len(rep.errors)} / 警告 {len(rep.warnings)}")
        for i in rep.issues:
            mark = "ERR " if i.level == "error" else "WARN"
            print(f"  [{mark}] {i.table}/{i.row_id or '-'} {i.code}: {i.message}")
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
    with st.tx("concepts", "relations", actor="repair", note="related") as tx:
        rels = tx.rows("relations")
        changed = 0
        for c in tx.rows("concepts"):
            want = D.derive_related_concepts(c["concept_id"], rels, include_suspect=True)
            if c.get("related_concepts") != want:
                c["related_concepts"] = want
                c["updated_at"] = S.now_iso()
                tx.upsert("concepts", c, note="related_recomputed")
                changed += 1
    print(f"[repair] related_concepts 重算了 {changed} 行")
    return 0


def cmd_tools(args) -> int:
    """列出工具层装配情况（按角色）。

    这个命令存在的意义：工具层的权限面是设计的一部分（A 拿不到 D 的工具等），
    但它默认是隐式的 —— 加一条命令把它变成可打印的事实，才好在评审时核对。
    """
    from agentflow.tools import ROLES, build_registry

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    # 角色清单必须来自 `ROLES`，不许在这里写死。
    # 这里原先写死 `("A","B","C","D")`，于是 E/F/G/H 落地之后，本命令会
    # 一边报告"工具总数 55"，一边只列 4 个角色的工具数 —— 而"角色即权限面"
    # 恰恰是靠这条命令变成可打印的事实的。写死名单让那句"评审时可核对"落空。
    build = build_registry(store=st, workspace_root=root, roles=tuple(ROLES))
    if args.json:
        print(json.dumps(build.summary(), ensure_ascii=False, indent=2))
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

        by_role = {r: len(build.registry.for_role(r)) for r in ROLES}
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
            names = [f"{r['concept_id']}={r['name']}" for r in st.rows("concepts")]
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
    """把用户给的东西解析成概念代号：既接受 4 位代号，也接受概念名（走 dedup 的规范化匹配）。"""
    from agentflow import dedup as D

    if S.is_valid_id(token) and any(r["concept_id"] == token for r in st.rows("concepts")):
        return token
    hit = D.find_concept(st.rows("concepts"), token)
    return hit["concept_id"] if hit else None


def cmd_research(args) -> int:
    """运行 D 的研究循环（可指定 C 报告，或用最近一份）。"""
    from agentflow.agent_d import AgentD

    root = Path(args.root or DEFAULT_ROOT).resolve()
    cfg = load_config(root, args.config)
    st = make_store(root)
    st.init()
    d = AgentD(st, config=cfg.get("agent_d") or {})
    out = d.run_from_latest_report(report_id=args.report_id, gap_rounds=args.gap_rounds)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_pipeline(args) -> int:
    """把 A→B→C→D 串起来跑（DESIGN-TOOLS.md §5）。"""
    from agentflow.agent_a import AgentA
    from agentflow.agent_b import AgentB
    from agentflow.extract import extract_text
    from agentflow.llm import RuleExtractor
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
            config={**(cfg.get("agent_a") or {}), **(cfg.get("lease") or {})},
        )
        agent_b = AgentB(
            st,
            extractor=RuleExtractor(),
            extract_text=extract_text,
            config={**(cfg.get("agent_b") or {}), **(cfg.get("lease") or {})},
        )

    out = run_pipeline(
        st,
        request=args.request,
        gap_rounds=args.gap_rounds,
        config=cfg,
        agent_a=agent_a,
        agent_b=agent_b,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
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
    )
    print(f"[run] 工作区：{root}")
    print(f"[run] 产物目录：{res['out_dir']}")
    print(f"[run] 退出原因：{res['reason']}；调用 {res['calls']} 次；"
          f"已花 {res['spent_usd']} 美元（预算 {args.budget_usd}）")
    # 检索三态与断言台账摘要必须打到 stdout：它们是"这次的结论有没有外部依据"
    # 的直接答案。只写在 JSON 里，等于要人先去读文件才知道该不该相信这份报告。
    counts = res["claims"]
    print(f"[run] 检索：{res['retrieval_status']}；断言 {counts['total']} 条"
          f"（逐字通过 {counts['verified']}：摘要级 {counts.get('verified_abstract', 0)}、"
          f"全文级 {counts.get('verified_fulltext', 0)}；未验证 {counts['unverified']}）")
    lean = res.get("lean") or {}
    print(f"[run] Lean：开启={'是' if lean.get('enabled') else '否'}；"
          f"跑过={'是' if lean.get('ran') else '否'}；"
          f"proof 级证据 {lean.get('proved', 0)} 条 —— {lean.get('reason')}")
    print("[run] 六件产物：" + "、".join(res["artifacts"]))
    # `not_wired` 必须打到 stdout：它是"这次有哪些事确定没做"的直接答案，
    # 只写在 JSON 里等于要人先去读文件才知道不该相信这份报告。
    man = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
    for item in man["not_wired"]:
        print(f"[run] 未接线：{item['name']} —— {item['reason']}")
    return int(res["exit_code"])


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentflow", description="A/B 多智能体协同工作流（原型）")
    p.add_argument("--root", default=None, help="工作目录（默认 test/test1/）")
    p.add_argument("--config", default=None, help="配置文件路径（默认 <root>/config.yaml）")
    sub = p.add_subparsers(dest="cmd", required=True)

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

    sp = sub.add_parser("research", help="D：研究循环")
    sp.add_argument("--report-id", default=None, help="基于哪份 C 报告（缺省用最近一份）")
    sp.add_argument("--gap-rounds", type=int, default=2)
    sp.set_defaults(func=cmd_research)

    sp = sub.add_parser("pipeline", help="编排：C→D→(A→B→D 复查) 循环")
    sp.add_argument("--request", required=True, help="自然语言分析需求")
    sp.add_argument("--gap-rounds", type=int, default=2)
    sp.add_argument("--no-search", action="store_true", help="不跑 A/B（只做静态分析）")
    sp.set_defaults(func=cmd_pipeline)

    # 端到端一条命令。退出码即 `run_topic` 的三态：0 / 1 / 2。
    sp = sub.add_parser("run", help="端到端跑一个主题（检索→作答→逐字回验→记账→熔断→六件产物）")
    sp.add_argument("--topic", required=True, help="研究主题")
    sp.add_argument("--budget-usd", type=float, default=1.0,
                    help="美元上限（硬约束：每轮调用前检查，达线即停）")
    sp.add_argument("--out", default=None, help="产物目录（默认新建临时目录并打印路径）")
    sp.add_argument("--max-calls", type=int, default=3)
    sp.add_argument("--model", default=None, help="只覆盖模型名（key/base_url 一律来自环境变量）")
    sp.add_argument("--prompt-version", default="v1", help="prompt 模板版本（写进清单）")
    sp.add_argument("--fulltext", action="store_true",
                    help="获取开放全文（逐条下载；回验因此可能到达全文级）")
    sp.add_argument("--lean", action="store_true",
                    help="对答复里的 Lean 代码块真跑证明检查器（需要环境里已装 Lean；"
                         "只有 verified 才算 proof 级证据）")
    # `--now` 只为自动化测试注入固定时间戳：产物里的时间戳可复现，断言才稳得住。
    sp.add_argument("--now", default=None, help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except StoreError as e:
        print(f"[store 错误] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
