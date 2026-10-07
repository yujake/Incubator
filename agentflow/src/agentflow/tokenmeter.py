"""FC-19：token/花销预算 —— 硬约束，且重试也计入。

## 为什么这一条最后才做，以及它为什么必须自己成一个模块

FC-19 的原文（`test/test2/LESSONS.md` §6.5）：

> token 预算是硬约束，重试也计入
> 为什么："Each retry is another billed provider request"（`04-…md` §B6）；
> 且框架不能假设它一定给你 token 预算 —— DSH 的 Ralph 目前只有轮次上限，
> token 预算是 deferred（`04-…md` §D3 ⑧）。
> 判据：① 每个子任务有 token 上限与最长轮次，超额即降级或返回当前最好答案。
> ② 重试计入预算（可判定：注入 N 次失败重试后，预算消耗 ≥ N × 单次成本）。
> ③ D 向 A 提问的预算必须已定值并写进配置。
> 落地形态：`token_meter` + 预算守卫 + 一条"重试也扣预算"的测试。

数据结构早就备好了（`UsageEntry` / `usage_ledger` / `Policy.token_budget` /
`CancelToken.token_budget`），但没有任何东西把花销记进去、也没有任何东西据此说"不"。
本模块补的正是这两件：

1. 记：`charge()` 把每一笔（包括零值）写进 `usage_ledger`。
2. 守：`guard()` 在开工之前回答"还允不允许"。

## 三条刻意的设计

① 重试按次计费。`Charge.attempts` 参与总量计算（`(in + out) × attempts`），
而不是"一次调用记一笔"。理由就是那句话：每次重试都是另一次计费请求。
只记一次的后果是：一条一直在重试的路径在账面上看起来和一条一次就成功的路径一样贵 ——
而那正是最该被看见的浪费。

② 零值也记。一次"跑了但没花 token"（纯本地计算）必须留下一条零值记录，
否则"没记账"与"花了零"无法区分，而"预算还剩多少"就永远答不准。
`UsageEntry.validate` 已经在 schema 层要求零值必须带 `note`。

③ 超预算之后仍然记账。`charge()` 在超预算时照样写（钱已经花了），
只是把 `over_budget=True` 报出来。拒绝的权力在 `guard()`（那是"开工之前"），
不在 `charge()`（那是"已经做完之后"）。把两者混起来会得到一个既不准又拦不住的账本。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import schema as S

__all__ = [
    "Charge",
    "TokenMeter",
    "MeterReading",
    "NOTE_SEP",
    "marker_of",
    "note_tokens",
    "row_with_idem_key",
]

#: 账本行 `note` 里各语义片段的分隔符。
#:
#: 为什么幂等键要作为其中一个片段写进 `note`：`usage_ledger` 的表结构
#: （`schema.UsageEntry`）在 FC-27 禁 AI 区里，加字段需要人编写 + 2 名 reviewer。
#: 在这个约束下 `note` 是唯一能承载"这一行属于哪个幂等键"的既有位置 ——
#: 这是已知的次优（键是文本，判重靠解析而不是索引），不是优选。
#: 把键做成一个分隔符切出来的 token（而不是子串）是这里能做到的最强形态。
NOTE_SEP = "；"


def marker_of(namespace: str, *parts: Any) -> str:
    """把 `(namespace, *parts)` 压成一个只含 `[a-z0-9-]` 的幂等标记。

    为什么必须压缩而不是原样拼接：`task_id` 里可能带 `#`、空格与全角分号，
    原样拼出来的标记会与 `note` 里别的片段互相干扰（甚至把两笔不同的账
    拼成同一个键）。摘要串既稳定又不会污染 `note` 的可读性。

    `namespace` 不参与哈希输入：它只是给人看的分类前缀。
    这样 `marker_of("idem", task_id, call_index)` 与历史上直接
    `sha256(f"{task_id}\\x1f{call_index}")` 算出来的键逐位相同 ——
    已有账本行与已发布清单里的键不会因为这次重构而失效。
    """
    raw = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return f"{namespace}-" + hashlib.sha256(raw).hexdigest()[:12]


def note_tokens(note: str) -> list[str]:
    """把 `note` 拆成 `NOTE_SEP` 分隔的片段（去空白、丢空片）。"""
    return [t.strip() for t in str(note or "").split(NOTE_SEP) if t.strip()]


def row_with_idem_key(rows: Any, idem_key: str) -> dict | None:
    """在若干账本行里找 `note` 中恰有这个幂等键 token 的那一行；找不到返回 `None`。

    ## 为什么按 token 精确比对，而不是子串包含

    子串比对（`if key in note`）会让 `idem-abc123` 命中 `idem-abc1234`。
    两个不同的键被判成同一笔的后果是静默少记一笔账 ——
    它比"多记一笔"更难发现，因为账面上一切都自洽。
    token 精确比对把这件事变成结构上不可能。

    `idem_key` 为空是错误而不是"匹配不上"：空键会让每一行都命中，
    于是所有花销都被折叠成第一笔。宁可抛，也不静默。
    """
    key = str(idem_key or "").strip()
    if not key:
        raise ValueError("idem_key 不能为空 —— 空键会让每一行都匹配上（花销全被折叠成第一笔）")
    for r in rows:
        if key in note_tokens(r.get("note")):
            return r
    return None


@dataclass(frozen=True)
class Charge:
    """一笔花销。`attempts` 参与计费（见模块 docstring 的设计①）。"""

    role: str
    scope: str
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    #: 这一笔是"花了几次才花出去"的。默认 1（一次成功）。
    attempts: int = 1
    task_id: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.scope not in S.USAGE_SCOPES:
            raise ValueError(f"scope 必须是 {S.USAGE_SCOPES} 之一，收到 {self.scope!r}")
        if self.tokens_in < 0 or self.tokens_out < 0:
            raise ValueError("token 数不能为负")
        if self.usd < 0:
            raise ValueError("usd 不能为负")
        if self.attempts < 1:
            raise ValueError(f"attempts 从 1 开始（收到 {self.attempts}）")

    @property
    def per_attempt_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def tokens(self) -> int:
        """计费口径：每次尝试的量 × 尝试次数。

        为什么不是"一次调用记一笔"：`04-…md` §B6 的原话是
        "Each retry is another billed provider request"。
        只记一次的后果是一直在重试的路径在账面上与一次就成功的路径一样贵 ——
        而那正是最该被看见的浪费。
        """
        return self.per_attempt_tokens * self.attempts

    @property
    def usd_total(self) -> float:
        return self.usd * self.attempts


@dataclass(frozen=True)
class MeterReading:
    """账本的一次读数。`limited` 与 `allowed` 是两件事。

    - `limited=False` ⇒ 这台部署没设预算 ⇒ `allowed=True` 但语义是"不限制"，
      不是"够用"。把两者折叠成一个 `True`，就无法回答
      "预算守卫生效了没有"。
    """

    limited: bool
    allowed: bool
    spent_tokens: int
    spent_usd: float
    budget_tokens: int | None
    budget_usd: float | None
    remaining_tokens: int | None
    remaining_usd: float | None
    estimate_tokens: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "limited": self.limited,
            "allowed": self.allowed,
            "spent_tokens": self.spent_tokens,
            "spent_usd": self.spent_usd,
            "budget_tokens": self.budget_tokens,
            "budget_usd": self.budget_usd,
            "remaining_tokens": self.remaining_tokens,
            "remaining_usd": self.remaining_usd,
            "estimate_tokens": self.estimate_tokens,
            "reason": self.reason,
        }


class TokenMeter:
    """花销记账 + 预算守卫。只动 `usage_ledger` 一张表。

    记账本身不占用 `LOCK_ORDER` 里的其它表，所以它不会与
    "某个 agent 正持有 relations 锁" 相互阻塞 —— 这一点在并发编队里很重要：
    记账是每次调用都要做的事，若它去抢一张被别处长期持有的表，整个编队会排队。
    """

    def __init__(self, store: Any, *, budget_tokens: int | None = None,
                 budget_usd: float | None = None, log: Any = None) -> None:
        if budget_tokens is not None and budget_tokens <= 0:
            raise ValueError(
                f"budget_tokens 必须为正（收到 {budget_tokens}）。**0 与 None 语义不同**："
                "`None` = 没设预算，0 = 预算为零（什么都不准做）"
            )
        if budget_usd is not None and budget_usd < 0:
            raise ValueError(f"budget_usd 不能为负（收到 {budget_usd}）")
        self.store = store
        self.budget_tokens = budget_tokens
        self.budget_usd = budget_usd
        self._log = log

    # ---------------------------------------------------------------- 读账

    def spent(self) -> dict:
        """从 `usage_ledger` 汇总已花。

        每次都从表里读，不在内存里缓存：账本是唯一的权威，
        而内存缓存会让"另一个进程刚记了一笔"在这边看不见 —— 那正是
        "预算判断按哪一份"这类问题的来源。
        """
        rows = self.store.rows("usage_ledger")
        tokens = sum(int(r.get("tokens_total") or 0) for r in rows)
        usd = sum(float(r.get("usd") or 0.0) for r in rows)
        attempts = sum(int(r.get("attempts") or 1) for r in rows)
        return {"entries": len(rows), "tokens": tokens, "usd": usd, "attempts": attempts}

    # ---------------------------------------------------------------- 记账

    def tokens_for(self, task_id: str) -> int:
        """把某一次召唤的 token 累计值从账本里读回来。

        ## 为什么必须有这个读取口（`tasks.tokens` 的单一来源）

        `verify.py` 会检查 `tasks.tokens` 与 `usage_ledger` 里该 task 的汇总
        相等（不一致就报 `usage_task_total_mismatch`："预算判断会按哪一份？"）。
        让 `Conductor.summon` 自己累加一遍再写 `tasks`，那个相等就只是
        "两处各算一遍但愿它们相等" —— 任何一条路径漏记（例如此刻还没接线的
        各 agent `_call`，或者一次重试）都会让它静默不等。

        有了这个读取口，`summon` 的写法是"先 charge，再把账本上的值抄进 tasks"，
        于是相等是由构造保证的，不是靠两处算法碰巧一致。

        `usd_for` 同理（见下）。
        """
        rows = self.store.rows("usage_ledger")
        return sum(
            int(r.get("tokens_total") or 0)
            for r in rows if str(r.get("task_id")) == str(task_id)
        )

    def usd_for(self, task_id: str) -> float:
        """`usd` 的对应读取口（与 :meth:`tokens_for` 同一口径、同一理由）。

        ## 粒度口径（P-09 要求先定死的那一条）

        记账的粒度是召唤级：一笔账对应 `tasks` 里的一行（一次
        `conductor.summon`），由 `Conductor._charge_and_settle` 在召唤结束时写。
        而 E/F 的"一轮"发生在那一次召唤的内部 ⇒ 本方法给的是
        "这一次召唤的累计花销"，既不是"这一轮"的花销，也不是"这个角色"的花销。
        要更细的粒度（每一轮）得先把记账下沉到各 agent 的 `_call` 那一层，
        而那一步必须同时把 `conductor` 那一笔改成"只补零值兜底"
        （见 `_charge_and_settle` 的 docstring），否则同一笔钱会被记两次。

        边界：`task_id` 为空/`None` 时本方法返回 `0.0` —— 它不区分
        "没有挂点"与"挂上了但花了零"。要那三态就用 :meth:`usd_reading`。
        """
        rows = self.store.rows("usage_ledger")
        return round(sum(
            float(r.get("usd") or 0.0)
            for r in rows if str(r.get("task_id")) == str(task_id)
        ), 6)

    def usd_reading(self, task_id: str) -> dict:
        """某一次召唤的花销读数（三态；空 `task_id` 不返回一个像真数的 0）。

        为什么要有它（`44 J-07` + P-09）：现记账是召唤级，而"这一单还准花多少"
        与"这一单已经花了多少"必须能当场答出来；同时"没有挂点"与"花了零"是两件事
        —— 前者是"这笔钱根本没记到任何一次召唤上"（未接线），后者是"记了、金额是 0"。
        把它们折成同一个 `0.0`，正是本项目最贵的那个缺陷形态。

        | 情形 | `attached` | `usd` | `entries` |
        |---|---|---|---|
        | 没有挂点（`task_id` 为空 / `None`） | `False` | `None` | 0 |
        | 挂上了、账上一条都没有 | `True` | `0.0` | 0 |
        | 挂上了、有账 | `True` | 汇总（与 :meth:`usd_for` 同一算式） | n |

        粒度与 :meth:`usd_for` 逐字相同：召唤级（不是"这一轮"）。
        """
        want = str(task_id or "").strip()
        if not want:
            return {"attached": False, "usd": None, "entries": 0, "tokens": 0,
                    "reason": ("task_id 为空 / None ⇒ 这笔账没有挂点（不是「花了零」）—— "
                               "要挂到某一次召唤上，就把那次 summon 的 task_id 传进来")}
        rows = [r for r in self.store.rows("usage_ledger")
                if str(r.get("task_id")) == want]
        return {"attached": True,
                "usd": round(sum(float(r.get("usd") or 0.0) for r in rows), 6),
                "entries": len(rows),
                "tokens": sum(int(r.get("tokens_total") or 0) for r in rows),
                "reason": ("挂上了" if rows else
                           "挂上了，但账上一条都没有 ⇒ 这一单还没记过账（不是「花了零」）")}


    # ---- 行的构造（`charge` 与 `charge_once` 共用同一份，FC-03）

    @staticmethod
    def _reject_information_free_zero(c: Charge) -> None:
        """零值且不带任何说明的花销直接拒绝。

        判据必须在追加幂等键之前判：键会让 `note` 非空，于是
        `UsageEntry.validate` 会放行一条"只有幂等键、不含任何业务信息"的零值行 ——
        那正是这条守卫要挡的污染。
        """
        if c.tokens == 0 and c.usd_total == 0.0 and not c.note.strip():
            raise ValueError(
                "零值花销必须写 note —— **零值也要记**（否则'没记账'与'花了零'无法区分），"
                "但一条不带任何信息的零值行只会污染台账"
            )

    @staticmethod
    def _note_for(c: Charge, extra_token: str = "") -> str:
        """这一行的 `note`：`c.note` +（重试说明）+（幂等键 token）。

        顺序固定为"业务说明 → 重试说明 → 幂等键"，于是键永远是最后一个 token
        （可读性：人一眼看得到这一行的身份；正确性：token 比对不依赖位置）。
        """
        note = c.note
        if c.attempts > 1:
            note = (note + NOTE_SEP if note else "") + f"含重试 {c.attempts} 次（每次尝试都计费）"
        if extra_token:
            note = (note + NOTE_SEP if note else "") + extra_token
        return note

    @staticmethod
    def _row_for(c: Charge, *, uid: str, at: str, note: str, idem_key: str = "") -> S.UsageEntry:
        """按记账口径造一行 `UsageEntry`。

        `idem_key` 缺省是空串（`charge()` 走的路：没有幂等身份的行）。

        ## 为什么键要同时进字段与 `note`

        `note` 里的键是跨版本的那一层（老进程写的行也带它，提案 §3.3），
        字段是有结构、有表级唯一性断言的那一层（提案 A）。
        两层判据指向同一个键，所以它们必须由同一个值填充 ——
        两处各生成一次的话，将来只改一处就会写出"判重按 A、落盘按 B"的行，
        而那会让同一笔账被记两次且没有任何检查会响。
        """
        return S.UsageEntry(
            usage_id=uid,
            scope=c.scope,
            role=c.role,
            task_id=c.task_id,
            tokens_in=c.tokens_in,
            tokens_out=c.tokens_out,
            tokens_total=c.tokens,
            usd=round(c.usd_total, 6),
            attempts=c.attempts,
            at=at,
            note=note,
            idem_key=idem_key,
        )

    def charge(self, c: Charge, *, now: str | None = None) -> dict:
        """把一笔花销写进账本。永远写（包括零值与超预算）。

        返回 ``{"recorded", "usage_id", "tokens", "cumulative_tokens",
        "remaining_tokens", "over_budget", "reason"}``。

        `over_budget=True` 时照样写：钱已经花了，账必须记。
        拦住新工作的权力在 :meth:`guard`。
        """
        self._reject_information_free_zero(c)
        at = now or S.now_iso()
        note = self._note_for(c)
        # 行的构造必须在事务内、拿到真号之后。
        #
        # 曾经先在外面用一个 `usage_id="PENDING"` 占位、`validate()` 一遍再进事务换号 ——
        # 那会直接抛 `usage_id 必须是 4 位十进制字符串，收到 'PENDING'`。
        # 这条错很浅，但它示范了一条纪律：4 位 ID 的合法性只能在拿到真号之后判断，
        # 因为号是 `alloc_id` 在持锁事务内发的。用占位符"先校验后换号"在结构上不可能成立。
        with self.store.tx("usage_ledger", "counters", actor=f"tokenmeter:{c.role}",
                           note=f"charge:{c.scope}") as tx:
            uid = tx.alloc_id("usage")
            row = self._row_for(c, uid=uid, at=at, note=note)
            # 早炸：不合法就别写（与 store 的"先校验后落盘"同一条纪律）
            row.validate()
            tx.upsert("usage_ledger", row.to_dict(), note=f"charge:{c.scope}")

        after = self.spent()
        over = self._over(after["tokens"], after["usd"])
        return {
            "recorded": True,
            "usage_id": uid,
            "tokens": c.tokens,
            "attempts": c.attempts,
            "cumulative_tokens": after["tokens"],
            "cumulative_usd": round(after["usd"], 6),
            "remaining_tokens": (None if self.budget_tokens is None
                                 else self.budget_tokens - after["tokens"]),
            "over_budget": over,
            "reason": (
                "已记账" + ("；**已超出预算**（账照样记，拦住新工作的责任在 guard）" if over else "")
            ),
        }

    # ---------------------------------------------------------------- 幂等入账

    def charge_once(self, c: Charge, *, idem_key: str, now: str | None = None) -> dict:
        """账本层的幂等入账：判重与写入在同一次加锁内完成。

        ## 这就是"给 `usage_ledger` 加唯一键"在本技术栈里的等价物

        本项目没有数据库：`usage_ledger` 是 `data/usage_ledger.json`，写入形态是
        "取排他锁 → 读全表 → 改 → 原子替换（`os.replace`）"。于是
        "由存储保证同一个幂等键只落一条记录"这件事，在本栈里的等价物是：
        把判重与写入放进同一个临界区。

        `charge()` 的调用方若自己"先读账（`Store.rows` 是无锁快照读）再写账
        （`charge` 内部有锁）"，两次操作之间就是那个窗口：多个进程会同时读到
        "没有这笔账"，然后各自拿到一个不同的 `usage_id`，各写一行。
        按主键（`usage_id`）去重在这里救不了 —— 两行的主键本来就不同，
        `validate_table` 的"重复 ID"检查也不会响。

        实测（修复前，4 个进程、1 个幂等键）：账本落 4 行、总 token 6000，
        而只调用了一次的那个键应记 1500 —— 即 4 倍重复扣费。

        本方法把"读账"搬进 `charge` 本来就已持有的那把锁里，窗口因此消失。

        ## 返回

        ``{"recorded", "duplicate", "usage_id", "row"}``：

        - `recorded=True`：本次真的落了一行；
        - `recorded=False, duplicate=True`：这一笔早已入过账，本次没有重复扣费。
          这是正常结局，不是错误 —— 调用方据此返回幂等结果（而不是 500）。

        ## 键同时写进 `note` 的 token 与 `idem_key` 字段

        `note` 的 token 是唯一还在生效的判重依据（`row_with_idem_key` 读它），
        字段是表级唯一性断言的依据（`schema.validate_table` 对非空键断言整表唯一，
        `verify.duplicate_idem_key` 复查）。两者都写，且写的是同一个 `key`：

        - 只写 `note` ⇒ `UsageEntry.idem_key` 永远是空的，字段级防线在真实路径上形同虚设
          （这正是本方法此前留下的缺口）；
        - 只写字段 ⇒ 回滚到不认识该字段的旧版本之后（`rebuild` 会静默丢字段），
          判重就没有依据了。所以 B 层不许撤，两层都要。
        """
        self._reject_information_free_zero(c)
        key = str(idem_key or "").strip()
        if not key:
            raise ValueError(
                "idem_key 不能为空。没有键就没有幂等 —— 静默退化成 `charge()` "
                "会把'跨进程重复扣费'重新引回来，而那正是本方法要修的东西"
            )
        if NOTE_SEP in key or any(ch.isspace() for ch in key):
            raise ValueError(
                f"idem_key 不能含空白或 {NOTE_SEP!r}（那会把它拆成多个 token，"
                f"判重就会指向另一行）：{idem_key!r}。请用 marker_of() 生成键。"
            )
        at = now or S.now_iso()
        note = self._note_for(c, extra_token=key)

        with self.store.tx("usage_ledger", "counters", actor=f"tokenmeter:{c.role}",
                           note=f"charge:{c.scope}") as tx:
            # 这一读必须在锁内。它读的是本事务取到排他锁之后磁盘上的内容，
            # 所以另一个进程刚刚提交的那一行在这里一定看得见；
            # 反过来，若把这一读挪到 `with` 之外（无锁快照读），窗口就回来了。
            prior = row_with_idem_key(tx.rows("usage_ledger"), key)
            if prior is not None:
                return {
                    "recorded": False,
                    "duplicate": True,
                    "usage_id": str(prior.get("usage_id") or ""),
                    "row": dict(prior),
                }
            uid = tx.alloc_id("usage")
            row = self._row_for(c, uid=uid, at=at, note=note, idem_key=key)
            row.validate()
            tx.upsert("usage_ledger", row.to_dict(), note=f"charge:{c.scope}")
            return {
                "recorded": True,
                "duplicate": False,
                "usage_id": uid,
                "row": row.to_dict(),
            }

    # ---------------------------------------------------------------- 守卫

    def _over(self, tokens: int, usd: float) -> bool:
        if self.budget_tokens is not None and tokens > self.budget_tokens:
            return True
        return self.budget_usd is not None and usd > self.budget_usd

    def guard(self, estimate_tokens: int = 0, *, role: str = "unknown",
              scope: str = "summon") -> MeterReading:
        """开工之前问一句"还允不允许"。三态在 `limited` 上。

        - `limited=False` ⇒ `allowed=True`，但 reason 说的是"未设预算，不限制"
          （不是"够用"）。
        - `limited=True` ⇒ 按 `已花 + estimate` 与预算比较。

        为什么 estimate 要由调用方给：只有它知道"这一步大概要花多少"
        （例如"一次检索 ≈ 2000 token"）。守卫不该猜 —— 猜出来的数字会让
        "为什么拦了"变得不可复核。
        """
        now = self.spent()
        limited = self.budget_tokens is not None or self.budget_usd is not None
        remaining_t = None if self.budget_tokens is None else self.budget_tokens - now["tokens"]
        remaining_u = None if self.budget_usd is None else round(self.budget_usd - now["usd"], 6)

        if not limited:
            return MeterReading(
                limited=False, allowed=True,
                spent_tokens=now["tokens"], spent_usd=round(now["usd"], 6),
                budget_tokens=None, budget_usd=None,
                remaining_tokens=None, remaining_usd=None,
                estimate_tokens=estimate_tokens,
                reason=(
                    "**未设预算 ⇒ 不限制**（注意这与'预算够用'是两件事："
                    "没设预算意味着这个守卫**没有生效**，谁也不知道还能花多少）"
                ),
            )

        if self._over(now["tokens"], now["usd"]):
            return MeterReading(
                limited=True, allowed=False,
                spent_tokens=now["tokens"], spent_usd=round(now["usd"], 6),
                budget_tokens=self.budget_tokens, budget_usd=self.budget_usd,
                remaining_tokens=remaining_t, remaining_usd=remaining_u,
                estimate_tokens=estimate_tokens,
                reason=(
                    f"**已经超出预算**（已花 {now['tokens']} token / "
                    f"{round(now['usd'], 6)} usd，预算 {self.budget_tokens} / {self.budget_usd}）"
                    "⇒ 拒绝新工作（FC-19：超额即降级或返回当前最好答案，不静默继续花）"
                ),
            )

        would = now["tokens"] + max(0, int(estimate_tokens))
        if self.budget_tokens is not None and would > self.budget_tokens:
            return MeterReading(
                limited=True, allowed=False,
                spent_tokens=now["tokens"], spent_usd=round(now["usd"], 6),
                budget_tokens=self.budget_tokens, budget_usd=self.budget_usd,
                remaining_tokens=remaining_t, remaining_usd=remaining_u,
                estimate_tokens=estimate_tokens,
                reason=(
                    f"这一步预估 {estimate_tokens} token，加上已花的 {now['tokens']} "
                    f"会超过预算 {self.budget_tokens} ⇒ **在开工前拒绝**"
                    "（而不是做到一半再停）"
                ),
            )

        return MeterReading(
            limited=True, allowed=True,
            spent_tokens=now["tokens"], spent_usd=round(now["usd"], 6),
            budget_tokens=self.budget_tokens, budget_usd=self.budget_usd,
            remaining_tokens=remaining_t, remaining_usd=remaining_u,
            estimate_tokens=estimate_tokens,
            reason=(
                f"预算内：已花 {now['tokens']}，预估 {estimate_tokens}，"
                f"上限 {self.budget_tokens}，余 {remaining_t}"
            ),
        )

    # ---------------------------------------------------------------- 只读视图

    def by_role(self) -> dict[str, dict]:
        """按角色汇总。为什么要有它：花销总量只说明"花了多少"，
        而"是谁花的"才决定下一步该压谁 —— `04-…md` §B6 的教训是
        "不能假设预算一定给"，所以每一分钱都要能归口。"""
        out: dict[str, dict] = {}
        for r in self.store.rows("usage_ledger"):
            k = str(r.get("role") or "unknown")
            acc = out.setdefault(k, {"tokens": 0, "usd": 0.0, "entries": 0, "attempts": 0})
            acc["tokens"] += int(r.get("tokens_total") or 0)
            acc["usd"] = round(acc["usd"] + float(r.get("usd") or 0.0), 6)
            acc["entries"] += 1
            acc["attempts"] += int(r.get("attempts") or 1)
        return out

    def by_scope(self) -> dict[str, dict]:
        """按用途归口汇总（G-20）：账本要能回答"搜索/抽取/审校各花了多少"。

        与 `by_role` 是两条不同的轴，谁也不能代替谁：角色回答"是谁"，
        归口回答"为了什么"。同一次工作可以是 D 角色在做 search 归口的事。

        ## 每一个 `USAGE_SCOPES` 档都出现（含零值）

        返回的键集合恒等于 `S.USAGE_SCOPES` 加上 `S.SCOPE_UNCLASSIFIED`。
        为什么零值档也要出现：`{"search": {...}}` 与"没有 search 这一档"
        在 `dict.get("search")` 眼里是一样的，而两者含义完全不同 ——
        前者是"查过、没花钱"，后者是"根本没有这个归口"。做成固定键之后，
        "某一档归零"这件事在产物里是可见的（这正是 G-20 负控要的形态）。

        ## 内容

        `{"tokens", "usd", "entries", "attempts", "roles"}`：`roles` 是这一档里
        出现过的角色计数，用来回答"extract 的钱是 B 花的还是 D 花的"。
        """
        out: dict[str, dict] = {
            name: {"tokens": 0, "usd": 0.0, "entries": 0, "attempts": 0, "roles": {}}
            for name in tuple(S.USAGE_SCOPES) + (S.SCOPE_UNCLASSIFIED,)
        }
        for r in self.store.rows("usage_ledger"):
            raw = str(r.get("scope") or "").strip()
            # 词表外的值（历史行、或别的写入方）落在显式的"未分类"档里，
            # 而不是被丢掉、也不是被塞进"其它"：丢掉会让总额对不上，
            # 塞进 other 会把"有人写了编外的归口"这件事藏起来。
            k = raw if raw in S.USAGE_SCOPES else S.SCOPE_UNCLASSIFIED
            acc = out[k]
            acc["tokens"] += int(r.get("tokens_total") or 0)
            acc["usd"] = round(acc["usd"] + float(r.get("usd") or 0.0), 6)
            acc["entries"] += 1
            acc["attempts"] += int(r.get("attempts") or 1)
            role = str(r.get("role") or "unknown")
            acc["roles"][role] = acc["roles"].get(role, 0) + 1
        out[S.SCOPE_UNCLASSIFIED]["raw_values"] = sorted({
            str(r.get("scope") or "") for r in self.store.rows("usage_ledger")
            if str(r.get("scope") or "").strip() not in S.USAGE_SCOPES
        })
        return out

    def retry_overhead(self) -> dict:
        """重试造成的额外开销（可判定判据②的正面证据）。

        `overhead = Σ per_attempt × (attempts - 1)`：如果所有调用都一次成功，
        它是 0；它越大，说明越多的钱花在"同一件事的第二遍"上。
        """
        extra = 0
        retried = 0
        for r in self.store.rows("usage_ledger"):
            a = int(r.get("attempts") or 1)
            if a <= 1:
                continue
            total = int(r.get("tokens_total") or 0)
            per = total // a
            extra += per * (a - 1)
            retried += 1
        return {"extra_tokens": extra, "entries_with_retry": retried}
