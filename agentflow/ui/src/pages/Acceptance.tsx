/*
 * 收工门内容级验收（W0：空壳）。
 *
 * 还缺什么：`readers.acceptance(root, ...)`（W1，`reviewaccept.check_review`）与
 * `GET /api/acceptance`。逐条三态要等那批读数；这里的 `not_applicable` 说的是
 * "这一格现在还用不着"，不是"查过了没问题"。
 */
import { Card } from "../components/Card";
import { TriState } from "../components/TriState";

export function Acceptance() {
  return (
    <Card title="验收">
      <TriState
        tri="not_applicable"
        label="5 判据 + 5 辅助"
        reason="这一面要等 W1 的读模型（readers.acceptance）"
      />
    </Card>
  );
}
