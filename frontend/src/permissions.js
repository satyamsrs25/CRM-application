// What the logged-in user may do. The backend sends the list at login (user.permissions) and checks
// every request again, so hiding a button here is only for a clean screen, not for security.
export const can = (user, permission) => !!user?.permissions?.includes(permission);

// Manage Access: the Admin (users), and Managers (their team, team access, team activity)
export const canManageAccess = (user) =>
  can(user, "manage_users") || can(user, "grant_team_access") || can(user, "manage_team");

// Change a lead or opportunity (Actions > Edit and the pencils on its Details tab): its owner, or anyone with
// "Edit team records" (Managers by default; the Admin has every permission). Team access alone is view-only.
export const canEditRecord = (user, record) =>
  !!user && !!record && (record.owner_id === user.id || can(user, "edit_team_records"));

// Lead conversion (Convert on the lead page, the board, the Leads list and Opportunities > Convert a Lead): the Admin,
// Managers and Salespeople. Which leads still follows canEditRecord (the backend checks both).
export const canCreateSales = (user) => ["Admin", "Manager", "Salesperson"].includes(user?.role);

// Direct opportunity creation is available to all signed-in CRM roles, including Admin.
export const canCreateOpportunity = (user) => ["Admin", "Manager", "Salesperson"].includes(user?.role);

// Transfer a lead: the Admin and Managers ("Reassign owner": any lead they can see),
// or a user with "Transfer own leads" (their own leads). A lead in the Unassigned Pool is assigned instead.
export const canTransferLead = (user, lead) =>
  !!user &&
  !!lead &&
  lead.owner_id != null &&
  (user.role === "Admin" || can(user, "reassign_owner") || (can(user, "transfer_leads") && lead.owner_id === user.id));

// The Unassigned Pool (leads with no owner yet, e.g. every upload): the Admin and Managers with "Reassign owner" assign
// a pooled lead, one at a time, to an active Salesperson (a Manager: one who reports to them). Salespeople request one.
export const canAssignPool = (user) => !!user && (user.role === "Admin" || (user.role === "Manager" && can(user, "reassign_owner")));
export const canRequestPool = (user) => user?.role === "Salesperson";
// who a pooled lead can go to, for this user's Assign list
export const poolAssignees = (user, users = []) =>
  users
    .filter((u) => u.is_active !== false && u.role === "Salesperson" && (user?.role === "Admin" || u.reports_to_id === user?.id))
    .sort((a, b) => a.full_name.localeCompare(b.full_name));
