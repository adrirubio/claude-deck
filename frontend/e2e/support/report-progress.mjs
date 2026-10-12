#!/usr/bin/env node
// Print a Markdown progress table for the @pending journeys, one row per gate.
// Input: the Playwright JSON report. Output: GitHub step summary text.
import { readFileSync, existsSync } from 'node:fs'

const reportPath = process.argv[2] ?? 'test-results/results.json'
if (!existsSync(reportPath)) {
  console.log('## E2E pending journeys\n\nNo report was written. Read the job log.')
  process.exit(0)
}
const report = JSON.parse(readFileSync(reportPath, 'utf8'))

const gates = new Map()
function visit(suite, file) {
  const here = suite.file ?? file
  for (const spec of suite.specs ?? []) {
    const gate = (spec.file ?? here ?? 'unknown').split('/')[0]
    const row = gates.get(gate) ?? { passed: 0, failed: 0, skipped: 0, titles: [] }
    for (const t of spec.tests ?? []) {
      const status = t.results?.at(-1)?.status ?? 'skipped'
      if (status === 'passed') row.passed += 1
      else if (status === 'skipped') row.skipped += 1
      else {
        row.failed += 1
        row.titles.push(spec.title)
      }
    }
    gates.set(gate, row)
  }
  for (const child of suite.suites ?? []) visit(child, here)
}
for (const suite of report.suites ?? []) visit(suite, suite.file)

const lines = ['## E2E pending journeys', '', '| Gate | Pass | Fail | Skipped |', '|---|---:|---:|---:|']
for (const [gate, row] of [...gates.entries()].sort()) {
  lines.push(`| ${gate} | ${row.passed} | ${row.failed} | ${row.skipped} |`)
}
const failing = [...gates.entries()].flatMap(([gate, row]) => row.titles.map(t => `- ${gate}: ${t}`))
if (failing.length) lines.push('', 'Pending journeys that do not pass yet:', '', ...failing)
lines.push('', 'A pending journey that passes can move to @active when its lane gate passes.')
console.log(lines.join('\n'))
