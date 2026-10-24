# -*- coding: utf-8 -*-
"""说明页与实现对得上的判据（`ui/src/pages/Help.tsx`）。

## 这一份守什么

`Help.tsx` 不调任何端点（`tests/test_webui_pages.py` 的 `PAGES["Help"] == ()` 钉着
这一点），所以它没有任何机器读数能自证正确 —— 页面上的每一句都可能已经过期，而其余
所有后端判据照样全绿。这一份按文本级把五条最要紧的事实钉住：

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| §1 `_roster_problems` | 名册面板的存在、`/api/roster`、盘上落点 `out/roster/`、收件箱积压、深度 | 页面不提名册，用户不知道"谁是谁的子"从哪看 |
| §2 `_tristate_problems` | 三态三个词 + 「没读到」不等于「没有」+ 名册的 `answer="unknown"` + 计数栏是 null 不是 0 | 三态被折成一档，"没读到"被读成"没有" |
| §3 `_exit_code_problems` | 退出码六档的中文名 + 至少四个数字串 | 页面只剩一句"非 0 就是坏了" |
| §4 `_budget_problems` | `total_usd` / 不传 = 无限制 / 累计制 / `budget.json`，且把 `cap_usd` 分开 | 不设预算被读成"不许花钱"，或把 `cap_usd` 当成预算寄存器 |
| §5 `_write_problems` | 七条 POST 全部点名 + "没有登记了还没落地" + 页面点到的每条端点都在路由表里 | 写面被说成"还没接线"，或页面写着一个不存在的端点 |

## 为什么是文本级而不是读端点

这一页的"正确"不是盘上的读数，而是说明文与实现同口径（页面分工、名册、三态、
退出码、预算、写面）—— 那件事只有源码能回答。端点的存在性由 §5 顺带对账
（`routes.patterns()` 是唯一真身），文本与实现因此不是两套口径。

## 负控

每个检查逻辑都是纯函数，各配一条"把关键那一句改坏 ⇒ 必须报出来"的负控；
没有负控，正则哪天失配就会以"一条都没解析到"的形态静默变绿。
"""
from __future__ import annotations

import pathlib
import re

from agentflow.webui import routes

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
HELP = REPO / "ui" / "src" / "pages" / "Help.tsx"

#: 块注释与整行注释（与 `tests/test_webui_pages.py` 同一条口径：只处理这两种；
#: 渲染正文里的中文引号对不参与扫描，所以不能逐字符找引号）。
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _strip_comments(text: str) -> str:
    """剥掉注释后的页面源码（注释不上屏，写在注释里的事实不算数）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _body() -> str:
    """说明页的渲染正文（注释已剥掉）。"""
    return _strip_comments(HELP.read_text(encoding="utf-8"))


# ====================================================================== §1 名册
def _roster_problems(body: str) -> list[str]:
    """§1：名册面板能看什么、端点叫什么、真身落在哪 —— 一条都不能少。"""
    wanted = (
        ("/api/roster", "名册那条端点"),
        ("out/roster/", "名册真身在盘上的落点（out/roster/父编号.jsonl）"),
        ("父编号", "文件名就是父的绝对编号这一条口径"),
        ("收件箱", "收件箱积压那一格"),
        ("深度", "深度口径（树里的距离，不是 tasks.depth）"),
    )
    return [f"说明页里缺 {token!r}：{why}" for token, why in wanted if token not in body]


# ====================================================================== §2 三态
_TRI_WORDS = ("computed", "unreadable", "not_applicable")


def _tristate_problems(body: str) -> list[str]:
    """§2：三态与「没读到」的语义（这一条是整页最要紧的一段）。"""
    problems = [f"说明页里缺三态词 {word!r}" for word in _TRI_WORDS if word not in body]
    for phrase, why in (
        ("「没读到」不等于「没有」", "没有把「没读到」与「没有」分开的那一句"),
        ('answer="unknown"', "名册那套 answer=unknown 没写"),
        ("不是 0", "计数栏是 null 而不是 0 这一条没写"),
    ):
        if phrase not in body:
            problems.append(f"说明页里缺 {phrase!r}：{why}")
    return problems


# ====================================================================== §3 退出码
#: 六档的中文名（`cli.EXIT_CODE_BY_STOP` 的注释里逐档写着同一组词）。
_EXIT_WORDS = ("正常完成", "行为异常", "研究启动失败", "等待用户",
               "正常且中途停止", "自行停止")


def _exit_code_problems(body: str, *, min_codes: int = 4) -> list[str]:
    """§3：退出码六档 —— 六个中文名都在，且至少四个数字串（`code: "N"`）在。"""
    problems = [f"说明页里缺退出码那一档：{word!r}" for word in _EXIT_WORDS
                if word not in body]
    codes = [digit for digit in "012345" if f'code: "{digit}"' in body]
    if len(codes) < min_codes:
        problems.append(f"退出码数字串只写了 {len(codes)} 个（至少要 {min_codes} 个）："
                        f"{codes}")
    if "没登记" not in body or "归 1" not in body:
        problems.append("没写「没登记的 stop_reason 一律归 1」（安全侧那一条）")
    return problems


# ====================================================================== §4 预算
def _budget_problems(body: str) -> list[str]:
    """§4：预算寄存器的语义 —— 不传 = 无限制、传多少就是多少、累计制，且与 cap_usd 分开。"""
    wanted = (
        ("budget.json", "寄存器的名字"),
        ("total_usd", "寄存器里那一格额度（不是 cap_usd）"),
        ("不传 = 无限制", "「不传 = 无限制」那一句"),
        ("累计制", "「累计制」那一句"),
        ("cap_usd", "把 cap_usd 与预算寄存器分开的那一段"),
        ("不进预算寄存器", "cap_usd 不进预算寄存器这一条结论"),
    )
    return [f"说明页里缺 {token!r}：{why}" for token, why in wanted if token not in body]


# ====================================================================== §5 写面
#: `writes.ROUTES` 里的八条 POST（顺序与那张表一致）。2026-10-24（D-50）：缓存预热
#: `POST /api/cache/warm` 并进了写面子表（`cacheface.ROUTES`），于是这里从七条变八条；
#: 这一条只钉"页面上有没有逐条点名"，条数本身由
#: `tests/test_help_page_matches_the_code.py` 与 `writes.ROUTES` 现算对拍。
_WRITES = ("/answer", "/api/stop", "/api/submit", "/api/settings",
           "/api/budget", "/api/run", "/api/task", "/api/cache/warm")

#: 页面里点到的端点（`/api/...` 一整段，含占位符与大括号）。
_ENDPOINT = re.compile(r"/(?:api/[A-Za-z0-9_{}/-]+)")


def _write_problems(body: str) -> list[str]:
    """§5：写面现状（八条 POST 全接线）+ 页面点到的端点都必须真在路由表里。"""
    problems = [f"写面那八条里没写 {path!r}（它已接线）" for path in _WRITES
                if path not in body]
    if "没有「登记了还没落地」的写端点" not in body:
        problems.append("没写「没有登记了还没落地」这一句（写面现状说不清）")
    return problems


def _endpoint_problems(body: str, table: tuple[tuple[str, str, str], ...] | None = None
                       ) -> list[str]:
    """页面点到的每条 `/api/...` 都必须在后端路由表里（端点只有一个真身）。"""
    patterns = set(routes.patterns(table=table))
    named = sorted(set(_ENDPOINT.findall(body)))
    return [f"说明页写了一个路由表里没有的端点：{path}" for path in named
            if path not in patterns]


# ====================================================================== 正控（真文件）
def test_the_help_page_names_the_roster_and_its_disk_layout() -> None:
    """§1：说明页必须写清名册怎么读（树 / 绝对编号 / 深度 / 收件箱积压 / 盘上落点）。"""
    body = _body()
    assert _roster_problems(body) == [], _roster_problems(body)
    assert "/api/roster" in routes.patterns(), routes.patterns()

    # 负控：把端点那一格改掉 ⇒ 必须报到它。
    assert _roster_problems(body.replace("/api/roster", "/api/nope")), (
        "端点改掉了，判据却一声不吭")
    # 负控：把落点改掉 ⇒ 必须报到它。
    assert _roster_problems(body.replace("out/roster/", "out/nowhere/")), (
        "落点改掉了，判据却一声不吭")


def test_the_help_page_says_unread_is_not_absent() -> None:
    """§2：三态三个词 + 「没读到」不等于「没有」+ `answer="unknown"` + 计数栏 null。"""
    body = _body()
    assert _tristate_problems(body) == [], _tristate_problems(body)

    # 负控三条：各抽掉一句，判据都必须红。
    assert _tristate_problems(body.replace("「没读到」不等于「没有」", "没读到就是没有")), (
        "「没读到」那一句被改写了，判据却一声不吭")
    assert _tristate_problems(body.replace('answer="unknown"', "answer=ok")), (
        "answer=unknown 那一格被改掉了，判据却一声不吭")
    assert _tristate_problems(body.replace("不是 0", "就是 0")), (
        "「null 不是 0」被改掉了，判据却一声不吭")


def test_the_help_page_lists_the_six_exit_codes() -> None:
    """§3：退出码六档（六个中文名 + 至少四个数字串 + 没登记归 1）。"""
    body = _body()
    assert _exit_code_problems(body) == [], _exit_code_problems(body)

    # 反真空：六档的数字串一个不少（`code: "0"` … `code: "5"`）。
    assert [d for d in "012345" if f'code: "{d}"' in body] == list("012345"), (
        "六档没有全部写出来（§3 要求至少四个，真实页面必须六个都在）")

    # 负控：删掉 0 与 1 两条 ⇒ 只剩四个，恰好还在下限上；再删一条 ⇒ 必须红。
    shell = body.replace('code: "0"', 'code: "x"').replace('code: "1"', 'code: "y"')
    assert len([d for d in "012345" if f'code: "{d}"' in shell]) == 4
    assert _exit_code_problems(shell) == [], "只剩四档时不该红（下限就是四）"
    shell2 = shell.replace('code: "2"', 'code: "z"')
    assert _exit_code_problems(shell2), "只剩三档，判据却一声不吭"


def test_the_help_page_says_no_budget_means_unlimited() -> None:
    """§4：`total_usd` / 不传 = 无限制 / 累计制，且 `cap_usd` 不是预算寄存器那一格。"""
    body = _body()
    assert _budget_problems(body) == [], _budget_problems(body)

    # 负控：把「不传 = 无限制」改写成「不传就是不许花」⇒ 必须红。
    assert _budget_problems(body.replace("不传 = 无限制", "不传 = 不许花钱")), (
        "预算那一条被改写了，判据却一声不吭")
    # 负控：把 total_usd 换成 cap_usd（任务书里就写错过这个字段名）⇒ 必须红。
    assert _budget_problems(body.replace("total_usd", "cap_usd")), (
        "寄存器字段名被换成 cap_usd，判据却一声不吭")


def test_the_help_page_lists_the_wired_writes_and_no_dead_endpoints() -> None:
    """§5：七条 POST 全部点名，且页面点到的每条端点都在路由表里。"""
    body = _body()
    assert _write_problems(body) == [], _write_problems(body)
    assert _endpoint_problems(body) == [], _endpoint_problems(body)

    # 反真空：这一页点到的端点不止一两条（否则"都在表里"是空话）。
    named = set(_ENDPOINT.findall(body))
    assert len(named) >= 12, sorted(named)

    # 负控：少写一条写端点 ⇒ 必须点名报出来。
    assert _write_problems(body.replace("/api/task", "/api/interject")), (
        "插话那条端点写错了，判据却一声不吭")
    # 负控：写一个路由表里没有的端点 ⇒ 必须点名报出来。
    assert _endpoint_problems("/api/nope 这一条不存在"), (
        "写了一个不存在的端点，判据却一声不吭")


def test_the_help_page_is_still_a_static_page() -> None:
    """反真空：说明页仍在盘上，而且不自己 fetch（端点只能从 `api.ts` 走）。"""
    assert HELP.is_file(), f"{HELP} 不在盘上"
    assert "fetch(" not in _body(), "说明页自己 fetch 了 —— 它该一条端点都不调"
