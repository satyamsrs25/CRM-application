// Home's period selector: the analytics cards count the records created in [start, end) of this period.
// "Past 1 week" is worked out at the moment Home loads (the last 7 days up to now); a custom range is two local
// date-times. The period is remembered in this browser (an older saved choice falls back to Past 1 week).

export const PERIODS = [
  ["7d", "Past 1 week"],
  ["custom", "Custom range"],
];
export const DEFAULT_PERIOD = { preset: "7d" };
const STORAGE_KEY = "crm-home-period";

const pad = (n) => String(n).padStart(2, "0");
// Local date-time without a time zone, as the API stores it: 2026-11-12T15:30:00
export const localIso = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

// { start, end } as Dates; end is not included. Unknown or incomplete periods fall back to the default.
export function periodRange(period = DEFAULT_PERIOD, now = new Date()) {
  const end = new Date(now.getTime() + 60_000); // includes records created in this minute
  const start = new Date(now);
  if (period?.preset === "custom") {
    const from = new Date(period.from);
    const to = new Date(period.to);
    if (!Number.isNaN(from.getTime()) && !Number.isNaN(to.getTime()) && from < to) return { start: from, end: to };
  }
  start.setDate(start.getDate() - 7); // Past 1 week (also for an incomplete custom range)
  return { start, end };
}

// The API query for this period: "start=..." for Past 1 week (up to now), "start=...&end=..." for a custom range
export function periodQuery(period, now = new Date()) {
  const { start, end } = periodRange(period, now);
  const query = `start=${encodeURIComponent(localIso(start))}`;
  return period?.preset === "custom" ? `${query}&end=${encodeURIComponent(localIso(end))}` : query;
}

// "Nov 5 – Nov 12, 2026" (with times for a custom range)
export function periodLabel(start, end, withTime = false) {
  const s = new Date(start);
  const e = new Date(end);
  const sameYear = s.getFullYear() === e.getFullYear();
  const day = (d, year) =>
    d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) });
  const clock = (d) => (withTime ? `, ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}` : "");
  return `${day(s, !sameYear)}${clock(s)} – ${day(e, true)}${clock(e)}`;
}

export function loadPeriod() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return saved && PERIODS.some(([key]) => key === saved.preset) ? saved : DEFAULT_PERIOD;
  } catch {
    return DEFAULT_PERIOD;
  }
}

export function savePeriod(period) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(period));
  } catch {
    /* private window: not remembered */
  }
}
