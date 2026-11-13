import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiRequest, normalizeWorkspace } from "./api";
import { DEFAULT_PERIOD, periodQuery } from "./homePeriod";

const empty = {
  leads: [],
  opportunities: [],
  tasks: [],
  users: [],
  accounts: [],
  contacts: [],
  home: null,
  notifications: [],
};
// userId = the logged-in user (the bell shows their notifications).
// homeScope: "team" = Home shows everyone's records (shared), "mine" = only records owned by userId.
// homePeriod: the Home period selector ({ preset } or { preset: "custom", from, to }); changing it reloads only Home.
export function useWorkspace(collection, id, userId, homeScope = "team", homePeriod = DEFAULT_PERIOD) {
  const [data, setData] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [hasLoaded, setHasLoaded] = useState(false);
  const notificationOwner = userId ? String(userId) : "";
  const sequence = useRef(0),
    busy = useRef(false);
  const period = useRef(homePeriod);
  period.current = homePeriod;
  const last = useRef(null); // the last full load, so a new period only fetches Home again
  const homePath = () =>
    `/home?${homeScope === "mine" && notificationOwner ? `owner_id=${notificationOwner}&` : ""}${periodQuery(period.current)}`;
  const reload = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true);
    try {
      const names = [
        "leads",
        "opportunities",
        "tasks",
        "users",
        "accounts",
        "contacts",
        "home",
      ];
      const path = (name) => (name === "home" ? homePath() : `/${name}`);
      const [responses, detail, notifications] = await Promise.all([
        Promise.all(names.map((name) => apiRequest(path(name)))),
        id && ["leads", "opportunities"].includes(collection)
          ? apiRequest(`/${collection}/${id}`)
          : null,
        notificationOwner
          ? apiRequest("/notifications")
          : [],
      ]);
      if (ticket !== sequence.current) return;
      const raw = Object.fromEntries(
        names.map((name, index) => [name, responses[index]]),
      );
      last.current = { raw, notifications, detail };
      setData(
        normalizeWorkspace(
          { ...raw, notifications },
          detail ? { collection, record: detail } : null,
        ),
      );
      setError("");
      setHasLoaded(true);
    } catch (err) {
      if (ticket === sequence.current) setError(err.message);
      throw err;
    } finally {
      if (ticket === sequence.current) setLoading(false);
    }
  }, [collection, id, notificationOwner, homeScope]);
  useEffect(() => {
    reload().catch(() => {});
    return () => {
      sequence.current++;
    };
  }, [reload]);
  // A new Home period: fetch Home only and keep everything else
  const periodKey = JSON.stringify(homePeriod);
  const firstPeriod = useRef(true);
  useEffect(() => {
    if (firstPeriod.current) {
      firstPeriod.current = false;
      return;
    }
    if (!last.current) {
      reload().catch(() => {}); // nothing loaded yet: load everything (with the new period)
      return;
    }
    const ticket = ++sequence.current;
    setLoading(true);
    apiRequest(homePath())
      .then((home) => {
        if (ticket !== sequence.current) return;
        const { raw, notifications, detail } = last.current;
        last.current = { ...last.current, raw: { ...raw, home } };
        setData(normalizeWorkspace({ ...raw, home, notifications }, detail ? { collection, record: detail } : null));
        setError("");
      })
      .catch((err) => ticket === sequence.current && setError(err.message))
      .finally(() => ticket === sequence.current && setLoading(false));
  }, [periodKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const latestReload = useRef(reload);
  latestReload.current = reload;
  const run = useCallback(
    async (name, ...args) => {
      if (busy.current)
        throw new Error(
          "A change is already being saved. Please try again in a moment.",
        );
      busy.current = true;
      setSaving(true);
      try {
        const result = await api[name](...args);
        try {
          await latestReload.current();
        } catch {
          setError(
            "Your change was saved, but the page could not refresh. Reload the latest data before continuing.",
          );
        }
        return result;
      } catch (err) {
        setError(err.message);
        throw err;
      } finally {
        busy.current = false;
        setSaving(false);
      }
    },
    [],
  );
  return {
    data,
    run,
    reload,
    loading,
    saving,
    error,
    hasLoaded,
    notificationOwner,
  };
}
