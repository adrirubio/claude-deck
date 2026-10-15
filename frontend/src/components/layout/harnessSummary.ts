type HarnessStatus = { display_name: string; installed: boolean; version?: string | null; unavailable_reason?: string | null };

/** One header badge for every harness, so the header keeps one row as harnesses are added. */
export function harnessSummary(harnesses: HarnessStatus[]) {
  const missing = harnesses.filter((harness) => !harness.installed).length;
  const noun = harnesses.length === 1 ? "harness" : "harnesses";
  return {
    label: missing ? `${missing} of ${harnesses.length} ${noun} missing` : `${harnesses.length} ${noun}`,
    problem: missing > 0,
    title: harnesses
      .map((harness) =>
        harness.installed
          ? `${harness.display_name} ${harness.version ? `v${harness.version}` : "installed"}`
          : `${harness.display_name} missing${harness.unavailable_reason ? `: ${harness.unavailable_reason}` : ""}`
      )
      .join("\n"),
  };
}
