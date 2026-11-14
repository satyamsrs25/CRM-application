// LinkedIn Profile URL with Apollo autofill: at the top of the lead form, and on the contact forms (New Contact, and
// New Opportunity > New contact). A complete profile address (pasted, or typed and then paused) is looked up in Apollo
// through the backend, and the details found fill the fields that are empty.
// - Each profile is looked up once per form (pasting it again, or going back to it, reuses the answer).
// - A newer address always wins: an older answer that arrives late is never applied. On a contact form the chosen
//   account is part of the request too: a late answer for another account is never applied.
// - Values the user typed or changed are never touched. Unchanged autofill from a previous address is replaced,
//   or removed when the address is cleared or the new one has no value for that field. A failed check of the same
//   address again (after the account changed) leaves what it filled in place.
// - Contacts: only the person's details are filled. The account is never chosen or changed; when Apollo lists another
//   current employer, the form says so.
// - Nothing is saved or sent here; Save runs the usual checks (required fields, duplicate email).
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { AUTOFILL_FIELDS, autofillPlan, autofillSummary, linkedInProfileUrl } from "./domain";
import { PHONE_RECHECK_EVENT, phoneCountryOf } from "./phone";
import { Icon } from "./ui";

const TYPING_PAUSE = 800; // ms after the last key before a typed address is looked up
const identity = (values) => values || {};

// required: only when Lead Source is LinkedIn (leadFieldsRequired); error: the form's message for this field.
// The contact forms also pass: name (the input's name), fields ({ input name: label } Apollo can fill), lookup (the
// backend request), toForm (Apollo's field names -> the form's), write (for inputs React controls), company (the
// chosen account), phone ({ field, country }: an international number sets the country), needed (required inputs)
// and noun ("contact").
export default function LinkedInField({
  autofill,
  defaultValue,
  form,
  onCompany,
  required = false,
  error = "",
  onInput,
  name = "linkedin_url",
  label = "LinkedIn Profile URL",
  fields = AUTOFILL_FIELDS,
  lookup: request = (url) => api.enrichLead(url),
  toForm = identity,
  write,
  company,
  phone,
  needed = [],
  noun = "lead",
  compact = false, // contact forms: no helper text or success narration; only loading, errors and essential warnings
  onMatched, // called after a verified match of the address now in the field has been applied (New Lead: the source),
  //            with the names of the fields it filled or cleared
}) {
  const [status, setStatus] = useState({ kind: "idle" });
  const enabled = useRef(null); // null until the server says whether Apollo is set up
  const answers = useRef(new Map()); // request key -> Apollo's answer, for this form only
  const pending = useRef(new Map()); // request key -> the lookup in progress
  const current = useRef(""); // the request key now wanted ("" = no valid address)
  const currentUrl = useRef(""); // the valid profile address now in the field
  const filled = useRef({}); // values Apollo filled that the user hasn't changed
  const filledFor = useRef(""); // the address those values came from
  const timer = useRef(null);
  const companyTimer = useRef(null);
  const alive = useRef(true);
  const companyNow = company === undefined ? undefined : String(company || "").trim();
  const keyOf = (url) => (companyNow === undefined ? url : `${url}\n${companyNow}`);

  useEffect(() => {
    alive.current = true;
    if (!autofill) return undefined;
    api
      .leadEnrichmentStatus()
      .then((res) => {
        enabled.current = !!res.enabled;
        // compact: said only when the user enters a profile address, not as a standing note
        if (alive.current && !res.enabled && !compact) setStatus((s) => (s.kind === "idle" ? { kind: "off" } : s));
      })
      .catch(() => {});
    // A field the user changes is theirs from then on.
    const element = form();
    const onEdit = (event) => {
      const { name: field } = event.target;
      if (field in filled.current && event.target.value !== filled.current[field]) {
        delete filled.current[field];
        event.target.classList.remove("autofilled");
      }
    };
    element?.addEventListener("input", onEdit);
    element?.addEventListener("change", onEdit);
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      clearTimeout(companyTimer.current);
      element?.removeEventListener("input", onEdit);
      element?.removeEventListener("change", onEdit);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Puts a profile's values in the form ({} removes the previous profile's untouched values)
  const apply = (incoming, url = "") => {
    const element = form();
    if (!element) return { filled: [], kept: [], missing: [] };
    const inputs = element.elements;
    const values = Object.fromEntries(Object.keys(fields).map((field) => [field, inputs[field]?.value ?? ""]));
    const plan = autofillPlan(values, filled.current, incoming, fields);
    if (write) write(plan.set);
    else for (const [field, value] of Object.entries(plan.set)) if (inputs[field]) inputs[field].value = value;
    // an international number Apollo gave sets the phone's country (the user can still change it)
    const number = phone && plan.set[phone.field];
    const country = number && number.startsWith("+") ? phoneCountryOf(number) : "";
    if (country && inputs[phone.country]) inputs[phone.country].value = country;
    // the phone field checks what it holds now: an entry the user kept is shown as invalid if it is (never erased)
    if (phone) inputs[phone.field]?.dispatchEvent(new Event(PHONE_RECHECK_EVENT, { bubbles: true }));
    for (const field of Object.keys(fields)) inputs[field]?.classList.toggle("autofilled", field in plan.autofilled);
    filled.current = plan.autofilled;
    filledFor.current = Object.keys(plan.autofilled).length ? url : "";
    if ("company" in plan.set) onCompany?.(plan.set.company); // show other records for this company, as when typed
    const after = { ...values, ...plan.set };
    return { ...plan, missing: needed.filter((field) => !String(after[field] ?? "").trim()) };
  };
  // A failed or unmatched lookup of another address removes that address's leftovers; of the same address, nothing
  const clearUnlessSame = (url) => {
    if (url !== filledFor.current) apply({});
  };

  const show = (answer, url) => {
    if (answer.status !== "matched" || answer.url_verified !== true) {
      clearUnlessSame(url);
      if (answer.status === "no_match")
        return setStatus({ kind: "no_match", text: answer.message || "Apollo found no match for this profile." });
      return setStatus({ kind: "unverified", text: answer.message || "The profile could not be verified. Nothing was filled." });
    }
    const plan = apply(toForm(answer.fields), url);
    setStatus({
      kind: "matched",
      ...autofillSummary(plan, fields),
      unavailable: toForm(answer.unavailable),
      missing: plan.missing,
      employer: answer.employer || "",
      employerMatches: answer.employer_matches ?? null,
      company: companyNow || "",
    });
    onMatched?.(Object.keys(plan.set)); // only here: never after a failed, unmatched, unverified or late answer
  };

  const lookup = async (url) => {
    const key = keyOf(url);
    current.current = key;
    currentUrl.current = url;
    if (answers.current.has(key)) return show(answers.current.get(key), url);
    if (enabled.current === false) {
      clearUnlessSame(url);
      return setStatus({ kind: "off" });
    }
    setStatus({ kind: "loading" });
    let pendingRequest = pending.current.get(key);
    if (!pendingRequest) {
      pendingRequest = request(url, companyNow);
      pending.current.set(key, pendingRequest);
    }
    try {
      const answer = await pendingRequest;
      answers.current.set(key, answer);
      if (alive.current && current.current === key) show(answer, url); // an older address's or account's answer is never applied
    } catch (err) {
      if (!alive.current || current.current !== key) return;
      clearUnlessSame(url);
      if (err.status === 503) {
        enabled.current = false;
        setStatus({ kind: "off" });
      } else setStatus({ kind: "error", text: err.message, url });
    } finally {
      pending.current.delete(key);
    }
  };

  // Contacts: another account was chosen while a profile is in the field. Apollo's employer is compared again (the
  // backend reuses its answer: no new Apollo request), and a late answer for the previous account is ignored.
  useEffect(() => {
    if (companyNow === undefined || !autofill || !currentUrl.current) return undefined;
    clearTimeout(companyTimer.current);
    companyTimer.current = setTimeout(() => currentUrl.current && lookup(currentUrl.current), 400);
    return () => clearTimeout(companyTimer.current);
  }, [companyNow]); // eslint-disable-line react-hooks/exhaustive-deps

  const check = (value) => {
    clearTimeout(timer.current);
    if (!value.trim()) {
      current.current = "";
      currentUrl.current = "";
      apply({});
      return setStatus(enabled.current === false ? { kind: "off" } : { kind: "idle" });
    }
    const { url, error: problem } = linkedInProfileUrl(value);
    if (problem) {
      current.current = "";
      currentUrl.current = "";
      apply({});
      return setStatus({ kind: "invalid", text: problem });
    }
    if (keyOf(url) !== current.current) lookup(url); // the same profile again: nothing new to do (Retry is explicit)
  };

  const help = `${name}-autofill-help`;
  const statusId = `${name}-autofill-status`;
  const input = (
    <input
      name={name}
      type="text"
      required={required}
      maxLength={300}
      defaultValue={defaultValue}
      placeholder="https://www.linkedin.com/in/name"
      aria-invalid={error ? true : undefined}
      aria-describedby={[error && `${name}-field-error`, autofill && (compact ? statusId : `${help} ${statusId}`)].filter(Boolean).join(" ") || undefined}
      onInput={onInput}
      onPaste={autofill ? (event) => setTimeout(() => check(event.target.value), 0) : undefined}
      onChange={
        autofill
          ? (event) => {
              const value = event.target.value;
              clearTimeout(timer.current);
              timer.current = setTimeout(() => check(value), value.trim() ? TYPING_PAUSE : 0);
            }
          : undefined
      }
    />
  );
  const labels = (names) => names.map((field) => fields[field] || field).join(", ");
  return (
    <div className="linkedin-field">
      <label className="field">
        <span>
          {label}{required && <i> *</i>}
        </span>
        {input}
        {error && (
          <small id={`${name}-field-error`} className="field-error">
            {error}
          </small>
        )}
      </label>
      {autofill && (
        <>
          {!compact && (
            <small id={help} className="field-hint">
              {noun === "lead"
                ? "Paste a LinkedIn profile URL to autofill available lead details using Apollo."
                : `Optional. Paste the person's LinkedIn profile URL to autofill available ${noun} details using Apollo, or enter them yourself.`}
            </small>
          )}
          {/* compact (contact forms): only what needs the user's attention; a successful fill says nothing */}
          <div id={statusId} className={`autofill-status ${status.kind}`} aria-live="polite">
            {status.kind === "loading" && <p>{compact ? "Looking up…" : "Looking up this profile in Apollo…"}</p>}
            {status.kind === "off" && (
              <p>
                {compact
                  ? "LinkedIn autofill isn't available. Enter the details manually."
                  : `LinkedIn autofill isn't available on this server. Fill in the ${noun} details manually.`}
              </p>
            )}
            {status.kind === "invalid" && <p className="autofill-problem">{status.text}</p>}
            {status.kind === "no_match" && (
              <p>
                {status.text} {compact ? "Enter the details manually." : `Fill in the ${noun} details manually.`}
              </p>
            )}
            {status.kind === "unverified" && (
              <p className="autofill-problem" role="alert">
                <Icon name="warn" size={14} /> {status.text}
                {compact ? "" : ` Fill in the ${noun} details manually.`}
              </p>
            )}
            {status.kind === "error" && (
              <p className="autofill-problem" role="alert">
                <Icon name="warn" size={14} /> {status.text}{" "}
                <button type="button" className="link" onClick={() => lookup(status.url)}>
                  Retry
                </button>
              </p>
            )}
            {status.kind === "matched" && (
              <>
                {!compact && (
                  <p>
                    <Icon name="check" size={14} /> {status.text}
                  </p>
                )}
                {!compact && status.email && <p>{status.email}</p>}
                {status.employerMatches === false && (
                  <p className="autofill-problem" role="alert">
                    <Icon name="warn" size={14} />{" "}
                    {compact
                      ? `Apollo lists ${status.employer} as this person's employer, not ${status.company}. Check it's the right person.`
                      : `Apollo lists ${status.employer} as this person's current employer, not ${status.company}. The ${noun} will still be added to ${status.company}: check that this is the right person.`}
                  </p>
                )}
                {!compact && status.employerMatches === null && status.employer && !status.company && (
                  <p>
                    Apollo lists {status.employer} as this person&apos;s current employer. Choose the account yourself: the
                    lookup never chooses or changes it.
                  </p>
                )}
                {status.missing?.length > 0 && (
                  <p className="autofill-problem">
                    {compact
                      ? `Not provided by Apollo, enter manually: ${labels(status.missing)}.`
                      : `Apollo didn't provide ${labels(status.missing)}. Enter ${status.missing.length > 1 ? "them" : "it"} manually (required).`}
                  </p>
                )}
                {!compact && Object.keys(status.unavailable).length > 0 && (
                  <ul>
                    {Object.entries(status.unavailable).map(([field, reason]) => (
                      <li key={field}>
                        {fields[field] || AUTOFILL_FIELDS[field] || field}: {reason}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
