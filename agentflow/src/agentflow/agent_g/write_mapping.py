# -*- coding: utf-8 -*-
"""G 的 `write_mapping` 动作：论文对应表三份的唯一写口（转发工具层）。"""
from __future__ import annotations

from ._support import Any, Mapping, Sequence


class _WriteMapping:
    def write_mapping(self, project: str, rows: Sequence[Mapping[str, Any]],
                      path_order: Sequence[str] | None = None) -> dict:
        """写论文对应表三份（`MAPPING.json` / `MAPPING.md` / 正文附录），先出表再写正文。

        参数与工具层逐字一致、原样转发不加格（`additionalProperties=False` 会把多出来的
        参数判成非法调用）。`path_order` 是 2026-11-26（GMAP）加的那一格：这一篇按 C 的
        哪一条路径行文（C 报告 `payload.order` 原样）。不给它就不传 —— 工具层的
        `path_order` 是可选的字符串数组，显式传 `None` 会被参数门判成类型错。
        失败时 `_call` 上抛（`mapping_unresolvable` / `mapping_empty` /
        `mapping_not_clean` / `io_error` / `bad_project`）；成功返回"写完再读"的读数。
        """
        kwargs: dict[str, Any] = {"project": project, "rows": list(rows)}
        if path_order is not None:
            kwargs["path_order"] = [str(node) for node in path_order]
        data = self._call("doc.write_mapping", **kwargs)
        self._emit(f"写论文对应表 {data.get('rows')} 行 state={data.get('state')}")
        return dict(data)
