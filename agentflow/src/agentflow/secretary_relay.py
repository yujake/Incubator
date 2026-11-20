# -*- coding: utf-8 -*-
"""秘书的转发链（正文只在链尾，从 secretary.py 的 U12 逐字搬出）。

我保证哪条不变式：正文只在链尾交给本人；台账不成不发。造下一跳秘书只经装配口 `self._new_secretary(...)`（混入模块不许 import 组装层，那会成环）。

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

from . import schema as S
import time

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    RELAY_ID_PREFIX,
    append_jsonl,
    append_jsonl_stamped,
    relay_path,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)


class RelayMixin:
    """转发链（正文只给链尾）（从 secretary.py 搬出的混入类）。"""

    def relay_out(self, *, chain: Sequence[str], body: str, subject: str = "",
                  sender_role: str = "") -> dict[str, Any]:
        """发送方的秘书：把正文交给链上第一跳的秘书（载荷里的 `remaining_chain`）。

        返回三态回执（键集在所有分支上相同）：
        `checked` / `status`（`delivered` / `refused` / `unknown`）/ `relay_id` /
        `delivered_to`（链尾那一个的绝对编号；只有 `delivered` 非空）/ `hops`
        （每跳：`hop` / `of` / `at` / `elapsed_us` / `delta_us` / `secretary_task_id` /
        `secretary_role` / `mode`（`forward` / `deliver`）/ `from` / `to` /
        `remaining_chain` / `content_read` / `item_id` / `relay_id`）/ `problems` /
        `refused` / `error` / `item_id`。每跳另带两格时间：`elapsed_us`（从发送方
        秘书起手那一刻算起的累计微秒数）与 `delta_us`（这一跳自己花掉的微秒数）——
        为什么两格都给：只给累计值时"哪一跳慢"要靠相邻相减，而相减在只有这一份
        读数的人手里做不了。

        ## 为什么"转发台账写不成就不发"
        这一条链的全部可审计性就在那份台账上（谁在哪一跳收到过、正文有没有给代理本人
        看）。台账写不成而正文照样往下走，回执会说 `delivered` 而盘上一条记录都没有
        —— 那正是本仓最忌的"回执说谎"。所以第一跳的台账写不成 ⇒ `unknown` + 拒信，
        正文一步都不动（fail-closed 只落在"盘上能不能留下这件事"这一格）。
        """
        out: dict[str, Any] = {
            "checked": False, "status": "unknown", "relay_id": "", "delivered_to": [],
            "hops": [], "problems": [], "refused": "", "error": "", "item_id": "",
        }

        def _stop(code: str, why: str, *, status: str = "refused") -> dict[str, Any]:
            out.update(status=status, refused=code, error=why)
            return out

        hops = [str(x) for x in (chain or ())]
        mine = str(self.task_id or "")
        if len(hops) < 2:
            return _stop("broken_chain",
                         f"链只有 {len(hops)} 跳 ⇒ 没有可发给的下一跳（链至少要有一级下级）")
        if hops[0] != mine:
            return _stop("broken_chain",
                         f"链头是 {hops[0]}，而这一位秘书服务的是 {mine or '（没绑实例）'}"
                         " ⇒ 这条链不是从它出发的，不转")
        t0 = time.perf_counter()
        t_hop = t0
        rest = hops[1:]
        peer, why = self._peer_secretary(rest[0])
        if peer is None:
            return _stop("not_in_roster", f"第一跳 {rest[0]} 的秘书拿不到：{why}",
                         status="unknown")
        rec = self._relay_rec(hop=1, of=len(hops), mode="forward", chain=hops,
                              remaining_chain=rest[1:], content_read=False,
                              item_id="", t0=t0, t_hop=t_hop, subject=subject,
                              sender_role=sender_role, to=rest[0])
        ok, problem, rid = append_jsonl_stamped(relay_path(self.root), rec,
                                                field="relay_id", prefix=RELAY_ID_PREFIX)
        if not ok or not rid:
            return _stop("relay_unwritten",
                         f"转发台账没写成（{problem or '没有发到号'}）⇒ 正文一步都没动"
                         "（这一条链的每一跳都要在盘上留得下，回执才不是一句空话）",
                         status="unknown")
        rec["relay_id"] = rid
        out.update(checked=True, relay_id=rid)
        down = peer.relay_in(relay_id=rid, chain=rest, remaining_chain=rest[1:], body=body,
                             subject=subject, sender_role=sender_role, hops_total=len(hops),
                             t0=t0, full_chain=hops)
        out["hops"] = [dict(rec)] + list(down.get("hops") or [])
        out["problems"].extend(str(p) for p in (down.get("problems") or ()))
        out["delivered_to"] = list(down.get("delivered_to") or ())
        out["item_id"] = str(down.get("item_id") or "")
        out["status"] = str(down.get("status") or "unknown")
        out["refused"] = str(down.get("refused") or "")
        out["error"] = str(down.get("error") or "")
        return out

    def relay_in(self, *, relay_id: str, chain: Sequence[str],
                 remaining_chain: Sequence[str], body: str, subject: str = "",
                 sender_role: str = "", hops_total: int = 0,
                 t0: float = 0.0, full_chain: Sequence[str] = ()) -> dict[str, Any]:
        """某一跳的秘书收到一次转发：只看剩余链的头，链尾才把正文交给代理本人。

        `chain` 的头必须就是这一位秘书服务的那个代理（对不上 ⇒ 受控拒绝，不猜谁该读）。
        `remaining_chain` 是"还要往下走的那几跳"：本方法只读它的第一个元素，再把
        `remaining_chain[1:]` 交给下一跳的秘书 —— 这就是"只看链头"的机器形态。
        `content_read` 在除链尾以外的每一跳都是 `False`：正文只随载荷往下走，
        不进任何一位被转发的代理的板项。
        `full_chain` 是发送方写的那条完整链（只用于链尾那一句正文的抬头：读到正文的
        代理要看得见"它从哪来"，而不是只看见自己那一段）。转发逻辑不读它。
        """
        out: dict[str, Any] = {
            "checked": False, "status": "unknown", "relay_id": str(relay_id or ""),
            "delivered_to": [], "hops": [], "problems": [], "refused": "", "error": "",
            "item_id": "",
        }
        hops = [str(x) for x in (chain or ())]
        left = [str(x) for x in (remaining_chain or ())]
        mine = str(self.task_id or "")
        if not hops or hops[0] != mine:
            out.update(status="refused", refused="broken_chain",
                       error=(f"载荷的链头是 {hops[0] if hops else '（空）'}，而这一位秘书"
                              f"服务的是 {mine or '（没绑实例）'} ⇒ 不猜谁该读，退回"))
            return out
        total = int(hops_total or len(hops))
        hop_no = total - len(hops) + 1
        t0 = t0 or time.perf_counter()
        t_hop = time.perf_counter()
        if not str(relay_id or ""):
            out.update(status="unknown", refused="relay_unwritten",
                       error="载荷没有转发编号 ⇒ 这一跳落不了台账（没查成）")
            return out
        if left:
            nxt = left[0]
            peer, why = self._peer_secretary(nxt)
            rec = self._relay_rec(hop=hop_no, of=total, mode="forward", chain=hops,
                                  remaining_chain=left[1:], content_read=False,
                                  item_id="", t0=t0, t_hop=t_hop, subject=subject,
                                  sender_role=sender_role, to=nxt)
            rec["relay_id"] = str(relay_id)
            if peer is None:
                rec.update(status="unknown", refused="not_in_roster",
                           note=f"{nxt} 的秘书拿不到：{why}")
                ok, problem = append_jsonl(relay_path(self.root), rec)
                out.update(checked=ok, status="unknown", refused="not_in_roster",
                           error=(f"下一跳 {nxt} 的秘书拿不到：{why} ⇒ 链停在第 {hop_no} 跳"
                                  + ("" if ok else f"（这一跳的台账也没写成：{problem}）")))
                out["hops"] = [dict(rec)]
                return out
            ok, problem = append_jsonl(relay_path(self.root), rec)
            if not ok:
                out.update(status="unknown", refused="relay_unwritten",
                           error=(f"第 {hop_no} 跳的转发台账没写成（{problem}）⇒ 正文"
                                  "不再往下走（这一跳不可审计，就不能说它发生过）"))
                return out
            out["checked"] = True
            down = peer.relay_in(relay_id=str(relay_id), chain=left, remaining_chain=left[1:],
                                 body=body, subject=subject, sender_role=sender_role,
                                 hops_total=total, t0=t0, full_chain=list(full_chain) or hops)
            out["hops"] = [dict(rec)] + list(down.get("hops") or [])
            out["problems"].extend(str(p) for p in (down.get("problems") or ()))
            out["delivered_to"] = list(down.get("delivered_to") or ())
            out["item_id"] = str(down.get("item_id") or "")
            out["status"] = str(down.get("status") or "unknown")
            out["refused"] = str(down.get("refused") or "")
            out["error"] = str(down.get("error") or "")
            return out
        # ---- 链尾：只有这一跳把正文交给它管的那一个代理
        item_id, problem = self.deliver_local(
            body=body, chain_text="->".join(str(x) for x in (full_chain or hops)),
            origin=str(sender_role or S.CONDUCTOR_ROLE),
            subject=subject, relay_id=str(relay_id))
        rec = self._relay_rec(hop=hop_no, of=total, mode="deliver", chain=hops,
                              remaining_chain=[], content_read=True, item_id=item_id,
                              t0=t0, t_hop=t_hop, subject=subject,
                              sender_role=sender_role, to=mine)
        rec["relay_id"] = str(relay_id)
        ok, why = append_jsonl(relay_path(self.root), rec)
        if not ok:
            out["problems"].append(f"链尾那一跳的台账没写成：{why}（正文已经交给了 {mine}）")
        if item_id:
            out.update(checked=True, status="delivered", delivered_to=[mine],
                       item_id=item_id, hops=[dict(rec)])
        else:
            out.update(checked=True, status="unknown", error=problem,
                       problems=out["problems"] + [problem], hops=[dict(rec)])
        return out

    def deliver_local(self, *, body: str, chain_text: str, origin: str = "",
                      subject: str = "", relay_id: str = "") -> tuple[str, str]:
        """链尾：把正文交给这一位秘书服务的那一个代理（整条链上唯一"读内容"的一跳）。

        手法沿用既有的板项通道（`conductor.open_item` + `set_item_detail`）：收件人
        写这一个代理的台账号，于是它下一次进循环就在信箱里读到这一条；中途各跳
        一条板项都不开 —— 这是"不把内容给被转发的代理本人看"的全部实现。
        返回 `(板项编号, 问题)`；编号空 = 正文没有交给任何人（不许当"送到了"）。
        """
        cond = self._conductor()
        if cond is None:
            return "", "没有 store ⇒ 打不开板项（正文没有交给任何人）"
        mine = str(self.task_id or "")
        try:
            row = cond._task(mine) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return "", f"台账读不成（{type(exc).__name__}: {exc}）⇒ 不知道该开给谁"
        if not row:
            return "", f"台账里没有 {mine} 那一行 ⇒ 没有收件人，正文没有交给任何人"
        role = str(row.get("role") or self.role)
        head = f"沿链 {chain_text} 传来的指导" if chain_text else "沿链传来的指导"
        who = f"（{origin} 发出）" if origin else ""
        detail = f"{head}{who}：{body}" + (f"（主题：{subject}）" if subject else "")
        try:
            item_id = cond.open_item(
                kind="notice", role=role, expects="ack", action="notice",
                summary=str(body or "")[:200], called_by=str(origin or S.CONDUCTOR_ROLE),
                parent_task_id=mine, depth=int(row.get("depth") or 1) + 1,
                input_key=f"relay@{relay_id or mine}")
        except Exception as exc:  # noqa: BLE001 —— 开不成要如实说
            return "", f"板项没开成（{type(exc).__name__}: {exc}）⇒ 正文没有交给 {mine}"
        got, problem = cond.set_item_detail(item_id, detail)
        if problem:
            return item_id, f"板项 {item_id} 的正文没写进去（{problem}）"
        return item_id, "" if got else f"板项 {item_id} 的正文是空的"

    def _relay_rec(self, *, hop: int, of: int, mode: str, chain: Sequence[str],
                   remaining_chain: Sequence[str], content_read: bool, item_id: str,
                   t0: float, t_hop: float, subject: str, sender_role: str,
                   to: str) -> dict[str, Any]:
        """一条转发记录的公共字段（`relay_out` 与 `relay_in` 共用同一张表）。

        两格时间用 `time.perf_counter`（高分辨率）：`time.monotonic` 在本机实测
        只有毫秒级粒度，一跳几十微秒的转发会被一律读成 0 —— 那等于没有"每跳时间"。
        """
        now = time.perf_counter()
        return {"kind": "relay_hop", "hop": int(hop), "of": int(of), "mode": str(mode),
                "secretary_role": self.role, "secretary_task_id": str(self.task_id or ""),
                "from": str(self.task_id or ""), "to": str(to or ""),
                "chain": [str(x) for x in chain],
                "remaining_chain": [str(x) for x in remaining_chain],
                "content_read": bool(content_read), "item_id": str(item_id or ""),
                "subject": str(subject or ""), "sender_role": str(sender_role or ""),
                "elapsed_us": int(max(0.0, now - float(t0 or now)) * 1_000_000),
                "delta_us": int(max(0.0, now - float(t_hop or now)) * 1_000_000),
                "at": _now_iso()}

    def _peer_secretary(self, task_id: str) -> tuple[Any, str]:
        """链上下一跳那一位秘书（角色从台账读；只分片，不写存活标记）。

        为什么走 `bind_task(..., mark_alive=False)` 而不是裸赋值：`task_id` 现在是只读
        属性，唯一的写点就是 `bind_task`；而 `bind_task` 的默认那一档会写
        `<role>-<task>.alive`，把它读成"有一个进程正在跑" —— 转发是一次请求，不是
        一次接管。存活标记只该由真正跑起来的循环写（`agent_loop` 那一路），秘书替它
        写等于伪造"它活着"（`secretary_alive` 会把发送方进程的 pid 读成下一跳的，
        "上次没善终"从此读错）。所以这里用 `bind_task` 的"代表别人"那一档：只拿分片。
        """
        cond = self._conductor()
        if cond is None:
            return None, "没有 store ⇒ 读不到台账号对应的角色"
        try:
            row = cond._task(str(task_id or "")) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return None, f"台账读不成（{type(exc).__name__}: {exc}）"
        if not row:
            return None, f"台账里没有 {task_id} 这一行"
        role = str(row.get("role") or "")
        if not role:
            return None, f"{task_id} 那一行没有角色 ⇒ 不知道交给哪个秘书"
        try:
            peer = self._new_secretary(role, root=self.root, store=self.store, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 造不出秘书要如实说
            return None, f"造不出 {task_id} 的秘书（{type(exc).__name__}: {exc}）"
        peer.bind_task(str(task_id), mark_alive=False)
        return peer, ""
