# DEVELOPMENT —— agentflow 项目开发规范

> ⚠️ **权威性（2026-10-18 标注，2026-10 拆分后重写）**：本条目的职责**只有一件事** —— 告诉你
> "要改代码，先读哪几节"。**判据本身不在本文**：规范在 [`docs/DEVELOPMENT-SPEC.md`](docs/DEVELOPMENT-SPEC.md)，
> 历史在 [`docs/DEVELOPMENT-APPENDIX.md`](docs/DEVELOPMENT-APPENDIX.md)。
> 与代码冲突时**以代码为准**；若代码与规范冲突，是**规范的 bug**（处置见 SPEC §12）。
> 「哪份文档算数」的权威地图见 [`docs/INDEX.md`](docs/INDEX.md)。
>
> **本文为什么变短了**：它原来是一份一千多行的单文件，里面同时住着"规矩"与"读数快照"。
> 读数会过期而规矩不会 —— 两类内容住在一起，结果就是**每一次读数过期都会被读成规矩变了**。
> 所以 2026-10 把它拆成三份：**入口（本文）/ 规范（SPEC）/ 历史（APPENDIX）**。
> 拆分的验收判据是「规范里不再出现任何单个定值计数」—— 读数一律住 SPEC §0.2 的
> `LIVE-READINGS` 块，每条都带自己的复跑命令。

---

## 本文的职责（三句话）

1. **指路**：谁该读哪几节、在哪个文件里；
2. **定权威顺序**：代码 > 规范 > 角色规格 > `AGENTS.md`（仅禁 AI 区）> 设计理由 > README > 历史；
3. **不改写规矩**：任何规则只写在 SPEC 里一处 —— 本文重复它，就多了一份会漂的副本。

## 改代码前先读这三节

| 顺序 | 节 | 什么时候必须读 |
|---:|---|---|
| 1 | **SPEC §5 六条硬纪律** | **每次改动**（三态 / 单一来源 / fail-closed / 证据等级 / 拒绝≠失败 / 派生态） |
| 2 | **SPEC §8 禁止模式清单（P1–P18）** | **每次改动**（静态可查的形态；其中 P1–P9 与 P17–P18 已落成 lint 规则 R001–R012） |
| 3 | **SPEC §6 Definition of Done** | 按你改的东西选一份 checklist（表 / 字段 / 工具 / 交互 / 角色 / 验证门） |
| — | **SPEC §0.2 的 `LIVE-READINGS` 块** | 要**当前读数**时才读这一格；它由 `tests/test_release_all.py::test_development_md_linter_readings_and_rule_range_match_the_repo` 逐键盯着 —— **不要相信任何抄在散文里的数字** |

**加读**（按改动落点）：

- 改**某个角色** ⇒ [`docs/ROLE-SPECS.md`](docs/ROLE-SPECS.md) 该角色那一节 + SPEC §2 第 ④ 层；
- 改**工具层** ⇒ SPEC §2 第 ③ 层 + §6.3；
- 改 **Web / 用户端** ⇒ SPEC §2 第 ⑧ 层 + `tests/test_webui_contracts.py`；
- 改**禁 AI 区里的任何文件** ⇒ [`AGENTS.md`](AGENTS.md)（**最短、最硬**；命中即停，需 2 名 reviewer）；
- 要**当前读数** ⇒ SPEC §0.2（不要相信任何抄在散文里的数字）。

## 一句话记住

**规范要说的话，只在 SPEC 里说一次；本文只负责把你送到那一节。**
