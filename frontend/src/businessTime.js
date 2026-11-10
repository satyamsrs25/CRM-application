// Demo dates and times use one business time zone: IST (Asia/Kolkata, UTC+05:30, no daylight saving), whatever the
// browser's or the server's time zone. The API stores them without a zone in server time and also sends each demo
// as a UTC instant (demo_at); these helpers convert between that instant and what people type and read in IST.
// backend/app/services.py has the same setting (BUSINESS_TIMEZONE). Other dates (tasks, close dates) are unchanged.

export const BUSINESS_TIMEZONE = "Asia/Kolkata";
export const BUSINESS_TZ_LABEL = "IST (UTC+05:30)";
const OFFSET = "+05:30";
const OFFSET_MINUTES = 5 * 60 + 30;

const toDate = (instant) => {
  const d = instant instanceof Date ? instant : new Date(instant);
  return Number.isNaN(d.getTime()) ? null : d;
};

// "2026-11-20T21:00" (what a date-and-time field holds, in IST) for an instant: a Date or an ISO time with a zone
export function toBusinessInput(instant) {
  const d = instant ? toDate(instant) : null;
  return d ? new Date(d.getTime() + OFFSET_MINUTES * 60000).toISOString().slice(0, 16) : "";
}

// Now, in IST, to the minute (the earliest a demo can be booked for)
export const businessNow = (now = new Date()) => toBusinessInput(now);

// What a date-and-time field holds (IST) -> what the API is sent: the same time with its offset, so it is never read
// in another time zone ("2026-11-20T21:00" -> "2026-11-20T21:00:00+05:30")
export const fromBusinessInput = (value) => (value ? `${String(value).slice(0, 16)}:00${OFFSET}` : null);

// "11/20/2026, 9:00 PM IST" (the app's usual date-and-time look, with the zone)
export function formatBusiness(instant, { time = true } = {}) {
  const d = instant ? toDate(instant) : null;
  if (!d) return "";
  const text = new Intl.DateTimeFormat("en-US", {
    timeZone: BUSINESS_TIMEZONE,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    ...(time ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(d);
  return `${text} IST`;
}

// "9:00 PM IST"
export function formatBusinessTime(instant) {
  const d = instant ? toDate(instant) : null;
  if (!d) return "";
  return `${new Intl.DateTimeFormat("en-US", { timeZone: BUSINESS_TIMEZONE, hour: "numeric", minute: "2-digit" }).format(d)} IST`;
}
