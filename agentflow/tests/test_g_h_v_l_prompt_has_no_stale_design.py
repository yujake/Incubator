# -*- coding: utf-8 -*-
"""G / H / V / L ＋公共段：过时硬伤的判据（2026-10-25 审计清单）。

这一份守的是"提示词/文案说的事，与代码里真有的那一件是不是同一件"。形态与
`tests/test_m_prompt_has_no_stale_design.py` 同源：每条硬伤有一个纯检查函数
（吃一份语料、吐问题清单），正控断言"今天的树干净"，负控拿改前那段原文喂同一个
函数、断言它必红 —— 只断言"今天没有那句话"无法区分"真修了"与"那句话被删光了"。

语料两类：
- 渲染出来的提示词（H / V / G / M 四份）—— 判据优先读这个（模型看到的就是它）；
- 源码文本（`specs/*.py` / `agent_prompts.py` / `evidencebits.py` / `agent_loop.py` /
  `agent_skills.py` / `papermapping.py` / `agent_l/_support.py`）—— 渲染不出来的那些
  （L 关着时不存在、关档文案、扫描面常量）只能扫源码。

零模型：不联网、不起子进程跑模型、不写工作区。
"""
from __future__ import annotations

import pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import evidencebits as EB
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.agent_l import _support as LSP
from agentflow.tools import build_registry

#: 本仓源码根（失败信息里的 `文件:行` 用它拼）。
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 渲染语料里的那几个角色（H / V 是被审计的只读角色，G / M 是同一段共享文案的另两个读者）。
PROMPT_ROLES: tuple[str, ...] = ("H", "V", "G", "M")

#: 扫源码的那几个文件（相对 `src/agentflow/`）。
SOURCE_FILES: tuple[str, ...] = (
    "agent_prompts.py", "agent_loop.py", "agent_skills.py", "evidencebits.py",
    "papermapping.py", "agent_l/_support.py",
    "specs/h.py", "specs/g.py", "specs/v.py", "specs/l.py",
)

TASK = "把这一条链路走一遍"
ROOT = "D:/x"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _line_of(rel: str, needle: str) -> int:
    """`needle` 在 `rel` 里第一次出现的行号（1 起；找不到返回 0）。"""
    for number, line in enumerate(_read(rel).split("\n"), start=1):
        if needle in line:
            return number
    return 0


def _at(rel: str, needle: str = "") -> str:
    """失败信息里的位置：`specs/h.py:117`（找不到 needle 时只给文件）。"""
    number = _line_of(rel, needle) if needle else 0
    return f"{rel}:{number}" if number else rel


@dataclass(frozen=True)
class Corpus:
    """判据吃的那一份语料：渲染出来的提示词 + 源码文本。"""

    prompts: Mapping[str, str]
    files: Mapping[str, str] = field(default_factory=dict)

    def prompt(self, role: str) -> str:
        return str(self.prompts.get(role) or "")

    def file(self, rel: str) -> str:
        return str(self.files.get(rel) or "")

    def replaced(self, *, role: str = "", old: str = "", new: str = "",
                 rel: str = "") -> "Corpus":
        """造一份"某个位置改回改前那个写法"的语料（负控用）。"""
        prompts = dict(self.prompts)
        files = dict(self.files)
        if role:
            assert old in prompts.get(role, ""), (
                f"负控自己写错了：{role} 的提示词里没有 {old!r} ⇒ 这一条负控是真空的")
            prompts[role] = prompts[role].replace(old, new, 1)
        if rel:
            assert old in files.get(rel, ""), (
                f"负控自己写错了：{rel} 里没有 {old!r} ⇒ 这一条负控是真空的")
            files[rel] = files[rel].replace(old, new, 1)
        return Corpus(prompts=prompts, files=files)


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    """渲染 H / V / G / M 四份提示词，并把要扫的源码读进来（只做一次）。

    渲染前把 Lean 开关「明确按关闭」那一档钉住（`os.environ` 直接写、进出各清一次
    `agent_prompts` 的读数缓存）：这一份语料判的是"关档也在渲染"的那些共享段，
    让它随外部的开关值漂，判据就会"有时红有时绿"。
    """
    import os

    from agentflow import settings as SET

    saved = os.environ.get(SET.ENV_LEAN_ENABLED)
    os.environ[SET.ENV_LEAN_ENABLED] = "0"
    AP.reset_toolchain_readings()
    try:
        registry = build_registry().registry
        prompts = {role: AP.system_prompt(role, registry=registry, task=TASK,
                                          workspace_root=ROOT)
                   for role in PROMPT_ROLES}
    finally:
        if saved is None:
            os.environ.pop(SET.ENV_LEAN_ENABLED, None)
        else:
            os.environ[SET.ENV_LEAN_ENABLED] = saved
        AP.reset_toolchain_readings()
    return Corpus(prompts=prompts, files={rel: _read(rel) for rel in SOURCE_FILES})


def _control_chars(text: str) -> str:
    """一份文本里的控制字符（除换行之外的 Cc 类；`⏎` 也在此类）。"""
    bad = []
    for ch in text:
        if ch == "\n":
            continue
        if ch == "\ufffd" or unicodedata.category(ch) == "Cc":
            bad.append(f"U+{ord(ch):04X}")
    return "、".join(sorted(set(bad)))


# ============================================================ ① H 被要求写正文


def check_1(t: Corpus) -> list[str]:
    """① 正文只由 G 写；H（与 M）读正文与回执，然后核对、落 finding。

    射程只到"正文"那一件事：M 用 `fs.write` 写自己的交付说明（`out/review/REPORT.md`）
    是它面上真有的工具，不在这一条里 —— 这一条管的是"正文由谁写、PDF 由谁编"。
    """
    out: list[str] = []
    for role in ("H", "M"):
        text = t.prompt(role)
        if "正文由你写" in text:
            out.append(f"[①] {role} 的提示词里还写着「正文由你写」"
                       f"（{_at('agent_prompts.py', '一、交付物是什么')} 那一段）")
        if "正文由 G 写" not in text:
            out.append(f"[①] {role} 的提示词里找不到「正文由 G 写」⇒ 这一段没说清谁写")
        for index, line in enumerate(text.split("\n"), start=1):
            about_body = "main.tex" in line or "正文" in line
            writes = "fs.write" in line or "doc.paper_compile" in line
            if about_body and writes and "G" not in line:
                out.append(f"[①] {role} 的提示词第 {index} 行把正文的 `fs.write` / "
                           f"`doc.paper_compile` 派给了读的人（那一件不在 H / M 的面上）："
                           f"{line.strip()[:80]}")
        if "你不写正文" not in text and "写与编都不是" not in text:
            out.append(f"[①] {role} 的提示词里没有一句说清「写与编不是你的动作」"
                       f"（{_at('agent_prompts.py', '正文由 G 写')}）")
    return out


# ============================================================ ② 销号入口


def check_2(t: Corpus) -> list[str]:
    """② 销号两个入口落到同一处（秘书）；只读角色只有 `retire` 形那一档。

    射程是"销号这件事"的说法，不是"凡出现 `retire_child` 那几个字"：`conductor.ack`
    的工具摘要里也点了它（"板没清干净时会拒"），那是 ack 自己的语义、不在这一条里；
    H 自己 policy 里那句"裁决 `rejected` 的唯一入口"也无关（它讲的是裁决）。
    """
    stale = (
        "销号只有一个入口",
        "这一形是**旧路**",
        "旧路 —— 销号走 `conductor.retire_child`",
    )
    out: list[str] = []
    for role in ("H", "V"):
        text = t.prompt(role)
        for phrase in stale:
            if phrase in text:
                out.append(f"[②] {role} 的提示词里还留着「{phrase}」"
                           f"（{_at('agent_prompts.py', '让一个子代理退役')}）")
        if "两个入口落到" not in text or "同一处" not in text:
            out.append(f"[②] {role} 的提示词里没有说清「两个入口落到同一处（秘书）」"
                       f"（{_at('agent_prompts.py', '销号是父的决定')}）")
        if "conductor.retire_child" not in text:
            out.append(f"[②] {role} 的提示词里找不到 `conductor.retire_child` "
                       f"⇒ 那一段被删光了，不是修好了")
        if '{"retire"' not in text:
            out.append(f"[②] {role} 的提示词里没有 `retire` 形（只读角色只剩那一档）")
        if "只读" not in text:
            out.append(f"[②] {role} 的提示词里没提「只读角色只有形那一档」")
    return out


# ============================================================ ③ verifications 是文件


def check_3(t: Corpus) -> list[str]:
    """③ 审过凭据是 `verifications/<命题号>.jsonl` 文件账本，不是一张表。"""
    out: list[str] = []
    for role in ("H", "G", "M"):
        text = t.prompt(role)
        if "`verifications` 表" in text:
            out.append(f"[③] {role} 的提示词里还写着「结论落 `verifications` 表」"
                       f"（{_at('agent_prompts.py', 'proof_text`（含假设')}）")
        if "verifications/<命题号>.jsonl" not in text:
            out.append(f"[③] {role} 的提示词里找不到 `verifications/<命题号>.jsonl`")
    return out


# ============================================================ ④ lean_file 三处落点


def check_4(t: Corpus, *, dirs: Any = None, state_fn: Any = None) -> list[str]:
    """④ `lean_file` 的落点、L 的落点、扫描面三处说同一件事。"""
    out: list[str] = []
    scanned = tuple(PM.LEAN_ARTIFACT_DIRS if dirs is None else dirs)
    if LSP.FORMAL_DIR not in scanned:
        out.append(f"[④] L 的落点 {LSP.FORMAL_DIR!r} 不在扫描面里：{scanned} "
                   f"（{_at('papermapping.py', 'LEAN_ARTIFACT_DIRS')}）")
    resolve = getattr(PM, "_lean_source_state", None) if state_fn is None else state_fn
    if resolve is None:
        out.append("[④] papermapping 没有 `_lean_source_state` ⇒ `lean_file` 只认一个根"
                   f"（{_at('papermapping.py', 'LEAN_ARTIFACT_DIRS')}）")
    spec_g = t.file("specs/g.py")
    if LSP.FORMAL_DIR not in spec_g:
        out.append(f"[④] G 的文案里没出现 {LSP.FORMAL_DIR!r}（它正在讲 `lean_file` 怎么写）："
                   f"{_at('specs/g.py', 'lean_file')}")
    if "项目根相对路径" not in spec_g:
        out.append(f"[④] G 的文案没写清 `lean_file` 是项目根相对路径"
                   f"（{_at('specs/g.py', 'lean_file')}）")
    return out


# ============================================================ ⑤ 派活不写 action


def check_5(t: Corpus) -> list[str]:
    """⑤ 主控派 H 审稿：`task` 说清审哪一份，`params` 里给 `doc_id`。"""
    out: list[str] = []
    text = t.prompt("H")
    if "action=review" in text:
        out.append(f"[⑤] H 的提示词里还写着「写 `action=review`」"
                   f"（{_at('specs/h.py', '落 findings 的写有两处入口')}）")
    if "`params` 里给 `doc_id`" not in text:
        out.append(f"[⑤] H 的提示词里没有「`params` 里给 `doc_id`」这一句"
                   f"（{_at('specs/h.py', '`review` 动作')}）")
    return out


# ============================================================ ⑥ 验收表 kind 不是八格


def check_6(t: Corpus) -> list[str]:
    """⑥ `review_files` / `reviewed_current_rows` 是验收表 kind，不是收工门八格。"""
    out: list[str] = []
    text = t.prompt("H")
    for kind in ("review_files", "reviewed_current_rows"):
        if f"收工门那一档 `{kind}`" in text or f"收工门的 `{kind}`" in text:
            out.append(f"[⑥] H 的提示词里仍把 `{kind}` 说成收工门那一档"
                       f"（{_at('specs/h.py', kind)}）")
        if f"kind={kind}" not in text:
            out.append(f"[⑥] H 的提示词里没有「`kind={kind}` 那一行」这个说法")
    if "验收表没声明这一行" not in text and "验收表里没声明这一行" not in text:
        out.append("[⑥] H 的提示词里没有「没声明 ⇒ 这一档没有读数」那半句")
    return out


# ============================================================ ⑦ review_report 必填


def check_7(t: Corpus, *, action_required: Any = None,
            tool_required: Any = None) -> list[str]:
    """⑦ 动作面与工具面的必填是同一句话（`doc_id` + `own_errors`）。"""
    spec = C.find_action("H", "review_report")
    if spec is None:
        return ["[⑦] 能力表里没有 H.review_report"]
    from agentflow.tools import review_tools as RT

    cap = ({str(x) for x in (spec.params.get("required") or ())}
           if action_required is None else set(action_required))
    tool_spec = RT._review_report_tool.__tool_spec__
    face = ({str(x) for x in (tool_spec.params.get("required") or ())}
            if tool_required is None else set(tool_required))
    out: list[str] = []
    if "own_errors" not in cap:
        out.append(f"[⑦] 动作面的必填 {sorted(cap)} 里没有 `own_errors`"
                   f"（{_at('specs/h.py', 'review_report')}）—— 照它派活必被工具层退回")
    if cap != face:
        out.append(f"[⑦] 两层必填不一致：动作面 {sorted(cap)} vs 工具面 {sorted(face)}"
                   f"（工具面在 {_at('tools/review_tools.py', 'own_errors')}）")
    return out


# ============================================================ ⑧ compose_claim 没有 page_range


def check_8(t: Corpus, *, skill_text: str = "") -> list[str]:
    """⑧ `page_range` 不是 `doc.compose_claim` 的参数（手册里那半句已删）。"""
    from agentflow.tools import doc_tools as DT

    props = set((DT._doc_compose_claim.__tool_spec__.params.get("properties") or {}).keys())
    if "page_range" in props:
        return ["[⑧] 前提变了：`doc.compose_claim` 现在真有 `page_range` ⇒ 这一条要重写"]
    body = t.file("agent_skills.py") if not skill_text else skill_text
    out: list[str] = []
    for index, line in enumerate(body.split("\n"), start=1):
        if "compose_claim" in line and "page_range" in line:
            out.append(f"[⑧] 手册正文第 {index} 行还说 `compose_claim` 有 `page_range`："
                       f"{line.strip()[:80]}（{_at('agent_skills.py', '同一个键在不同工具里')}）")
    if "register_statement" not in body or "page_range" not in body:
        out.append("[⑧] 手册里 `page_range` 那一条整段不见了（不是删了半句，是删光了）")
    return out


# ============================================================ ⑨ 骨架不教 action / A-H


def check_9(t: Corpus, *, tail: str = "", protocol: str = "") -> list[str]:
    """⑨ 每一步的骨架与循环协议都按「伙伴表里的角色名 + task + params」讲话。"""
    from agentflow.agent_loop import JSON_TAIL

    skeleton = JSON_TAIL if not tail else tail
    out: list[str] = []
    if '"action"' in skeleton:
        out.append(f"[⑨] JSON_TAIL 还在教 `action` 这一格"
                   f"（{_at('agent_loop.py', 'JSON_TAIL = (')}）")
    if "A-H" in skeleton:
        out.append("[⑨] JSON_TAIL 还在教 `A-H` 这种角色级寻址")
    if '{"summon": {"role": "<伙伴表里的角色名>"' not in skeleton:
        out.append("[⑨] JSON_TAIL 的 summon 骨架不是「role=<伙伴表里的角色名> + task」那一形")
    text = t.file("agent_prompts.py") if not protocol else protocol
    if "A–H 之一" in text:
        out.append(f"[⑨] 循环协议的 summon 占位符还写着「角色（A–H 之一）」"
                   f"（{_at('agent_prompts.py', '唤起一个伙伴去做一件事')}）")
    if "伙伴表里的角色名" not in text:
        out.append("[⑨] 循环协议的 summon 占位符没有指向伙伴表里的角色名")
    return out


# ============================================================ 其余：数字与枚举


def check_numbers(t: Corpus) -> list[str]:
    """其余：H 与 V 那几个写死的数字/枚举，以及六个真前缀。"""
    out: list[str] = []
    h, v = t.prompt("H"), t.prompt("V")
    if "proof 环境数 ≥ 6" in h or "proof 环境数 >= 6" in h:
        out.append(f"[H-数字] proof 环境数还写死成 ≥ 6（{_at('specs/h.py', 'proof 环境数')}）")
    if "== 台账里定理类命题数" not in h:
        out.append(f"[H-数字] 没有把 proof 环境数挂到「台账里定理类命题数」上"
                   f"（{_at('specs/h.py', 'proof 环境数')}）")
    if "四件套" in h:
        out.append(f"[H-数字] 还写着「四件套齐全」而只列三样（{_at('specs/h.py', '四件套')}）")
    if "三件齐全" not in h:
        out.append("[H-数字] 那一条没有改成「三件齐全」")
    if "两份手册" in v:
        out.append(f"[V-数字] V 还写「那两份手册」而 skills/V 下是三份"
                   f"（{_at('specs/v.py', '两份手册')}）")
    if "三份手册" not in v:
        out.append("[V-数字] V 的提示词里没有「三份手册」")
    if "proof_no" not in v:
        out.append(f"[V-数字] V 的正文 0 次提到 `proof_no`（{_at('specs/v.py', '三态：')}）")
    for role in ("H", "G"):
        if "conj:" in t.prompt(role):
            out.append(f"[前缀] {role} 的提示词里还有 `conj:` 这个不存在的引用前缀")
        if "eval:" not in t.prompt(role) or "doc:" not in t.prompt(role):
            out.append(f"[前缀] {role} 的提示词里的前缀清单没列全六个真前缀（缺 eval/doc）"
                       f"（{_at('specs/g.py', '内部编号')}）")
    return out


def check_prefixes_are_real(*, prefix_line: str = "") -> list[str]:
    """前缀清单必须只含 `schema.CITATION_PREFIXES` 里真有的那六个。"""
    real = set(S.CITATION_PREFIXES)
    found = set(re.findall(r"`([a-z_]+):`", prefix_line))
    if not found:
        return ["[前缀] 这一份文本里一个 `前缀:` 写法都没找到 ⇒ 这一条是真空的"]
    ordered = {name for name in found if name in real}
    unknown = sorted(found - real)
    out: list[str] = []
    if unknown:
        out.append(f"[前缀] 列表里出现了不存在的引用前缀 {unknown}（真身 {sorted(real)}，"
                   f"位置 {_at('attackround.py', 'CITE_DISCIPLINE')}）")
    if ordered != real:
        out.append(f"[前缀] 前缀清单不全：{sorted(ordered)} vs 真身 {sorted(real)}"
                   f"（{_at('attackround.py', 'CITE_DISCIPLINE')}）")
    return out


def check_out_edges_comment(t: Corpus, *, source: str = "", edges: Any = None) -> list[str]:
    """出边非空的角色名单（注释级读数）与边表读数一致。"""
    table = C.ALLOWED_EDGES if edges is None else edges
    live = sorted(role for role, targets in table.items()
                  if targets and role != S.CONDUCTOR_ROLE)
    text = t.file("agent_prompts.py") if not source else source
    match = re.search(r"出边非空的([一二三四五六七八九十]+)个（([A-Z/]+)）", text)
    if not match:
        return [f"[出边] 找不到那句注释（{_at('agent_prompts.py', '出边非空的')}）"
                "⇒ 这一条是真空的"]
    said = match.group(2).split("/")
    if sorted(said) != live:
        return [f"[出边] 注释说的是 {said}，边表里出边非空的是 {live}"
                f"（{_at('agent_prompts.py', '出边非空的')}）"]
    return []


# ============================================================ 其余：公共段


def check_common(t: Corpus, *,
                 reviewed_ledger: str = "",
                 formal_states: Any = None,
                 fivebits: str = "") -> list[str]:
    """公共段：第 3 位的凭据按证明号钉；第 4 位有 `stale` 一档；V 提到 `proof_no`。"""
    out: list[str] = []
    ledger = reviewed_ledger or str(EB.BIT_LEDGERS["reviewed"].get("ledger") or "")
    where = _at("evidencebits.py", 'reviewed_by_proof[证明号]')
    if "reviewed_by_proof" not in ledger:
        out.append(f"[公共] 第 3 位的凭据还写着 {ledger!r}，不是 "
                   f"`bits.evidence.reviewed_by_proof[证明号]`（{where}）")
    if ledger.strip().startswith("documents"):
        out.append("[公共] 第 3 位的凭据仍指 `documents`（那是按稿件钉的第 5 位）")
    states = tuple(EB.FORMAL_PATH_STATES if formal_states is None else formal_states)
    if "stale" not in states:
        out.append(f"[公共] FORMAL_PATH_STATES 里没有 `stale`：{states}"
                   f"（{_at('evidencebits.py', 'FORMAL_PATH_STATES')}）")
    text = fivebits or AP.collab_fivebits_text()
    if "stale" not in text:
        out.append(f"[公共] 渲染出来的五元位那一段没提 `stale`"
                   f"（{_at('agent_prompts.py', '四态（第 1/4 位')}）")
    if "reviewed_by_proof" not in text:
        out.append("[公共] 渲染出来的五元位那一段里第 3 位还是按稿件钉的凭据")
    if "proof_no" not in t.prompt("V"):
        out.append(f"[公共] V 的提示词里没有 `proof_no`（{_at('specs/v.py', 'proof_no')}）")
    return out


# ============================================================ 其余：L 关档那块退役


def check_l_retired(t: Corpus, *, tables: Any = None) -> list[str]:
    """L 的关档改写表整块退役（关着时不可达），关档的话留在能行动的那两家。"""
    from agentflow.specs import l as LSPEC

    names = ("NO_LEAN_REPLACEMENTS", "NO_LEAN_DROP_LINE_MARKERS", "NO_LEAN_DROP_BLOCKS")
    present = ([name for name in names if hasattr(LSPEC, name)]
               if tables is None else list(tables))
    out: list[str] = []
    if present:
        out.append(f"[L-关档] specs/l.py 里还留着 {present}"
                   f"（{_at('specs/l.py', '改写表')}）—— 关着时 L 不存在，那几张表一条都应用不上")
    if "from .specs import l as _L_SPEC" in t.file("agent_prompts.py"):
        out.append(f"[L-关档] `_no_lean_tables` 仍在收 specs/l.py 那一份（它永远不会命中）"
                   f"（{_at('agent_prompts.py', '_no_lean_tables')}）")
    for role in PROMPT_ROLES:
        if "检查器那一步若仍被调用" in t.prompt(role):
            out.append(f"[L-关档] {role} 的提示词里还写着「检查器那一步若仍被调用」"
                       f"（模型面上没有那个入口，"
                       f"{_at('agent_prompts.py', '检查器那一步若仍被调用')}）")
    return out


# ============================================================ 渲染无损坏


def check_rendering(t: Corpus) -> list[str]:
    """渲染无损坏：没有 `⏎`、没有控制字符、没有替换字符。"""
    out: list[str] = []
    for role in PROMPT_ROLES:
        bad = _control_chars(t.prompt(role))
        if bad:
            out.append(f"[渲染] {role} 的提示词里有控制字符 {bad}")
        if "⏎" in t.prompt(role):
            out.append(f"[渲染] {role} 的提示词里有 `⏎`（换行被写成了符号）")
    return out


# ============================================================ 正控：每条一个断言


def test_item_1_h_is_not_told_to_write_the_paper(corpus: Corpus) -> None:
    """① H 只读正文与回执，写正文与编 PDF 都归 G。"""
    problems = check_1(corpus)
    assert problems == [], "\n".join(problems)


def test_item_2_retirement_has_two_entrances_one_sink(corpus: Corpus) -> None:
    """② 销号：`retire` 形与 `retire_child` 工具同一落点，只读角色只有形那一档。"""
    problems = check_2(corpus)
    assert problems == [], "\n".join(problems)


def test_item_3_verifications_is_a_file_ledger(corpus: Corpus) -> None:
    """③ 结论落 `verifications/<命题号>.jsonl`（文件账本，表不存在）。"""
    problems = check_3(corpus)
    assert problems == [], "\n".join(problems)


def test_item_4_lean_file_lands_where_l_writes(corpus: Corpus) -> None:
    """④ L 落 `code/formal/`、扫描面含它、G 的文案写项目根相对路径。"""
    problems = check_4(corpus)
    assert problems == [], "\n".join(problems)


def test_item_5_a_dispatch_names_the_task_not_an_action(corpus: Corpus) -> None:
    """⑤ 派活写 `task` 说清审哪一份，`params` 里给 `doc_id`。"""
    problems = check_5(corpus)
    assert problems == [], "\n".join(problems)


def test_item_6_review_files_is_an_acceptance_kind(corpus: Corpus) -> None:
    """⑥ `review_files` / `reviewed_current_rows` 是验收表 kind，不是八格。"""
    problems = check_6(corpus)
    assert problems == [], "\n".join(problems)


def test_item_7_review_report_requires_own_errors(corpus: Corpus) -> None:
    """⑦ 动作面必填与工具面必填是同一句话（`doc_id` + `own_errors`）。"""
    problems = check_7(corpus)
    assert problems == [], "\n".join(problems)


def test_item_8_compose_claim_has_no_page_range(corpus: Corpus) -> None:
    """⑧ 手册不再说 `doc.compose_claim` 有 `page_range`。"""
    problems = check_8(corpus)
    assert problems == [], "\n".join(problems)


def test_item_9_the_skeleton_teaches_role_name_and_task(corpus: Corpus) -> None:
    """⑨ 骨架与循环协议都用「伙伴表里的角色名 + task + params」。"""
    problems = check_9(corpus)
    assert problems == [], "\n".join(problems)


def test_the_numbers_and_enumerations_are_clean(corpus: Corpus) -> None:
    """其余各条：写死的数字、枚举、前缀、出边读数。"""
    from agentflow import attackround as AR

    problems = (check_numbers(corpus) + check_prefixes_are_real(prefix_line=AR.CITE_DISCIPLINE)
                + check_out_edges_comment(corpus))
    assert problems == [], "\n".join(problems)


def test_the_shared_sections_are_clean(corpus: Corpus) -> None:
    """公共段：第 3 位按证明号钉、第 4 位有 `stale`、V 提到 `proof_no`。"""
    problems = check_common(corpus)
    assert problems == [], "\n".join(problems)


def test_the_l_closed_block_is_retired(corpus: Corpus) -> None:
    """L 关档那一块整块退役（不可达），关档的话留在 B / G 能行动的那两家。"""
    problems = check_l_retired(corpus)
    assert problems == [], "\n".join(problems)


def test_the_rendering_is_intact(corpus: Corpus) -> None:
    """渲染无损坏（不出现 `⏎` / 控制字符）。"""
    problems = check_rendering(corpus)
    assert problems == [], "\n".join(problems)


def test_the_g_no_lean_table_matches_the_open_prompt() -> None:
    """反真空：`specs/g.py::NO_LEAN_REPLACEMENTS` 的左边在开档的 G 提示词里逐字出现。

    为什么必须有这一条（`T-L3` 的同一课）：改写表的左边是手写的字面量，抄错一个字，
    关档那一条就静默不生效 —— 提示词会告诉 G 去填一个这一档产不出来的 `lean_file`，
    而没有任何读数会说这件事。`tests/test_lean_switch.py` 对 E 那张表有同形的判据，
    这里给 G 的（`lean_file` 那一句是 2026-10-25 新加的替身）。
    """
    import os

    from agentflow import settings as SET
    from agentflow.specs import g as GSPEC

    saved = os.environ.get(SET.ENV_LEAN_ENABLED)
    os.environ[SET.ENV_LEAN_ENABLED] = "1"
    AP.reset_toolchain_readings()
    try:
        text = AP.system_prompt("G", registry=build_registry().registry,
                                task=TASK, workspace_root=ROOT)
    finally:
        if saved is None:
            os.environ.pop(SET.ENV_LEAN_ENABLED, None)
        else:
            os.environ[SET.ENV_LEAN_ENABLED] = saved
        AP.reset_toolchain_readings()
    missing = [old for old, _new in GSPEC.NO_LEAN_REPLACEMENTS if old not in text]
    assert missing == [], (
        f"[④] specs/g.py 的改写表左边在开档的 G 提示词里找不到（表失效了）：{missing}")


def test_the_g_no_lean_table_rewrites_every_left() -> None:
    """关档那一条真的生效：左边不出现、右边出现（否则「留空那两格」这句话没人说）。"""
    import os

    from agentflow import settings as SET
    from agentflow.specs import g as GSPEC

    saved = os.environ.get(SET.ENV_LEAN_ENABLED)
    os.environ[SET.ENV_LEAN_ENABLED] = "0"
    AP.reset_toolchain_readings()
    try:
        text = AP.system_prompt("G", registry=build_registry().registry,
                                task=TASK, workspace_root=ROOT)
    finally:
        if saved is None:
            os.environ.pop(SET.ENV_LEAN_ENABLED, None)
        else:
            os.environ[SET.ENV_LEAN_ENABLED] = saved
        AP.reset_toolchain_readings()
    for old, new in GSPEC.NO_LEAN_REPLACEMENTS:
        assert old not in text, f"[④] 关档的 G 提示词里还留着改写表的左边：{old[:60]!r}"
        assert new in text, f"[④] 关档的 G 提示词里没有改写后的那一段：{new[:60]!r}"


def test_the_lean_file_lands_where_l_writes_it(tmp_path: pathlib.Path) -> None:
    """④ 的功能面：`code/formal/<名>.lean` 真的能被 `lean_file` 指到。

    三个落点此前各说各话（G 说"包内"、L 落 `code/formal`、扫描面只有包内 +
    `out/formal`），而全仓没有一步把 `code/formal` 拷进包。这一条判的是行为：
    盘上那份源码在，`lean_file` 写它就该被认；两个根之外仍然是红。
    """
    project = tmp_path / "ws"
    package = PM.package_dir(project)
    (package / "formal").mkdir(parents=True, exist_ok=True)
    (package / "formal" / "000001.lean").write_text("theorem a : 1 = 1 := rfl\n",
                                                    encoding="utf-8")
    source = project / "code" / "formal" / "000004.lean"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("theorem b : 1 = 1 := rfl\n", encoding="utf-8")

    assert "code/formal/000004.lean" in PM.lean_artifacts(project), (
        f"[④] 扫描面看不见 L 的落点：{PM.lean_artifacts(project)}"
        f"（{_at('papermapping.py', 'LEAN_ARTIFACT_DIRS')}）")
    repo = PM._lean_source_state(package, project, "code/formal/000004.lean")
    assert repo["state"] == "present", (
        f"[④] `lean_file` 指 L 的落点却读不到：{repo}"
        f"（{_at('papermapping.py', '_lean_source_state')}）")
    assert pathlib.Path(repo["abs"]) == source.resolve(), repo
    inside = PM._lean_source_state(package, project, "formal/000001.lean")
    assert inside["state"] == "present", f"[④] 包内写法不再被认：{inside}"
    assert PM._lean_source_state(package, project, "../escape.lean")["state"] == "outside"
    assert PM._lean_source_state(package, project,
                                 str(source.resolve()))["state"] == "outside"


def test_a_summon_without_own_errors_is_refused_at_the_gate(tmp_path: pathlib.Path) -> None:
    """⑦ 的功能面：照动作面派活不再"先放行、再被拒"，缺 `own_errors` 当场说清。

    改前：动作面只写 `doc_id` ⇒ 主控照它派活，参数门放行、工具层退回（G15）；
    那一步的预算白花，而读数上看起来像 H 不肯干活。
    """
    from agentflow.host import wired_conductor
    from agentflow.store import Store

    store = Store(tmp_path / "ws")
    store.init()
    cond = wired_conductor(store, workspace_root=str(store.root))
    refused = cond.summon("H", "review_report", {"doc_id": "0000"}, by="M")
    assert str(refused.outcome) == "refused", refused
    assert str(refused.refusal_reason) == "invalid_params", refused
    assert "own_errors" in str(refused.detail), refused.detail


# ============================================================ 反真空（三条点名的）


def test_mutation_put_the_table_back_turns_item_3_red(corpus: Corpus) -> None:
    """反真空 ③：把「结论落 `verifications` 表」塞回去 ⇒ ③ 必红。"""
    broken = corpus.replaced(role="H",
                             old="结论落 `verifications/<命题号>.jsonl`（文件账本，不是表）",
                             new="结论落 `verifications` 表")
    problems = check_3(broken)
    assert any(problem.startswith("[③]") for problem in problems), problems


def test_mutation_put_the_action_key_back_turns_item_9_red(corpus: Corpus) -> None:
    """反真空 ⑨：把骨架里的 `action` 塞回去 ⇒ ⑨ 必红。"""
    from agentflow.agent_loop import JSON_TAIL

    broken_tail = JSON_TAIL.replace(
        '{"summon": {"role": "<伙伴表里的角色名>", "task": "<一件可判定的活>", "params": {...}}}',
        '{"summon": {"role": "A-H", "action": "<动作名>", "params": {...}}}')
    assert broken_tail != JSON_TAIL, "负控自己写错了：骨架里没有那一行"
    problems = check_9(corpus, tail=broken_tail)
    assert any(problem.startswith("[⑨]") for problem in problems), problems


def test_mutation_put_the_write_back_turns_item_1_red(corpus: Corpus) -> None:
    """反真空 ①：把「正文由你写」塞回 H 的那一段 ⇒ ① 必红。"""
    broken = corpus.replaced(role="H", old="正文由 G 写", new="正文由你写")
    problems = check_1(broken)
    assert any(problem.startswith("[①]") for problem in problems), problems


# ============================================================ 其余各条自己的红


def test_mutation_retire_as_the_only_entrance_turns_item_2_red(corpus: Corpus) -> None:
    """反真空 ②：把「销号只有一个入口」塞回去 ⇒ ② 必红。"""
    broken = corpus.replaced(role="H", old="销号是父的决定，两个入口落到**同一处**",
                             new="这一形是**旧路**：销号只有一个入口")
    problems = check_2(broken)
    assert any(problem.startswith("[②]") for problem in problems), problems


def test_mutation_lean_file_scan_without_l_dir_turns_item_4_red(corpus: Corpus) -> None:
    """反真空 ④：扫描面去掉 `code/formal` ⇒ ④ 必红。"""
    problems = check_4(corpus, dirs=("out/formal",))
    assert any(problem.startswith("[④]") for problem in problems), problems


def test_mutation_action_review_turns_item_5_red(corpus: Corpus) -> None:
    """反真空 ⑤：把 `action=review` 塞回 H 的提示词 ⇒ ⑤ 必红。"""
    broken = corpus.replaced(role="H", old="主控派活时在 `task` 里说清审哪一份",
                             new="主控派活时写 `action=review` 并")
    problems = check_5(broken)
    assert any(problem.startswith("[⑤]") for problem in problems), problems


def test_mutation_closing_gate_wording_turns_item_6_red(corpus: Corpus) -> None:
    """反真空 ⑥：把「收工门那一档 `review_files`」塞回去 ⇒ ⑥ 必红。"""
    broken = corpus.replaced(role="H", old="那是**验收表**里 `kind=review_files` 那一行的读数",
                             new="收工门那一档 `review_files`")
    problems = check_6(broken)
    assert any(problem.startswith("[⑥]") for problem in problems), problems


def test_mutation_action_face_without_own_errors_turns_item_7_red(corpus: Corpus) -> None:
    """反真空 ⑦：动作面只写 `doc_id` ⇒ ⑦ 必红。"""
    problems = check_7(corpus, action_required=("doc_id",))
    assert any(problem.startswith("[⑦]") for problem in problems), problems


def test_mutation_compose_claim_page_range_turns_item_8_red(corpus: Corpus) -> None:
    """反真空 ⑧：把 `compose_claim` 那半句塞回去 ⇒ ⑧ 必红。"""
    broken = corpus.replaced(
        rel="agent_skills.py",
        old="`page_range` 在 `register_statement` 里是",
        new="`page_range` 在 `doc.compose_claim` 里是")
    problems = check_8(broken)
    assert any(problem.startswith("[⑧]") for problem in problems), problems


def test_mutation_reviewed_ledger_turns_common_red(corpus: Corpus) -> None:
    """反真空（公共段）：第 3 位的凭据改回 `documents` ⇒ 必红。"""
    problems = check_common(corpus, reviewed_ledger="documents（V 的审校结论，按稿件钉）")
    assert any(problem.startswith("[公共]") for problem in problems), problems


def test_mutation_four_states_turn_common_red(corpus: Corpus) -> None:
    """反真空（公共段）：第 4 位只剩四态（没有 `stale`）⇒ 必红。"""
    problems = check_common(corpus, formal_states=("pending", "na", "failed", "verified"))
    assert any(problem.startswith("[公共]") for problem in problems), problems


def test_mutation_l_tables_turn_l_retired_red(corpus: Corpus) -> None:
    """反真空（L 关档）：把改写表塞回 specs/l.py ⇒ 必红。"""
    problems = check_l_retired(corpus, tables=["NO_LEAN_REPLACEMENTS"])
    assert any(problem.startswith("[L-关档]") for problem in problems), problems


def test_mutation_control_characters_turn_rendering_red(corpus: Corpus) -> None:
    """反真空（渲染）：塞一个 `⏎` 进去 ⇒ 必红。"""
    broken = corpus.replaced(role="H", old="论文（你参与的那份交付物）",
                             new="论文⏎（你参与的那份交付物）")
    problems = check_rendering(broken)
    assert any(problem.startswith("[渲染]") for problem in problems), problems


def test_mutation_out_edge_comment_turns_red(corpus: Corpus) -> None:
    """反真空（出边）：把那句注释改回「八个」⇒ 必红。"""
    broken = corpus.replaced(rel="agent_prompts.py", old="出边非空的九个（A/B/D/E/F/G/H/L/V）",
                             new="出边非空的八个（A/B/D/E/F/G/H/V）")
    problems = check_out_edges_comment(broken)
    assert any(problem.startswith("[出边]") for problem in problems), problems
