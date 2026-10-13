import type { Locator, Page } from '@playwright/test'

// WCAG 2.x AA text contrast, measured in the rendered page.
// Normal text needs 4.5:1. Large text (at least 24px, or at least 18.66px and
// bold) needs 3:1. Colours are normalised through a 1x1 canvas, so any CSS
// colour syntax (rgb, hsl, oklch, color()) becomes sRGB. Semi-transparent
// backgrounds are composited up the ancestor chain onto the page background.

export type Theme = 'light' | 'dark'

export interface ContrastFailure {
  text: string
  ratio: number
  required: number
  color: string
  background: string
}

// The theme that useTheme() set for each page, so the settle step can wait for it.
const expectedThemes = new WeakMap<Page, Theme>()

/** Open pages in this theme. ThemeContext reads localStorage "theme" on load. */
export async function useTheme(page: Page, theme: Theme): Promise<void> {
  expectedThemes.set(page, theme)
  await page.addInitScript(value => window.localStorage.setItem('theme', value), theme)
}

// A settled page has its theme class and no running transition. A transition
// that does not end within this time fails the journey instead of hanging it.
export const SETTLE_TIMEOUT_MS = 3_000

/**
 * Wait until colours are final before a contrast measurement (#644):
 * - <html> has the theme class that useTheme() asked for. ThemeContext adds it
 *   after the first paint, and `transition-colors` then animates every button
 *   from its light colours to its dark ones for about 150 ms;
 * - the pointer is away from the content, so no hover state is active;
 * - no finite animation or transition is running, for two frames in a row.
 *   Infinite animations (spinners) are ignored: they never end.
 */
export async function settleForContrast(page: Page): Promise<void> {
  await page.mouse.move(0, 0)
  const theme = expectedThemes.get(page) ?? null
  try {
    await page.waitForFunction(expected => {
      if (expected && !document.documentElement.classList.contains(expected)) return false
      const running = document.getAnimations().filter(animation => {
        const timing = animation.effect?.getComputedTiming()
        const finite = timing ? Number.isFinite(timing.endTime as number) : true
        return finite && (animation.playState === 'running' || animation.pending)
      })
      const state = window as unknown as { __e2eQuietFrames?: number }
      state.__e2eQuietFrames = running.length === 0 ? (state.__e2eQuietFrames ?? 0) + 1 : 0
      return state.__e2eQuietFrames >= 2
    }, theme, { timeout: SETTLE_TIMEOUT_MS, polling: 'raf' })
  } catch (error) {
    throw new Error(
      `contrast: the page did not settle within ${SETTLE_TIMEOUT_MS} ms ` +
      `(theme ${theme ?? 'not set'}; a transition or animation is still running)`,
      { cause: error },
    )
  } finally {
    await page.evaluate(() => { delete (window as unknown as { __e2eQuietFrames?: number }).__e2eQuietFrames })
  }
}

/** Every visible text element under `root` that fails AA contrast, measured once the page settles. */
export async function contrastFailures(root: Locator): Promise<ContrastFailure[]> {
  await settleForContrast(root.page())
  return root.evaluate((rootElement: Element) => {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) throw new Error('no 2d canvas')

    type RGBA = [number, number, number, number]
    const toRGBA = (css: string): RGBA => {
      ctx.clearRect(0, 0, 1, 1)
      ctx.fillStyle = 'rgba(0, 0, 0, 0)'
      ctx.fillStyle = css
      ctx.fillRect(0, 0, 1, 1)
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data
      return [r, g, b, a / 255]
    }
    const over = (top: RGBA, bottom: RGBA): RGBA => {
      const a = top[3] + bottom[3] * (1 - top[3])
      if (a === 0) return [0, 0, 0, 0]
      const mix = (i: number) => (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / a
      return [mix(0), mix(1), mix(2), a]
    }
    const luminance = ([r, g, b]: RGBA) => {
      const lin = (c: number) => {
        const s = c / 255
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
      }
      return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    }
    const ratio = (a: RGBA, b: RGBA) => {
      const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
      return (hi + 0.05) / (lo + 0.05)
    }
    const pageBackground = (): RGBA => {
      const body = toRGBA(getComputedStyle(document.body).backgroundColor)
      const html = toRGBA(getComputedStyle(document.documentElement).backgroundColor)
      return over(body, over(html, [255, 255, 255, 1]))
    }
    const effectiveBackground = (element: Element): RGBA | null => {
      const layers: RGBA[] = []
      for (let node: Element | null = element; node; node = node.parentElement) {
        const style = getComputedStyle(node)
        // A background image hides the real colour; skip such text.
        if (style.backgroundImage && style.backgroundImage !== 'none') return null
        const layer = toRGBA(style.backgroundColor)
        if (layer[3] > 0) layers.push(layer)
        if (layer[3] >= 1) break
      }
      let colour = pageBackground()
      for (const layer of layers.reverse()) colour = over(layer, colour)
      return colour
    }

    const failures: ContrastFailure[] = []
    const seen = new Set<Element>()
    const walker = document.createTreeWalker(rootElement, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = (node.textContent ?? '').trim()
      const element = node.parentElement
      if (!text || !element || seen.has(element)) continue
      seen.add(element)
      const style = getComputedStyle(element)
      const box = element.getBoundingClientRect()
      if (box.width === 0 || box.height === 0 || style.visibility === 'hidden') continue
      if (Number(style.opacity) === 0 || element.closest('[aria-hidden="true"], .sr-only')) continue
      const background = effectiveBackground(element)
      if (!background) continue
      const opacity = Number(style.opacity)
      const fg = toRGBA(style.color)
      const colour = over([fg[0], fg[1], fg[2], fg[3] * opacity], background)
      const size = parseFloat(style.fontSize)
      const bold = Number(style.fontWeight) >= 700
      const required = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5
      const measured = ratio(colour, background)
      // Disabled controls are exempt from the contrast requirement.
      if (element.closest(':disabled, [aria-disabled="true"]')) continue
      if (measured + 0.005 < required) {
        failures.push({
          text: text.slice(0, 60),
          ratio: Math.round(measured * 100) / 100,
          required,
          color: style.color,
          background: `rgb(${background.slice(0, 3).map(Math.round).join(', ')})`,
        })
      }
    }
    return failures
  })
}
