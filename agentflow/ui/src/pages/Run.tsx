/*
 * 一趟详情（W0：空壳）。
 *
 * 还缺什么：后端那一趟的 JSON（`GET /api/run/{sid}`）落在 W1 —— 本批的
 * `webui/routes.py` 里只有服务端渲染的 `/run/{sid}`（HTML）与 `/api/state`。
 * 所以这一页现在只把"看的是哪一趟"如实显示出来，不假装有读数。
 */
import { Card } from "../components/Card";

export interface RunProps {
  sid: string;
}

export function Run(props: RunProps) {
  return (
    <Card title="一趟详情" subtitle={props.sid === "" ? "没给会话号" : `会话 ${props.sid}`}>
      <span class="empty">
        这一面还没有接线：事件回放与花销读数要等 W1 的读模型（`webui/readers.py`）与
        一趟详情的 JSON 端点。在那之前，服务端渲染的那一页照旧可用：
        <a href={`/run/${encodeURIComponent(props.sid)}`}>/run/{props.sid}</a>。
      </span>
    </Card>
  );
}
