/*
 * 一格读数的「原文」入口（`GET /api/source`）。
 *
 * 为什么不是一条 `<a href="file:///...">`：浏览器从 http 页面打不开 file://；
 * 为什么不是页面自己 `fetch(path)`：端点必须只从 `api.ts` 走（`test_webui_pages.py`
 * 的 `test_every_page_is_registered...` 会抓页面源码里的裸 `fetch(`）。
 *
 * 三态：`tri="computed"` 才显示行；`unreadable`（越界 / 后缀不认 / 文件不在 /
 * 没找到 needle）只显示拒因，不显示内容 —— 路径闸的拒绝理由原样给读的人看。
 */
import { useState } from "preact/hooks";

import { api } from "../api";
import type { SourceRef, SourceWindow } from "../types";

export interface SourceLinkProps {
  source: SourceRef;
  /** 按钮上的字（缺省「原文」）。 */
  label?: string;
}

export function SourceLink(props: SourceLinkProps) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SourceWindow | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  if (props.source.path === "") {
    return <span class="caption">没有出处</span>;
  }

  const toggle = async (): Promise<void> => {
    if (open) {
      setOpen(false);
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      const got = await api.getSource({
        path: props.source.path,
        line: props.source.line,
        match: props.source.match,
      });
      setData(got);
      setOpen(true);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setOpen(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span class="source-link">
      <button class="btn" type="button" onClick={toggle} disabled={busy}>
        {open ? "收起" : (props.label ?? "原文")}
      </button>
      {open ? (
        problem !== "" ? (
          <span class="tri-reason">{problem}</span>
        ) : data === null ? null : data.tri !== "computed" ? (
          <span class="tri-reason">{data.reason || "没查成"}</span>
        ) : (
          <pre class="mono pre">
            {data.lines.join("\n")}
            {data.truncated ? "\n…（文件被截断；只回了窗口，不是全文）" : ""}
          </pre>
        )
      ) : null}
    </span>
  );
}
