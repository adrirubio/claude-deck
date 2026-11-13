import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Header } from "../src/components/layout/Header";

const WARNING = "Host agent CLIs are not visible from this container.";
const LABEL = "Container cannot see host agent CLIs";

const mocks = vi.hoisted(() => ({ status: null as unknown }));

vi.mock("../src/contexts/ThemeContext", () => ({ useTheme: () => ({ theme: "dark" }) }));
vi.mock("../src/hooks/useSystemStatus", () => ({ useSystemStatus: () => mocks.status }));
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

function statusWithWarning(warning: string | null) {
  return {
    claudeCodeVersion: null,
    activeSessions: 0,
    providers: {},
    instance: null,
    environment: { containerized: true, agent_cli_warning: warning },
  };
}

beforeEach(() => {
  mocks.status = null;
});

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

  it("shows no container warning when the status has none", () => {
    mocks.status = statusWithWarning(null);
    renderHeader();
    expect(screen.queryByRole("button", { name: new RegExp(LABEL) })).not.toBeInTheDocument();
  });

  describe("container warning", () => {
    beforeEach(() => {
      mocks.status = statusWithWarning(WARNING);
    });

    it("is a button with the full warning in its accessible name, and its text hides below sm", () => {
      renderHeader();
      const warning = screen.getByRole("button", { name: `${LABEL}. ${WARNING}` });
      expect(warning).toHaveAttribute("title", WARNING);
      // Icon only below sm: the button keeps its size, so the instance badge absorbs a narrow row.
      expect(warning).toHaveClass("shrink-0", "sm:shrink", "sm:min-w-0");
      expect(screen.getByText(LABEL, { selector: "span" })).toHaveClass("hidden", "sm:inline");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("opens the full warning by keyboard and closes it with Escape", async () => {
      const user = userEvent.setup();
      renderHeader();
      const warning = screen.getByRole("button", { name: new RegExp(LABEL) });
      warning.focus();
      await user.keyboard("{Enter}");
      const dialog = await screen.findByRole("dialog");
      expect(dialog).toHaveTextContent(WARNING);
      // Side padding keeps the title clear of the close button and its focus ring.
      expect(screen.getByRole("heading", { name: LABEL }).parentElement).toHaveClass("px-5");
      await user.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("opens the full warning with the Space key", async () => {
      const user = userEvent.setup();
      renderHeader();
      screen.getByRole("button", { name: new RegExp(LABEL) }).focus();
      await user.keyboard(" ");
      expect(await screen.findByRole("dialog")).toHaveTextContent(WARNING);
    });

    it("opens the full warning on a click or a tap", async () => {
      const user = userEvent.setup();
      renderHeader();
      await user.click(screen.getByRole("button", { name: new RegExp(LABEL) }));
      expect(await screen.findByRole("dialog")).toHaveTextContent(WARNING);
    });
  });
});
