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
//
// Cc: Outlook on the web ignores a "cc" parameter on this page (To, Subject and Message were filled, Cc stayed empty).
// The page's "mailtouri" parameter takes a whole mailto: link instead (RFC 6068), the way Outlook handles mailto links
// itself, and that fills Cc as well. So the link carries one mailtouri value: mailto:<to>?cc=…&subject=…&body=…
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

// The draft as a mailto: link (RFC 6068). Each value is percent-encoded on its own (UTF-8), so &, +, #, %, line breaks
// (sent as CRLF) and any language are carried exactly; several addresses are joined with commas (an @ stays readable).
// Empty fields are left out.
const address = (list) => list.map((a) => encodeURIComponent(wellFormed(a)).replace(/%40/g, "@")).join(",");
export function mailtoUri({ to, cc, subject, body }) {
  const params = [
    ["cc", splitAddresses(cc).length ? address(splitAddresses(cc)) : ""],
    ["subject", String(subject ?? "").trim() && encodeURIComponent(wellFormed(String(subject).trim()))],
    ["body", lines(body) && encodeURIComponent(wellFormed(lines(body).replace(/\n/g, "\r\n")))],
  ].filter(([, value]) => value);
  const query = params.map(([key, value]) => `${key}=${value}`).join("&");
  return `mailto:${address(splitAddresses(to))}${query ? `?${query}` : ""}`;
}

// The compose link: the mailto: link above, encoded once more as the page's mailtouri value. Nothing to fill: the
// plain compose page.
export function outlookComposeUrl(draft) {
  const mailto = mailtoUri(draft);
  return mailto === "mailto:" ? OUTLOOK_COMPOSE_URL : `${OUTLOOK_COMPOSE_URL}?mailtouri=${encodeURIComponent(mailto)}`;
}

// What the link fills in, read back (the tests use it): { to, cc, subject, body } as Outlook gets them
export function readComposeUrl(url) {
  const mailto = new URL(url).searchParams.get("mailtouri") || "mailto:";
  const [path, query = ""] = mailto.slice("mailto:".length).split("?");
  const out = { to: decodeURIComponent(path), cc: "", subject: "", body: "" };
  for (const part of query.split("&").filter(Boolean)) {
    const [key, value = ""] = part.split("=");
    out[key] = decodeURIComponent(value).replace(/\r\n/g, "\n");
  }
  return out;
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
