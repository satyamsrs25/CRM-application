// A contact's phone number and its country (New Contact, and New Opportunity > New contact). The number is optional;
// a given one is checked against its country's numbering rules with libphonenumber-js (Google's libphonenumber
// rules, the same as the backend's `phonenumbers`, backend/app/schemas.py international_phone). The backend checks
// it again and saves it in international format. This checks the format only: it doesn't show that the number
// exists or belongs to the contact. Plain functions (no React), so the node test runner checks them.
import { getCountries, getCountryCallingCode, parsePhoneNumberFromString } from "libphonenumber-js/max";

export const DEFAULT_PHONE_COUNTRY = "IN"; // India (+91)
// Sent to the phone input after a LinkedIn lookup: the field checks what it holds, so an invalid number already there
// (typed, or put there by the browser) shows its message instead of waiting for the field to be left
export const PHONE_RECHECK_EVENT = "crm-phone-recheck";
export const PHONE_WITH_CODE_INVALID = "Enter a valid phone number, including its country code after the +.";
const PHONE_CHARACTERS = /^\+?[0-9 ().-]+$/; // digits, spaces, brackets, hyphens and dots; an optional leading +

const regionNames = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    return null;
  }
})();
// Every country with its name and calling code, by name; countries that share a code (Canada and the United States,
// +1) stay apart by name
export const PHONE_COUNTRIES = getCountries()
  .map((code) => ({ code, name: regionNames?.of(code) || code, dial: `+${getCountryCallingCode(code)}` }))
  .sort((a, b) => a.name.localeCompare(b.name, "en"));
const byCode = new Map(PHONE_COUNTRIES.map((country) => [country.code, country]));
export const phoneCountryLabel = (code) => {
  const country = byCode.get(code);
  return country ? `${country.name} (${country.dial})` : code;
};

// "" when the number is empty or valid; otherwise the message to show under the field. Without a leading +, the
// number must be valid in the chosen country (a US number isn't a Canadian one, though both use +1); with one, its
// own country code decides.
export function phoneProblem(value, country = DEFAULT_PHONE_COUNTRY) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  if (!byCode.has(country)) return "Choose the phone number's country.";
  const international = text.startsWith("+");
  const message = international ? PHONE_WITH_CODE_INVALID : `Enter a valid phone number for ${phoneCountryLabel(country)}.`;
  if (!PHONE_CHARACTERS.test(text)) return message;
  const number = parsePhoneNumberFromString(text, country);
  if (!number || !number.isValid()) return message;
  return international || number.country === country ? "" : message;
}

// What the Phone field shows under it: nothing while the user hasn't left the field yet; once it has been left (or a
// Save was tried), the live check of the number for the chosen country, so a change of number or country updates it
// and a corrected number clears it. saveError: the form's message from a Save attempt (shown until the field changes).
export function phoneFieldError(value, country, { touched = false, saveError = "" } = {}) {
  return saveError || (touched ? phoneProblem(value, country) : "");
}

// The country of an international number ("+1 415 555 0142" -> "US"); "" when it can't be told
export function phoneCountryOf(value) {
  const number = parsePhoneNumberFromString(String(value ?? "").trim());
  return number?.country || "";
}
