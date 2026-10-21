"""A 的"会应变"能力面（2026-10-16，业主口径："把 A 做成真的智能体"）。

## 为什么补这个文件

`search.download` 失败时此前把下载层的细分类压成笼统的 `download_failed`
（`res.kind` 只留在自由文本里）⇒ A 读不到"为什么没下到"，也就无法决定
"换源 / 停手 / 重试"。而我亲自下一轮文献的读数说明这三类的正确处置是相反的：

| 类别 | 现场读数 | 正确处置 |
|---|---|---|
| `tls_cert` | 同一 URL 默认 122 秒才判死（本机证书/吊销检查），换客户端开关后 0.55 秒拿到状态码 | 换源；重试修不好 |
| `tls_timeout` | MDPI 那个 PDF 连试三次都是它（对方挡脚本） | 至多再试一次 |
| `http_403` | 浏览器化请求头也照样 403 | 直接换源，别重试 |

⇒ 三类必须分别可见地传到 A 手上（第 1、2 组），而且 A 被告知的类名必须与
代码真能产出的类名对齐（第 3 组，业主点名的"描述侧对齐"）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentflow import fetch as F
from agentflow.store import Store
from agentflow.tools import search_tools
from agentflow.tools.base import ToolRegistry


class _FakeDownloader:
    """替身下载器：照给定结果回答，并记下被请求的 URL。"""

    max_bytes = 8 * 1024 * 1024

    def __init__(self, result: F.FetchResult) -> None:
        self._result = result
        self.calls: list[str] = []

    def download(self, url: str, dest_dir: Path, filename_hint: str = "") -> F.FetchResult:
        self.calls.append(url)
        return self._result


def _registry(tmp_path: Path, result: F.FetchResult) -> tuple[ToolRegistry, _FakeDownloader]:
    store = Store(tmp_path / "ws")
    store.init()
    fake = _FakeDownloader(result)
    reg = ToolRegistry(name="a-recovery-face")
    reg.bound_role = "A"
    search_tools.register(reg, store=store, workspace=store.root, downloader=fake)
    return reg, fake


def _payload(res: object) -> dict:
    """工具结果的载荷：`fail(...)` 把具名参数放 `meta`，成功路径放 `data`（实测）。"""
    out: dict = {}
    for attr in ("data", "meta"):
        val = getattr(res, attr, None)
        if isinstance(val, dict):
            out.update(val)
    return out


# ============================================================ 第 1 组：类别要传下去


def test_a_download_failure_carries_the_fetch_layer_class(tmp_path) -> None:
    """正控：失败时 `fetch_kind` 要原样带出去（A 据此决定下一步）。"""
    result = F.FetchResult(ok=False, kind="tls_cert", error="tls_cert: 本机吊销检查够不到")
    reg, _fake = _registry(tmp_path, result)
    res = reg.call("search.download", url="https://example.invalid/paper.pdf")
    assert res.ok is False, res
    assert _payload(res).get("fetch_kind") == "tls_cert", _payload(res)


@pytest.mark.parametrize("kind", ["tls_cert", "tls_timeout", "http_403", "network_error"])
def test_each_class_stays_distinguishable(tmp_path, kind: str) -> None:
    """负控（防折平）：四个类别的正确处置各不相同 ⇒ 它们不许折成同一个值。

    （改前它们全被压成 `download_failed` ⇒ 这条会红。）
    """
    result = F.FetchResult(ok=False, kind=kind, error=f"{kind}: 探针")
    reg, _fake = _registry(tmp_path, result)
    res = reg.call("search.download", url="https://example.invalid/paper.pdf")
    assert _payload(res).get("fetch_kind") == kind, _payload(res)
    assert _payload(res).get("fetch_kind") != "download_failed", _payload(res)


# ============================================================ 第 2 组：描述侧对齐


def _a_literature_body() -> str:
    from agentflow import agent_skills as AS

    for skill in AS.skills_for("A"):
        if skill.slug.startswith("找文献"):
            return str(skill.body)
    raise AssertionError("A 的『找文献』技能不见了 —— 改名前先确认这份判据要守的是谁")


def _download_description() -> str:
    """`search.download` 声明给模型看的那段话（说明 ＋ returns）。"""
    reg = ToolRegistry(name="declared-face")
    reg.bound_role = "A"
    search_tools.register(reg, store=None, workspace=None)
    spec = reg.get("search.download")
    return f"{spec.summary}\n{getattr(spec, 'returns', '')}"


def _class_names_in(text: str) -> set[str]:
    """从一段描述里挑出像失败类别的那些词（受控词表里的 + `http_NNN`）。"""
    known = set(F.ERROR_KINDS)
    hits = {k for k in known if k in text}
    hits |= set(re.findall(r"http_\d{3}", text))
    return hits


def test_both_description_surfaces_tell_a_the_same_classes() -> None:
    """描述侧对齐：`search.download` 的说明与 A 的手册必须说到同一批类别。

    为什么不是"两边提到同样的字"就算过：这里取的是两边各自命中的类名集合，
    要求两集合相等（不是包含）—— 少一边就说明有读者会被漏掉：
    只写进工具说明、没写进手册 ⇒ A 不知道该怎么办；只写进手册、工具不报 ⇒ A 看不到。
    """
    tool_hits = _class_names_in(_download_description())
    manual_hits = _class_names_in(_a_literature_body())
    assert tool_hits, "工具说明里一个失败类别都没提 —— 那 A 只能看到一个笼统的失败"
    assert tool_hits == manual_hits, (
        f"工具说明 {sorted(tool_hits)} 与 A 的手册 {sorted(manual_hits)} 对不上"
    )


def test_the_classes_a_is_told_about_are_really_producible() -> None:
    """反真空：A 被告知的类名必须是下载层真能产出的（不许写一个不存在的档）。"""
    told = _class_names_in(_a_literature_body()) | _class_names_in(_download_description())
    assert told, "一个类名都没有 ⇒ 上面那条对齐是空断言"
    producible = set(F.ERROR_KINDS) | {"http_403", "http_401"}
    unknown = {k for k in told if k not in producible and not re.fullmatch(r"http_\d{3}", k)}
    assert not unknown, f"这些档位在 fetch 层产不出来（描述与实现漂了）：{sorted(unknown)}"


# ============================================================ 第 3 组：手册要求的事，A 要真做得到


def _a_tools_and_actions(tmp_path: Path) -> tuple[set[str], set[str]]:
    """A 真有的工具名与动作名（工具面读完整注册表，动作面读声明真身）。"""
    from agentflow.specs import a as A_spec
    from agentflow.tools import build_registry

    store = Store(tmp_path / "full")
    store.init()
    reg = build_registry(store=store, workspace_root=store.root).registry
    tools = {n for n in reg.names() if "A" in (reg.get(n).roles or ())}
    actions = {f"A.{spec.action}" for spec in A_spec.ACTIONS}
    return tools, actions


def test_every_tool_the_manual_names_is_one_a_can_actually_call(tmp_path) -> None:
    """描述侧对齐（能力面）：手册里点名的工具，A 必须真能调。

    为什么这条不是"机械判据"：它守的是两份描述之间的一致性（手册说"你去调 X"
    ↔ 工具面里到底有没有 X）。手册让 A 去调一件它没有的工具，A 那一趟就只能空转；
    而这件事在纯行为测试里测不出来（要真模型才会踩）。
    """
    tools, actions = _a_tools_and_actions(tmp_path)
    assert len(tools) >= 20, f"A 的工具面只剩 {len(tools)} 件 ⇒ 先解释清楚再改这条下限"

    body = _a_literature_body()
    namespaces = {n.split(".")[0] for n in tools}
    mentioned = {
        m.group(0)
        for m in re.finditer(r"\b([a-z_]+)\.([a-z_][a-z0-9_]*)\b", body)
        if m.group(1) in namespaces
    }
    assert mentioned, "手册里一个工具名都没提 ⇒ 这条判据是空断言"
    missing = {n for n in mentioned if n not in tools and n not in actions}
    assert not missing, (
        f"手册让 A 去调这些，而 A 的工具面里没有：{sorted(missing)}"
        f"（A 的工具面示例：{sorted(tools)[:5]}…）"
    )

