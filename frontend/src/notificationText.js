// The bell's short text. A notification's message keeps every detail (one per line) for its email; the bell and the
// pop-up show only what it is about: the first sentence, plus the record's name and company when that sentence
// doesn't name it. The full message is in the tooltip, and the record opens on click.

const NAME = /^(Lead|Opportunity|Account|Contact|Task):\s*(.+)$/;
const MAX = 140;

export function shortNotification(message) {
  const lines = String(message || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) return "";
  const clip = (text) => (text.length > MAX ? `${text.slice(0, MAX - 1).trimEnd()}…` : text);
  const first = clip(lines[0]);
  const named = lines.slice(1).map((line) => line.match(NAME)).find(Boolean);
  if (!named || first.includes(named[2])) return first;
  const company = lines.map((line) => line.match(/^Company:\s*(.+)$/)).find(Boolean);
  const extra = company && company[1] !== "No company" ? ` · ${company[1]}` : "";
  return `${first}\n${clip(`${named[1]}: ${named[2]}${extra}`)}`;
}

// When a notification came, as a clock time in the viewer's own time zone (where their computer is):
// "Today, 9:51 PM", "Yesterday, 9:51 PM", "Nov 22, 9:51 PM", "Nov 22, 2025, 9:51 PM". Times come from the server
// with its offset, so the same moment shows as 9:51 PM in New York and 8:21 AM the next day in India.
// timeZone: for tests only (empty = this browser's zone).
export function notificationTime(value, nowMs = Date.now(), timeZone = undefined) {
  if (!value) return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  const zone = timeZone ? { timeZone } : {};
  const day = (ms) => new Date(ms).toLocaleDateString("en-CA", zone); // 2026-11-24 in that zone
  const clock = at.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", ...zone });
  if (day(at.getTime()) === day(nowMs)) return `Today, ${clock}`;
  if (day(at.getTime()) === day(nowMs - 86400000)) return `Yesterday, ${clock}`;
  const sameYear = day(at.getTime()).slice(0, 4) === day(nowMs).slice(0, 4);
  const date = at.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }), ...zone });
  return `${date}, ${clock}`;
}

// The full date, time and time zone, for the tooltip: "Tue, Nov 24, 2026, 9:51 PM EST"
export function notificationTimeFull(value, timeZone = undefined) {
  if (!value) return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    timeZoneName: "short", ...(timeZone ? { timeZone } : {}),
  });
}
