import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { canCreateOpportunity, canCreateSales, canEditRecord } from "./permissions.js";
import {
  api,
  apiRequest,
  leadPayload,
  taskPayload,
  opportunityPayload,
  normalizeTask,
  normalizeWorkspace,
  setToken,
} from "./api.js";
import {
  LEAD_STAGES,
  LEAD_SOURCES,
  PRIORITIES,
  LOST_REASONS,
  salesOverview,
  money,
  ATTACHMENT_MAX_BYTES,
  STAGE_FILES_MAX,
  AUTOFILL_FIELDS,
  autofillPlan,
  autofillSummary,
  linkedInProfileUrl,
  attachmentProblem,
  attachmentType,
  pickStageFiles,
  STAGE_NOTE_REQUIRED,
  CONVERSION_COMMENT_REQUIRED,
  stageNote,
  stageNoteField,
  stageNoteMessage,
  leadBoardColumns,
  leadStageAction,
  TASK_SUBJECT_REQUIRED,
  TASK_DUE_REQUIRED,
  stageTaskNeeded,
  stageTaskPayload,
  stageTaskProblems,
  LEAD_FLOW,
  LEAD_OPTIONAL_STAGES,
  OPPORTUNITY_FLOW,
  skippedStages,
  emailWebsiteProblem,
  isPersonalEmail,
  draftContent,
  emailWritingAction,
  toRecordContact,
  parseRecipients,
  companyFromEmail,
  newRecordProblems,
  CONTACT_EMAIL_INVALID,
  leadConvertChoice,
  CONVERT_ONE,
  CONVERT_ONE_AT_A_TIME,
  ASSISTANT_FILE_TYPES,
  ASSISTANT_ATTACH_HELP,
  homeDescription,
  demoDateMin,
  opportunityMovesForward,
  unfinishedStageTasks,
  ATTACHMENT_EXTENSIONS,
  ATTACHMENT_STAGES,
  ATTACHMENT_UPLOAD_STAGES,
  ATTACHMENT_TYPES_TEXT,
  ATTACHMENT_LEGACY_TEXT,
  PREVIEW_TYPES,
  LEAD_FIRST_NAME_REQUIRED,
  LINKEDIN_PROFILE_REQUIRED,
  SOURCE_DETAIL_MAX,
  SOURCE_DETAIL_REQUIRED,
  UPLOAD_SOURCE,
  leadFieldsRequired,
  leadFormProblems,
  webAddressProblem,
  CONTACT_FORM,
  OPPORTUNITY_CONTACT_FORM,
  contactAnswerFields,
  contactAutofillFields,
  contactProblems,
  NEW_LEAD_DEFAULT_SOURCE,
  sourceAfterLinkedInMatch,
} from "./domain.js";
import { BUSINESS_TIMEZONE, BUSINESS_TZ_LABEL, businessNow, formatBusiness, formatBusinessTime, fromBusinessInput, toBusinessInput } from "./businessTime.js";
import { attachedSummary, fileSize } from "./format.js";
import {
  BULK_LIMIT,
  chipText,
  clampPage,
  filterChips,
  filterText,
  leadSelectionActions,
  leadsEmptyMessage,
  pageSummary,
  selectionSummary,
  sortText,
  withoutFilter,
  isMyOpenTask,
  myOverdueTasks,
  OVERDUE_SHORTCUT_FILTERS,
  boardPages,
  boardQueryKey,
  columnRange,
  latestRequests,
  withColumnPage,
  LEAD_DATE_RANGES,
  dateRangeBounds,
  dateFilterOffered,
  defaultSortDirection,
} from "./listHelpers.js";
import { demoEvent, foldIcsLine, googleCalendarUrl, icsContent, icsText, outlookCalendarUrl } from "./calendarLinks.js";
import { addressProblem, draftForCopy, OUTLOOK_COMPOSE_URL, OUTLOOK_URL_LIMIT, outlookComposeUrl, outlookHandoff, splitAddresses } from "./outlookDraft.js";
import { DEFAULT_PHONE_COUNTRY, PHONE_COUNTRIES, PHONE_RECHECK_EVENT, PHONE_WITH_CODE_INVALID, phoneCountryLabel, phoneCountryOf, phoneFieldError, phoneProblem } from "./phone.js";

test("lead form sends the backend's fields (the form's own checks are in leadFormProblems)", () => {
  assert.deepEqual(
    leadPayload({
      last_name: " Smith ",
      company: " Example ",
      source: "Phone",
      owner_id: "3",
    }),
    {
      salutation: null,
      first_name: null,
      last_name: "Smith",
      company: "Example",
      title: null,
      industry: null,
      email: null,
      phone: null,
      linkedin_url: null,
      company_website: null,
      company_linkedin_url: null,
      annual_revenue: null,
      currency: "USD",
      employees: null,
      location: null,
      source: "Phone",
      source_detail: null,
      owner_id: 3,
    },
  );
  // Other: what the source is, trimmed; any other source sends no description (even if one was typed earlier)
  assert.equal(leadPayload({ last_name: "A", company: "B", source: "Other", source_detail: "  Trade fair 2026 " }).source_detail, "Trade fair 2026");
  assert.equal(leadPayload({ last_name: "A", company: "B", source: "Other", source_detail: "   " }).source_detail, null);
  assert.equal(leadPayload({ last_name: "A", company: "B", source: "LinkedIn", source_detail: "Trade fair" }).source_detail, null);
  assert.ok(!("welcome_email" in leadPayload({ last_name: "A", company: "B" }))); // leads are never emailed automatically
  const links = leadPayload({ last_name: "A", company: "B", linkedin_url: " linkedin.com/in/a ", employees: "250", annual_revenue: "" });
  assert.equal(links.linkedin_url, "linkedin.com/in/a"); // the backend adds https://
  assert.equal(links.employees, 250);
  assert.equal(links.annual_revenue, null);
  assert.ok(!LEAD_STAGES.includes("Won"));
  assert.ok(LEAD_SOURCES.includes("Social Media"));
  assert.deepEqual(LEAD_SOURCES, ["Website", "LinkedIn", "Referral", "Phone", "Email", "Event", "Social Media", "Other"]);
  assert.deepEqual(PRIORITIES, ["Low", "Normal", "High"]);
  assert.ok(LOST_REASONS.includes("No budget"));
});
test("task updates cannot silently change relationship or status", () => {
  const values = {
    title: " Follow up ",
    due_date: "2026-10-20T10:00",
    priority: "Normal",
    owner_id: "2",
    relatedType: "leads",
    relatedId: "7",
    status: "Open",
  };
  assert.equal(taskPayload(values).lead_id, 7);
  assert.equal(
    taskPayload({ ...values, relatedType: "general" }).lead_id,
    null,
  );
  const edit = taskPayload(values, true);
  assert.ok(!("lead_id" in edit));
  assert.ok(!("status" in edit));
  assert.ok(!("opportunity_id" in edit));
});
test("opportunity values preserve blank fields and zero as different values", () => {
  const payload = opportunityPayload({
    name: "Deal",
    expected_value: "0",
    probability: "20",
    owner_id: "1",
    expected_close_date: "",
  });
  assert.equal(payload.expected_value, 0);
  assert.equal(payload.expected_close_date, null);
  assert.equal(
    opportunityPayload({ name: "Deal", probability: "20", expected_value: "" })
      .expected_value,
    null,
  );
  assert.equal(money(null), "—");
  assert.equal(money(1234.5), "1,234.5");
});
test("server Auto-closed and Done tasks stay terminal and IDs match frontend routes", () => {
  const task = normalizeTask({
    id: 2,
    status: "Auto-closed",
    priority: "Normal",
    due_date: "2026-10-20T10:00:00",
    lead_id: 4,
    reminder_at: null,
  });
  assert.equal(task.id, "2");
  assert.equal(task.relatedId, "4");
  assert.equal(task.completed, true);
  assert.equal(task.status, "Auto-closed");
  assert.equal(task.due, "2026-10-20");
  assert.equal(
    normalizeTask({
      ...task,
      id: 3,
      status: "Open",
      lead_id: null,
      opportunity_id: 8,
    }).relatedType,
    "opportunities",
  );
});
test("detail normalization retains backend notes, history and contact information", () => {
  const raw = {
    leads: [
      { id: 1, name: "Jane Smith", company: "Example", stage: "Converted" },
    ],
    opportunities: [
      {
        id: 2,
        name: "Deal",
        stage: "Won",
        final_value: 500,
        expected_value: 400,
        lead_id: 1,
        primary_contact_id: 3,
      },
    ],
    tasks: [],
    contacts: [{ id: 3, email: "jane@example.test" }],
  };
  const data = normalizeWorkspace(raw, {
    collection: "leads",
    record: {
      ...raw.leads[0],
      notes: [{ id: 4, body: "A note" }],
      history: [
        {
          from_stage: "Demo",
          to_stage: "Converted",
          changed_at: "2026-10-20T10:00",
          changed_by_name: "Owner",
        },
      ],
    },
  });
  assert.equal(data.leads[0].notes[0].body, "A note");
  assert.match(data.leads[0].activity[0].text, /Demo → Converted/);
  assert.equal(data.opportunities[0].leadId, "1");
  assert.equal(data.opportunities[0].value, 500);
  assert.equal(data.opportunities[0].email, "jane@example.test");
});
test("dashboard uses backend home counts and includes overdue follow-ups", () => {
  const data = {
    tasks: [
      normalizeTask({ id: 1, status: "Open", due_date: "2026-10-01T10:00" }),
    ],
    home: {
      summary: { total_leads: 4, open_opportunities: 2, tasks_due_today: 0 },
      pipeline: [
        { stage: "New", total: 4 },
        { stage: "Opportunity", total: 2 },
        { stage: "Won", total: 1 },
        { stage: "Lost", total: 2 },
      ],
      won_vs_lost: [
        { outcome: "Won", deals: 1, value: 500 },
        { outcome: "Lost", deals: 2, value: 200 },
      ],
      todays_tasks: [{ id: 1, is_overdue: true }],
    },
  };
  const overview = salesOverview(data);
  assert.equal(overview.totalLeads, 4);
  assert.equal(overview.dueToday, 0);
  assert.equal(overview.todayTasks.length, 1);
  assert.equal(overview.activeCount, 6);
  assert.equal(overview.winRate, 33);
  assert.equal(overview.wonValue, 500);
  assert.equal(salesOverview({ tasks: [], home: null }).wonCount, 0);
});
test("lifecycle actions call dedicated backend endpoints", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ id: 4 }), { status: 200 });
  });
  await api.convert("4", { note: "Budget approved", expected_value: 200 });
  await api.won("6", { final_value: 225, note: "Contract signed" });
  await api.completeTask("8");
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method]),
    [
      ["/api/leads/4/convert", "POST"],
      ["/api/opportunities/6/won", "POST"],
      ["/api/tasks/8/complete", "PUT"],
    ],
  );
  assert.equal(JSON.parse(calls[0].options.body).expected_value, 200);
  assert.equal(JSON.parse(calls[0].options.body).note, "Budget approved");
  assert.equal(JSON.parse(calls[1].options.body).note, "Contract signed");
});
test("every stage change popup has a required note; creating and editing records don't", () => {
  assert.equal(stageNoteField("stage"), "note"); // path bar, Mark as Complete, Kanban
  assert.equal(stageNoteField("convert"), "note");
  assert.equal(stageNoteField("won"), "note"); // the Closing Note
  assert.equal(stageNoteField("lost"), "lost_notes"); // the Lost Notes (the Lost Reason stays required too)
  assert.equal(stageNoteField("cancelDemo", "nurturing"), "reason"); // the lead goes back to Nurturing
  assert.equal(stageNoteField("cancelDemo", "reschedule"), null); // the lead stays at Demo
  for (const type of ["lead", "opportunity", "task", "account", "contact", "note", "transfer", "delete"])
    assert.equal(stageNoteField(type), null);
  assert.equal(STAGE_NOTE_REQUIRED, "Enter a note to change the stage.");
});
test("the Leads board has seven columns in order; Converted, Unqualified and Lost are closed; the list view decides which can fill", () => {
  const all = leadBoardColumns("all", null);
  assert.deepEqual(all.map((c) => c.stage), ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"]);
  assert.deepEqual(all.filter((c) => c.closed).map((c) => c.stage), ["Unqualified", "Converted", "Lost"]);
  assert.ok(all.every((c) => c.excluded === ""));
  const excluded = (view, stage) => leadBoardColumns(view, stage).filter((c) => c.excluded).map((c) => c.stage);
  const open = ["New", "Nurturing", "Revisit", "Demo"];
  assert.deepEqual(excluded("all_open"), ["Unqualified", "Converted", "Lost"]);
  assert.deepEqual(excluded("my_open"), ["Unqualified", "Converted", "Lost"]);
  assert.deepEqual(excluded("converted"), ["Unqualified", ...open, "Lost"]);
  assert.deepEqual(excluded("lost"), ["Unqualified", ...open, "Converted"]);
  assert.deepEqual(excluded("unqualified"), [...open, "Converted", "Lost"]);
  assert.deepEqual(excluded("revisit_due"), ["Unqualified", "New", "Nurturing", "Demo", "Converted", "Lost"]);
  assert.deepEqual(excluded("uploaded"), []);
  assert.deepEqual(excluded("all", "Demo"), ["Unqualified", "New", "Nurturing", "Revisit", "Converted", "Lost"]); // the Lead Status filter
  assert.equal(leadBoardColumns("all_open", "Demo").find((c) => c.stage === "New").excluded, "Hidden by the Lead Status filter");
  assert.equal(leadBoardColumns("all_open", null).find((c) => c.stage === "Lost").excluded, "Not in this list view");
});
test("stage order: skipped stages must be confirmed, Revisit is optional, going back skips nothing", () => {
  assert.deepEqual(skippedStages(LEAD_FLOW, "New", "Demo", LEAD_OPTIONAL_STAGES), ["Nurturing"]);
  assert.deepEqual(skippedStages(LEAD_FLOW, "Nurturing", "Demo", LEAD_OPTIONAL_STAGES), []); // Revisit may be passed over
  assert.deepEqual(skippedStages(LEAD_FLOW, "New", LEAD_FLOW.length, LEAD_OPTIONAL_STAGES), ["Nurturing", "Demo"]);
  assert.deepEqual(skippedStages(LEAD_FLOW, "Demo", "New", LEAD_OPTIONAL_STAGES), []);
  assert.deepEqual(skippedStages(OPPORTUNITY_FLOW, "Opportunity", "Proposal"), ["Discovery"]);
  assert.deepEqual(skippedStages(OPPORTUNITY_FLOW, "Opportunity", OPPORTUNITY_FLOW.length), ["Discovery", "Proposal"]);
  assert.deepEqual(skippedStages(OPPORTUNITY_FLOW, "Proposal", OPPORTUNITY_FLOW.length), []);
});
test("a lead card opens the existing popups and only for moves the lead page allows", () => {
  const lead = { id: 7, stage: "Nurturing" };
  const both = { canEdit: true, canConvert: true };
  assert.deepEqual(leadStageAction(lead, "Demo", both), { type: "stage", collection: "leads", record: lead, stage: "Demo" });
  assert.deepEqual(leadStageAction(lead, "New", both), { type: "stage", collection: "leads", record: lead, stage: "New" }); // back
  assert.deepEqual(leadStageAction(lead, "Converted", both), { type: "convert", record: lead });
  assert.deepEqual(leadStageAction(lead, "Lost", both), { type: "lost", collection: "leads", record: lead });
  assert.equal(leadStageAction(lead, "Nurturing", both), null); // the same column does nothing
  assert.equal(leadStageAction(lead, "Demo", { canEdit: false, canConvert: false }), null); // view-only
  assert.equal(leadStageAction(lead, "Converted", { canEdit: true, canConvert: false }), null); // e.g. an Admin
  assert.deepEqual(leadStageAction(lead, "Lost", { canEdit: true, canConvert: false }).type, "lost");
  for (const closed of ["Converted", "Lost"])
    for (const to of ["New", "Nurturing", "Demo", "Converted", "Lost"])
      assert.equal(leadStageAction({ id: 8, stage: closed }, to, both), null); // closed leads don't move
  assert.equal(leadStageAction(lead, "Won", both), null);
  assert.equal(leadStageAction(null, "Demo", both), null);
});
test("Convert's note is the Conversion Comment, with its own message; other popups keep theirs", () => {
  assert.equal(stageNoteField("convert"), "note"); // the same field the backend reads
  assert.equal(CONVERSION_COMMENT_REQUIRED, "Enter a conversion comment.");
  assert.equal(stageNoteMessage("convert"), CONVERSION_COMMENT_REQUIRED);
  for (const type of ["stage", "won", "lost", "cancelDemo"]) assert.equal(stageNoteMessage(type), STAGE_NOTE_REQUIRED);
});
test("every stage change but Lost needs a New Task with a subject and a due date", () => {
  for (const type of ["stage", "convert", "won"]) assert.equal(stageTaskNeeded(type), true);
  assert.equal(stageTaskNeeded("cancelDemo", "nurturing"), true); // back to Nurturing is a stage change
  assert.equal(stageTaskNeeded("cancelDemo", "reschedule"), false); // the lead stays at Demo
  for (const type of ["lost", "lead", "task", "note", "transfer", "opportunity"]) assert.equal(stageTaskNeeded(type), false);
  assert.deepEqual(stageTaskProblems({}), { task_title: TASK_SUBJECT_REQUIRED, task_due_date: TASK_DUE_REQUIRED });
  assert.deepEqual(stageTaskProblems({ task_title: "   ", task_due_date: "2030-01-15T10:00" }), { task_title: TASK_SUBJECT_REQUIRED });
  assert.deepEqual(stageTaskProblems({ task_title: "Call", task_due_date: "2030-01-15T10:00" }), {});
});
test("the New Task is sent as the task form sends it: trimmed subject, optional fields left empty", () => {
  assert.deepEqual(
    stageTaskPayload({ task_title: "  Call the buyer ", task_due_date: "2030-01-15T10:00", task_priority: "High",
                       task_reminder_at: "", task_description: "  ", task_owner_id: "3" }),
    { title: "Call the buyer", due_date: "2030-01-15T10:00", priority: "High", reminder_at: null, description: null, owner_id: 3 },
  );
  assert.deepEqual(stageTaskPayload({ task_title: "Call", task_due_date: "2030-01-15T10:00" }), {
    title: "Call", due_date: "2030-01-15T10:00", priority: "Normal", reminder_at: null, description: null, owner_id: null,
  }); // no assignee chosen: the server gives it to the record's owner
});
test("the popups with files send the New Task as one JSON form field", async (t) => {
  const forms = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    forms.push(options.body);
    return new Response(JSON.stringify({ id: 1 }), { status: 200 });
  });
  const task = { title: "Handover", due_date: "2030-01-20T10:00", priority: "Normal", reminder_at: null, description: null, owner_id: null };
  const file = new File(["%PDF-1.4"], "quote.pdf", { type: "application/pdf" });
  await api.stageWithFiles("5", { stage: "Proposal", note: "Sent", task }, [file]);
  await api.wonWithFiles("5", { final_value: 10, note: "Signed", task }, [file]);
  for (const form of forms) assert.deepEqual(JSON.parse(form.get("task")), task);
});
test("a blank stage note is caught; a real one keeps its formatting inside", () => {
  for (const blank of [undefined, null, "", "   ", "\n\t \n", 5]) assert.equal(stageNote(blank), "");
  assert.equal(stageNote("  Called Priya.\n  - budget ok\n\n"), "Called Priya.\n  - budget ok");
});
test("API validation failures reach the form as readable errors", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          detail: [{ loc: ["body", "last_name"], msg: "Field required" }],
        }),
        { status: 422 },
      ),
  );
  await assert.rejects(apiRequest("/leads"), /last_name: Field required/);
});
test("failed network requests never fall back to browser demo records", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("network unavailable");
  });
  await assert.rejects(apiRequest("/leads"), /Cannot reach the backend/);
});
test("attachment files are checked before upload (the backend checks again)", () => {
  const file = (name, size) => ({ name, size });
  assert.equal(ATTACHMENT_MAX_BYTES, 20 * 1024 * 1024);
  for (const name of ["a.pdf", "b.DOCX", "c.jpg", "d.JPEG", "e.png", "f.pptx", "g.XLSX"])
    assert.equal(attachmentProblem(file(name, 10)), "");
  assert.equal(attachmentProblem(file("max.pdf", ATTACHMENT_MAX_BYTES)), "");
  assert.match(attachmentProblem(file("big.pdf", ATTACHMENT_MAX_BYTES + 1)), /larger than 20 MB/);
  assert.match(attachmentProblem(file("big.pptx", ATTACHMENT_MAX_BYTES + 1)), /larger than 20 MB/);
  assert.match(attachmentProblem(file("empty.png", 0)), /is empty/);
  assert.match(attachmentProblem(file("empty.xlsx", 0)), /is empty/);
  assert.match(attachmentProblem(file("old.doc", 10)), /\.doc.*save it as \.docx/i);
  assert.match(attachmentProblem(file("old.ppt", 10)), /old PowerPoint files \(\.ppt\).*save it as \.pptx/i);
  assert.match(attachmentProblem(file("old.XLS", 10)), /old Excel files \(\.xls\).*save it as \.xlsx/i);
  for (const name of ["notes.txt", "page.html", "archive.zip", "pdf", ".pdf", "macro.docm", "macro.xlsm", "show.ppsx"])
    assert.match(attachmentProblem(file(name, 10)), /only PDF, Word \(\.docx\), PowerPoint \(\.pptx\), Excel \(\.xlsx\), JPG and PNG/);
});
test("attachments use their own endpoints and send the login only in a header", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return url.endsWith("/file") || url.endsWith("?download=true")
      ? new Response(new Uint8Array([37, 80, 68, 70]), { status: 200, headers: { "Content-Type": "application/pdf" } })
      : new Response(JSON.stringify([]), { status: 200 });
  });
  setToken("secret-token");
  try {
    await api.attachments("4");
    const blob = await api.attachmentFile("4", "9");
    await api.attachmentFile("4", "9", true);
    await api.uploadAttachment("4", new File([new Uint8Array([1])], "quote.pdf", { type: "application/pdf" }));
    await api.deleteAttachment("4", "9");
    assert.equal(blob.type, "application/pdf");
    assert.equal(blob.size, 4);
  } finally {
    setToken("");
  }
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method || "GET"]),
    [
      ["/api/opportunities/4/attachments", "GET"],
      ["/api/opportunities/4/attachments/9/file", "GET"],
      ["/api/opportunities/4/attachments/9/file?download=true", "GET"],
      ["/api/opportunities/4/attachments", "POST"],
      ["/api/opportunities/4/attachments/9", "DELETE"],
    ],
  );
  for (const call of calls) {
    assert.ok(!call.url.includes("secret-token")); // never in the address
    assert.equal(call.options.headers.Authorization, "Bearer secret-token");
  }
  const form = calls[3].options.body;
  assert.equal(form.getAll("file").length, 1); // one file per request
  assert.equal(form.get("file").name, "quote.pdf");
  assert.equal(calls[3].options.headers["Content-Type"], undefined); // the browser sets the multipart boundary
});
test("attachment errors reach the card as readable messages", async (t) => {
  let reply;
  t.mock.method(globalThis, "fetch", async () => reply());
  reply = () => new Response("<html>Request Entity Too Large</html>", { status: 413 });
  await assert.rejects(api.uploadAttachment("4", new File(["x"], "big.pdf")), /larger than 20 MB/);
  reply = () => new Response(JSON.stringify({ detail: "logo.png is named as a PNG image but is really a PDF." }), { status: 415 });
  await assert.rejects(api.uploadAttachment("4", new File(["x"], "logo.png")), /really a PDF/);
  reply = () => new Response(JSON.stringify({ detail: "Attachment 9 not found" }), { status: 404 });
  await assert.rejects(api.attachmentFile("4", "9"), /Attachment 9 not found/);
  reply = () => {
    throw new TypeError("network unavailable");
  };
  await assert.rejects(api.attachmentFile("4", "9"), /Cannot reach the backend/);
  await assert.rejects(api.uploadAttachment("4", new File(["x"], "a.pdf")), /Cannot reach the backend/);
  // an expired login sends the app back to the login page
  const events = new EventTarget();
  let loggedOut = 0;
  events.addEventListener("crm-logout", () => loggedOut++);
  globalThis.window = events;
  setToken("old-token");
  try {
    reply = () => new Response(JSON.stringify({ detail: "Please log in again" }), { status: 401 });
    await assert.rejects(api.attachmentFile("4", "9"), /Please log in again/);
    await assert.rejects(api.attachments("4"), /Please log in again/);
  } finally {
    setToken("");
    delete globalThis.window;
  }
  assert.equal(loggedOut, 2);
});
test("email uploads keep their own messages", async (t) => {
  let status;
  t.mock.method(globalThis, "fetch", async () => new Response("", { status }));
  status = 413;
  await assert.rejects(api.sendEmail(new FormData()), /The attachments are too large\./);
  status = 500;
  await assert.rejects(api.sendEmail(new FormData()), /The email could not be sent\./);
});
test("files chosen in the Change Stage popup are checked, kept once and limited", () => {
  const file = (name, size, lastModified = 1) => ({ name, size, lastModified });
  const proposal = file("proposal.pdf", 10);
  let picked = pickStageFiles([], [proposal, file("old.doc", 10), file("empty.png", 0), file("big.pdf", ATTACHMENT_MAX_BYTES + 1)]);
  assert.deepEqual(picked.files, [proposal]);
  assert.equal(picked.problems.length, 3);
  assert.match(picked.problems.join("\n"), /\.doc[\s\S]*is empty[\s\S]*larger than 20 MB/);
  // the same file chosen again is not added twice; another file with the same name is
  picked = pickStageFiles(picked.files, [proposal, file("proposal.pdf", 10, 2)]);
  assert.equal(picked.files.length, 2);
  assert.deepEqual(picked.problems, []);
  assert.equal(STAGE_FILES_MAX, 5);
  picked = pickStageFiles(picked.files, ["a.png", "b.jpg", "c.jpeg", "d.docx"].map((n) => file(n, 5)));
  assert.equal(picked.files.length, 5);
  assert.match(picked.problems[0], /^d\.docx: up to 5 files/);
  assert.deepEqual(
    ["a.PDF", "b.docx", "c.JPG", "d.jpeg", "e.png", "f.doc", "g.txt", "pdf"].map(attachmentType),
    ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/jpeg",
     "image/jpeg", "image/png", "", "", ""],
  );
});
test("a stage change with files is one request, sent with the login header", async (t) => {
  const calls = [];
  let reply = () => new Response(JSON.stringify({ id: 6, stage: "Proposal" }), { status: 200 });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return reply();
  });
  const files = [new File(["%PDF-"], "quote.pdf"), new File(["png"], "chart.png")];
  setToken("secret-token");
  try {
    await api.stageWithFiles("6", { stage: "Proposal", note: "Sent the quote" }, files);
    await api.stageWithFiles("6", { stage: "Opportunity", note: null }, files.slice(0, 1));
    await api.stage("opportunities", "6", { stage: "Proposal", note: null }); // without files: unchanged JSON call
  } finally {
    setToken("");
  }
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method]),
    [
      ["/api/opportunities/6/stage-with-files", "POST"],
      ["/api/opportunities/6/stage-with-files", "POST"],
      ["/api/opportunities/6/stage", "PUT"],
    ],
  );
  const form = calls[0].options.body;
  assert.equal(form.get("stage"), "Proposal");
  assert.equal(form.get("note"), "Sent the quote");
  assert.deepEqual(form.getAll("files").map((f) => f.name), ["quote.pdf", "chart.png"]);
  assert.equal(calls[1].options.body.get("note"), null); // an empty note is not sent
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret-token");
  assert.ok(!calls[0].url.includes("secret-token"));
  assert.deepEqual(JSON.parse(calls[2].options.body), { stage: "Proposal", note: null });

  reply = () => new Response(JSON.stringify({ detail: "chart.png is named as a PNG image but is really a PDF." }), { status: 415 });
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /chart\.png .* really a PDF/);
  reply = () => new Response("<html>Request Entity Too Large</html>", { status: 413 });
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /Each file can be up to 20 MB/);
  reply = () => new Response("", { status: 500 });
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /The stage could not be changed/);
  reply = () => {
    throw new TypeError("network unavailable");
  };
  await assert.rejects(api.stageWithFiles("6", { stage: "Proposal" }, files), /Cannot reach the backend/);
});
test("Mark as Won with files is one request with the amount, note, email choice and files", async (t) => {
  const calls = [];
  let reply = () => new Response(JSON.stringify({ id: 6, stage: "Won" }), { status: 200 });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return reply();
  });
  const files = [new File(["%PDF-"], "signed.pdf"), new File(["png"], "photo.png")];
  setToken("secret-token");
  try {
    await api.wonWithFiles("6", { final_value: 1500.5, note: "Signed", completed_stages: ["Proposal"],
                                  completed_note: "Sent by email" }, files);
    await api.wonWithFiles("6", { final_value: 0, note: null }, files.slice(0, 1));
    await api.won("6", { final_value: null, note: null }); // without files: unchanged JSON call
  } finally {
    setToken("");
  }
  assert.deepEqual(
    calls.map((c) => [c.url, c.options.method]),
    [
      ["/api/opportunities/6/won-with-files", "POST"],
      ["/api/opportunities/6/won-with-files", "POST"],
      ["/api/opportunities/6/won", "POST"],
    ],
  );
  const form = calls[0].options.body;
  assert.deepEqual(
    [...form.entries()].map(([name, value]) => [name, typeof value === "string" ? value : value.name]),
    [["final_value", "1500.5"], ["note", "Signed"], ["completed_stages", "Proposal"],
     ["completed_note", "Sent by email"], ["files", "signed.pdf"], ["files", "photo.png"]],
  );
  const second = calls[1].options.body;
  assert.equal(second.get("final_value"), "0"); // 0 is an amount, not "empty"
  assert.equal(second.get("notify_customer"), null); // customers are never emailed automatically
  assert.equal(second.get("note"), null);
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret-token");
  assert.ok(!calls[0].url.includes("secret-token"));
  assert.deepEqual(JSON.parse(calls[2].options.body), { final_value: null, note: null });

  reply = () => new Response(JSON.stringify({ detail: "final_value: Input should be greater than or equal to 0" }), { status: 422 });
  await assert.rejects(api.wonWithFiles("6", { final_value: -5 }, files), /final_value: Input should be greater/);
  reply = () => new Response("<html>Request Entity Too Large</html>", { status: 413 });
  await assert.rejects(api.wonWithFiles("6", {}, files), /Each file can be up to 20 MB/);
  reply = () => new Response("", { status: 500 });
  await assert.rejects(api.wonWithFiles("6", {}, files), /could not be marked as Won/);
});
test("only LinkedIn person profiles are looked up, in one form", () => {
  const url = (value) => linkedInProfileUrl(value).url;
  assert.equal(url("https://www.linkedin.com/in/Jane-Doe-123/"), "https://linkedin.com/in/jane-doe-123");
  assert.equal(url("  linkedin.com/in/jane-doe-123?trk=public#about "), "https://linkedin.com/in/jane-doe-123");
  assert.equal(url("http://uk.linkedin.com/in/jane_doe"), "https://linkedin.com/in/jane_doe");
  assert.equal(url("https://www.linkedin.com/in/j%C3%BCrgen-m"), "https://linkedin.com/in/j%C3%BCrgen-m");
  for (const bad of [
    "",
    "https://www.linkedin.com/company/acme",
    "https://www.linkedin.com/school/some-school",
    "https://www.linkedin.com/in/",
    "https://www.linkedin.com/in/jane/details/experience",
    "https://www.linkedin.com/sales/lead/abc123",
    "https://linkedin.com.example.test/in/jane-doe",
    "https://evil-linkedin.com/in/jane-doe",
    "https://www.linkedin.com@example.test/in/jane-doe",
    "https://www.linkedin.com:443/in/jane-doe",
    "javascript:alert(1)",
    "ftp://linkedin.com/in/jane-doe",
    "https://lnkd.in/abc123",
    "https://www.linkedin.com/in/jane doe",
    "https://www.linkedin.com/in/ab",
    `https://www.linkedin.com/in/${"a".repeat(300)}`,
  ])
    assert.ok(linkedInProfileUrl(bad).error, `should refuse ${bad}`);
});
test("Apollo autofill fills empty fields and never overwrites what the user typed", () => {
  const empty = { first_name: "", last_name: "", company: "", title: "", industry: "", email: "", phone: "" };
  const jane = { first_name: "Jane", last_name: "Doe", company: "Synthetic Co", title: "CTO" };
  // a first profile: empty fields are filled; the user's own company stays
  let plan = autofillPlan({ ...empty, company: "Typed Co" }, {}, jane);
  assert.deepEqual(plan.set, { first_name: "Jane", last_name: "Doe", title: "CTO" });
  assert.deepEqual(plan.filled, ["first_name", "last_name", "title"]);
  assert.deepEqual(plan.kept, ["company"]);
  // the user then edits the title; a second profile replaces only the untouched autofill
  const form = { ...empty, first_name: "Jane", last_name: "Doe", company: "Typed Co", title: "Chief Technology Officer" };
  plan = autofillPlan(form, plan.autofilled, { first_name: "Sam", last_name: "Lee", title: "VP Sales", email: "sam@example.test" });
  assert.deepEqual(plan.set, { first_name: "Sam", last_name: "Lee", email: "sam@example.test" });
  assert.deepEqual(plan.kept, ["title"]);
  // a profile without a last name removes the old profile's untouched last name
  plan = autofillPlan({ ...form, first_name: "Sam", last_name: "Lee", email: "sam@example.test" }, plan.autofilled, { first_name: "Sam" });
  assert.deepEqual(plan.set, { last_name: "", email: "" });
  // clearing the address ({}) removes untouched autofill only
  plan = autofillPlan({ ...form, first_name: "Sam" }, plan.autofilled, {});
  assert.deepEqual(plan.set, { first_name: "" });
  assert.deepEqual(plan.autofilled, {});
});
test("company details follow the same rules: empty fields only, manual entries kept, untouched autofill replaced", () => {
  assert.deepEqual(
    Object.entries(AUTOFILL_FIELDS).slice(-2),
    [["company_website", "Company Website"], ["company_linkedin_url", "Company LinkedIn URL"]],
  );
  const synthetic = { company: "Synthetic Co", industry: "Software", company_website: "https://synthetic-co.example",
                      company_linkedin_url: "https://www.linkedin.com/company/synthetic-co" };
  // the user typed a website before pasting: it stays; the other company details are filled
  let plan = autofillPlan({ company_website: "https://typed.example" }, {}, synthetic);
  assert.deepEqual(plan.set, { company: "Synthetic Co", industry: "Software",
                               company_linkedin_url: "https://www.linkedin.com/company/synthetic-co" });
  assert.deepEqual(plan.kept, ["company_website"]);
  // the user edits the company name; another profile (another employer, no LinkedIn page) replaces only untouched values
  const form = { company: "Synthetic Company Ltd", industry: "Software", company_website: "https://typed.example",
                 company_linkedin_url: "https://www.linkedin.com/company/synthetic-co" };
  plan = autofillPlan(form, plan.autofilled, { company: "Other Co", industry: "Retail", company_website: "https://other.example" });
  assert.deepEqual(plan.set, { industry: "Retail", company_linkedin_url: "" }); // the old page doesn't belong to Other Co
  assert.deepEqual(plan.kept, ["company", "company_website"]);
  // clearing the profile address removes only the untouched autofill
  plan = autofillPlan({ ...form, industry: "Retail", company_linkedin_url: "" }, plan.autofilled, {});
  assert.deepEqual(plan.set, { industry: "" });
  assert.deepEqual(plan.autofilled, {});
});
test("switching profiles never mixes two people's details, and the user's own edits stay", () => {
  const empty = Object.fromEntries(Object.keys(AUTOFILL_FIELDS).map((name) => [name, ""]));
  const ana = { first_name: "Ana Maria", last_name: "Okafor", company: "Synthetic Co", email: "ana.okafor@synthetic-co.example" };
  const mary = { first_name: "Mary Jo", last_name: "Lindqvist", company: "Other Co" }; // no usable email from Apollo
  let plan = autofillPlan(empty, {}, ana);
  assert.deepEqual(plan.set, ana); // the compound first name and the surname exactly as given
  // the user corrects the surname, then pastes another profile
  const form = { ...empty, ...ana, last_name: "Okafor-Typed" };
  plan = autofillPlan(form, plan.autofilled, mary);
  assert.deepEqual(plan.set, { first_name: "Mary Jo", company: "Other Co", email: "" }); // Ana's email doesn't stay
  assert.deepEqual(plan.kept, ["last_name"]);
  assert.deepEqual(plan.autofilled, { first_name: "Mary Jo", company: "Other Co" });
  // an unmatched answer ({}) removes Mary's untouched values; the user's surname stays
  plan = autofillPlan({ ...form, first_name: "Mary Jo", company: "Other Co", email: "" }, plan.autofilled, {});
  assert.deepEqual(plan.set, { first_name: "", company: "" });
});
test("a match is described as Apollo's data, never as a confirmed identity or email owner", () => {
  const matched = "Apollo returned a matching profile URL. Review all details before saving.";
  const emailNote = "Email verification status is provided by Apollo; ownership has not been independently confirmed by this CRM.";
  let summary = autofillSummary({ filled: ["first_name", "last_name", "email"], kept: ["company"] });
  assert.equal(summary.text, `${matched} Filled by Apollo: First Name, Last Name, Email. Kept your entries for Company.`);
  assert.equal(summary.email, emailNote);
  assert.doesNotMatch(summary.text, /verified/i);
  // no note when Apollo's email isn't in the form (none usable, or the user's own entry was kept)
  summary = autofillSummary({ filled: ["first_name"], kept: ["email"] });
  assert.equal(summary.text, `${matched} Filled by Apollo: First Name. Kept your entries for Email.`);
  assert.equal(summary.email, "");
  summary = autofillSummary({ filled: [], kept: [] });
  assert.equal(summary.text, `${matched} Nothing was filled: the fields already had your entries.`);
  assert.equal(summary.email, "");
});
test("LinkedIn autofill calls only the backend, with the login header, and keeps the error status", async (t) => {
  const calls = [];
  let reply = () => new Response(JSON.stringify({ enabled: true }), { status: 200 });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return reply();
  });
  setToken("secret-token");
  try {
    await api.leadEnrichmentStatus();
    reply = () => new Response(JSON.stringify({ status: "no_match", linkedin_url: "x", fields: {} }), { status: 200 });
    await api.enrichLead("https://www.linkedin.com/in/jane-doe");
    reply = () => new Response(JSON.stringify({ detail: "LinkedIn autofill isn't set up on this server." }), { status: 503 });
    await assert.rejects(api.enrichLead("https://www.linkedin.com/in/jane-doe"), (err) => err.status === 503 && /isn't set up/.test(err.message));
    reply = () => {
      throw new TypeError("network unavailable");
    };
    await assert.rejects(api.enrichLead("https://www.linkedin.com/in/jane-doe"), (err) => err.status === 0 && /Cannot reach the backend/.test(err.message));
  } finally {
    setToken("");
  }
  assert.deepEqual(calls.map((c) => [c.url, c.options.method || "GET"]), [
    ["/api/leads/enrichment", "GET"],
    ["/api/leads/enrichment", "POST"],
    ["/api/leads/enrichment", "POST"],
    ["/api/leads/enrichment", "POST"],
  ]);
  assert.deepEqual(JSON.parse(calls[1].options.body), { linkedin_url: "https://www.linkedin.com/in/jane-doe" });
  for (const call of calls) {
    assert.ok(call.url.startsWith("/api/") && !call.url.includes("apollo") && !call.url.includes("secret-token"));
    assert.equal(call.options.headers.Authorization, "Bearer secret-token");
  }
});

test("a lead's email must use the company website's domain", () => {
  assert.equal(emailWebsiteProblem("asha@acme.com", "https://www.acme.com/about"), null);
  assert.equal(emailWebsiteProblem("asha@mail.acme.com", "acme.com"), null);
  assert.equal(emailWebsiteProblem("asha@acme.com", "shop.acme.com"), null);
  assert.equal(emailWebsiteProblem("", "acme.com"), null); // nothing to compare
  assert.equal(emailWebsiteProblem("asha@acme.com", ""), null);
  assert.match(emailWebsiteProblem("asha@gmail.com", "acme.com"), /Personal emails \(@gmail\.com\) aren't allowed/);
  assert.match(emailWebsiteProblem("asha@acme-group.com", "acme.com"), /@acme-group\.com doesn't match the company website \(acme\.com\)\. If this email is correct, click Save anyway/);
  assert.equal(isPersonalEmail("a@yahoo.co.in"), true);
  assert.equal(isPersonalEmail("a@srsconsultinginc.com"), false);
  assert.match(emailWebsiteProblem("asha@notacme.com", "acme.com"), /doesn't match/);
});

test("New Opportunity needs the opening note and the first task, like Convert", () => {
  assert.equal(stageNoteField("newOpportunity"), "note");
  assert.equal(stageTaskNeeded("newOpportunity"), true);
});

test("New Campaign's To field: pasted addresses, with names kept", () => {
  assert.deepEqual(parseRecipients("asha@acme.com, Ravi Kumar <ravi@bluebird.io>; a@x.com b@y.com\nnotanemail"), [
    { email: "asha@acme.com" },
    { email: "ravi@bluebird.io", name: "Ravi Kumar" },
    { email: "a@x.com" },
    { email: "b@y.com" },
    { email: "notanemail" },
  ]);
  assert.deepEqual(parseRecipients('"Meera Iyer" <meera@lumen.com>'), [{ email: "meera@lumen.com", name: "Meera Iyer" }]);
  assert.equal(companyFromEmail("asha@acme-retail.com"), "Acme Retail");
  assert.equal(companyFromEmail("asha@gmail.com"), "");
});

test("AI drafting: a greeting and signature alone is not a draft to refine", () => {
  const sign = ["Ravi Kumar", "ravi@crm.test"];
  const starter = "Hi Jack,\n\n\n\nBest regards,\nRavi Kumar\nravi@crm.test"; // what New Email starts with
  assert.equal(draftContent(starter, ...sign), "");
  assert.equal(draftContent("", ...sign), "");
  assert.equal(draftContent("Hello,\r\n\r\nKind regards,\r\nRavi Kumar", ...sign), "");
  assert.equal(draftContent("Dear Ana Maria Okafor,\n\nSincerely,", ...sign), "");
  assert.equal(draftContent("Hi Jack, let's reconnect.", ...sign), "Hi Jack, let's reconnect."); // words after the greeting
  assert.equal(draftContent("Hi Jack,\n\nThe proposal covers 25 seats.\n\nBest regards,\nRavi Kumar\nravi@crm.test", ...sign),
    "The proposal covers 25 seats.");
  assert.equal(draftContent("Could you share your availability?", ...sign), "Could you share your availability?");
});
test("AI drafting greets by name only while To still addresses the record's contact", () => {
  assert.equal(toRecordContact("jack@bluebird.example", "jack@bluebird.example"), true);
  assert.equal(toRecordContact(" Jack@Bluebird.example ; ops@bluebird.example", "jack@bluebird.example"), true);
  assert.equal(toRecordContact("", "jack@bluebird.example"), true); // not chosen yet: the record's contact
  assert.equal(toRecordContact("mary.jo@other.example", "jack@bluebird.example"), false);
  assert.equal(toRecordContact("mary.jo@other.example", ""), false);
});

test("New Account needs Account Name and Industry; no Phone; Website and Company LinkedIn URL optional but checked", () => {
  const ok = { name: "Synthetic Harbor Co", industry: "Logistics" };
  assert.deepEqual(newRecordProblems("account", ok), {}); // saved without a phone
  assert.deepEqual(Object.keys(newRecordProblems("account", { ...ok, industry: "   " })), ["industry"]);
  assert.deepEqual(Object.keys(newRecordProblems("account", { name: " " })), ["name", "industry"]);
  assert.deepEqual(newRecordProblems("account", { ...ok, website: "", linkedin_url: "" }), {});
  assert.deepEqual(newRecordProblems("account", { ...ok, website: "harbor.example", linkedin_url: "linkedin.com/company/harbor" }), {});
  assert.equal(newRecordProblems("account", { ...ok, website: "harbor" }).website, "Enter a valid web address");
  assert.equal(newRecordProblems("account", { ...ok, linkedin_url: "https://harbor.example/about" }).linkedin_url,
    "Enter a LinkedIn address (linkedin.com/...)");
});
test("New Contact needs First Name, Last Name, Email and the account; Phone and LinkedIn are optional but checked", () => {
  const ok = { first_name: "Ana", last_name: "Okafor", account_id: "4", email: "ana.okafor@harbor.example" };
  assert.deepEqual(newRecordProblems("contact", ok), {}); // no phone: fine
  assert.deepEqual(newRecordProblems("contact", { ...ok, phone: "   ", phone_country: "IN" }), {});
  assert.deepEqual(Object.keys(newRecordProblems("contact", { account_id: "4" })), ["first_name", "last_name", "email"]);
  assert.deepEqual(Object.keys(newRecordProblems("contact", { ...ok, first_name: " ", last_name: "\t", email: " " })),
    ["first_name", "last_name", "email"]);
  assert.equal(newRecordProblems("contact", { ...ok, first_name: "" }).first_name, "Enter the contact's first name.");
  assert.equal(newRecordProblems("contact", { ...ok, email: "" }).email, "Enter the contact's email address.");
  for (const email of ["ana.okafor", "ana@harbor", "@harbor.example", "ana okafor@harbor.example", "a@b.example, c@d.example"])
    assert.equal(newRecordProblems("contact", { ...ok, email }).email, CONTACT_EMAIL_INVALID, email);
  assert.deepEqual(Object.keys(newRecordProblems("contact", { ...ok, account_id: "" })), ["account_id"]);
  // phone: checked for the chosen country (India by default)
  assert.deepEqual(newRecordProblems("contact", { ...ok, phone: "98765 43210", phone_country: "IN" }), {});
  assert.equal(newRecordProblems("contact", { ...ok, phone: "12345", phone_country: "IN" }).phone,
    "Enter a valid phone number for India (+91).");
  // LinkedIn: a person's profile, when given
  assert.deepEqual(newRecordProblems("contact", { ...ok, linkedin_url: "linkedin.com/in/ana-okafor" }), {});
  assert.match(newRecordProblems("contact", { ...ok, linkedin_url: "https://www.linkedin.com/company/harbor" }).linkedin_url,
    /person's profile address/);
  assert.deepEqual(newRecordProblems("lead", {}), {}); // other forms keep their own checks
});
test("Convert to Opportunity: exactly one open lead the user may convert", () => {
  const mine = { id: 7, name: "Synthetic Lead", stage: "Demo", owner_id: 2 };
  const salesperson = () => ({ canEdit: true, canCreateSales: true });
  const open = leadConvertChoice([mine], salesperson);
  assert.deepEqual(open.action, { type: "convert", record: mine }); // the existing Convert popup, nothing converted yet
  assert.equal(open.reason, undefined);
  for (const stage of ["New", "Nurturing", "Revisit"]) assert.ok(leadConvertChoice([{ ...mine, stage }], salesperson).action);
  assert.equal(leadConvertChoice([], salesperson).reason, CONVERT_ONE);
  assert.equal(leadConvertChoice([undefined], salesperson).reason, CONVERT_ONE); // ticked but not loaded
  for (const stage of ["Converted", "Lost", "Unqualified"]) {
    const closed = leadConvertChoice([{ ...mine, stage }], salesperson);
    assert.equal(closed.action, undefined);
    assert.match(closed.reason, new RegExp(`This lead is ${stage}`));
  }
  // the Admin converts like a Manager (canCreateSales is true for every CRM role; canEdit from Edit team records)
  const admin = () => ({ canEdit: canEditRecord({ id: 3, role: "Admin", permissions: ["edit_team_records"] }, mine),
    canCreateSales: canCreateSales({ role: "Admin" }) });
  assert.deepEqual(leadConvertChoice([mine], admin).action, { type: "convert", record: mine });
  assert.match(leadConvertChoice([mine], () => ({ canEdit: true, canCreateSales: false })).reason, /can't convert leads/);
  assert.match(leadConvertChoice([mine], () => ({ canEdit: false, canCreateSales: true })).reason, /only your own leads/);
});

test("Convert to Opportunity with several leads ticked only explains, and never opens the Convert form", () => {
  const lead = (id, stage = "Demo") => ({ id, name: `Synthetic Lead ${id}`, stage, owner_id: 2 });
  const salesperson = () => ({ canEdit: true, canCreateSales: true });
  assert.equal(CONVERT_ONE_AT_A_TIME, "Only one lead can be converted at a time. Please select one lead.");
  for (const leads of [[lead(1), lead(2)], [lead(1), lead(2), lead(3)], [lead(1, "Converted"), lead(2, "Lost")], [lead(1), undefined]]) {
    const choice = leadConvertChoice(leads, salesperson);
    assert.equal(choice.explain, CONVERT_ONE_AT_A_TIME);
    assert.equal(choice.action, undefined); // no Convert form, so no conversion request
    assert.equal(choice.reason, undefined);
  }
  // several ticked doesn't get round the role rule: a role that can't convert stays off with the reason
  const noRole = leadConvertChoice([lead(1), lead(2)], () => ({ canEdit: true, canCreateSales: false }));
  assert.equal(noRole.explain, undefined);
  assert.equal(noRole.action, undefined);
  assert.match(noRole.reason, /can't convert leads/);
  // the Admin gets the same one-lead-at-a-time warning as everyone else
  assert.equal(leadConvertChoice([lead(1), lead(2)], () => ({ canEdit: true, canCreateSales: true })).explain, CONVERT_ONE_AT_A_TIME);
  // one lead: the usual rules (someone else's lead without Edit team records stays off)
  assert.match(leadConvertChoice([lead(1)], () => ({ canEdit: false, canCreateSales: true })).reason, /only your own leads/);
  assert.deepEqual(leadConvertChoice([lead(1)], salesperson).action, { type: "convert", record: lead(1) });
});

// The UI wording and conditions below live in JSX components (not importable by the node test runner): checked in
// the source, and in the browser
const source = (file) => readFileSync(new URL(file, import.meta.url), "utf8");

test("Leads Download offers 'All Leads' (wording only: the same 'all' value goes to the server)", () => {
  const files = source("./LeadFiles.jsx");
  assert.match(files, /\["all", "All Leads"\]/);
  assert.doesNotMatch(files, /All leads I can see/);
});

test("create/edit popups have no '* = Required Information' legend; required fields keep their stars", () => {
  for (const file of readdirSync(new URL(".", import.meta.url)).filter((f) => f.endsWith(".jsx")))
    assert.doesNotMatch(source(`./${file}`), /=\s*Required Information/i, file);
  const modal = source("./Modal.jsx");
  assert.match(modal, /\{required && <i> \*<\/i>\}/); // the red star beside required fields
  assert.match(modal, /required=\{required\}/); // and the accessible required attribute
});

test("Opportunities Actions appears only with at least one opportunity ticked, with the same actions", () => {
  const list = source("./ListView.jsx");
  assert.match(list, /ticks && mode !== "kanban" && picked\.size > 0 && \(\s*<ActionMenu/);
  assert.doesNotMatch(list, /Tick opportunities in the list first/);
  for (const action of ["Change Owner", "Mark as Lost", "Clear Selection"]) assert.match(list, new RegExp(`label: "${action}"`));
});

test("Tasks filter is called Record Type, with the Lead, Opportunity and General options and the same filtering", () => {
  const tasks = source("./TasksPage.jsx");
  assert.match(
    tasks,
    /\{ key: "related", label: "Record Type", options: \[\["leads", "Lead"\], \["opportunities", "Opportunity"\], \["general", "General"\]\], get: \(t\) => t\.relatedType \}/,
  );
  assert.match(tasks, /\["Related To", "related"\]/); // the column (the related record's name) keeps its name
});

test("AI Assistant attachment guidance matches the file types and limits the backend accepts", () => {
  const types = ASSISTANT_FILE_TYPES.split(",");
  assert.equal(new Set(types).size, types.length);
  assert.match(source("./AssistantPage.jsx"), /const ACCEPT = ASSISTANT_FILE_TYPES/);
  for (const words of ["PDF", "Word", "Excel", "PowerPoint", "CSV", "text", "HTML", "email (.eml)", "PNG", "JPG", "WEBP", "GIF", "5 files", "10 MB", "images 5 MB"])
    assert.ok(ASSISTANT_ATTACH_HELP.includes(words), words);
  const store = new URL("../../backend/app/assistant_store.py", import.meta.url);
  if (!existsSync(store)) return; // frontend-only checkout
  const py = readFileSync(store, "utf8");
  const keys = (name) => [...py.match(new RegExp(`${name} = \\{([\\s\\S]*?)\\}`))[1].matchAll(/"(\.[a-z]+)":/g)].map((m) => m[1]);
  const backend = ["DOC_TYPES", "TEXT_TYPES", "IMAGE_TYPES"].flatMap(keys);
  assert.deepEqual([...types].sort(), [...backend].sort()); // the picker offers exactly what the backend reads
  assert.match(py, /MAX_FILE_BYTES = 10 \* 1024 \* 1024/);
  assert.match(py, /MAX_IMAGE_BYTES = 5 \* 1024 \* 1024/);
  assert.match(py, /MAX_FILES_PER_MESSAGE = 5\b/);
});

test("New Campaign has no rendered preview; subject and message stay templates with merge fields", () => {
  const campaigns = source("./CampaignsPage.jsx");
  assert.doesNotMatch(campaigns, /email-sample|aria-label="Preview"|function fill\(/);
  assert.match(campaigns, /className="merge-chip" onClick=\{\(\) => insert\(key\)\}/); // Insert field buttons
  assert.match(campaigns, /const token = `\{\$\{field\}\}`/); // inserts {first_name}, not one recipient's value
  assert.match(campaigns, /subject: subject\.trim\(\),\s*body: body\.trim\(\),/); // the templates are what's sent
  assert.match(campaigns, /\.campaignPreview\(audience\)/); // recipient counts and exclusions still checked
  assert.match(campaigns, /preview\?\.eligible/);
});

test("Leads selection actions: only with leads ticked, keeping Convert's one-lead form, the warning and the limits", () => {
  const lead = (id, stage = "Demo") => ({ id, name: `Synthetic Lead ${id}`, stage, owner_id: 2 });
  const seller = () => ({ canEdit: true, canCreateSales: true });
  const admin = () => ({ canEdit: true, canCreateSales: canCreateSales({ role: "Admin" }) });
  const noRole = () => ({ canEdit: true, canCreateSales: false });
  const actions = (leads, rights, extra = {}) =>
    leadSelectionActions({ count: leads.length, convertChoice: leadConvertChoice(leads, rights), canCampaign: true, canTransfer: true, ...extra });
  const byKey = (list) => Object.fromEntries(list.map((a) => [a.key, a]));

  // nothing ticked: no bar, no actions
  assert.deepEqual(leadSelectionActions({ count: 0, convertChoice: leadConvertChoice([], seller), canCampaign: true, canTransfer: true }), []);

  // one open lead of mine: every action on, Convert opens the existing popup
  const one = byKey(actions([lead(1)], seller));
  assert.deepEqual(Object.keys(one), ["convert", "campaign", "transfer", "delete"]);
  assert.equal(one.convert.disabled, false);
  assert.equal(one.transfer.label, "Transfer Lead");
  assert.equal(one.delete.label, "Delete Lead");
  assert.equal(one.delete.danger, true);

  // several ticked: Convert stays clickable only to show the one-lead-at-a-time warning (leadConvertChoice.explain)
  const several = byKey(actions([lead(1), lead(2)], seller));
  assert.equal(several.convert.disabled, false);
  assert.equal(leadConvertChoice([lead(1), lead(2)], seller).explain, CONVERT_ONE_AT_A_TIME);
  assert.equal(several.transfer.label, "Transfer Leads");

  // a closed lead, or a role that can't convert: Convert is off and says why; the Admin's Convert is on
  const closed = byKey(actions([lead(1, "Converted")], seller));
  assert.equal(closed.convert.disabled, true);
  assert.match(closed.convert.reason, /This lead is Converted/);
  assert.match(byKey(actions([lead(1)], noRole)).convert.reason, /can't convert leads/);
  assert.equal(byKey(actions([lead(1)], admin)).convert.disabled, false);

  // rights decide which actions are offered; the server still checks each lead
  assert.deepEqual(Object.keys(byKey(actions([lead(1)], seller, { canCampaign: false, canTransfer: false }))), ["convert", "delete"]);

  // Transfer and Delete: up to 500 leads at a time
  const many = byKey(
    leadSelectionActions({ count: BULK_LIMIT + 1, convertChoice: { explain: CONVERT_ONE_AT_A_TIME }, canCampaign: true, canTransfer: true }),
  );
  assert.equal(many.transfer.disabled, true);
  assert.equal(many.delete.disabled, true);
  assert.equal(many.delete.reason, "Up to 500 leads at a time");
  assert.equal(many.campaign.disabled, undefined);
  assert.equal(byKey(actions([lead(1)], seller)).delete.disabled, false); // within the limit
});

test("Leads selection bar: shown only in the list with leads ticked; Convert's popup and warning are wired as before", () => {
  const leads = source("./LeadsTable.jsx");
  assert.match(leads, /const selecting = !kanban && selected\.size > 0;/);
  assert.match(leads, /\{selecting \? \(/);
  assert.match(leads, /convertChoice\.explain \? setNotice\(\{ title: "Convert to Opportunity", message: convertChoice\.explain \}\) : setModal\(convertChoice\.action\)/);
  // an action that is off sends nothing; it only explains why (the old menu showed the reason under the item)
  assert.match(leads, /onClick=\{\(\) => \(a\.disabled \? a\.reason && setNotice\(\{ title: a\.label, message: a\.reason \}\) : run\[a\.key\]\(\)\)\}/);
  assert.doesNotMatch(leads, /createPortal|lead-bulk-actions/); // the old Actions menu in the header is gone
  assert.doesNotMatch(source("./ListView.jsx"), /lead-bulk-actions/);
});

test("Select all ticks the current page only, and the bar says where the ticked leads are", () => {
  const page = [1, 2, 3];
  assert.deepEqual(selectionSummary(new Set(), page), { count: 0, onPage: 0, elsewhere: 0, where: "" });
  assert.equal(selectionSummary(new Set([1, 2, 3]), page).where, "All 3 on this page");
  assert.equal(selectionSummary(new Set([2]), page).where, "On this page");
  assert.equal(selectionSummary(new Set([7, 8]), page).where, "2 on other pages"); // ticks stay when the page changes
  const mixed = selectionSummary(new Set([1, 2, 3, 40, 41]), page);
  assert.equal(mixed.count, 5);
  assert.equal(mixed.where, "3 on this page, 2 on other pages");
  const leads = source("./LeadsTable.jsx");
  assert.match(leads, /label=\{`Select all \$\{pageIds\.length\} leads on this page`\}/);
  assert.doesNotMatch(leads, /select all matching/i); // no "all matching records" without server support
});

test("Leads paging footer: 'Showing X–Y of N leads', never '1–0', and a page past the end moves back", () => {
  assert.equal(pageSummary({ start: 0, size: 15, total: 28, noun: "lead" }), "Showing 1–15 of 28 leads");
  assert.equal(pageSummary({ start: 15, size: 15, total: 28, noun: "lead" }), "Showing 16–28 of 28 leads");
  assert.equal(pageSummary({ start: 0, size: 25, total: 1, noun: "lead" }), "Showing 1–1 of 1 lead");
  assert.equal(pageSummary({ start: 0, size: 15, total: 0, noun: "lead" }), "No leads to show");
  assert.equal(pageSummary({ start: 100, size: 100, total: 123456, noun: "lead" }), "Showing 101–200 of 123,456 leads");
  assert.equal(pageSummary({ start: 45, size: 15, total: 30, noun: "lead" }), "Showing 30–30 of 30 leads"); // stale page: no "46–30"
  assert.equal(clampPage(3, 30, 15), 1); // after a delete or a bigger page size
  assert.equal(clampPage(1, 30, 15), 1);
  assert.equal(clampPage(2, 0, 15), 0); // empty list: first page
  assert.equal(clampPage(0, 400, 100), 0);
  // the server pages the list (offset / limit) with the chosen rows per page; nothing loads every lead
  const leads = source("./LeadsTable.jsx");
  assert.match(leads, /offset: page \* size, limit: size/);
  assert.match(leads, /noun="lead"/);
  assert.match(source("./ui.jsx"), /export const PAGE_SIZES = \[15, 25, 50, 100\];/); // all within the server's 500
});

test("applied filters become chips: each removes only its own values, a custom range shows its dates", () => {
  const defs = [
    { key: "stage", label: "Lead Status", options: [["New", "New"], ["Demo", "Demo"]] },
    { key: "source", label: "Lead Source", options: [["Upload", "Upload"]] },
    { key: "owner", label: "Owner", options: [["2", "Me"], ["5", "Ana Ruiz"]] },
    { key: "created", label: "Created", type: "date" },
    { key: "account", label: "Account", type: "text" },
  ];
  const values = { source: "Upload", owner: "2", created: "custom", created_from: "2026-11-01", created_to: "2026-11-05" };
  const chips = filterChips(defs, values);
  assert.deepEqual(chips.map((c) => c.text), ["Lead Source: Upload", "Owner: Me", "Created: Nov 1, 2026 – Nov 5, 2026"]);
  assert.deepEqual(chips[1].without, { source: "Upload", created: "custom", created_from: "2026-11-01", created_to: "2026-11-05" });
  assert.deepEqual(chips[2].without, { source: "Upload", owner: "2" }); // the range's own dates go with it
  assert.deepEqual(withoutFilter({ created: "last7" }, "created"), {});
  assert.deepEqual(filterChips(defs, {}), []);
  // the summary under other lists keeps its wording
  assert.equal(filterText(defs[3], { created: "last7" }), "Created: Last 7 days");
  assert.equal(filterText(defs[4], { account: "acme" }), 'Account: contains "acme"');
  assert.equal(chipText(defs[3], { created: "custom", created_from: "2026-11-01" }), "Created: from Nov 1, 2026");
  assert.equal(chipText(defs[3], { created: "today" }), "Created: Today");
});

test("an empty Leads list says why: nothing matches, an empty list view, or no leads yet", () => {
  const matching = leadsEmptyMessage({ search: true, filtered: false, view: "all_open", viewName: "All Open Leads" });
  assert.equal(matching.title, "No leads match your search or filters");
  assert.equal(matching.clear, true);
  assert.equal(leadsEmptyMessage({ search: false, filtered: true, view: "all" }).clear, true);
  assert.equal(leadsEmptyMessage({ search: false, filtered: false, view: "all" }).title, "No leads yet");
  const view = leadsEmptyMessage({ search: false, filtered: false, view: "converted", viewName: "Converted Leads" });
  assert.equal(view.title, "No leads in Converted Leads");
  assert.equal(view.clear, undefined);
});

test("the sort order is described in words under the list title", () => {
  assert.equal(sortText("Created", "created", "desc"), "Sorted by Created, newest first");
  assert.equal(sortText("Last Modified", "modified", "asc"), "Sorted by Last Modified, oldest first");
  assert.equal(sortText("Name", "name", "asc"), "Sorted by Name, A–Z");
  assert.equal(sortText("Owner", "owner", "desc"), "Sorted by Owner, Z–A");
  assert.equal(sortText(undefined, "x", "asc"), "");
});

// The code that runs: comments removed (JSX {/* */} blocks, /* */ blocks and whole-line // comments)
const activeCode = (text) =>
  text.replace(/\{\/\*[\s\S]*?\*\/\}/g, "").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("New Email: the CRM attachment controls and direct send are preserved in comments, not active", () => {
  // the shared size helpers stay (the opportunity Attachments card and the email list use them)
  assert.equal(attachedSummary([]), "No files attached");
  assert.equal(attachedSummary([{ size: 220 * 1024 }]), "1 file attached · 220 KB of 25 MB");
  assert.equal(attachedSummary([{ size: 1.4 * 1024 * 1024 }, { size: 220 * 1024 }]), "2 files attached · 1.6 MB of 25 MB");
  assert.equal(fileSize(500), "1 KB");
  assert.equal(fileSize(10 * 1024 * 1024), "10.0 MB");
  const email = source("./Email.jsx");
  const active = activeCode(email);
  // preserved for restoration: the attachment controls, their limits and handlers, the Send from choice and the send call
  for (const kept of ['aria-controls="email-attach-panel"', 'type="file"', "const [attachOpen, setAttachOpen] = useState(false);",
    "// const MAX_FILE = 10 * 1024 * 1024;", "if (f.size > MAX_FILE)", 'files.forEach((f) => form.append("files", f, f.name));',
    "<legend>Send from</legend>", "<b>CRM mailbox</b>", 'name="reply_to"', "const email = await api.sendEmail(form);"])
    assert.ok(email.includes(kept), kept);
  assert.match(email, /PRESERVED, intentionally disabled/);
  // ...but none of it runs: no attachment button, file picker or drop area, no mailbox choice, no CRM send
  for (const gone of ['type="file"', "Attach files", "email-attach", "onDrop", "dropzone", "Choose files", "Send from", 'name="via"',
    "CRM mailbox", "reply_to", "api.sendEmail(", "setSending(", "attachedSummary("])
    assert.ok(!active.includes(gone), gone);
  // stage-change and campaign attachments are separate components and untouched by this
  assert.doesNotMatch(source("./Modal.jsx"), /email-attach/);
  assert.doesNotMatch(source("./CampaignsPage.jsx"), /email-attach/);
});

test("New Email: one Open in Outlook action, the attachments hint, AI drafting and editable fields; nothing is sent", () => {
  const active = activeCode(source("./Email.jsx"));
  assert.equal((active.match(/type="submit"/g) || []).length, 1);
  assert.match(active, /title=\{canSend \? "Open this draft in Outlook on the web in a new tab"[^}]*\}\s*>\s*Open in Outlook\s*<\/button>/);
  assert.equal((active.match(/Opens Outlook in a new tab\. Add attachments there\./g) || []).length, 1);
  assert.doesNotMatch(active, /CRM files|attachments will|files will be added/i); // nothing suggests CRM files go to Outlook
  // the form opens Outlook; the handler never calls the API, so nothing is sent, marked Sent or saved as history
  assert.match(active, /<form ref=\{formRef\} onSubmit=\{openInOutlook\}/);
  const handler = active.slice(active.indexOf("const openInOutlook"), active.indexOf("const copyText"));
  assert.match(handler, /outlookHandoff\(draft\)/);
  assert.doesNotMatch(handler, /api\.|fetch\(|onSent|onClose/); // the composer and its draft stay open
  assert.match(handler, /addressProblem\(draft\.to, "To", true\) \|\| addressProblem\(draft\.cc, "Cc"\)/);
  assert.match(handler, /if \(!canSend\) return setError/); // the Send emails permission still applies
  // the new tab is opened inside the click; a blocked tab is detected and offered as a link
  assert.match(active, /const tab = window\.open\(url, "_blank"\);\s*if \(!tab\) return false;\s*tab\.opener = null;/);
  assert.match(active, /handoff\?\.kind === "blocked"/);
  assert.match(active, /handoff\?\.kind === "too-long"/);
  // Help me write stays, with the same props; To, Cc, Subject and Message stay editable
  assert.match(active, /<EmailDraftAssistant target=\{target\} settings=\{sender\} user=\{user\} subject=\{subject\} message=\{message\} sending=\{sending\} recipients=\{[^}]+\} onBusyChange=\{setAiBusy\} onApply=\{draft => \{ setSubject\(draft\.subject\); setMessage\(draft\.body\); \}\} \/>/);
  assert.match(active, /<input name="to" defaultValue=\{target\.email \|\| ""\}/);
  assert.match(active, /<input name="cc" /);
  assert.doesNotMatch(active, /readOnly/);
  assert.match(active, /disabled=\{aiBusy \|\| !canSend\}/); // not while a draft is being written
  // older history entries saved by the previous handoff say what really happened
  assert.match(active, /\{handoff \? ` • Draft opened in \$\{email\.status\}; sending not confirmed` : ""\}/);
  // the backend send endpoint and the shared mail services are not removed
  const router = readFileSync(new URL("../../backend/app/routers/emails.py", import.meta.url), "utf8");
  assert.match(router, /@router\.post\("", response_model=schemas\.EmailOut/);
  assert.match(router, /error = mailer\.send\(/);
});

test("Open in Outlook link: encoding, several recipients, line breaks, Unicode and the length limit", () => {
  const draft = {
    to: " ana@acme.example ",
    cc: "raj@acme.example; mei@acme.example, ops+crm@acme.example",
    subject: "Q4 pricing & next steps #2 (100% + 5%)",
    body: "Hi Ana,\r\n\r\nPrices: A&B + C = 100% #1.\nनमस्ते — café ✓ 🎉\rThanks,\nRavi",
  };
  const url = outlookComposeUrl(draft);
  // the one compose link Outlook on the web supports (the older /owa/?path=/mail/action/compose is redirected to it)
  assert.equal(OUTLOOK_COMPOSE_URL, "https://outlook.office.com/mail/deeplink/compose");
  assert.ok(url.startsWith(`${OUTLOOK_COMPOSE_URL}?to=`));
  const query = url.slice(url.indexOf("?") + 1);
  assert.doesNotMatch(query, /[ #+\n\r]|%(?![0-9A-F]{2})/); // nothing that could end or change the link
  assert.match(query, /%26/); // &
  assert.match(query, /%2B/); // + (never read as a space)
  assert.match(query, /%23/); // #
  assert.match(query, /%25/); // %
  assert.match(query, /%0A/); // line break
  const params = new URL(url).searchParams;
  assert.equal(params.get("to"), "ana@acme.example");
  assert.equal(params.get("cc"), "raj@acme.example,mei@acme.example,ops+crm@acme.example");
  assert.equal(params.get("subject"), "Q4 pricing & next steps #2 (100% + 5%)");
  assert.equal(params.get("body"), "Hi Ana,\n\nPrices: A&B + C = 100% #1.\nनमस्ते — café ✓ 🎉\nThanks,\nRavi");
  assert.deepEqual([...params.keys()], ["to", "cc", "subject", "body"]);
  // empty fields are left out; a broken emoji half doesn't break the link
  assert.deepEqual([...new URL(outlookComposeUrl({ to: "a@b.co", cc: " ", subject: "Hi", body: "x" })).searchParams.keys()], ["to", "subject", "body"]);
  assert.doesNotThrow(() => outlookComposeUrl({ to: "a@b.co", subject: "Hi", body: "half \ud83d emoji" }));
  // short drafts open whole
  const ok = outlookHandoff(draft);
  assert.equal(ok.fits, true);
  assert.equal(ok.url, url);
  assert.equal(OUTLOOK_URL_LIMIT, 4000);
  // a long draft is never cut: it doesn't fit, and To, Cc and Subject can still open while the message is copied
  const long = { ...draft, body: "We reviewed the proposal in detail. ".repeat(150) };
  const plan = outlookHandoff(long);
  assert.equal(plan.fits, false);
  assert.equal(plan.url, null);
  assert.ok(plan.length > OUTLOOK_URL_LIMIT);
  assert.equal(plan.partialHasFields, true);
  assert.deepEqual([...new URL(plan.partialUrl).searchParams.keys()], ["to", "cc", "subject"]);
  assert.equal(new URL(outlookComposeUrl(long)).searchParams.get("body"), long.body); // the full link still carries all of it
  // Unicode counts as it is encoded: 600 Hindi letters are too long for one link
  assert.equal(outlookHandoff({ to: "a@b.co", subject: "Hi", body: "न".repeat(600) }).fits, false);
  // the limit is exact
  const base = outlookComposeUrl({ to: "a@b.co", subject: "Hi", body: "" }).length + "&body=".length;
  assert.equal(outlookHandoff({ to: "a@b.co", subject: "Hi", body: "x".repeat(OUTLOOK_URL_LIMIT - base) }).fits, true);
  assert.equal(outlookHandoff({ to: "a@b.co", subject: "Hi", body: "x".repeat(OUTLOOK_URL_LIMIT - base + 1) }).fits, false);
  // even To and Subject too long: Outlook opens empty and the whole draft is copied instead
  const huge = outlookHandoff({ to: "a@b.co", subject: "Hi", cc: Array.from({ length: 300 }, (_, i) => `person${i}@example.com`).join(","), body: "x" });
  assert.equal(huge.partialHasFields, false);
  assert.equal(huge.partialUrl, OUTLOOK_COMPOSE_URL);
  assert.equal(draftForCopy(draft), "To: ana@acme.example\nCc: raj@acme.example, mei@acme.example, ops+crm@acme.example\nSubject: Q4 pricing & next steps #2 (100% + 5%)\n\nHi Ana,\n\nPrices: A&B + C = 100% #1.\nनमस्ते — café ✓ 🎉\nThanks,\nRavi");
});

test("Open in Outlook: addresses are checked like the API before Outlook opens", () => {
  assert.deepEqual(splitAddresses(" a@x.co ;b@y.co,, c@z.co "), ["a@x.co", "b@y.co", "c@z.co"]);
  assert.equal(addressProblem("", "To", true), "Enter at least one recipient.");
  assert.equal(addressProblem(" ", "Cc"), "");
  assert.equal(addressProblem("ana@acme.example, raj@acme.example", "To", true), "");
  assert.equal(addressProblem("ana@acme", "To", true), "Check the To address: ana@acme");
  assert.equal(addressProblem("x, y@z.co, w w@z.co", "Cc"), "Check the Cc addresses: x, w w@z.co");
});

test("Help me write: an unrelated request shows exactly 'Ask relevant to CRM' and keeps the subject, message and request", () => {
  const text = source("./EmailDraftAssistant.jsx");
  const keptMessage = new Function(`${text.slice(text.indexOf("const NOT_CRM"), text.indexOf("export default function"))}; return keptMessage;`)();
  assert.equal(keptMessage("Ask relevant to CRM"), "Ask relevant to CRM"); // nothing added
  assert.equal(keptMessage("Cannot reach the AI service."), "Cannot reach the AI service. Your email is unchanged.");
  assert.equal(keptMessage("AI drafting took too long. Your email is unchanged; please try again."), "AI drafting took too long. Your email is unchanged; please try again.");
  // the backend refuses with the same words, for generation and refinement
  const backend = readFileSync(new URL("../../backend/app/ai_email.py", import.meta.url), "utf8");
  assert.match(backend, /^NOT_CRM = "Ask relevant to CRM"/m);
  // only a successful draft fills the subject and message and clears the request; an error changes none of them
  const run = text.slice(text.indexOf("const run = async"), text.indexOf("const cancel = "));
  const failure = run.slice(run.indexOf("} catch (err) {"), run.indexOf("} finally {"));
  assert.doesNotMatch(failure, /onApply|setInstructions|setSubject|setMessage|setHistory/);
  assert.ok(run.indexOf("onApply(applied)") < run.indexOf("} catch (err) {"));
  assert.ok(run.indexOf('setInstructions("")') < run.indexOf("} catch (err) {"));
});

test("Manage Access: Status is a column filter (All, Active, Inactive), off by default and removable", () => {
  const users = source("./UsersPage.jsx");
  assert.doesNotMatch(users, /aria-label="Filter by status"/); // the dropdown above the table is gone
  assert.match(users, /const STATUS_FILTER = \{ key: "status", label: "Status", options: \[\["active", "Active"\], \["inactive", "Inactive"\]\] \};/);
  assert.match(users, /<Th label="Status" className="status-col" filter=\{STATUS_FILTER\} values=\{statusValues\} onChange=\{setStatusFilter\} \/>/);
  assert.match(users, /const \[status, setStatus\] = useState\("any"\);/); // default: every status
  assert.match(users, /\(status === "any" \|\| \(status === "active"\) === u\.is_active\)/); // the same filtering
  assert.match(users, /usePaged\(shown, `\$\{roleFilter\}\|\$\{team\}\|\$\{query\}\|\$\{status\}`\)/); // back to page 1 on change
  assert.match(users, /<span className=\{`pill \$\{u\.is_active \? "pill-ok" : "pill-off"\}`\}>/); // the badge in each row stays
  const def = { key: "status", label: "Status", options: [["active", "Active"], ["inactive", "Inactive"]] };
  assert.equal(filterText(def, { status: "inactive" }), "Status: Inactive"); // the chip shown while it is on
  assert.equal(filterText(def, { status: "active" }), "Status: Active");
  // keyboard: after a choice or Esc, focus goes back to the column's filter arrow (every list uses this menu)
  const filters = source("./Filters.jsx");
  assert.match(filters, /onChange\(next\);\s*setOpen\(false\);\s*button\.current\?\.focus\(\{ preventScroll: true \}\);/);
  assert.match(filters, /e\.key === "Escape" && \(setOpen\(false\), button\.current\?\.focus\(\{ preventScroll: true \}\)\)/);
});

test("Home: one short, simple line under the greeting for each role", () => {
  assert.equal(homeDescription("Admin", true), "Company-wide sales at a glance.");
  assert.equal(homeDescription("Admin", false), "Company-wide sales at a glance."); // the Admin always sees every record
  assert.equal(homeDescription("Manager", true), "Your team's sales at a glance."); // My Team
  assert.equal(homeDescription("Manager", false), "Your sales and follow-ups for today."); // Me
  assert.equal(homeDescription("Salesperson", false), "Your sales and follow-ups for today.");
  const home = source("./SellerHome.jsx");
  assert.match(home, /<h1>\{greeting\(\)\.replace\(/); // the time-based greeting stays
  assert.match(home, /<p>\{homeDescription\(user\.role, teamView\)\}<\/p>/);
  assert.doesNotMatch(home, /My Sales Desk|Team Command Center|Company Control Tower/); // no tagline
});

test("column filter menus keep their own option layout inside table headers (no horizontal scrollbar)", () => {
  const css = source("./styles.css");
  // .sf-table th button (sortable headers: wider than the cell, negative margin) must not reach the menu options
  const rule = css.match(/\.sf-table th \.th-menu > button \{([^}]*)\}/);
  assert.ok(rule, "override for menu options inside headers");
  for (const decl of ["width: 100%", "margin: 0", "padding: 6px 12px", "color: var(--text)"]) assert.ok(rule[1].includes(decl), decl);
  assert.match(css, /\.sf-table th \.th-menu > button\.on \{\s*color: var\(--brand-dark\);/);
});

test("direct opportunity creation and lead conversion: the Admin, Managers and Salespeople", () => {
  for (const role of ["Admin", "Manager", "Salesperson"]) assert.equal(canCreateOpportunity({ role }), true);
  assert.equal(canCreateOpportunity(null), false);
  assert.equal(canCreateOpportunity({ role: "Unknown" }), false);
  // lead conversion (canCreateSales gates only the Convert entry points): every CRM role, and nobody else
  for (const role of ["Admin", "Manager", "Salesperson"]) assert.equal(canCreateSales({ role }), true, role);
  assert.equal(canCreateSales(null), false);
  assert.equal(canCreateSales({ role: "Unknown" }), false);
  // ...and every use of it is a Convert entry point (no other sales action is opened to the Admin by it)
  const uses = ["./RecordPage.jsx", "./LeadsKanban.jsx", "./LeadsTable.jsx", "./ListView.jsx"]
    .flatMap((file) => source(file).split("\n").filter((line) => line.includes("canCreateSales(")).map((line) => `${file}: ${line.trim()}`));
  assert.equal(uses.length, 4, uses.join("\n"));
  assert.ok(uses.find((u) => u.startsWith("./RecordPage.jsx") && /const canConvert = canEdit && canCreateSales\(user\)/.test(u)));
  assert.ok(uses.find((u) => u.startsWith("./LeadsKanban.jsx") && /canConvert: canEdit && canCreateSales\(user\)/.test(u)));
  assert.ok(uses.find((u) => u.startsWith("./LeadsTable.jsx") && /canCreateSales: canCreateSales\(user\)/.test(u)));
  assert.ok(uses.find((u) => u.startsWith("./ListView.jsx") && /collection === "opportunities" && canCreateSales\(user\)/.test(u)));
  assert.match(source("./ListView.jsx"), /canCreateSales\(user\) && \(\s*<a className="sf-button" href="#\/leads" title="Opportunities are created by converting a lead">\s*Convert a Lead/);
});


test("email writing button and Enter choose the same action for an empty or existing draft", () => {
  const starter = "Hi Jack,\n\nBest regards,\nRavi Kumar\nravi@crm.test";
  assert.equal(emailWritingAction("", starter, "Ravi Kumar", "ravi@crm.test"), "stage");
  assert.equal(emailWritingAction("Write an email", starter, "Ravi Kumar", "ravi@crm.test"), "custom");
  const draft = "Hi Jack,\n\nCould you share your availability?";
  assert.equal(emailWritingAction("   ", draft, "Ravi Kumar", "ravi@crm.test"), "formalize");
  assert.equal(emailWritingAction("Change the subject", draft, "Ravi Kumar", "ravi@crm.test"), "custom");
});


test("resetting the writing bar returns to generation even while the previous email is still present", () => {
  const draft = "Hi Jack,\n\nCould you share your availability?";
  assert.equal(emailWritingAction("", draft, "Ravi Kumar", "ravi@crm.test", true), "stage");
  assert.equal(emailWritingAction("write an email", draft, "Ravi Kumar", "ravi@crm.test", true), "custom");
  assert.equal(emailWritingAction("", draft, "Ravi Kumar", "ravi@crm.test", false), "formalize");
});

// ---------- review follow-ups (vikram-fixes) ----------

test("lead Edit: the Details pencils follow the same rule as Actions > Edit (owner or Edit team records)", () => {
  const lead = { id: 7, owner_id: 2, stage: "Converted" };
  const user = (role, permissions = [], id = 9) => ({ id, role, permissions });
  assert.equal(canEditRecord(user("Salesperson", [], 2), lead), true); // the owner
  assert.equal(canEditRecord(user("Manager", ["edit_team_records", "view_team_records"]), lead), true);
  assert.equal(canEditRecord(user("Admin", ["edit_team_records", "manage_users"]), lead), true);
  assert.equal(canEditRecord(user("Salesperson", ["view_team_records"]), lead), false); // team access is view-only
  assert.equal(canEditRecord(user("Salesperson"), lead), false);
  assert.equal(canEditRecord(null, lead), false);
  const page = source("./RecordPage.jsx");
  assert.match(page, /const canEdit = canEditRecord\(user, item\);/);
  assert.match(page, /const editField = canEdit \? edit : undefined;/);
  assert.doesNotMatch(page, /onEdit=\{edit\}/); // every pencil uses the guarded handler
  assert.match(page, /canEdit && \{ label: "Edit", onClick: edit \}/); // Actions > Edit unchanged (also Converted leads)
});

test("record pages: one New Task button, in the Activity tab, linked to the record", () => {
  const page = source("./RecordPage.jsx");
  const header = page.slice(page.indexOf('<div className="button-group">'), page.indexOf("<ActionMenu", page.indexOf('<div className="button-group">')));
  assert.doesNotMatch(header, /openTask\(/); // no New Task button in the header any more
  assert.match(page, /<button className="sf-button" onClick=\{\(\) => openTask\(item\.id, collection\)\}>\s*<ObjectIcon type="task" size=\{18\} \/> New Task/);
  // the stage popups still require their own New Task
  assert.equal(stageTaskNeeded("stage", "leads", "Demo"), true);
});

test("completed tasks: no strikethrough on record pages or the Tasks list; the status stays visible", () => {
  const css = source("./styles.css");
  assert.match(css, /\.task-line\.done \.link \{\s*text-decoration: none;/);
  assert.match(css, /\.row-done \.link \{\s*text-decoration: none;/);
  assert.doesNotMatch(css, /\.task-line\.done \.link \{[^}]*line-through/);
  const page = source("./RecordPage.jsx");
  assert.match(page, /checked=\{task\.completed\}\s*disabled=\{task\.completed\}/); // ticked and disabled
  assert.match(page, /\{task\.completed \? ` • \$\{task\.status\}` : ""\}/); // "Done" / "Auto-closed" in the line
});

test("sign-in: Edge's own password reveal is hidden, so the app's Show / Hide password button is the only one", () => {
  const css = source("./login.css");
  assert.match(css, /#signin-password::-ms-reveal, #signin-password::-ms-clear \{ display: none; \}/);
  const login = source("./Login.jsx");
  assert.match(login, /aria-label=\{showPassword \? "Hide password" : "Show password"\}/);
  assert.match(login, /type=\{showPassword \? "text" : "password"\}/);
  assert.match(login, /autoComplete="current-password"/); // password managers still fill it
});

test("demo times are IST (Asia/Kolkata) for entry and display, whatever the browser's time zone", () => {
  // a fixed instant: 2026-11-09 22:16:30 UTC = 10 Nov 03:46 IST (and 17:16 in New York)
  const now = new Date(Date.UTC(2026, 10, 9, 22, 16, 30));
  const zones = ["America/New_York", "America/Los_Angeles", "Europe/London"];
  const saved = process.env.TZ;
  try {
    for (const tz of zones) {
      process.env.TZ = tz; // the browser's own zone must not matter
      assert.equal(businessNow(now), "2026-11-10T03:46", tz);
      assert.equal(toBusinessInput("2026-11-20T15:30:00Z"), "2026-11-20T21:00", tz); // stored 10:30 New York
      assert.equal(formatBusiness("2026-11-20T15:30:00Z"), "11/20/2026, 9:00 PM IST", tz);
      assert.equal(formatBusinessTime("2026-11-20T15:30:00Z"), "9:00 PM IST", tz);
      assert.equal(new Date(fromBusinessInput("2026-11-20T21:00")).toISOString(), "2026-11-20T15:30:00.000Z", tz);
    }
  } finally {
    if (saved === undefined) delete process.env.TZ;
    else process.env.TZ = saved;
  }
  assert.equal(BUSINESS_TIMEZONE, "Asia/Kolkata");
  assert.equal(BUSINESS_TZ_LABEL, "IST (UTC+05:30)");
  assert.equal(fromBusinessInput(""), null);
  assert.equal(toBusinessInput(null), "");
  // the backend uses the same zone
  assert.match(readFileSync(new URL("../../backend/app/services.py", import.meta.url), "utf8"), /BUSINESS_TIMEZONE = ZoneInfo\("Asia\/Kolkata"\)/);
});

test("demo date pickers: earliest is now in IST; Edit Lead keeps a demo that already passed", () => {
  const now = new Date(Date.UTC(2026, 10, 9, 22, 16, 30)); // 10 Nov 03:46 IST
  const earliest = "2026-11-10T03:46";
  assert.equal(demoDateMin({ name: "demo_date", type: "stage", stage: "Demo", now }), earliest); // Change Stage > Demo
  assert.equal(demoDateMin({ name: "reschedule_to", type: "cancelDemo", now }), earliest); // Reschedule
  assert.equal(demoDateMin({ name: "demo_date", type: "lead", current: "", now }), earliest); // Edit Lead, no date yet
  assert.equal(demoDateMin({ name: "demo_date", type: "lead", current: "2026-12-01T10:00", now }), earliest);
  assert.equal(demoDateMin({ name: "demo_date", type: "lead", current: "2026-11-10T03:00", now }), undefined); // passed
  assert.equal(demoDateMin({ name: "task_due_date", type: "stage", stage: "Demo", now }), undefined);
  const modal = source("./Modal.jsx");
  assert.match(modal, /demoDateMin\(\{ name, type, stage: modal\?\.stage, current: value \}\)/);
  // labelled, filled from the instant, sent with the IST offset
  assert.equal((modal.match(/`Demo Date in \$\{BUSINESS_TZ_LABEL\}`/g) || []).length, 2); // Edit Lead and Change Stage
  assert.match(modal, /`New Demo Date in \$\{BUSINESS_TZ_LABEL\}`/); // Reschedule
  assert.equal((modal.match(/toBusinessInput\(record\.demo_at\)/g) || []).length, 2);
  assert.match(modal, /\{ demo_date: fromBusinessInput\(v\.demo_date\) \}/);
  assert.match(modal, /reschedule_to: demoChoice === "reschedule" \? fromBusinessInput\(v\.reschedule_to\) : null/);
  assert.match(source("./api.js"), /payload\.demo_date = fromBusinessInput\(optional\(values\.demo_date\)\)/);
  assert.match(source("./RecordPage.jsx"), /<span>\{formatBusiness\(item\.demo_at\)\}<\/span>/);
  assert.match(source("./SellerHome.jsx"), /formatBusinessTime\(e\.start_at\)/);
});

test("Home overdue shortcut: the count and the Tasks page use one definition, and the shortcut is never saved", () => {
  const tasks = [
    { id: "1", owner_id: 2, completed: false, isOverdue: true },
    { id: "2", owner_id: 2, completed: true, isOverdue: false }, // done (a past due date doesn't make it overdue)
    { id: "3", owner_id: 5, completed: false, isOverdue: true }, // someone else's
    { id: "4", owner_id: 2, completed: false, isOverdue: false }, // due today or later
  ];
  assert.deepEqual(myOverdueTasks(tasks, 2).map((t) => t.id), ["1"]);
  assert.deepEqual(tasks.filter((t) => isMyOpenTask(t, 2)).map((t) => t.id), ["1", "4"]); // the shortcut's list
  assert.deepEqual(OVERDUE_SHORTCUT_FILTERS, { due: "overdue" }); // + Due Date: Overdue = task 1 only
  const page = source("./TasksPage.jsx");
  assert.doesNotMatch(page, /setStored\(\{ due: "overdue" \}\)/); // the saved filters are not overwritten
  assert.match(page, /const filterValues = shortcut \? shortcutFilters : stored;/);
  assert.match(page, /const viewTest = shortcut \? \(t\) => isMyOpenTask\(t, user\.id\)/);
  // Home's Suggested Actions is gone: overdue tasks are listed first in Action Items > Today (from the API)
  assert.doesNotMatch(source("./SellerHome.jsx"), /myOverdueTasks/);
  // Due Date > Overdue itself is unchanged (it still lists every task due before today), and so is the dropdown
  // (the date ranges moved from Filters.jsx to listHelpers.js; Filters.rangeBounds uses them)
  assert.match(source("./listHelpers.js"), /case "overdue":\s*return \[null, today\];/);
  assert.equal(dateRangeBounds("overdue", "", "", new Date(2026, 10, 10, 15))[0], null);
  assert.equal(dateRangeBounds("overdue", "", "", new Date(2026, 10, 10, 15))[1].getTime(), new Date(2026, 10, 10).getTime());
  assert.match(page, /\["My Tasks", \(t\) => mine\(t\)\],\s*\["Open Tasks", \(t\) => !t\.completed\],\s*\["Completed Tasks", \(t\) => t\.completed\],/);
});

test("Add to Calendar: Google and Microsoft 365 links, a valid .ics, only for a booked demo", () => {
  const start = new Date(Date.UTC(2026, 10, 20, 15, 30));
  const event = { uid: "lead-7-demo@salestrack", title: "Sales Demo: Ana Ruiz (Acme, Inc; West)", start, description: "Line one\nEmail: ana@acme.test" };
  const google = new URL(googleCalendarUrl(event));
  assert.equal(google.host, "calendar.google.com");
  assert.equal(google.searchParams.get("dates"), "20261120T153000Z/20261120T163000Z"); // one hour, in UTC
  assert.equal(google.searchParams.get("location"), null);
  const outlook = new URL(outlookCalendarUrl(event));
  assert.equal(outlook.host, "outlook.office.com"); // Microsoft 365, not outlook.live.com
  assert.equal(outlook.searchParams.get("startdt"), "2026-11-20T15:30:00.000Z");
  assert.equal(outlook.searchParams.get("enddt"), "2026-11-20T16:30:00.000Z");
  const ics = icsContent({ ...event, stamp: new Date(Date.UTC(2026, 10, 9, 22, 0)) });
  assert.ok(ics.endsWith("\r\n") && !/[^\r]\n/.test(ics)); // CRLF line ends only
  for (const line of ["UID:lead-7-demo@salestrack", "DTSTAMP:20261109T220000Z", "DTSTART:20261120T153000Z", "DTEND:20261120T163000Z"])
    assert.ok(ics.includes(`\r\n${line}\r\n`), line);
  assert.ok(ics.includes("SUMMARY:Sales Demo: Ana Ruiz (Acme\\, Inc\\; West)"));
  assert.ok(ics.includes("DESCRIPTION:Line one\\nEmail: ana@acme.test"));
  assert.doesNotMatch(ics, /LOCATION|ORGANIZER|ATTENDEE/); // no venue guessed, no invitation
  assert.equal(icsText("a\\b"), "a\\\\b");
  // long lines fold at 75 octets (also with multi-byte characters), continuation lines start with a space
  const folded = foldIcsLine(`DESCRIPTION:${"é".repeat(60)}`);
  for (const part of folded.split("\r\n")) assert.ok(new TextEncoder().encode(part).length <= 75);
  assert.equal(folded.split("\r\n").slice(1).every((p) => p.startsWith(" ")), true);
  assert.equal(folded.replace(/\r\n /g, ""), `DESCRIPTION:${"é".repeat(60)}`);
  // only for a lead at Demo with a date
  const lead = { id: 7, stage: "Demo", demo_date: "2026-11-20T10:30:00", demo_at: "2026-11-20T15:30:00Z", name: "Ana Ruiz", first_name: "Ana", last_name: "Ruiz", company: "Acme", email: "ana@acme.test" };
  const booked = demoEvent(lead);
  assert.equal(booked.start.toISOString(), "2026-11-20T15:30:00.000Z"); // the API's instant: the same for every viewer
  assert.equal(booked.uid, "lead-7-demo@salestrack");
  assert.equal(booked.title, "Sales Demo: Ana Ruiz (Acme)");
  assert.equal(booked.description, "Sales demo with Ana Ruiz from Acme.\nEmail: ana@acme.test"); // no empty Phone line
  for (const stage of ["Converted", "Lost", "Revisit", "Nurturing"]) assert.equal(demoEvent({ ...lead, stage }), null);
  assert.equal(demoEvent({ ...lead, demo_date: null, demo_at: null }), null); // cancelled demo
  const menu = source("./calendar.jsx");
  for (const a of ['aria-haspopup="menu"', "aria-expanded={open}", 'role="menu"', 'role="menuitem"', 'e.key === "Escape"', "button.current?.focus()"])
    assert.ok(menu.includes(a), a);
});

test("list headers: the buttons on the right are spaced and wrap, without touching each other", () => {
  const css = source("./styles.css");
  const rule = css.match(/\.list-title > \.list-buttons \{([^}]*)\}/);
  assert.ok(rule, "list-buttons rule");
  for (const decl of ["display: flex", "flex-wrap: wrap", "gap: 8px", "justify-content: flex-end"]) assert.ok(rule[1].includes(decl), decl);
  assert.match(css, /\.list-title \{\s*display: flex;\s*flex-wrap: wrap;/);
  // List / Kanban stay one joined control (no gap between its two halves)
  assert.doesNotMatch(css, /\.toggle-group \{[^}]*gap:/);
});

test("amounts show their own currency and totals are never added across currencies", async () => {
  const { amount, compactMoney, compactMoneyMix, CURRENCIES } = await import("./format.js");
  assert.deepEqual(CURRENCIES, ["USD", "INR", "EUR", "CAD", "AUD", "AED"]);
  assert.equal(amount(1234.5, "USD"), "$1,234.5");
  assert.equal(amount(1234.5, "INR"), "₹1,234.5");
  assert.equal(amount(1234.5, "AED"), "AED 1,234.5");
  assert.equal(amount(null, "EUR"), "");
  assert.equal(compactMoney(2550000, "EUR"), "€2.55M");
  assert.equal(compactMoneyMix({ INR: 500000, USD: 12000 }), "$12K + ₹500K");
  assert.equal(compactMoneyMix({}), "$0");
});

// ---------- vikram-fixes2: Opportunity stage tasks, PowerPoint / Excel attachments, Leads Kanban pages ----------

test("opportunity moves forward only when its stage tasks are done (date reminders don't count)", () => {
  assert.equal(opportunityMovesForward("Opportunity", "Discovery"), true);
  assert.equal(opportunityMovesForward("Opportunity", "Proposal"), true); // skipping is still forward
  assert.equal(opportunityMovesForward("Proposal", "Won"), true);
  assert.equal(opportunityMovesForward("Proposal", "Discovery"), false); // going back is not limited
  assert.equal(opportunityMovesForward("Won", "Won"), false); // closed deals don't move
  const opp = { id: "7" };
  const task = (id, extra) => ({ id, relatedType: "opportunities", relatedId: "7", completed: false, due_date: "2030-01-0" + id, ...extra });
  const tasks = [
    task(3, { title: "Send the revised quote" }),
    task(1, { title: "Close date coming up - Deal", is_auto: true, is_date_reminder: true }), // a date reminder
    task(2, { title: "Call the CFO" }),
    task(4, { title: "Done already", completed: true }),
    task(5, { relatedId: "8", title: "Another deal" }),
    task(6, { relatedType: "leads", title: "A lead's task" }),
  ];
  assert.deepEqual(unfinishedStageTasks(tasks, opp).map((t) => t.id), [2, 3]); // soonest first
  assert.deepEqual(unfinishedStageTasks([], opp), []);
  // the API's flag reaches the page unchanged
  assert.equal(normalizeTask({ id: 1, status: "Open", due_date: "2030-01-01T09:00:00", is_date_reminder: true }).is_date_reminder, true);
});

test("Change Stage, Mark as Won and the Kanban show the open tasks instead of a form that can't be saved", () => {
  const modal = source("./Modal.jsx");
  // forward moves of opportunities only (Mark as Won, Change Stage, Kanban drop all open this popup)
  assert.match(modal, /const moveTarget = type === "won" \? "Won" : type === "stage" && modal\.collection === "opportunities" \? modal\.stage : null;/);
  assert.match(modal, /opportunityMovesForward\(record\.stage, moveTarget\) \? unfinishedStageTasks\(data\.tasks, record\) : \[\]/);
  assert.match(modal, /stageBlockers\.length > 0 \?/);
  assert.match(modal, /Finish the \{record\.stage\} stage first/);
  assert.match(modal, /Tick each task as done in the Activity tab \(Upcoming &amp; Overdue\)/);
  assert.match(modal, /Nothing has been changed\./);
  // ticking a task only completes it: App's toggleTask never changes the stage
  const app = source("./App.jsx");
  const toggle = app.slice(app.indexOf("const toggleTask"), app.indexOf("// Email composer"));
  assert.match(toggle, /run\("completeTask", taskId\)/);
  assert.doesNotMatch(toggle, /stage|won/i);
});

test("PowerPoint and Excel files: accepted types, legacy formats explained, no preview, upload once Won", () => {
  assert.deepEqual(ATTACHMENT_EXTENSIONS, [".pdf", ".docx", ".pptx", ".xlsx", ".jpg", ".jpeg", ".png"]);
  assert.equal(attachmentType("Deck.PPTX"), "application/vnd.openxmlformats-officedocument.presentationml.presentation");
  assert.equal(attachmentType("Pricing.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  // Office files download through the logged-in file request (no preview, no conversion service)
  assert.deepEqual(PREVIEW_TYPES, ["application/pdf", "image/jpeg", "image/png"]);
  // added while open and once Won; never after Lost. Deleting stays limited to open deals.
  assert.deepEqual(ATTACHMENT_UPLOAD_STAGES, ["Opportunity", "Discovery", "Proposal", "Won"]);
  assert.deepEqual(ATTACHMENT_STAGES, ["Opportunity", "Discovery", "Proposal"]);
  assert.match(ATTACHMENT_TYPES_TEXT, /PowerPoint \(\.pptx\), Excel \(\.xlsx\)/);
  assert.match(ATTACHMENT_LEGACY_TEXT, /\.ppt or \.xls files: save them as \.pptx or \.xlsx/);
  // the popups take the same files, still five at a time
  const file = (name) => ({ name, size: 10, lastModified: 1 });
  const picked = pickStageFiles([], ["a.pptx", "b.xlsx", "c.pdf", "d.docx", "e.png", "f.jpg"].map(file));
  assert.equal(picked.files.length, STAGE_FILES_MAX);
  assert.match(picked.problems[0], /f\.jpg: up to 5 files/);
  const attachments = source("./Attachments.jsx");
  assert.match(attachments, /const canUpload = canEdit && ATTACHMENT_UPLOAD_STAGES\.includes\(opportunity\.stage\);/);
  assert.match(attachments, /canEdit &&\s+ATTACHMENT_STAGES\.includes\(opportunity\.stage\) &&/); // delete: open deals only
  assert.match(attachments, /\{ATTACHMENT_TYPES_TEXT\} • 20 MB per file\. \{ATTACHMENT_LEGACY_TEXT\}/);
  assert.match(attachments, /\{ATTACHMENT_TYPES_TEXT\} • 20 MB per file • up to \{STAGE_FILES_MAX\} files\. \{ATTACHMENT_LEGACY_TEXT\}/);
  assert.match(attachments, /"application\/vnd\.openxmlformats-officedocument\.presentationml\.presentation": "PowerPoint"/);
  // an obvious route: Add Files in the Activity tab, for people who may edit an open or Won opportunity
  const record = source("./RecordPage.jsx");
  assert.match(record, /!lead && canEdit && ATTACHMENT_UPLOAD_STAGES\.includes\(item\.stage\)\s+\? \(\) => window\.dispatchEvent\(new Event\(PICK_ATTACHMENTS\)\)/);
  assert.match(record, /<ObjectIcon type="note" size=\{18\} \/> Add Files/);
});

test("Leads Kanban pages: a new query starts every column at its first page, Previous / Next move one column", () => {
  const base = { view: "all_open", stage: "", filters: {}, search: "", sort: { col: "created", dir: "desc" }, size: 15 };
  const key = boardQueryKey(base);
  for (const change of [{ view: "all" }, { stage: "Demo" }, { filters: { source: "Upload" } }, { search: "acme" },
    { sort: { col: "name", dir: "desc" } }, { sort: { col: "created", dir: "asc" } }, { size: 25 }])
    assert.notEqual(boardQueryKey({ ...base, ...change }), key, JSON.stringify(change));
  let state = withColumnPage({ key: "", pages: {} }, key, "Demo", 2);
  state = withColumnPage(state, key, "New", 6);
  assert.deepEqual(boardPages(state, key), { Demo: 2, New: 6 });
  assert.deepEqual(boardPages(state, boardQueryKey({ ...base, search: "acme" })), {}); // new query: first pages
  assert.deepEqual(withColumnPage(state, "other", "Demo", 1), { key: "other", pages: { Demo: 1 } });
  // 549 synthetic leads, 120 at Demo: every card is reachable
  assert.deepEqual(columnRange(0, 15, 120), { pages: 8, range: "1–15 of 120", pageText: "Page 1 of 8" });
  assert.deepEqual(columnRange(7, 15, 120), { pages: 8, range: "106–120 of 120", pageText: "Page 8 of 8" });
  assert.equal(columnRange(1, 100, 101).range, "101–101 of 101"); // the 101st card has a page
  assert.equal(columnRange(0, 15, 50001).pageText, "Page 1 of 3,334");
  assert.equal(columnRange(0, 15, 0).range, "No leads");
  assert.equal(clampPage(7, 104, 15), 6); // a stage change moved cards out: back to the last page
});

test("Leads Kanban: only the latest request of a column is shown", () => {
  const requests = latestRequests();
  const first = requests.start("Demo");
  const second = requests.start("Demo"); // Next pressed again, or the search changed
  const other = requests.start("New");
  assert.equal(requests.isLatest("Demo", first), false); // the slow first answer is dropped
  assert.equal(requests.isLatest("Demo", second), true);
  assert.equal(requests.isLatest("New", other), true);
  requests.forgetAll(); // a new board query: every earlier answer is dropped
  assert.equal(requests.isLatest("Demo", second), false);
  assert.equal(requests.isLatest("New", other), false);
});

test("Leads Kanban: every column pages through the server query, with the List page's filters and page sizes", () => {
  const table = source("./LeadsTable.jsx");
  assert.doesNotMatch(table, /BOARD_CARDS|limit: 100/); // no fixed first 100 cards
  assert.match(table, /load\(\{ stage: column, offset: at \* cardSize, limit: cardSize \}\)/);
  assert.match(table, /if \(!requests\.current\.isLatest\(column, id\)\) return;/);
  assert.match(table, /const fixed = clampPage\(at, r\.total, cardSize\);/);
  assert.match(table, /\{defs\.map\(\(def\) => \(\s+<FilterButton key=\{def\.key\} def=\{def\} values=\{filters\} onChange=\{onFilter\} \/>/);
  assert.match(table, /\{PAGE_SIZES\.map\(\(n\) => \(/);
  assert.match(table, /<span>Cards per column<\/span>/);
  assert.match(table, /<span>Sort by<\/span>/);
  // a saved stage change (refresh) reloads every column at its page; Try again too
  assert.match(table, /const reload = `\$\{refresh\}\|\$\{again\}`;/);
  const board = source("./LeadsKanban.jsx");
  assert.match(board, /aria-label=\{`Previous page of \$\{stage\}`\}/);
  assert.match(board, /aria-label=\{`Next page of \$\{stage\}`\}/);
  assert.match(board, /<b>\{range\.range\}<\/b>/);
  assert.match(board, /\{excluded \? stage : `\$\{stage\} \(\$\{column \? column\.total\.toLocaleString\(\) : "…"\}\)`\}/);
  // drag and drop and the Change Status menu still open the usual popups (nothing moves until it's saved)
  assert.match(board, /draggable=\{options\.length > 0\}/);
  assert.match(board, /label="Change Status"/);
  const filters = source("./Filters.jsx");
  assert.match(filters, /export const FilterButton = \(props\) => <HeaderFilter \{\.\.\.props\} pill \/>;/);
});

// ---------- vikram-fixes2 follow-up: Leads date choices and the Kanban sort ----------

test("Leads date choices: Today, Last week (Monday to Sunday) and Last month, in local time", () => {
  assert.deepEqual(LEAD_DATE_RANGES, [["today", "Today"], ["lastweek", "Last week"], ["lastmonth", "Last month"]]);
  const iso = ([start, end]) => [start, end].map((d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:00`);
  const saved = process.env.TZ;
  try {
    for (const tz of ["Asia/Kolkata", "America/New_York"]) {
      process.env.TZ = tz;
      const at = (y, m, d, h = 15) => new Date(y, m - 1, d, h, 30);
      // a Monday, a Wednesday and a Sunday of the week 9-15 Nov 2026: last week is Mon 2 - Sun 8 Nov (to Mon 9, exclusive)
      for (const now of [at(2026, 11, 9, 0), at(2026, 11, 11), at(2026, 11, 15, 23)])
        assert.deepEqual(iso(dateRangeBounds("lastweek", "", "", now)), ["2026-11-02 00:00", "2026-11-09 00:00"], `${tz} ${now}`);
      // across a month and a year end, and over New York's clock change (1 Nov 2026): still midnight to midnight
      assert.deepEqual(iso(dateRangeBounds("lastweek", "", "", at(2027, 1, 6))), ["2026-12-28 00:00", "2027-01-04 00:00"], tz);
      assert.deepEqual(iso(dateRangeBounds("lastweek", "", "", at(2026, 11, 4))), ["2026-10-26 00:00", "2026-11-02 00:00"], tz);
      // last month: the previous complete calendar month (also from the first and the last day of a month)
      assert.deepEqual(iso(dateRangeBounds("lastmonth", "", "", at(2026, 11, 10))), ["2026-10-01 00:00", "2026-11-01 00:00"], tz);
      assert.deepEqual(iso(dateRangeBounds("lastmonth", "", "", at(2027, 1, 1, 0))), ["2026-12-01 00:00", "2027-01-01 00:00"], tz);
      assert.deepEqual(iso(dateRangeBounds("lastmonth", "", "", at(2026, 3, 31, 23))), ["2026-02-01 00:00", "2026-03-01 00:00"], tz);
      assert.deepEqual(iso(dateRangeBounds("today", "", "", at(2026, 11, 10))), ["2026-11-10 00:00", "2026-11-11 00:00"], tz);
      // custom: From and To days, the To day included
      assert.deepEqual(iso(dateRangeBounds("custom", "2026-11-02", "2026-11-08")), ["2026-11-02 00:00", "2026-11-09 00:00"], tz);
    }
  } finally {
    if (saved === undefined) delete process.env.TZ;
    else process.env.TZ = saved;
  }
  // the chips and the summary name the new choices
  const created = { key: "created", label: "Created", type: "date", ranges: LEAD_DATE_RANGES };
  assert.equal(filterText(created, { created: "lastweek" }), "Created: Last week");
  assert.equal(chipText(created, { created: "lastmonth" }), "Created: Last month");
});

test("Leads: a saved date filter the page no longer offers is not applied (no invisible filter)", () => {
  const created = { key: "created", label: "Created", type: "date", ranges: LEAD_DATE_RANGES };
  for (const removed of ["last7", "last30", "week", "month", "quarter", "year", "nonsense"])
    assert.equal(dateFilterOffered(created, { created: removed }), false, removed);
  for (const offered of ["today", "lastweek", "lastmonth"]) assert.equal(dateFilterOffered(created, { created: offered }), true);
  assert.equal(dateFilterOffered(created, { created: "custom", created_from: "2026-11-01" }), true);
  assert.equal(dateFilterOffered(created, { created: "custom" }), false); // a custom range without dates
  // other lists keep their own choices
  assert.equal(dateFilterOffered({ key: "created", type: "date" }, { created: "last7" }), true);
  const list = source("./ListView.jsx");
  assert.match(list, /\{ \.\.\.created, ranges: LEAD_DATE_RANGES \},\s+\{ \.\.\.modified, ranges: LEAD_DATE_RANGES \},/);
  assert.match(list, /if \(f\.type === "date" && !dateFilterOffered\(f, values\)\) continue;/);
  // the List headers and the Kanban buttons use the same menu: Any time, the choices, then Custom range
  const filters = source("./Filters.jsx");
  assert.match(filters, /def\.type === "date" \? def\.ranges \|\| \(def\.future \? FUTURE : PAST\)/);
  assert.match(filters, /\{def\.type === "date" \? "Any time" : "All"\}/);
  assert.match(filters, /<p className="th-menu-label">Custom range<\/p>/);
  assert.match(filters, /max=\{custom\.to \|\| undefined\}/); // From can't be after To
  assert.match(filters, /min=\{custom\.from \|\| undefined\}/);
});

test("Leads Kanban: Sort by only, each field in its default order; the summary names the order", () => {
  assert.equal(defaultSortDirection("created"), "desc");
  assert.equal(defaultSortDirection("modified"), "desc");
  assert.equal(defaultSortDirection("name"), "asc");
  assert.equal(defaultSortDirection("owner"), "asc");
  assert.equal(sortText("Created", "created", defaultSortDirection("created")), "Sorted by Created, newest first");
  assert.equal(sortText("Name", "name", defaultSortDirection("name")), "Sorted by Name, A–Z");
  const table = source("./LeadsTable.jsx");
  assert.doesNotMatch(table, /board-direction|Reverse the order/);
  assert.match(table, /onChange=\{\(e\) => setSort\(\{ col: e\.target\.value, dir: defaultSortDirection\(e\.target\.value\) \}\)\}/);
  assert.match(table, /const \[sort, setSort\] = useState\(\{ col: "created", dir: "desc" \}\);/); // the page still opens newest first
  assert.match(table, /sort: sortText\(sortLabel, sort\.col, sort\.dir\)/); // the summary under the title
});

test("Home period: Past 1 week counts up to now, a custom range has an end", async () => {
  const { PERIODS, DEFAULT_PERIOD, periodRange, periodQuery, periodLabel, localIso } = await import("./homePeriod.js");
  assert.deepEqual(PERIODS, [["7d", "Past 1 week"], ["custom", "Custom range"]]);
  assert.deepEqual(DEFAULT_PERIOD, { preset: "7d" });
  const now = new Date(2026, 10, 12, 15, 30, 0); // Nov 12, 2026 3:30 PM
  assert.equal(localIso(periodRange({ preset: "7d" }, now).start), "2026-11-05T15:30:00");
  assert.equal(localIso(periodRange({ preset: "1m" }, now).start), "2026-11-05T15:30:00"); // an older choice: 1 week
  assert.equal(periodQuery({ preset: "7d" }, now), "start=2026-11-05T15%3A30%3A00");
  const custom = { preset: "custom", from: "2026-01-01T09:00", to: "2026-02-01T18:00" };
  assert.equal(periodQuery(custom, now), "start=2026-01-01T09%3A00%3A00&end=2026-02-01T18%3A00%3A00");
  // a custom range that ends before it starts falls back to Past 1 week
  assert.equal(localIso(periodRange({ ...custom, to: "2025-01-01T00:00" }, now).start), "2026-11-05T15:30:00");
  assert.equal(periodLabel("2026-11-05T15:30:00", "2026-11-12T15:30:00"), "Nov 5 – Nov 12, 2026");
});

test("Home: one dashboard per role, each card with its permission", async () => {
  const fs = await import("node:fs");
  const home = fs.readFileSync(new URL("./SellerHome.jsx", import.meta.url), "utf8");
  for (const title of ["Action Needed", "Scheduled Demos", "Overall Value", "Closing Soon", "Follow-up Radar", "My Scorecard",
    "Recent Activity", "Team Performance", "Win/Loss Analysis", "Lead Sources"])
    assert.ok(home.includes(title), title);
  for (const old of ["Top Opportunities", "Suggested Actions", "Campaign Performance", "Lead Funnel", "Coaching Alerts",
    "Data Health", "Open deals by stage", "in this period", "My Pipeline", "Team Leaderboard", "Team Comparison", "manager_id"])
    assert.ok(!home.includes(old), old);
  for (const card of ["action_items", "meetings", "pipeline", "follow_up_radar", "scorecard", "recent_activity", "win_loss",
    "team_performance"])
    assert.ok(home.includes(`shows("${card}")`), card);
  // the Admin's own cards (every record, no team picker); Closing Soon is the Admin's only
  assert.match(home, /isAdmin && charts\.lead_sources/);
  assert.match(home, /isAdmin && charts\.closing_soon && <ClosingSoonCard/);
  assert.match(home, /isAdmin && <RadarCard/);
  assert.match(home, /isAdmin && charts\.recent_records && <RecentCard/); // not on the Manager's My Team view
  assert.match(home, /!isAdmin && shows\("team_performance"\)/);
  assert.equal(home.match(/<Section title="Today"/g).length, 2);
  assert.equal(home.match(/<Section title="Upcoming"/g).length, 2);
});


test("Lead transfer requests, the lead list's Created By / Transferred To, and duplicate warnings", () => {
  const table = source("./LeadsTable.jsx");
  assert.doesNotMatch(table, /"Created By"/); // the owner who added a lead is its Owner: only Owner and Transferred To
  assert.match(table, /\["Transferred To", "transferred", \d+\]/);
  assert.match(table, /l\.last_transferred_to/);
  const api = source("./api.js");
  for (const path of ["/transfer-requests`", "/transfer-requests?box=", "/cancel`", "/accounts/duplicates?", "/contacts/duplicates?"])
    assert.ok(api.includes(path), path);
  const record = source("./RecordPage.jsx");
  assert.match(record, /label: "Request Transfer"/); // anyone but the Admin, on someone else's open lead
  assert.match(record, /user\.role !== "Admin" && item\.owner_id !== user\.id/);
  const modal = source("./Modal.jsx");
  assert.match(modal, /Request Transfer from \{askFor\.owner_name\}/); // from the "email already in the CRM" message
  assert.match(modal, /\(dupes\.length > 0 && newRecord\)/); // New Account / Contact: no save over a duplicate
  const page = source("./TransferRequests.jsx");
  for (const tab of ["To Approve", "My Requests", "All"]) assert.ok(page.includes(`"${tab}"`), tab);
  assert.match(source("./App.jsx"), /section === "transfer-requests"/);
});

// ---------- vikram-crm-followups: Lead Source and the New Lead / Edit Lead rules ----------

test("Lead Source: LinkedIn is offered on the form and in the Source filter; Upload stays upload-only", () => {
  assert.ok(LEAD_SOURCES.includes("LinkedIn"));
  assert.ok(!LEAD_SOURCES.includes(UPLOAD_SOURCE)); // not offered on the New Lead form
  assert.match(source("./ListView.jsx"), /\{ key: "source", label: "Lead Source", options: opts\(\[\.\.\.LEAD_SOURCES, UPLOAD_SOURCE\]\) \}/);
  const backend = readFileSync(new URL("../../backend/app/constants.py", import.meta.url), "utf8");
  const listed = backend.match(/^LEAD_SOURCES = \[([^\]]*)\]/m)[1].match(/"([^"]+)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual(listed, [...LEAD_SOURCES, UPLOAD_SOURCE]); // the same list, in the same order, as the API
  assert.match(backend, new RegExp(`LEAD_SOURCE_DETAIL_MAX = ${SOURCE_DETAIL_MAX}\\b`));
});

test("New Lead: First Name, Specify lead source (Other), LinkedIn Profile URL (LinkedIn) are required", () => {
  const ok = { first_name: "Ana", last_name: "Okafor", company: "Harbor", email: "ana@harbor.example", source: "Website" };
  assert.deepEqual(leadFormProblems(ok), {});
  // First Name: empty or only spaces
  for (const first_name of ["", "   ", "\t"]) assert.equal(leadFormProblems({ ...ok, first_name }).first_name, LEAD_FIRST_NAME_REQUIRED);
  // every source works; Other and LinkedIn ask for their own value
  for (const source of LEAD_SOURCES.filter((s) => !["Other", "LinkedIn"].includes(s))) assert.deepEqual(leadFormProblems({ ...ok, source }), {}, source);
  for (const source_detail of [undefined, "", "   "])
    assert.equal(leadFormProblems({ ...ok, source: "Other", source_detail }).source_detail, SOURCE_DETAIL_REQUIRED);
  assert.deepEqual(leadFormProblems({ ...ok, source: "Other", source_detail: "Trade fair 2026" }), {});
  assert.match(leadFormProblems({ ...ok, source: "Other", source_detail: "x".repeat(SOURCE_DETAIL_MAX + 1) }).source_detail, /at most 100/);
  assert.equal(leadFormProblems({ ...ok, source: "LinkedIn" }).linkedin_url, LINKEDIN_PROFILE_REQUIRED);
  assert.equal(leadFormProblems({ ...ok, source: "LinkedIn", linkedin_url: "   " }).linkedin_url, LINKEDIN_PROFILE_REQUIRED);
  assert.deepEqual(leadFormProblems({ ...ok, source: "LinkedIn", linkedin_url: "https://www.linkedin.com/in/ana-okafor" }), {});
  // the LinkedIn Profile URL is optional for every other source; a description typed for Other doesn't matter elsewhere
  assert.deepEqual(leadFormProblems({ ...ok, source: "Referral", linkedin_url: "", source_detail: "" }), {});
  assert.deepEqual(leadFieldsRequired("Website"), { first_name: true, source_detail: false, linkedin_url: false });
  assert.deepEqual(leadFieldsRequired("Other"), { first_name: true, source_detail: true, linkedin_url: false });
  assert.deepEqual(leadFieldsRequired("LinkedIn"), { first_name: true, source_detail: false, linkedin_url: true });
});

test("Lead form: Company Website and Company LinkedIn URL are optional, but checked when given", () => {
  const ok = { first_name: "Ana", last_name: "Okafor", company: "Harbor", email: "ana@harbor.example", source: "Website" };
  assert.deepEqual(leadFormProblems({ ...ok, company_website: "", company_linkedin_url: "" }), {});
  assert.deepEqual(leadFormProblems({ ...ok, company_website: "harbor.example", company_linkedin_url: "linkedin.com/company/harbor" }), {});
  assert.equal(leadFormProblems({ ...ok, company_website: "harbor" }).company_website, "Enter a valid web address");
  assert.equal(leadFormProblems({ ...ok, company_website: "harbor .example" }).company_website, "Enter a valid web address");
  assert.equal(leadFormProblems({ ...ok, company_linkedin_url: "https://harbor.example/about" }).company_linkedin_url,
    "Enter a LinkedIn address (linkedin.com/...)");
  assert.equal(leadFormProblems({ ...ok, linkedin_url: "https://linkedin.com.example.test/in/ana" }).linkedin_url,
    "Enter a LinkedIn address (linkedin.com/...)");
  // the same rule as the API's clean_url
  assert.equal(webAddressProblem("https://uk.linkedin.com/company/x", { linkedin: true }), "");
  assert.equal(webAddressProblem("ftp://example.com"), "Enter a valid web address");
  assert.equal(webAddressProblem("  "), "");
});

test("Edit Lead: an older lead's missing First Name, Other description or LinkedIn URL doesn't block an unrelated edit", () => {
  const legacy = { id: 9, first_name: null, last_name: "Okafor", source: "Other", source_detail: null, linkedin_url: null };
  const form = { first_name: "", last_name: "Okafor", company: "Harbor", email: "ana@harbor.example", source: "Other", source_detail: "" };
  assert.deepEqual(leadFormProblems(form, legacy), {}); // e.g. only the phone changed
  assert.deepEqual(leadFieldsRequired("Other", legacy), { first_name: false, source_detail: false, linkedin_url: false });
  // ...but a value the lead has can't be removed, and changing the source asks for what that source needs
  const named = { ...legacy, first_name: "Ana", source_detail: "Trade fair" };
  assert.equal(leadFormProblems({ ...form, source_detail: "Trade fair" }, named).first_name, LEAD_FIRST_NAME_REQUIRED);
  assert.equal(leadFormProblems({ ...form, first_name: "Ana", source_detail: "  " }, named).source_detail, SOURCE_DETAIL_REQUIRED);
  const website = { ...legacy, source: "Website" };
  assert.equal(leadFormProblems({ ...form, source: "Other" }, website).source_detail, SOURCE_DETAIL_REQUIRED);
  assert.equal(leadFormProblems({ ...form, source: "LinkedIn" }, website).linkedin_url, LINKEDIN_PROFILE_REQUIRED);
  // an uploaded LinkedIn lead without a profile: other edits save; removing a saved profile doesn't
  const uploaded = { ...legacy, source: "LinkedIn" };
  assert.deepEqual(leadFormProblems({ ...form, source: "LinkedIn" }, uploaded), {});
  assert.equal(
    leadFormProblems({ ...form, source: "LinkedIn", linkedin_url: "" }, { ...uploaded, linkedin_url: "https://linkedin.com/in/ana" }).linkedin_url,
    LINKEDIN_PROFILE_REQUIRED,
  );
});

test("Lead form wiring: required stars follow the rules; Specify lead source shows for Other; one LinkedIn field", () => {
  const modal = source("./Modal.jsx");
  assert.match(modal, /field\("First Name", "first_name", "text", leadNeeds\.first_name\)/);
  assert.match(modal, /leadSource === "Other" &&\s*field\("Specify lead source", "source_detail", "text", leadNeeds\.source_detail, record\?\.source_detail \?\? ""\)/);
  assert.match(modal, /required=\{leadNeeds\.linkedin_url\}/);
  assert.match(modal, /field\("Company Website", "company_website", "text", false\)/);
  assert.match(modal, /field\("Company LinkedIn URL", "company_linkedin_url", "text", false\)/);
  assert.match(modal, /const problems = leadFormProblems\(v, record\);/);
  assert.doesNotMatch(modal, /\["linkedin_url", "LinkedIn Profile URL"\],\s*\["company_website"/); // no longer always required
  assert.match(modal, /name === "source_detail"\s*\? SOURCE_DETAIL_MAX/); // bounded like the database column
  // the LinkedIn Profile URL stays one field, with Apollo autofill on New Lead (looked up only when a profile is pasted)
  const leadForm = modal.slice(modal.indexOf('{type === "lead" && ('), modal.indexOf('{type === "newOpportunity" && ('));
  assert.equal((leadForm.match(/name="linkedin_url"|"linkedin_url", "text"/g) || []).length, 0);
  assert.equal((modal.match(/<LinkedInField/g) || []).length, 2); // one on the lead form, one on New Contact
  const field = source("./LeadAutofill.jsx");
  assert.match(field, /required=\{required\}/);
  assert.match(field, /label = "LinkedIn Profile URL",/);
  assert.match(field, /\{label\}\{required && <i> \*<\/i>\}/);
  assert.match(field, /onPaste=\{autofill \? /);
  // the lead page shows what an Other source is
  assert.match(source("./RecordPage.jsx"), /item\.source === "Other" && item\.source_detail \? ` \(\$\{item\.source_detail\}\)` : ""/);
});

test("Account page has no Send Email (for every role); leads, opportunities and contacts keep theirs; history stays", () => {
  const related = source("./RelatedPages.jsx");
  const accountPage = related.slice(related.indexOf("export function AccountPage"), related.indexOf("export function ContactPage"));
  const contactPage = related.slice(related.indexOf("export function ContactPage"));
  assert.doesNotMatch(accountPage, /Send Email|openEmail|field: "account_id"/); // no role check: it isn't rendered at all
  assert.match(accountPage, /useEmails\("account_id", account\?\.id, emailVersion\)/); // the account's email history...
  assert.match(accountPage, /<EmailList emails=\{emails\} \/>/); // ...is still listed
  assert.match(contactPage, /openEmail\(\{\s*type: "contact",\s*field: "contact_id"/);
  assert.match(contactPage, /Send Email/);
  assert.match(source("./RecordPage.jsx"), /Send Email/); // leads and opportunities
  assert.doesNotMatch(source("./App.jsx"), /<AccountPage[^>]*openEmail/);
  assert.match(source("./App.jsx"), /<ContactPage[^>]*openEmail=\{openEmail\}/);
});

test("Opportunities table: Client POC is a label only; Account Name stays Account Name", () => {
  const list = source("./ListView.jsx");
  const start = list.indexOf('["Opportunity Name"'); // the Opportunities table's columns
  const opps = list.slice(start, list.indexOf("accounts: [", start));
  assert.match(opps, /\["Client POC", \(r\) => r\.lead_name \|\| "", \(r\) => r\.lead_id && r\.lead_name \? <a href=\{`#\/leads\/\$\{r\.lead_id\}`\}>\{r\.lead_name\}<\/a> : "—"\]/);
  assert.match(opps, /\["Account Name", \(r\) => r\.account_name \|\| "", account\]/); // value and link unchanged
  assert.doesNotMatch(opps, /Client Name|Account POC/);
  // sorting is by column position and the Opportunities filters don't use these columns, so both keep working
  assert.match(list, /const get = cols\[sort\.col\]\[1\];/);
  // the Accounts and Contacts tables and the board's cards keep "Account Name" too
  assert.match(list, /\["Account Name", \(r\) => r\.name, \(r\) => link\(r, r\.name\)\]/);
  assert.equal((list.match(/\["Account Name", \(r\) => r\.account_name \|\| "", account\]/g) || []).length, 2); // Opportunities, Contacts
  assert.match(list, /<dt>Account Name<\/dt>/); // the opportunity board's cards
});

// ---------- issues 2, 3 and 7: New Account, New Contact and New Opportunity > New contact ----------

test("Phone: country-aware checks, India by default; spaces, brackets and hyphens are fine; blank is fine", () => {
  assert.equal(DEFAULT_PHONE_COUNTRY, "IN");
  assert.equal(phoneCountryLabel("IN"), "India (+91)");
  assert.equal(phoneProblem(""), "");
  assert.equal(phoneProblem("   "), "");
  for (const ok of ["98765 43210", "98765-43210", "(98765) 43210", "098765 43210", "+91 98765 43210"])
    assert.equal(phoneProblem(ok, "IN"), "", ok);
  for (const bad of ["12345", "98765 4321", "98765 432100", "phone 98765 43210", "98765 43210 ext. 4"])
    assert.equal(phoneProblem(bad, "IN"), "Enter a valid phone number for India (+91).", bad);
  // not every country has ten digits
  assert.equal(phoneProblem("020 7946 0958", "GB"), "");
  assert.equal(phoneProblem("030 901820", "DE"), "");
  assert.equal(phoneProblem("2 9876 5432", "AU"), "");
  assert.equal(phoneProblem("6123 4567", "SG"), "");
  assert.equal(phoneProblem("6123 4567", "IN"), "Enter a valid phone number for India (+91).");
  // the chosen country decides a number without +: a US number isn't a Canadian one, though both are +1
  assert.equal(phoneProblem("(212) 555-0142", "US"), "");
  assert.equal(phoneProblem("(212) 555-0142", "CA"), "Enter a valid phone number for Canada (+1).");
  assert.equal(phoneProblem("(416) 555-0142", "CA"), "");
  // with +, the number's own country code decides
  assert.equal(phoneProblem("+44 20 7946 0958", "IN"), "");
  assert.equal(phoneProblem("+91 12345", "IN"), PHONE_WITH_CODE_INVALID);
  assert.equal(phoneCountryOf("+1 416 555 0142"), "CA");
  assert.equal(phoneCountryOf("98765 43210"), ""); // no country without +
  assert.equal(phoneProblem("98765 43210", "ZZ"), "Choose the phone number's country.");
});

test("Phone country list: every country with its name and calling code; shared codes stay apart by name", () => {
  const labels = PHONE_COUNTRIES.map((c) => `${c.name} (${c.dial})`);
  assert.ok(PHONE_COUNTRIES.length > 200);
  assert.equal(new Set(labels).size, labels.length); // no two options look the same
  for (const label of ["India (+91)", "United States (+1)", "Canada (+1)", "United Kingdom (+44)", "Russia (+7)", "Kazakhstan (+7)"])
    assert.ok(labels.includes(label), label);
  assert.deepEqual([...PHONE_COUNTRIES.map((c) => c.name)], [...PHONE_COUNTRIES.map((c) => c.name)].sort((a, b) => a.localeCompare(b, "en")));
});

test("New Opportunity > New contact: the same rules as New Contact, on the form's own field names", () => {
  const F = OPPORTUNITY_CONTACT_FORM;
  const ok = { contact_first_name: "Ana", contact_last_name: "Okafor", contact_email: "ana@harbor.example" };
  assert.deepEqual(contactProblems(ok, F), {});
  assert.deepEqual(Object.keys(contactProblems({}, F)), ["contact_first_name", "contact_last_name", "contact_email"]);
  assert.equal(contactProblems({ ...ok, contact_email: "ana@harbor" }, F).contact_email, CONTACT_EMAIL_INVALID);
  assert.deepEqual(contactProblems({ ...ok, contact_phone: "" }, F), {});
  assert.equal(contactProblems({ ...ok, contact_phone: "555 0142", contact_phone_country: "US" }, F).contact_phone,
    "Enter a valid phone number for United States (+1).");
  assert.deepEqual(contactProblems({ ...ok, contact_phone: "(212) 555-0142", contact_phone_country: "US" }, F), {});
  assert.match(contactProblems({ ...ok, contact_linkedin_url: "lnkd.in/abc" }, F).contact_linkedin_url, /linkedin/i);
  // and New Contact checks exactly the same things
  const same = { first_name: "Ana", last_name: "Okafor", email: "ana@harbor.example", phone: "555 0142", phone_country: "US" };
  assert.deepEqual(Object.values(contactProblems(same, CONTACT_FORM)), Object.values(contactProblems(
    { contact_first_name: "Ana", contact_last_name: "Okafor", contact_email: "ana@harbor.example", contact_phone: "555 0142", contact_phone_country: "US" }, F)));
});

test("Contact autofill fills only the person's details, never typed values, and maps them to each form's fields", () => {
  const fields = contactAutofillFields(OPPORTUNITY_CONTACT_FORM);
  assert.deepEqual(fields, { contact_first_name: "First Name", contact_last_name: "Last Name", contact_title: "Title",
    contact_email: "Email", contact_phone: "Phone" });
  assert.deepEqual(Object.keys(contactAutofillFields(CONTACT_FORM)), ["first_name", "last_name", "job_title", "email", "phone"]);
  // Apollo's contact answer in the form's names; anything else (a company) is never mapped
  const incoming = contactAnswerFields({ first_name: "Ana", job_title: "CTO", email: "ana@harbor.example", company: "Other Co" },
    OPPORTUNITY_CONTACT_FORM);
  assert.deepEqual(incoming, { contact_first_name: "Ana", contact_title: "CTO", contact_email: "ana@harbor.example" });
  // the user's typed last name and email stay; empty fields are filled
  const plan = autofillPlan({ contact_first_name: "", contact_last_name: "Okafor", contact_email: "mine@harbor.example" }, {},
    incoming, fields);
  assert.deepEqual(plan.set, { contact_first_name: "Ana", contact_title: "CTO" });
  assert.deepEqual(plan.kept, ["contact_email"]);
  assert.equal(autofillSummary(plan, fields).text.includes("Filled by Apollo: First Name, Title."), true);
  assert.match(autofillSummary({ filled: ["contact_email"], kept: [] }, fields).email, /^Email verification status is provided by Apollo/);
  // the lead form's autofill is unchanged
  assert.deepEqual(Object.keys(autofillPlan({}, {}, { company: "Acme" }).set), ["company"]);
});

test("Contact autofill wiring: lookup keyed by profile and account, late answers dropped, account never changed", () => {
  const field = source("./LeadAutofill.jsx");
  assert.match(field, /const keyOf = \(url\) => \(companyNow === undefined \? url : `\$\{url\}\\n\$\{companyNow\}`\);/);
  assert.match(field, /if \(alive\.current && current\.current === key\) show\(answer, url\);/); // late answers are ignored
  assert.match(field, /if \(url !== filledFor\.current\) apply\(\{\}\);/); // a failed re-check keeps what it filled
  assert.match(field, /status\.employerMatches === false/); // another employer: a clear warning, the account is kept
  assert.match(field, /Apollo lists \$\{status\.employer\} as this person's employer, not \$\{status\.company\}\. Check it's the right person\./);
  assert.doesNotMatch(field.slice(field.indexOf("const apply")), /account_id|setAccount/); // never picks an account
  const modal = source("./Modal.jsx");
  assert.match(modal, /lookup=\{\(url, company\) => api\.enrichContact\(url, company\)\}/);
  assert.match(modal, /needed=\{\[CONTACT_FORM\.first_name, CONTACT_FORM\.last_name, CONTACT_FORM\.email\]\}/);
  assert.match(source("./api.js"), /enrichContact: \(linkedinUrl, company\) => lookupProfile\(linkedinUrl, "\/contacts\/enrichment", \{ company: company \|\| null \}\)/);
});

test("New Account and New Contact forms: the agreed fields", () => {
  const modal = source("./Modal.jsx");
  const account = modal.slice(modal.indexOf('{type === "account" && ('), modal.indexOf('{type === "contact" && ('));
  assert.doesNotMatch(account, /"Phone"|"phone"/); // no Phone on New Account
  assert.doesNotMatch(account, /"Address"|"address"/); // nor Address (older accounts keep theirs)
  for (const f of [/field\("Account Name", "name", "text", true, ""\)/, /field\("Industry", "industry", "text", true, ""\)/,
    /field\("Website", "website", "text", false, ""\)/, /field\("Company LinkedIn URL", "linkedin_url", "text", false, ""\)/,
    /\{owner\(\)\}/])
    assert.match(account, f);
  const contact = modal.slice(modal.indexOf('{type === "contact" && ('), modal.indexOf('{type === "lead" && ('));
  for (const f of [/field\("First Name", "first_name", "text", true, ""\)/, /field\("Last Name", "last_name", "text", true, ""\)/,
    /field\("Email", "email", "email", true, ""\)/, /<PhoneField /, /<LinkedInField/, /"Account Name",\s*"account_id"/])
    assert.match(contact, f);
  const api = source("./api.js");
  const saveAccount = api.slice(api.indexOf("saveAccount:"), api.indexOf("saveContact:"));
  assert.doesNotMatch(saveAccount, /phone/);
  assert.match(saveAccount, /linkedin_url: optional\(v\.linkedin_url\?\.trim\(\)\)/);
  const saveContact = api.slice(api.indexOf("saveContact:"), api.indexOf("login:"));
  assert.match(saveContact, /phone_country: v\.phone_country \|\| "IN"/);
  assert.match(saveContact, /linkedin_url: optional\(v\.linkedin_url\?\.trim\(\)\)/);
  const phoneField = source("./PhoneField.jsx");
  assert.match(phoneField, /defaultValue=\{DEFAULT_PHONE_COUNTRY\}/);
  assert.match(phoneField, /\{country\.name\} \(\{country\.dial\}\)/);
});

test("New Opportunity > New contact: shown only for a new contact; existing contacts are reused with no lookup", () => {
  const opp = source("./NewOpportunity.jsx");
  assert.match(opp, /const showNewContact = newContact && !!\(accountId \|\| !accounts\.length\);/);
  assert.match(opp, /\{showNewContact && \(\s*<fieldset className="stage-task" ref=\{contactBox\}>/);
  assert.match(opp, /<LinkedInField[\s\S]*?company=\{company\}[\s\S]*?write=\{writeContact\}|<LinkedInField[\s\S]*?write=\{writeContact\}[\s\S]*?company=\{company\}/);
  assert.match(opp, /required: true, maxLength: 50, error: errors\[F\.first_name\]/);
  assert.match(opp, /required: true, maxLength: 50, error: errors\[F\.last_name\]/);
  assert.match(opp, /type: "email", required: true, maxLength: 255, error: errors\[F\.email\]/);
  assert.match(opp, /<PhoneField name=\{F\.phone\} countryName=\{F\.phone_country\}/);
  // the account comes from the user's choice (or the company typed), never from Apollo
  assert.match(opp, /const company = existingAccount \? data\.accounts\.find\(\(a\) => a\.id === existingAccount\)\?\.name \|\| "" : accountName\.trim\(\);/);
  // the payload: an existing contact sends no new contact fields
  const payloadSource = opp.slice(opp.indexOf("export function newOpportunityPayload")).replace("export function", "function");
  const newOpportunityPayload = new Function(`${payloadSource}; return newOpportunityPayload;`)();
  const fromForm = (v) => newOpportunityPayload(v, {});
  const chosen = fromForm({ name: "Deal", account_id: "4", primary_contact_id: "9", contact_first_name: "x", contact_phone: "1" });
  assert.equal(chosen.primary_contact_id, 9);
  assert.equal(chosen.contact_first_name, null);
  assert.equal("contact_phone_country" in chosen, false);
  const fresh = fromForm({ name: "Deal", account_id: "4", primary_contact_id: "new", contact_first_name: "Ana",
    contact_last_name: "Okafor", contact_email: "ana@harbor.example", contact_phone: " 98765 43210 ", contact_phone_country: "IN",
    contact_linkedin_url: " linkedin.com/in/ana " });
  assert.deepEqual([fresh.contact_phone, fresh.contact_phone_country, fresh.contact_linkedin_url], ["98765 43210", "IN", "linkedin.com/in/ana"]);
  const modal = source("./Modal.jsx");
  assert.match(modal, /const problems = newContact \? contactProblems\(values, OPPORTUNITY_CONTACT_FORM\) : \{\};/);
  assert.match(modal, /errors=\{fieldErrors\}\s*onFix=\{clearError\}/);
});

// ---------- four focused follow-ups: LinkedIn source, visible phone errors, short LinkedIn text, no Address ----------

test("New Lead: a successful LinkedIn lookup selects LinkedIn only while the source is untouched or blank", () => {
  assert.equal(NEW_LEAD_DEFAULT_SOURCE, "Other");
  assert.equal(sourceAfterLinkedInMatch({ current: "Other" }), "LinkedIn"); // the form's untouched default
  assert.equal(sourceAfterLinkedInMatch({ current: "" }), "LinkedIn"); // blank
  assert.equal(sourceAfterLinkedInMatch({ current: "", chosen: true }), "LinkedIn"); // still blank
  assert.equal(sourceAfterLinkedInMatch({ current: "LinkedIn" }), null); // already LinkedIn
  // the user's own choice stays, including Other
  for (const current of ["Website", "Referral", "Event", "Other"]) assert.equal(sourceAfterLinkedInMatch({ current, chosen: true }), null, current);
  assert.equal(sourceAfterLinkedInMatch({ current: "Other", detail: "Trade fair" }), null); // an Other the user described
  assert.equal(sourceAfterLinkedInMatch({ current: "Other", detail: "   " }), "LinkedIn"); // spaces aren't a description
  // wiring: only after a verified match of the current address, on New Lead only; the user's pick is remembered
  const field = source("./LeadAutofill.jsx");
  const show = field.slice(field.indexOf("const show = "), field.indexOf("const lookup = "));
  assert.ok(show.indexOf("onMatched?.()") > show.indexOf('answer.status !== "matched" || answer.url_verified !== true'));
  assert.equal((field.match(/onMatched\?\.\(\)/g) || []).length, 1); // never after a failed, unmatched or late answer
  assert.match(field, /if \(alive\.current && current\.current === key\) show\(answer, url\);/);
  const modal = source("./Modal.jsx");
  assert.match(modal, /onMatched=\{linkedInMatched\}/);
  assert.match(modal, /sourceChosen\.current = true; \/\/ the user's choice/);
  assert.match(modal, /const next = sourceAfterLinkedInMatch\(\{ current: list\.value, chosen: sourceChosen\.current, detail: form\.elements\.source_detail\?\.value \}\);/);
  assert.match(modal, /setLeadSource\(next\);/); // Specify lead source hides; the LinkedIn URL rule follows the source
  assert.equal((modal.match(/onMatched=/g) || []).length, 1); // only the lead form; contacts have no source
});

test("Phone field: no error before the field is left; then a live check that follows number and country", () => {
  const india = "Enter a valid phone number for India (+91).";
  assert.equal(phoneFieldError("uiadcna", "IN"), ""); // still typing: nothing yet
  assert.equal(phoneFieldError("uiadcna", "IN", { touched: true }), india); // letters fail once the field is left
  assert.equal(phoneFieldError("98765 432", "IN", { touched: true }), india); // too short
  assert.equal(phoneFieldError("98765 432101", "IN", { touched: true }), india); // too long
  assert.equal(phoneFieldError("", "IN", { touched: true }), ""); // optional: empty is fine with a country chosen
  assert.equal(phoneFieldError("   ", "US", { touched: true }), "");
  assert.equal(phoneFieldError("98765 43210", "IN", { touched: true }), ""); // corrected: the message clears
  // the country decides: the same number is checked again when the country changes
  assert.equal(phoneFieldError("6123 4567", "IN", { touched: true }), india);
  assert.equal(phoneFieldError("6123 4567", "SG", { touched: true }), ""); // valid in Singapore
  assert.equal(phoneFieldError("(212) 555-0142", "US", { touched: true }), "");
  assert.equal(phoneFieldError("(212) 555-0142", "CA", { touched: true }), "Enter a valid phone number for Canada (+1).");
  assert.equal(phoneFieldError("+44 20 7946 0958", "IN", { touched: true }), ""); // a valid international number
  // a Save attempt's message shows until the field changes
  assert.equal(phoneFieldError("98765 43210", "IN", { saveError: india }), india);
});

test("Phone field wiring: blur, number and country changes, aria-invalid and the linked message", () => {
  const phone = source("./PhoneField.jsx");
  assert.match(phone, /onBlur=\{\(event\) => \{\s*read\(event\);\s*setTouched\(true\);/);
  assert.match(phone, /<select name=\{countryName\}[^>]*onChange=\{changed\}/);
  assert.match(phone, /onInput=\{changed\}/);
  assert.match(phone, /if \(error\) setTouched\(true\); \/\/ a failed Save counts as having left the field/);
  assert.match(phone, /aria-invalid=\{message \? true : undefined\}/);
  assert.match(phone, /aria-describedby=\{message \? errorId : undefined\}/);
  assert.match(phone, /<small id=\{errorId\} className="field-error" role="alert">/);
  assert.match(source("./styles.css"), /\.field input\[aria-invalid="true"\],\s*\.field select\[aria-invalid="true"\] \{\s*border-color: #c23934;/);
  // both contact forms use it; Save is still blocked and the first invalid field is focused
  assert.match(source("./Modal.jsx"), /<PhoneField error=\{fieldError\("phone"\)\}/);
  assert.match(source("./NewOpportunity.jsx"), /<PhoneField name=\{F\.phone\} countryName=\{F\.phone_country\} error=\{errors\[F\.phone\] \|\| ""\}/);
  const modal = source("./Modal.jsx");
  assert.match(modal, /const problems = newContact \? contactProblems\(values, OPPORTUNITY_CONTACT_FORM\) : \{\};[\s\S]*?event\.target\.elements\[Object\.keys\(problems\)\[0\]\]\?\.focus\(\);/);
  assert.equal(contactProblems({ first_name: "A", last_name: "B", email: "a@b.example", phone: "uiadcna" }).phone,
    "Enter a valid phone number for India (+91).");
  // the lead form's Phone is unchanged (a plain field, no country)
  assert.match(modal, /\{field\("Phone", "phone", "tel"\)\}/);
});

test("Contact LinkedIn: no standing helper text or success narration; loading, errors and warnings stay", () => {
  const field = source("./LeadAutofill.jsx");
  assert.match(field, /\{!compact && \(\s*<small id=\{help\} className="field-hint">/); // helper text: lead form only
  assert.match(field, /if \(alive\.current && !res\.enabled && !compact\)/); // no standing "not available" note
  const matched = field.slice(field.indexOf('{status.kind === "matched" && ('));
  assert.match(matched, /\{!compact && \(\s*<p>\s*<Icon name="check" size=\{14\} \/> \{status\.text\}/); // no "matching profile" text
  assert.match(matched, /\{!compact && status\.email && <p>\{status\.email\}<\/p>\}/); // no email-source note
  assert.match(matched, /\{!compact && Object\.keys\(status\.unavailable\)\.length > 0 && \(/); // no "no phone returned" list
  assert.match(matched, /\{!compact && status\.employerMatches === null && status\.employer && !status\.company && \(/);
  // what stays visible: loading, failure with Retry, a profile mismatch, missing required details, another employer
  assert.match(field, /\{status\.kind === "loading" && <p>\{compact \? "Looking up…" : /);
  assert.match(field, /\{status\.kind === "error" && \(\s*<p className="autofill-problem" role="alert">[\s\S]*?Retry/);
  assert.match(field, /\{status\.kind === "unverified" && \(\s*<p className="autofill-problem" role="alert">/);
  assert.match(matched, /\{status\.employerMatches === false && \(\s*<p className="autofill-problem" role="alert">/);
  assert.match(matched, /Not provided by Apollo, enter manually: \$\{labels\(status\.missing\)\}\./);
  // both contact forms are compact; the lead form isn't
  assert.match(source("./Modal.jsx"), /noun="contact"\s*compact/);
  assert.match(source("./NewOpportunity.jsx"), /noun="contact"\s*compact/);
  const lead = source("./Modal.jsx").slice(source("./Modal.jsx").indexOf('{type === "lead" && ('));
  assert.doesNotMatch(lead.slice(0, lead.indexOf("/>")), /compact/);
});

test("New Account: no Address or Phone; Name and Industry still required; saved without them", () => {
  const modal = source("./Modal.jsx");
  const account = modal.slice(modal.indexOf('{type === "account" && ('), modal.indexOf('{type === "contact" && ('));
  assert.doesNotMatch(account, /"Address"|"address"|"Phone"|"phone"/); // no such field (a comment may name them)
  assert.deepEqual(newRecordProblems("account", { name: "Synthetic Harbor Co", industry: "Logistics" }), {});
  assert.deepEqual(Object.keys(newRecordProblems("account", {})), ["name", "industry"]);
  // the account page still shows an older account's address
  assert.match(source("./RelatedPages.jsx"), /address/i);
});

// ---------- no stale or malformed phone in the contact forms ----------

test("Apollo's phone reaches a contact form only as a valid international number", () => {
  for (const phone of ["uiadcna", "555-0142", "(212) 555-0142", "+1 555", "+91 12345", "+1 212-555-0142 ext. 9"])
    assert.deepEqual(contactAnswerFields({ first_name: "Jane", phone }, OPPORTUNITY_CONTACT_FORM), { contact_first_name: "Jane" }, phone);
  assert.deepEqual(contactAnswerFields({ phone: "+1 212-555-0142" }, CONTACT_FORM), { phone: "+1 212-555-0142" });
  assert.deepEqual(contactAnswerFields({ phone: "+91 98765 43210" }, OPPORTUNITY_CONTACT_FORM), { contact_phone: "+91 98765 43210" });
  const fields = contactAutofillFields(CONTACT_FORM);
  // an untouched phone from an earlier profile is cleared when the new profile has no usable number
  const earlier = autofillPlan({ phone: "+1 212-555-0142" }, { phone: "+1 212-555-0142" }, contactAnswerFields({ phone: "uiadcna" }), fields);
  assert.equal(earlier.set.phone, "");
  // a number the user typed (even an invalid one) is never erased by a lookup: the field shows it as invalid instead
  const typed = autofillPlan({ phone: "uiadcna" }, {}, contactAnswerFields({ first_name: "Jane" }), fields);
  assert.equal("phone" in typed.set, false);
  assert.equal(phoneFieldError("uiadcna", "IN", { touched: true }), "Enter a valid phone number for India (+91).");
});

test("Contact forms: no browser autofill of the phone; a lookup re-checks the phone the field holds", () => {
  assert.equal(PHONE_RECHECK_EVENT, "crm-phone-recheck");
  const phone = source("./PhoneField.jsx");
  assert.match(phone, /autoComplete="off"/);
  assert.doesNotMatch(phone, /autoComplete="tel"/);
  assert.match(phone, /element\?\.addEventListener\(PHONE_RECHECK_EVENT, recheck\);/);
  assert.match(phone, /if \(value\.trim\(\)\) setTouched\(true\);/); // an empty phone stays quiet (it's optional)
  const field = source("./LeadAutofill.jsx");
  const apply = field.slice(field.indexOf("const apply = "), field.indexOf("const clearUnlessSame"));
  assert.match(apply, /if \(phone\) inputs\[phone\.field\]\?\.dispatchEvent\(new Event\(PHONE_RECHECK_EVENT, \{ bubbles: true \}\)\);/);
  // both contact forms turn the browser's autofill off (the lead form is unchanged)
  assert.match(source("./Modal.jsx"), /autoComplete=\{type === "contact" \|\| type === "newOpportunity" \? "off" : undefined\}/);
});

test("New Opportunity: switching to an existing contact drops the new-contact draft; each open starts blank", () => {
  const opp = source("./NewOpportunity.jsx");
  assert.match(opp, /useEffect\(\(\) => \{\s*if \(!showNewContact\) setPerson\(\{ first: "", last: "", email: "" \}\);\s*\}, \[showNewContact\]\);/);
  // the phone, title, country and LinkedIn inputs aren't kept in state: they start blank whenever the fields appear
  assert.match(opp, /<input name=\{F\.job_title\} maxLength=\{100\} \/>/);
  assert.match(source("./PhoneField.jsx"), /const \[now, setNow\] = useState\(\{ value: "", country: DEFAULT_PHONE_COUNTRY \}\);/);
  assert.doesNotMatch(source("./PhoneField.jsx"), /defaultValue=\{value|localStorage|sessionStorage/);
  // the dialog itself is removed when closed and created again when opened (no draft carried over)
  assert.match(source("./App.jsx"), /\{modal && <Modal modal=\{modal\} close=\{\(\) => setModal\(null\)\}/);
});

test("Bulk email: a progress pop-up with Sent / Queued / Failed opens when a campaign is sent", () => {
  const page = source("./CampaignsPage.jsx");
  for (const label of ['["Sent", counts.Sent', '["Queued", counts.Queued', '["Failed", counts.Failed']) assert.ok(page.includes(label), label);
  assert.match(page, /export function CampaignProgressPopups\(\)/);
  assert.match(page, /api\s*\.campaign\(id, \{ limit: 1 \}\)/); // refreshed while sending (one recipient row is enough)
  // opened from Email Campaigns and from leads selected on the Leads page
  assert.match(page, /watchCampaign\(c\); \/\/ the progress pop-up/);
  assert.match(source("./LeadsTable.jsx"), /watchCampaign\(c\); \/\/ the progress pop-up/);
  assert.match(source("./App.jsx"), /<CampaignProgressPopups \/>/);
});

test("Account page: a Leads card with the account's leads", () => {
  const pages = source("./RelatedPages.jsx");
  assert.match(pages, /<AccountLeads accountId=\{account\.id\} \/>/);
  assert.match(pages, /api\s*\.accountLeads\(accountId\)/);
  assert.match(source("./api.js"), /accountLeads: \(id\) => apiRequest\(`\/accounts\/\$\{id\}\/leads`\)/);
});
