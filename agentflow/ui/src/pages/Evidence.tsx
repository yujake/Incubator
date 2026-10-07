/*
 * 证据链（W0：空壳）。
 *
 * 还缺什么：`readers.evidence_chain(store)`（W1）与 `GET /api/evidence`。
 * 现在不显示任何"0 条" —— 没有 reader 就没有读数，显 0 是把"没查成"折成"查到零"。
 */
import { Card } from "../components/Card";
import { TriState } from "../components/TriState";

export function Evidence() {
  return (
    <Card title="证据链">
      <TriState
        tri="not_applicable"
        label="命题 / 猜想 / 实验 / 审校"
        reason="这一面要等 W1 的读模型（readers.evidence_chain）与 GET /api/evidence"
      />
    </Card>
  );
}
