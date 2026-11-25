import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { DISPLAY_CURRENCIES, RATES, convert, moneyIn, ratesNote, total } from "./currencyConvert.js";

test("Home currency: mixed $ and ₹ totals are shown in the one chosen currency", () => {
  const values = { USD: 15000, INR: 200000 }; // "$15K + ₹200K" before
  assert.equal(moneyIn(values, "USD"), "$17.2K");
  assert.equal(moneyIn(values, "INR"), "₹1.59M");
  assert.equal(Math.round(total(values, "INR")), Math.round(15000 * RATES.INR + 200000));
  assert.equal(moneyIn({}, "EUR"), "€0");
  assert.equal(convert(100, "USD", "USD"), 100);
  assert.equal(Math.round(convert(RATES.AED, "AED", "USD")), 1);
  assert.deepEqual(DISPLAY_CURRENCIES, ["USD", "INR", "EUR", "CAD", "AUD", "AED"]);
  assert.match(ratesNote("USD"), /^Amounts in other currencies are converted to USD at fixed rates of .+: 1 INR = /);
});

test("Home currency: the dashboard has a Currency drop-down and converts every card", () => {
  const home = readFileSync(new URL("./SellerHome.jsx", import.meta.url), "utf8");
  assert.match(home, /<select value=\{currency\} onChange=\{\(e\) => setCurrency\(e\.target\.value\)\} aria-label="Show amounts in">/);
  assert.match(home, /<DisplayCurrency\.Provider value=\{currency\}>/);
  assert.doesNotMatch(home, /compactMoneyMix/); // no more "$167K + ₹600K"
  assert.match(home, /\{ value: sum\(pipeline\.by_currency\?\.open\), color: COLORS\.open \}/); // the ring adds converted amounts
  assert.match(home, /const pipeline = \(p\) => sum\(p\.open_pipeline_values\);/); // Team Performance ranks converted
  assert.match(home, /compactMoney\(convert\(d\.amount, d\.currency \|\| "USD", currency\), currency\)/);
});
