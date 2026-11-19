/*
 * 错误块（鲁棒 e）：任何 4xx/5xx 都要有一块读得懂的错误，不许吞成空白。
 *
 * 三样东西一起给，缺一样读的人就得猜：
 * - 状态码 / 传输档（`http 403` / `timeout` / `network`）；
 * - 后端给的档名（`kind`：writes_off / csrf_token / confirm_required …）；
 * - 后端给的"怎么办"（`how_to_fix`，逐字；没有就不编一句）。
 *
 * 为什么单独一个组件：写面有七条端点、四个页面，各写一份错误块就会漂成四种说法；
 * 而"被拒了但什么都没说"是这一路最贵的形态（读的人只会反复按同一个按钮）。
 */
import { ApiError } from "../api";
import type { Tri, WriteResult } from "../types";
import { TriState } from "./TriState";

/** 一次写动作的结局（成功回执或失败异常，归一成同一块要显示的东西）。 */
export interface ErrorFace {
  ok: boolean;
  tri: Tri;
  reason: string;
  code: number;
  /** 传输档（`timeout` / `network` / `http` / `bad-json`）；成功时是空串。 */
  transport: string;
  /** 后端档名（`writes_off` …）；读请求不一定有。 */
  kind: string;
  /** 后端给的"怎么办"。 */
  howToFix: string;
}

/** 把一支 `WriteResult` 收成错误块要的读数。 */
export function faceOfWrite(got: WriteResult): ErrorFace {
  return {
    ok: got.ok,
    tri: got.tri,
    reason: got.reason,
    code: 0,
    transport: "",
    kind: got.kind === undefined ? "" : got.kind,
    howToFix: got.how_to_fix === undefined ? "" : got.how_to_fix,
  };
}

/** 把 `/answer` 那支 `WriteOutcome`（只有 ok/tri/reason）收成同一块读数。 */
export function faceOfOutcome(got: { ok: boolean; tri: Tri; reason: string }): ErrorFace {
  return {
    ok: got.ok,
    tri: got.tri,
    reason: got.reason,
    code: 0,
    transport: "",
    kind: "",
    howToFix: "",
  };
}

/** 把一个异常收成错误块要的读数（`ApiError` 带得出状态码与后端那两栏）。 */
export function faceOfError(exc: unknown): ErrorFace {
  if (exc instanceof ApiError) {
    return {
      ok: false,
      tri: exc.tri,
      reason: exc.reason,
      code: exc.code,
      transport: exc.kind,
      kind: exc.backendKind,
      howToFix: exc.howToFix,
    };
  }
  return {
    ok: false,
    tri: "unreadable",
    reason: String(exc),
    code: 0,
    transport: "unknown",
    kind: "",
    howToFix: "",
  };
}

export interface ErrorBlockProps {
  face: ErrorFace;
  /** 成功那一档的说法（缺省"成了"）；失败时不用。 */
  okText?: string;
}

export function ErrorBlock(props: ErrorBlockProps) {
  const f = props.face;
  if (f.ok) {
    return (
      <div class="readings">
        <span class="mono">{props.okText === undefined ? "成了" : props.okText}</span>
        {f.reason === "" ? null : <span> · {f.reason}</span>}
      </div>
    );
  }
  const codeWord = f.code > 0 ? `HTTP ${f.code}` : (f.transport === "" ? "没成" : f.transport);
  return (
    <div class="card problem">
      <div class="card-head">
        <span class="badge badge-fail">没成</span>
        <span class="mono">{codeWord}</span>
        {f.kind === "" ? null : <span class="badge badge-unknown">{f.kind}</span>}
        {f.transport === "" || f.transport === "http" ? null : (
          <span class="mono">{f.transport}</span>
        )}
      </div>
      <div class="readings">{f.reason}</div>
      {f.howToFix === "" ? null : (
        <div class="readings">
          <span class="mono">怎么办：</span>
          {f.howToFix}
        </div>
      )}
      <TriState tri={f.tri} label="这一笔" reason={f.reason} />
    </div>
  );
}
