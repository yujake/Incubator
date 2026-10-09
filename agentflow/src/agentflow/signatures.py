"""稿件内容的规范哈希（依据 `draft/30` §T4-A；`draft/29` §8.5 第 2 条）。

## 为什么需要它

"审批通过"必须是对某一个版本的审批。今天 `Document` 没有内容哈希 ⇒
"审批过的版本"与"被引用的版本"可以静默变成两版（本仓最忌的静默失效形态）。
这一层提供那个唯一的哈希算法，供两侧共用：

- 写侧（G）：落稿 / 改稿时算一次，写进 `documents.content_sha256`；
- 读侧（`verify`）：重算一遍与行里的值比对（`content_hash_mismatch`），
  并核对 `doc:<doc>#<claim>@<hash>` 这种引用钉的是不是当前这一版。

两份实现必然漂移 —— 所以算法只在这里定义一次。
`doc:` 内部引用的三段判据同理：它的唯一实现是本文件的 `doc_ref_verdict`
（写入期 `doc_tools` 与审计期 `verify` 都调它，题 5/5a 把原先那两份合成了一份）。

## 口径（逐字，改它等于改"什么算同一版"）

只覆盖内容五个字段：`kind / title / sections / claims / open_problems`；
不含 `status` / `review_rounds` / `markdown_path` / `created_at` / `updated_at` /
`revision` / `content_sha256` 自己 —— 它们是生命周期与呈现，不是内容。
把它们算进去会让"审一次"因为一次状态迁移而失效，那是把两种变化混成一种。

序列化：`json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
（UTF-8 编码后取 sha256 小写十六进制）。`ensure_ascii=False` 是刻意的：
中文标题必须按原字符入哈希，而不是按 `\\uXXXX` 转义。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Sequence

from . import canonical as CANONICAL
from .jsonlfile import read_jsonl

#: 参与内容哈希的字段（顺序无关：序列化时 `sort_keys=True`）。
CANONICAL_FIELDS: tuple[str, ...] = ("kind", "title", "sections", "claims", "open_problems")

#: 三个列表字段：缺字段与空列表必须算同一版。
#:
#: 实测踩到的坑（`T4-A` 第一批）：夹具/调用方给的字典常常没有 `sections` 键，
#: 而落库后的行是 `[]` —— 若把"缺键"读成 `None`，同一份内容就有两种哈希，
#: `content_hash_mismatch` 会在完全干净的库上开火
#: （实测：`test_fully_clean_workspace_has_no_errors` 就是这样红的）。
LIST_FIELDS: tuple[str, ...] = ("sections", "claims", "open_problems")

#: 引用里钉的哈希长度（`doc:<doc>#<claim>@<前 16 位>`）。
REF_HASH_LEN = 16


def _canonical_bytes(row: Mapping[str, Any]) -> bytes:
    """把稿件的内容序列化成规范字节串（键排序、无多余空白、非 ASCII 原样）。

    列表字段用 `row.get(k) or []` 归一：缺键、`None`、空列表三者在内容上
    是同一件事（"这篇稿子没有那一节"），不许因为写法不同而算出两个哈希。

    "规范字节串"的口径只有一处实现（`agentflow.canonical`，`R-33`）：
    本函数只负责"哪些字段进哈希 + 列表字段怎么归一"，
    序列化参数由那边定死（门 `scripts/noai_gate.py` 用的是同一份实现，
    它按文件路径加载，不 import 本包）。
    """
    payload: dict[str, Any] = {k: row.get(k) for k in CANONICAL_FIELDS}
    for k in LIST_FIELDS:
        payload[k] = payload.get(k) or []
    return CANONICAL.canonical_json_bytes(payload)


def content_sha256_of(row: Mapping[str, Any]) -> str:
    """稿件内容的规范哈希（小写十六进制，64 位）。"""
    return hashlib.sha256(_canonical_bytes(row)).hexdigest()


def claims_hash_of(row: Mapping[str, Any]) -> str:
    """只覆盖 `claims` 的哈希（单条断言级签名用；`draft/29` §8.8.2 的 `claims_hash`）。"""
    return CANONICAL.canonical_sha256(row.get("claims") or [])


def ref_hash_of(row: Mapping[str, Any]) -> str:
    """引用里钉的那一段哈希（`content_sha256` 的前 `REF_HASH_LEN` 位）。"""
    return content_sha256_of(row)[:REF_HASH_LEN]


def doc_ref(doc_id: str, claim_id: str, row: Mapping[str, Any]) -> str:
    """构造一条内部引用：`doc:<doc_id>#<claim_id>@<前 16 位>`。"""
    return f"doc:{doc_id}#{claim_id}@{ref_hash_of(row)}"


def parse_doc_ref(ref: str) -> tuple[str, str, str] | None:
    """拆内部引用；不是 `doc:` 形状时返回 `None`（不抛 —— 调用方要能把它当"另一档"）。

    两种形状（业主 2026-10-09 的裁定把它分成两档，见 `doc_ref_verdict` 的 docstring）：

    - `doc:<doc_id>#<claim_id>@<hash>` —— 引某条断言（三段式；`@hash` 可省 ⇒
      没钉版本，见下）；
    - `doc:<doc_id>` / `doc:<doc_id>@<hash>` —— 引我方那份手稿（整体成果）。

    形状坏掉的两处仍然返回 `None`：`doc:` 后面没有稿件号；或者写了 `@` 却是空的
    （`doc:0001@` / `doc:0001#c1@` —— 那是"钉了一个空哈希"，不是"没钉"）。
    """
    if not ref.startswith("doc:"):
        return None
    body = ref[4:]
    head, at, rev = body.partition("@")
    if at and not rev.strip():
        return None
    doc_id, sep, claim_id = head.partition("#")
    if not doc_id or (sep and not claim_id.strip()):
        return None
    return doc_id, claim_id, rev


# --------------------------------------------------- `doc:` 内部引用的三段判据（题 5/5a）
#
# 三段（稿件在 / 那条断言在 / 钉的哈希就是当前这一版）此前有两份实现：
# 写入期 `tools/doc_tools.py` 的 `_doc_citation_problem` 与审计期 `verify.py` 里
# `elif kind == "doc":` 那一支。两份对同一个字符串各判一次，漂了没有任何地方会报
# —— 写入期那份自己的注释写着"与 `verify.py:923-961` 同口径"，
# 而"口径靠注释对齐"就等于没有门（行号本身还会漂）。
#
# 唯一实现落在本模块，理由三条：
# 1. 这一段用到的三件原语都已经在这里（`parse_doc_ref` 解析、`content_sha256_of`
#    与 `ref_hash_of` 算哈希），判定与它的原语同处一文件，改口径只有一处可改；
# 2. 两侧本来就 import 本模块（`verify` 模块级 `SIG`，`doc_tools` 惰性 `SIG`）
#    ⇒ 不新增任何一条模块级依赖边；放进 `tools/` 会让 `verify → tools` 成环，
#    放进 `verify.py` 会让写入期反向依赖审计期；
# 3. 它是"数据 → 判定"的纯函数（查稿件的能力由调用方以回调传入），
#    与本模块"算法与词表只有一个落点"的性格一致。
#
# 合成的只是判定，不是渲染：两侧各自保留自己的文案，审计期还多一条自己的档
# （目标稿件必须 `accepted`）—— 那一条不在三段里，本次一字未动。

#: 三段判据的判定码（空串 = 三段全过）。
DOC_REF_OK = ""
DOC_REF_BAD_SHAPE = "doc_ref_bad_shape"
DOC_REF_NO_DOC = "doc_ref_no_doc"
DOC_REF_NO_CLAIM = "doc_ref_no_claim"
DOC_REF_STALE = "doc_ref_stale"


class DocRefVerdict(NamedTuple):
    """三段判据的判定，外加渲染文案要用的三段原值。

    为什么把 `doc` 与 `current_hash` 一起带回来，而不是让调用方自己再解析一次、
    再算一次哈希：那样等于在每个调用点上又长出一份三段逻辑，而那正是本次要消掉的
    东西。调用方只翻译判定码，不重做判定。

    `code` 是上表里那五个值之一；`pinned_hash` 是引用里钉的那一段（可为空串 =
    没钉哈希）；`current_hash` 只在稿件真的找到时才有值。
    """

    code: str
    doc_id: str = ""
    claim_id: str = ""
    pinned_hash: str = ""
    doc: Mapping[str, Any] | None = None
    current_hash: str = ""

    @property
    def ok(self) -> bool:
        """三段是否全过。"""
        return self.code == DOC_REF_OK

    @property
    def whole(self) -> bool:
        """这一条引的是整份手稿（两段式）还是某条断言（三段式）。

        业主 2026-10-09：「智能体产生的手稿确实不是正常引文……错误的是所有智能体
        产生的手稿里的成果若要使用则必须在论文正文里从零搭建，使内容自包含，
        不以引文格式落实」⇒ 两段式是合法的一档（引我方那份手稿的整体成果），
        这一格让"引整份手稿"与"引某条断言"在读数上分得开。
        """
        return not self.claim_id

    @property
    def pinned(self) -> bool:
        """这一条钉没钉版本（没钉 = 改稿之后旧引用不会失效）。"""
        return bool(self.pinned_hash)


def doc_ref_reading(raw: str) -> dict[str, bool]:
    """一条 `doc:` 引用的读数：`{"whole": 引整份手稿, "pinned": 钉了版本}`。

    纯读数（判定仍在 :func:`doc_ref_verdict`）。放进本模块是为了守住"三段判据的
    原语只许出现在这里"那条结构判据（`tests/test_internal_citations.py` ⑤）：
    调用点自己 `parse_doc_ref` 就等于又长出一份解析。
    形状不对 ⇒ 两格都 `False`（调用方那时已经有判定码了，不需要这里再报一次）。
    """
    parts = parse_doc_ref(str(raw))
    if parts is None:
        return {"whole": False, "pinned": False}
    _doc_id, claim_id, rev = parts
    return {"whole": not claim_id, "pinned": bool(str(rev))}


def doc_ref_verdict(raw: str,
                    doc_of: Callable[[str], Mapping[str, Any] | None]) -> DocRefVerdict:
    """`doc:` 内部引用的判定（依据 `draft/30` §T4-A，含 2026-10-09 的两档裁定）。

    ## 两档（业主 2026-10-09 的裁定）

    逐字：「关于"写论文时无法写入引用智能体产生的手稿的研究成果"，这个现象是半对半错。
    对的在于智能体产生的手稿确实不是正常引文，错误的是所有智能体产生的手稿里的成果
    若要使用则必须在论文正文里从零搭建，使内容自包含，不以引文格式落实」

    ⇒ 半边保留、半边改：

    - 保留：手稿不是文献（它不在 `literature` 里，`lit:` 引不到它）—— 这一档不动；
    - 改：`doc:<稿件>`（两段式）是合法的一档：引我方那份手稿里的成果，
      不必在正文里从零重搭一遍。此前它被 `parse_doc_ref` 判成"形状不对"
      （唯一写法的三段式要求 `#断言@哈希`），于是"用手稿里的成果"只剩"重搭"一条路
      —— 真机现场与三条读数见 `tests/test_a_document_may_cite_our_own_statement.py`。
    - 三段式（`doc:<稿件>#<断言>@<哈希>`）照旧：它比两段式更精确（钉到某条断言、
      钉到那一版）。钉了哈希就要对上（`DOC_REF_STALE` 一字未松）；
      两段式没钉版本这一档要看得见（`pinned=False`），不许与"钉过了"混作一谈。

    `doc_of(doc_id) -> 行 | None` 给的是查稿件的「能力」，不是表或库实例：
    写入期在事务内用 `rows_of("documents")` 查（拿到一致的快照），审计期用
    它已经读好的 `doc_by_id.get`（不再读第二遍表 ⇒ 不会看到两份快照）。
    形状解析不出来时一次表都不读（短路与两份旧实现一致）。

    判定只看这几段；"目标稿件必不必须是 `accepted`"之类的「调用方档」不在这里
    —— 那是两侧口径可以不同、且刻意不同的地方（写入期不查、审计期查）。
    """
    parts = parse_doc_ref(raw)
    if parts is None:
        return DocRefVerdict(DOC_REF_BAD_SHAPE)
    tdoc_id, tclaim_id, thash = parts
    doc = doc_of(tdoc_id)
    if doc is None:
        return DocRefVerdict(DOC_REF_NO_DOC, tdoc_id, tclaim_id, thash)
    if tclaim_id:
        claims = {str(cl.get("claim_id")) for cl in (doc.get("claims") or [])
                  if isinstance(cl, dict)}
        if str(tclaim_id) not in claims:
            return DocRefVerdict(DOC_REF_NO_CLAIM, tdoc_id, tclaim_id, thash, doc)
    cur = ref_hash_of(doc)
    if not str(thash):
        # 没钉版本（两段式，或三段式省了 `@哈希`）：通过，但读数里带着
        # `pinned=False` —— 改稿之后这条引用不会失效，那是写稿人的选择，不是错。
        return DocRefVerdict(DOC_REF_OK, tdoc_id, tclaim_id, "", doc, cur)
    if str(thash) != cur:
        return DocRefVerdict(DOC_REF_STALE, tdoc_id, tclaim_id, thash, doc, cur)
    return DocRefVerdict(DOC_REF_OK, tdoc_id, tclaim_id, thash, doc, cur)


# ---------------------------------------------------------------- 签名台账（T4-B）
#
# `draft/29` §8.8：签名对象是"某一个修订版"（`doc_id + content_sha256`），
# 记录落成文件台账（append-only JSONL），不进 `schema.TABLES`。
# 这一节只做"记录的写法与读法"；谁有资格签、签得上算不上，由下面几组判据回答。

#: 台账文件名（工作区根下）。
LEDGER_NAME = "DOC-SIGNATURES.jsonl"
#: 证据快照目录（工作区根下）。一条签名一份，文件名钉住内容哈希。
EVIDENCE_DIR = "doc-signatures"
#: 只有审核角色有资格签（`draft/29` §8.8.2：角色名说明"谁有资格"，
#: `instance_id` 说明"是哪一次审"）。
SIGNER_NAME = "agent-H"
#: "接受档"判定。设计的字面是 `verdict == "accepted"`，而本仓 `review` 的判定词表实测是
#: `rejected / unverified / accepted_with_warnings / accepted`，且 §8.8.3 明说
#: "含 `external_unavailable` 依赖 ⇒ H 给 warning（已知边界）"也要签一条。
#: 所以接受档是这两个 —— 不把 warning 当拒绝（那会把"已知边界"变成"不许发布"）。
ACCEPTING_VERDICTS: tuple[str, ...] = ("accepted", "accepted_with_warnings")

#: 「该被签」的稿件状态（E-07 / `draft/52` D5：`accepted` 且 `revised`）。
#:
#: 为什么把 `revised` 也算进来（`draft/44` E-07 "签名覆盖 `revised`"）：
#: `G.revise` 把稿子推成 `revised` 的那一刻，签名还钉着改之前那一版 ——
#: 只按 `accepted` 判的话，一份"改完之后没再复核"的稿子在这条判据面前
#: 一份都不查（真机根 A 实测 10 份非 `accepted` 的稿子被静默跳过，
#: 其中 2 份的签名哈希与现行版不符：`p6d/0015`、`p8e/0000`）。
#:
#: 三处必须同源（分叉的症状是"读数说查了 N 行而判据一行没查"）：
#: 本常量、`verify.py` 的覆盖读数与交叉断言、`closing.REVIEWED_DOC_STATUSES`
#: （`reviewed_current_rows` 那一档的 `claimed` 集合）。
#: `scripts/lint_rules` 的 R002 与 `verify_all` 都直接读它，`append_signature`
#: 的写侧闸门一个字不改（E-07 只改读侧）。
SIGNABLE_STATUSES: tuple[str, ...] = ("accepted", "revised")
#: 旧名（标量）保留作别名转发：`verify.py` 与若干读数键仍在用它。
SIGNABLE_STATUS = SIGNABLE_STATUSES[0]

#: 判据码（`verify` 直接消费）。放在这里是为了让"算法 + 词表"只有一处。
CODE_ACCEPTED_WITHOUT_SIGNATURE = "accepted_without_signature"
CODE_STALE_SIGNATURE = "stale_signature"
CODE_VERDICT_NOT_ACCEPTING = "signature_verdict_not_accepting"
CODE_SIGNER_NOT_REVIEWER = "signer_not_reviewer"
CODE_INPUTS_MISMATCH = "signature_inputs_mismatch"
CODE_EVIDENCE_UNVERIFIABLE = "signature_evidence_unverifiable"
CODE_LEDGER_CORRUPT = "signature_ledger_corrupt"

#: 一条签名记录必须有的字段（缺一条就不许写进台账）。
REQUIRED_SIGNATURE_FIELDS: tuple[str, ...] = (
    "doc_id", "content_sha256", "name", "at", "scope", "verdict", "instance_id",
    "evidence_path", "evidence_sha256", "inputs", "basis",
)

#: 其中由 `append_signature` 自己产出的两个（证据锚）：调用方不必给，
#: 也不能自己填 —— 否则"证据锚"就退化成一个可以随便写的字符串。
DERIVED_SIGNATURE_FIELDS: tuple[str, ...] = ("evidence_path", "evidence_sha256")


def ledger_path(root: str | Path) -> Path:
    """台账文件路径（只算路径，不建目录）。"""
    return Path(root) / LEDGER_NAME


def evidence_dir(root: str | Path) -> Path:
    """证据快照目录（只算路径，不建目录）。"""
    return Path(root) / EVIDENCE_DIR


def line_hash(record: Mapping[str, Any]) -> str:
    """一行的规范哈希（不含 `prev_hash` 自己）—— 链式台账的链节。"""
    payload = {k: v for k, v in record.items() if k != "prev_hash"}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_ledger(path: str | Path) -> tuple[list[dict], list[str]]:
    """读台账；返回 `(记录, 问题)`。

    坏行逐条报出来（带行号），不静默跳过 —— "读不出来"与"没有这一行"
    是两件事（三态纪律）。文件不存在 ⇒ 空台账、零问题（那是合法初态）。

    JSONL 的读法只有一份实现：:func:`jsonlfile.read_jsonl`（`draft/36` T-6 合并）。
    此前这里是第二份完整实现，唯一的差别是那句措辞写"不是 JSON 对象"；
    合并后统一成"不是对象"（与 `artifacts` / `sessions` 一致，两处对一处）。
    """
    return read_jsonl(path)


def chain_problems(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """链完整性：每条记录的 `prev_hash` 必须等于上一行的 `line_hash`；首行为空串。"""
    out: list[str] = []
    prev = ""
    for i, r in enumerate(records):
        if str(r.get("prev_hash") or "") != prev:
            out.append(f"第 {i + 1} 条的 prev_hash={str(r.get('prev_hash'))[:12]!r} "
                       f"与上一行的哈希 {prev[:12]!r} 不符（台账被插队或删过）")
        prev = line_hash(r)
    return out


def _rel_inside(root: str | Path, path: str | Path) -> tuple[str, Path] | None:
    """把路径规范化到工作区内；越界/绝对路径 ⇒ `None`（拒绝，不抛）。"""
    base = Path(root).resolve()
    raw = str(path).replace("\\", "/")
    if raw.startswith("/") or ":" in raw or ".." in raw.split("/"):
        return None
    target = (base / raw).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return raw, target


def verify_signature(root: str | Path, record: Mapping[str, Any],
                     doc_row: Mapping[str, Any]) -> str:
    """逐条判一条签名；返回判据码，全部通过则返回 `"valid"`。

    判的顺序与 `draft/29` §8.8.4 的五条逐字对应：谁签的 → 判定档 → 签的是这一版 →
    它读到的输入是这一版 → 证据锚可复核。
    """
    name = str(record.get("name") or "")
    if name != SIGNER_NAME or name == str(doc_row.get("created_by") or ""):
        return CODE_SIGNER_NOT_REVIEWER
    if str(record.get("verdict") or "") not in ACCEPTING_VERDICTS:
        return CODE_VERDICT_NOT_ACCEPTING
    cur = content_sha256_of(doc_row)
    if str(record.get("content_sha256") or "") != cur:
        return CODE_STALE_SIGNATURE
    inputs = record.get("inputs") or {}
    if not isinstance(inputs, Mapping) or str(inputs.get("doc_sha256") or "") != cur:
        return CODE_INPUTS_MISMATCH
    located = _rel_inside(root, str(record.get("evidence_path") or ""))
    if located is None:
        return CODE_EVIDENCE_UNVERIFIABLE
    _raw, path = located
    if not path.is_file():
        return CODE_EVIDENCE_UNVERIFIABLE
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != str(record.get("evidence_sha256") or ""):
        return CODE_EVIDENCE_UNVERIFIABLE
    return "valid"


def signature_problems(root: str | Path, doc_row: Mapping[str, Any],
                       records: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """这份稿件在"签名"这件事上的问题（空 = 签过且有效）。

    `status ∈ SIGNABLE_STATUSES`（`accepted` / `revised`）的稿件才谈"该被签"——
    草稿没有签名不是缺陷。`revised` 也算进来是 E-07：改稿之后签名钉的是旧版，
    而那正是最该被看见的一件事（只按 `accepted` 判 ⇒ 10 份真机稿件被静默跳过）。

    ## 判据是"至少一条签名完全成立"，不是"第一条签名成立"

    同一版内容被签多次是正常状态（H 重审一轮就再签一条；改稿后旧签名作废、
    新签名钉新版）。所以判据必须是"存在一条有效的"，而不是"台账里第一条有效" ——
    后者会让一条历史记录的失效把整份稿件判成"没签"。实测（2026-09-29）：
    同一版内容签了两条，其中一条的证据快照被后一条覆盖（当时快照路径只含内容哈希），
    于是 `formal(doc)` 变假，而它自己这条函数的 docstring 与 `signed()` 写的是
    "至少一条签名完全成立"。快照路径的重名问题已在 `append_signature` 里修掉，
    这里修的是判据本身的语义。

    一条都不成立时，返回第一条的具体判据码与证据（人要知道是哪种失效）。
    """
    if str(doc_row.get("status") or "") not in SIGNABLE_STATUSES:
        return []
    cur = content_sha256_of(doc_row)
    mine = [r for r in records if str(r.get("doc_id") or "") == str(doc_row.get("doc_id") or "")]
    same = [r for r in mine if str(r.get("content_sha256") or "") == cur]
    if not same:
        if mine:
            return [(CODE_STALE_SIGNATURE,
                     f"稿件 {doc_row.get('doc_id')} 已是 accepted，但台账里的 {len(mine)} 条签名"
                     f"钉的都是别的版本（当前 {cur[:16]}…）⇒ 改稿之后旧审批不许沿用")]
        return [(CODE_ACCEPTED_WITHOUT_SIGNATURE,
                 f"稿件 {doc_row.get('doc_id')} 已是 accepted，却没有任何签名记录 ⇒"
                 "「审过了」这件事没有可核的凭据")]
    problems: list[tuple[str, str]] = []
    for r in same:
        code = verify_signature(root, r, doc_row)
        if code == "valid":
            return []
        problems.append((code, f"稿件 {doc_row.get('doc_id')} 的签名不成立（{code}）："
                               f"name={r.get('name')!r} verdict={r.get('verdict')!r} "
                               f"inputs.doc_sha256="
                               f"{str((r.get('inputs') or {}).get('doc_sha256'))[:16]!r} "
                               f"evidence={r.get('evidence_path')!r}"))
    return problems[:1]


def signed(doc_row: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
           *, root: str | Path) -> bool:
    """`draft/29` §8.8.4 的 `signed(doc)`：至少一条签名完全成立。"""
    return not signature_problems(root, doc_row, records)


def formal(doc_row: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
           *, root: str | Path) -> bool:
    """`formal(doc) ⇔ signed(doc) ∧ status == "accepted"`。"""
    return (str(doc_row.get("status") or "") == "accepted"
            and signed(doc_row, records, root=root))


def signed_revision(doc_row: Mapping[str, Any],
                    records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """钉在当前这一版内容上的签名记录（找到第一条就返回它）；没有 ⇒ `None`。

    ## 与 :func:`signed` 的分工（两者不可互换）

    `signed(doc)` 答的是"这份稿件在签名这件事上有没有问题"，而它对
 非 `accepted` 状态的稿件一律返回真（草稿本来就不该被签 ⇒ 没有问题是正常的）。
    所以它回答不了另一个问题："现在盘上这一版内容，有没有一条签名针对它"。

    那个问题在 `R-59`（`draft/28` §161.4）里是决定性的：`verify_fixes` 复审通过时想把
    状态置回 `accepted`，而"改过稿之后旧审批不许沿用"（`draft/29` §8.8.4）要求
    `accepted` 必须由针对这一版的审+签背书。用 `signed()` 去判会得到"真"
    （因为状态那一刻还是 `revised`）⇒ 于是置了 `accepted`、签名却还钉着旧版本 ⇒
    `stale_signature`。本函数的判据是逐字的：台账里存在一条 `content_sha256`
    等于当前内容哈希的记录。
    """
    cur = content_sha256_of(doc_row)
    for r in records:
        if str(r.get("doc_id") or "") != str(doc_row.get("doc_id") or ""):
            continue
        if str(r.get("content_sha256") or "") == cur:
            return r
    return None


def append_signature(root: str | Path, record: Mapping[str, Any], *,
                     findings: Sequence[Mapping[str, Any]] = ()) -> dict:
    """写一条签名：先落证据快照，再追加台账一行（带 `prev_hash`）。

    写侧闸门（`draft/29` §8.8.7 的"禁自批"）：签名者必须是 `agent-H`、
    判定必须是接受档、必填字段必须齐 —— 否则 `ValueError`，不写半个文件。
    """
    missing = [k for k in REQUIRED_SIGNATURE_FIELDS
               if k not in DERIVED_SIGNATURE_FIELDS and not record.get(k)]
    if missing:
        raise ValueError(f"签名记录缺必填字段 {missing}（`draft/29` §8.8.2 的字段表）")
    name = str(record.get("name") or "")
    if name != SIGNER_NAME:
        raise ValueError(f"只有 {SIGNER_NAME!r} 有资格签，收到 {name!r}（禁自批）")
    if str(record.get("verdict") or "") not in ACCEPTING_VERDICTS:
        raise ValueError(f"verdict 必须是接受档 {ACCEPTING_VERDICTS} 之一，"
                         f"收到 {record.get('verdict')!r}")

    base = Path(root)
    snap_dir = evidence_dir(base)
    snap_dir.mkdir(parents=True, exist_ok=True)
    doc_id = str(record["doc_id"])
    content = str(record["content_sha256"])
    records, _problems = read_ledger(ledger_path(base))
    # 快照文件名必须逐条唯一：同一版内容被签多次是正常状态（H 重审一轮就再签一条），
    # 若文件名只含内容哈希，后一条会把前一条的快照覆盖掉 ⇒ 前一条的 `evidence_sha256`
    # 从此对不上 ⇒ 那条签名永久失效。实测（2026-09-29，P7 重签台账）：正是这样把
    # `formal(doc)` 变成假的，而错在"快照被覆盖"这件与内容无关的事上。
    # 序号取"台账里已有多少条"，确定性、可读、且与新记录一一对应。
    ordinal = len(records) + 1
    name = f"{doc_id}-{content[:REF_HASH_LEN]}-{ordinal:03d}.json"
    rel = f"{EVIDENCE_DIR}/{name}"
    snapshot = {"doc_id": doc_id, "content_sha256": content,
                "at": str(record.get("at") or ""), "verdict": str(record.get("verdict") or ""),
                "findings": [dict(f) for f in findings]}
    snap_path = snap_dir / name
    snap_path.write_text(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")) + "\n", encoding="utf-8")

    row = dict(record)
    row["evidence_path"] = rel
    row["evidence_sha256"] = hashlib.sha256(snap_path.read_bytes()).hexdigest()
    row["prev_hash"] = line_hash(records[-1]) if records else ""
    line = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    with ledger_path(base).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    return row


def selftest() -> int:
    """自检：同一内容不同键序 ⇒ 同哈希；改一个字节 ⇒ 变；中文按原字符入哈希。"""
    a = {"kind": "paper", "title": "谱的界", "sections": [], "claims": [], "open_problems": []}
    b = {"open_problems": [], "claims": [], "sections": [], "title": "谱的界", "kind": "paper"}
    if content_sha256_of(a) != content_sha256_of(b):
        print("[fail] 键序不同的同一内容必须同哈希")
        return 1
    if content_sha256_of(a) == content_sha256_of({**a, "title": "谱的界!"}):
        print("[fail] 改一个字节必须换哈希")
        return 1
    if content_sha256_of({**a, "status": "accepted"}) != content_sha256_of(a):
        print("[fail] status 不参与内容哈希（生命周期不是内容）")
        return 1
    if len(content_sha256_of(a)) != 64 or ref_hash_of(a) != content_sha256_of(a)[:REF_HASH_LEN]:
        print("[fail] 哈希长度或引用段口径不对")
        return 1
    ref = doc_ref("0001", "C1", a)
    if parse_doc_ref(ref) != ("0001", "C1", ref_hash_of(a)):
        print("[fail] doc_ref 与 parse_doc_ref 不自洽")
        return 1
    if parse_doc_ref("lit:0003#p.4") is not None or parse_doc_ref("doc:0001") is not None:
        print("[fail] 非 doc: 形状或缺 claim 时必须返回 None")
        return 1
    print("SELF-CHECK DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(selftest())
