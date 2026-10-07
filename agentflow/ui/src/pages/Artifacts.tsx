/*
 * 产物台账（W0：空壳）。
 *
 * 还缺什么：`readers.artifact_ledger` / `readers.handoffs` / `readers.run_products`
 * （W1）与 `GET /api/artifacts`。裁定 J2 说六件产物的样本用夹具造并在页面上标明，
 * 那一批（W1）落地之前这里不给任何读数。
 */
import { Card } from "../components/Card";
import { TriState } from "../components/TriState";

export function Artifacts() {
  return (
    <Card title="产物台账">
      <TriState
        tri="not_applicable"
        label="台账 / 交接 / 六件产物"
        reason="这一面要等 W1 的读模型（readers.artifact_ledger / handoffs / run_products）"
      />
    </Card>
  );
}
