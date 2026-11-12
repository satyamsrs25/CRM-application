// Open in Outlook (individual record emails): the email written or AI-drafted in the CRM is opened in Outlook on the web
// (Microsoft 365) as a new message with To, Cc, Subject and Message filled in. Outlook signs the user in if needed; the
// user adds attachments there and sends from Outlook. The CRM sends nothing, saves nothing and changes no stage.
// Plain functions (no React), so the node test runner checks them (domain.test.js).
//
// Why this link, and why Outlook shows the draft on its own compose page: Outlook on the web has no supported link that
// opens a pre-filled new message inside the mailbox view (folders and message list beside it). The older
// "/owa/?path=/mail/action/compose&to=…" form, which used to open there, is now redirected by Microsoft to this same
// "/mail/deeplink/compose" page before sign-in (checked 2026-11 without signing in), so it gives the same layout. What
// remains is Microsoft Graph (an API that creates a draft in the mailbox), which this workflow deliberately doesn't use.
// When the user isn't signed in yet, Microsoft's sign-in request carries this whole link unchanged (every encoded
// character intact) to return to after sign-in; nothing here asks for a sign-in, so an existing Outlook session is used.

export const OUTLOOK_COMPOSE_URL = "https://outlook.office.com/mail/deeplink/compose";

// A link longer than this is not opened. Microsoft's web front ends commonly refuse request addresses over about 8 KB,
// and when Outlook first asks the user to sign in, the compose address travels inside the sign-in address, encoded once
// more, so it grows. 4,000 characters keeps both well inside that. A longer draft is never cut: the composer offers to
// copy the message and open Outlook with To, Cc and Subject only.
export const OUTLOOK_URL_LIMIT = 4000;

// The same address check as the API (backend/app/routers/emails.py, EMAIL_RE); commas or semicolons separate addresses
const EMAIL_RE = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/;
export const splitAddresses = (value) =>
  String(value ?? "")
    .split(/[,;]/)
    .map((address) => address.trim())
    .filter(Boolean);

// "" when the field is fine, otherwise what to fix
export function addressProblem(value, label, required = false) {
  const list = splitAddresses(value);
  if (required && !list.length) return "Enter at least one recipient.";
  const bad = list.filter((address) => !EMAIL_RE.test(address));
  return bad.length ? `Check the ${label} address${bad.length > 1 ? "es" : ""}: ${bad.join(", ")}` : "";
}

// Line breaks as plain \n; text that can't be encoded (a broken emoji half) becomes the replacement character
const lines = (text) => String(text ?? "").replace(/\r\n?/g, "\n");
const wellFormed = (text) => (typeof text.toWellFormed === "function" ? text.toWellFormed() : text);

// The compose link. Each value is percent-encoded on its own (UTF-8), so &, +, #, %, line breaks and any language are
// carried exactly; several addresses are joined with commas. Empty fields are left out.
export function outlookComposeUrl({ to, cc, subject, body }) {
  const params = [
    ["to", splitAddresses(to).join(",")],
    ["cc", splitAddresses(cc).join(",")],
    ["subject", String(subject ?? "").trim()],
    ["body", lines(body)],
  ];
  const query = params
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}=${encodeURIComponent(wellFormed(value))}`)
    .join("&");
  return query ? `${OUTLOOK_COMPOSE_URL}?${query}` : OUTLOOK_COMPOSE_URL;
}

// What Open in Outlook can do with this draft: open it whole (fits), or, when the link would be too long, open Outlook
// with To, Cc and Subject (or an empty message if even those don't fit) while the message is copied. Never truncates.
export function outlookHandoff(draft, limit = OUTLOOK_URL_LIMIT) {
  const url = outlookComposeUrl(draft);
  if (url.length <= limit) return { fits: true, url, length: url.length, limit };
  const withoutBody = outlookComposeUrl({ ...draft, body: "" });
  return {
    fits: false,
    url: null,
    length: url.length,
    limit,
    partialUrl: withoutBody.length <= limit ? withoutBody : OUTLOOK_COMPOSE_URL,
    partialHasFields: withoutBody.length <= limit,
  };
}

// The whole draft as text, for the clipboard when Outlook can't take it through the link
export function draftForCopy({ to, cc, subject, body }) {
  return [
    `To: ${splitAddresses(to).join(", ")}`,
    ...(splitAddresses(cc).length ? [`Cc: ${splitAddresses(cc).join(", ")}`] : []),
    `Subject: ${String(subject ?? "").trim()}`,
    "",
    lines(body),
  ].join("\n");
}
