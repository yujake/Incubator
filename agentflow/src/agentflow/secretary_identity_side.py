# -*- coding: utf-8 -*-
"""秘书的挑词、形态闸与修稿同一性（从 secretary.py 的 U21 后半逐字搬出）。

我保证哪条不变式：形态闸只判形状、不判对错：它回答的是「这一句像不像一条命题」，「这一条命题对不对」在别处。

## 为什么它能单独成文件（依赖方向）

它只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from typing import Mapping
import hashlib

from .secretary_axes import (  # noqa: F401 — 这些名字由 secretary_axes 定义
    _proposition_verdict_key,
    append_proposition_form,
    append_statement_same,
    proposition_form_of,
)

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    EMPTY_STATEMENT_TEXT,
    PROPOSITION_KINDS,
)

from .secretary_identity import (  # noqa: F401 — 这些名字由 secretary_identity 定义
    _is_proposition_kind,
)

from .secretary_prompts import (  # noqa: F401 — 这些名字由 secretary_prompts 定义
    JUDGE_MATERIAL_CAP,
    _abandon_difficulty_system,
    _judge_material,
    _proposition_form_system,
    _statement_keywords_system,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    PROPOSITION_FORM_REFUSED,
    PROPOSITION_VERDICTS,
)


class IdentitySideMixin:
    """挑词/形态闸/修稿同一性（从 secretary.py 搬出的混入类）。"""

    def judge_proposition_form(self, *, statement_full: str, label: str = "",
                               kind: str = "", proof_text: str = "",
                               task_id: str = "", stmt_id: str = "") -> dict[str, Any]:
        """F 的秘书专属：这条命题描述有没有明确「从什么条件导出什么结论」。

        业主 2026-11-07 逐字：

        > 「命题登记时需过 F 秘书闸，审查命题描述是否规范，是否明确了从什么条件导出什么结论」

        ## 它判什么、不判什么（两根轴必须分开）
        - 判：这段描述的形状 —— 前提写得出来吗？结论是一个可判真假的断言吗？
          二者由"若…则…/设…则…"一类结构连起来了吗？有没有把作业/验收规格
          （"本轮产物必须是 proof"、"判据是 `manuscript_published=true`"、
          "原样提交 `reports/xxx.md`"）写成一条命题？
        - 不判：它对不对（那是 V 的轴，`verify.verify_proof`）、它是否平凡/是否已知
          （那是 `judge_statement` 的非平凡性轴）。两根轴混进同一格就是本仓反复踩过的
          "同一件事两个名字"。
        - 不用词面阈值代替判断（业主明确不要机械判据）：这里一次模型调用，没有
          关键词表、没有字数阈值。

        ## 返回（键集合固定）

        | 键 | 意思 |
        |---|---|
        | `checked` | 这一问有没有真的判成（没缝 / 关着 / 超时 / 坏 JSON / 词表外 ⇒ False） |
        | `well_formed` | 两态，没有第三档：`True` 形状合规 / `False` 不合规（只在 `checked=True` 时有意义） |
        | `conditions` | 它读出来的前提（字符串；合格时不许为空） |
        | `conclusion` | 它读出来的结论（字符串；合格时不许为空） |
        | `problems` | 逐条说缺什么（合格时为空；不合格时必须非空） |
        | `decision` | 一句话判词 |
        | `refused` | 受控码（`checked=False` 或 `well_formed=False` 时非空） |

        ## 三态（本仓最贵的那条纪律）
        `checked=False` 不是"没毛病"：调用方（F 的交稿那一步）必须 fail-closed
        当受控拒处理 —— 否则"今天没判成"会被读成"今天放行了"。

        ## 缓存
        按命题正文的 sha256 命中本台账（`out/secretary/proposition_form.jsonl`）：
        同一条正文重交一次不重复花钱，命中的结论原样带回（`cached=True`）。
        "没查成"的行不缓存（缝可能好起来，与 `proposition_verdict_of` 同一条纪律）。
        """
        out: dict[str, Any] = {
            "checked": False, "well_formed": False, "conditions": "", "conclusion": "",
            "problems": [], "decision": "", "refused": "", "reason": "", "cached": False,
            "cost": {}, "material": {}, "statement_sha256": "", "role": str(self.role),
        }
        body = str(statement_full or "")
        if not body.strip():
            out.update(refused=EMPTY_STATEMENT_TEXT,
                       reason=("这一条没有命题正文（0 字）⇒ 没有可判的对象："
                               "不进形态判定，不发调用"))
            return out
        root = str(getattr(self.store, "root", "") or self.root or "")
        key = _proposition_verdict_key(body)
        out["statement_sha256"] = key
        if root:
            cached = proposition_form_of(root, statement_full=body)
            if cached and cached.get("checked"):
                out.update(checked=bool(cached.get("checked")),
                           well_formed=bool(cached.get("well_formed")),
                           conditions=str(cached.get("conditions") or ""),
                           conclusion=str(cached.get("conclusion") or ""),
                           problems=[str(x) for x in (cached.get("problems") or [])],
                           decision=str(cached.get("decision") or ""),
                           cached=True,
                           reason=f"命中台账里那一次判定（{cached.get('at') or ''}）")
                if not out["well_formed"]:
                    out["refused"] = PROPOSITION_FORM_REFUSED
                return out
        if self.seam is None or not self.enable_model:
            # fail-closed：没有判断面 ⇒ 这一格没查成（不是"没毛病"）。
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 形态没判成。"
                               "登记这一步按受控拒处理 —— 「没判成」不许折成「没毛病」"
                               + (f"（装配读数：{self.model_source}）"
                                  if str(self.model_source or "") else "")))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        material = {"label": str(label or ""), "kind": str(kind or ""),
                    "statement_full": body[:JUDGE_MATERIAL_CAP],
                    "proof_chars": len(str(proof_text or ""))}
        out["material"] = dict(material)
        try:
            data, call = self.seam.ask_json(_judge_material(material),
                                            system=_proposition_form_system(),
                                            task_id=task_id,
                                            note="secretary:proposition_form")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 没判成（fail-closed）
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=f"形态判定调用失败（{type(exc).__name__}: {exc}）⇒ 没判成")
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=(f"形态判定没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                               f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 没判成"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        raw = data.get("well_formed")
        if not isinstance(raw, bool):
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=(f"模型给的 well_formed 不是布尔（收到 {raw!r}）⇒ 不采信："
                               "这一问只有两态，第三档会让「没判成」冒充「没毛病」"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        conditions = str(data.get("conditions") or "").strip()
        conclusion = str(data.get("conclusion") or "").strip()
        problems = [str(x).strip() for x in (data.get("problems") or []) if str(x).strip()]
        decision = str(data.get("decision") or "").strip()
        if raw and not (conditions and conclusion):
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=("模型判合格，却读不出前提或结论（conditions/conclusion 有空格）⇒ "
                               "这一格没判成：合格的那一档必须能复述「条件 → 结论」"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        if not raw and not problems:
            out.update(refused=PROPOSITION_FORM_REFUSED,
                       reason=("模型判不合格，却一条 problems 都没点名 ⇒ 这一格没判成："
                               "拒收必须逐条说缺什么，否则调用方不知道该改哪里"))
            self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                            task_id=task_id, root=root)
            return out
        out.update(checked=True, well_formed=bool(raw), conditions=conditions,
                   conclusion=conclusion, problems=problems, decision=decision,
                   refused="" if raw else PROPOSITION_FORM_REFUSED,
                   reason=("形态合规：前提与结论都读得出来" if raw else
                           f"形态不合规：{len(problems)} 条 —— " + "；".join(problems[:4])))
        self._note_form(out, body=body, label=label, kind=kind, stmt_id=stmt_id,
                        task_id=task_id, root=root)
        return out

    def _note_form(self, out: Mapping[str, Any], *, body: str, label: str = "",
                   kind: str = "", stmt_id: str = "", task_id: str = "",
                   root: str = "") -> None:
        """把这一次形态判定落进台账（写不进去不许带走这一次判定的结论）。"""
        if not root:
            return
        try:
            out["ledger"] = append_proposition_form(
                root, statement_full=body, checked=bool(out.get("checked")),
                well_formed=bool(out.get("well_formed")),
                conditions=str(out.get("conditions") or ""),
                conclusion=str(out.get("conclusion") or ""),
                problems=list(out.get("problems") or ()),
                decision=str(out.get("decision") or ""),
                refused=str(out.get("refused") or ""),
                reason=str(out.get("reason") or ""), label=label, kind=kind,
                stmt_id=stmt_id, role=str(self.role), task_id=task_id)
        except Exception as exc:  # noqa: BLE001 —— 台账写不进去要看得见，但不改判定
            out["ledger_error"] = f"{type(exc).__name__}: {exc}"

    def judge_same_proposition(self, *, before: str, after: str, label: str = "",
                               kind: str = "conjecture", task_id: str = "",
                               note: str = "secretary:proposition_identity") -> dict[str, Any]:
        """同一个稿上改前 / 改后那两段命题正文，是不是同一条命题（两态；判不了 ⇒ 没判成）。

        ## 与 `adjudicate_proposition` 的分工（不是第二份判据）

        那一问是"新命题 vs 在册候选"：判 same 必须点出一个候选号（`same_as`），并落
        `proposition_verdicts` 缓存。这一问是"同一份稿的 `## 命题` 从 A 改成 B"——
        两侧都没有台账号，也没有"并进哪一条"这件事。所以：

        - 轴不新造：`judge("proposition_identity", …)` 与那一问同一类、同一份题面
          （`_judge_system("proposition_identity")`）；
        - 材料同形：`_identity_context(full=after, candidates=[before 那一条])`
          —— 模型看到的是"要判的这一条 + 一条候选"，读法一字不差；
        - 不缓存：`proposition_verdicts` 的键只有 `after` 的 sha，而这一问的答案还取决
          于 `before` ⇒ 按单一 sha 缓存会把"上次 A→B 判 same"沿用到"C→B"上。这一档不写
          那本账（这一问是修稿兜底，不是每次登记的常路，花一次调用是可接受的）。

        ## 三态（与全仓同一条纪律）

        | 结局 | 返回 |
        |---|---|
        | 判成 | `checked=True` + `decision="same"` / `"different"` + `basis` |
        | 没判成 | `checked=False` + `decision=""` + `reason`（没缝 / 开关关着 / 超时 / 坏 JSON / 词表外） |

        `same` 是"同一条命题"，`different` 是"另一条命题"——调用方（原位重写的写口）
        只在 `checked=True and decision=="same"` 时才许动稿，别的两档一律 fail-closed。
        """
        out: dict[str, Any] = {"checked": False, "decision": "", "reason": "",
                               "basis": "", "cost": {}, "before_sha256": "",
                               "after_sha256": "", "note": note}
        before_text = str(before or "")
        after_text = str(after or "")
        out["before_sha256"] = _proposition_verdict_key(before_text)
        out["after_sha256"] = _proposition_verdict_key(after_text)
        if not before_text.strip() or not after_text.strip():
            out["reason"] = ("改前或改后的命题正文是空的 ⇒ 没有可判的两段"
                             "（空的那一侧不是「同一条」）")
            return out
        if not _is_proposition_kind(str(kind or "")):
            out["reason"] = (f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 "
                             "⇒ 不是命题，不参与同一性判定")
            return out
        context = self._identity_context(
            full=after_text, label=str(label or ""), kind=str(kind or ""),
            candidates=[{"stmt_id": "", "label": str(label or ""),
                         "proof_nos": [], "statement_full": before_text}])
        got = self.judge("proposition_identity", context, task_id=task_id, note=note)
        out["cost"] = dict(got.get("cost") or {})
        if not got.get("checked"):
            out["reason"] = str(got.get("reason") or "这一格没查成（原因不明）")
            return out
        decision = str(got.get("decision") or "")
        if decision not in PROPOSITION_VERDICTS:
            out["reason"] = (f"模型给的结论 {decision!r} 不在两档 {list(PROPOSITION_VERDICTS)} "
                             "里 ⇒ 不采信：这一格没判成")
            return out
        parts = [str(x).strip() for x in (got.get("basis") or []) if str(x).strip()]
        out.update(checked=True, decision=decision,
                   reason=str(got.get("reason") or ""),
                   basis="；".join(parts + ([out["reason"]] if out["reason"] else [])))
        return out

    def pick_statement_keywords(self, *, statement_full: str, label: str = "",
                                kind: str = "", task_id: str = "") -> dict[str, Any]:
        """给一条待收命题挑检索关键词（一次模型调用；产物只有 keywords 与 why）。

        「B秘书要学会在命题台账里按关键词搜索」。
        这一问只回答"拿哪几个词去台账里捞"，不回答"捞到的是不是同一条"（那是
        :meth:`adjudicate_proposition` 那一趟）。两问分开的理由：关键词是检索的输入，
        判同一是检索结果的处置；混成一问会让"检索没捞到"与"判定说不是"在读数上同形。

        ## 返回
        | 键 | 意思 |
        |---|---|
        | checked | 这一问有没有真的判成（没缝 / 关着 / 超时 / 坏 JSON / 空词表 ⇒ False） |
        | keywords | 模型给出的关键词（原样，按出现顺序去重；词数由它自己定） |
        | why | 一句话：这几个词为什么能把同义的那条捞出来 |

        代码里没有"最多 N 个词"的上限：词数是判定的一部分（业主明确不许机械上限）。
        检索面多大由调用方按工程上限分批，不由这一问替它裁。
        """
        out: dict[str, Any] = {"checked": False, "keywords": [], "why": "",
                               "seam_source": str(self.model_source or ""),
                               "ledger": {}, "role": str(self.role)}
        body = str(statement_full or "")
        if not body.strip():
            out["why"] = ("命题正文是 0 字 ⇒ 没有可检索的内容（没调模型）："
                          "空正文不是「材料不足」，它没有关键词可挑")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        if self.seam is None or not self.enable_model:
            out["why"] = ("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 关键词没提取成。"
                          "调用方必须 fail-closed：不新注册"
                          + (f"（装配读数：{self.model_source}）"
                             if str(self.model_source or "") else ""))
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        material = {"label": str(label or ""), "kind": str(kind or ""),
                    "statement_full": body[:JUDGE_MATERIAL_CAP]}
        try:
            data, call = self.seam.ask_json(
                _judge_material(material), system=_statement_keywords_system(),
                task_id=task_id, note="secretary:statement_keywords")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 没提取成（fail-closed）
            out["why"] = f"关键词提取调用失败（{type(exc).__name__}: {exc}）⇒ 没提取成"
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out["why"] = (f"关键词提取没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                          f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 没提取成")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        raw = data.get("keywords")
        if not isinstance(raw, (list, tuple)):
            out["why"] = (f"模型给的 keywords 不是数组（收到 {raw!r}）⇒ 不采信："
                          "这一问的产物是一张词表，不是一句话")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        from . import textutil as T   # 惰性：只借既有归一化口径做去重
        words: list[str] = []
        seen: set[str] = set()
        for item in raw:
            word = str(item or "").strip()
            key = T.normalize(word)
            if not word or not key or key in seen:
                continue
            seen.add(key)
            words.append(word)
        why = str(data.get("why") or "").strip()
        if not words:
            out["why"] = "模型给的关键词表是空的 ⇒ 没提取成（空词表捞不到任何一条）"
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        if not why:
            out["why"] = ("模型给了关键词却没写 why ⇒ 不采信：读的人要能看出"
                          "这几个词凭什么能把同义的那条捞出来")
            self._note_statement_same(stage="keywords", out=out, body=body,
                                      label=label, kind=kind, task_id=task_id)
            return out
        out.update(checked=True, keywords=words, why=why)
        self._note_statement_same(stage="keywords", out=out, body=body,
                                  label=label, kind=kind, task_id=task_id)
        return out

    def _note_statement_same(self, *, stage: str, out: dict[str, Any],
                             body: str = "", label: str = "", kind: str = "",
                             keywords: Sequence[str] = (), hits_total: int = 0,
                             candidates: Sequence[str] = (),
                             task_id: str = "") -> None:
        """把这一问落进台账（写不进去不许带走结论；与 `_note_form` 同一条纪律）。"""
        root = str(getattr(self.store, "root", "") or self.root or "")
        if not root:
            return
        try:
            out["ledger"] = append_statement_same(
                root, stage=stage, statement_full=body,
                checked=bool(out.get("checked")),
                keywords=list(keywords or ()), hits_total=int(hits_total or 0),
                candidates=list(candidates or ()),
                found=str(out.get("found") or ""), why=str(out.get("why") or ""),
                label=label, kind=kind,
                seam_source=str(out.get("seam_source") or ""),
                role=str(self.role), task_id=task_id)
        except Exception as exc:  # noqa: BLE001 —— 台账写不进去要看得见，但不改判定
            out["ledger_error"] = f"{type(exc).__name__}: {exc}"

    def judge_abandon_difficulty(self, *, statement: Mapping[str, Any],
                                 difficulty: Any, basis: Any, salvaged: Any = (),
                                 task_id: str = "", stmt_id: str = "") -> dict[str, Any]:
        """放弃闸的 difficulty 档：一次秘书语义判定。

        「对于 2，需指出困难，并将原先证明中可取之处拆出落成引理」。
        `difficulty` 只非空不算数（"做不动了"不是指出困难），`salvaged` 光"在册 /
        active / kind=lemma"也不算（可以是任意一条无关旧引理）。这一问同时判两件事，
        一次调用：

        1. `difficulty` 是不是在说真实的数学困难、难在哪（卡在哪条引理 / 哪一步 /
           哪条假设），而不是"做不动了"这类没有内容的话；
        2. `salvaged` 里那几条引理是不是从这条命题的原证明里拆出来的可取之处，
           而不是随便一条在册引理（或这条命题自己）。

        ## 为什么是模型判定而不是字数/关键词阈值
        「真困难」与「从旧稿拆出」都是语义判断：任何字数下限都会被一段套话满足，
        任何关键词表都会把"缺一条 K 的速降假设"判成没有关键词。不要机械判据。

        ## 三态（本仓最贵的那条纪律）
        没缝 / 关着 / 超时 / 坏 JSON / 非布尔 / 说合格却读不出"难在哪" ⇒ `checked=False`
        + `refused`（调用方按受控拒处理）。不许把"这一次没判成"折成"有理由"。

        ## 返回（键集合固定）
        `checked` / `genuine` / `where` / `salvaged_from_proof` / `problems` /
        `decision` / `refused` / `reason`。
        """
        out: dict[str, Any] = {
            "checked": False, "genuine": False, "where": "", "salvaged_from_proof": False,
            "problems": [], "decision": "", "refused": "", "reason": "",
            "cost": {}, "statement_sha256": "",
        }
        body = str((statement or {}).get("statement_full") or "")
        proof = str((statement or {}).get("proof_text") or "")
        out["statement_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
        if not str(difficulty or "").strip():
            out.update(refused="abandon_difficulty_required",
                       reason="这一档没有 `difficulty` ⇒ 没有可判的「难在哪」（不发调用）")
            return out
        if self.seam is None or not self.enable_model:
            out.update(refused="abandon_difficulty_not_judged",
                       reason=("这一名秘书没有判断面（没有缝 / 开关关着）⇒ 难度没判成；"
                               "按受控拒处理 ——「没判成」不许折成「有理由」"
                               + (f"（装配读数：{self.model_source}）"
                                  if str(self.model_source or "") else "")))
            return out
        rows = []
        for one in (salvaged or ()):
            if not isinstance(one, Mapping):
                continue
            rows.append({"stmt_id": str(one.get("stmt_id") or ""),
                         "kind": str(one.get("kind") or ""),
                         "created_at": str(one.get("created_at") or ""),
                         "label": str(one.get("label") or ""),
                         "statement_full": str(one.get("statement_full") or "")[:JUDGE_MATERIAL_CAP]})
        material = {
            "statement_full": body[:JUDGE_MATERIAL_CAP],
            "proof_text": proof[:JUDGE_MATERIAL_CAP],
            "difficulty": str(difficulty or ""),
            "abandon_basis": str(basis or ""),
            "salvaged": rows,
        }
        try:
            data, call = self.seam.ask_json(_judge_material(material),
                                            system=_abandon_difficulty_system(),
                                            task_id=task_id,
                                            note="secretary:abandon_difficulty")
        except Exception as exc:  # noqa: BLE001 —— 调用失败 = 没判成（fail-closed）
            out.update(refused="abandon_difficulty_not_judged",
                       reason=f"难度判定调用失败（{type(exc).__name__}: {exc}）⇒ 没判成")
            return out
        out["cost"] = dict(getattr(call, "cost", {}) or {})
        if not getattr(call, "ok", False) or not isinstance(data, Mapping):
            out.update(refused="abandon_difficulty_not_judged",
                       reason=(f"难度判定没拿到可用的 JSON（{getattr(call, 'problem', '') or 'no_reply'}:"
                               f"{str(getattr(call, 'detail', '') or '')[:160]}）⇒ 没判成"))
            return out
        genuine = data.get("genuine")
        from_proof = data.get("salvaged_from_proof")
        if not isinstance(genuine, bool):
            out.update(refused="abandon_difficulty_not_judged",
                       reason=(f"模型给的 genuine 不是布尔（收到 {genuine!r}）⇒ 不采信："
                               "这一问只有两态，第三档会让「没判成」冒充「有理由」"))
            return out
        if not isinstance(from_proof, bool):
            out.update(refused="abandon_difficulty_not_judged",
                       reason=(f"模型给的 salvaged_from_proof 不是布尔（收到 {from_proof!r}）"
                               "⇒ 不采信（同一档只有两态）"))
            return out
        where = str(data.get("where") or "").strip()
        problems = [str(x).strip() for x in (data.get("problems") or []) if str(x).strip()]
        decision = str(data.get("decision") or "").strip()
        if genuine and not where:
            out.update(refused="abandon_difficulty_not_judged",
                       reason=("模型判「这是真困难」，却读不出难在哪（where 是空的）⇒ "
                               "这一格没判成：合格必须能复述「难在哪」"))
            return out
        if (not genuine or not from_proof) and not problems:
            out.update(refused="abandon_difficulty_not_judged",
                       reason=("模型判不合格，却一条 problems 都没点名 ⇒ 这一格没判成："
                               "拒收必须逐条说缺什么"))
            return out
        refused = ""
        if not genuine:
            refused = "abandon_difficulty_not_genuine"
        elif not from_proof:
            refused = "abandon_salvaged_not_from_proof"
        out.update(checked=True, genuine=genuine, where=where,
                   salvaged_from_proof=from_proof, problems=problems,
                   decision=decision, refused=refused,
                   reason=(f"难度判定：{'是真困难，难在 ' + where if genuine else '不是真困难'}"
                           f"；salvaged {'取自原证明' if from_proof else '不是从原证明拆出来的'}"))
        return out
