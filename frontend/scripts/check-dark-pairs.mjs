// Fails on a light-only status colour: a text-<colour>-300 or text-<colour>-400
// class with no dark:text-* class in the same quoted string. Those shades do not
// meet 4.5:1 contrast on a light surface (#510, #577, #592).
//
// An exception for a surface that is dark in both themes needs a comment
// "contrast-exempt: <reason>" on the same line or on the line above.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SHADE = /(?<![\w:-])text-[a-z]+-(?:300|400)(?![\w-])/
const DARK_PAIR = /(?<![\w-])dark:text-/
const EXEMPT = /contrast-exempt:\s*\S/
const QUOTED = /(["'`])((?:\\.|(?!\1).)*)\1/g
const SOURCE = /\.(?:tsx?|jsx?)$/

/** Findings for one source text: [{ line, className }]. */
export function findUnpairedClasses(source) {
  const lines = source.split('\n')
  const found = []
  lines.forEach((text, index) => {
    for (const match of text.matchAll(QUOTED)) {
      const value = match[2]
      const shade = value.match(SHADE)
      if (!shade || DARK_PAIR.test(value)) continue
      const exempt = EXEMPT.test(text) || (index > 0 && EXEMPT.test(lines[index - 1]))
      if (!exempt) found.push({ line: index + 1, className: shade[0] })
    }
  })
  return found
}

function* sourceFiles(directory) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) yield* sourceFiles(path)
    else if (SOURCE.test(name)) yield path
  }
}

/** Findings for every file under a directory: [{ file, line, className }]. */
export function checkDirectory(directory) {
  const findings = []
  for (const file of sourceFiles(directory)) {
    for (const finding of findUnpairedClasses(readFileSync(file, 'utf8'))) {
      findings.push({ file: relative(process.cwd(), file), ...finding })
    }
  }
  return findings
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = process.argv[2] ?? 'src'
  const findings = checkDirectory(root)
  for (const { file, line, className } of findings) {
    console.error(`${file}:${line}: ${className} has no dark:text-* partner. Use a pair such as text-blue-700 dark:text-blue-300, or add "contrast-exempt: <reason>".`)
  }
  if (findings.length > 0) process.exit(1)
  console.log('check-dark-pairs: no unpaired light-only text colours')
}
