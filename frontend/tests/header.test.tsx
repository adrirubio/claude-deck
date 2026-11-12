import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Header } from "../src/components/layout/Header";

vi.mock("../src/contexts/ThemeContext", () => ({ useTheme: () => ({ theme: "dark" }) }));
vi.mock("../src/hooks/useSystemStatus", () => ({ useSystemStatus: () => null }));
vi.mock("../src/hooks/useInstanceDocumentTitle", () => ({ useInstanceDocumentTitle: () => undefined }));
vi.mock("../src/contexts/ProviderContext", () => ({
  useProviderContext: () => ({ providers: [], selectedProviderId: "", selectedProvider: null }),
}));

function renderHeader() {
  return render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
}

describe("Header", () => {
  it("shows the logo only, without a repeated visible product name", () => {
    renderHeader();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("announces the product name exactly once through the logo alt text", () => {
    renderHeader();
    const logo = screen.getByAltText("Albiex Synth City");
    expect(logo.tagName).toBe("IMG");
    expect(screen.queryAllByText("Albiex Synth City")).toHaveLength(0);
  });

  it("keeps the subtitle, and hides it below the sm breakpoint so the narrow header fits one row", () => {
    renderHeader();
    const subtitle = screen.getByText("Your local agent command centre");
    expect(subtitle).toBeInTheDocument();
    expect(subtitle).toHaveClass("hidden", "sm:block");
  });

  it("keeps the header on one row and lets the toggle stay beside the logo", () => {
    const { container } = renderHeader();
    const row = container.querySelector("header > div");
    expect(row).not.toHaveClass("flex-wrap");
    for (const group of Array.from(row?.children ?? [])) {
      expect(group).not.toHaveClass("flex-wrap");
    }
    expect(row?.lastElementChild).toHaveClass("min-w-0", "gap-1", "sm:gap-2");
    expect(screen.getByAltText("Albiex Synth City")).toHaveClass("shrink-0");
    expect(screen.getByRole("button", { name: "Toggle theme" }).parentElement).toHaveClass("shrink-0");
  });
});
