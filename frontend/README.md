# CRM Frontend

React app for our CRM POC. The screens follow Salesforce Lightning (Sales app), and all data comes from the backend API.

## Run

The easiest way is Docker from the main project folder. It starts the database, the API and this app together:

```
docker compose up --build
```

Then open http://localhost:5173 and log in. The first time, use the default Admin (`admin@salestrack.local` / `Admin@2026`) and add users on the **Users** page.

To run only the frontend while the API is already running on port 8001:

```
cd frontend
npm install
npm run dev
```

Calls to `/api` are forwarded to `http://127.0.0.1:8001` (see `vite.config.js`). To use a different API address, copy `.env.example` to `.env.local` and change `API_PROXY_TARGET`.

## Screens

![Seller Home](docs/seller-home.png)

| Screen | What it shows |
| --- | --- |
| Login | Log in (`POST /api/auth/login`); the token is sent on every request |
| Users (Admin) | Add users, change roles, reset passwords, deactivate, transfer records |
| Home | One dashboard per role, with a period selector (Past 1 week or a custom range). Salesperson and a Manager's Me view: Action Needed, Scheduled Demos (each with Today and Upcoming), Overall Value, Follow-up Radar, My Scorecard, Recent Activity. Manager's My Team view: Action Needed, Scheduled Demos, Overall Value, Win/Loss Analysis, Team Performance. Admin (every record): Overall Value, Win/Loss Analysis, Lead Sources, Closing Soon, Follow-up Radar, Recent Activity. Each card is shown by its "Home dashboard" permission |
| Leads | List views (All Open Leads, My Open Leads, Converted, Lost), sort, search, New. Columns include Owner, Created By and Transferred To (to whom and when). Transfer Requests: ask for someone else's lead (Request Transfer on the lead, or from the "email already in the CRM" message) and approve or reject requests for yours |
| Lead page | Highlights, path (New → Nurturing → Demo → Converted), Convert, Mark as Lost, Details and Activity tabs, notes, stage history |
| Opportunities | Table or Kanban (drag a deal to change its stage) |
| Opportunity page | Path (Opportunity → Proposal → Won), Mark as Won / Lost, Activity, Details |
| Accounts / Contacts | Lists and record pages with related contacts and opportunities |
| Tasks | My Open Tasks, Today, Overdue, Completed, All; complete with the checkbox |
| Send Email | From a lead, opportunity, contact or account: To, Cc, subject, message and attachments; sent emails show on the record |

More screenshots in `docs/`: [lead page](docs/lead-page.png), [send email](docs/send-email.png), [opportunity Kanban](docs/opportunities-kanban.png), [App Launcher](docs/app-launcher.png), [login](docs/login.png).

The left side panel has the main pages (it can be collapsed). The 9 dots open the App Launcher with every page plus the test inbox and API docs.
The header has global search (`GET /api/search`), a + menu for new records, the notification bell for the logged-in user, and Log Out.
Every notification, task, Assistant item and Home card opens the record it is about.

## Files

| File | Purpose |
| --- | --- |
| `src/App.jsx` | Login check, page routing, dialogs and messages |
| `src/Header.jsx` | Top bar, App Launcher, search, + menu, bell, user menu, and the side panel |
| `src/Login.jsx` | Login |
| `src/UsersPage.jsx` | Users page (Admin) and Change Password |
| `src/Email.jsx` | Send Email (with attachments) and the list of sent emails |
| `src/Attachments.jsx` | Attachments card on the opportunity page: upload, open (PDF / images), download and delete files |
| `src/SellerHome.jsx` | Home page cards |
| `src/ListView.jsx` | List views and the opportunity Kanban |
| `src/RecordPage.jsx` | Lead and opportunity pages |
| `src/RelatedPages.jsx` | Account and contact pages |
| `src/TasksPage.jsx` | Tasks list |
| `src/Modal.jsx` | Create / edit forms and stage actions (convert, won and stage change with optional files, lost, note) |
| `src/LeadAutofill.jsx` | LinkedIn Profile URL on the lead form; on New Lead it fills empty fields from Apollo (through the backend) |
| `src/api.js` | API calls and request/response mapping |
| `src/useWorkspace.js` | Loads and refreshes data from the API |
| `src/domain.js`, `src/format.js` | Dropdown values and display formatting |
| `src/listHelpers.js` | List page wording and rules without React (paging text, filter chips, selection bar actions, empty states), tested in `domain.test.js` |
| `src/ui.jsx` | Icons, ring charts, path bar and other small pieces |

## Tests

```
npm test            # unit tests
npm run build       # production build
```

`npm run test:integration` runs a full lead-to-won flow against a running API. It creates records, so only point it at a test database:

```
CRM_TEST_ORIGIN=http://127.0.0.1:5173 npm run test:integration
```

## Notes

- The logged-in user is remembered in the browser. The backend does not issue tokens yet, so this is not real security.
- Amounts are shown without a currency symbol because the database has no currency field.
