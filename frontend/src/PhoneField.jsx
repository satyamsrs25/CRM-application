// A Phone with its country beside it, India (+91) first chosen. Used by New Contact and New Opportunity > New contact
// (optional), and by New Lead (required). Both inputs are read by name (name / countryName) when the form is saved, and LinkedIn
// autofill can set them; the number is checked with phoneProblem (phone.js) and again by the server.
// An invalid number is shown (red border and the message under it, linked with aria-describedby) once the user leaves
// the field or tries to save; from then on a change of number or country checks it again, and a corrected number (or
// an empty one: the phone is optional) clears it. error: the form's message from a Save attempt.
// The browser's own autofill is off: this is the customer's number, never the user's saved one.
import React, { useEffect, useRef, useState } from "react";
import { DEFAULT_PHONE_COUNTRY, PHONE_COUNTRIES, PHONE_RECHECK_EVENT, phoneFieldError } from "./phone";

// required: the red star and aria-required (New Lead); the form itself says when it is empty (error).
export default function PhoneField({ name = "phone", countryName = "phone_country", label = "Phone", error = "", onInput, required = false }) {
  const errorId = `${name}-field-error`;
  const [touched, setTouched] = useState(false);
  const [now, setNow] = useState({ value: "", country: DEFAULT_PHONE_COUNTRY }); // what the two inputs hold
  const box = useRef(null);
  useEffect(() => {
    if (error) setTouched(true); // a failed Save counts as having left the field
  }, [error]);
  // after a LinkedIn lookup: check what the field holds now (an entry the user kept is shown as invalid if it is)
  useEffect(() => {
    const element = box.current;
    const recheck = () => {
      const value = element.querySelector("input").value;
      setNow({ value, country: element.querySelector("select").value });
      if (value.trim()) setTouched(true);
    };
    element?.addEventListener(PHONE_RECHECK_EVENT, recheck);
    return () => element?.removeEventListener(PHONE_RECHECK_EVENT, recheck);
  }, []);
  const message = phoneFieldError(now.value, now.country, { touched, saveError: error });
  const read = (event) => {
    const box = event.target.closest(".phone-inputs");
    setNow({ value: box.querySelector("input").value, country: box.querySelector("select").value });
  };
  const changed = (event) => {
    read(event);
    onInput?.(event); // clears the Save message; the live check takes over
  };
  return (
    <div className="field phone-field">
      <label htmlFor={`${name}-input`}>
        <span>
          {label}
          {required && <i> *</i>}
        </span>
      </label>
      <div className="phone-inputs" ref={box}>
        <select name={countryName} defaultValue={DEFAULT_PHONE_COUNTRY} aria-label={`${label}: country`} onChange={changed}>
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
          aria-required={required || undefined}
          aria-invalid={message ? true : undefined}
          aria-describedby={message ? errorId : undefined}
          onInput={changed}
          onBlur={(event) => {
            read(event);
            setTouched(true);
          }}
        />
      </div>
      {message && (
        <small id={errorId} className="field-error" role="alert">
          {message}
        </small>
      )}
    </div>
  );
}
