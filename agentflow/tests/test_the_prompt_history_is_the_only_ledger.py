# -*- coding: utf-8 -*-
"""判据：提示词版本账只有一个家，且它的末节标题就是当前的 `PROMPT_VERSION`。

## 背景（这一条补的是 F-5）

`agent_prompts.py` 里原先躺着 2,879 行按序追加的版本账（`#: p38 —— …` 起，每抬一格
`pNNN` 追加一段）。它不是代码、只有一个语义单元（"按序追加"），却有两个后果：

1. 那个文件永远出不了「`>800` 行」的体量软基线；而按年代把它切成几块，正是
   `draft/190` §0 明令禁止的"按体量切"（切的位置由体量决定，不是由语义决定）。
2. 它此前一条判据都没有：漏写一段、写错一格、把两版合成一段，都不会红。
   本仓对其它台账（`STEP_VOLATILE_FACTS` 账本、提案台账、签台账）都有判据，
   只有这一份没有 —— 这就是 F-5 那条"静默面"。

2026-11-20 按业主口径（方案 C）整块逐字节搬进 `docs/PROMPT-HISTORY.md`：
账不是代码、与任何代码单元都没有调用边，搬的是文件位置，不是把语义单元切开。
这一条判据接管原来那条"地址约定"（~15 处注释按"`PROMPT_VERSION` 上方那一格"引用它），
并把"人记得追加"换成机器检查。

## 这一条钉住什么

1. 源码里一段不留：`src/agentflow/agent_prompts.py` 里不许再出现版本账的段头
   （行首 `#: pNNN`）—— 搬回去就红。
2. 账必须读得到：`docs/PROMPT-HISTORY.md` 存在、且读得到段头。读不到是"没查成"，
   不许折成"源码里没有历史段落"（三态纪律：没检查 ≠ 检查过了没问题）。
3. 末节标题 == `PROMPT_VERSION`：抬了版本而账末没有新的一段 ⇒ 红；账末多了一段而
   版本没抬 ⇒ 也红（版本号是那一版的名字，账末是它的落点，两件事必须同笔）。

判据只认账末那一节：前面的老段是历史，写错一个字不该让今天变红（那是"改历史"，
归 review 管）；今天能不能红得住，全看"下一次抬版本有没有落账"。

## 反真空（这一条自己也承重）

四条"该红"的形态各喂一次真文本（不是造的针）：

1. 把账搬回 `agent_prompts.py`（真源码 + 真账拼起来）；
2. 把末节标题改错一格（在真账文本上改段头）；
3. 账被清空（空文档同样满足"末节标题 == `PROMPT_VERSION`"这句话，所以必须单独判）；
4. 账文档不存在（"读不到"与"没有历史段落"必须分得开）。

## 边界

本文件只读盘（`src/` 与 `docs/` 一个字节都不写、不改 `PROMPT_VERSION`、不动 golden）。
"""
from __future__ import annotations

import pathlib
import re

from agentflow import agent_prompts as AP

PROJECT = pathlib.Path(__file__).resolve().parents[1]

#: 版本账的唯一落点（2026-11-20 从 `src/agentflow/agent_prompts.py` 的第 31–2,909 行
#: 逐字节搬出，共 2,879 行；核对读数见 `temp/prompthist/REPORT.md`）。
HISTORY_DOC = PROJECT / "docs" / "PROMPT-HISTORY.md"
#: 账原来的家：现在里面一段历史都不许留。
PROMPTS_SOURCE = PROJECT / "src" / "agentflow" / "agent_prompts.py"

#: 版本账里"这一段记的是哪个 p 号"的行首。只认行首一格 `#: p`：
#: 段头一律写成一格（`#: pNNN` / `#: pA → pB（…`），段内的续行是两格以上（`#:   …`）
#: —— 那是账自己的体例，不是这里另立的规矩（`#:   p298 同值）…` 那种续行就是靠
#: 一格/两格分开的，放宽成 `\s*` 会把续行读成段头，末节就会指错）。
_LEDGER_HEADING = re.compile(r"^#: p(?P<start>\d+)(?:\s*→\s*p(?P<end>\d+))?", re.MULTILINE)

#: 反真空下限：账今天有 98 个段头（只增不减）。读到远少于这个数 ⇒ 账被截了、
#: 或者段头格式变了（格式一变，"末节"就会指到老段上去，必须当场红而不是静默）。
_MIN_SECTIONS = 90


def _headings(text: str) -> list[re.Match[str]]:
    """账里的全部段头（行首一格 `#: pNNN`），按出现顺序。"""
    return list(_LEDGER_HEADING.finditer(text))


def _section_version(match: re.Match[str]) -> int:
    """一个段头记的版本号（`pA → pB` 取 B：那一节讲的是搬到 B 这一版）。"""
    return int(match.group("end") or match.group("start"))


def _ledger_problems(source: str, history: str | None, version: str) -> list[str]:
    """版本账的两件事（空列表 = 都成立）。纯函数：喂替身进来就能给两端做反负控。

    ① `agent_prompts.py` 里不许再留着历史段落；
    ② 账文档读得到、且末节标题 == `version`（`pA → pB` 取 B）。
    """
    bad: list[str] = []
    left = len(_headings(source))
    if left:
        bad.append(
            f"`src/agentflow/agent_prompts.py` 里还有 {left} 个版本账段头（行首 `#: pNNN`）⇒ "
            "账只许活在 `docs/PROMPT-HISTORY.md`：搬回去等于把 2,879 行历史重新塞进提示词装配"
            "文件（那个文件因此出不了 `>800` 行的体量软基线，而按年代切是 `draft/190` §0 "
            "禁的按体量切）")
    if history is None:
        bad.append(
            "`docs/PROMPT-HISTORY.md` 读不到 ⇒ 版本账没有落点"
            "（`agent_prompts.py` 里没有历史段落这句话，这时是没查成，不是查过了）")
        return bad
    heads = _headings(history)
    if not heads:
        bad.append(
            "`docs/PROMPT-HISTORY.md` 里一个段头（行首 `#: pNNN`）都没读到 ⇒ 账被清空了"
            "（空文档同样满足「末节标题 == PROMPT_VERSION」，所以这一格必须单独判）")
        return bad
    last = _section_version(heads[-1])
    if f"p{last}" != version:
        bad.append(
            f"版本账末节标题是 `p{last}`，而 `PROMPT_VERSION` 是 {version!r} ⇒ "
            "抬了版本没在账末追加一段，或者追加了没抬版本；这两件事必须在同一个 commit 里"
            "（判据只看账末那一节：前面的老段是历史，只读不判）")
    return bad


def test_the_ledger_lives_in_its_own_document_and_ends_at_the_current_version() -> None:
    """正控：账在 `docs/PROMPT-HISTORY.md`、源码里一段不留、末节标题 == 当前版本。"""
    source = PROMPTS_SOURCE.read_text(encoding="utf-8")
    history = HISTORY_DOC.read_text(encoding="utf-8") if HISTORY_DOC.exists() else None

    problems = _ledger_problems(source, history, AP.PROMPT_VERSION)
    assert problems == [], "\n".join(problems)

    # 这一条自己也要承重：账真的是一整块（不是"只剩末节那一段"也算绿）
    assert history is not None
    heads = _headings(history)
    assert len(heads) >= _MIN_SECTIONS, (
        f"`docs/PROMPT-HISTORY.md` 里只读到 {len(heads)} 个段头（应当 ≥ {_MIN_SECTIONS}）⇒ "
        "要么账被截掉了一段，要么段头格式变了（段头必须是行首一格 `#: pNNN`，"
        "判据按这个格式认「末节」）")


def test_the_ledger_checks_bite_on_every_broken_shape() -> None:
    """反真空：四种"该红"的形态各喂一次真文本，每一种都必须报出来。"""
    source = PROMPTS_SOURCE.read_text(encoding="utf-8")
    history = HISTORY_DOC.read_text(encoding="utf-8")
    version = AP.PROMPT_VERSION

    # 前提（0）：现状是绿的（否则下面几条"报了东西"可能只是它本来就红）
    assert _ledger_problems(source, history, version) == [], \
        "前提不成立：现状已经红了，下面四条反真空证明不了什么"

    # ① 把账搬回 `agent_prompts.py` ⇒ 必红（拼的是两份真文本，不是合成的针）
    back = _ledger_problems(source + "\n" + history, history, version)
    assert back, "反真空失效：账搬回了源码文件，判据却放过了"
    assert "还有" in back[0], back[0]

    # ② 把末节标题改错一格 ⇒ 必红
    last = _headings(history)[-1]
    doctored = (history[:last.start()]
                + re.sub(r"p\d+$", f"p{_section_version(last) + 1}", last.group(0))
                + history[last.end():])
    assert doctored != history, "探针没改到账末的段头 ⇒ 这条反真空是空转"
    assert _ledger_problems(source, doctored, version), \
        "反真空失效：末节标题改错了一格，判据却放过了"

    # ③ 账被清空 ⇒ 必红（空文档同样"末节对得上"，这一条专门钉它）
    assert _ledger_problems(source, "", version), \
        "反真空失效：账清空之后判据仍然绿"

    # ④ 账文档读不到 ⇒ 必红（"读不到"不许折成"没有历史段落"）
    assert _ledger_problems(source, None, version), \
        "反真空失效：读不到账文档，判据却当成没事"
