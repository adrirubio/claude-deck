import { describe, expect, it } from 'vitest'
// @ts-expect-error The check script is plain ESM without type declarations.
import { checkDirectory, findUnpairedClasses } from '../scripts/check-dark-pairs.mjs'

type Finding = { line: number; className: string }
const find = findUnpairedClasses as (source: string) => Finding[]

describe('check-dark-pairs', () => {
  it('fails on a light-only 300 or 400 text colour', () => {
    expect(find(`const a = 'rounded text-amber-400'`)).toEqual([{ line: 1, className: 'text-amber-400' }])
    expect(find('const b = `border text-blue-300 p-2`')).toEqual([{ line: 1, className: 'text-blue-300' }])
  })

  it('passes when the same string has a dark partner', () => {
    expect(find(`const a = 'text-blue-700 dark:text-blue-300'`)).toEqual([])
    expect(find(`const a = 'text-amber-400 dark:text-amber-400'`)).toEqual([])
  })

  it('ignores darker shades and a dark-only utility', () => {
    expect(find(`const a = 'text-blue-700'`)).toEqual([])
    expect(find(`const a = 'dark:text-blue-300'`)).toEqual([])
  })

  it('allows an exception with a reason on the same line or the line above', () => {
    expect(find(`// contrast-exempt: bg-zinc-900 in both themes\nconst a = 'text-red-400'`)).toEqual([])
    expect(find(`const a = 'text-red-400' // contrast-exempt: bg-zinc-900 in both themes`)).toEqual([])
  })

  it('rejects an exception comment without a reason', () => {
    expect(find(`// contrast-exempt:\nconst a = 'text-red-400'`)).toHaveLength(1)
  })

  it('finds no unpaired class in the application source', () => {
    expect((checkDirectory('src') as Array<Finding & { file: string }>).map(f => `${f.file}:${f.line} ${f.className}`)).toEqual([])
  })
})
