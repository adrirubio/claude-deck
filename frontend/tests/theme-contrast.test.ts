import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// #510: every text and background token pair meets WCAG AA (4.5:1) in both themes.
const css = readFileSync(resolve(__dirname, '../src/index.css'), 'utf8')

function tokens(selector: string) {
  const block = new RegExp(`${selector}\\s*\\{([^}]*)\\}`).exec(css)
  if (!block) throw new Error(`No ${selector} block in index.css`)
  const result: Record<string, [number, number, number]> = {}
  for (const [, name, h, s, l] of block[1].matchAll(/--([\w-]+):\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%;/g))
    result[name] = [Number(h), Number(s), Number(l)]
  return result
}

function rgb([h, s, l]: [number, number, number]) {
  const saturation = s / 100
  const lightness = l / 100
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation
  const x = chroma * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = lightness - chroma / 2
  const [r, g, b] = [[chroma, x, 0], [x, chroma, 0], [0, chroma, x], [0, x, chroma], [x, 0, chroma], [chroma, 0, x]][Math.floor(h / 60) % 6]
  return [r + m, g + m, b + m]
}

function luminance(color: [number, number, number]) {
  const [r, g, b] = rgb(color).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: [number, number, number], b: [number, number, number]) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

// [text token, background token]
const pairs: [string, string][] = [
  ['foreground', 'background'],
  ['card-foreground', 'card'],
  ['popover-foreground', 'popover'],
  ['primary-foreground', 'primary'],
  ['secondary-foreground', 'secondary'],
  ['accent-foreground', 'accent'],
  ['destructive-foreground', 'destructive'],
  ['success-foreground', 'success'],
  ['warning-foreground', 'warning'],
  ['info-foreground', 'info'],
  ['muted-foreground', 'background'],
  ['muted-foreground', 'card'],
  ['muted-foreground', 'muted'],
  ['muted-foreground', 'accent'],
  ['primary', 'background'],
  ['primary', 'card'],
  ['primary', 'accent'],
  ['destructive', 'background'],
  ['destructive', 'card'],
  ['destructive', 'accent'],
]

describe('theme contrast', () => {
  for (const [theme, selector] of [['light', ':root'], ['dark', '\\.dark']] as const) {
    describe(theme, () => {
      const t = tokens(selector)
      for (const [text, background] of pairs) {
        if (!t[text] || !t[background]) continue
        it(`${text} on ${background} is at least 4.5:1`, () => {
          expect(contrast(t[text], t[background])).toBeGreaterThanOrEqual(4.5)
        })
      }
    })
  }

  it('keeps the accent surface neutral so hover and selected states are not green', () => {
    for (const selector of [':root', '\\.dark']) {
      const t = tokens(selector)
      expect(t.accent[1]).toBe(0)
      expect(t.accent).not.toEqual(t.primary)
    }
  })
})
