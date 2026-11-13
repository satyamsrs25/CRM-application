// New Opportunity (Opportunities and Account pages) and the duplicate check shown on New Opportunity and Convert.
// No duplicates: the company's existing account and the person's existing contact are reused (same company name; same
// email or same name), and the same open opportunity for one person at one company can't be handled by two salespeople.
// The server decides (GET /opportunities/duplicate-check); records the user can't open show only their owner.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { contactAnswerFields, contactAutofillFields, OPPORTUNITY_CONTACT_FORM, SALUTATIONS } from "./domain";
import LinkedInField from "./LeadAutofill";
import PhoneField from "./PhoneField";
import { AmountField, Icon } from "./ui";

// Asks the server what would happen, shortly after the user stops typing
export function useDuplicateCheck(params, enabled = true) {
  const [result, setResult] = useState(null);
  const key = JSON.stringify(params);
  useEffect(() => {
    if (!enabled) {
      setResult(null);
      return undefined;
    }
    let live = true;
    const t = setTimeout(() => {
      api
        .opportunityDuplicateCheck(params)
        .then((r) => live && setResult(r))
        .catch(() => live && setResult(null));
    }, 400);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [key, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return result;
}

const who = (r) => (r.mine ? "you" : r.owner || "another user");
const link = (path, r, text) => (r.id ? <a href={`#/${path}/${r.id}`} target="_blank" rel="noreferrer">{text}</a> : text);

export function DuplicateNotice({ result }) {
  if (!result) return null;
  const { account, contact, duplicate, related = [] } = result;
  if (!account && !contact && !duplicate) return null;
  return (
    <div className={`dup-notice${duplicate ? " blocked" : ""}`} role="status" aria-live="polite">
      {duplicate && (
        <p className="dup-line dup-stop">
          <Icon name="warn" size={15} />
          <span>
            <b>Already open:</b> {link("opportunities", duplicate, `"${duplicate.name}"`)} ({duplicate.stage}) for this person is handled by{" "}
            {who(duplicate)}. One opportunity has one salesperson: ask for it to be transferred, or use a different opportunity name.
          </span>
        </p>
      )}
      {account && (
        <p className="dup-line">
          <Icon name="check" size={15} />
          <span>
            Uses the existing account <b>{link("accounts", account, account.name)}</b>
            {account.mine ? "" : ` (owner: ${account.owner})`}, so no duplicate account is created.
          </span>
        </p>
      )}
      {contact && (
        <p className="dup-line">
          <Icon name="check" size={15} />
          <span>
            Uses the existing contact <b>{link("contacts", contact, contact.name)}</b>
            {contact.mine ? "" : ` (owner: ${contact.owner})`}, so no duplicate contact is created.
          </span>
        </p>
      )}
      {related.length > 0 && (
        <p className="dup-line dup-info">
          <Icon name="help" size={15} />
          <span>
            Other open opportunities for this person:{" "}
            {related.map((r, i) => (
              <React.Fragment key={i}>
                {i > 0 && ", "}
                {link("opportunities", r, `"${r.name}"`)} ({who(r)})
              </React.Fragment>
            ))}
            .
          </span>
        </p>
      )}
    </div>
  );
}

// Convert Lead: the same check, from the lead's company, email and name (and the account / opportunity name chosen)
export function ConvertCheck({ leadId, values, onBlocked }) {
  const result = useDuplicateCheck({
    lead_id: leadId,
    name: (values.opportunity_name || "").trim(),
    account_id: values.account_id || "",
  });
  const blocked = !!result?.duplicate;
  useEffect(() => onBlocked(blocked), [blocked]); // eslint-disable-line react-hooks/exhaustive-deps
  return <DuplicateNotice result={result} />;
}

// error: the form's message for this field (shown under it until the field is changed)
const input = (label, name, value, onChange, { required = false, type = "text", error = "", ...rest } = {}) => (
  <label className="field">
    <span>
      {label}
      {required && <i> *</i>}
    </span>
    <input
      name={name}
      type={type}
      required={required}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? `${name}-field-error` : undefined}
      {...rest}
    />
    {error && (
      <small id={`${name}-field-error`} className="field-error">
        {error}
      </small>
    )}
  </label>
);
const F = OPPORTUNITY_CONTACT_FORM;

// The account, contact and deal fields of New Opportunity (the note, first task and owner come from the Modal).
// errors / onFix: the Modal's messages for the new contact's fields (contactProblems) and how to clear one.
export function NewOpportunityFields({ data, defaults, owner, onBlocked, errors = {}, onFix = () => {} }) {
  const [accountId, setAccountId] = useState(defaults?.account_id ? String(defaults.account_id) : "");
  const [accountName, setAccountName] = useState("");
  const [contactId, setContactId] = useState("");
  const [person, setPerson] = useState({ first: "", last: "", email: "" });
  const [name, setName] = useState("");
  const newAccount = accountId === "new";
  const existingAccount = accountId && !newAccount ? Number(accountId) : null;
  const contacts = existingAccount ? data.contacts.filter((c) => c.account_id === existingAccount) : [];
  const newContact = !existingAccount || contactId === "new" || !contacts.length;
  const chosenContact = !newContact && contactId ? Number(contactId) : null;
  const accounts = [...data.accounts].sort((a, b) => a.name.localeCompare(b.name));

  useEffect(() => setContactId(""), [accountId]);
  // the New Contact fields go away when an existing contact is chosen (or the account has contacts to pick from): the
  // draft goes with them, so "+ New contact" always starts blank (no other draft's names or email)
  const showNewContact = newContact && !!(accountId || !accounts.length);
  useEffect(() => {
    if (!showNewContact) setPerson({ first: "", last: "", email: "" });
  }, [showNewContact]);
  const params = {
    account_id: existingAccount || "",
    company: newAccount ? accountName.trim() : "",
    contact_id: chosenContact || "",
    email: newContact ? person.email.trim() : "",
    first_name: newContact ? person.first.trim() : "",
    last_name: newContact ? person.last.trim() : "",
    name: name.trim(),
  };
  const ready = !!(existingAccount || params.company.length >= 2) && !!(chosenContact || params.last_name || params.email);
  const result = useDuplicateCheck(params, ready);
  const blocked = ready && !!result?.duplicate;
  useEffect(() => onBlocked(blocked), [blocked]); // eslint-disable-line react-hooks/exhaustive-deps
  const setP = (key, field) => (value) => {
    if (errors[field]) onFix(field);
    setPerson((p) => ({ ...p, [key]: value }));
  };
  // LinkedIn autofill: the chosen account (or the new company typed) is only compared with Apollo's employer
  const company = existingAccount ? data.accounts.find((a) => a.id === existingAccount)?.name || "" : accountName.trim();
  const contactBox = useRef(null);
  const contactForm = () => contactBox.current?.closest("form");
  // autofill puts names and the email into this component's state (they drive the duplicate check), the rest directly
  const writeContact = (set) => {
    const next = {};
    for (const [field, value] of Object.entries(set)) {
      if (field === F.first_name) next.first = value;
      else if (field === F.last_name) next.last = value;
      else if (field === F.email) next.email = value;
      else if (contactForm()?.elements[field]) contactForm().elements[field].value = value;
    }
    if (Object.keys(next).length) setPerson((p) => ({ ...p, ...next }));
  };
  const fix = (field) => (errors[field] ? () => onFix(field) : undefined);

  return (
    <>
      <p className="field-hint">
        Pick the company and the person, or type new ones. An existing account or contact with the same company or person is
        reused, and the same open opportunity can't be added twice.
      </p>
      <div className="form-grid">
        <label className="field">
          <span>
            Account <i> *</i>
          </span>
          <select name="account_id" required value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Select an account</option>
            <option value="new">+ New account (type the company name)</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {newAccount ? input("Company Name", "account_name", accountName, setAccountName, { required: true, maxLength: 200 }) : <span />}
        {existingAccount && contacts.length > 0 && (
          <label className="field">
            <span>
              Contact <i> *</i>
            </span>
            <select name="primary_contact_id" required value={contactId} onChange={(e) => setContactId(e.target.value)}>
              <option value="">Select a contact</option>
              <option value="new">+ New contact</option>
              {contacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.full_name}
                  {c.job_title ? ` (${c.job_title})` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {existingAccount && contacts.length > 0 && <span />}
      </div>
      {/* a new contact: the same fields and rules as New Contact (an existing contact is reused as it is, with no
          lookup) */}
      {showNewContact && (
        <fieldset className="stage-task" ref={contactBox}>
          <legend>New Contact</legend>
          <LinkedInField
            autofill
            defaultValue=""
            name={F.linkedin_url}
            form={contactForm}
            fields={contactAutofillFields(F)}
            lookup={(url, chosen) => api.enrichContact(url, chosen)}
            toForm={(values) => contactAnswerFields(values, F)}
            write={writeContact}
            company={company}
            phone={{ field: F.phone, country: F.phone_country }}
            needed={[F.first_name, F.last_name, F.email]}
            noun="contact"
            compact
            error={errors[F.linkedin_url] || ""}
            onInput={fix(F.linkedin_url)}
          />
          <div className="form-grid">
            <label className="field">
              <span>Salutation</span>
              <select name="contact_salutation" defaultValue="">
                <option value="">Default / not specified</option>
                {SALUTATIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            {input("First Name", F.first_name, person.first, setP("first", F.first_name), {
              required: true, maxLength: 50, error: errors[F.first_name] })}
            {input("Last Name", F.last_name, person.last, setP("last", F.last_name), {
              required: true, maxLength: 50, error: errors[F.last_name] })}
            {input("Email", F.email, person.email, setP("email", F.email), {
              type: "email", required: true, maxLength: 255, error: errors[F.email] })}
            <label className="field">
              <span>Title</span>
              <input name={F.job_title} maxLength={100} />
            </label>
            <PhoneField name={F.phone} countryName={F.phone_country} error={errors[F.phone] || ""} onInput={fix(F.phone)} />
          </div>
        </fieldset>
      )}
      <div className="form-grid">
        {input("Opportunity Name", "name", name, setName, { required: true, maxLength: 200 })}
        <AmountField label="Amount" name="expected_value" />
        <label className="field">
          <span>Close Date</span>
          <input name="expected_close_date" type="date" />
        </label>
        {owner}
      </div>
      {ready && <DuplicateNotice result={result} />}
    </>
  );
}

// The request body for POST /opportunities from the form values
export function newOpportunityPayload(v, extra) {
  const text = (value) => (typeof value === "string" && value.trim() ? value.trim() : null);
  const isNew = v.account_id === "new";
  const contactNew = !v.primary_contact_id || v.primary_contact_id === "new";
  return {
    name: (v.name || "").trim(),
    expected_value: v.expected_value === "" || v.expected_value == null ? null : Number(v.expected_value),
    currency: v.currency || "USD",
    expected_close_date: v.expected_close_date || null,
    owner_id: v.owner_id ? Number(v.owner_id) : null,
    account_id: isNew || !v.account_id ? null : Number(v.account_id),
    account_name: isNew ? text(v.account_name) : null,
    primary_contact_id: contactNew ? null : Number(v.primary_contact_id),
    contact_salutation: contactNew ? text(v.contact_salutation) : null,
    contact_first_name: contactNew ? text(v.contact_first_name) : null,
    contact_last_name: contactNew ? text(v.contact_last_name) : null,
    contact_email: contactNew ? text(v.contact_email) : null,
    contact_title: contactNew ? text(v.contact_title) : null,
    contact_phone: contactNew ? text(v.contact_phone) : null,
    // the phone's country (checked and saved in international format by the server) and the person's LinkedIn profile
    ...(contactNew ? { contact_phone_country: v.contact_phone_country || "IN", contact_linkedin_url: text(v.contact_linkedin_url) } : {}),
    ...extra,
  };
}
