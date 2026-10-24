# -*- coding: utf-8 -*-
"""说明页里每个数字、每条命令、每个键名都要能追到代码（`ui/src/pages/Help.tsx`）。

## 为什么还要这一份（`tests/test_webui_help_is_current.py` 已经在守五条）

那一份守的是"说明页有没有讲到"（名册 / 三态 / 退出码 / 预算 / 写面各一句）。它守不住
"讲的那句话里的数字还是不是真的"：2026-10-24（D-50）实测到两簇集体过期 —— 角色
十变十一（L 于 2026-10-22 新设）、写面七条 POST 变八条（`POST /api/cache/warm` 上线）。
两处都是"句子结构没变、数字变了"，于是那五条文本级判据全绿。

这一份按四层守，每层都有自己的反真空：

| 层 | 它守什么 | 改坏之后长什么样 |
|---|---|---|
| 1 数字 | 页面里每个"数字 + 量词"的断言，都能追到一处现算的代码读数 | 页面写"九张卡"而 `ARTIFACT_CARDS` 是十张 |
| 2 命令 | 页面里每条示例命令都能被 `cli.build_parser()` 解析；`--root` 那句抱怨与真实行为同源 | 页面写着一条不存在的子命令 |
| 3 键名 | 页面点名的每个键都在对应接口的声明里（`readers._TS_TYPES` / `state._TS_TYPES`） | 页面写 `upsertz` 而接口里叫 `upserts` |
| 4 反真空 | 把某个数字改错、把某条命令改成不存在的子命令、把某个键名改歪，前三层必须各自红 | 判据是一枚橡皮图章 |

## 两条口径

一是"一"不参与第 1 层：它是量词（"一个父一份名册"），不是计数；`0` 与 `1` 同理，除了
表里逐条登记的那些。二是"页面自己的结构"也算代码：`六格读数` 这一格的真值就是那张卡里
`<b>` 的个数，`两处待答` 的真值就是 `Home.tsx` 里出现"全局待答清单"的处数 —— 它们
不从后端来，但仍然是"改一处而另一处不动就会红"的可计算读数。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import pathlib
import re
import tempfile
from dataclasses import dataclass
from typing import Callable

from agentflow import capabilities
from agentflow import cli
from agentflow import evidencebits as EB
from agentflow import reviewaccept
from agentflow import schema
from agentflow import secretary
from agentflow import specs as SP
from agentflow import stopctl
from agentflow.webui import readers
from agentflow.webui import state as state_mod
from agentflow.webui import writes

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
HELP = REPO / "ui" / "src" / "pages" / "Help.tsx"
MAIN = REPO / "ui" / "src" / "main.tsx"
ARTIFACTS = REPO / "ui" / "src" / "pages" / "Artifacts.tsx"
MACHINE = REPO / "ui" / "src" / "pages" / "Machine.tsx"
HOME = REPO / "ui" / "src" / "pages" / "Home.tsx"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)
#: 只剥行内标签、不剥带 `title=` 的那些：卡片标题里的"六格""六档"也是断言。
_INLINE_TAG = re.compile(r"</?span[^>]*>|</?b>")


def _squash(text: str) -> str:
    """去掉所有空白（"10 条" 与 "10条" 是同一个断言，比对时不该差一个空格）。"""
    return re.sub(r"\s+", "", text)


def _strip_comments(text: str) -> str:
    """剥掉注释（注释不上屏，写在注释里的事实不算数）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _unescape(text: str) -> str:
    for entity, real in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"')):
        text = text.replace(entity, real)
    return text


def _plain(text: str) -> str:
    """上屏正文的近似：注释剥掉、行内标签剥掉、实体还原、横向空白压成一个空格。"""
    return re.sub(r"[ \t]+", " ", _unescape(_INLINE_TAG.sub("", _strip_comments(text))))


# ====================================================================== 1 数字断言
#: 数字 + 量词。量词表要包含页面真用到的那些（"态"也在内：三态是断言）。
_MEASURES = "个|页|张|档|条|位|格|层|种|栏|项|步|字|笔|段|遍|处|次|名|分|列|块|节|套|态"
_NUMBER_ASSERTION = re.compile(
    r"(?<![0-9A-Za-z-])((?:\d+)|[一二两三四五六七八九十]{1,4})\s*(" + _MEASURES + r")")

#: 中文数字（够用即可：这一页最大的数是 160，量词前的数没有超过 500 的）。
_CN_DIGIT = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _int_of_numerals(text: str) -> int | None:
    """把 `"9"` / `"九"` / `"十一"` / `"160"` 读成整数（读不出返回 None）。"""
    text = text.strip()
    if text.isdigit():
        return int(text)
    if not text or any(ch not in _CN_DIGIT for ch in text):
        return None
    if text == "十":
        return 10
    if "十" in text:
        head, _, tail = text.partition("十")
        head_v = 1 if head == "" else (_CN_DIGIT[head] if len(head) == 1 else None)
        tail_v = 0 if tail == "" else (_CN_DIGIT[tail] if len(tail) == 1 else None)
        if head_v is None or tail_v is None:
            return None
        return head_v * 10 + tail_v
    return _CN_DIGIT[text] if len(text) == 1 else None


def _declared(module: str, interface: str) -> tuple[str, ...]:
    """契约里的那一个接口声明了哪些键（`readers._TS_TYPES` / `state._TS_TYPES`）。"""
    table = readers._TS_TYPES if module == "readers" else state_mod._TS_TYPES
    for name, _source, fields in table:
        if name == interface:
            return tuple(f[0] for f in fields)
    raise AssertionError(f"{module} 里没有接口 {interface!r}：这张契约表是键名的唯一真身")


# ---------------------------------------------------------------- 后端读数（现算）
def _roles(_raw: str) -> int:
    """角色数：`capabilities.CAPABILITIES` 的键数（并与 `specs` 与 `schema.ROLES` 交叉对账）。"""
    got = len(capabilities.CAPABILITIES)
    assert got == len(SP.builtin_specs()), "两层角色表不同数了（声明与动作表分家）"
    assert got == len(schema.ROLES) + 1, "角色数应等于 schema.ROLES 加上主控"
    return got


def _pages(_raw: str) -> int:
    """页面数：`main.tsx` 的 `ROUTES` 条数（客户端路由的唯一真身）。"""
    text = MAIN.read_text(encoding="utf-8")
    block = text[text.index("export const ROUTES"):]
    return len(re.findall(r'"[^"]+"', block[: block.index("] as const")]))


def _pages_besides_this(_raw: str) -> int:
    """「旁边八页」：路由总数减去本页那一格。"""
    return _pages(_raw) - 1


def _artifact_cards(raw: str) -> tuple[str, ...]:
    text = ARTIFACTS.read_text(encoding="utf-8")
    block = text[text.index("export const ARTIFACT_CARDS"):]
    return tuple(re.findall(r"^\s*(\w+):", block[: block.index("} as const")], re.M))


def _card_count(raw: str) -> int:
    return len(_artifact_cards(raw))


def _spots_ordinal(raw: str) -> int:
    """「第九张是实验产物的落点」里的那个序数（`spots` 在表里的位次）。"""
    cards = _artifact_cards(raw)
    assert "spots" in cards, "ARTIFACT_CARDS 里没有 spots 那一张了"
    return cards.index("spots") + 1


def _evidence_columns(_raw: str) -> int:
    """证据链的栏数：`EvidenceView` 里除三态那几个键之外的数据键。"""
    skip = {"tri", "reason", "store_problems"}
    return len([f for f in _declared("readers", "EvidenceView")
                if not f.endswith("_tri") and f not in skip])


def _bit_names(_raw: str) -> int:
    return len(EB.BIT_NAMES)


def _quote_tiers(_raw: str) -> int:
    return len(EB.QUOTE_STATES)


def _criteria(_raw: str) -> int:
    return len(reviewaccept.CRITERIA)


def _auxiliary(_raw: str) -> int:
    return len(reviewaccept.AUXILIARY_SIGNALS)


def _verdict_words(_raw: str) -> int:
    """验收判据那三档：`reviewaccept` 里真出现过 pass / fail / unknown 三个字面量。"""
    src = inspect.getsource(reviewaccept)
    got = [w for w in ("pass", "fail", "unknown") if f'"{w}"' in src]
    assert len(got) == 3, f"验收判据的三档词在 reviewaccept 里不全了：{got}"
    return len(got)


def _exit_tiers(_raw: str) -> int:
    return len(set(cli.EXIT_CODE_BY_STOP.values()))


def _autonomy_extras(_raw: str) -> int:
    """多轮路径比单趟多出来的形态：`rounds` 一档 + `AUTONOMY_ONLY_EXIT_CODE` 那几档。"""
    return len(cli.AUTONOMY_ONLY_EXIT_CODE) + 1


def _post_routes(_raw: str) -> int:
    """写面子表里的 POST 条数（`writes.ROUTES` 是唯一真身，缓存那两条也并进来了）。"""
    return len([r for r in writes.ROUTES if r[0] == "POST"])


def _api_post_routes(_raw: str) -> int:
    """写面子表里挂在 `/api/` 下的 POST 条数（`/answer` 不进那张矩阵）。"""
    return len([r for r in writes.ROUTES if r[0] == "POST" and r[1].startswith("/api/")])


#: 授权矩阵的四层各有一个代码落点（少一层这个数就变）。
_AUTH_LAYER_MARKERS = ("_source_of", "_csrf_ok", "allow_writes", "settings_write")


def _auth_layers(_raw: str) -> int:
    src = inspect.getsource(writes.authorize)
    missing = [m for m in _AUTH_LAYER_MARKERS if m not in src]
    assert not missing, f"授权矩阵里读不到这几层了：{missing}"
    return len(_AUTH_LAYER_MARKERS)


def _tri_words() -> tuple[str, ...]:
    return (readers.TRI_COMPUTED, readers.TRI_UNREADABLE, readers.TRI_NOT_APPLICABLE)


def _tri_count(_raw: str) -> int:
    return len(_tri_words())


def _tri_null_tiers(_raw: str) -> int:
    """计数栏是 null 的那几档（`unreadable` / `not_applicable`，都不是 computed）。"""
    return len([w for w in ("unreadable", "not_applicable") if w in _tri_words()])


def _live_answer_tiers(_raw: str) -> int:
    """在飞面 answer 那三档：`stopctl.running_loops` 给"有 / 没有"，读不出来那一档在
    `readers.live_face` 里补"没查成"。三处都在，这个数才是 3。"""
    src = inspect.getsource(stopctl.running_loops) + inspect.getsource(readers.live_face)
    got = [w for w in ("有", "没有", "没查成") if f'"{w}"' in src]
    assert len(got) == 3, f"在飞面那三档词不全了：{got}"
    return len(got)


def _inbox_tiers(_raw: str) -> int:
    """收件箱三格：`RosterInbox` 里那三个计数键都在声明里才算。"""
    declared = _declared("readers", "RosterInbox")
    got = [f for f in ("unread", "seen_not_acked", "open_total") if f in declared]
    assert len(got) == 3, f"收件箱那三格在契约里不全了：{got}"
    return len(got)


def _unread_pair(_raw: str) -> int:
    """并进"前两格"的那两格：`unread` 与 `seen_not_acked`。"""
    declared = _declared("readers", "RosterInbox")
    return len([f for f in ("unread", "seen_not_acked") if f in declared])


def _ledger_pair(_raw: str) -> int:
    """台账那两格：`upserts` 与 `commit_markers`（都在 `LedgerReading` 里）。"""
    declared = _declared("state", "LedgerReading")
    return len([f for f in ("upserts", "commit_markers") if f in declared])


def _coverage_numbers(_raw: str) -> int:
    """名册底下"对账"那一行摆在一起的几个数（`RosterCoverage`）。"""
    return len(_declared("readers", "RosterCoverage"))


def _two_counts(_raw: str) -> int:
    """两种条数：会话自己的 `events_seen` 与工作区的 `upserts`（各在自己的接口里）。"""
    got = []
    if "events_seen" in _declared("state", "SessionRow"):
        got.append("events_seen")
    if "upserts" in _declared("state", "LedgerReading"):
        got.append("upserts")
    assert len(got) == 2, f"两种条数那两格在契约里不全了：{got}"
    return len(got)


def _two_lean_facts(_raw: str) -> int:
    declared = _declared("readers", "MachineView")
    got = [f for f in ("lean_enabled", "lean_ready") if f in declared]
    assert len(got) == 2, f"Lean 那两条独立事实在契约里不全了：{got}"
    return len(got)


def _inbox_clip(_raw: str) -> int:
    return int(readers.ROSTER_INBOX_CLIP)


def _inbox_items(_raw: str) -> int:
    return int(readers.ROSTER_INBOX_ITEMS)


def _nodes_max(_raw: str) -> int:
    return int(readers.ROSTER_NODES_MAX)


def _levels(_raw: str) -> int:
    return len(secretary.NONTRIVIALITY_LEVELS)


# ---------------------------------------------------------------- 前端同一份表的读数
def _card_block(raw: str, title_piece: str) -> str:
    """从 `<Card title="…">` 到它自己的 `</Card>`（这一张卡的那一段源码）。"""
    start = raw.index(f'<Card title="{title_piece}')
    return raw[start: raw.index("</Card>", start)]


def _six_cells(raw: str) -> int:
    """「六格读数」那一格：那张卡里有几个 `<b>` 小标题。"""
    return len(re.findall(r"<b>", _card_block(raw, "容易读混的")))


def _pending_places(_raw: str) -> int:
    """「待答两处同一个数」的那两处：`Home.tsx` 里写"全局待答清单"的处数。"""
    return len(re.findall("全局待答清单", HOME.read_text(encoding="utf-8")))


def _settings_parts(_raw: str) -> int:
    """「设置三段」的三段：`Machine.tsx` 里 `part: "…"` 的不同取值。"""
    got = set(re.findall(r'part: "(\w+)"', MACHINE.read_text(encoding="utf-8")))
    assert got, "Machine.tsx 里读不出 part 那三段了"
    return len(got)


def _error_places(raw: str) -> int:
    """「报错看三处」的那三处：那一句里用「；」分出的段数。"""
    got = re.search(r"报错看三处：(.+?)。", _squash(_plain(raw)))
    assert got is not None, "说明页里找不到「报错看三处」那一句了"
    return len([p for p in got.group(1).split("；") if p.strip()])


def _two_vocabularies(raw: str) -> int:
    """「另外两套词表」：交付说明那三档与验收判据那三档各算一套。"""
    squashed = _squash(_plain(raw))
    got = [v for v in ("ok/missing/unknown", "pass/fail/unknown") if v in squashed]
    assert len(got) == 2, f"两套词表在页面里不全了：{got}"
    return len(got)


@dataclass(frozen=True)
class Claim:
    """一条数字断言：页面上逐字出现的那一段，与它对应的现算读数。

    `count` 收的是"读到的整份 Help 源码"（前端结构类读数需要它），后端读数忽略这个参数。
    `pin` 是这一段里"归这一条管"的那个数字（一段里有两个数目时必须给，例如
    "七栏各带自己的三态"同时说了七栏与三态，两条断言各认领一个）。
    `expected` 只在字面量里没有"数字 + 量词"可读时给（例如 `500` 后面跟的是括号）。
    """

    literal: str
    source: str
    count: Callable[[str], int]
    pin: str | None = None
    expected: int | None = None


#: 页面里每一个数字断言的出处。三列：页面上的那段话、代码里的那个读数、读数在哪。
CLAIMS: tuple[Claim, ...] = (
    Claim("十一个角色（A–H、V、L、M）", "capabilities.CAPABILITIES 的键数", _roles),
    Claim("旁边八页读的就是那些盘上事实", "main.tsx 的 ROUTES 条数减本页那一格",
          _pages_besides_this),
    Claim("（加上本页一共九页）", "main.tsx 的 ROUTES 条数", _pages),
    Claim("就是本页：九页分工", "main.tsx 的 ROUTES 条数", _pages),
    Claim("九页共享那份快照与连接态", "main.tsx 的 ROUTES 条数", _pages),
    Claim("九个页面各看什么", "main.tsx 的 ROUTES 条数", _pages),
    Claim("九张卡（数字与标题同数 ARTIFACT_CARDS", "ARTIFACT_CARDS 的键数", _card_count),
    Claim("第九张是实验产物的落点", "spots 在 ARTIFACT_CARDS 里的位次", _spots_ordinal),
    Claim("五元位五位各一格", "evidencebits.BIT_NAMES 的位数", _bit_names),
    Claim("引文回验（五档，含 no_evidence）", "evidencebits.QUOTE_STATES 的档数",
          _quote_tiers),
    Claim("七栏各带自己的三态", "EvidenceView 的数据键数", _evidence_columns, pin="七栏"),
    Claim("七栏各带自己的三态", "三态词表（readers.TRI_ 那三个）的个数", _tri_count,
          pin="三态"),
    Claim("台账写入笔数与 commit 标记两格", "LedgerReading 的 upserts/commit_markers",
          _ledger_pair),
    Claim("不并进前两格", "RosterInbox 的 unread/seen_not_acked", _unread_pair),
    Claim("台账文件不在盘上时两格都是", "LedgerReading 的 upserts/commit_markers",
          _ledger_pair),
    Claim("五条判据 + 五种辅助读数", "reviewaccept.CRITERIA 的条数", _criteria, pin="五条"),
    Claim("五条判据 + 五种辅助读数", "reviewaccept.AUXILIARY_SIGNALS 的条数", _auxiliary,
          pin="五种"),
    Claim("（第三档是没查成，不是通过）", "reviewaccept 里 pass/fail/unknown 三档",
          _verdict_words),
    Claim("unknown（第三档 = 没查成，不是通过", "reviewaccept 里 pass/fail/unknown 三档",
          _verdict_words),
    Claim("「有」/「没有」/「没查成」三档", "在飞面 answer 的三档（stopctl + live_face）",
          _live_answer_tiers),
    Claim("模型接线、设置三段", "Machine.tsx 里 part 三种（toolchain/model/workspace）",
          _settings_parts),
    Claim("unreadable / not_applicable 两档的计数栏是 null",
          "三态里计数栏为 null 的那两档", _tri_null_tiers),
    Claim("八条 POST 全在路由表里", "writes.ROUTES 里的 POST 条数", _post_routes),
    Claim("写面现状：八条 POST 已全部接线", "writes.ROUTES 里的 POST 条数", _post_routes),
    Claim("下那七条写端点", "writes.ROUTES 里 /api/ 下的 POST 条数", _api_post_routes,
          pin="七条"),
    Claim("授权次序是四层", "writes.authorize 的四层", _auth_layers, pin="四层"),
    Claim("这四层管的是", "writes.authorize 的四层", _auth_layers, pin="四层"),
    Claim("收件箱三格", "RosterInbox 的三个计数键", _inbox_tiers),
    Claim("三格分开给", "RosterInbox 的三个计数键", _inbox_tiers),
    Claim("点开节点另给三格", "RosterInbox 的三个计数键", _inbox_tiers),
    Claim("一个节点最多列 10 条", "readers.ROSTER_INBOX_ITEMS", _inbox_items),
    Claim("正文截到 160 字", "readers.ROSTER_INBOX_CLIP", _inbox_clip),
    Claim("节点上限 500（ROSTER_NODES_MAX）", "readers.ROSTER_NODES_MAX", _nodes_max,
          expected=500),
    Claim("三个数摆在一起", "RosterCoverage 的三个键", _coverage_numbers),
    Claim("容易读混的六格读数", "那张卡里 <b> 小标题的个数", _six_cells),
    Claim("待答两处同一个数", "Home.tsx 里写全局待答清单的处数", _pending_places),
    Claim("两种「条数」不是一回事", "SessionRow.events_seen 与 LedgerReading.upserts",
          _two_counts),
    Claim("两个数并排摆着", "SessionRow.events_seen 与 LedgerReading.upserts", _two_counts),
    Claim("另外两套词表各自独立", "交付说明与验收判据各一套三档词表", _two_vocabularies),
    Claim("报错看三处", "那一句里用「；」分出的段数", _error_places),
    Claim("退出码六档", "cli.EXIT_CODE_BY_STOP 的值集合", _exit_tiers),
    Claim("只多两档", "AUTONOMY_ONLY_EXIT_CODE 加 rounds 那一档", _autonomy_extras),
    Claim("两条独立事实", "MachineView 的 lean_enabled 与 lean_ready", _two_lean_facts),
    Claim("非平凡度 T0–T4 / 未判", "secretary.NONTRIVIALITY_LEVELS 的档数", _levels,
          expected=5),
)


def _expected_of(claim: Claim) -> int:
    """这条断言在页面上写的是几（先看表里给的，再从字面量里的"数字 + 量词"读）。"""
    if claim.expected is not None:
        return int(claim.expected)
    if claim.pin is not None:
        got = _NUMBER_ASSERTION.search(claim.pin)
        assert got is not None, f"pin 里没有数字 + 量词：{claim.pin!r}"
        value = _int_of_numerals(got.group(1))
        assert value is not None, f"读不出中文数字：{got.group(1)!r}"
        return value
    for got in _NUMBER_ASSERTION.finditer(claim.literal):
        value = _int_of_numerals(got.group(1))
        if value is None or value == 1:
            # "一个/一条" 是量词不是计数：要的是这一段里第一个真计数。
            continue
        return value
    raise AssertionError(f"这一条既没给 pin / expected，也没有可读的计数：{claim.literal!r}")


def _number_problems(raw: str, claims: tuple[Claim, ...] = CLAIMS) -> list[str]:
    """第 1 层：每条数字断言都要在页面上、且与代码读数相等；页面上不许有没登记的数目。

    `claims` 可以换一份（反真空那一条用它打桩"代码那一侧变了"）：判据本体与表分开，
    否则"打桩"就只能靠改真文件。
    """
    plain = _plain(raw)
    squashed = _squash(plain)
    problems: list[str] = []
    for claim in claims:
        if _squash(claim.literal) not in squashed:
            problems.append(f"说明页里找不到这条断言：{claim.literal!r}"
                            f"（它在说 {claim.source}）")
            continue
        want = _expected_of(claim)
        got = int(claim.count(raw))
        if want != got:
            problems.append(
                f"数字对不上：页面写 {want}（{claim.literal!r}）而 {claim.source} 是 {got}")
    literals = [_squash(c.literal) for c in claims]
    seen: set[str] = set()
    for match in _NUMBER_ASSERTION.finditer(plain):
        token = _squash(match.group(0))
        if _int_of_numerals(match.group(1)) == 1:
            continue
        if token in seen:
            continue
        seen.add(token)
        if not any(token in literal for literal in literals):
            problems.append(f"这个数字断言没有出处（未登记到 CLAIMS）：{token!r}")
    return problems


def _exit_code_set_problems(raw: str) -> list[str]:
    """第 1 层续：页面那张退出码表写的档，必须逐值等于 `EXIT_CODE_BY_STOP` 的值集合。"""
    plain = _plain(raw)
    named = set(re.findall(r'code: "(\d+)"', raw))
    got = {str(v) for v in cli.EXIT_CODE_BY_STOP.values()}
    problems: list[str] = []
    if named != got:
        problems.append(f"退出码表对不上：页面 {sorted(named)} / EXIT_CODE_BY_STOP {sorted(got)}")
    if "没登记" not in plain or "归 1" not in plain:
        problems.append("没写「没登记的 stop_reason 一律归 1」（安全侧那一条）")
    return problems


def _tier_name_problems(raw: str) -> list[str]:
    """第 1 层续：非平凡度的档位名与"判不了"那个词，逐字来自代码而不是页面自己编。

    页面可以用区间写法（`T0–T4`）也可以逐档写出来；两种都要能把每一档说到才不算缺。
    """
    plain = _plain(raw)
    levels = [f"T{int(level)}" for level in secretary.NONTRIVIALITY_LEVELS]
    problems: list[str] = []
    missing = [label for label in levels if label not in plain]
    if missing:
        span = f"{levels[0]}–{levels[-1]}" if len(levels) > 1 else ""
        covered = bool(span) and (span in plain or span.replace("–", "-") in plain)
        if not covered:
            problems.extend(f"说明页里缺非平凡度那一档：{label}" for label in missing)
    word = readers.NONTRIVIALITY_UNJUDGED_WORD
    if word not in plain:
        problems.append(f"说明页里缺非平凡度「判不了」的写法：{word!r}")
    return problems


# ====================================================================== 2 示例命令
_PROGRAM_ONLY = (("agentflow",), ("python", "-m", "agentflow.cli"))
_PLACEHOLDERS = {
    "<工作区>": "WS",
    "<会话号>": "SID",
    "<一句话任务>": "TASK",
    "<同一句话>": "TASK2",
    "<口令>": "TOK",
}
_CMD_FIELD = re.compile(r'cmd:\s*"([^"]+)"')
_MONO = re.compile(r'<span class="mono">([^<]*)</span>')


def shlex_split(text: str) -> list[str]:
    """`shlex.split`（单独一层：示例命令里的引号要按 shell 的规矩剥）。"""
    import shlex

    return shlex.split(text, posix=True)


def _example_commands(raw: str) -> list[str]:
    """页面上的示例命令：命令表的 `cmd:` 那一格，加上正文里点名的整条命令行。"""
    out: list[str] = []
    for text in _CMD_FIELD.findall(raw):
        got = _unescape(text).strip()
        if got and got not in out:
            out.append(got)
    for text in _MONO.findall(raw):
        got = _unescape(text).strip()
        tokens = got.split()
        if not any(tuple(tokens[: len(p)]) == p for p in _PROGRAM_ONLY):
            continue
        if len(tokens) < 2 or tuple(tokens) in _PROGRAM_ONLY:
            continue
        if got not in out:
            out.append(got)
    return out


def _argv_of(command: str) -> list[str]:
    """一条示例命令 → argv（程序名那一段去掉，占位符换成实值）。"""
    text = command
    for placeholder, real in _PLACEHOLDERS.items():
        text = text.replace(placeholder, real)
    tokens = shlex_split(text)
    for prefix in _PROGRAM_ONLY:
        if tuple(tokens[: len(prefix)]) == prefix:
            return cli.canonical_argv(tokens[len(prefix):])
    return cli.canonical_argv(tokens)


def _parse(argv: list[str]) -> tuple[int, str]:
    """跑一次 `build_parser().parse_args`：`(退出码, argparse 说给用户的那一段)`。"""
    parser = cli.build_parser()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0), buf.getvalue().strip()
    return 0, buf.getvalue().strip()


def _command_problems(raw: str) -> list[str]:
    """第 2 层：每条示例命令都必须被 `build_parser()` 解析（失败即红，并原样给 argparse 的话）。"""
    problems: list[str] = []
    for command in _example_commands(raw):
        code, why = _parse(_argv_of(command))
        if code != 0:
            problems.append(f"这条示例命令解析不了（退出码 {code}）：{command}"
                            f" —— {why or '（argparse 没说话）'}")
    return problems


def _root_position_problems(raw: str) -> list[str]:
    """第 2 层续：页面那句"`--root` 必须写在 web 之前，写在后面会被拒且退出码 2"要真的成立。

    两面都核：写在前面能解析；写在后面必须是"拒绝 + 退出码 2 + unrecognized arguments"。
    页面文案与真实行为绑在一起 —— 哪天 `web` 自己也收了 `--root`，这里会红。
    """
    plain = _plain(raw)
    squashed = _squash(plain)
    problems: list[str] = []
    if _squash("--root 是全局参数，必须写在 web 之前") not in squashed:
        problems.append("说明页里缺「--root 是全局参数，必须写在 web 之前」那一句")
    if "退出码 2" not in plain:
        problems.append("说明页里缺「写在后面会被拒、退出码 2」那一句")
    good, _why = _parse(["--root", "WS", "web"])
    if good != 0:
        problems.append(f"`--root WS web` 竟然解析不了（退出码 {good}）")
    bad, why = _parse(["--root", "WS", "web", "--root", "WS"])
    if bad != 2:
        problems.append(f"`web --root` 的退出码变了：现在 {bad}（页面写的是 2）")
    if "unrecognized arguments" not in why:
        problems.append(f"`web --root` 的拒绝话术变了：{why!r}（页面写的是 argparse 会拒）")
    return problems


# ====================================================================== 3 键名
@dataclass(frozen=True)
class FieldClaim:
    """页面点名的一个键，以及它该在哪个接口的声明里。"""

    name: str
    module: str
    interface: str
    #: 这个键是不是那个接口的顶层键（是的话还要在真读到的返回值里出现）。
    top: bool = False


FIELD_CLAIMS: tuple[FieldClaim, ...] = (
    FieldClaim("pending_questions", "state", "StateSnapshot", True),
    FieldClaim("events_seen", "state", "SessionRow"),
    FieldClaim("upserts", "state", "LedgerReading"),
    FieldClaim("answer", "readers", "RosterView", True),
    FieldClaim("count", "readers", "RosterView", True),
    FieldClaim("truncated", "readers", "RosterView", True),
    FieldClaim("task_id", "readers", "RosterNode"),
    FieldClaim("name", "readers", "RosterNode"),
    FieldClaim("depth", "readers", "RosterNode"),
    FieldClaim("parent_task_id", "readers", "RosterNode"),
    FieldClaim("inbox", "readers", "RosterNode"),
    FieldClaim("unread", "readers", "RosterInbox"),
    FieldClaim("seen_not_acked", "readers", "RosterInbox"),
    FieldClaim("open_total", "readers", "RosterInbox"),
    FieldClaim("more", "readers", "RosterInbox"),
    FieldClaim("item_state", "readers", "TaskRow"),
    FieldClaim("total_usd", "readers", "BudgetView", True),
    FieldClaim("added", "readers", "BudgetView", True),
    FieldClaim("source", "readers", "BudgetView", True),
    FieldClaim("lean_enabled", "readers", "MachineView", True),
    FieldClaim("lean_ready", "readers", "MachineView", True),
)

#: 页面点名但不是"读到器的键"的那几个名字（各有自己的出处，故单列）。
NON_FIELD_NAMES: dict[str, str] = {
    "cap_usd": "验收端点的查询参数（GET /api/acceptance?cap_usd=），不是读模型的键",
    "stop_reason": "agent_loop 的运行记录字段（cli.EXIT_CODE_BY_STOP 就是按它归的档）",
    "usage_ledger": "台账表名（TokenMeter 的累计账落点），不是某个读模型的键",
}


def _bit_name_problems(raw: str) -> list[str]:
    """「五元位五位各叫什么」：页面上的五个名字必须逐字等于 `BIT_NAMES`（连顺序）。"""
    plain = _plain(raw)
    head = "五元位五位各一格"
    if head not in plain:
        return [f"说明页里找不到「{head}」那一段"]
    window = plain[plain.index(head):]
    if "）" in window:
        window = window[: window.index("）") + 1]
    problems: list[str] = []
    positions: list[tuple[int, str]] = []
    for name in EB.BIT_NAMES:
        at = window.find(name)
        if at < 0:
            problems.append(f"五位里缺 {name!r}（BIT_NAMES 里有它）")
            continue
        positions.append((at, name))
    if [n for _at, n in sorted(positions)] != [n for _at, n in positions]:
        problems.append(f"五位的顺序与 BIT_NAMES 不一致：{positions}")
    return problems


def _enum_problems(raw: str) -> list[str]:
    """第 3 层续：页面点名的枚举值必须是那个词表里的真值。"""
    plain = _plain(raw)
    problems: list[str] = []
    if "no_evidence" in plain and "no_evidence" not in EB.QUOTE_STATES:
        problems.append("引文回验那一档 no_evidence 不在 QUOTE_STATES 里")
    for name in ("computed", "unreadable", "not_applicable"):
        if name in plain and name not in _tri_words():
            problems.append(f"三态词 {name!r} 不在 readers 的三态词表里")
    return problems


#: 页面里长得像蛇形键名的那些段（`a_b` 形态）必须能在契约里找到。
_SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")


def _all_declared() -> set[str]:
    """契约里出现过的键名，加上几个词表取值与单列的名字（`no_evidence` 是取值不是键）。"""
    got: set[str] = set()
    for table in (readers._TS_TYPES, state_mod._TS_TYPES):
        for _name, _source, fields in table:
            got |= {f[0] for f in fields}
    got |= set(EB.QUOTE_STATES) | set(EB.BIT_STATES) | set(EB.FORMAL_PATH_STATES)
    got |= set(_tri_words())
    got |= set(NON_FIELD_NAMES)
    return got


def _field_problems(raw: str) -> list[str]:
    """第 3 层：页面点名的键都在对应接口的声明里；没登记的蛇形键名即红。"""
    plain = _plain(raw)
    squashed = _squash(plain)
    problems: list[str] = []
    for claim in FIELD_CLAIMS:
        declared = _declared(claim.module, claim.interface)
        if claim.name not in declared:
            problems.append(f"{claim.interface} 里没有 {claim.name!r} 这个键了（页面还在说它）")
        if claim.name not in squashed:
            problems.append(f"说明页里不再点名 {claim.name!r} 了（它该在 {claim.interface} 里）")
    for token in _SNAKE.findall(plain):
        if token not in _all_declared():
            problems.append(f"说明页点了一个契约里没有的键名：{token!r}")
    return problems


def _live_face(interface: str) -> dict:
    """那个接口对应的读口，在一个空工作区上现读一次（只写临时目录，不碰真工作区）。"""
    root = pathlib.Path(tempfile.mkdtemp(prefix="dsh-help-claims-"))
    got = {
        "StateSnapshot": state_mod.snapshot,
        "RosterView": readers.roster_face,
        "BudgetView": readers.budget_face,
        "MachineView": readers.machine_face,
    }[interface](root)
    assert isinstance(got, dict), f"{interface} 的读口没有返回字典"
    return got


def _live_problems(raw: str) -> list[str]:
    """第 3 层续：标了 top 的键，还要在真读到的返回值里出现（声明与返回值不许分家）。"""
    problems: list[str] = []
    faces: dict[str, dict] = {}
    for claim in FIELD_CLAIMS:
        if not claim.top:
            continue
        if claim.interface not in faces:
            faces[claim.interface] = _live_face(claim.interface)
        if claim.name not in faces[claim.interface]:
            problems.append(f"{claim.interface} 真读出来的键里没有 {claim.name!r}")
    return problems


# ====================================================================== 正控（真文件）
def test_every_number_on_the_help_page_traces_to_the_code() -> None:
    """第 1 层：页面每个数字断言都能追到一处现算读数，且两边的数相等。"""
    raw = HELP.read_text(encoding="utf-8")
    problems = _number_problems(raw) + _exit_code_set_problems(raw) + _tier_name_problems(raw)
    assert problems == [], problems
    # 反真空：表本身不许退化成空壳（否则"每条都对上了"是空话）。
    assert len(CLAIMS) >= 40, len(CLAIMS)
    tokens = {_squash(m.group(0)) for m in _NUMBER_ASSERTION.finditer(_plain(raw))}
    assert len(tokens) >= 20, sorted(tokens)


def test_every_example_command_on_the_help_page_parses() -> None:
    """第 2 层：每条示例命令都能被 `build_parser()` 解析；`--root` 那句抱怨与真实行为同源。"""
    raw = HELP.read_text(encoding="utf-8")
    problems = _command_problems(raw) + _root_position_problems(raw)
    assert problems == [], problems
    commands = _example_commands(raw)
    # 反真空：这一页真在给命令（不是"一条都没解析，所以都过了"）。
    assert len(commands) >= 15, commands
    assert any("--root" in c for c in commands), commands


def test_every_field_named_on_the_help_page_is_declared() -> None:
    """第 3 层：页面点名的每个键都在对应接口的声明里（顶层键还要在真读到的返回值里）。"""
    raw = HELP.read_text(encoding="utf-8")
    problems = (_field_problems(raw) + _live_problems(raw)
                + _bit_name_problems(raw) + _enum_problems(raw))
    assert problems == [], problems
    assert len(FIELD_CLAIMS) >= 20, len(FIELD_CLAIMS)


# ====================================================================== 4 反真空
def test_wrong_numbers_wrong_commands_and_wrong_keys_all_turn_red() -> None:
    """第 4 层：把页面改坏三处（数字 / 子命令 / 键名）⇒ 前三层各自红。"""
    raw = HELP.read_text(encoding="utf-8")

    # 前提：改前是绿的（否则下面的负控可能只是"本来就红"）。
    assert _number_problems(raw) == []
    assert _command_problems(raw) == []
    assert _field_problems(raw) == []

    # 一 把一张卡的数字改错 ⇒ 数字那一层必红。
    wrong_number = raw.replace("九张卡", "八张卡", 1)
    assert wrong_number != raw, "负控没改到东西（页面里没有九张卡那一段）"
    got = _number_problems(wrong_number)
    assert got, "把卡数改错，判据却一声不吭"
    assert any("九张卡" in p for p in got), got
    assert any("没有出处" in p for p in got), got

    # 一-b 反方向：代码那一侧变了而页面没改 ⇒ 也要红（这里打桩那个计数，不动真代码）。
    stubbed = tuple(
        Claim(c.literal, c.source, (lambda _raw: 99), c.pin, c.expected)
        if c.literal.startswith("九张卡") else c
        for c in CLAIMS)
    got = _number_problems(raw, stubbed)
    assert any("数字对不上" in p for p in got), got

    # 一-c 加一个没人核的数目 ⇒ 覆盖性那一半必红。
    invented = raw.replace("七栏各带自己的三态", "七栏各带自己的三态、共 11 项", 1)
    assert any("没有出处" in p for p in _number_problems(invented)), (
        "新加的数字没人核，判据却一声不吭")

    # 二 把一条命令改成不存在的子命令 ⇒ 命令那一层必红。
    wrong_cmd = raw.replace("agentflow --root <工作区> verify",
                            "agentflow --root <工作区> nosuchverb", 1)
    assert wrong_cmd != raw, "负控没改到东西（页面里没有那条 verify 示例）"
    got = _command_problems(wrong_cmd)
    assert got and "nosuchverb" in got[0], got

    # 二-b 把 `--root` 那句抱怨改掉 ⇒ 文案与实行为了分家，必红。
    wrong_exit = raw.replace("必须写在 web 之前", "写在哪都行", 1)
    assert any("web 之前" in p for p in _root_position_problems(wrong_exit)), (
        "--root 那句抱怨被改掉了，判据却一声不吭")

    # 三 把点名的键名改歪 ⇒ 键名那一层必红。
    wrong_key = raw.replace("open_total", "open_totl")
    assert wrong_key != raw, "负控没改到东西（页面里没有 open_total 那一段）"
    got = _field_problems(wrong_key)
    assert got, "键名改歪了，判据却一声不吭"
    assert any("open_totl" in p for p in got), got
