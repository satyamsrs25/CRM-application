// Add to Calendar (lead record > Details > Demo Date): a Google Calendar link, an Outlook on the web (Microsoft 365)
// link and an .ics file. Nothing is synchronised and no invitation is sent: the person adds the event themselves.
// Plain functions (no React), so the node test runner checks them (domain.test.js).

export const DEMO_MINUTES = 60; // a demo lasts an hour (the app has no duration setting)

// When the demo starts, as an instant: the API's demo_at (UTC). Demo times are entered and shown in IST
// (businessTime.js); the instant is the same for every viewer and every calendar, whatever their time zone.
export const demoStart = (lead) => new Date(lead.demo_at);

const pad = (n) => String(n).padStart(2, "0");
// 20261120T153000Z (UTC, as calendars expect)
export const utcStamp = (date) =>
  `${date.getUTCFullYear()}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}T${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())}Z`;

const demoEnd = (start) => new Date(start.getTime() + DEMO_MINUTES * 60000);

export function googleCalendarUrl({ title, start, description }) {
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: title,
    dates: `${utcStamp(start)}/${utcStamp(demoEnd(start))}`,
    details: description || "",
  });
  return `https://calendar.google.com/calendar/render?${params}`;
}

// Outlook on the web for work and school accounts (Microsoft 365), not outlook.live.com (personal Outlook.com)
export function outlookCalendarUrl({ title, start, description }) {
  const params = new URLSearchParams({
    path: "/calendar/action/compose",
    rru: "addevent",
    subject: title,
    startdt: start.toISOString(),
    enddt: demoEnd(start).toISOString(),
    body: description || "",
  });
  return `https://outlook.office.com/calendar/0/deeplink/compose?${params}`;
}

// TEXT values (RFC 5545 3.3.11): backslash, semicolon and comma are escaped, line breaks become \n
export const icsText = (value) =>
  String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r\n|\r|\n/g, "\\n");

// Lines longer than 75 octets continue on the next line, which starts with a space (RFC 5545 3.1)
export function foldIcsLine(line) {
  const encoder = new TextEncoder();
  const lines = [];
  let current = "";
  let octets = 0;
  for (const ch of line) {
    const size = encoder.encode(ch).length;
    if (octets + size > 75) {
      lines.push(current);
      current = ` ${ch}`;
      octets = 1 + size;
    } else {
      current += ch;
      octets += size;
    }
  }
  lines.push(current);
  return lines.join("\r\n");
}

// One event, no organizer or attendees (no invitation is sent). The UID is the lead's: importing the file again
// after the demo moved updates the same event instead of adding a second one.
export function icsContent({ uid, title, start, description, stamp = new Date() }) {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SalesTrack CRM//Demo//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${utcStamp(stamp)}`,
    `DTSTART:${utcStamp(start)}`,
    `DTEND:${utcStamp(demoEnd(start))}`,
    `SUMMARY:${icsText(title)}`,
    ...(description ? [`DESCRIPTION:${icsText(description)}`] : []),
    "END:VEVENT",
    "END:VCALENDAR",
  ];
  return `${lines.map(foldIcsLine).join("\r\n")}\r\n`;
}

// The event for a lead's demo: shown only for a lead at Demo with a demo date (not Converted, Lost or a cancelled
// demo). No LOCATION: the lead's address is not where the demo happens, and the app has no meeting link.
export function demoEvent(lead) {
  if (!lead || lead.stage !== "Demo" || !lead.demo_date || !lead.demo_at) return null;
  const name = [lead.salutation, lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.name;
  const details = [
    `Sales demo with ${lead.name}${lead.company ? ` from ${lead.company}` : ""}.`,
    lead.email && `Email: ${lead.email}`,
    lead.phone && `Phone: ${lead.phone}`,
  ].filter(Boolean);
  return {
    uid: `lead-${lead.id}-demo@salestrack`,
    title: `Sales Demo: ${name}${lead.company ? ` (${lead.company})` : ""}`,
    start: demoStart(lead),
    description: details.join("\n"),
    fileName: `Sales_Demo_${String(lead.name || "lead").replace(/[^a-zA-Z0-9]+/g, "_")}.ics`,
  };
}
