import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { homeDescription } from "./domain";
import { amount, compactMoney, currencySymbol, dateTime, greeting, shortDate, time } from "./format";
import { DISPLAY_CURRENCIES, convert, moneyIn, ratesNote, total } from "./currencyConvert";
import { Card, EmptyState, Icon, ObjectIcon, Ring, StageBadge } from "./ui";
import { formatBusiness, formatBusinessTime } from "./businessTime";
import { can } from "./permissions";
import { localIso, periodQuery } from "./homePeriod";
import PeriodPicker from "./PeriodPicker";
import AnalyticsPage, { HomeTabs } from "./Analytics";

// Home > Dashboard: one dashboard per role. The tab needs the "Dashboard" permission (Manage Access > Permissions >
// Home; the Admin has it); without it Home opens Analytics (if allowed):
// - Salesperson, and a Manager's Me view: Active Tasks, Scheduled Demos, Overall Value, Follow-up Radar, My Scorecard,
//   Recent Activity (GET /api/home)
// - Manager's My Team view: Active Tasks, Scheduled Demos, Overall Value, Win/Loss Analysis, Team Performance
//   (GET /api/home/team-charts)
// - Admin (every record): Overall Value, Win/Loss Analysis, Lead Sources, Closing Soon, Follow-up Radar,
//   Recent Activity
// The period (top right) applies to every card except Active Tasks, Scheduled Demos, Closing Soon and Recent Activity,
// which are about now. Every amount is shown in the currency chosen next to it (Currency: USD, INR...): deals in other
// currencies are converted at fixed rates (currencyConvert.js), so totals never mix "$" and "₹".

const COLORS = { open: "#06a59a", won: "#1b96ff", lost: "#ea001e" };
const list = (collection, view) => `#/${collection}?list=${encodeURIComponent(view)}`;
// The dashboard's currency (the Currency drop-down), remembered in this browser
const DisplayCurrency = createContext("USD");
const CURRENCY_KEY = "salestrack.homeCurrency";
function useDisplayCurrency() {
  const [currency, setCurrency] = useState(() => {
    try {
      const saved = window.localStorage.getItem(CURRENCY_KEY);
      return DISPLAY_CURRENCIES.includes(saved) ? saved : "USD";
    } catch {
      return "USD";
    }
  });
  const choose = (value) => {
    setCurrency(value);
    try {
      window.localStorage.setItem(CURRENCY_KEY, value);
    } catch {
      // private window: the choice lasts until the page is left
    }
  };
  return [currency, choose];
}
// {"USD": 15000, "INR": 200000} -> "$17K" in the dashboard's currency
function useMoney() {
  const currency = useContext(DisplayCurrency);
  return { currency, money: (values) => moneyIn(values, currency), sum: (values) => total(values, currency) };
}
const percent = (value) => (value === null || value === undefined ? "–" : `${value}%`);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const ROUTE = { Lead: "leads", Opportunity: "opportunities", Account: "accounts", Contact: "contacts" };

function ViewButton({ href, children }) {
  return (
    <a className="outline-button" href={href}>
      {children}
    </a>
  );
}

// Each pill opens the matching list (items: [colorKey, text, href])
function Legend({ items }) {
  return (
    <ul className="legend">
      {items.map(([key, text, href]) => (
        <li key={key}>
          <i style={{ background: COLORS[key] }} />
          <a className={`pill pill-${key}`} href={href}>
            {text}
          </a>
        </li>
      ))}
    </ul>
  );
}

// One series of horizontal bars (one hue; the label on each row names it, the value sits at the bar's end)
function BarList({ rows, format = (v) => v, label }) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  return (
    <ul className="team-bars" aria-label={label}>
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${format(r.value, r)}${r.note ? ` (${r.note})` : ""}`}>
          <span className="team-bar-label">{r.href ? <a href={r.href}>{r.label}</a> : r.label}</span>
          <span className="team-bar-track">
            <span className="team-bar" style={{ width: max ? `${Math.max((r.value / max) * 100, r.value ? 2 : 0)}%` : 0 }} />
          </span>
          <span className="team-bar-value">
            {format(r.value, r)}
            {r.note && <small>{r.note}</small>}
          </span>
        </li>
      ))}
    </ul>
  );
}

// A "Today" or "Upcoming" part of Active Tasks / Scheduled Demos
function Section({ title, count, children }) {
  return (
    <div className="home-section">
      <h3>
        {title} <span className="home-section-count">{count}</span>
      </h3>
      {children}
    </div>
  );
}

// Active Tasks: High priority tasks (and any proposal task) come first, then overdue, then by due date
const isHighTask = (t) => t.priority === "High" || /proposal/i.test(t.title || "");
const byPriority = (tasks) =>
  tasks
    .map((t, i) => [t, i])
    .sort(([a, i], [b, j]) => isHighTask(b) - isHighTask(a) || i - j)
    .map(([t]) => t);

function TaskRows({ tasks, toggleTask, showDay, empty }) {
  if (!tasks.length) return <p className="home-section-empty">{empty}</p>;
  return (
    <ul className="home-tasks work-list">
      {byPriority(tasks).slice(0, 5).map((t) => (
        <li key={t.id}>
          <input type="checkbox" aria-label={`Complete ${t.title}`} checked={t.completed} disabled={t.completed} onChange={() => toggleTask(t.id)} />
          <div>
            <span className="home-task-title">
              <a href={t.relatedType !== "general" ? `#/${t.relatedType}/${t.relatedId}` : `#/tasks?task=${t.id}`}>{t.title}</a>
              {isHighTask(t) && <span className="pill pill-high">High</span>}
            </span>
            {t.related_to && (
              <small>
                {t.related_type}: {t.related_to}
              </small>
            )}
          </div>
          <span className={t.isOverdue ? "due overdue" : "due"}>
            {t.isOverdue ? `Overdue · ${shortDate(t.due_date)}` : showDay ? dateTime(t.due_date) : time(t.due_date)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EventRows({ events, showDay, empty }) {
  if (!events.length) return <p className="home-section-empty">{empty}</p>;
  return (
    <ul className="home-tasks work-list">
      {events.slice(0, 5).map((e) => (
        <li key={`${e.lead_id}${e.start}`}>
          <ObjectIcon type="event" size={24} />
          <div>
            <a href={`#/leads/${e.lead_id}`}>Demo with {e.name}</a>
            <small>{e.company}</small>
          </div>
          <span className="due">{showDay ? formatBusiness(e.start_at) : formatBusinessTime(e.start_at)}</span>
        </li>
      ))}
    </ul>
  );
}

// Overall Value: open, won and lost amounts of the opportunities created in the period (pills open the lists)
function PipelineCard({ pipeline, views, range }) {
  const { money, sum } = useMoney();
  const show = (key) => money(pipeline.by_currency?.[key]);
  return (
    <Card title="Overall Value" className="home-card" footer={<ViewButton href={`${list("opportunities", views.all)}${range}`}>View Opportunities</ViewButton>}>
      <div className="ring-row">
        <Ring
          label={`Total pipeline ${show("total_pipeline")}`}
          segments={[
            { value: sum(pipeline.by_currency?.open), color: COLORS.open },
            { value: sum(pipeline.by_currency?.won), color: COLORS.won },
            { value: sum(pipeline.by_currency?.lost), color: COLORS.lost },
          ]}
        >
          {/* a long amount ("AED 12.5M") gets a smaller line so it stays inside the ring */}
          <strong className={show("total_pipeline").length > 8 ? "ring-long" : ""}>{show("total_pipeline")}</strong>
          <span>Total Pipeline</span>
        </Ring>
        <Legend
          items={[
            ["open", `${show("open")} Open`, `${list("opportunities", views.open)}${range}`],
            ["won", `${show("won")} Won`, `${list("opportunities", views.won)}${range}`],
            ["lost", `${show("lost")} Lost`, `${list("opportunities", views.lost)}${range}`],
          ]}
        />
      </div>
    </Card>
  );
}

// Won and Lost side by side (count and amount): My Scorecard and Win/Loss Analysis
function Outcomes({ won, wonValues, lost, lostValues }) {
  const { money } = useMoney();
  return (
    <div className="home-score-outcomes">
      <div className="home-score-won">
        <span>Won</span>
        <b>{won ?? 0}</b>
        <small>{money(wonValues)}</small>
      </div>
      <div className="home-score-lost">
        <span>Lost</span>
        <b>{lost ?? 0}</b>
        <small>{money(lostValues)}</small>
      </div>
    </div>
  );
}

// Win/Loss Analysis (Manager's team, Admin): won vs lost, the win rate and the top lost reasons
function WinLossCard({ results, range }) {
  return (
    <Card title="Win/Loss Analysis" className="home-card" footer={<ViewButton href={`${list("opportunities", "Lost Opportunities")}${range}`}>View Lost Opportunities</ViewButton>}>
      <Outcomes won={results.won.count} wonValues={results.won.values} lost={results.lost.count} lostValues={results.lost.values} />
      <p className="home-winrate">
        <b>{percent(results.win_rate)}</b> win rate
      </p>
      <h3 className="home-subhead">Top lost reasons</h3>
      {results.lost_reasons.length ? (
        <BarList label="Top lost reasons" rows={results.lost_reasons.map((r) => ({ label: r.reason, value: r.count }))} />
      ) : (
        <p className="home-section-empty home-note">No deals lost yet.</p>
      )}
    </Card>
  );
}

// Closing Soon (Admin): open opportunities closing in the next 30 days (or late), with their owner
function ClosingSoonCard({ deals }) {
  const { currency } = useMoney();
  return (
    <Card title="Closing Soon" className="home-card" footer={<ViewButton href={list("opportunities", "Open Opportunities")}>View Opportunities</ViewButton>}>
      {deals.length ? (
        <ul className="deal-list">
          {deals.map((d) => (
            <li key={d.id}>
              <ObjectIcon type="opportunity" size={28} />
              <div>
                <a href={`#/opportunities/${d.id}`}>{d.name}</a>
                <small className={d.late ? "overdue" : ""}>
                  {d.account_name} • {d.late ? "Was due" : "Closes"} {shortDate(d.close_date)}
                </small>
                {d.owner_name && <small>{d.owner_name}</small>}
              </div>
              <div className="deal-amount">
                {/* in the dashboard's currency; the deal's own amount on hover */}
                <b title={d.currency && d.currency !== currency ? `${amount(d.amount, d.currency)} (deal currency)` : undefined}>
                  {compactMoney(convert(d.amount, d.currency || "USD", currency), currency)}
                </b>
                <StageBadge stage={d.stage} />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState text="Nothing closing in the next 30 days." small />
      )}
    </Card>
  );
}

// Follow-up Radar: leads, accounts and contacts created in the period; each pill opens the records with that activity
function RadarCard({ home, mine, range }) {
  const rows = [
    ["Lead", "leads", mine ? "My Leads" : "All Leads", home.build_pipeline],
    ["Account", "accounts", mine ? "My Accounts" : "All Accounts", home.accounts],
    ["Contact", "contacts", mine ? "My Contacts" : "All Contacts", home.contacts],
  ];
  return (
    <Card title="Follow-up Radar" className="home-card">
      <ul className="home-radar">
        {rows.map(([noun, collection, view, stats]) => {
          const pick = (activity) => `${list(collection, view)}&activity=${activity}${range}`;
          return (
            <li key={collection}>
              <a className="home-radar-name" href={`${list(collection, view)}${range}`}>
                {plural(stats.total, noun)}
              </a>
              <span>
                <a className="pill pill-upcoming" href={pick("upcoming")}>
                  {stats.upcoming_activity} Upcoming
                </a>
                <a className="pill pill-past" href={pick("past")}>
                  {stats.past_activity} Past
                </a>
                <a className="pill pill-none" href={pick("none")}>
                  {stats.no_activity} No Activity
                </a>
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

// Recent Activity: the leads, opportunities, accounts and contacts changed last (the Admin's also names the owner)
function RecentCard({ records, showOwner }) {
  return (
    <Card title="Recent Activity" className="home-card">
      {records.length ? (
        <ul className="recent-list home-recent">
          {records.map((r) => (
            <li key={r.type + r.id}>
              <ObjectIcon type={r.type} size={28} />
              <div>
                <a href={`#/${ROUTE[r.type]}/${r.id}`}>{r.name}</a>
                <small>
                  {r.type}
                  {showOwner && r.owner_name ? ` • ${r.owner_name}` : ""} • {dateTime(r.updated_at)}
                </small>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState text="Records you work on will show up here." small />
      )}
    </Card>
  );
}

// Lead Sources: leads created in the period per source, and the share of them converted
function SourcesCard({ sources, range }) {
  return (
    <Card title="Lead Sources" className="home-card" footer={<ViewButton href={`${list("leads", "All Leads")}${range}`}>View Leads</ViewButton>}>
      {sources.length ? (
        <BarList
          label="Leads by source"
          format={(v, r) => `${v} · ${percent(r.rate)}`}
          rows={sources.map((s) => ({ label: s.source, value: s.leads, rate: s.conversion_rate, note: `${s.converted} converted` }))}
        />
      ) : (
        <EmptyState text="No new leads." small />
      )}
    </Card>
  );
}

// Team Performance: each salesperson ranked by deals won, then converted leads, then open pipeline
function LeaderboardCard({ people }) {
  const { money, sum } = useMoney();
  const pipeline = (p) => sum(p.open_pipeline_values);
  const ranked = [...people].sort(
    (a, b) =>
      b.won_count - a.won_count ||
      b.converted_this_month - a.converted_this_month ||
      pipeline(b) - pipeline(a) ||
      a.name.localeCompare(b.name),
  );
  const top = Math.max(...ranked.map(pipeline), 0);
  return (
    <Card title="Team Performance" className="home-card home-wide">
      <div className="table-scroll">
        <table className="sf-table">
          <thead>
            <tr>
              <th className="num">Rank</th>
              <th>Name</th>
              <th className="num">Open Leads</th>
              <th className="num">Converted</th>
              <th>Open Pipeline</th>
              <th className="num">Deals Won</th>
              <th className="num">Won</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((p, i) => (
              <tr key={p.id}>
                <td className="num">{i + 1}</td>
                <td>
                  {p.name} {p.role === "Manager" && <small className="muted">(Manager)</small>}
                </td>
                <td className="num">{p.open_leads}</td>
                <td className="num">{p.converted_this_month}</td>
                <td>
                  <span className="team-inline-bar">
                    <span style={{ width: `${top ? (pipeline(p) / top) * 100 : 0}%` }} />
                    <b>{money(p.open_pipeline_values)}</b>
                  </span>
                </td>
                <td className="num">{p.won_count}</td>
                <td className="num">{money(p.won_this_month_values)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!ranked.length && <p className="table-empty">No salespeople yet.</p>}
      </div>
    </Card>
  );
}

// The team cards' data (GET /api/home/team-charts) for this period
function useTeamCharts(enabled, period) {
  const [charts, setCharts] = useState(null);
  const [error, setError] = useState("");
  const key = JSON.stringify(period);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    setError("");
    api
      .teamCharts(periodQuery(period))
      .then((value) => live && setCharts(value))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [enabled, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return { charts: enabled ? charts : null, error };
}

const MINE = { all: "My Opportunities", open: "My Open Opportunities", won: "My Won Opportunities", lost: "My Lost Opportunities" };
const EVERYONE = { all: "All Opportunities", open: "Open Opportunities", won: "Won Opportunities", lost: "Lost Opportunities" };

export default function SellerHome({
  data,
  user,
  toggleTask,
  openTask,
  scope = "team",
  setScope = () => {},
  teamDashboard = true,
  period = { preset: "7d" },
  setPeriod = () => {},
}) {
  const isAdmin = user.role === "Admin";
  const dashboard = can(user, "home_dashboard");
  const teamView = isAdmin || (teamDashboard && scope === "team");
  const { charts, error } = useTeamCharts(dashboard && teamView, period);
  const [currency, setCurrency] = useDisplayCurrency();
  if (!dashboard) return <AnalyticsPage user={user} />; // its own message when Analytics is off too
  const home = data.home?.seller_home;
  if (!home) return null;

  // the period the API counted (no end = up to now): every pill and View button opens its records with it
  const counted = (teamView ? charts?.period : null) || home.period || { start: localIso(new Date(Date.now() - 7 * 864e5)), end: null };
  const shown = { start: counted.start, end: counted.end || new Date() };
  const range = `&from=${encodeURIComponent(counted.start)}${counted.end ? `&to=${encodeURIComponent(counted.end)}` : ""}`;
  const tasksFor = (rows) => (rows || []).map((t) => data.tasks.find((x) => x.id === String(t.id))).filter(Boolean);
  const todayTasks = tasksFor(home.my_tasks?.today);
  const upcomingTasks = tasksFor(home.my_tasks?.upcoming);

  // ----- the user's own work: on the Manager's and Salesperson's dashboards (not the Admin's) -----
  const work = isAdmin
    ? []
    : [
        (
          <Card
            key="actions"
            title="Active Tasks"
            className="home-card"
            actions={
              <button className="icon-btn" aria-label="New task" title="New Task" onClick={() => openTask()}>
                <Icon name="plus" size={14} />
              </button>
            }
            footer={<ViewButton href="#/tasks">View Tasks</ViewButton>}
          >
            <Section title="Today" count={todayTasks.length}>
              <TaskRows tasks={todayTasks} toggleTask={toggleTask} empty="Nothing due today." />
            </Section>
            <Section title="Upcoming" count={upcomingTasks.length}>
              <TaskRows tasks={upcomingTasks} toggleTask={toggleTask} showDay empty="Nothing planned for the next 7 days." />
            </Section>
          </Card>
        ),
        (
          <Card key="meetings" title="Scheduled Demos" className="home-card" footer={<ViewButton href={list("leads", "My Open Leads")}>View Leads</ViewButton>}>
            <Section title="Today" count={home.todays_events.length}>
              <EventRows events={home.todays_events} empty="No demos today." />
            </Section>
            <Section title="Upcoming" count={(home.upcoming_events || []).length}>
              <EventRows events={home.upcoming_events || []} showDay empty="No demos booked for the next 7 days." />
            </Section>
          </Card>
        ),
      ];

  let cards = [];
  if (!teamView) {
    const score = home.scorecard || {};
    cards = [
      ...work,
      <PipelineCard key="pipeline" pipeline={home.close_deals} views={MINE} range={range} />,
      <RadarCard key="radar" home={home} mine range={range} />,
      (
        <Card key="score" title="My Scorecard" className="home-card">
          <Outcomes won={score.won} wonValues={score.won_values} lost={score.lost} lostValues={score.lost_values} />
          <dl className="home-score">
            <div>
              <dt>Win rate</dt>
              <dd>{percent(score.win_rate)}</dd>
            </div>
            <div>
              <dt>Leads converted</dt>
              <dd>{score.converted ?? 0}</dd>
            </div>
            <div>
              <dt>Average deal</dt>
              <dd>{score.won ? moneyIn({ [currency]: total(score.won_values, currency) / score.won }, currency) : moneyIn({}, currency)}</dd>
            </div>
          </dl>
        </Card>
      ),
      <RecentCard key="recent" records={home.recent_records} />,
    ];
  } else if (charts) {
    // ----- the Manager's My Team view / the Admin's dashboard -----
    cards = [
      ...work,
      <PipelineCard key="pipeline" pipeline={charts.pipeline} views={EVERYONE} range={range} />,
      <WinLossCard key="winloss" results={charts.win_loss} range={range} />,
      isAdmin && charts.lead_sources && <SourcesCard key="sources" sources={charts.lead_sources} range={range} />,
      isAdmin && charts.closing_soon && <ClosingSoonCard key="closing" deals={charts.closing_soon} />,
      isAdmin && <RadarCard key="radar" home={home} range={range} />,
      !isAdmin && <LeaderboardCard key="leaders" people={charts.people} />,
      isAdmin && charts.recent_records && <RecentCard key="recent" records={charts.recent_records} showOwner />,
    ];
  }
  cards = cards.filter(Boolean);

  return (
    <div className="page seller-home">
      <HomeTabs active="dashboard" user={user} />
      <div className="home-title">
        <div className="home-greeting">
          {/* Title Case on the page title: "Good Evening" */}
          <h1>{greeting().replace(/\b\w/g, (c) => c.toUpperCase())}!</h1>
          <p>{homeDescription(user.role, teamView)}</p>
        </div>
        <div className="home-controls">
          <PeriodPicker period={period} setPeriod={setPeriod} shown={shown} />
          <label className="home-currency" title={ratesNote(currency)}>
            <span>Currency</span>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Show amounts in">
              {DISPLAY_CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c} ({currencySymbol(c)})
                </option>
              ))}
            </select>
          </label>
          {teamDashboard && !isAdmin && (
            <div className="home-scope" role="group" aria-label="Show records">
              <button className={scope === "team" ? "on" : ""} aria-pressed={scope === "team"} onClick={() => setScope("team")}>
                My Team
              </button>
              <button className={scope === "team" ? "" : "on"} aria-pressed={scope !== "team"} onClick={() => setScope("mine")}>
                Me
              </button>
            </div>
          )}
        </div>
      </div>

      {error && <p className="table-empty">{error}</p>}
      {teamView && !charts && !error ? (
        <p className="table-empty">Loading the dashboard…</p>
      ) : cards.length ? (
        <DisplayCurrency.Provider value={currency}>
          <div className="home-grid">{cards}</div>
        </DisplayCurrency.Provider>
      ) : (
        !error && <EmptyState text="Nothing to show yet." />
      )}
    </div>
  );
}
