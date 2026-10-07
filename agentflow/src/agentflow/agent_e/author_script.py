"""角色 E 的动作 `author_script`（S-10(a)）：把一份判据变成落进工作区的核验脚本。

## 它补的是哪一跳（`draft/44` S-10）

F 的 `counterexample_request` 造出来的 E 子目标带着判据（`script_spec` 的
`criterion` / `params` / `expected_bound`）却没有 `script_path`
⇒ `F._deploy_e` 只能回一句"没有给 `script_path` ⇒ 未推进"，那条子目标原地打转，
直到计划标记 `stalled`。这一跳就是"按判据写脚本"。

## 生成与判读是两件事（FC-16 一个字不改）

E 的判读路径（`run_experiment` / `_derive` / `_parse_conclusion` / `check_formal`）
必须是确定性的：结论只从脚本输出与检查器来，一次模型都不许问（FC-16）。
本动作只做生成。写出来的脚本仍然要自己打印 `REPRO_RESULT:` 那一行才作数，
判它的人还是 `run_experiment` 那一套规则。

`AgentE.__init__` 的 `llm` 形参此前刻意留着不用，理由写在 `_support.py` 的
模块 docstring 里（"显式说明 E 不用 LLM，而不是让调用方以为没传 llm 所以功能缺了一块"）。
现在它的用途收窄成一句话：只用来写脚本。

## 五种没写成，各归各的码（不许折成"原地打转"）

| 情形 | `reason` |
|---|---|
| 缝没接（`llm is None`） | `no_seam` |
| 判据不完整（缺 `criterion` 或 `expected_bound`） | `bad_spec` |
| 模型给的源码不合格（空 / 没有 `REPRO_RESULT` / 过长） | `bad_source` |
| 写盘失败（含落点越出工作区） | `write_failed` |
| 缝本身没查成（`judge_*`，原话见 `judge.reason_of`） | `judge_*` |

五档都返回 `ok=False` 且 `script_path=""` —— 调用方据此把码写进 `blocked_reason`：
`no_seam` 要去接线，`bad_source` 要改脚本，两件事不该在读数上长得一样。
"""
from __future__ import annotations

from ._support import Any, Mapping, Path, VT
from ..refusals import refuse

#: 生成的源码长度上限。超过它多半是模型把整篇解释都塞进了脚本：
#: 核验脚本要短到能一眼看完全部逻辑，否则"它凭什么判这条判据"没人复核得了。
MAX_SOURCE_CHARS = 20_000


def _prompt(criterion: str, params: str, bound: str, sid: str) -> str:
    """给模型的提示词：只要一个 JSON 对象，`source` 是脚本全文。"""
    lines = [
        "你在给一条数值核验实验写脚本（角色 E 的活）。",
        "",
        "这条实验要回答的判据：" + criterion,
    ]
    if params:
        lines.append("已知参数：" + params)
    lines.append("期望界：" + bound)
    if sid:
        lines.append("子目标号：" + sid)
    lines += [
        "",
        "硬要求（一条都不许省）：",
        "1. 自足的 Python 脚本，只用标准库；不联网、不读别的文件；",
        "2. 在 stdout 打印单独一行，行首就是 `REPRO_RESULT: `，后面跟一个 JSON 对象；",
        "3. 那个对象必须含四个键：result（supports / refutes / inconclusive 之一）、"
        "observations（这次到底算了什么：参数与读数）、"
        "counterexample（result 是 refutes 时给非空对象，否则 null）、"
        "negation_kind（not_proved / not_searched_here / no_local_evidence 之一）；",
        "4. 再给三样读数：bound（这次搜到哪个界）、strategy（用的枚举策略名）、"
        "scaling（成本曲线：每个规模多少秒、多少对象）—— 缺了它们，"
        "下一次实验就只能从零开始；",
        "5. 参数要小到几十秒内跑完。算不动就把规模调小、把 result 写成 inconclusive；"
        "不许硬凑一个结论。",
        "",
        "只输出一个 JSON 对象（不要解释、不要 Markdown 围栏），形如：",
        '{"source": "<完整脚本全文，换行写成 \\n>", '
        '"why": "<一句话：这份脚本凭什么能判这条判据>"}',
    ]
    return "\n".join(lines)


def _source_problem(source: str) -> str:
    """这份源码能不能当"会说结论的核验脚本"（空串 = 合格）。"""
    if not source.strip():
        return "模型给的脚本是空的"
    if "REPRO_RESULT" not in source:
        return "这份脚本不会说结论：里面没有 REPRO_RESULT（跑完也判不了这条判据）"
    if len(source) > MAX_SOURCE_CHARS:
        return (f"这份脚本太长了（{len(source)} 字符 > {MAX_SOURCE_CHARS}）："
                "核验脚本要短到能一眼看完全部逻辑")
    return ""


class _AuthorScript:
    def author_script(self, spec: Mapping[str, Any], *, rel_dir: str = "code",
                      name: str = "", sid: str = "") -> dict[str, Any]:
        """按判据写一份核验脚本，落进工作区并返回它的相对路径。

        参数
        ----
        spec : `{"criterion", "params", "expected_bound"}`（F 那一侧
            `counterexample_request` 交下来的那三样）。
        rel_dir : 落点目录，默认 `code/`。
        name : 文件名，默认按 `sid` 生成（`attack_<sid>.py`）。

        为什么必须落进工作区（这一条踩过）：`check_formal(source=...)` 把源码放在
        临时目录里跑，那份文件既不是 `proof_location`、也交不了
        `run_experiment(script_path=...)`：裁决与落库之间只差"把源码写进工作区"。
        """
        criterion = str(spec.get("criterion") or "").strip()
        params = str(spec.get("params") or "").strip()
        bound = str(spec.get("expected_bound") or "").strip()
        if not criterion or not bound:
            # 走 `refuse`：这是"这次调用本身不成立"（判据不全 ⇒ 没有可执行的活），
            # 与 `A.ingest_local` 的 `bad_books_dir` 同一档。先例：`A.search_literature`
            # 的 `no_provider`（环境里没有 provider）也走 `refuse` —— 所以下面 `no_seam`
            # 同样走它，理由是"缺前置条件"而不是"执行了没成功"。
            return refuse("bad_spec",
                          ("判据不完整（criterion 与 expected_bound 都要有）⇒ 写不出脚本；"
                           f"收到 criterion={criterion!r}、expected_bound={bound!r}"),
                          reason="bad_spec", script_path="", sha256="")
        if self.llm is None:
            return refuse("no_seam",
                          ("E 这一次没有接模型缝（llm=None）⇒ 写不出脚本。"
                           "接线的办法是 llmseam.set_role_seam(\"E\", ...)（host 装配时登记）——"
                           "这一条缺的是缝，不是脚本"),
                          reason="no_seam", script_path="", sha256="")
        from .. import judge as J  # 惰性：`llmseam` 那一串在 import 期会绕回来

        data, problem = J.judge_json(self.llm, _prompt(criterion, params, bound, sid),
                                     point="E.author_script")
        if problem or not isinstance(data, Mapping):
            # `judge_json` 给的码本来就在 `judge_*` 词表里（`judge_bad_json` /
            # `judge_failed:<异常类名>` / …）⇒ 这里不再加前缀（加了会得到
            # `judge_judge_failed:…` 这种谁也匹配不上的码，而它照样是个"字符串原因"，
            # 不会有任何判据因此变红 —— 这一条是这块代码第一次跑起来时自己报出来的）。
            #
            # 这一支不走 `refuse`：缝没答上来是"执行了、没成功"（网关炸了 / 回了坏 JSON），
            # 不是"这次调用本身不成立" ⇒ `kind` 给字面量 `judge_failed`（细一档的具体码
            # 留在 `reason` 里，它可能是 `judge_failed:RuntimeError` 这种动态串）。
            # 登记见 `tests/test_refusals.py::_FAILURES_NOT_REFUSALS`。
            code = problem or "judge_bad_json"
            return {"ok": False, "kind": "judge_failed", "reason": code,
                    "script_path": "", "sha256": "",
                    "note": (f"写脚本这一跳没查成：{J.reason_of(code, point='E.author_script')}"
                             "⇒ 这一条卡在'缺一份能跑的脚本'上，不是'这条路死了'")}
        source = str(data.get("source") or "")
        why = str(data.get("why") or "").strip()
        bad = _source_problem(source)
        if bad:
            # 同上：模型回了一份不合格的脚本 = 执行了、产出不能用 ⇒ 登记为 `failed`。
            return {"ok": False, "kind": "bad_source", "reason": "bad_source",
                    "script_path": "", "sha256": "",
                    "note": f"模型写的脚本不合格：{bad}（它自己的 why：{why[:120]}）"}
        leaf = name or ("attack_" + (str(sid or "").strip() or "s") + ".py")
        rel = f"{str(rel_dir).strip('/')}/{leaf}"
        try:
            full: Path = self._resolve(rel)
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(source if source.endswith("\n") else source + "\n",
                            encoding="utf-8", newline="\n")
        except Exception as exc:  # noqa: BLE001 —— 落点越界与写盘失败都是"没做成"，如实报
            # 不走 `refuse`：写盘失败是"执行了、没成功"（与 `paper_package` 的
            # `state_failed` 同族：读盘/写盘失败不等于这次调用不成立）⇒ 登记为 `failed`。
            return {"ok": False, "kind": "write_failed", "reason": "write_failed",
                    "script_path": "", "sha256": "",
                    "note": (f"脚本没能落盘（{type(exc).__name__}: {exc}）⇒ 这一条子目标"
                             "没有可跑的脚本")}
        out = {"ok": True, "reason": "", "script_path": rel, "sha256": VT.code_hash(full),
               "chars": len(source), "model_why": why,
               "note": (f"脚本已落进工作区 {rel}（sha256 前 16 位 {VT.code_hash(full)}）——"
                        "它仍要跑出 REPRO_RESULT 才作数（判读那一段一个字没改，FC-16）")}
        self.last_authored = out
        return out
