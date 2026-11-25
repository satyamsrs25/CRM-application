// Home > Dashboard shows every amount in one currency, chosen in its Currency drop-down. Deals keep their own currency
// (format.js CURRENCIES); here they are converted at fixed reference rates (units per 1 USD), so "$167K + ₹600K"
// reads "$173K". Update RATES and RATES_DATE together when the rates should move.
import { CURRENCIES, compactMoney } from "./format.js";

export const RATES_DATE = "25 Nov 2026";
export const RATES = { USD: 1, INR: 92.81, EUR: 0.9121, CAD: 1.4272, AUD: 1.5079, AED: 3.6725 };
export const DISPLAY_CURRENCIES = CURRENCIES.filter((c) => RATES[c]);

// One amount from `from` to `to` (an unknown currency counts as USD)
export function convert(amount, from, to) {
  const value = Number(amount) || 0;
  return (value / (RATES[from] || 1)) * (RATES[to] || 1);
}

// {"USD": 15000, "INR": 200000} -> the total in `to`
export function total(values, to) {
  return Object.entries(values || {}).reduce((sum, [currency, v]) => sum + convert(v, currency, to), 0);
}

// {"USD": 15000, "INR": 200000} -> "$17K" (in `to`)
export const moneyIn = (values, to) => compactMoney(total(values, to), to);

// "1 USD = 92.81 INR · 1 EUR = …": the rates behind the conversion, for the drop-down's tooltip
export function ratesNote(to) {
  const others = DISPLAY_CURRENCIES.filter((c) => c !== to)
    .map((c) => `1 ${c} = ${convert(1, c, to).toLocaleString("en-US", { maximumFractionDigits: 4 })} ${to}`)
    .join(" · ");
  return `Amounts in other currencies are converted to ${to} at fixed rates of ${RATES_DATE}: ${others}`;
}
