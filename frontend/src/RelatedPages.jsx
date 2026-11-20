import React, { useEffect, useState } from "react";
import { api } from "./api";
import { EmailList, useEmails } from "./Email";
import { canCreateOpportunity } from "./permissions";
import { amount, dateTime, shortDate } from "./format";
import { regionName } from "./phone";
import { Card, Icon, ObjectIcon, PhoneReveal, StageBadge } from "./ui";

function NotFound({ collection }) {
  return (
    <div className="page">
      <Card title="Record not found">
        <p className="pad">
          This record doesn't exist, or you don't have access to it. <a href={`#/${collection}`}>Back to list</a>
        </p>
      </Card>
    </div>
  );
}

function Highlights({ type, label, name, fields, children }) {
  return (
    <section className="card highlights">
      <div className="highlights-top">
        <ObjectIcon type={type} size={36} />
        <div className="highlights-name">
          <small>{label}</small>
          <h1>{name}</h1>
        </div>
        <div className="button-group">{children}</div>
      </div>
      <dl className="highlights-fields">
        {fields.map(([l, v]) => (
          <div key={l}>
            <dt>{l}</dt>
            <dd>{v || " "}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function FieldGrid({ rows }) {
  return (
    <div className="field-grid">
      {rows.map(([label, value]) => (
        <div className="field-row" key={label}>
          <span className="field-label">{label}</span>
          <span className="field-value">{value || " "}</span>
        </div>
      ))}
    </div>
  );
}

const owner = (data, id) => data.users.find((u) => u.id === id)?.full_name || "";
const site = (url) => (url ? <a href={/^https?:/.test(url) ? url : `https://${url}`} target="_blank" rel="noreferrer">{url}</a> : "");

// No Send Email here: emails are written from a lead, opportunity or contact. The account's email history stays below.
// The account page's Leads card: leads converted into this account, and leads from the same company (name or website)
function AccountLeads({ accountId }) {
  const [leads, setLeads] = useState(null);
  useEffect(() => {
    let live = true;
    setLeads(null);
    api
      .accountLeads(accountId)
      .then((value) => live && setLeads(value))
      .catch(() => live && setLeads({ total: 0, items: [] }));
    return () => {
      live = false;
    };
  }, [accountId]);
  const items = leads?.items || [];
  return (
    <Card title={`Leads (${leads ? leads.total : "…"})`} icon="lead">
      {!leads ? (
        <p className="muted pad">Loading…</p>
      ) : !items.length ? (
        <p className="muted pad">No leads from this company.</p>
      ) : (
        <div className="account-table-wrap">
          <table className="account-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Stage</th>
                <th>Owner</th>
                <th>Linked by</th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td>
                    <a href={`#/leads/${l.id}`}>{l.name}</a>
                  </td>
                  <td>
                    <StageBadge stage={l.stage} />
                  </td>
                  <td>{l.owner_name || "—"}</td>
                  <td>{l.why || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {leads && leads.total > items.length && <p className="muted pad">Showing the newest {items.length} of {leads.total}.</p>}
    </Card>
  );
}

// The account page: a header (name, industry, owner, website), Account information, then its
// Contacts and Leads side by side, its Opportunities and its emails.
export function AccountPage({ id, data, user, openNew, emailVersion }) {
  const account = data.accounts.find((a) => String(a.id) === id);
  const { emails } = useEmails("account_id", account?.id, emailVersion);
  if (!account) return <NotFound collection="accounts" />;
  const contacts = data.contacts.filter((c) => c.account_id === account.id);
  const opps = data.opportunities.filter((o) => o.account_id === account.id);
  const meta = [
    account.industry,
    account.owner_name && `Owner: ${account.owner_name}`,
  ].filter(Boolean);
  return (
    <div className="page record-page account-page">
      <section className="card account-head">
        <ObjectIcon type="account" size={40} />
        <div className="account-title">
          <small>Account</small>
          <h1>{account.name}</h1>
          <p>
            {meta.join(" · ")}
            {account.website && (
              <>
                {meta.length ? " · " : ""}
                {site(account.website)}
              </>
            )}
          </p>
        </div>
        <div className="button-group">
          <button className="sf-button" onClick={() => openNew("contact", { account_id: account.id })}>
            New Contact
          </button>
          {canCreateOpportunity(user) && (
            <button className="sf-button brand" onClick={() => openNew("newOpportunity", { account_id: account.id })}>
              New Opportunity
            </button>
          )}
        </div>
      </section>

      <section className="card account-info">
        <h2>Account information</h2>
        <dl className="account-fields">
          {[
            ["Account name", account.name],
            ["Account owner", account.owner_name],
            ["Industry", account.industry],
            ["Phone", account.phone && <PhoneReveal value={account.phone} />],
            ["Created", dateTime(account.created_at)],
            ["Website", site(account.website)],
            ["LinkedIn", site(account.linkedin_url)],
            ["Address", account.address],
            ["Headcount", account.employees != null ? Number(account.employees).toLocaleString() : ""],
            ["Turnover", amount(account.annual_revenue, account.currency)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className={value ? "" : "none"}>{value || "Not added"}</dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="account-pair">
        <Card
          title={`Contacts (${contacts.length})`}
          icon="contact"
          actions={
            <button className="sf-button small" onClick={() => openNew("contact", { account_id: account.id })}>
              New
            </button>
          }
        >
          {contacts.length ? (
            <div className="account-table-wrap">
              <table className="account-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Title</th>
                    <th>Email</th>
                    <th>Phone</th>
                  </tr>
                </thead>
                <tbody>
                  {contacts.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <a href={`#/contacts/${c.id}`}>{c.full_name}</a>
                      </td>
                      <td>{c.job_title || "—"}</td>
                      <td>{c.email || "—"}</td>
                      <td>{c.phone ? <PhoneReveal value={c.phone} /> : <span className="muted">Not added</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted pad">No contacts yet.</p>
          )}
        </Card>
        <AccountLeads accountId={account.id} />
      </div>

      <Card
        title={`Opportunities (${opps.length})`}
        icon="opportunity"
        actions={
          canCreateOpportunity(user) && (
            <button className="sf-button small" onClick={() => openNew("newOpportunity", { account_id: account.id })}>
              New
            </button>
          )
        }
      >
        {opps.length ? (
          <div className="account-table-wrap">
            <table className="account-table">
              <thead>
                <tr>
                  <th>Opportunity</th>
                  <th>Stage</th>
                  <th>Client POC</th>
                  <th className="num">Amount</th>
                  <th>Close date</th>
                  <th>Owner</th>
                </tr>
              </thead>
              <tbody>
                {opps.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <a href={`#/opportunities/${o.id}`}>{o.name}</a>
                    </td>
                    <td>
                      <StageBadge stage={o.stage} />
                    </td>
                    <td>{o.lead_name || "—"}</td>
                    <td className="num">{amount(o.value, o.currency) || "—"}</td>
                    <td>{shortDate(o.expected_close_date) || "—"}</td>
                    <td>{o.owner || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted pad">No opportunities yet.</p>
        )}
      </Card>

      <Card title={`Emails (${emails.length})`} icon="event">
        <EmailList emails={emails} />
      </Card>
    </div>
  );
}

export function ContactPage({ id, data, openEmail, emailVersion }) {
  const contact = data.contacts.find((c) => String(c.id) === id);
  const { emails } = useEmails("contact_id", contact?.id, emailVersion);
  if (!contact) return <NotFound collection="contacts" />;
  const opps = data.opportunities.filter((o) => o.primary_contact_id === contact.id);
  const name = [contact.salutation, contact.full_name].filter(Boolean).join(" ");
  return (
    <div className="page record-page">
      <Highlights
        type="contact"
        label="Contact"
        name={name}
        fields={[
          ["Title", contact.job_title],
          ["Account Name", <a href={`#/accounts/${contact.account_id}`}>{contact.account_name}</a>],
          ["Phone", contact.phone && <PhoneReveal value={contact.phone} />],
          ["Email", contact.email],
        ]}
      >
        <button
          className="sf-button"
          onClick={() =>
            openEmail({
              type: "contact",
              field: "contact_id",
              id: contact.id,
              name: contact.full_name,
              email: contact.email,
              firstName: contact.first_name,
              noEmail: "This contact has no email address.",
            })
          }
        >
          Send Email
        </button>
      </Highlights>
      <div className="record-columns">
        <section className="card record-main">
          <div className="tabs">
            <button className="on">Details</button>
          </div>
          <div className="detail-section">
            <span className="section-toggle static">
              <Icon name="down" size={12} /> Contact Information
            </span>
            <FieldGrid
              rows={[
                ["Contact Owner", owner(data, contact.owner_id)],
                ["Name", name],
                ["Account Name", <a href={`#/accounts/${contact.account_id}`}>{contact.account_name}</a>],
                ["Title", contact.job_title],
                ["Email", contact.email],
                ["Phone", contact.phone && <PhoneReveal value={contact.phone} />],
                ["Region", regionName(contact.phone_country) || contact.region], // the country chosen beside the phone (empty when none was chosen)
                ["LinkedIn", site(contact.linkedin_url)],
                ["Created", dateTime(contact.created_at)],
                ["Last Modified", dateTime(contact.updated_at)],
              ]}
            />
          </div>
        </section>
        <aside className="record-side">
          <Card title={`Emails (${emails.length})`} icon="event">
            <EmailList emails={emails} />
          </Card>
          <Card title={`Opportunities (${opps.length})`} icon="opportunity">
            <ul className="related-records">
              {opps.map((o) => (
                <li key={o.id}>
                  <a href={`#/opportunities/${o.id}`}>{o.name}</a>
                  <dl>
                    <dt>Stage:</dt>
                    <dd>
                      <StageBadge stage={o.stage} />
                    </dd>
                    <dt>Amount:</dt>
                    <dd>{amount(o.value, o.currency)}</dd>
                  </dl>
                </li>
              ))}
              {!opps.length && <p className="muted pad">No opportunities with this contact.</p>}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}
