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

  it("keeps the subtitle", () => {
    renderHeader();
    expect(screen.getByText("Your local agent command centre")).toBeInTheDocument();
  });
});
