// A Phone with its country beside it (India +91 first chosen), and the Region that country gives. Used by New Lead and
// Edit Lead, New Contact and New Opportunity > New contact; the phone is optional on all of them. The inputs are read by
// name when the form is saved: the number (name), the listed country the number is checked for (countryName) and the
// Region to save (regionName: the country's code, or "" when none was chosen). LinkedIn autofill can set them.
// Region: the listed country once the user picks one, or enters a number for it (phone.js chosenRegion). The default
// India alone is not a choice, so a record saved without a phone and without picking a country gets no Region; a
// record that already has a Region keeps it, also when its number is cleared. Countries sharing a calling code (+1:
// the United States, Canada...) are separate entries, so the Region is always one named country.
// An invalid number is shown (red border and the message under it, linked with aria-describedby) once the user leaves
// the field or tries to save; from then on a change of number or country checks it again, and a corrected number (or
// an empty one: the phone is optional) clears it. error: the form's message from a Save attempt.
// The browser's own autofill is off: this is the customer's number, never the user's saved one.
import React, { useEffect, useRef, useState } from "react";
import { DEFAULT_PHONE_COUNTRY, PHONE_COUNTRIES, PHONE_RECHECK_EVENT, chosenRegion, phoneFieldError, regionName as nameOf, regionProblem } from "./phone";

// required: the red star and aria-required (no form requires the phone now; kept for a form that may).
// defaultValue / defaultCountry: an edited record's phone and saved Region ("" when it has none).
export default function PhoneField({
  name = "phone",
  countryName = "phone_country",
  regionName = "region",
  label = "Phone",
  error = "",
  onInput,
  required = false,
  defaultValue = "",
  defaultCountry = "",
}) {
  const errorId = `${name}-field-error`;
  const [touched, setTouched] = useState(false);
  const [now, setNow] = useState({ value: defaultValue || "", country: defaultCountry || DEFAULT_PHONE_COUNTRY });
  const [chosen, setChosen] = useState(!!defaultCountry); // the user picked the country (or the record had a Region)
  const [typed, setTyped] = useState(false); // a number was entered here (an edited record's saved number isn't)
  const box = useRef(null);
  useEffect(() => {
    if (error) setTouched(true); // a failed Save counts as having left the field
  }, [error]);
  // after a LinkedIn lookup: check what the field holds now (an entry the user kept is shown as invalid if it is)
  useEffect(() => {
    const element = box.current;
    const recheck = () => {
      const value = element.querySelector("input[type=tel]").value;
      setNow({ value, country: element.querySelector("select").value });
      if (value.trim()) {
        setTouched(true);
        setTyped(true);
      }
    };
    element?.addEventListener(PHONE_RECHECK_EVENT, recheck);
    return () => element?.removeEventListener(PHONE_RECHECK_EVENT, recheck);
  }, []);
  const region = chosenRegion({ country: now.country, chosen, phone: typed ? now.value : "" });
  // an edited record's saved number is checked only once it is changed, or its Region is (as the server does)
  const unchanged = !!String(defaultValue).trim() && now.value.trim() === String(defaultValue).trim();
  const message = (unchanged ? error : phoneFieldError(now.value, now.country, { touched, saveError: error })) ||
    (touched && region && (!unchanged || region !== defaultCountry) ? regionProblem(now.value, region) : "");
  const read = (event) => {
    const inputs = event.target.closest(".phone-inputs");
    setNow({ value: inputs.querySelector("input[type=tel]").value, country: inputs.querySelector("select").value });
  };
  const changed = (event) => {
    read(event);
    if (event.target.tagName === "SELECT") setChosen(true);
    else setTyped(true);
    // clears or rechecks the form's message, once this change is drawn: the form's check then reads the Region the
    // user sees (the hidden input), not the one before the change
    if (onInput) setTimeout(() => onInput(event), 0);
  };
  return (
    <>
      <div className="field phone-field">
        <label htmlFor={`${name}-input`}>
          <span>
            {label}
            {required && <i> *</i>}
          </span>
        </label>
        <div className="phone-inputs" ref={box}>
          <select name={countryName} defaultValue={now.country} aria-label={`${label}: country`} onChange={changed}>
            {PHONE_COUNTRIES.map((country) => (
              <option key={country.code} value={country.code}>
                {country.name} ({country.dial})
              </option>
            ))}
          </select>
          <input
            id={`${name}-input`}
            name={name}
            type="tel"
            maxLength={30}
            autoComplete="off"
            defaultValue={defaultValue || ""}
            aria-required={required || undefined}
            aria-invalid={message ? true : undefined}
            aria-describedby={message ? errorId : undefined}
            onInput={changed}
            onBlur={(event) => {
              read(event);
              setTouched(true);
            }}
          />
          <input type="hidden" name={regionName} value={region} />
        </div>
        {message && (
          <small id={errorId} className="field-error" role="alert">
            {message}
          </small>
        )}
      </div>
      {/* Region: the chosen country, by name (read-only: it follows the country beside the phone) */}
      <label className="field region-field">
        <span>Region</span>
        <input readOnly tabIndex={-1} value={nameOf(region)} placeholder="Not set: choose the phone's country"
          aria-describedby={`${name}-region-hint`} />
        <small id={`${name}-region-hint`} className="field-hint">From the country beside the phone</small>
      </label>
    </>
  );
}
