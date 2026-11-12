// New Email from a lead, opportunity, contact or account, and the list of a record's emails.
// The agreed workflow for individual emails: write the email here (or draft it with Help me write), review To, Cc,
// Subject and Message, then "Open in Outlook" opens it in Outlook on the web (Microsoft 365) in a new tab. Attachments
// are added and the email is sent from Outlook. The CRM itself sends nothing, saves nothing and changes no stage.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import EmailDraftAssistant from "./EmailDraftAssistant";
import { dateTime, fileSize } from "./format";
import { addressProblem, draftForCopy, outlookHandoff } from "./outlookDraft";
import { can } from "./permissions";
import { Icon, ObjectIcon } from "./ui";

// PRESERVED, intentionally disabled (CRM attachments of the individual email; see the preserved blocks below).
// Restore these together with them:
// import { attachedSummary } from "./format";
// const MAX_FILE = 10 * 1024 * 1024;
// const MAX_TOTAL = 25 * 1024 * 1024;
// const MAX_FILES = 10;

export const size = fileSize; // also used by the opportunity Attachments card

// Loads the emails of one record; reload() after sending.
export function useEmails(field, id, version = 0) {
  const [emails, setEmails] = useState([]);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    if (!id) return Promise.resolve();
    return api
      .emails(field, id)
      .then((list) => {
        setEmails(list);
        setError("");
      })
      .catch((err) => setError(err.message));
  }, [field, id]);
  useEffect(() => {
    reload();
  }, [reload, version]);
  return { emails, error, reload };
}

// PRESERVED, intentionally disabled: the old "My Outlook" link builder of the direct-send composer. Open in Outlook now
// uses outlookDraft.js (the same Outlook on the web address, with each address list, line breaks and length checked).
// const composeUrl = (app, { to, cc, subject, body }) => {
//   const q = (params) =>
//     Object.entries(params)
//       .filter(([, v]) => v)
//       .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
//       .join("&");
//   return `https://outlook.office.com/mail/deeplink/compose?${q({ to, cc, subject, body })}`;
// };
// const APP_NAME = { outlook: "Outlook" };

// onSent is only used by the preserved direct-send path (App.jsx still passes it)
export function EmailComposer({ target, user, onClose, onSent }) { // eslint-disable-line no-unused-vars
  const [sender, setSender] = useState(null);
  useEffect(() => {
    api.emailSettings().then(setSender).catch(err => setSender({ ai_drafting_enabled: false, settings_error: err.message }));
  }, []);
  const [error, setError] = useState("");
  // Nothing is sent from this window: Outlook sends the email. (The CRM sending state is in the preserved block below.)
  const sending = false;
  const [aiBusy, setAiBusy] = useState(false);
  const [subject, setSubject] = useState(target.subject || "");
  const [message, setMessage] = useState(target.greeting || "");
  // What happened with the last Open in Outlook: { kind: "opened" | "blocked" | "too-long", ... }; the draft stays here
  const [handoff, setHandoff] = useState(null);
  const [copied, setCopied] = useState("");
  const canSend = can(user, "send_emails"); // the same permission the CRM needs to send or log an email
  const ref = useRef(null);
  const formRef = useRef(null);

  /* PRESERVED, intentionally disabled: individual email sent by the CRM mailbox ("Send from: CRM mailbox / My Outlook")
     with CRM attachments. The agreed workflow opens the draft in Outlook, where attachments are added and the email is
     sent, so this composer no longer calls POST /api/emails. The backend endpoint and the mail services are unchanged
     (campaigns, notifications and reminders use them). To restore: uncomment this block, the preserved submit handler
     and the preserved JSX blocks below, remove "const sending = false", and point the form's onSubmit back to submit.

  const [files, setFiles] = useState([]);
  const [sending, setSending] = useState(false);
  // "crm": the app sends it from the CRM mailbox (SMTP). "mine": opens the user's own Gmail / Outlook.
  const [via, setVia] = useState("crm");
  const app = "outlook"; // "My email" always opens Outlook (company mail)
  const fileInput = useRef(null);
  // Attachments: a compact "Attach files" button that opens the chooser / drop area; the chosen files stay listed
  // (with their count and sizes) whether it is open or closed
  const [attachOpen, setAttachOpen] = useState(false);
  const attachButton = useRef(null);
  const fileListRef = useRef(null);
  const removeFile = (file) => {
    setFiles(files.filter((x) => x !== file));
    // the remove button goes away: keep the keyboard on the next file, or on Attach files
    requestAnimationFrame(() => (fileListRef.current?.querySelector("button") || attachButton.current)?.focus());
  };

  const addFiles = (list) => {
    setError("");
    const next = [...files];
    for (const f of list) {
      if (f.size > MAX_FILE) {
        setError(`${f.name} is larger than 10 MB.`);
        continue;
      }
      if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    if (next.length > MAX_FILES) return setError(`You can attach up to ${MAX_FILES} files.`);
    if (next.reduce((s, f) => s + f.size, 0) > MAX_TOTAL) return setError("Attachments can be up to 25 MB in total.");
    setFiles(next);
  };

  const submit = async (event) => {
    event.preventDefault();
    if (sending || aiBusy) return;
    setError("");
    const form = new FormData(event.target);
    if (!String(form.get("to")).trim()) return setError("Enter at least one recipient.");
    form.delete("files");
    if (via === "mine") {
      // open the user's own mailbox right away (inside the click, so the browser doesn't block it)
      window.open(
        composeUrl(app, {
          to: form.get("to"),
          cc: form.get("cc"),
          subject: form.get("subject"),
          body: form.get("body"),
        }),
        "_blank",
        "noopener",
      );
      form.append("open_in", app);
    } else {
      files.forEach((f) => form.append("files", f, f.name));
    }
    form.append(target.field, target.id);
    setSending(true);
    try {
      const email = await api.sendEmail(form);
      onSent(email);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  };
  end of the preserved direct-send code */

  useEffect(() => {
    ref.current?.querySelector("input[name=to]")?.focus();
    const onKey = (e) => e.key === "Escape" && !sending && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, sending]);

  // An edit makes the last Open in Outlook message out of date (the draft in Outlook is the earlier one)
  const resetHandoff = () => {
    setHandoff(null);
    setCopied("");
  };
  useEffect(resetHandoff, [subject, message]);

  const draftNow = () => ({
    to: formRef.current?.elements.to?.value || "",
    cc: formRef.current?.elements.cc?.value || "",
    subject,
    body: message,
  });

  // Opens the tab inside the click (so the browser allows it). Returns false when the browser blocked it.
  const openTab = (url) => {
    const tab = window.open(url, "_blank");
    if (!tab) return false;
    tab.opener = null; // Outlook's page gets no access back to the CRM
    return true;
  };

  // Open in Outlook: checks the draft, then opens Outlook on the web with it. Never calls the CRM send endpoint, never
  // marks anything sent or saves email history; the draft stays in this window.
  const openInOutlook = (event) => {
    event.preventDefault();
    if (aiBusy) return;
    setError("");
    setCopied("");
    if (!canSend) return setError("You don't have the Send emails permission. Ask your Admin or Manager.");
    const draft = draftNow();
    const problem = addressProblem(draft.to, "To", true) || addressProblem(draft.cc, "Cc");
    if (problem) return setError(problem);
    if (!draft.subject.trim()) return setError("Enter a subject.");
    if (!draft.body.trim()) return setError("Enter a message.");
    const plan = outlookHandoff(draft);
    if (!plan.fits) return setHandoff({ kind: "too-long", plan, draft });
    setHandoff(openTab(plan.url) ? { kind: "opened" } : { kind: "blocked", url: plan.url });
  };

  // When the draft is too long for a link: copy the message (or the whole draft), and open Outlook without it
  const copyText = async (text, what) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(`${what} copied. Paste it into the Outlook message (Ctrl+V).`);
    } catch {
      const box = ref.current?.querySelector("#email-message");
      box?.focus();
      box?.select();
      setCopied("Copying isn't allowed here. The message is selected: press Ctrl+C to copy it.");
    }
  };
  const openWithoutMessage = () => {
    if (!openTab(handoff.plan.partialUrl)) setHandoff({ ...handoff, blockedUrl: handoff.plan.partialUrl });
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !sending && onClose()}>
      <section ref={ref} className="modal email-modal" role="dialog" aria-modal="true" aria-labelledby="email-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={sending}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="email-title">New Email</h2>
        </header>
        <form ref={formRef} onSubmit={openInOutlook} onInput={(e) => ["to", "cc"].includes(e.target.name) && resetHandoff()} autoComplete="off">
          <div className="modal-body">
            <div className="email-related">
              <ObjectIcon type={target.type} size={20} />
              <span>
                Related to <b>{target.name}</b>
              </span>
            </div>
            {/* PRESERVED, intentionally disabled: the "Send from" choice (CRM mailbox / My Outlook) and the CRM mailbox's
                Reply-To field. Individual emails now always open in Outlook. Restore with the preserved code above.
            <fieldset className="send-from">
              <legend>Send from</legend>
              <label className={`send-option ${via === "crm" ? "on" : ""}`}>
                <input type="radio" name="via" checked={via === "crm"} onChange={() => setVia("crm")} />
                <span>
                  <b>CRM mailbox</b>
                  <small>
                    Sent by SalesTrack. Replies come to you.
                  </small>
                </span>
              </label>
              <label className={`send-option ${via === "mine" ? "on" : ""}`}>
                <input type="radio" name="via" checked={via === "mine"} onChange={() => setVia("mine")} />
                <span>
                  <b>My Outlook</b>
                  <small>Sent from your own Outlook.</small>
                </span>
              </label>
            </fieldset>
            {via === "crm" ? (
              <label className="field">
                <span>Reply-To</span>
                <input name="reply_to" type="email" defaultValue={user.email} autoComplete="off" />
                <small className="field-hint">Replies from the customer go to this address.</small>
              </label>
            ) : (
              <p className="field-hint send-note">
                Opens {APP_NAME[app]} in a new tab. Add attachments there.
              </p>
            )}
            end of the preserved "Send from" choice */}
            <p className="field-hint send-note">Opens Outlook in a new tab. Add attachments there.</p>
            <label className="field">
              <span>
                To <i>*</i>
              </span>
              <input name="to" defaultValue={target.email || ""} placeholder="name@company.com" required />
            </label>
            <label className="field">
              <span>Cc</span>
              <input name="cc" placeholder="Separate addresses with commas" autoComplete="off" />
            </label>
            <label className="field">
              <span>
                Subject <i>*</i>
              </span>
              <input name="subject" required maxLength={255} value={subject} onChange={e => setSubject(e.target.value)} autoComplete="off" disabled={sending} />
            </label>
            <div className="field">
              <label htmlFor="email-message">Message <i>*</i></label>
              <div className="email-editor">
                {/* stays editable while a draft is written: an answer is dropped if the email changed meanwhile */}
                <textarea id="email-message" name="body" rows={8} required value={message} onChange={e => setMessage(e.target.value)} disabled={sending} />
                <EmailDraftAssistant target={target} settings={sender} user={user} subject={subject} message={message} sending={sending} recipients={() => formRef.current?.elements.to?.value || ""} onBusyChange={setAiBusy} onApply={draft => { setSubject(draft.subject); setMessage(draft.body); }} />
              </div>
            </div>
            {/* PRESERVED, intentionally disabled: CRM attachments of the individual email (Attach files, the chooser and
                drop area, the file input and the list of chosen files). Attachments are added in Outlook now.
            {via === "crm" && (
              <div
                className="email-attach"
                // files can be dropped here whether the chooser is open or not
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  addFiles(e.dataTransfer.files);
                }}
              >
                <div className="email-attach-bar">
                  <button
                    ref={attachButton}
                    type="button"
                    className={`sf-button small attach-toggle ${attachOpen ? "open" : ""}`}
                    aria-expanded={attachOpen}
                    aria-controls="email-attach-panel"
                    title={attachOpen ? "Hide the file chooser" : "Show the file chooser"}
                    onClick={() => setAttachOpen((o) => !o)}
                  >
                    <Icon name="clip" size={14} />
                    Attach files
                    <Icon name="down" size={12} className="attach-chevron" />
                  </button>
                  <span className="attach-summary" aria-live="polite">
                    {attachedSummary(files)}
                  </span>
                </div>
                <div id="email-attach-panel" className="dropzone email-attach-panel" hidden={!attachOpen}>
                  <button type="button" className="sf-button small" onClick={() => fileInput.current.click()}>
                    Choose files
                  </button>
                  <span className="muted">or drop files here (up to {MAX_FILES} files, 10 MB each, 25 MB total)</span>
                </div>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  onChange={(e) => {
                    addFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
                {files.length > 0 && (
                  <ul className="file-list" ref={fileListRef} aria-label="Attached files">
                    {files.map((f) => (
                      <li key={f.name + f.size}>
                        <ObjectIcon type="note" size={20} />
                        <span title={f.name}>{f.name}</span>
                        <small>{size(f.size)}</small>
                        <button type="button" className="attach-remove" aria-label={`Remove ${f.name}`} title="Remove" onClick={() => removeFile(f)}>
                          <Icon name="close" size={12} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            end of the preserved CRM attachments */}
            {handoff?.kind === "opened" && (
              <p className="email-handoff done" role="status">
                Outlook opened in a new tab with this draft. Add attachments and send it from Outlook. If Outlook asked you
                to sign in and the draft isn&apos;t there, click Open in Outlook again. Your draft stays here until you close
                this window.
              </p>
            )}
            {handoff?.kind === "blocked" && (
              <div className="email-handoff" role="alert">
                <b>Your browser blocked the new tab.</b> Allow pop-ups for this site, or{" "}
                <a href={handoff.url} target="_blank" rel="noopener noreferrer">
                  open the draft in Outlook
                </a>
                . Your draft stays here.
              </div>
            )}
            {handoff?.kind === "too-long" && (
              <div className="email-handoff" role="alert">
                <p>
                  <b>This email is too long to open in Outlook in one step.</b> An Outlook link holds about{" "}
                  {handoff.plan.limit.toLocaleString("en-US")} characters and this draft needs{" "}
                  {handoff.plan.length.toLocaleString("en-US")}. Nothing has been cut, and your draft stays here.
                </p>
                <p>
                  {handoff.plan.partialHasFields
                    ? "Copy the message, open Outlook with To, Cc and Subject, then paste the message there."
                    : "Copy the whole draft, open Outlook, then paste it there."}
                </p>
                <div className="email-handoff-actions">
                  {handoff.plan.partialHasFields ? (
                    <button type="button" className="sf-button small" onClick={() => copyText(handoff.draft.body, "Message")}>
                      Copy message
                    </button>
                  ) : (
                    <button type="button" className="sf-button small" onClick={() => copyText(draftForCopy(handoff.draft), "Draft")}>
                      Copy draft
                    </button>
                  )}
                  <button type="button" className="sf-button small" onClick={openWithoutMessage}>
                    {handoff.plan.partialHasFields ? "Open Outlook without the message" : "Open Outlook"}
                  </button>
                </div>
                {copied && <p role="status">{copied}</p>}
                {handoff.blockedUrl && (
                  <p>
                    Your browser blocked the new tab.{" "}
                    <a href={handoff.blockedUrl} target="_blank" rel="noopener noreferrer">
                      Open Outlook
                    </a>
                  </p>
                )}
              </div>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="sf-button" onClick={onClose} disabled={sending}>
              {handoff?.kind === "opened" ? "Close" : "Cancel"}
            </button>
            {/* the only action: nothing is sent from the CRM */}
            <button
              type="submit"
              className="sf-button brand"
              disabled={aiBusy || !canSend}
              title={canSend ? "Open this draft in Outlook on the web in a new tab" : "You don't have the Send emails permission"}
            >
              Open in Outlook
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function EmailItem({ email: initial }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState(initial);
  const [resending, setResending] = useState(false);
  const [resendError, setResendError] = useState("");
  useEffect(() => setEmail(initial), [initial]);
  // An older entry saved when a draft was opened in Gmail / Outlook: the CRM never knew whether it was sent
  const handoff = ["Gmail", "Outlook"].includes(email.status);
  // A failed email can be sent again (same text and attachments), e.g. after the mail server is fixed
  const resend = async () => {
    setResending(true);
    setResendError("");
    try {
      const updated = await api.resendEmail(email.id);
      setEmail(updated);
      if (updated.status === "Failed") setResendError(`Still not sent: ${updated.error}`);
    } catch (err) {
      setResendError(err.message);
    } finally {
      setResending(false);
    }
  };
  return (
    <li className={`email-item ${email.status === "Failed" ? "failed" : ""}`}>
      <ObjectIcon type="note" size={24} />
      <div>
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {email.subject}
        </button>
        <small>
          {email.sent_by_name} {handoff ? "opened a draft to" : "to"} {email.to_address}
          {email.attachments.length ? ` • ${email.attachments.length} attachment${email.attachments.length > 1 ? "s" : ""}` : ""}
          {email.status === "Failed" ? " • Not sent" : ""}
          {handoff ? ` • Draft opened in ${email.status}; sending not confirmed` : ""}
        </small>
        {open && (
          <div className="email-open">
            {email.cc_address && <p className="muted">Cc: {email.cc_address}</p>}
            <p className="email-body">{email.body}</p>
            {email.status === "Failed" && <p className="form-error">Not sent: {email.error}</p>}
            {email.attachments.length > 0 && (
              <ul className="file-list">
                {email.attachments.map((a) => (
                  <li key={a.id}>
                    <ObjectIcon type="note" size={20} />
                    <a href={api.attachmentUrl(a.id)} download={a.filename}>
                      {a.filename}
                    </a>
                    <small>{size(a.size_bytes)}</small>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <span className="email-side">
        <span className="due" title={handoff ? "When the draft was opened" : undefined}>{dateTime(email.sent_at)}</span>
        {email.status === "Failed" && (
          <button className="sf-button small" onClick={resend} disabled={resending} aria-busy={resending}>
            {resending ? "Sending…" : "Resend"}
          </button>
        )}
        {resendError && (
          <small className="form-error" role="alert">
            {resendError}
          </small>
        )}
      </span>
    </li>
  );
}

export function EmailList({ emails, empty = "No emails yet." }) {
  return emails.length ? (
    <ul className="task-lines">
      {emails.map((e) => (
        <EmailItem key={e.id} email={e} />
      ))}
    </ul>
  ) : (
    <p className="muted pad">{empty}</p>
  );
}
