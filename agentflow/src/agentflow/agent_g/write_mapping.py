"""角色 G 的动作 `write_mapping`。

只做转交：行的解析、三份渲染、写完再读一遍都在工具层 `doc.write_mapping` 里
（它只调 `papermapping.parse_rows` 与 `write_package`）。这一层不另立第二套
"写成功了"的说辞 —— 判据要的是"md 与附录由 json 渲染"。
"""
from __future__ import annotations

from ._support import Any, Mapping, Sequence


class _WriteMapping:
    def write_mapping(self, project: str, rows: Sequence[Mapping[str, Any]]) -> dict:
        """写论文对应表三份（`MAPPING.json` / `MAPPING.md` / 正文附录），先出表再写正文。

        参数与工具层逐字一致、原样转发不加格（`additionalProperties=False` 会把多出来的
        参数判成非法调用）。失败时 `_call` 上抛（`mapping_unresolvable` / `mapping_empty` /
        `mapping_not_clean` / `io_error` / `bad_project`）；成功返回"写完再读"的读数。
        """
        data = self._call("doc.write_mapping", project=project, rows=list(rows))
        self._emit(f"写论文对应表 {data.get('rows')} 行 state={data.get('state')}")
        return dict(data)
