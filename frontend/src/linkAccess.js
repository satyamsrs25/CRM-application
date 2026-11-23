// Opening a record from a link (the "Open in SalesTrack" button of an assignment email, a bookmark): what to tell the
// person when it doesn't open. Three different things, never mixed up:
// - "offline": SalesTrack's server didn't answer (no network, timed out, a gateway page): a connection problem;
// - "denied": the server answered that this account can't open the record (it doesn't exist, it belongs to someone
//   else, or it was reassigned after the email was sent). The server answers the same for "doesn't exist" and "not
//   yours", so the page doesn't tell them apart either;
// - "error": the server answered with another error.
export function loadProblem(error) {
  if (error?.unreachable) return "offline";
  return error?.status === 403 || error?.status === 404 ? "denied" : "error";
}

// The record a route opens ("/leads/12" -> "lead"), shown on the sign-in page so a signed-out person knows they go
// straight back to it after signing in; null for a list or any other page.
const RECORDS = { leads: "lead", opportunities: "opportunity", accounts: "account", contacts: "contact" };
export function linkDestination(route = "") {
  const [, section, id] = route.split("?")[0].split("/");
  return id ? RECORDS[section] || null : null;
}
