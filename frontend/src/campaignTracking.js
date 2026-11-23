// Campaign open and click tracking, as the pages show it (backend/app/tracking.py). Signals, not proof: an open signal
// means the email's tracking image was loaded, a click signal that a tracked link was requested. Mail apps, privacy
// features and security scanners do both on their own, some apps never load images, and a forwarded email records its
// new reader's activity against the original recipient. Engagement is kept apart from sending (a signal never means
// "Delivered"), and no signal is "No open detected", never "Unread".

// What the Admin's settings and every report say, in the same words
export const TRACKING_FACTS = [
  "Only campaigns that ask for it are tracked (Track opens / Track clicks on New Campaign). Existing campaigns aren't changed.",
  "An open signal means the email's tracking image was loaded; a click signal means a tracked link was requested. Mail apps, privacy features and security scanners can do this on their own, and some apps never load images: signals don't prove anyone read the email.",
  "A forwarded email records its new reader's activity against the original recipient.",
  "Signals never change a lead (owner, priority or follow-ups) and never count as delivery.",
];

// "33.3%" for a rate the server gave, "—" when nothing was sent with that tracking (never a division by zero)
export const rateText = (pct) => (pct == null ? "—" : `${pct}%`);

// One recipient's opens or clicks: not tracked (the email didn't carry it), none detected, or the signals so far
export function signalText(tracked, count, kind = "open") {
  if (!tracked) return { text: "Not tracked", tone: "muted" };
  if (!count) return { text: kind === "open" ? "No open detected" : "No click detected", tone: "muted" };
  return { text: `${count} ${kind} signal${count === 1 ? "" : "s"}`, tone: "on" };
}

// The settings address check: tracking addresses must open from the recipient's own computer
export const reachNote = (settings) =>
  settings && !settings.public_https
    ? `Tracking addresses point to ${settings.tracking_base}, which only works on this computer or network. ` +
      "People outside can't load the image or follow tracked links through it: production needs a public https " +
      "address (PUBLIC_URL)."
    : "";
