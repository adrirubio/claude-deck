import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useInstanceDocumentTitle } from "../src/hooks/useInstanceDocumentTitle";
import type { InstanceIdentity } from "../src/types/status";

const instance: InstanceIdentity = {
  id: "abc",
  name: "This machine",
  name_configured: false,
  hostname: "linux-box.local",
  short_hostname: "linux-box",
  accent: "blue",
  started_at: "2026-10-12T00:00:00Z",
};

afterEach(() => {
  document.title = "";
});

describe("instance document title", () => {
  it("stays Claude Deck when no name is configured", () => {
    renderHook(() => useInstanceDocumentTitle(instance));
    expect(document.title).toBe("Claude Deck");
  });

  it("stays Claude Deck before the status loads", () => {
    renderHook(() => useInstanceDocumentTitle(null));
    expect(document.title).toBe("Claude Deck");
  });

  it("carries the name when the operator configured one", () => {
    const { rerender } = renderHook(
      ({ value }) => useInstanceDocumentTitle(value),
      { initialProps: { value: instance } },
    );
    rerender({ value: { ...instance, name: "Studio Mac", name_configured: true } });
    expect(document.title).toBe("Studio Mac · Claude Deck");
    rerender({ value: instance });
    expect(document.title).toBe("Claude Deck");
  });

  it("does not use an old payload without name_configured as a configured name", () => {
    const { name_configured: _unused, ...legacy } = instance;
    void _unused;
    renderHook(() => useInstanceDocumentTitle({ ...legacy, name: "linux-box" }));
    expect(document.title).toBe("Claude Deck");
  });
});
