"""命令行入口。

设计意图：把"能跑起来的最小操作集"固定成几个动词，避免每次都写一次性脚本 ——
一次性脚本正是这类系统后来无法复现的根源。

    python -m abflow init / submit / run-a / run-b / status / verify / rebuild / repair / demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import schema as S
from .store import Store, StoreError
from .verify import verify_all

DEFAULT_ROOT = Path(__file__).resolve().parents[2]  # test/test1/


# ---------------------------------------------------------------- 配置装载


def load_config(root: Path, path: str | None = None) -> dict:
    p = Path(path) if path else (root / "config.yaml")
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # 环境里已装；没有则回退 JSON
        return yaml.safe_load(text) or {}
    except Exception:
        try:
            return json.loads(text)
        except Exception as e:
            raise SystemExit(f"配置解析失败（{p}）：{e}")


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
    st = make_store(args.root)
    st.init()
    if args.file:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        items = payload["rows"] if isinstance(payload, dict) and "rows" in payload else payload
    else:
        items = [{"topic": args.topic, "mode": args.mode, "content_description": args.content or ""}]
    added = []
    with st.tx("search_requests", actor=args.by, note="submit") as tx:
        rows = tx.rows("search_requests")
        n = len(rows)
        for i, it in enumerate(items):
            rid = f"r-{n + i + 1:04d}"
            while any(r.get("request_id") == rid for r in rows):
                n += 1
                rid = f"r-{n + i + 1:04d}"
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
    print(f"[submit] 已提交 {len(added)} 条：{', '.join(added)}")
    return 0


def _build_providers(cfg: dict, names: list[str], root: Path):
    """按配置构造 provider。import 放在这里，避免无网络环境下 `abflow status` 也去连网。"""
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
    return 0


def cmd_run_b(args) -> int:
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
    return 0


def cmd_status(args) -> int:
    st = make_store(args.root)
    st.init()
    s = st.stats()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    print(f"根目录：{s['root']}")
    for t in ("search_requests", "literature", "concepts", "relations"):
        info = s[t]
        extra = " ".join(f"{k}={v}" for k, v in info.items() if k != "count")
        print(f"  {t:16} 行数={info['count']:<5} {extra}")
    print(f"  events          {s['events']['appended']} 条")
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
    # 关键：引文复核参数必须与 agent_b 写入时用的**同一份配置**，否则 --deep
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
    if args.strict and not rep.ok:
        return 1
    return 0


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
    """按 verify 的派生规则修复 related_concepts（唯一允许的"自动修复"，因为它完全可派生）。"""
    from . import dedup as D

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

    这个命令存在的意义：工具层的**权限面**是设计的一部分（A 拿不到 D 的工具等），
    但它默认是隐式的 —— 加一条命令把它变成可打印的事实，才好在评审时核对。
    """
    from abflow.tools import ROLES, build_registry

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    # ⚠️ 角色清单必须来自 `ROLES`，**不许在这里写死**。
    # 这里原先写死 `("A","B","C","D")`，于是 E/F/G/H 落地之后，本命令会
    # 一边报告"工具总数 55"，一边只列 4 个角色的工具数 —— 而"角色即权限面"
    # 恰恰是靠这条命令变成**可打印的事实**的。写死名单让那句"评审时可核对"落空。
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
        # 只读角色的写工具泄漏必须**一眼可见**：它是"审校者手里有没有刀"的直接答案。
        from abflow.tools import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE

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
    from abflow.agent_c import AgentC

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

    row = rep.persist()
    print(rep.markdown)
    # ⚠️ `persist()` 返回的是**登记行**（report_id / markdown_path / abs_path），
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
    from abflow import dedup as D

    if S.is_valid_id(token) and any(r["concept_id"] == token for r in st.rows("concepts")):
        return token
    hit = D.find_concept(st.rows("concepts"), token)
    return hit["concept_id"] if hit else None


def cmd_research(args) -> int:
    """运行 D 的研究循环（可指定 C 报告，或用最近一份）。"""
    from abflow.agent_d import AgentD

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
    from abflow.agent_a import AgentA
    from abflow.agent_b import AgentB
    from abflow.extract import extract_text
    from abflow.llm import RuleExtractor
    from abflow.pipeline import run_pipeline
    from abflow import fetch as F

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


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abflow", description="A/B 多智能体协同工作流（原型）")
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

    sp = sub.add_parser("verify", help="校验全局不变量")
    sp.add_argument("--deep", action="store_true", help="重新打开文献复核引文（慢）")
    sp.add_argument("--strict", action="store_true", help="有错误时返回非零退出码")
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
    sp.add_argument("--role", default=None, choices=["A", "B", "C", "D"], help="只看某个角色的工具")
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
