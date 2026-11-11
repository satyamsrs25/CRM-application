// Display helpers shared by the screens.

// 850000 -> "850K", 2550000 -> "2.55M". The backend has no currency field, so no symbol is added.
export function compact(value) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1e6) return `${+(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${+(n / 1e3).toFixed(1)}K`;
  return String(+n.toFixed(2));
}

// Currency of a lead's turnover or an opportunity's amounts (chosen per record; never converted)
export const CURRENCIES = ["USD", "INR", "EUR", "CAD", "AUD", "AED"];
export const DEFAULT_CURRENCY = "USD";
// USD -> "$", INR -> "₹", EUR -> "€", CAD -> "CA$", AUD -> "A$", AED -> "AED"
export function currencySymbol(currency = DEFAULT_CURRENCY) {
  const code = CURRENCIES.includes(currency) ? currency : DEFAULT_CURRENCY;
  const parts = new Intl.NumberFormat("en-US", { style: "currency", currency: code }).formatToParts(0);
  return parts.find((p) => p.type === "currency")?.value || code;
}
const joinSymbol = (symbol, text) => (/^[A-Z]{3}$/.test(symbol) ? `${symbol} ${text}` : `${symbol}${text}`);

// 1234.5 -> "1,234.5"; with a currency: "$1,234.5", "₹1,234.5", "AED 1,234.5"
export function amount(value, currency) {
  if (value == null || value === "") return "";
  const text = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  return currency ? joinSymbol(currencySymbol(currency), text) : text;
}

// Short money for cards: 2550000, "USD" -> "$2.55M"
export const compactMoney = (value, currency = DEFAULT_CURRENCY) =>
  value == null || value === "" ? "—" : joinSymbol(currencySymbol(currency), compact(value));

// Totals per currency from the API ({USD: 12000, INR: 500000}) -> "$12K + ₹500K". Amounts in different
// currencies are never added together. Empty -> "$0".
export function compactMoneyMix(values) {
  const entries = Object.entries(values || {}).filter(([, v]) => v);
  if (!entries.length) return compactMoney(0);
  return entries
    .sort(([a], [b]) => CURRENCIES.indexOf(a) - CURRENCIES.indexOf(b))
    .map(([currency, v]) => compactMoney(v, currency))
    .join(" + ");
}

const asDate = (value) =>
  value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);

export function shortDate(value) {
  if (!value) return "";
  return asDate(value).toLocaleDateString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "numeric",
  });
}

export function dateTime(value) {
  if (!value) return "";
  return asDate(value).toLocaleString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// Tables: 10/28/26, 7:11 PM (keeps date columns narrow)
export function shortDateTime(value) {
  if (!value) return "";
  return asDate(value).toLocaleString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "2-digit",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function time(value) {
  if (!value) return "";
  return asDate(value).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function greeting(date = new Date()) {
  const h = date.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export const firstName = (fullName = "") => fullName.split(" ")[0];

export const initials = (name = "") =>
  name
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

// "+91 98200 00110", "+1 416-555-0114", "4165550114" -> one consistent style with single spaces
export function formatPhone(value) {
  if (!value) return "";
  const text = String(value).trim();
  const digits = text.replace(/\D/g, "");
  if (!text.startsWith("+") && digits.length === 10) return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  if (text.startsWith("+1") && digits.length === 11) return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  if (text.startsWith("+91") && digits.length === 12) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  return text.replace(/[\s\-.()]+/g, " ").replace(/\s+/g, " ");
}

// Lists show only the start of a phone number; the full number is on the record page.
// "+1 (416) 555-0114" -> "+1 (416) •••-••••", "+91 98200 00110" -> "+91 982•• •••••"
export function maskPhone(value) {
  const text = formatPhone(value);
  if (!text) return "";
  const country = text.startsWith("+") ? (text.match(/^\+(\d{1,3})/)?.[1].length ?? 0) : 0;
  let shown = 0;
  const keep = country + 3; // country code + first 3 digits
  return text.replace(/\d/g, (d) => (++shown <= keep ? d : "•"));
}

// File sizes: "220 KB", "1.4 MB"
export const fileSize = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

// New Email: the line beside Attach files, so the attachments are clear while the chooser is closed
export function attachedSummary(files, limit = "25 MB") {
  if (!files.length) return "No files attached";
  const bytes = files.reduce((sum, f) => sum + f.size, 0);
  return `${files.length} file${files.length === 1 ? "" : "s"} attached · ${fileSize(bytes)} of ${limit}`;
}
