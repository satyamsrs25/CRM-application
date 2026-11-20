// A lead's or contact's phone number and its country (New / Edit Lead, New Contact, New Opportunity > New contact).
// The number is optional everywhere;
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

// Is the number valid in this country's own numbering plan? The same check as the server's
// phonenumbers.is_valid_number_for_region: the number is tested against the country's own patterns (a fresh copy of it,
// with its country set to the one chosen). Countries sharing a calling code stay apart (a Toronto number is valid
// for Canada only), and numbers they share (+1 toll-free 800, 888...) are valid for each of them. It never relies on
// the single country libphonenumber-js names for a number (it names the United States for every +1 toll-free number).
export function validInCountry(number, country) {
  if (!number || !byCode.has(country) || number.countryCallingCode !== getCountryCallingCode(country)) return false;
  const copy = parsePhoneNumberFromString(number.number);
  if (!copy) return false;
  copy.country = country;
  return copy.isValid();
}

// "" when the number is empty or valid; otherwise the message to show under the field. Without a leading +, the
// number must be valid in the chosen country (a US number isn't a Canadian one, though both use +1); with one, its
// own country code decides (and regionProblem checks it against a chosen Region).
export function phoneProblem(value, country = DEFAULT_PHONE_COUNTRY) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  if (!byCode.has(country)) return "Choose the phone number's country.";
  const international = text.startsWith("+");
  const message = international ? PHONE_WITH_CODE_INVALID : `Enter a valid phone number for ${phoneCountryLabel(country)}.`;
  if (!PHONE_CHARACTERS.test(text)) return message;
  const number = parsePhoneNumberFromString(text, country);
  if (!number) return message;
  return (international ? number.isValid() : validInCountry(number, country)) ? "" : message;
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

// Region: the country chosen beside the phone, saved with the lead or contact (backend/app/regions.py). It means the
// country (not a state or sales territory) and is shown by name. Countries that share a calling code (+1: the United
// States, Canada, Jamaica...) are separate choices in the list, so the choice always names one country; nothing is
// guessed from a number's digits.
export const regionName = (code) => (code && byCode.get(code)?.name) || "";
// What the form saves as Region: the listed country once the user chose it (or the record already had it), or entered
// a number for it (the number is checked for that country). "" while the list only shows its default (India) and the
// phone is empty, so no Region is saved that nobody chose. Clearing the number keeps a chosen Region.
export const chosenRegion = ({ country, chosen = false, phone = "" }) =>
  chosen || String(phone ?? "").trim() ? country : "";
// A number given with its own +code must belong to the Region: first its calling code (a +1 number can't be saved
// with Region India), then the Region's own numbering plan (a Toronto +1 number can't be saved with Region United
// States; a +1 toll-free number can, and with Canada or Jamaica too). "" when it does, has no + (phoneProblem checks
// it for the chosen country), or isn't a valid number at all (phoneProblem reports that). The server checks it too
// (backend/app/regions.py phone_region_problem, with the same messages).
export function regionProblem(value, country) {
  const text = String(value ?? "").trim();
  if (!text.startsWith("+") || !byCode.has(country)) return "";
  const number = parsePhoneNumberFromString(text);
  if (!number) return "";
  const wanted = getCountryCallingCode(country);
  if (number.countryCallingCode !== wanted)
    return `This number's country code is +${number.countryCallingCode}, but the Region is ${regionName(country)} (+${wanted}). Choose the number's country.`;
  if (number.isValid() && !validInCountry(number, country))
    return `This number isn't valid for the Region, ${regionName(country)} (+${wanted}). Choose the number's country.`;
  return "";
}
