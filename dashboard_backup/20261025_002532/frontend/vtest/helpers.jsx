import React from "react";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fx from "./fixtures/api.json";

// serve the REAL API responses captured from the backend; `override` replaces/blanks individual endpoints
export function mockApi(override = {}) {
  global.fetch = async (url) => {
    const path = new URL(String(url)).pathname;
    const key = Object.keys(fx).find((k) => k.split("?")[0] === path);
    if (path in override) {
      const o = override[path];
      if (o === "error") return { ok: false, status: 500, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => o };
    }
    if (!key) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => fx[key] };
  };
}

export async function renderPage(Page, { override = {}, until } = {}) {
  mockApi(override);
  const r = render(<MemoryRouter><Page /></MemoryRouter>);
  if (until) await waitFor(() => { if (!r.container.textContent.includes(until)) throw new Error("waiting for: " + until + " | have: " + r.container.textContent.slice(0, 200)); }, { timeout: 8000 });
  else await new Promise((res) => setTimeout(res, 800));
  return r;
}
export const text = (r) => r.container.textContent;
