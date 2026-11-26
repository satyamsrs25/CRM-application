import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("No Activity (3+ Days): a list view on Leads (server view idle) and Opportunities (idle flag)", () => {
  const list = readFileSync(new URL("./ListView.jsx", import.meta.url), "utf8");
  assert.match(list, /"No Activity \(3\+ Days\)": "idle",/);
  assert.match(list, /\["No Activity \(3\+ Days\)", \(\) => true\],/);
  assert.match(list, /\["No Activity \(3\+ Days\)", \(r\) => !!r\.idle\],/);
});
