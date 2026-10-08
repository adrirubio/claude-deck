import { MemoryRouter, Routes, Route } from "react-router-dom";
import { render, act } from "@testing-library/react";
import { vi } from "vitest";
import type { ReactNode } from "react";
import catalog from "../fixtures/provider-operations/v1/catalog.json";
export function operationsFixtureResponse(path: string) {
  const match = /^providers\/([^/]+)\/operations$/.exec(path);
  if (!match) return undefined;
  const value = catalog.providers[match[1] as keyof typeof catalog.providers];
  return jsonResponse(value ?? { detail: "Unknown fixture provider" }, value ? 200 : 404);
}
export function renderRoute(
  element: ReactNode,
  path = "/work",
  route = "/work",
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}
export function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
export function fixtureFetch(
  handler: (
    path: string,
    query: URLSearchParams,
    options?: RequestInit,
  ) => Response | Promise<Response>,
) {
  const requests: { path: string; query: URLSearchParams; method: string }[] =
    [];
  const fetch = vi.fn(
    (input: string | URL | Request, options?: RequestInit) => {
      const url = new URL(String(input), "http://fixture.test");
      const path = url.pathname.replace("/api/v1/", "");
      requests.push({
        path,
        query: url.searchParams,
        method: options?.method ?? "GET",
      });
      return Promise.resolve(handler(path, url.searchParams, options));
    },
  );
  vi.stubGlobal("fetch", fetch);
  return { fetch, requests };
}
export async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}
export async function visibility(value: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value,
  });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
}
