// T-G2 executes the shipped migration against the old fixture's two namespaces.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const request = JSON.parse(readFileSync(process.argv[2], 'utf8'))
class Storage {
  constructor(values) { this.values = new Map(Object.entries(values)); this.oldReads = 0 }
  get length() { return this.values.size }
  key(index) { return [...this.values.keys()][index] ?? null }
  getItem(key) { if (/claude-deck|^deck-/.test(key)) this.oldReads++; return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(String(key), String(value)) }
  removeItem(key) { this.values.delete(key) }
  clear() { this.values.clear() }
  snapshot() { return Object.fromEntries(this.values) }
}
globalThis.window = {
  localStorage: new Storage(request.localStorage),
  sessionStorage: new Storage(request.sessionStorage),
}
const { migrateBrowserStorage } = await import(pathToFileURL(process.argv[3]).href)
const first = migrateBrowserStorage()
const state = () => ({localStorage: window.localStorage.snapshot(), sessionStorage: window.sessionStorage.snapshot()})
const after = state()
window.localStorage.oldReads = 0
window.sessionStorage.oldReads = 0
const second = migrateBrowserStorage()
if (JSON.stringify(after) !== JSON.stringify(state())) throw new Error('Second load changed browser state')
if (window.localStorage.oldReads || window.sessionStorage.oldReads) throw new Error('Completed conversion read an old key')
console.log(JSON.stringify({ state: after, first, second }))
