"""抽取层：``Extractor`` 协议 + 离线基线 ``RuleExtractor`` + 可插拔 ``LLMExtractor``。

设计基线：``test/test1/DESIGN.md`` §4.1（接口契约）、§6.3（引文校验）。

定位说明（很重要，避免误读本模块的野心）：

- ``RuleExtractor`` 不是要做出学术级抽取。它的价值是给整条 A/B 流水线
  一个确定性的、诚实的基线：同样的输入永远产出同样的 draft，让
  store / dedup / verify / CLI 这些真正的工程难点可以离线被测到，
  而不必先接上 LLM（§9 待决问题 3 尚未定论）。
- ``LLMExtractor`` 只负责"调用一个 ``.complete(prompt) -> str`` 的对象并
  解析结果"，不绑定任何厂商 SDK。它是协议适配器，不是模型客户端。

贯穿本模块的正确性红线（§6.3 的直接推论）：

draft 里的 ``quote`` 必须是原文的逐字子串，否则宁可不产出这条 draft。

对 ``RuleExtractor`` 而言这靠"从原页文本里切出来"在结构上保证；对
``LLMExtractor`` 而言这靠回验 + 剔除（fail-closed）来保证。两者路径不同，
但结论一致：任何进入下游的 quote 都已经过"它真的在原文里"的检验，
所以 agent_b 的 §6.3 校验只可能因为"页码窗口给错了"或"无文本层"而失败，
不会因为"模型编了句漂亮话"而失败。
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Iterable, Iterator, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查器
    # PageRange 由 schema.py 实现（他人负责）。放进 TYPE_CHECKING 是为了让
    # 本模块在 schema.py 尚不存在时也能被导入，从而能独立单测。
    from .schema import PageRange

    from .extract import DocumentText

logger = logging.getLogger(__name__)

__all__ = [
    "ConceptDraft",
    "DEFAULT_PROMPT_TEMPLATE",
    "ExtractionError",
    "Extractor",
    "LLMExtractor",
    "NullExtractor",
    "RelationDraft",
    "RuleExtractor",
]


# --------------------------------------------------------------------------- #
# 运行时依赖：schema.PageRange 与 extract.DocumentText
# --------------------------------------------------------------------------- #


def _load_document_text_cls() -> Any:
    """惰性拿到 ``DocumentText`` 类对象。

    只在需要运行时构造它的场合使用（目前是自检脚本）。正常流程里
    ``DocumentText`` 由调用方（agent_b）传进来，本模块只做属性访问，
    因此不依赖 extract 模块的真实存在，两者可以各自单测。
    """
    try:
        from .extract import DocumentText as _DT

        return _DT
    except Exception:  # pragma: no cover - 包外直接跑脚本时的兜底路径
        try:
            from agentflow.extract import DocumentText as _DT  # type: ignore[no-redef]

            return _DT
        except Exception:
            return None


@dataclass(frozen=True)
class _SimplePageRange:
    """``PageRange`` 的本地最小替身。

    为什么需要它：``PageRange`` 属于 schema.py（他人实现）。本模块要能被
    单独导入并运行自检（见文件末尾 ``__main__``），此刻 schema.py 可能
    根本不存在。因此运行期优先 import ``schema.PageRange``；一旦失败就走这个
    替身。替身刻意只保留 §1.4 定义的三个字段（``start`` / ``end`` / ``label``），
    字段名与真身逐字一致，因此 ``dataclasses.asdict`` 的下游代码（写库前的
    序列化）在两种情况下行为相同——替身不会污染真实快照的结构。
    """

    start: int
    end: int
    label: str


def _format_page_label(start: int, end: int) -> str:
    """生成 §1.4 的 ``page_range.label``：单页 ``p. 2``，跨页 ``pp. 45–46``。"""
    if start == end:
        return f"p. {start}"
    return f"pp. {start}\u2013{end}"  # U+2013 半字线，与 DESIGN.md 示例一致


def make_page_range(start: int, end: int, label: str | None = None) -> Any:
    """构造 ``PageRange``（优先真身，缺失时用 :class:`_SimplePageRange`）。

    运行期不做类型检查（鸭子类型）：只要下游拿到的对象有 ``.start`` /
    ``.end`` / ``.label``、且能被 ``asdict``，行为就一致。这样 llm.py 与
    schema.py 之间没有硬依赖，两者可以并行开发、各自单测。
    """
    if start > end:  # 写反了就修正，避免下游 page_range.start <= end 不变量被破
        start, end = end, start
    start = max(1, int(start))
    end = max(start, int(end))
    text_label = label or _format_page_label(start, end)
    try:
        from .schema import PageRange as _PR
    except Exception:
        try:
            from agentflow.schema import PageRange as _PR  # type: ignore[no-redef]
        except Exception:
            _PR = None  # type: ignore[assignment]
    if _PR is not None:
        try:
            return _PR(start=start, end=end, label=text_label)
        except Exception:
            # 真身签名与预期不符时继续用替身，保证本模块自身可用。
            logger.debug("schema.PageRange 构造失败，退回 _SimplePageRange", exc_info=True)
    return _SimplePageRange(start=start, end=end, label=text_label)


# --------------------------------------------------------------------------- #
# §4.1 数据契约
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConceptDraft:
    """概念草稿。``source_lit_id`` 对应当前处理的文献（§1.3 的
    ``definition_source_lit_id``）——概念定义必须能追溯来源，否则无法复核。"""

    name: str
    definition: str
    aliases: list[str]
    source_lit_id: str


@dataclass(frozen=True)
class RelationDraft:
    """关系草稿。

    - ``concept_names``：松散输入（名字，不是 ID）。解析成 ``concept_id``、
      必要时新建概念，是 agent_b 的职责（§6.1 第 4 步）——抽取器不该知道
      也不会去碰 ID 分配和锁。
    - ``quote``：必须是原文逐字子串（§6.3 / C6）。这是整个设计里唯一能
      把"关系描述忠于参考文献"从口号变成质量门的东西，所以本模块对它的
      保证方式写在每个抽取器的 docstring 里，而不是靠"相信模型"。
    - ``page_range``：鸭子类型对象（``.start`` / ``.end`` / ``.label``）。
      标注为 ``PageRange`` 但运行期不做 isinstance 检查，见
      :func:`make_page_range`。
    """

    concept_names: list[str]
    description: str
    quote: str
    page_range: Any


@runtime_checkable
class Extractor(Protocol):
    """§4.1 契约：``extract(doc, lit_id, meta) -> (concepts, relations)``。

    ``runtime_checkable``：让 agent_b 的测试可以用 ``isinstance(obj, Extractor)``
    做一次廉价的结构检查（只校验方法名存在性，不做签名校验——签名错误由
    类型检查器保证）。
    """

    def extract(
        self, doc: "DocumentText", lit_id: str, meta: dict
    ) -> tuple[list[ConceptDraft], list[RelationDraft]]:
        ...


class ExtractionError(RuntimeError):
    """抽取失败（LLM 返回不可解析、schema 不符等）。"""


# --------------------------------------------------------------------------- #
# RuleExtractor：离线确定性基线
# --------------------------------------------------------------------------- #

#: 中文定义句式：``X 是/称为/叫做/定义为 Y``。
#: 主语限制在 1..30 字且不含句读，避免把整句当成概念名。
_ZH_DEF_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<name>[^，。；：、,.;:!?()（）\s][^，。；：、,.;:!?()（）]{0,29}?)\s*"
    r"(?:是|称为|叫做|叫作|指的是|定义为|又称|即)\s*"
    r"(?P<definition>\S.{0,300})$"
)

#: 英文定义句式。顺序即优先级：``is called`` / ``is defined as`` 比 ``is a``
#: 更专指，先匹配可避免 "…is defined as a group…" 被 ``is a`` 截断。
_EN_DEF_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(
            r"^(?P<head>[^,;:]{1,60}?)\s+is\s+(?:called|known\s+as|termed)\s+"
            r"(?P<definition>\S.{1,300})$",
            re.IGNORECASE,
        ),
        "called",
    ),
    (
        re.compile(
            r"^(?P<head>[^,;:]{1,60}?)\s+is\s+defined\s+as\s+"
            r"(?P<definition>\S.{1,300})$",
            re.IGNORECASE,
        ),
        "defined_as",
    ),
    (
        re.compile(
            r"^(?P<head>[^,;:]{1,60}?)\s+is\s+"
            r"(?P<definition>(?:a|an)\s+\S.{1,300})$",
            re.IGNORECASE,
        ),
        "is_a",
    ),
    (
        re.compile(
            r"^(?P<head>[^,;:]{1,60}?)\s+(?:refers\s+to|means)\s+"
            r"(?P<definition>\S.{1,300})$",
            re.IGNORECASE,
        ),
        "refers_to",
    ),
)

#: 主语开头的冠词，剥掉后概念名更干净（"An abelian group" → "abelian group"）。
_ARTICLE_RE: Final[re.Pattern[str]] = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)

#: 不像术语的主语（代词等）。命中即放弃该句，宁可漏抽也不伪造概念名。
_EN_STOP_SUBJECTS: Final[frozenset[str]] = frozenset(
    {"it", "this", "that", "there", "these", "those", "he", "she", "they", "we", "one", "which"}
)

#: 按句末标点切句，保留标点。用 ``finditer`` 而不是 ``split``：只有拿到
#: span 才能保证切出来的句子是原页文本的连续切片（quote 逐字性的基础）。
_SENTENCE_RE: Final[re.Pattern[str]] = re.compile(r"[^.!?。！？\n]+[.!?。！？]?", re.UNICODE)


def _looks_like_term(name: str) -> bool:
    """判断候选主语是否像个"概念名"而不是半句话。

    这是 RuleExtractor 精度的主要闸门。规则刻意保守：宁可漏（少抽一条关系），
    不可错（把 "It is a well known fact" 里的 "It" 变成概念）。
    """
    name = name.strip()
    if not name or len(name) > 60:
        return False
    if re.search(r"[，。；：、,.;!?]", name):
        return False
    words = name.split()
    if len(words) > 6:
        return False
    if len(words) == 1 and words[0].casefold() in _EN_STOP_SUBJECTS:
        return False
    # 中文名：1..20 字（含空格也算，中文术语里偶有空格）
    if len(name) > 20 and " " not in name:
        return False
    return True


def _match_definition(sentence: str) -> tuple[str, str] | None:
    """从一句里抽出 ``(概念名, 定义文本)``；不是定义句则返回 ``None``。"""
    text = sentence.strip()
    if not text:
        return None

    m = _ZH_DEF_RE.match(text)
    if m:
        name = m.group("name").strip()
        definition = m.group("definition").strip()
        if _looks_like_term(name) and definition:
            return name, definition

    for pattern, _kind in _EN_DEF_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        head = m.group("head").strip()
        head = _ARTICLE_RE.sub("", head).strip()
        definition = m.group("definition").strip().rstrip(".")
        if _looks_like_term(head) and definition:
            return head, definition
    return None


def _iter_sentences(page_text: str) -> Iterable[tuple[int, int, str]]:
    """切句，产出 ``(start, end, sentence)``。

    ``sentence`` 是 ``page_text[start:end]`` 经过 ``strip`` 的结果——仍是
    原串的连续子串，这一点是 RuleExtractor 能保证 quote 逐字命中的根基，
    改这里务必小心。
    """
    for m in _SENTENCE_RE.finditer(page_text):
        raw = m.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        offset = raw.index(stripped) if stripped != raw else 0
        yield m.start() + offset, m.start() + offset + len(stripped), stripped


class RuleExtractor:
    """规则基线：定义句式 + ``meta['seed_concepts']``，全程离线、确定性。

    ## ⚠️ 它是**框架的回退**，`AgentB` 默认会**拒抽**（`R-56`，`draft/28` §157）

    实测（`projects/p2-review`）：无 LLM 时靠它抽取，会往概念图里灌碎片
    （`ANU` / `cingled property` / `Ultimately this`），而 `quote_verified=True`
    让那些碎片看起来有证据 —— "引文回验只证明这句话在文件里，不证明这是一个概念"。
    所以 `AgentB` 见到**本类**（判据：`is_framework_fallback`）就跳过并记
    `last_mine_error="no_llm_extractor"`，一行概念都不写。

    想要"显式选择离线基线"（演示 / 单测 / 自检）请用
    :class:`OfflineFixtureExtractor` —— 它与本类同行为，但**声明自己不是回退**，
    于是那次选择是**调用方明确点名**的，而不是框架悄悄替你选的。

    产出策略：

    1. 概念来自两处——
       a) ``meta["seed_concepts"]``（形如 ``[{"name":…, "definition":…,
          "aliases":[…]}]``）。调用方显式给了种子，就一定尊重它：这是
          "可测试基线"最可靠的部分，也让 demo 不依赖自动抽取的质量。
       b) 正文里的定义句式（中英各一套，见 :data:`_ZH_DEF_RE` /
          :data:`_EN_DEF_PATTERNS`）。
    2. 关系由定义句同时产出：``concept_names = [被定义概念] + 同句中出现的
       其它已知概念``，``quote`` 就是那个定义句本身（逐字）。同一句只产出一条
       （``quote`` 为去重键），避免同一句话因为多个已知概念命中而产生重复行。
    3. ``description`` 直接用原句（RuleExtractor 不做翻译/转写）。§9 待决
       问题 1（description 用中文还是英文）尚无定论，基线里任何"自作的
       转写"都会变成需要审计的额外假设；用原句最忠实，也让测试断言简单。
       ``statement`` 的规范化留给 agent_b。

    已知局限（刻意保留、不做掩饰）：

    - 只会定义句式，抽不到"定理式"关系（"若 X 则 Y"）。这是基线的本分。
    - 多词概念靠子串匹配已知名，可能出现 "group" 被 "abelian group" 顺带
      命中的情况；本类通过"先把被定义概念自身的出现删掉再找其它概念"
      做了缓解，但不追求消灭它。
    - ``concept_names`` 可能只有 1 个元素（句中确实没提及其它已知概念）。
      这种 draft 会被 §6.1 第 5 步的 ``len(concept_ids) >= 2`` 拦下——
      这个过滤是 agent_b 的职责，本类不代替它做决定，以免两个模块对
      "什么算有效关系"各持一套标准。
    """

    #: `AgentB` 用它判"这是不是框架在无 LLM 时替你选的回退"（`R-56`）。
    #: 判据是**声明**而不是类名：按类名判会被一个"改个名字的复制品"绕过，
    #: 而声明式判据要绕过就必须显式写一句"我不是回退"（`OfflineFixtureExtractor`
    #: 就是那样写的，并且它带理由）。
    is_framework_fallback = True

    #: 无文本层时，本抽取器不做任何猜测（返回空），使 §6.3 的
    #: "因无文本层未能校验"成为一句可核查的事实，而不是靠报告口径。
    def __init__(self, *, max_relations: int = 500) -> None:
        self.max_relations = max_relations

    # -- 内部工具 ---------------------------------------------------------- #

    @staticmethod
    def _seed_concepts(meta: dict | None) -> list[dict[str, Any]]:
        """读取并粗校验 ``meta['seed_concepts']``。坏数据跳过而非整篇失败。"""
        if not isinstance(meta, dict):
            return []
        raw = meta.get("seed_concepts")
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            definition = str(item.get("definition") or "").strip()
            aliases_raw = item.get("aliases") or []
            aliases = (
                [str(a).strip() for a in aliases_raw if str(a).strip()]
                if isinstance(aliases_raw, list)
                else []
            )
            out.append({"name": name, "definition": definition, "aliases": aliases})
        return out

    @staticmethod
    def _occurrences(sentence: str, name: str) -> bool:
        """``name`` 是否作为"词"出现在 ``sentence`` 中（大小写不敏感）。

        英文用词边界，避免 "group" 命中 "groupoid" 这类假阳性；中文没有
        词边界概念，直接子串匹配。
        """
        if not name:
            return False
        if re.fullmatch(r"[\x00-\x7f]+", name):  # 纯 ASCII ⇒ 走词边界匹配
            pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
            return re.search(pattern, sentence, re.IGNORECASE) is not None
        return name in sentence

    def extract(
        self, doc: "DocumentText", lit_id: str, meta: dict
    ) -> tuple[list[ConceptDraft], list[RelationDraft]]:
        """见 §4.1。无文本层（``pages == []``）时返回 ``([], [])``。"""
        seeds = self._seed_concepts(meta)

        # ---- 概念：种子优先 -------------------------------------------------
        concepts: list[ConceptDraft] = []
        seen_names: set[str] = set()  # 规范化名去重（§3.4 的 normalized_name 口径）

        def _norm(name: str) -> str:
            return unicodedata.normalize("NFC", name).casefold().strip()

        for seed in seeds:
            key = _norm(seed["name"])
            if key in seen_names:
                continue
            seen_names.add(key)
            concepts.append(
                ConceptDraft(
                    name=seed["name"],
                    definition=seed["definition"],
                    aliases=list(seed["aliases"]),
                    source_lit_id=lit_id,
                )
            )

        # ---- 概念：定义句式（不回填种子已覆盖的名字，避免重复行） ----------
        # mined 记录 (概念名, 定义, 页码, quote)，供第二步产关系。
        mined: list[tuple[str, str, int, str]] = []
        if doc.pages:
            for page_idx, page_text in enumerate(doc.pages):
                for _s, _e, sentence in _iter_sentences(page_text):
                    hit = _match_definition(sentence)
                    if hit is None:
                        continue
                    name, definition = hit
                    key = _norm(name)
                    if key not in seen_names:
                        seen_names.add(key)
                        concepts.append(
                            ConceptDraft(
                                name=name,
                                definition=definition,
                                aliases=[],
                                source_lit_id=lit_id,
                            )
                        )
                    mined.append((name, definition, page_idx + 1, sentence))

        # ---- 关系 -----------------------------------------------------------
        # 已知概念表：别名 → 规范名。种子与正文挖掘出的概念都算"已知"——
        # 一句里同时定义了 A 并用到了本页刚定义过的 B，这也是真实关系。
        known: dict[str, str] = {}
        for c in concepts:
            known.setdefault(_norm(c.name), c.name)
            for alias in c.aliases:
                known.setdefault(_norm(alias), c.name)

        relations: list[RelationDraft] = []
        seen_quotes: set[str] = set()
        for name, _definition, page_no, sentence in mined:
            if len(relations) >= self.max_relations:
                logger.warning("RuleExtractor 达到 max_relations=%d，停止抽取关系", self.max_relations)
                break
            quote = sentence  # 逐字：来自 _iter_sentences 的原页切片
            if quote in seen_quotes:
                continue  # 同一句只产一条（去重键 = quote）

            # 先挖掉被定义概念自身的出现，再找其它已知概念：
            # 否则 "abelian group is a group …" 会把 "group" 算成"另一个概念"。
            probe = re.sub(re.escape(name), " ", sentence, flags=re.IGNORECASE)
            others: list[str] = []
            for key, canonical in known.items():
                if key == _norm(name):
                    continue
                if self._occurrences(probe, canonical) or (
                    key != _norm(canonical) and self._occurrences(probe, key)
                ):
                    if canonical not in others:
                        others.append(canonical)

            seen_quotes.add(quote)
            relations.append(
                RelationDraft(
                    concept_names=[name, *others],
                    description=quote,  # 基线不做转写，理由见类 docstring 第 3 条
                    quote=quote,
                    page_range=make_page_range(page_no, page_no),
                )
            )

        logger.debug(
            "RuleExtractor: lit=%s pages=%d concepts=%d relations=%d",
            lit_id,
            len(doc.pages),
            len(concepts),
            len(relations),
        )
        return concepts, relations


# --------------------------------------------------------------------------- #
# LLMExtractor：可插拔（本机不实跑）
# --------------------------------------------------------------------------- #

#: 完整可用的抽取提示词模板。
#:
#: 占位符刻意用 ``{LIT_ID}`` / ``{DOCUMENT_TEXT}`` 这种全大写花括号，
#: 并用 ``str.replace`` 而不是 ``str.format`` 渲染：模板正文里全是 JSON 花括号，
#: 用 ``format`` 就得把所有 ``{`` 写成 ``{{``，任何一次手改模板都可能漏掉一个，
#: 变成线上才炸的 KeyError/ValueError。
DEFAULT_PROMPT_TEMPLATE: Final[str] = """\
你是文献知识抽取器。请从下面给出的文献正文中抽取"概念"与"概念间关系"。

【文献标识】{LIT_ID}

【输入正文】
正文按页给出，页与页之间用形如 <<<PAGE 3>>> 的行分隔。
这些分隔行是定位标记，不属于文献内容，绝对不要把它们写进 quote。

--- BEGIN DOCUMENT ---
{DOCUMENT_TEXT}
--- END DOCUMENT ---

【输出格式】只输出一个 JSON 对象，不要任何解释性文字，不要 Markdown 围栏：

{
  "concepts": [
    {
      "name": "概念名（尽量用正文中出现的原词，不要自行翻译）",
      "definition": "该概念的定义（可以是正文原句的紧致改写）",
      "aliases": ["正文中出现的异名/缩写，没有就给空数组"],
      "page": 1
    }
  ],
  "relations": [
    {
      "concept_names": ["概念A", "概念B"],
      "description": "这条关系说了什么（用你自己的话陈述）",
      "quote": "支撑该关系的原文，必须逐字照抄",
      "page_range": {"start": 1, "end": 1}
    }
  ]
}

【硬性规则，违反会导致整条记录被丢弃】
1. relations[].quote 必须是输入正文里**逐字出现**的一段连续文字。
   允许的差异只有：首尾空白、句内换行、大小写。
   不要改写、不要翻译、不要用省略号截断、不要拼接不连续的两段文字。
2. **如果你无法在正文里逐字找到支撑某条关系的原句，就不要输出这条关系。**
   少输出一条关系是可接受的；编造引文是不可接受的，它会被自动校验剔除。
3. relations[].page_range 必须标出该引文所在的页（依据 <<<PAGE n>>> 标记），
   1-based、闭区间、start <= end。引文跨页时用跨页区间。
   注意：这里的页码一律指 <<<PAGE n>>> 里的 n，也就是这一段正文被切给
   你时的序号；不要用书里印在页眉页脚上的那个页码。两者常常不相等：
   一本有前言/目录/封面的书里，"印着第 3 页"的那一页很可能是 <<<PAGE 8>>>。
   实测（2026-09-28）：一本书的前 12 条关系全部按"印着的页码"报，恒定比
   <<<PAGE n>>> 小 5，于是全部被逐字回验判为 not_found（引文是真的，页码是错的）。
   判据：`<<<PAGE n>>>` 就在你眼前的正文里，印着的页码得你自己去认 —— 用眼前的那个。
4. relations[].concept_names 至少给出 2 个概念名；只有一个概念时不输出该关系。
5. 概念名要与正文用词一致（英文正文就用英文名），不要输出空名或纯符号名。
6. 没有可抽取内容时输出 {"concepts": [], "relations": []}。
7. 条数上限：概念最多 12 条、关系最多 12 条。挑最能代表这段正文的，宁可少而准。
   这条上限不是口味问题：输出的 JSON 一旦超过模型单次回复的 token 上限，就会被截在
   半句上，整次抽取因解析失败而作废（连已经正确的条目也一起丢掉）。
   实测（2026-09-28）：一本 417 页的书连读两次都栽在这里（`Expecting ',' delimiter`），
   把上限从"不限制"收到 12 条之后就不再触发。
8. page_range 里填的是 <<<PAGE n>>> 的 n（见第 3 条），**不是**书里印的页码。
   把第 3 条再强调一次是因为它错得最贵：引文逐字正确、页码错 5 页，回验照样判
   not_found，而读者从产物上看到的是"这条关系的出处找不到"。
"""


def _nfkc_clusters(text: str) -> Iterator[tuple[str, int, int]]:
    """把 ``text`` 切成"必须一起做 NFKC 的簇"，逐簇产出 ``(规范化片段, 起, 止)``。

    为什么不能逐字符做 NFKC：NFKC 是上下文相关的，而逐字符规范化会
    把"规范化后等价"的两串判成不同。最典型的失败是组合记号：

        text  = "Spe\\u0301ctrum"（s p e + 组合尖音符 …，PDF/LaTeX 常见的分解形）
        quote = "Sp\\u00e9ctrum" （预组合的 é）
        unicodedata.normalize("NFKC", text) == unicodedata.normalize("NFKC", quote)  # True！

    但逐字符规范化后前者里的 ``e``+``´`` 仍是两个字符，后者是一个 ``é``，
    于是一句真的引文会被判成幻觉并被剔除（``_ground_relations`` 的
    ``quote_not_found``）——这正是本模块唯一自动幻觉防线最不能出的错，
    而且它不出声：报告里只会多一条"疑似幻觉"的计数。

    簇的边界用 ``NFC`` 探测"相邻两字符会不会合成"（合成后串变短/变不同），
    这比列举 Unicode 组合类更通用：组合记号、Hangul Jamo 都能被它覆盖。
    """
    i = 0
    n = len(text)
    while i < n:
        j = i + 1
        # 只要"前一字符 + 当前字符"还能合成出别的东西，就必须留在同一个簇里。
        while j < n and unicodedata.normalize("NFC", text[j - 1 : j + 1]) != text[j - 1 : j + 1]:
            j += 1
        yield unicodedata.normalize("NFKC", text[i:j]), i, j
        i = j


def _normalize_with_spans(text: str) -> tuple[str, list[tuple[int, int]]]:
    """生成"折叠空白 + NFKC + 大小写折叠"后的文本，并保留每个字符的原文区间。

    返回 ``(normalized, spans)``，其中 ``spans[i] = (start, end)`` 是
    ``normalized[i]`` 在 ``text`` 中对应的原始字符区间 ``text[start:end]``。

    为什么需要它：LLM 抄引文时最常见的差异是把 PDF 的换行抄成了空格
    （PDF 抽取出来的句子常常带 ``\\n``）。§6.3 允许"空白折叠"这种差异，
    所以这种引文在规范意义上是合格的。但如果原样存进 ``quote`` 字段，
    它就不是 ``doc.text`` 的逐字子串了——§6.3 的字面要求会被破，也会让
    "quote 必须是子串"这条本模块的红线失效。
    用这张区间映射，可以把模型给的引文投影回原文的确切切片，
    从而让存下去的 quote 同时满足"规范化后等价"与"字面上就是子串"。

    为什么是"区间"而不是单独的起始下标：一个规范化后的字符可能来自多个
    原始字符（``é`` ← ``e``+组合尖音符、``가`` ← 两个 Jamo），只记起始下标
    会在算切片末尾时把这类字符截成半个，切出来的东西反而不是原文子串。
    """
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    pending_space = False
    for piece, start, end in _nfkc_clusters(text):
        for sub in piece.casefold():
            # 软连字符是零宽格式字符：它在视觉上不存在，只标记"这里可断行"。
            # 早先的实现把它当成空白 ⇒ 凭空插入一个空格
            # （"abel\u00adian" → "abel ian"），于是 PDF 断词处的真引文永远匹配不上，
            # 被幻觉防线判成"编造的引文"剔除。正确处置是删掉它（不插入任何字符）：
            # 引用里写的字面文本在原文里仍然逐字存在，只是中间少了一个不可见控制符。
            if sub == "\u00ad":
                continue
            if sub.isspace():
                pending_space = True
                continue
            if pending_space and out:
                out.append(" ")
                # 插入的空格不对应原文任何字符 ⇒ 零宽区间。它不可能成为匹配的
                # 首字符（引文的首尾空白在规范化里被丢掉），所以这个区间不会被用来切片。
                spans.append((start, start))
            pending_space = False
            out.append(sub)
            spans.append((start, end))
    return "".join(out), spans


def _locate_verbatim(text: str, quote: str) -> str | None:
    """在 ``text`` 中定位 ``quote``，返回原文里的确切切片；定位不到返回 ``None``。

    两级匹配（对应 §6.3 允许的差异范围）：

    1. 直接子串命中（最常见，零成本）；
    2. 规范化后命中（空白折叠 / 大小写 / NFKC 全半角与连字符归一化，
       并把软连字符当作零宽字符删除），再经区间映射还原成原文切片。

    返回原文切片而不是原样返回 ``quote``，是本模块 fail-closed 设计的一半：
    调用方拿到的东西天然是 ``text`` 的子串，不需要再相信谁。

    规范化必须整簇做 NFKC（见 :func:`_nfkc_clusters`）：逐字符做会把
    "``e``+组合尖音符"与"``é``"判成两串，从而把真引文判成幻觉。
    """
    if not quote:
        return None
    if quote in text:
        return quote
    norm_doc, spans = _normalize_with_spans(text)
    norm_quote, _ = _normalize_with_spans(quote)
    if not norm_quote:
        return None
    pos = norm_doc.find(norm_quote)
    if pos < 0:
        return None
    start = spans[pos][0]
    # 末尾用区间右端而不是"起始下标 + 1"：一个规范化字符可能来自多个原文
    # 字符，用 +1 会把 "é"（来自 "e"+组合记号）切掉一半。
    end = spans[pos + len(norm_quote) - 1][1]
    return text[start:end]


def _strip_code_fence(raw: str) -> str:
    """去掉 ```json … ``` 围栏（模型最常见的"多余装饰"）。"""
    text = raw.strip()
    fence = re.match(r"^```[A-Za-z0-9_+-]*\s*\n(?P<body>.*?)\n?```\s*$", text, re.DOTALL)
    if fence:
        return fence.group("body").strip()
    # 只有开头围栏、结尾没闭合的情况也容忍
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9_+-]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def parse_llm_json(raw: str) -> dict[str, Any]:
    """宽松解析 LLM 返回的 JSON 对象。

    容忍：```json 围栏、前后寒暄文字（截取首个 ``{`` 到末个 ``}``）、
    数组/对象结尾的多余逗号。
    最终仍解析不出对象就抛 :class:`ExtractionError`——注意这里是
    "解析失败即失败"，不做"从文本里猜几个概念"的补救：抽取结果直接进库，
    猜出来的东西会污染概念表且无法追溯。
    """
    text = _strip_code_fence(raw)
    if not text:
        raise ExtractionError("LLM 返回为空，无法解析 JSON")

    candidates = [text]
    # 退一步：截取第一个 { 到最后一个 } 之间的内容（对付前后解说文字）。
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        for repaired in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = ExtractionError(f"LLM 返回的 JSON 顶层不是对象: {type(parsed).__name__}")
    raise ExtractionError(f"无法把 LLM 返回解析为 JSON 对象: {last_error}") from last_error


class LLMExtractor:
    """把任意 ``.complete(prompt) -> str`` 客户端适配成 :class:`Extractor`。

    刻意不依赖任何厂商 SDK、不做重试与限速（那是 client 的职责）：本类只关心
    "怎么问"和"怎么不信"两件事。

    本机不实跑（无 API key，也不该在单测里打网络）。因此这里的正确性
    全部围绕"LLM 会怎么骗我们"来设计，见 ``_ground_relations``。
    """

    def __init__(
        self,
        client: Any,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        *,
        max_chars: int = 60_000,
        max_relations: int = 500,
    ) -> None:
        if not hasattr(client, "complete"):
            raise TypeError("client 必须提供 complete(prompt: str) -> str 方法")
        self.client = client
        self.prompt_template = prompt_template
        # 字符上限：LLM 有上下文窗口，超长输入必须显式截断或拒绝。这里
        # 选择"截断到 max_chars"并记录在 report 里，因为对 LLM 抽取而言
        # 少读几页只是召回下降，不会产生假事实；而抛异常会让整篇文献卡住。
        self.max_chars = max_chars
        self.max_relations = max_relations
        # 剔除计数在 __init__ 里先置零：_ground_relations 之外若有人读
        # last_report（例如无文本层提前返回的路径），不会 AttributeError。
        self._dropped_count: int = 0
        self._drop_reasons: list[str] = []
        #: 最近一次抽取的审计信息（保留/剔除的计数与原因）。
        #: 之所以挂在实例上而不是只写日志：agent_b 的报告要统计
        #: "有多少条关系因引文无法回验被剔除"，这本身就是防幻觉的指标。
        self.last_report: dict[str, Any] = {}

    # -- prompt ------------------------------------------------------------ #

    def build_prompt(self, doc: "DocumentText", lit_id: str) -> tuple[str, bool]:
        """渲染提示词，返回 ``(prompt, truncated)``。

        正文以 ``<<<PAGE n>>>`` 标记逐页拼接，而不是直接塞 ``doc.text``：
        模型必须知道"第几页"，否则 ``page_range`` 只能靠猜，§6.3 的
        "±1 页扩大窗口"就永远命中不了。标记行独占一行，因此任一页内的文字
        仍是 ``doc.text`` 的连续子串——引文回验不受影响。
        """
        if doc.pages:
            body = "\n".join(
                f"<<<PAGE {i + 1}>>>\n{page}" for i, page in enumerate(doc.pages)
            )
        else:
            body = doc.text

        truncated = False
        if len(body) > self.max_chars:
            body = body[: self.max_chars]
            truncated = True

        # 用 replace 而非 format：模板含大量 JSON 花括号，理由见模板注释。
        prompt = (
            self.prompt_template.replace("{LIT_ID}", str(lit_id))
            .replace("{DOCUMENT_TEXT}", body)
        )
        return prompt, truncated

    # -- extract ----------------------------------------------------------- #

    def extract(
        self, doc: "DocumentText", lit_id: str, meta: dict
    ) -> tuple[list[ConceptDraft], list[RelationDraft]]:
        """见 §4.1。

        fail-closed 总原则：任何无法在原文里回验的产出都不进入下游。

        - 无文本层（``doc.pages == []``）⇒ 直接返回空。不调用 LLM，是因为
          没有正文可引用，模型只能靠标题/元数据编故事；而 §6.3 明确要求
          这种情况记 "未能校验" 而不是硬凑结果。
        - ``quote`` 回验失败 ⇒ 剔除该条关系并计数（``_ground_relations``）。
        """
        if not doc.pages or not doc.text.strip():
            self._dropped_count = 0
            self._drop_reasons = []
            self.last_report = {
                "lit_id": lit_id,
                "skipped": "no_text_layer",
                "truncated": False,
                "concepts": 0,
                "relations_kept": 0,
                "relations_dropped": 0,
                "drop_reasons": [],
            }
            logger.info("LLMExtractor: 文献 %s 无文本层，跳过抽取（§6.3）", lit_id)
            return [], []

        prompt, truncated = self.build_prompt(doc, lit_id)
        raw = self.client.complete(prompt)
        payload = parse_llm_json(raw)

        concepts = self._build_concepts(payload, lit_id)
        relations = self._ground_relations(payload, doc)

        self.last_report = {
            "lit_id": lit_id,
            "truncated": truncated,
            "concepts": len(concepts),
            "relations_kept": len(relations),
            "relations_dropped": self._dropped_count,
            "drop_reasons": list(self._drop_reasons),
        }
        return concepts, relations

    # -- 内部：构建与回验 --------------------------------------------------- #

    def _build_concepts(
        self, payload: dict[str, Any], lit_id: str
    ) -> list[ConceptDraft]:
        """把 ``concepts`` 数组转成 draft，顺手丢掉空名条目。"""
        raw = payload.get("concepts")
        if not isinstance(raw, list):
            return []
        out: list[ConceptDraft] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            key = unicodedata.normalize("NFC", name).casefold()
            if key in seen:
                continue
            seen.add(key)
            aliases_raw = item.get("aliases") or []
            aliases = (
                [str(a).strip() for a in aliases_raw if str(a).strip()]
                if isinstance(aliases_raw, list)
                else []
            )
            out.append(
                ConceptDraft(
                    name=name,
                    definition=str(item.get("definition") or "").strip(),
                    aliases=aliases,
                    source_lit_id=lit_id,
                )
            )
        return out

    def _coerce_page_range(self, raw: Any, doc: "DocumentText") -> Any:
        """把 LLM 给的 ``page_range`` 收束到合法区间；缺失时退化为首末页。

        为什么缺失时用 ``(1, len(pages))`` 而不是 ``(1, 1)``：模型偶尔会漏
        ``page_range``，此时把页码钉死在第 1 页会让 §6.3 的 ±1 页重试也救不
        回来（引文可能在第 40 页）；给一个"整篇"的宽区间让引文校验仍有机会
        命中。注意这不会降低校验严格性——quote 本身必须逐字存在于原文，
        放宽的只是"在哪一页"的定位精度，而精度问题会在报告里被看见。
        """
        total = max(1, len(doc.pages))
        if isinstance(raw, dict):
            try:
                start = int(raw.get("start"))
            except (TypeError, ValueError):
                start = 1
            try:
                end = int(raw.get("end", start))
            except (TypeError, ValueError):
                end = start
        else:
            start = end = 1
        start = min(max(1, start), total)
        end = min(max(1, end), total)
        label = raw.get("label") if isinstance(raw, dict) else None
        return make_page_range(start, end, str(label) if label else None)

    def _ground_relations(
        self, payload: dict[str, Any], doc: "DocumentText"
    ) -> list[RelationDraft]:
        """本模块最重要的一段：逐条回验 LLM 给的 quote，验不过就剔除。

        为什么必须回验（而不是"相信模型/相信提示词"）：

        §6.3 把"完全引用参考文献"做成了质量门，前提是 quote 真的能在原文里
        找到。LLM 天然会做三件事——改写、翻译、以及最危险的凭常识编一句
        听起来像原文的话。这三种失败在文本层面无法与真实引文区分，
        只能靠"回到原文里找一遍"来判定。提示词里写"不要编造"是降低概率，
        回验是消除后果：编造的 quote 永远不会进库，因此
        ``quote_verified`` 这个字段的含义始终是"我们真的核对过"。

        这里刻意选择 剔除该条 而不是"标记为 suspect 后照样入库"：
        下游 agent_b 会对拿到的 draft 再跑一次 §6.3 并给出 ``quote_verified``，
        如果本层把可疑条目混进去，报告里"校验失败"的数字就会同时包含
        "模型幻觉"和"页码窗口没给对"两种完全不同的原因，无法归因。
        剔除 + 计数让这两件事在 ``last_report`` 里各自可数。

        （另一条同样合法的路线是"保留但打标"，由 agent_b 统一裁决。本实现
        选剔除，是因为 draft 层没有任何持久化身份，打标没有地方存。）
        """
        raw_relations = payload.get("relations")
        self._dropped_count = 0
        self._drop_reasons: list[str] = []
        if not isinstance(raw_relations, list):
            return []

        out: list[RelationDraft] = []
        seen_quotes: set[str] = set()
        for item in raw_relations:
            if len(out) >= self.max_relations:
                logger.warning("LLMExtractor 达到 max_relations=%d，停止接收关系", self.max_relations)
                break
            if not isinstance(item, dict):
                self._record_drop("not_an_object")
                continue

            quote_raw = str(item.get("quote") or "")
            verbatim = _locate_verbatim(doc.text, quote_raw)
            if verbatim is None:
                # 幻觉或抄错 ⇒ 剔除。这就是防幻觉的关键一步。
                self._record_drop("quote_not_found")
                logger.warning(
                    "剔除引文无法回验的关系（疑似幻觉）: lit=%s quote=%r",
                    getattr(doc, "source_kind", "?"),
                    quote_raw[:80],
                )
                continue

            names_raw = item.get("concept_names")
            names: list[str] = []
            if isinstance(names_raw, list):
                for n in names_raw:
                    text = str(n).strip()
                    if text and text not in names:
                        names.append(text)
            if len(names) < 2:
                # §6.1 第 5 步要求 concept_ids >= 2；只有一个概念时这条关系
                # 表达不了任何"关系"，剔除比让它到下游被丢弃更省事。
                self._record_drop("too_few_concepts")
                continue

            if verbatim in seen_quotes:
                self._record_drop("duplicate_quote")
                continue
            seen_quotes.add(verbatim)

            description = str(item.get("description") or "").strip() or verbatim
            out.append(
                RelationDraft(
                    concept_names=names,
                    description=description,
                    # 存投影回原文的切片而不是模型原文：保证 §6.3 的字面
                    # 子串要求与"规范化后等价"同时成立。见 _locate_verbatim。
                    quote=verbatim,
                    page_range=self._coerce_page_range(item.get("page_range"), doc),
                )
            )
        return out

    def _record_drop(self, reason: str) -> None:
        self._dropped_count += 1
        self._drop_reasons.append(reason)


class NullExtractor:
    """什么都不抽。用于管线冒烟测试与"只跑 A 不跑 B"的场合。

    存在的意义：让 agent_b 可以在"抽取器返回空"这条合法路径上被测试
    （而不是用 mock 去伪造一个空返回值），从而验证"没有关系时也要正确置
    ``processed=true``"这类容易漏的分支。
    """

    def extract(
        self, doc: "DocumentText", lit_id: str, meta: dict
    ) -> tuple[list[ConceptDraft], list[RelationDraft]]:
        return [], []


class OfflineFixtureExtractor(RuleExtractor):
    """**显式选择的**离线确定性抽取器（演示 / 单测 / 自检用）。

    ## 它与 :class:`RuleExtractor` 的唯一差别是"谁选的"

    `RuleExtractor` 是框架在**没有 LLM 时替你选**的回退 ⇒ `AgentB` 拒抽（`R-56`：
    它会往概念图里灌 `ANU` / `cingled property` 这类碎片，而 `quote_verified=True`
    让碎片看起来有证据）。

    本类**行为完全相同**（同一个实现，只是改了一个声明），差别只有一处：
    `is_framework_fallback = False` ⇒ `AgentB` 认为"这是调用方点名要的抽取器"，
    于是照常抽取。这条差异是**刻意的**：

    - 演示（`demo.py`）与单测需要一个**离线、确定性**的抽取器来把 A→B→校验整条
      链路真跑一遍 —— 它们点名要的就是这个；
    - 而"没有 LLM 就悄悄用它"这件事必须被挡住 —— 那正是 `R-56` 的形态。

    换句话说：**允许人明确选择一条已知较弱的路径，不允许框架在被问到时假装
    那条路径没有被选过。** 用它写出来的概念/关系仍然只该出现在演示、单测与自检
    （临时工作区）里；真实项目里想要概念图，请接 `LLMExtractor`。
    """

    is_framework_fallback = False


# --------------------------------------------------------------------------- #
# 自检：python -m agentflow.extract / python -m agentflow.llm
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    # 运行方式：在 src/ 下执行 `python -m agentflow.llm`（或设 PYTHONPATH=src 后在任意目录执行）
    # （本文件即 __main__，因此模块级名字 RuleExtractor/LLMExtractor 等可直接用，
    #   不要再 `from .llm import ...`，否则会加载出第二份模块实例。）
    import sys
    from dataclasses import asdict, is_dataclass
    from pathlib import Path

    try:  # Windows 控制台/管道下强制 utf-8，避免中文输出报编码错
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    # 跨模块导入只用到 extract（本仓库自有的轻量模块），不触碰 schema/store。
    from .extract import (  # type: ignore[import-not-found]
        ExtractTooLarge,
        UnsupportedFormat,
        extract_text,
        page_count,
    )

    DEMO = Path(__file__).resolve().parents[2] / "demo" / "selftest"
    DEMO.mkdir(parents=True, exist_ok=True)
    pdf_path = DEMO / "sample.pdf"
    blank_path = DEMO / "blank.pdf"

    print("=" * 72)
    print("[1] 用 fitz 现造 3 页 PDF")
    import fitz

    doc = fitz.open()
    lines = [
        "Group theory studies algebraic structures.",
        "An abelian group is a group in which the commutative law holds.",
        "The identity element is unique in every group.",
    ]
    for line in lines:
        page = doc.new_page()
        page.insert_text((72, 96), line, fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    print(f"    saved: {pdf_path}")

    print("[2] extract_text(sample.pdf)")
    dt = extract_text(pdf_path)
    print(
        f"    source_kind={dt.source_kind}  pages={len(dt.pages)}"
        f"  has_text_layer={dt.has_text_layer}  page_count()={page_count(pdf_path)}"
    )
    for i, page in enumerate(dt.pages):
        print(f"    p{i + 1}: {page.strip()[:60]!r}")

    print("[3] RuleExtractor 抽取 + quote 逐条回验")
    seed = [
        {"name": "group", "definition": "a set with a binary operation", "aliases": ["groups"]},
        {"name": "commutative law", "definition": "", "aliases": []},
    ]
    concepts, relations = RuleExtractor().extract(dt, "0000", {"seed_concepts": seed})
    print(f"    concepts={len(concepts)} relations={len(relations)}")
    for c in concepts:
        print(f"    C: {c.name!r} | def={c.definition[:40]!r} | aliases={c.aliases}")
    all_ok = True
    for r in relations:
        ok = r.quote in dt.text
        all_ok = all_ok and ok
        pr = asdict(r.page_range) if is_dataclass(r.page_range) else r.page_range
        print(
            f"    R: names={r.concept_names} page_range={pr}"
            f" quote_in_text={ok} quote={r.quote[:60]!r}"
        )
    print(f"    >>> 所有 quote 均为原文子串: {all_ok}")

    print("[4] 空白 PDF（模拟扫描版无文本层）")
    blank = fitz.open()
    blank.new_page()
    blank.new_page()
    blank.save(str(blank_path))
    blank.close()
    bdt = extract_text(blank_path)
    print(f"    source_kind={bdt.source_kind} pages={bdt.pages!r} text={bdt.text!r}")
    print(f"    >>> pages == [] : {bdt.pages == []}   has_text_layer={bdt.has_text_layer}")
    b_concepts, b_relations = RuleExtractor().extract(bdt, "0001", {"seed_concepts": seed})
    print(
        "    RuleExtractor on blank: "
        f"concepts={len(b_concepts)} relations={len(b_relations)}"
        "  (期望 2/0：种子概念照给，关系 0 条)"
    )

    print("[5] text_at 边界语义")
    print(f"    text_at(2,2) 第2页前50字: {dt.text_at(2, 2).strip()[:50]!r}")
    print(f"    text_at(0,999) 收窄到全部页 长度={len(dt.text_at(0, 999))} 全文长度={len(dt.text)}")
    print(f"    text_at(9,9) 越界 => {dt.text_at(9, 9)!r}")
    print(f"    text_at(5,2) 反向 => {dt.text_at(5, 2)!r}")
    print(f"    text_at(None,None) => {dt.text_at(None, None)!r}  (刻意返回空串，见 docstring)")
    print(f"    blank.text_at(1,1) => {bdt.text_at(1, 1)!r}")
    try:
        # 先落一个真实文件：extract_text 先查存在性再查格式（存在性是更根本的错误）
        (DEMO / "nope.docx").write_bytes(b"PK\x03\x04 fake docx")
        extract_text(DEMO / "nope.docx")
    except UnsupportedFormat as exc:
        print(f"    >>> 不支持的扩展名抛 UnsupportedFormat: {exc}")
    try:
        extract_text(pdf_path, max_pages=1)
    except ExtractTooLarge as exc:
        print(f"    >>> 超限抛 ExtractTooLarge: {exc}")

    print("[6] LLMExtractor 回验：用会编引文的假 client 验证 fail-closed")

    class _FakeClient:
        """模拟两类模型行为：一条真引文（把换行抄成了空格）+ 一条凭空捏造的引文。"""

        def complete(self, prompt: str) -> str:
            # 顺手断言提示词确实渲染了：占位符被替换、正文带页标记。
            assert "{DOCUMENT_TEXT}" not in prompt and "<<<PAGE 1>>>" in prompt
            assert "逐字" in prompt
            return (
                "好的，以下是抽取结果：\n```json\n"
                + json.dumps(
                    {
                        "concepts": [
                            {
                                "name": "abelian group",
                                "definition": "a group with commutative law",
                                "aliases": [],
                            }
                        ],
                        "relations": [
                            {
                                "concept_names": ["abelian group", "group"],
                                "description": "定义阿贝尔群",
                                "quote": "An abelian group is a group in which the\ncommutative law holds.",
                                "page_range": {"start": 2, "end": 2},
                            },
                            {
                                "concept_names": ["abelian group", "magic"],
                                "description": "编造的关系",
                                "quote": "An abelian group is always finite and cyclic.",
                                "page_range": {"start": 2, "end": 2},
                            },
                            {
                                "concept_names": ["only one"],
                                "description": "概念数不足",
                                "quote": "Group theory studies algebraic structures.",
                                "page_range": {"start": 1, "end": 1},
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n```\n希望有帮助！"
            )

    le = LLMExtractor(_FakeClient())
    c2, r2 = le.extract(dt, "0000", {})
    print(f"    concepts={len(c2)} relations={len(r2)} report={le.last_report}")
    for r in r2:
        print(
            f"    R kept: 字面子串={r.quote in dt.text} quote={r.quote!r}"
        )
    print(f"    >>> 幻觉引文被剔除且计数正确: {le.last_report['relations_dropped'] == 2}")
    print(f"    >>> 剔除原因为 {le.last_report['drop_reasons']}")
    print(
        "    >>> 无文本层时 LLMExtractor 直接返回空（不调用模型）: "
        f"{LLMExtractor(_FakeClient()).extract(bdt, '0001', {}) == ([], [])}"
    )
    print(f"    >>> NullExtractor: {NullExtractor().extract(dt, '0000', {})}")
    _messy = '前言\n```json\n{"a": 1,}\n```\n后记'
    print(f"    >>> 围栏/寒暄容忍: {list(parse_llm_json(_messy))}")
    try:
        parse_llm_json("这不是 JSON")
    except ExtractionError as exc:
        print(f"    >>> 解析失败抛 ExtractionError: {type(exc).__name__}")

    print("=" * 72)
    print("SELF-CHECK DONE")

