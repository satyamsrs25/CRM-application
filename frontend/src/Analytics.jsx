// Home > Analytics (#/analytics), "Performance Overview": each user builds their own board of charts to show their work.
// - A Salesperson's charts count their own records, a Manager's their team's, the Admin's everyone's.
// - The board's owner, their Manager and the Admin see it, live. A Manager / the Admin searches for whose board to open.
// - The board's Period (Past 1 week, Past 1 month or a custom range: the Dashboard's picker) applies to every
//   chart, and a click on any bar, slice or point filters the other charts (a chip shows it; click again or x to
//   remove). Active leads and open opportunities are counted as of now. "Leads by stage" / "Opportunities by stage"
//   (Add Suggested Charts) show every stage in one donut.
// - Edit turns on Add Chart, Edit, Remove, Move and each chart's width.
// - Download: the board as an image (PNG) or as Excel (one sheet per chart); each chart as Excel.
// - Send Report (the board, shown as charts) and Share as Excel (one chart): a dated snapshot with a note goes to the
//   people picked (their Manager and the Admins; the Admin: anyone). They are notified and the link opens it here.
// The server's backend/app/routers/analytics.py does the counting; analyticsCharts.js has the builder's rules.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { Dialog } from "./LeadFiles";
import { can } from "./permissions";
import { EmptyState, Icon } from "./ui";
import {
  anyPicked,
  BLANK_CHART,
  chartPayload,
  chartProblem,
  chartTypesFor,
  DATASETS,
  datasetOf,
  DEFAULT_PERIOD,
  donutSlices,
  filterChips,
  filterQuery,
  filtersFromQuery,
  fitChart,
  fitLabel,
  formatValue,
  isPicked,
  labelEvery,
  niceScale,
  pickFilter,
  removeFilter,
  SINGLE,
  suggestedTitle,
  TIME_GROUPS,
  WIDTHS,
  withPeriod,
  withSplit,
} from "./analyticsCharts";
import { periodRange } from "./homePeriod";
import PeriodPicker from "./PeriodPicker";

// ---------- Home's two tabs ----------

export function HomeTabs({ active, user }) {
  // each tab needs its permission (Manage Access > Permissions > Home); with only one there are no tabs to pick
  const tabs = [
    ["dashboard", "Dashboard", "#/"],
    ["analytics", "Analytics", "#/analytics"],
  ].filter(([key]) => can(user, `home_${key}`));
  if (tabs.length < 2) return null;
  return (
    <nav className="home-tabs" aria-label="Home">
      {tabs.map(([key, label, href]) => (
        <a key={key} href={href} className={active === key ? "on" : ""} aria-current={active === key ? "page" : undefined}>
          {label}
        </a>
      ))}
    </nav>
  );
}

// ---------- the charts: plain SVG with inline styles (so Screenshot can draw them), hover for values, click to filter ----------

const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const INK = "#181818";
const WEAK = "#5c5c5c";
const GRID = "#ececec";
const AXIS = "#c9c9c9";
const W = 560;
const H = 220;
const PAD = { left: 52, right: 12, top: 18, bottom: 34 };
const text = (size, fill = WEAK, weight = 400) => ({ fontFamily: FONT, fontSize: size, fill, fontWeight: weight });

function useTip(width = W, height = H) {
  const [tip, setTip] = useState(null); // { x, y, label, value } in viewBox units
  const show = (x, y, label, value) => setTip({ x, y, label, value });
  const box = tip && (
    <div className="viz-tip" style={{ left: `${(tip.x / width) * 100}%`, top: `${(tip.y / height) * 100}%` }} role="status">
      <span>{tip.label}</span>
      <b>{tip.value}</b>
    </div>
  );
  return { show, hide: () => setTip(null), box };
}

function Axis({ scale, fmt, y, W }) {
  return scale.ticks.map((t) => (
    <g key={t}>
      <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth="1" />
      <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" style={text(11)}>
        {fmt(t)}
      </text>
    </g>
  ));
}

// The x-axis labels. Dates (day / week / month) are spaced out when crowded; names (sources, stages, people) all
// show under their own column, shortened to fit (the full name on hover).
function XLabels({ points, x, W, band, dates }) {
  const every = dates ? labelEvery(points.length, Math.round(W / 70)) : 1;
  return points.map((p, i) => {
    if (i % every) return null;
    const label = p.label.replace(/^Week of /, "");
    const lines = dates || !band ? [label] : fitLabel(label, band);
    // a date label at either end of the axis is anchored inwards, so it isn't cut off
    const anchor = dates ? (x(i) > W - 40 ? "end" : x(i) < PAD.left + 20 ? "start" : "middle") : "middle";
    return (
      <text key={i} x={x(i)} y={H - PAD.bottom + 18} textAnchor={anchor} style={text(11)}>
        {lines.join(" ") !== label && <title>{label}</title>}
        {lines.map((line, n) => (
          <tspan key={n} x={x(i)} dy={n ? 13 : 0}>
            {line}
          </tspan>
        ))}
      </text>
    );
  });
}

const clickable = (onPick, p) => (onPick && p.key ? { onClick: () => onPick(p), style: { cursor: "pointer" } } : {});

function ColumnChart({ chart, fmt, onPick, filters, w: W = 560 }) {
  const { show, hide, box } = useTip(W);
  const points = chart.points;
  const scale = niceScale(Math.max(...points.map((p) => p.value || 0), 0));
  const inner = W - PAD.left - PAD.right;
  const band = inner / Math.max(points.length, 1);
  const barW = Math.max(3, Math.min(36, band - 2)); // at least a 2px gap between bars
  const x = (i) => PAD.left + band * i + band / 2;
  const y = (v) => PAD.top + (H - PAD.top - PAD.bottom) * (1 - v / scale.top);
  const base = y(0);
  const dim = anyPicked(filters, points);
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title}: column chart`}>
        <Axis scale={scale} fmt={fmt} y={y} W={W} />
        {points.map((p, i) => {
          if (!p.value) return null;
          const top = Math.min(y(p.value), base - 3); // a small value next to large ones still shows (at least 3px)
          const r = Math.min(4, barW / 2, base - top);
          const left = x(i) - barW / 2;
          // the data end rounded (4px), anchored square to the baseline
          const d = `M${left},${base} V${top + r} Q${left},${top} ${left + r},${top} H${left + barW - r} Q${left + barW},${top} ${left + barW},${top + r} V${base} Z`;
          return <path key={i} d={d} fill={SINGLE} opacity={dim && !isPicked(filters, p) ? 0.3 : 1} />;
        })}
        {points.map((p, i) => (
          // hit area: the whole band, taller than the bar
          <rect key={`hit${i}`} x={x(i) - band / 2} y={PAD.top} width={band} height={base - PAD.top} fill="transparent"
            onMouseEnter={() => show(x(i), y(p.value || 0), p.label, fmt(p.value))} onMouseLeave={hide} {...clickable(onPick, p)} />
        ))}
        <line x1={PAD.left} x2={W - PAD.right} y1={base} y2={base} stroke={AXIS} strokeWidth="1" />
        <XLabels points={points} x={x} W={W} band={band} dates={TIME_GROUPS.includes(chart.group_shown || chart.group_by)} />
      </svg>
      {box}
    </div>
  );
}

function LineChart({ chart, fmt, onPick, filters, w: W = 560 }) {
  const { show, hide, box } = useTip(W);
  const [hover, setHover] = useState(null);
  const points = chart.points;
  const scale = niceScale(Math.max(...points.map((p) => p.value || 0), 0));
  const inner = W - PAD.left - PAD.right;
  const step = inner / Math.max(points.length - 1, 1);
  const x = (i) => (points.length === 1 ? PAD.left + inner / 2 : PAD.left + step * i);
  const y = (v) => PAD.top + (H - PAD.top - PAD.bottom) * (1 - v / scale.top);
  const labelled = points.length <= 12; // values on the points while they fit (selective, never crowded)
  // a gap (no value, e.g. no deals closed that week for a win rate) breaks the line
  const segments = [];
  let current = [];
  points.forEach((p, i) => {
    if (p.value === null || p.value === undefined) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push([x(i), y(p.value)]);
  });
  if (current.length) segments.push(current);
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.title}: line chart`} onMouseLeave={() => (setHover(null), hide())}>
        <Axis scale={scale} fmt={fmt} y={y} W={W} />
        <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke={AXIS} strokeWidth="1" />
        {segments.map((s, i) =>
          s.length > 1 ? (
            <polyline key={i} points={s.map((p) => p.join(",")).join(" ")} fill="none" stroke={SINGLE} strokeWidth="2" strokeLinejoin="round" />
          ) : (
            <circle key={i} cx={s[0][0]} cy={s[0][1]} r="4" fill={SINGLE} />
          ),
        )}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={y(0)} stroke={AXIS} strokeDasharray="3 3" />}
        {points.map((p, i) =>
          p.value === null || p.value === undefined ? null : (
            <g key={`m${i}`}>
              {(points.length <= 24 || hover === i || isPicked(filters, p)) && (
                <circle cx={x(i)} cy={y(p.value)} r={hover === i || isPicked(filters, p) ? 5 : 3.5} fill={SINGLE} stroke="#fff" strokeWidth={hover === i ? 2 : 1} />
              )}
              {labelled && p.value !== 0 && (
                <text x={x(i)} y={y(p.value) - 9} style={text(11, INK, 600)}
                  textAnchor={points.length > 1 && i === points.length - 1 ? "end" : points.length > 1 && i === 0 ? "start" : "middle"}>
                  {fmt(p.value)}
                </text>
              )}
            </g>
          ),
        )}
        {points.map((p, i) => (
          <rect key={i} x={x(i) - step / 2} y={PAD.top} width={Math.max(step, 8)} height={y(0) - PAD.top} fill="transparent"
            onMouseEnter={() => (setHover(i), show(x(i), y(p.value || 0), p.label, fmt(p.value)))} {...clickable(onPick, p)} />
        ))}
        <XLabels points={points} x={x} W={W} dates />
      </svg>
      {box}
    </div>
  );
}

function BarChart({ chart, fmt, onPick, filters, w: W = 560 }) {
  const rows = chart.points.slice(0, 12);
  const max = Math.max(...rows.map((p) => p.value || 0), 0);
  const rowH = 28;
  const height = rows.length * rowH + 8;
  const labelW = Math.min(150, W * 0.32);
  const valueW = Math.min(90, W * 0.24);
  const track = W - labelW - valueW - 16;
  const dim = anyPicked(filters, rows);
  const { show, hide, box } = useTip(W, height);
  return (
    <div className="viz">
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${chart.title}: bar chart`}>
        {rows.map((p, i) => {
          const y = 4 + i * rowH;
          const width = max ? Math.max(((p.value || 0) / max) * track, p.value ? 3 : 0) : 0;
          const label = p.label.length > 22 ? `${p.label.slice(0, 21)}…` : p.label;
          return (
            <g key={p.label} onMouseEnter={() => show(labelW + width / 2, y, p.label, fmt(p.value))} onMouseLeave={hide} {...clickable(onPick, p)}>
              <rect x="0" y={y} width={W} height={rowH} fill="transparent" />
              <text x="0" y={y + 18} style={text(12, INK)}>
                {label}
              </text>
              <rect x={labelW} y={y + 8} width={track} height="10" rx="5" fill="#f1f1f1" />
              {width > 0 && <rect x={labelW} y={y + 8} width={width} height="10" rx="5" fill={SINGLE} opacity={dim && !isPicked(filters, p) ? 0.3 : 1} />}
              <text x={W} y={y + 18} textAnchor="end" style={text(12, INK, 600)}>
                {fmt(p.value)}
              </text>
            </g>
          );
        })}
      </svg>
      {box}
      {chart.points.length > rows.length && <small className="muted">Top 12 of {chart.points.length}: the table shows all.</small>}
    </div>
  );
}

function DonutChart({ chart, fmt, onPick, filters, w: W = 560 }) {
  const slices = donutSlices(chart.points);
  const total = slices.reduce((s, p) => s + p.value, 0);
  const height = Math.max(200, 30 + slices.length * 22);
  const { show, hide, box } = useTip(W, height);
  const R = 70;
  const r = 44;
  const cx = 110;
  const cy = height / 2;
  const dim = anyPicked(filters, slices);
  let angle = -Math.PI / 2;
  const arc = (from, to) => {
    const large = to - from > Math.PI ? 1 : 0;
    const p = (a, rad) => `${cx + rad * Math.cos(a)},${cy + rad * Math.sin(a)}`;
    return `M${p(from, R)} A${R},${R} 0 ${large} 1 ${p(to, R)} L${p(to, r)} A${r},${r} 0 ${large} 0 ${p(from, r)} Z`;
  };
  const pct = (v) => `${Math.round((v / total) * 100)}%`;
  return (
    <div className="viz viz-donut">
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${chart.title}: donut chart`}>
        {slices.length === 1 && (
          <circle cx={cx} cy={cy} r={(R + r) / 2} fill="none" stroke={slices[0].color} strokeWidth={R - r}
            onMouseEnter={() => show(cx, cy - R, slices[0].label, `${fmt(total)} (100%)`)} onMouseLeave={hide} {...clickable(onPick, slices[0])} />
        )}
        {slices.length > 1 &&
          slices.map((s) => {
            const from = angle;
            angle += (s.value / total) * Math.PI * 2;
            const mid = (from + angle) / 2;
            return (
              <path key={s.label} d={arc(from, angle)} fill={s.color} stroke="#fff" strokeWidth="2" opacity={dim && !isPicked(filters, s) ? 0.3 : 1}
                onMouseEnter={() => show(cx + R * Math.cos(mid), cy + R * Math.sin(mid), s.label, `${fmt(s.value)} (${pct(s.value)})`)}
                onMouseLeave={hide} {...clickable(onPick, s)} />
            );
          })}
        <text x={cx} y={cy - 2} textAnchor="middle" style={text(18, INK, 700)}>
          {fmt(total)}
        </text>
        <text x={cx} y={cy + 16} textAnchor="middle" style={text(11)}>
          Total
        </text>
        {/* the legend names every slice with its value: identity is never colour alone */}
        {slices.map((s, i) => (
          <g key={s.label} transform={`translate(230, ${cy - (slices.length * 22) / 2 + 15 + i * 22})`} {...clickable(onPick, s)}>
            <rect width="10" height="10" rx="2" y="-9" fill={s.color} />
            <text x="16" style={text(12, INK, isPicked(filters, s) ? 700 : 400)}>
              {s.label.length > 26 ? `${s.label.slice(0, 25)}…` : s.label}
            </text>
            <text x={W - 240} textAnchor="end" style={text(12)}>
              {fmt(s.value)} • {pct(s.value)}
            </text>
          </g>
        ))}
      </svg>
      {box}
    </div>
  );
}

function NumberTile({ chart, fmt }) {
  const empty = chart.total === null || chart.total === undefined;
  return (
    <div className="viz">
      <svg viewBox="0 0 280 96" className="viz-num" role="img" aria-label={`${chart.title}: ${empty ? "no value" : fmt(chart.total)}`}>
        {empty ? (
          <text x="0" y="52" style={text(13)}>
            {chart.unit === "percent" ? "No deals won or lost in this period yet." : chart.period_label === "As of now" ? "None right now." : "Nothing in this period yet."}
          </text>
        ) : (
          <>
            <text x="0" y="58" style={text(42, INK, 700)}>
              {fmt(chart.total)}
            </text>
            <text x="0" y="84" style={text(13)}>
              {chart.metric_label}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}

function Table({ chart, fmt, onPick, filters }) {
  return (
    <div className="table-scroll viz-table">
      <table className="sf-table">
        <thead>
          <tr>
            <th>{chart.group_shown === "none" ? "" : chart.group_label || "Group"}</th>
            <th className="num">{chart.metric_label}</th>
          </tr>
        </thead>
        <tbody>
          {chart.points.map((p) => (
            <tr key={p.label} className={isPicked(filters, p) ? "picked" : ""}>
              <td>{onPick && p.key ? <button className="link-button" onClick={() => onPick(p)}>{p.label}</button> : p.label}</td>
              <td className="num">{fmt(p.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DRAW_WIDTH = { quarter: 340, half: 560, full: 1160 }; // the drawing's width for the card's width: text stays the same size

export function ChartView({ chart, table = false, onPick, filters = {} }) {
  const fmt = (v) => formatValue(v, chart.unit, chart.currency);
  const empty = chart.chart_type !== "number" && !chart.points.some((p) => p.value);
  if (table) return <Table chart={chart} fmt={fmt} onPick={onPick} filters={filters} />;
  const nothing = chart.period_label === "As of now" ? "None right now." : "Nothing in this period yet.";
  if (empty)
    return (
      <div className="viz">
        <svg viewBox="0 0 280 60" className="viz-num" role="img" aria-label={nothing}>
          <text x="140" y="34" textAnchor="middle" style={text(12)}>
            {nothing}
          </text>
        </svg>
      </div>
    );
  const View = { column: ColumnChart, line: LineChart, bar: BarChart, donut: DonutChart, number: NumberTile }[chart.chart_type] || ColumnChart;
  const width = chart.width || (chart.chart_type === "number" ? "quarter" : "half");
  const w = chart.chart_type === "donut" ? 560 : DRAW_WIDTH[width] || 560; // a donut's legend needs its room
  return <View chart={chart} fmt={fmt} onPick={onPick} filters={filters} w={w} />;
}

function ChartCard({ chart, editing, onEdit, onMove, onRemove, first, last, groups, onPick, filters, onExcel, onShare }) {
  const [table, setTable] = useState(false);
  const group = groups.find((g) => g.key === chart.group_shown);
  const shown = { ...chart, group_label: group?.label };
  const width = chart.width || (chart.chart_type === "number" ? "quarter" : "half");
  return (
    <section className={`card analytics-card w-${width}${editing ? " editing" : ""}`} data-title={chart.title}>
      <header className="card-header">
        <div className="analytics-card-title">
          <h2>{chart.title}</h2>
          <small>
            {chart.period_label}
            {chart.unit !== "percent" && chart.chart_type !== "number" && ` • Total ${formatValue(chart.total, chart.unit, chart.currency)}`}
            {chart.group_shown !== chart.group_by && " • by week (a long period)"}
          </small>
          {chart.not_filtered_by?.length > 0 && <small className="analytics-unfiltered">Not filtered by {chart.not_filtered_by.join(", ").toLowerCase()}</small>}
        </div>
        <div className="card-actions">
          {chart.chart_type !== "number" && (
            <button className="icon-btn" title={table ? "Show chart" : "Show as table"} aria-label={table ? "Show chart" : "Show as table"}
              aria-pressed={table} onClick={() => setTable(!table)}>
              <Icon name={table ? "chart" : "list"} size={14} />
            </button>
          )}
          {!editing && onExcel && (
            <button className="icon-btn" title="Download Excel" aria-label={`Download ${chart.title} as Excel`} onClick={onExcel}>
              <Icon name="download" size={14} />
            </button>
          )}
          {!editing && onShare && (
            <button className="icon-btn" title="Share as Excel" aria-label={`Share ${chart.title} as Excel`} onClick={onShare}>
              <Icon name="share" size={14} />
            </button>
          )}
          {editing && (
            <>
              <button className="icon-btn" title="Move earlier" aria-label="Move earlier" disabled={first} onClick={() => onMove(-1)}>
                <Icon name="left" size={14} />
              </button>
              <button className="icon-btn" title="Move later" aria-label="Move later" disabled={last} onClick={() => onMove(1)}>
                <Icon name="right" size={14} />
              </button>
              <button className="icon-btn" title="Edit chart" aria-label="Edit chart" onClick={onEdit}>
                <Icon name="edit" size={14} />
              </button>
              <button className="icon-btn" title="Remove chart" aria-label={`Remove ${chart.title}`} onClick={onRemove}>
                <Icon name="trash" size={14} />
              </button>
            </>
          )}
        </div>
      </header>
      <div className="card-body">
        <ChartView chart={shown} table={table} onPick={onPick} filters={filters} />
      </div>
    </section>
  );
}

// ---------- Add / Edit Chart ----------

function ChartFields({ options, chart, set, setChart, title, setTitle }) {
  const { metrics, groups, chart_types: types, currencies } = options;
  const metric = metrics.find((m) => m.key === chart.metric);
  const typeChoices = chartTypesFor(chart.metric, chart.group_by, metrics, types);
  return (
    <>
      <label className="field">
        <span>Show</span>
        <select value={chart.metric} onChange={(e) => set({ metric: e.target.value })}>
          {DATASETS.map(([key, label]) => {
            const inSet = metrics.filter((m) => datasetOf(m.key) === key);
            return inSet.length ? (
              <optgroup key={key} label={label}>
                {inSet.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </optgroup>
            ) : null;
          })}
        </select>
      </label>
      <label className="field">
        <span>Split by</span>
        <select value={chart.group_by} onChange={(e) => set(withSplit(chart, e.target.value))}>
          {groups
            .filter((g) => metric?.groups.includes(g.key))
            .map((g) => (
              <option key={g.key} value={g.key}>
                {g.label}
              </option>
            ))}
        </select>
      </label>
      <fieldset className="field analytics-types">
        <legend>Chart type</legend>
        <div role="radiogroup" aria-label="Chart type">
          {typeChoices.map((t) => (
            <button type="button" key={t.key} role="radio" aria-checked={chart.chart_type === t.key}
              className={chart.chart_type === t.key ? "on" : ""} disabled={Boolean(t.problem)} title={t.problem || t.label}
              onClick={() => setChart((c) => ({ ...c, chart_type: t.key }))}>
              {t.label}
            </button>
          ))}
        </div>
      </fieldset>
      {metric?.unit === "money" && (
        <label className="field">
          <span>Currency</span>
          <select value={chart.currency} onChange={(e) => set({ currency: e.target.value })}>
            {currencies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <small className="field-hint">Only deals in this currency are added up.</small>
        </label>
      )}
      <label className="field">
        <span>Width</span>
        <select value={chart.width || (chart.chart_type === "number" ? "quarter" : "half")} onChange={(e) => setChart((c) => ({ ...c, width: e.target.value }))}>
          {WIDTHS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>
          <abbr title="required">*</abbr> Title
        </span>
        <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
      </label>
    </>
  );
}

function usePreview(payload, enabled, filters = {}) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const key = JSON.stringify([payload, filters]);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    const timer = setTimeout(() => {
      api
        .previewAnalyticsChart({ ...payload, filters })
        .then((value) => live && (setPreview(value), setError("")))
        .catch((err) => live && setError(err.message));
    }, 300);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [key, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return { preview, error };
}

function ChartBuilder({ options, chart: start, period, onClose, onSaved }) {
  const { metrics, groups } = options;
  const [chart, setChart] = useState(() => (start ? { ...start, start_date: start.start_date || "", end_date: start.end_date || "" } : { ...BLANK_CHART }));
  const [typed, setTyped] = useState(start ? start.title : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const title = typed ?? suggestedTitle(chart, metrics, groups);
  const problem = chartProblem(chart.metric, chart.group_by, chart.chart_type, metrics);
  const payload = { ...chartPayload({ ...chart, title: title || "Chart" }), width: chart.width || null };
  const { preview, error: previewError } = usePreview(payload, !problem, period); // in the board's Period
  const set = (changes) => setChart((c) => fitChart({ ...c, ...changes }, metrics));

  const save = async (e) => {
    e.preventDefault();
    if (!title.trim()) return setError("Give the chart a title.");
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveAnalyticsChart({ ...payload, title: title.trim() }, start?.id));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={start ? "Edit Chart" : "Add Chart"}
      onClose={onClose}
      busy={busy}
      wide
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" form="analytics-chart" disabled={busy || Boolean(problem)} aria-busy={busy}>
            {busy ? "Saving…" : start ? "Save Chart" : "Add Chart"}
          </button>
        </>
      }
    >
      <form id="analytics-chart" className="analytics-builder" onSubmit={save}>
        <div className="analytics-builder-fields">
          <ChartFields options={options} chart={chart} set={set} setChart={setChart} title={title} setTitle={setTyped} />
        </div>
        <div className="analytics-preview" aria-live="polite">
          <h3>Preview</h3>
          {problem ? (
            <p className="form-error">{problem}</p>
          ) : previewError ? (
            <p className="form-error">{previewError}</p>
          ) : preview ? (
            <>
              <p className="muted">
                {preview.period_label}
                {preview.unit !== "percent" && ` • Total ${formatValue(preview.total, preview.unit, preview.currency)}`}
              </p>
              <ChartView chart={{ ...preview, title, chart_type: chart.chart_type }} />
            </>
          ) : (
            <p className="muted">Loading…</p>
          )}
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// ---------- whose board, and what was clicked ----------

// Whose board: a search box over everyone the user can see (a Manager: their team; the Admin: everyone)
function BoardPicker({ people, whose, onChoose }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const name = (p) => (p.me ? "My board" : p.full_name);
  const current = people.find((p) => p.id === whose);
  const words = search.trim().toLowerCase();
  const shown = people.filter((p) => `${p.full_name} ${p.role} ${p.me ? "my board" : ""}`.toLowerCase().includes(words));
  const choose = (p) => {
    onChoose(p.id);
    setOpen(false);
    setSearch("");
  };
  return (
    <div className="analytics-board-picker" ref={box}>
      <button className="home-period-row analytics-board-button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}
        title="Choose whose board to see">
        <Icon name="user" size={16} />
        <span>{current ? name(current) : "My board"}</span>
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="analytics-board-menu" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <input
            type="search"
            autoFocus
            placeholder="Search by name or role"
            aria-label="Search people"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && shown[0] && choose(shown[0])}
          />
          <ul role="listbox" aria-label="Boards">
            {shown.map((p) => (
              <li key={p.id}>
                <button role="option" aria-selected={p.id === whose} className={p.id === whose ? "on" : ""} onClick={() => choose(p)}>
                  <span>{name(p)}</span>
                  <small>{p.role}</small>
                </button>
              </li>
            ))}
          </ul>
          {!shown.length && <p className="muted">No one matches “{search.trim()}”.</p>}
        </div>
      )}
    </div>
  );
}

// What was clicked on a chart: a chip per filter (x removes it). Nothing shows until something is clicked.
function ClickedFilters({ filters, setFilters, people }) {
  const chips = filterChips(filters, people);
  if (!chips.length) return <span />;
  return (
    <div className="analytics-chips" aria-live="polite">
      {chips.map((c) => (
        <span key={c.key} className="analytics-chip">
          {c.text}
          <button aria-label={`Remove filter ${c.text}`} title="Remove filter" onClick={() => setFilters(removeFilter(filters, c.key))}>
            <Icon name="close" size={12} />
          </button>
        </span>
      ))}
      <button className="link-button" onClick={() => setFilters(withPeriod({}, filters.period || DEFAULT_PERIOD, filters.start_date, filters.end_date))}>
        Clear
      </button>
    </div>
  );
}

// ---------- Download image: the board as a PNG (the charts are SVG, drawn onto a canvas) ----------

function svgImage(svg) {
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const box = svg.getBoundingClientRect();
  clone.setAttribute("width", box.width);
  clone.setAttribute("height", box.height);
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(clone))}`;
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

async function boardPng(grid, heading) {
  const scale = 2;
  const outer = grid.getBoundingClientRect();
  const top = 56;
  const canvas = document.createElement("canvas");
  canvas.width = (outer.width + 32) * scale;
  canvas.height = (outer.height + top + 16) * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#f3f3f3";
  ctx.fillRect(0, 0, outer.width + 32, outer.height + top + 16);
  ctx.fillStyle = INK;
  ctx.font = `700 18px ${FONT}`;
  ctx.fillText(heading.title, 16, 28);
  ctx.fillStyle = WEAK;
  ctx.font = `12px ${FONT}`;
  ctx.fillText(heading.subtitle, 16, 46);
  for (const card of grid.querySelectorAll(".analytics-card")) {
    const box = card.getBoundingClientRect();
    const x = box.left - outer.left + 16;
    const y = box.top - outer.top + top;
    ctx.fillStyle = "#fff";
    roundRect(ctx, x, y, box.width, box.height, 16);
    ctx.fill();
    ctx.fillStyle = INK;
    ctx.font = `700 15px ${FONT}`;
    ctx.fillText(card.dataset.title || "", x + 16, y + 28);
    ctx.fillStyle = WEAK;
    ctx.font = `12px ${FONT}`;
    ctx.fillText(card.querySelector(".analytics-card-title small")?.textContent || "", x + 16, y + 46);
    const svg = card.querySelector(".card-body svg");
    if (svg) {
      const s = svg.getBoundingClientRect();
      ctx.drawImage(await svgImage(svg), s.left - outer.left + 16, s.top - outer.top + top, s.width, s.height);
    } else {
      // a chart shown as a table: its rows as text
      let rowY = y + 76;
      ctx.fillStyle = INK;
      for (const row of card.querySelectorAll("tbody tr")) {
        const [label, value] = [...row.querySelectorAll("td")].map((td) => td.textContent);
        ctx.textAlign = "left";
        ctx.fillText(label, x + 16, rowY);
        ctx.textAlign = "right";
        ctx.fillText(value, x + box.width - 16, rowY);
        rowY += 20;
        if (rowY > y + box.height - 10) break;
      }
      ctx.textAlign = "left";
    }
  }
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- Send Report (the board) / Share as Excel (one chart) ----------

function SendDialog({ board, chart, filters, onClose, onSent }) {
  const today = new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const [title, setTitle] = useState(chart ? chart.title : `${board.user.full_name}'s report, ${today}`);
  const [note, setNote] = useState("");
  const [people, setPeople] = useState(null);
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api
      .analyticsRecipients()
      .then((rows) => {
        setPeople(rows);
        setPicked(rows.filter((r) => r.picked).map((r) => r.id));
      })
      .catch((err) => setError(err.message));
  }, []);
  const toggle = (id) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const send = async (e) => {
    e.preventDefault();
    if (!picked.length) return setError("Choose who to send it to.");
    setBusy(true);
    setError("");
    try {
      const period = { period: filters.period, start_date: filters.start_date, end_date: filters.end_date };
      const sent = await api.sendAnalyticsReport({ title: title.trim(), note: note.trim(), recipient_ids: picked, chart_id: chart?.id ?? null, filters: period });
      onSent(sent);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={chart ? "Share as Excel" : "Send Report"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" form="analytics-send" disabled={busy || !people} aria-busy={busy}>
            {busy ? "Sending…" : chart ? "Share" : "Send Report"}
          </button>
        </>
      }
    >
      <form id="analytics-send" className="transfer-form" onSubmit={send}>
        <p className="muted">
          {chart
            ? `"${chart.title}" (${chart.period_label}) goes as an Excel sheet.`
            : `Your ${board.charts.length} chart${board.charts.length === 1 ? "" : "s"} as they are now go as a report.`}{" "}
          Each person is notified and the link opens it.
        </p>
        <fieldset className="field analytics-recipients">
          <legend>Send to</legend>
          {!people && !error && <p className="muted">Loading…</p>}
          {people?.map((p) => (
            <label key={p.id}>
              <input type="checkbox" checked={picked.includes(p.id)} onChange={() => toggle(p.id)} />
              <span>{p.full_name}</span>
              <small className="muted">{p.role}</small>
            </label>
          ))}
        </fieldset>
        <label className="field">
          <span>Title</span>
          <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span>Note</span>
          <textarea rows={4} maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Highlights, wins, what you need help with…" />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

function ReportDialog({ id, groups, onClose, onChanged }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const grid = useRef(null);
  useEffect(() => {
    api.analyticsReport(id).then(setReport).catch((err) => setError(err.message));
  }, [id]);
  const excel = () => api.analyticsReportExcel(id).catch((err) => setError(err.message));
  const image = async () => {
    try {
      const blob = await boardPng(grid.current, { title: report.title, subtitle: `From ${report.user_name} • ${dateTime(report.created_at)}` });
      download(blob, `${report.title.replace(/\W+/g, "-").toLowerCase()}.png`);
    } catch {
      setError("The image couldn't be made in this browser.");
    }
  };
  const review = async () => {
    setBusy(true);
    setError("");
    try {
      const saved = await api.reviewAnalyticsReport(id, comment.trim());
      setReport(saved);
      onChanged?.();
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  return (
    <Dialog
      title={report?.title || "Report"}
      onClose={onClose}
      busy={busy}
      wide
      footer={
        <>
          {report && (
            <button className="sf-button" onClick={excel}>
              <Icon name="download" size={14} /> Excel
            </button>
          )}
          {report?.kind === "board" && (
            <button className="sf-button" onClick={image}>
              <Icon name="image" size={14} /> Image
            </button>
          )}
          {report?.can_review && (
            <button className="sf-button brand" onClick={review} disabled={busy} aria-busy={busy}>
              {busy ? "Saving…" : "Mark Reviewed"}
            </button>
          )}
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Close
          </button>
        </>
      }
    >
      {error && <p className="form-error">{error}</p>}
      {!report && !error && <p className="muted">Loading…</p>}
      {report && (
        <div className="analytics-report">
          <p className="muted">
            From <b>{report.user_name}</b> ({report.user_role}) • Sent {dateTime(report.created_at)} to {report.sent_to}
            {report.charts[0]?.scope && ` • ${report.charts[0].scope}`}
          </p>
          {report.note && <blockquote className="analytics-note">{report.note}</blockquote>}
          {report.reviewed_at ? (
            <p className="analytics-reviewed">
              <Icon name="check" size={14} /> Reviewed by {report.reviewed_by_name}, {dateTime(report.reviewed_at)}
              {report.review_comment && <>: “{report.review_comment}”</>}
            </p>
          ) : (
            report.can_review && (
              <label className="field">
                <span>Comment (optional)</span>
                <textarea rows={2} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Feedback for the author" />
              </label>
            )
          )}
          <p className="muted small">The numbers as they were when it was sent.</p>
          <div className="analytics-grid" ref={grid}>
            {report.charts.map((c) => (
              <ChartCard key={c.id} chart={c} groups={groups} editing={false} />
            ))}
          </div>
        </div>
      )}
    </Dialog>
  );
}

function ReportList({ rows, onOpen, received }) {
  if (!rows.length)
    return <p className="table-empty">{received ? "Nothing has been sent to you yet." : "You haven't sent anything yet."}</p>;
  return (
    <div className="table-scroll">
      <table className="sf-table">
        <thead>
          <tr>
            <th>Report</th>
            {received && <th>From</th>}
            {!received && <th>To</th>}
            <th>Sent</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>
                <button className="link-button" onClick={() => onOpen(r.id)}>
                  {r.title}
                </button>
                <small className="analytics-sub">
                  {r.kind === "chart" ? "Chart (Excel)" : `Report • ${r.chart_count} chart${r.chart_count === 1 ? "" : "s"}`}
                  {r.note ? ` • ${r.note.slice(0, 80)}${r.note.length > 80 ? "…" : ""}` : ""}
                </small>
              </td>
              {received && (
                <td>
                  {r.user_name}
                  <small className="analytics-sub">{r.user_role}</small>
                </td>
              )}
              {!received && <td>{r.sent_to}</td>}
              <td className="nowrap">{dateTime(r.created_at)}</td>
              <td>
                {r.reviewed_at ? (
                  <span className="pill pill-ok" title={r.review_comment || ""}>Reviewed by {r.reviewed_by_name}</span>
                ) : (
                  <span className="pill pill-warn">Waiting for review</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- the page ----------

// Home > Analytics needs its permission (Manage Access > Permissions > Home > Analytics)
export default function AnalyticsPage({ user, query = "" }) {
  if (!can(user, "home_analytics"))
    return (
      <div className="page seller-home analytics-page">
        <HomeTabs active="analytics" user={user} />
        <EmptyState text="Analytics isn't turned on for your role. Your Admin can turn it on in Manage Access > Permissions." />
      </div>
    );
  return <AnalyticsBoard user={user} query={query} />;
}

function AnalyticsBoard({ user, query }) {
  const params = useMemo(() => new URLSearchParams(query), [query]);
  const [options, setOptions] = useState(null);
  const [people, setPeople] = useState([]);
  const [whose, setWhose] = useState(() => Number(params.get("user")) || user.id);
  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState(() => ({ period: DEFAULT_PERIOD, ...filtersFromQuery(params) }));
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [building, setBuilding] = useState(null); // null | "new" | a chart
  const [sending, setSending] = useState(null); // null | "board" | a chart (Share as Excel)
  const [menu, setMenu] = useState(false); // the Download menu
  const [openReport, setOpenReport] = useState(() => Number(params.get("report")) || null);
  // Reports go to Managers and Admins: a Salesperson only sends them
  const receives = user.role !== "Salesperson";
  const [box, setBox] = useState(receives ? "received" : "sent");
  const [reports, setReports] = useState(null);
  const [flash, setFlash] = useState("");
  const loadId = useRef(0);
  const gridRef = useRef(null);
  const menuRef = useRef(null);

  const loadBoard = (id = whose, f = filters) => {
    const ticket = ++loadId.current;
    setError("");
    setLoading(true);
    return api
      .analyticsBoard(id, filterQuery(f))
      .then((value) => ticket === loadId.current && setBoard(value))
      .catch((err) => ticket === loadId.current && setError(err.message))
      .finally(() => ticket === loadId.current && setLoading(false));
  };
  const loadReports = () => api.analyticsReports(box).then(setReports).catch((err) => setError(err.message));
  useEffect(() => {
    api.analyticsOptions().then(setOptions).catch((err) => setError(err.message));
    api.analyticsPeople().then(setPeople).catch(() => {});
  }, []);
  useEffect(() => {
    loadBoard(whose, filters);
  }, [whose, JSON.stringify(filters)]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setReports(null);
    loadReports();
  }, [box]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (Number(params.get("report"))) setOpenReport(Number(params.get("report")));
    if (Number(params.get("user"))) setWhose(Number(params.get("user")));
  }, [params]);
  useEffect(() => {
    if (!menu) return undefined;
    const close = (e) => menuRef.current && !menuRef.current.contains(e.target) && setMenu(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  const say = (message) => {
    setFlash(message);
    setTimeout(() => setFlash(""), 4000);
  };
  const choosePerson = (id) => {
    if (id === whose) return;
    setEditing(false);
    // another board counts other people: a clicked person doesn't carry over
    const { owner_id: _drop, ...rest } = filters; // eslint-disable-line no-unused-vars
    setFilters(rest);
    setWhose(id);
  };
  const move = async (index, by) => {
    const ids = board.charts.map((c) => c.id);
    const [item] = ids.splice(index, 1);
    ids.splice(index + by, 0, item);
    setBoard({ ...board, charts: ids.map((id) => board.charts.find((c) => c.id === id)) });
    try {
      await api.orderAnalyticsCharts(ids);
    } catch (err) {
      setError(err.message);
      loadBoard();
    }
  };
  const remove = async (chart) => {
    try {
      await api.removeAnalyticsChart(chart.id);
      setBoard({ ...board, charts: board.charts.filter((c) => c.id !== chart.id) });
    } catch (err) {
      setError(err.message);
    }
  };
  const suggested = async () => {
    try {
      await api.addSuggestedAnalyticsCharts();
      loadBoard();
    } catch (err) {
      setError(err.message);
    }
  };
  const image = async () => {
    setMenu(false);
    if (!gridRef.current || !board) return;
    try {
      const chips = filterChips(filters, board.people).map((c) => c.text);
      const blob = await boardPng(gridRef.current, {
        title: `${board.user.full_name} • Performance Overview`,
        subtitle: [board.scope, board.charts.find((c) => !["As of now"].includes(c.period_label))?.period_label, ...chips, new Date().toLocaleString()]
          .filter(Boolean)
          .join(" • "),
      });
      download(blob, `analytics-${board.user.full_name.replace(/\W+/g, "-").toLowerCase()}-${new Date().toISOString().slice(0, 10)}.png`);
      say("Image downloaded.");
    } catch {
      setError("The image couldn't be made in this browser.");
    }
  };
  const excel = (chart = null) => {
    setMenu(false);
    api
      .analyticsBoardExcel(board.user.id, filterQuery(filters), chart?.id)
      .then(() => say("Excel downloaded."))
      .catch((err) => setError(err.message));
  };

  // the Dashboard's picker: { preset, from, to } (a custom range's local date-times)
  const period = { preset: filters.period || DEFAULT_PERIOD, from: filters.start_date, to: filters.end_date };
  const own = board?.can_edit;
  const max = options?.max_charts || 12;
  const hasCharts = board?.charts.length > 0;
  return (
    <div className="page seller-home analytics-page">
      <HomeTabs active="analytics" user={user} />
      <div className="home-title">
        <div className="home-greeting">
          <h1>Performance Overview</h1>
          <p>Your latest metrics are ready.</p>
        </div>
        <div className="home-controls">
          {people.length > 1 && <BoardPicker people={people} whose={whose} onChoose={choosePerson} />}
          <PeriodPicker
            id="analytics-period"
            period={period}
            shown={periodRange(period)}
            setPeriod={(p) => setFilters(withPeriod(filters, p.preset, p.from, p.to))}
          />
        </div>
      </div>

      {flash && (
        <p className="analytics-flash" role="status">
          <Icon name="check" size={14} /> {flash}
        </p>
      )}
      {error && <p className="form-error">{error}</p>}

      {!board && !error && (
        <div className="analytics-grid" aria-busy="true" aria-label="Loading the board">
          {["quarter", "quarter", "half", "half", "half"].map((w, i) => (
            <section key={i} className={`card analytics-card analytics-skeleton w-${w}`} />
          ))}
        </div>
      )}
      {board && (
        <>
          <div className="analytics-toolbar">
            <ClickedFilters filters={filters} setFilters={setFilters} people={board.people || []} />
            <div className="analytics-actions">
              {own &&
                (editing ? (
                  <>
                    <button className="sf-button" onClick={() => setBuilding("new")} disabled={!options || board.charts.length >= max}
                      title={board.charts.length >= max ? `A board holds up to ${max} charts` : "Add Chart"}>
                      <Icon name="plus" size={14} /> Add Chart
                    </button>
                    <button className="sf-button brand" onClick={() => setEditing(false)}>
                      Done
                    </button>
                  </>
                ) : (
                  hasCharts && (
                    <button className="sf-button" onClick={() => setEditing(true)}>
                      <Icon name="edit" size={14} /> Edit
                    </button>
                  )
                ))}
              {!editing && hasCharts && (
                <>
                  <div className="analytics-menu" ref={menuRef}>
                    <button className="sf-button" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
                      <Icon name="download" size={14} /> Download
                    </button>
                    {menu && (
                      <div className="analytics-menu-list" role="menu">
                        <button role="menuitem" onClick={image}>
                          <Icon name="image" size={14} /> Image
                        </button>
                        <button role="menuitem" onClick={() => excel()}>
                          <Icon name="file" size={14} /> Excel
                        </button>
                      </div>
                    )}
                  </div>
                  {own && board.can_send && (
                    <button className="sf-button brand" onClick={() => setSending("board")}>
                      <Icon name="mail" size={14} /> Send Report
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
          {hasCharts ? (
            <div className={`analytics-grid${loading ? " refreshing" : ""}`} ref={gridRef}>
              {board.charts.map((c, i) => (
                <ChartCard
                  key={c.id}
                  chart={c}
                  groups={options?.groups || []}
                  editing={editing}
                  first={i === 0}
                  last={i === board.charts.length - 1}
                  onEdit={() => setBuilding(c)}
                  onMove={(by) => move(i, by)}
                  onRemove={() => remove(c)}
                  filters={filters}
                  onPick={(p) => setFilters(pickFilter(filters, p))}
                  onExcel={() => excel(c)}
                  onShare={own && board.can_send ? () => setSending(c) : null}
                />
              ))}
            </div>
          ) : own ? (
            <section className="card analytics-empty">
              <EmptyState text="Your board is empty. Add charts that show your work, or start with a few suggested ones." />
              <div className="analytics-empty-actions">
                <button className="sf-button brand" onClick={suggested}>
                  Add Suggested Charts
                </button>
                <button className="sf-button" onClick={() => setBuilding("new")} disabled={!options}>
                  Build My Own
                </button>
              </div>
            </section>
          ) : (
            <section className="card analytics-empty">
              <EmptyState text={`${board.user.full_name} hasn't added any charts yet.`} />
            </section>
          )}
        </>
      )}

      <section className="card analytics-reports">
        <header className="card-header">
          <h2>Reports</h2>
        </header>
        {receives && (
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={box === "received"} className={box === "received" ? "on" : ""} onClick={() => setBox("received")}>
              Sent to Me
            </button>
            <button role="tab" aria-selected={box === "sent"} className={box === "sent" ? "on" : ""} onClick={() => setBox("sent")}>
              Sent by Me
            </button>
          </div>
        )}
        <div className="card-body">
          {reports === null ? <p className="table-empty">Loading…</p> : <ReportList rows={reports} received={box === "received"} onOpen={setOpenReport} />}
        </div>
      </section>

      {building && options && (
        <ChartBuilder
          options={options}
          chart={building === "new" ? null : building}
          period={{ period: filters.period, start_date: filters.start_date, end_date: filters.end_date }}
          onClose={() => setBuilding(null)}
          onSaved={() => {
            setBuilding(null);
            loadBoard(); // with the board's filters
          }}
        />
      )}
      {sending && board && (
        <SendDialog
          board={board}
          chart={sending === "board" ? null : sending}
          filters={filters}
          onClose={() => setSending(null)}
          onSent={(sent) => {
            setSending(null);
            say(`${sent.kind === "chart" ? "Chart shared" : "Report sent"} to ${sent.sent_to}.`);
            if (box === "sent") loadReports();
            else setBox("sent");
          }}
        />
      )}
      {openReport && <ReportDialog id={openReport} groups={options?.groups || []} onClose={() => setOpenReport(null)} onChanged={loadReports} />}
    </div>
  );
}
