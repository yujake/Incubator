# -*- coding: utf-8 -*-
"""只读面的读模型（`draft/73` §2.3 的本体；属于 B 线那一批）。

## 本批（W0）只安排接缝

`draft/78 §3` 说：没有这三条接缝，任何两条线都会撞在同一个文件上。所以 W0 在这里
只留下形状，不实现任何读模型 —— 三个名字就是 B 线接手的地方：

- :data:`ROUTES` —— 本模块挂到总路由表上的只读端点。`webui/routes.py` 的总表是
  `自有 + READER_ROUTES + WRITE_ROUTES` 拼出来的，所以这里加一条端点不需要去改
  A 线的文件（本批是空子表：W0 的只读端点只有快照与一趟详情，它们属于 A 线自有）。
- :func:`type_decls` —— 本模块那一段 TS 声明文本，被
  `agentflow/web/emit_types.py` 拼进 `ui/src/types.ts`（本批返回空串）。
- :data:`MISSING_TYPES` —— 本模块还欠的接口与理由。生成器把它们写成
  `types.ts` 末尾的 TODO 注释（这就是"其余接口留 TODO 注释并说明还缺哪个 reader"
  那条要求的落点：清单住在这里，不住在生成器里，于是 B 线补完一个接口只删自己
  文件里的一行）。

## B 线要实现的那些面（`draft/73` §2.3 的清单，逐条在这里点名）

一份读数一个函数，只读、三态、不吞异常，统一返回
`{"tri": Tri, "rows": [...], "reason": str, "source": str}`：
`handoffs` · `artifact_ledger` · `run_products` · `evidence_chain` ·
`machine_readings` · `acceptance` · `provider_states` · `verifications`。
它们读的是既有实现（`artifacts.read_ledger` / `manuscripts.rows` /
`store.rows(...)` / `toolchain.toolchain_report` / `reviewaccept.check_review` /
`verifications.list_verifications`），不另写第二份。
"""

from __future__ import annotations

__all__ = ["CHECKED_TYPES", "HANDLERS", "MISSING_TYPES", "PENDING_ENDPOINTS",
           "ROUTES", "UNCHECKED_TYPES", "type_decls"]

#: 本模块要挂到总路由表上的只读端点：`(method, path 模式, 处理器名字)`。
#: W0 是空子表 —— 快照与一趟详情是 A 线自有的两条（`/api/state`、`/run/{sid}`），
#: W1 的六个面（`/api/evidence` 等）从这一行开始加。
ROUTES: tuple[tuple[str, str, str], ...] = ()

#: 处理器的落点（`draft/78 §3` 的接缝之一）：键 = `ROUTES` 第三元素，
#: 值 = `(handler, params, query)` 签名的函数，`handler` 是 `WebHandler` 实例。
#: 有了它，B 线加端点只改这个文件，不必碰 A 线的 `server.py`（也不用往
#: `WebHandler` 上猴补丁）。`webui/routes.py:handler_for()` 会来读它。
HANDLERS: dict[str, object] = {}

#: 契约判据 C 的两份登记：本模块声明、而且在夹具上真读得出来的接口写进
#: `CHECKED_TYPES`（判据会逐键比对）；声明了但还没有读数的写进 `UNCHECKED_TYPES`
#: （`{接口名: 理由}`）。两份都住在本模块里 ⇒ B 线补一个接口时只删自己文件里的一行。
CHECKED_TYPES: tuple[str, ...] = ()
UNCHECKED_TYPES: dict[str, str] = {}

#: 契约判据 D 的例外面：本模块声明、但后端还没落地的端点（`{端点: 理由}`）。
#: 落地之后必须删掉这一行 —— 判据有一条反向断言专门抓"永不生效的豁免"。
PENDING_ENDPOINTS: dict[str, str] = {}

#: 本模块还欠的 TS 接口（`(名字, 缺哪个 reader)`）。生成器逐条写成 TODO 注释 ——
#: 于是"这个类型为什么还没有"在生成物里是看得见的，而不是一份空话。
MISSING_TYPES: tuple[tuple[str, str], ...] = (
    ("RunView",
     "缺本模块的「一趟详情」适配器（W1）；本批 ROUTES 里没有 `GET /api/run/{sid}`，"
     "所以它没有生产者"),
    ("EvidenceView",
     "缺 `readers.evidence_chain(store)`（W1）：`store.rows(\"statements\"/\"conjectures\"/"
     "\"experiments\"/\"review_findings\")` 的适配器"),
    ("ArtifactsView",
     "缺 `readers.artifact_ledger` / `readers.handoffs` / `readers.run_products`（W1）："
     "`artifacts.read_ledger` · `manuscripts.rows` · 六件产物那一路"),
    ("AcceptanceView",
     "缺 `readers.acceptance(root, ...)`（W1）：`reviewaccept.check_review` 的逐条读数"),
    ("MachineView",
     "缺 `readers.machine_readings(root)`（W1）：`toolchain.toolchain_report()` 与 "
     "`settings.load_settings()`（key 走 `ModelSpec.redacted()`）"),
    ("TaskRow", "缺 `store.rows(\"tasks\")` 的适配器（W1 的 readers 那一面）"),
    ("SearchRequestRow", "缺 `store.rows(\"search_requests\")` 的适配器（W1）"),
    ("ConjectureRow", "缺 `store.rows(\"conjectures\")` 的适配器（W1）"),
    ("ExperimentRow", "缺 `store.rows(\"experiments\")` 的适配器（W1）"),
    ("ArtifactRow", "缺 `artifacts.read_ledger` 的行适配器（W1）"),
    ("HandoffRow", "缺 `manuscripts.rows` 的行适配器（W1）"),
    ("SecretaryDecision", "缺 `secretary.decisions_path` 的读法（W1）"),
    ("AcceptanceCheck", "缺 `closing.py` 的 ACCEPTANCE-CHECKS 读者（W1）"),
    ("ReportStyle", "缺 `out/review/REPORT-STYLE.json` 的读者（W1）"),
    ("UsageRow", "缺 `store.rows(\"usage_ledger\")` 的适配器（W1）"),
)


def type_decls() -> str:
    """本模块那一段 TS 声明文本；W0 只留空串占位（B 线在 W1 填）。"""
    return ""
