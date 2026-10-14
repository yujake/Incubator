"""语义判据的接入方式：判据注册表 + 三态 + 引用落地过滤 + 负控要求。

## 这一层填的是哪个洞

`judge.judge_json` 在 `draft/28` §178 里被记成"有定义、零调用点"：
框架里有一处"唯一的 LLM 缝"，但没有任何判据真的走它。
而"高观点 / 敢创新 / 有品味"这三项官能如果只写在提示词里，
就等于把质量交给运气 —— 没有人能回答"这次的产出到底达没达到标准"。

这一层把"另一半"（语义的那一半，机械的那一半在 `faculty_checks.py`）接起来，
并且给模型判断加三道结构约束：

1. 三态：没接线 = `judge_not_wired`、坏 JSON = `judge_bad_json`、超预算 / 拒答各有码
   （复用 `judge.JUDGE_PROBLEMS`）。"没判"与"判过了没问题"必须分得开。
2. 引用落地：模型给的每条 finding 必须带一句 `quote`，而那句话必须逐字出现在被审的产出里；
   引不到就丢掉并计数（`dropped`）。一条"凭印象"的评审意见在记录里是可见的缺陷，不是结论。
3. 负控是准入条件：每条判据都必须带至少一条"这一段必须被判不通过"的样本
   （`NEGATIVE_CONTROLS`），没有负控的判据不许进表 —— 这是 `draft/28` §180 里
   "判据必须有注入负控"那条纪律在语义判据上的落点。

## 与 `review_tools` 的关系

`tools/review_tools.py` 里已经有一条同形的接缝（`semantic_judge` + `checked=False` + 逐字理由），
它管的是审校环节里"结论是否强于引文"那一格。这一层不重复它：
这里给的是逐官能的判据表，供 `agent_loop` / 编排层在"交付前"逐项问一次。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import agent_prompts as AP
from . import judge as J
from .llmseam import LlmSeam

#: 判据模板的版本。改任何一条模板都要改它 —— 它是审计记录里
#: "这次审的是哪一版判据"的答案，与角色提示词版本（`agent_prompts.PROMPT_VERSION`）是两件事。
JUDGE_VERSION = "j1"

#: 判据表：`id -> Criterion`。每条的字段都在 `registry_problems()` 里被核过。
CRITERIA: dict[str, "Criterion"] = {}


@dataclass(frozen=True)
class Criterion:
    """一条语义判据：问什么、允许哪些判定、哪一种算通过。"""

    id: str
    faculty: str            # 十项官能里的哪一项（必须是 `agent_prompts.FACULTIES` 里的名字）
    name: str
    question: str
    artifact_kind: str      # `markdown` / `claims` / `conjecture`（给读的人一个口径）
    verdicts: tuple[str, ...]
    pass_verdicts: tuple[str, ...]
    template: str           # 必须含 `{artifact}`（可选 `{context}`）

    def prompt(self, artifact: str, context: str = "") -> str:
        """渲染这次要问的 prompt。"""
        return self.template.replace("{artifact}", artifact).replace(
            "{context}", context or "（没有额外上下文）")


def _register(criterion: Criterion) -> None:
    CRITERIA[criterion.id] = criterion


_JSON_RULES = (
    "只输出一个 JSON 对象，不要解释文字、不要 Markdown 围栏，形如：\n"
    '{"verdict": "<上面允许的判定之一>", "why": "<一句话理由>",\n'
    ' "findings": [{"quote": "<被审文本里逐字出现的一句>", "why": "<这一条的问题>"}]}\n'
    "findings 可以为空；但只要给了一条，它的 quote 就必须在被审文本里逐字出现 —— "
    "引不到的那条会被框架丢掉，并记成一条缺陷。"
)

_register(Criterion(
    id="overview.essence", faculty="高观点",
    name="结构判断是不是真的结构判断",
    question="这段产出给的是概念/理论之间的结构判断（一般与特例、等价、蕴含、推广），"
             "还是把若干局部结论摊开？",
    artifact_kind="markdown",
    verdicts=("structural", "listing", "unsupported"),
    pass_verdicts=("structural",),
    template=(
        "你在审一份数学产出，只判一件事：它有没有给出结构判断。\n"
        "structural = 明确说了概念/理论之间的关系（谁是一般、谁是特例、谁蕴含谁、能否推广），"
        "且文内能看出这个判断是怎么得出来的；\n"
        "listing = 只是把若干局部结论并列摊开，没有结构判断；\n"
        "unsupported = 有结构措辞，但文内自相矛盾或根本推不出那个关系。\n"
        "注意：文中引用的编号（如 relations/0001）**存不存在**由框架的机械半另行核对，"
        "你不要因为「文内看不到那个编号的内容」就判 unsupported —— 那是另一条判据的事。\n\n"
        "额外上下文：{context}\n\n被审文本：\n---\n{artifact}\n---\n\n" + _JSON_RULES
    ),
))

_register(Criterion(
    id="innovation.conjecture_value", faculty="敢创新",
    name="猜想是不是实质猜想",
    question="提出的猜想是否实质（不是平凡真/假）、是否给了可判定路径与对立面？",
    artifact_kind="conjecture",
    verdicts=("substantive", "trivial", "unfalsifiable"),
    pass_verdicts=("substantive",),
    template=(
        "你在审一条数学猜想。只判它值不值得投入：\n"
        "substantive = 不是平凡真/假，且有可判定的检验路径（能被一次实验或反例推进）；\n"
        "trivial = 由定义或已知结论直接可得，投入没有意义；\n"
        "unfalsifiable = 无法想象什么证据能推翻它（对立面没写清或不存在）。\n\n"
        "额外上下文：{context}\n\n被审文本：\n---\n{artifact}\n---\n\n" + _JSON_RULES
    ),
))

_register(Criterion(
    id="taste.journal_style", faculty="有品味",
    name="学术写作是否达到期刊体例",
    question="记号是否有定义、定理环境是否稳定、引用格式是否一致、有无堆砌？",
    artifact_kind="markdown",
    verdicts=("journal_ready", "needs_work", "not_a_draft"),
    pass_verdicts=("journal_ready",),
    template=(
        "你在按期刊体例审一份稿件。只判体例与取舍，不判数学对错：\n"
        "journal_ready = 记号有定义、定理/引理环境一致、引用格式统一、没有为了显得丰富而堆砌；\n"
        "needs_work = 能读懂，但有明确的体例问题（记号冲突、环境混用、冗余段落）；\n"
        "not_a_draft = 还不是一份稿（缺结构、缺定义、像笔记）。\n\n"
        "额外上下文：{context}\n\n被审文本：\n---\n{artifact}\n---\n\n" + _JSON_RULES
    ),
))

_register(Criterion(
    id="brain.blocker_specificity", faculty="脑子",
    name="卡点说得够不够具体",
    question="结论里的卡点是否具体到'缺什么、下一步做什么'，还是一句笼统的话？",
    artifact_kind="markdown",
    verdicts=("specific", "vague", "none"),
    pass_verdicts=("specific",),
    template=(
        "你在看一段研究结论。只判它的'卡点'说得够不够具体：\n"
        "specific = 点名缺什么（缺哪条引理/哪个实验/哪份文献）以及下一步做什么；\n"
        "vague = 说了卡住，但看不出缺什么、也看不出下一步；\n"
        "none = 没有卡点表述（通常是'已完成/没问题'这一类）。\n\n"
        "额外上下文：{context}\n\n被审文本：\n---\n{artifact}\n---\n\n" + _JSON_RULES
    ),
))

_register(Criterion(
    id="reasoning.source_fidelity", faculty="能思辨",
    name="读的是原始来源还是二手复述",
    question="结论是回到原始材料（原文/原始证明/一次实验）核对出来的，还是复述别人的转述？",
    artifact_kind="markdown",
    verdicts=("primary", "secondary", "authority_only"),
    pass_verdicts=("primary",),
    template=(
        "你在看一段论证。只判它的依据来自哪里：\n"
        "primary = 回到原始材料（原文那一段、原始证明那一步、一次可复现的实验）核对过；\n"
        "secondary = 依据是别人的转述或综述，没有回到原始材料；\n"
        "authority_only = 依据是「某权威这么说」或「以前都这么做」，没有可核对的材料。\n\n"
        "额外上下文：{context}\n\n被审文本：\n---\n{artifact}\n---\n\n" + _JSON_RULES
    ),
))

_register(Criterion(
    id="claims.conclusion_strength", faculty="能思辨",
    name="结论有没有强于它挂的证据",
    question="台账里每一条断言说得有多强，与它挂的证据等级对得上吗？"
             "（cross_check 只说明「独立核过一遍」，不是证明）",
    artifact_kind="claims",
    verdicts=("within_evidence", "overclaimed", "unjudgeable"),
    pass_verdicts=("within_evidence",),
    template=(
        "你在审一份数学产出的断言台账，只判一件事：有没有哪一条的结论**强于**它挂的证据。\n"
        "within_evidence = 每一条的措辞都没有超出它的证据等级"
        "（例如证据等级是 cross_check 的条目只说「我们独立核过」「数值上一致」，"
        "没有说「证明」「必然成立」）；\n"
        "overclaimed = 至少有一条的措辞超出了它挂的证据等级"
        "（把 cross_check 写成证明、把数值一致写成一般结论、把转述写成已核对）；\n"
        "unjudgeable = 文本里看不出证据等级，或条目残缺到判不了（这不是「没问题」）。\n"
        "注意：断言本身对不对不由你判（那是实验与形式化的事），你只判「说得比证据强没强」。\n"
        "把每一条超出证据的断言逐字引出来（quote 必须是被审文本里逐字出现的一段）。\n\n"
        "额外上下文：{context}\n\n被审文本：\n---\n{artifact}\n---\n\n" + _JSON_RULES
    ),
))

#: 负控样本：这一条判据必须能把它们判成不通过（准入条件，没有负控的判据不许进表）。
#: 它们不是"格式错"，而是各自官能上真实会出现的坏形态。
NEGATIVE_CONTROLS: dict[str, tuple[str, ...]] = {
    "overview.essence": (
        "# 材料小结\n\n我们读了 12 篇文献。第 1 篇讲了群的定义；第 2 篇讲了阿贝尔群；"
        "第 3 篇讲了有限群。三条结论并列如下。\n",
        "# 高观点\n\n群论与表示论之间有深刻联系，这一点是本质的。\n",
    ),
    "innovation.conjecture_value": (
        "猜想：任何群都有单位元。\n",
        "猜想：某个很复杂的东西可能存在某种我们还不知道的性质。\n",
    ),
    "taste.journal_style": (
        "# 草稿\ntodo：定义待补。这里用 f 表示那个东西，后面又用 f 表示另一个东西。\n",
        "群。环。域。都是代数结构。\n",
    ),
    "brain.blocker_specificity": (
        "本项目已全部核对完成，没有发现问题。\n",
        "目前遇到了一些困难，还需要更多时间研究。\n",
    ),
    "reasoning.source_fidelity": (
        "据综述 [3] 所述，该结论已被广泛接受，因此我们采用它。\n",
        "这是该领域的经典结论，教材上都这么写，所以不必再核。\n",
    ),
    "claims.conclusion_strength": (
        "| 断言 | 证据等级 | 结论 |\n|---|---|---|\n"
        "| 主坐标的涨落收敛到正态 | cross_check | 我们证明了该涨落服从中心极限定理 |\n",
        "| 断言 | 证据等级 | 结论 |\n|---|---|---|\n"
        "| 距离二阶矩的表达式 | 数值一致 | 该公式对一切维数必然成立 |\n",
    ),
}


@dataclass
class Verdict:
    """一条判据的结论：判定、理由、落地的发现、被丢掉的发现，以及这次调用的审计事实。"""

    criterion: str
    faculty: str
    ok: bool
    problem: str = ""
    verdict: str = ""
    why: str = ""
    findings: list[dict[str, str]] = field(default_factory=list)
    dropped: list[dict[str, str]] = field(default_factory=list)
    model: str = ""
    prompt_version: str = ""
    prompt_sha256: str = ""
    judge_version: str = JUDGE_VERSION
    detail: str = ""

    @property
    def grounded_ratio(self) -> float:
        """落地的发现占模型给出的发现的比例（1.0 = 全部落地；没有发现也算 1.0）。"""
        total = len(self.findings) + len(self.dropped)
        return 1.0 if total == 0 else len(self.findings) / total

    def to_dict(self) -> dict[str, Any]:
        """落档/打印用的扁平结构（含落地比例与这次调用的审计事实）。"""
        return {"criterion": self.criterion, "faculty": self.faculty, "ok": self.ok,
                "problem": self.problem, "verdict": self.verdict, "why": self.why,
                "findings": list(self.findings), "dropped": list(self.dropped),
                "grounded_ratio": round(self.grounded_ratio, 3),
                "model": self.model, "prompt_version": self.prompt_version,
                "judge_version": self.judge_version,
                "prompt_sha256": self.prompt_sha256, "detail": self.detail}


def _norm(text: str) -> str:
    """比较引文时用的归一化：压掉空白差异（换行/多空格不算改字）。"""
    return re.sub(r"\s+", "", text or "")


def _ground(artifact: str, raw_findings: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """把模型给的发现分成"落地"与"引不到"两堆。

    这一条是"语义判据也可机械判"的那一半：模型可以胡说，但它说的每一句
    要么能在被审文本里找到，要么被记成一次引文失败。
    """
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes)):
        return kept, dropped
    body = _norm(artifact)
    for item in raw_findings:
        if not isinstance(item, Mapping):
            dropped.append({"quote": str(item)[:120], "why": "finding 不是对象"})
            continue
        quote = str(item.get("quote") or "").strip()
        why = str(item.get("why") or "").strip()
        if not quote or _norm(quote) not in body:
            dropped.append({"quote": quote[:120], "why": why or "（没有理由）"})
            continue
        if not why:
            dropped.append({"quote": quote[:120], "why": "（有引文但没有说明问题）"})
            continue
        kept.append({"quote": quote, "why": why})
    return kept, dropped


#: 值得重试一次的失败档（见 `judge()` 里那一段）：模型**答歪了**（散文 / JSON 不可解析）
#: 或**答案被思维链吃光**。这两档都不是"判过了没问题"，也不该只试一次就放弃 ——
#: 而"没接模型"（`judge_not_wired`）、"预算耗尽"、"超时"不在此列（重试也没用）。
RETRY_PROBLEMS: tuple[str, ...] = ("judge_bad_json", "judge_output_limit")


def judge(criterion_id: str, artifact: str, *, seam: LlmSeam | None,
          context: str = "") -> Verdict:
    """按一条判据审一段产出。三态与引用落地都在这里落。"""
    criterion = CRITERIA.get(criterion_id)
    if criterion is None:
        raise KeyError(f"未登记的判据 {criterion_id!r}（已知 {sorted(CRITERIA)}）")
    base = Verdict(criterion=criterion.id, faculty=criterion.faculty, ok=False)
    if seam is None or not seam.wired:
        base.problem = "judge_not_wired"
        base.detail = "没有接模型（或没有 key）：这是没判成，不是判过了没问题"
        return base

    prompt = criterion.prompt(artifact, context)
    data, problem, call = J.seam_json(seam, prompt, point=f"judge:{criterion.id}")
    # 一次重试（2026-10-14 真机实测逼出来的）：这一档用的是**会思考**的模型，
    # 思维链把输出预算吃光（`judge_output_limit`）或把 JSON 说成散文（`judge_bad_json`）
    # 都会让判据落到"没查成"—— 而那两档都不是"判过了没问题"，也不该白扔一次判定。
    # 重试只加一句"先给 JSON"，只重试一次；仍然不行就如实回那一档（三态纪律）。
    if data is None and problem in RETRY_PROBLEMS:
        retry_prompt = (prompt + "\n\n（上一次的回答没能解析成一个 JSON 对象。"
                        "这一次**先**直接输出那个 JSON 对象，再谈理由；"
                        "不要写任何解释性文字、不要用 Markdown 围栏。）")
        again, problem2, call2 = J.seam_json(seam, retry_prompt,
                                             point=f"judge:{criterion.id}:retry")
        if again is not None:
            data, call = again, call2
        else:
            problem, call = problem2, call2
    base.model = str(getattr(call, "model", "") or "")
    base.prompt_version = str(getattr(call, "prompt_version", "") or "")
    base.prompt_sha256 = str(getattr(call, "prompt_sha256", "") or "")
    if data is None:
        # `L-05b-2/4`（`draft/52` D3）：异常→码的映射只有一处（`judge._problem_of`），
        # 本入口不再自己 try/except（旧实现让 `BudgetExhausted` / `JudgeRefused` /
        # `TimeoutError` 落成 `judge_failed:<类名>`，与 `judge_json` 给的码不一致）。
        base.problem = problem or "judge_failed"
        base.detail = str(getattr(call, "detail", "") or "") or base.problem
        return base

    verdict = str(data.get("verdict") or "")
    if verdict not in criterion.verdicts:
        base.problem = "judge_bad_verdict"
        base.detail = f"判定 {verdict!r} 不在允许的 {criterion.verdicts} 里"
        return base
    base.verdict = verdict
    base.why = str(data.get("why") or "")
    base.findings, base.dropped = _ground(artifact, data.get("findings"))
    passed = verdict in criterion.pass_verdicts
    # 一条"通过"如果建立在引不到的发现上，不算通过：那说明评审意见是凭印象写的。
    if passed and base.dropped and not base.findings:
        base.ok = False
        base.problem = "judge_ungrounded_findings"
        base.detail = "判定为通过，但给出的发现一条都没能在被审文本里落地"
        return base
    base.ok = passed
    if not passed and not base.why:
        base.detail = "判定为不通过，但没有给理由"
    return base


def semantic_judge_for(seam: Any, *, criterion_id: str = "claims.conclusion_strength",
                       doc_context: str = "") -> Any:
    """把一条模型缝接成 `review_tools` 认的 `semantic_judge(claim, doc)`（`draft/28` §196）。

    ## 为什么需要这个适配器（两套词表，一个方向）

    `review_tools.SemanticJudge` 的词表是 `("consistent", "stronger_than_evidence", "unknown")`，
    而本条判据的词表是 `("within_evidence", "overclaimed", "unjudgeable")`。
    两套词表各自都对着自己的消费者（前者对着 H 的审校报告，后者对着交付闸门），
    所以不合并；这里做单向映射，并把映射写在一处：

    | 判据判定 | 接缝判定 |
    |---|---|
    | `within_evidence`（通过档） | `consistent` |
    | `overclaimed` | `stronger_than_evidence` |
    | `unjudgeable` / 判据没判成（`problem` 非空） | `unknown` |

    ## 三态

    返回 `{"verdict": "unknown", "reason": ...}` 的两种情况必须分得开（都写进 reason）：
    "模型说它判不了"（`unjudgeable`）与"这次调用就没成"（`problem`，如 `judge_not_wired`、
    坏 JSON）。没查成不许折成"没问题" —— 这是 H 的审校报告里那一格的全部意义。
    """
    def _judge(claim: Mapping[str, Any], doc: Mapping[str, Any] | None = None) -> dict[str, Any]:
        text = str(claim.get("text") or claim.get("statement") or "")
        level = str(claim.get("evidence_kind") or "（未标）")
        cid = str(claim.get("claim_id") or "")
        title = str((doc or {}).get("title") or "")
        artifact = (f"断言（claim_id={cid}，证据等级={level}）：\n{text}\n"
                    + (f"（所属稿件：{title}）\n" if title else "")
                    + (doc_context or ""))
        got = judge(criterion_id, artifact, seam=seam,
                    context=f"逐条判这一条断言。证据等级={level}。")
        if got.problem:
            return {"verdict": "unknown",
                    "reason": f"判据没判成（{got.problem}）：{got.detail or got.why or ''}"[:200]}
        if got.verdict == "overclaimed":
            return {"verdict": "stronger_than_evidence",
                    "reason": (got.why or "结论强于它挂的证据")[:200]}
        if got.verdict == "within_evidence":
            return {"verdict": "consistent", "reason": (got.why or "措辞没有超出证据")[:200]}
        return {"verdict": "unknown",
                "reason": f"模型说这一条判不了（{got.verdict or '空判定'}）：{got.why or ''}"[:200]}

    _judge.__name__ = f"judge:{criterion_id}"
    return _judge


# ============================================================ 引文回验的语义档（2026-10-14）
# 业主：「回验不应该是十分呆板的逐字验证，而是保持语义相同即可」，落点是 B 唤起 H。
# 逐字那一档仍归 `quoteverify.check_quote`（不花模型钱，先走它）；逐字不中才轮到这一档。
# **不许**把模型调用塞进 `check_quote`：那是禁改区里的逐字判据，混进模型会让
# "引文级证据"的口径取决于模型 —— 两档分居两处，靠 `quote_mode` 那一栏分开记账。

_register(Criterion(
    id="quote.same_meaning", faculty="能思辨",
    name="引文与来源是不是说同一件事",
    question="这段引文与来源里的那一段，是不是在说同一件事（语义相同）？"
             "改写、换记号、跨语言都算相同；引文比来源更强不算。",
    artifact_kind="claims",
    verdicts=("same_meaning", "different", "stronger_than_source", "unjudgeable"),
    pass_verdicts=("same_meaning",),
    template=(
        "你在核一条引文。只判一件事：**引文与来源说的事是不是同一件**。\n"
        "same_meaning = 语义相同（允许改写、换记号、跨语言、简写 —— 只要说的是同一件事）；\n"
        "different = 说的不是同一件事（对象 / 条件 / 结论对不上）；\n"
        "stronger_than_source = 引文把来源的结论**加强了**（来源说「在某条件下」而引文写成"
        "无条件；来源说「可能」而引文写成「必然」……）—— 这一档**不算通过**；\n"
        "unjudgeable = 材料不足以判（来源那一段没给全 / 引文本身有歧义）。\n"
        "**不要**因为字面不完全一样就判 different —— 那是逐字比对，不是这一条要的。\n"
        "{context}\n"
        "被审材料：\n{artifact}\n\n" + _JSON_RULES
    ),
))

#: 负控（`registry_problems` 要求每条判据至少两条）：两条都必须在**语义**上不成立，
#: 而字面上都与来源沾边 —— 这正是这一档存在的理由（逐字档判不了它们，
#: 而"看起来像"也不该放过它们）。
NEGATIVE_CONTROLS["quote.same_meaning"] = (
    "引文：对一切有限图都有 d ≤ Δ。\n来源：对**连通**有限图，d ≤ Δ。",
    "引文：该常数等于 4(1/6-(2-√3)/π)。\n来源：本节只给出该常数的数值上界 0.33（约）。",
)


def quote_semantics_judge_for(
        seam: "LlmSeam | None") -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """把一条模型缝接成"引文 ↔ 来源"的语义判据（给 H 用；B 唤起 H 之后由它判）。

    输入 `material` 的四栏（调用方给，H 不自己去猜）：
    `quote`（待核的引文）、`span`（来源里那一段，**逐字**取来的）、
    `statement`（这条引文要支撑的断言，可空）、`where`（落点：文件/页码，给人看的）。

    返回 `{"verdict", "why", "call"}`：`verdict` 是判据词表里的四档之一或 `unknown`；
    `call` 是这次调用的审计事实（model / prompt_sha256 / prompt_version）——
    **语义那一档必须留证据**（业主那一句的后半段），这三格就是"可复查的调用记录"。

    三态：缝没接（或没有 key）⇒ `judge_not_wired` ⇒ `verdict="unknown"` 且理由写明
    "没判成，不是判过了没问题"；坏 JSON 同理。**没有 key 时如实回没查**。
    """
    def _judge(material: Mapping[str, Any]) -> dict[str, Any]:
        quote = str(material.get("quote") or "").strip()
        span = str(material.get("span") or "").strip()
        statement = str(material.get("statement") or "").strip()
        where = str(material.get("where") or "").strip() or "（没给落点）"
        artifact = (f"引文（待核）：\n{quote}\n\n来源里那一段（逐字取自 {where}）：\n{span}\n"
                    + (f"\n这条引文要支撑的断言：\n{statement}\n" if statement else ""))
        got = judge("quote.same_meaning", artifact, seam=seam,
                    context="只判「是不是同一件事」；字面不同不算不同。")
        call = {"model": got.model, "prompt_sha256": got.prompt_sha256,
                "prompt_version": got.prompt_version, "judge_version": got.judge_version}
        if got.problem:
            return {"verdict": "unknown",
                    "why": f"没判成（{got.problem}）：{got.detail or got.why or ''}"[:200],
                    "call": call}
        allowed = CRITERIA["quote.same_meaning"].verdicts
        if got.verdict not in allowed:
            return {"verdict": "unknown",
                    "why": f"模型说这一条判不了（{got.verdict or '空判定'}）：{(got.why or '')[:160]}",
                    "call": call}
        return {"verdict": got.verdict, "why": (got.why or "")[:200], "call": call}

    _judge.__name__ = "judge:quote.same_meaning"
    return _judge


def quote_fields_from_verdict(verdict: str, why: str, *, judge: str = "H"
                              ) -> tuple[bool | None, str, str]:
    """一条语义判定 ⇒ `(quote_verified, quote_mode, quote_reason)`（**唯一**口径）。

    三条，逐条对着业主那句裁定：

    - `same_meaning` ⇒ `(True, "semantic", …)`：**语义相同即通过**（这正是要改的那一条）；
    - `different` / `stronger_than_source` ⇒ `(False, "", …)`：语义不同、或引文把来源的
      结论加强了 —— 那一档**绝不会**因为"字面沾边"就被放过；
    - 其余（`unjudgeable` / `unknown`）⇒ `(None, "", "还没查：…")`：三态里的第三档，
      没判成不许折成通过，也不许折成不通过。
    """
    why = str(why or "")[:400]
    if verdict == "same_meaning":
        return True, "semantic", f"{judge} 判语义相同：{why}"
    if verdict in ("different", "stronger_than_source"):
        return False, "", f"{judge} 判不通过（{verdict}）：{why}"
    return None, "", f"还没查：{why or '语义判定没给出结论'}"


def registry_problems() -> list[str]:
    """判据表自身的完整性（判据也要有判据）。返回问题清单，空 = 干净。"""
    problems: list[str] = []
    faculties = {f for f, _w, _b in AP.FACULTIES}
    if len(CRITERIA) < 3:
        problems.append(f"判据表只有 {len(CRITERIA)} 条（少于三条：官能覆盖不够）")
    for cid, c in CRITERIA.items():
        if cid != c.id:
            problems.append(f"键与 id 不一致：{cid!r} vs {c.id!r}")
        if c.faculty not in faculties:
            problems.append(f"{cid} 的 faculty={c.faculty!r} 不在十项官能里")
        if not c.verdicts:
            problems.append(f"{cid} 没有判定词表")
        if not c.pass_verdicts or not set(c.pass_verdicts) <= set(c.verdicts):
            problems.append(f"{cid} 的通过判定不是判定词表的子集")
        if "{artifact}" not in c.template:
            problems.append(f"{cid} 的模板里没有 {{artifact}} 占位符")
        controls = NEGATIVE_CONTROLS.get(cid) or ()
        if not controls:
            problems.append(f"{cid} 没有负控样本 ⇒ 不许进表（无法证明它能判不通过）")
        elif len(controls) < 2:
            problems.append(f"{cid} 只有 1 条负控：一条样本证明不了判别力")
    for want in ("高观点", "敢创新", "有品味", "脑子", "能思辨"):
        if not any(c.faculty == want for c in CRITERIA.values()):
            problems.append(f"没有一条判据给『{want}』做背书")
    return problems


def covered_faculties() -> tuple[str, ...]:
    """有语义判据背书的官能（排序后）。"""
    return tuple(sorted({c.faculty for c in CRITERIA.values()}))


def json_rules_problems() -> list[str]:
    """每条判据的模板都得把 `_JSON_RULES` 带上（否则模型不知道该回 JSON）。

    为什么单列一条（2026-10-14 真机实测的教训）：新加的 `quote.same_meaning`
    第一版模板忘了接 `_JSON_RULES` —— 夹具（假缝回 JSON）全绿，真机上 5 条引文
    全部 `judge_bad_json`（模型回的是散文），于是那一档在真机上恒"没查成"。
    这不是"模型不行"，是**判据自己没把形状说给模型听**。凡新增判据，这一条都会先红。
    """
    missing = [cid for cid, c in CRITERIA.items() if _JSON_RULES not in c.template]
    return [f"{cid} 的模板没带上 `_JSON_RULES`（模型不知道要回 JSON）" for cid in missing]


def selftest() -> int:
    """自检：判据表完整性 + 三态 + 引用落地（含"凭印象的评审"这一负控）。"""
    import tempfile
    from pathlib import Path

    problems = list(registry_problems())

    class Fake:
        """按剧本回答的替身模型。"""

        spec = type("S", (), {"model": "fake"})()

        def __init__(self, text: str) -> None:
            self.text = text

        def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                     **kw: Any) -> Any:
            """自检替身：按剧本返回一段文本（与真模型的接口一致）。"""
            return type("R", (), {"ok": True, "text": self.text, "tokens_in": 3,
                                  "tokens_out": 3, "error_detail": "", "error_kind": ""})()

    artifact = "# 稿子\n\n阿贝尔群是群的特例，这一点由定义直接给出。\n"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 正控：判定通过 + 一条落地的发现
        good = ('{"verdict": "structural", "why": "点明了一般与特例",'
                ' "findings": [{"quote": "阿贝尔群是群的特例", "why": "这句是结构判断"}]}')
        seam = LlmSeam(role="H", session_root=root, gateway=Fake(good), price=(0.0, 0.0), sid="t")
        v = judge("overview.essence", artifact, seam=seam)
        if not v.ok or len(v.findings) != 1 or v.dropped:
            problems.append(f"正控没过：{v.to_dict()}")
        # 负控一：判定通过，但发现引不到原文 ⇒ 降级为不通过
        liar = ('{"verdict": "structural", "why": "看起来不错",'
                ' "findings": [{"quote": "这句话根本不在文本里", "why": "编的"}]}')
        v2 = judge("overview.essence", artifact,
                   seam=LlmSeam(role="H", session_root=root, gateway=Fake(liar),
                                price=(0.0, 0.0), sid="t"))
        if v2.ok or v2.problem != "judge_ungrounded_findings" or len(v2.dropped) != 1:
            problems.append(f"凭印象的评审没有被降级：{v2.to_dict()}")
        # 负控二：坏 JSON ⇒ judge_bad_json（不许当"通过"）
        v3 = judge("overview.essence", artifact,
                   seam=LlmSeam(role="H", session_root=root, gateway=Fake("不是 JSON"),
                                price=(0.0, 0.0), sid="t"))
        if v3.ok or v3.problem != "judge_bad_json":
            problems.append(f"坏 JSON 没被归类：{v3.to_dict()}")
        # 负控三：判定不在词表里
        v4 = judge("overview.essence", artifact,
                   seam=LlmSeam(role="H", session_root=root,
                                gateway=Fake('{"verdict": "great", "why": "x"}'),
                                price=(0.0, 0.0), sid="t"))
        if v4.ok or v4.problem != "judge_bad_verdict":
            problems.append(f"词表外的判定没被拒：{v4.to_dict()}")
        # 负控四：没接线 ⇒ judge_not_wired
        v5 = judge("overview.essence", artifact, seam=None)
        if v5.ok or v5.problem != "judge_not_wired":
            problems.append(f"没接线没落成 judge_not_wired：{v5.to_dict()}")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print(f"SELF-CHECK DONE（判据表 {len(CRITERIA)} 条、覆盖 {len(covered_faculties())} 项官能；"
          "三态 + 引用落地 + 凭印象评审的负控）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
