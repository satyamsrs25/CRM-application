// Home > Analytics: the chart builder's rules (the same as the server's) and the charts' scales. Run with domain.test.js.
import assert from "node:assert/strict";
import test from "node:test";
import { chartPayload, chartProblem, donutSlices, fitChart, formatValue, labelEvery, niceScale, SERIES, suggestedTitle } from "./analyticsCharts.js";

const METRICS = [
  { key: "leads_created", label: "Leads created", unit: "count", groups: ["none", "stage", "source", "person", "day", "week", "month"] },
  { key: "revenue_won", label: "Revenue won", unit: "money", groups: ["day", "week", "month", "person", "none"] },
  { key: "win_rate", label: "Win rate", unit: "percent", groups: ["none", "person", "week", "month"] },
];
const GROUPS = [{ key: "none", label: "Total only" }, { key: "source", label: "Lead source" }, { key: "month", label: "Month" }];

test("Analytics: the builder allows only charts that can be drawn", () => {
  assert.equal(chartProblem("leads_created", "source", "column", METRICS), "");
  assert.equal(chartProblem("leads_created", "month", "line", METRICS), "");
  assert.equal(chartProblem("leads_created", "none", "number", METRICS), "");
  assert.match(chartProblem("leads_created", "source", "line", METRICS), /Line chart shows a trend/);
  assert.match(chartProblem("leads_created", "source", "number", METRICS), /choose Total only/);
  assert.match(chartProblem("leads_created", "none", "column", METRICS), /Number chart for one total/);
  assert.match(chartProblem("leads_created", "month", "donut", METRICS), /parts of a whole/);
  assert.match(chartProblem("win_rate", "person", "donut", METRICS), /parts of a whole/);
  assert.match(chartProblem("revenue_won", "source", "column", METRICS), /can't be split/);
  // changing the metric keeps what still fits, and fixes the rest
  assert.deepEqual(fitChart({ metric: "revenue_won", group_by: "source", chart_type: "donut" }, METRICS), {
    metric: "revenue_won", group_by: "day", chart_type: "column",
  });
  assert.deepEqual(fitChart({ metric: "win_rate", group_by: "none", chart_type: "number" }, METRICS), {
    metric: "win_rate", group_by: "none", chart_type: "number",
  });
  assert.equal(fitChart({ metric: "leads_created", group_by: "month", chart_type: "line" }, METRICS).chart_type, "line");
  assert.equal(suggestedTitle({ metric: "leads_created", group_by: "source" }, METRICS, GROUPS), "Leads created by lead source");
  assert.equal(suggestedTitle({ metric: "win_rate", group_by: "none" }, METRICS, GROUPS), "Win rate");
  assert.equal(suggestedTitle({ metric: "leads_created", group_by: "stage" }, METRICS, GROUPS), "Leads by stage");
  assert.deepEqual(chartPayload({ title: " A ", metric: "x", group_by: "y", chart_type: "z", period: "30d", start_date: "2026-01-01", end_date: "2026-02-01" }),
    { title: "A", metric: "x", group_by: "y", chart_type: "z", period: "30d", start_date: null, end_date: null, currency: "USD" });
});

test("Analytics: scales, donut slices and values", () => {
  assert.deepEqual(niceScale(7), { top: 8, ticks: [0, 2, 4, 6, 8] });
  assert.deepEqual(niceScale(0).ticks, [0, 1, 2, 3, 4]);
  assert.equal(niceScale(1234).top, 2000);
  assert.equal(niceScale(23).top, 40);
  // colours in fixed order; past 8 slices the rest fold into one "Other"
  const points = Array.from({ length: 10 }, (_, i) => ({ label: `S${i}`, value: 10 - i }));
  const slices = donutSlices(points);
  assert.equal(slices.length, 8);
  assert.deepEqual(slices.slice(0, 7).map((s) => s.color), SERIES.slice(0, 7));
  assert.deepEqual(slices[7], { label: "Other (3)", value: 6, color: "#8c8b86" });
  assert.equal(donutSlices([{ label: "A", value: 0 }, { label: "B", value: 2 }]).length, 1); // empty slices left out
  assert.equal(labelEvery(8), 1);
  assert.equal(labelEvery(30, 8), 4);
  assert.equal(formatValue(null, "percent"), "–");
  assert.equal(formatValue(50, "percent"), "50%");
  assert.equal(formatValue(1500, "count"), "1,500");
});

test("Analytics: click-to-filter and the filter chips", async () => {
  const { pickFilter, isPicked, filterChips, removeFilter, filterQuery, filtersFromQuery } = await import("./analyticsCharts.js");
  const referral = { label: "Referral", value: 3, key: { source: "Referral" } };
  const october = { label: "Oct 2026", value: 4, key: { from_date: "2026-10-01", to_date: "2026-10-31" } };
  let filters = pickFilter({ period: "90d" }, referral);
  assert.deepEqual(filters, { period: "90d", source: "Referral" });
  assert.ok(isPicked(filters, referral));
  assert.deepEqual(pickFilter(filters, referral), { period: "90d" }); // a second click removes it
  filters = pickFilter(filters, october);
  assert.deepEqual(filterChips({ ...filters, owner_id: "4" }, [{ id: 4, full_name: "Ravi Kumar" }]).map((c) => c.text), [
    "Lead source: Referral",
    "Dates: 2026-10-01 – 2026-10-31",
    "Owner: Ravi Kumar",
  ]);
  assert.deepEqual(removeFilter(filters, "from_date"), { period: "90d", source: "Referral" });
  assert.equal(pickFilter(filters, { label: "Total", value: 1, key: null }), filters); // nothing to filter by
  assert.equal(filterQuery({ source: "Referral", owner_id: "", period: "7d" }), "source=Referral&period=7d");
  assert.deepEqual(filtersFromQuery(new URLSearchParams("user=4&source=Website&x=1")), { source: "Website" });
});

test("Analytics: the board's Period (the Dashboard's picker) in the filters", async () => {
  const { withPeriod, filterChips } = await import("./analyticsCharts.js");
  const custom = withPeriod({ source: "Referral" }, "custom", "2026-01-05T09:00", "2026-02-01T18:00");
  assert.deepEqual(custom, { source: "Referral", period: "custom", start_date: "2026-01-05T09:00", end_date: "2026-02-01T18:00" });
  assert.deepEqual(withPeriod(custom, "30d"), { source: "Referral", period: "30d" });
  // the Period has its own dropdown: no chip for it; a clicked stage has one
  assert.deepEqual(filterChips({ ...custom, lead_stage: "Demo" }).map((c) => c.text), ["Lead source: Referral", "Lead stage: Demo"]);
});
