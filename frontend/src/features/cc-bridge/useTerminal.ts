import { useRef, useCallback, useState, useEffect } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebglAddon } from '@xterm/addon-webgl'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import { fetchTerminalToken, buildTerminalWsUrl } from './api'
import type { TeamSlotTerminalTheme } from '@/lib/agentTeamColors'
import type { LeaderNavigationDirection } from './types'

const DEFAULT_TERMINAL_THEME: TeamSlotTerminalTheme = {
  background: '#1e1e2e',
  foreground: '#cdd6f4',
  cursor: '#f5e0dc',
  selectionBackground: '#585b7066',
}

const LEADER_TIMEOUT_MS = 2000
const LEADER_PREFIX_INPUT = '\x00'

interface TerminalShortcutOptions {
  target?: string | null
  onLeaderNavigate?: (sourceTarget: string, direction: LeaderNavigationDirection) => void
  onLeaderStateChange?: (sourceTarget: string, active: boolean) => void
}

function isLeaderPrefix(event: KeyboardEvent): boolean {
  return (
    event.ctrlKey
    && !event.altKey
    && !event.metaKey
    && !event.shiftKey
    && (event.code === 'Space' || event.key === ' ' || event.key === 'Spacebar')
  )
}

function keyHasCommandModifier(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.altKey || event.metaKey
}

function shortcutDirection(event: KeyboardEvent): LeaderNavigationDirection | null {
  if (keyHasCommandModifier(event)) return null
  if (event.key === 'ArrowLeft') return 'prev'
  if (event.key === 'ArrowRight') return 'next'
  if (/^[1-4]$/.test(event.key)) return Number(event.key)
  return null
}

export function useTerminal(
  containerRef: React.RefObject<HTMLDivElement | null>,
  wrapperRef: React.RefObject<HTMLDivElement | null>,
  terminalTheme?: TeamSlotTerminalTheme | null,
  shortcutOptions: TerminalShortcutOptions = {},
) {
  const termRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const themeRef = useRef<TeamSlotTerminalTheme>(terminalTheme ?? DEFAULT_TERMINAL_THEME)
  const sourceTargetRef = useRef<string | null>(shortcutOptions.target ?? null)
  const onLeaderNavigateRef = useRef(shortcutOptions.onLeaderNavigate)
  const onLeaderStateChangeRef = useRef(shortcutOptions.onLeaderStateChange)
  const leaderArmedRef = useRef(false)
  const leaderTimeoutRef = useRef<number | null>(null)
  const [connected, setConnected] = useState(false)
  const [readOnly, setReadOnly] = useState(true)
  const readOnlyRef = useRef(true)

  useEffect(() => {
    sourceTargetRef.current = shortcutOptions.target ?? null
    onLeaderNavigateRef.current = shortcutOptions.onLeaderNavigate
    onLeaderStateChangeRef.current = shortcutOptions.onLeaderStateChange
  }, [shortcutOptions.onLeaderNavigate, shortcutOptions.onLeaderStateChange, shortcutOptions.target])

  useEffect(() => {
    readOnlyRef.current = readOnly
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'mode', readOnly }))
    }
  }, [readOnly])

  const notifyLeaderState = useCallback((active: boolean) => {
    const sourceTarget = sourceTargetRef.current
    if (!sourceTarget) return
    onLeaderStateChangeRef.current?.(sourceTarget, active)
  }, [])

  const clearLeaderTimeout = useCallback(() => {
    if (leaderTimeoutRef.current === null) return
    window.clearTimeout(leaderTimeoutRef.current)
    leaderTimeoutRef.current = null
  }, [])

  const emitLeaderPrefix = useCallback(() => {
    termRef.current?.input(LEADER_PREFIX_INPUT)
  }, [])

  const disarmLeader = useCallback(() => {
    if (!leaderArmedRef.current) return
    clearLeaderTimeout()
    leaderArmedRef.current = false
    notifyLeaderState(false)
  }, [clearLeaderTimeout, notifyLeaderState])

  const armLeader = useCallback(() => {
    clearLeaderTimeout()
    leaderArmedRef.current = true
    notifyLeaderState(true)
    leaderTimeoutRef.current = window.setTimeout(() => {
      if (!leaderArmedRef.current) return
      leaderArmedRef.current = false
      leaderTimeoutRef.current = null
      emitLeaderPrefix()
      notifyLeaderState(false)
    }, LEADER_TIMEOUT_MS)
  }, [clearLeaderTimeout, emitLeaderPrefix, notifyLeaderState])

  const initTerminal = useCallback(() => {
    if (termRef.current || !containerRef.current) return

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
      theme: themeRef.current,
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(new WebLinksAddon())

    term.open(containerRef.current)
    term.attachCustomKeyEventHandler((event) => {
      if (event.type !== 'keydown' || event.isComposing) return true
      if (!sourceTargetRef.current) return true

      if (!leaderArmedRef.current) {
        if (!isLeaderPrefix(event)) return true
        event.preventDefault()
        event.stopPropagation()
        armLeader()
        return false
      }

      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        disarmLeader()
        return false
      }

      const direction = shortcutDirection(event)
      if (direction !== null) {
        event.preventDefault()
        event.stopPropagation()
        const sourceTarget = sourceTargetRef.current
        if (!sourceTarget) return false
        disarmLeader()
        onLeaderNavigateRef.current?.(sourceTarget, direction)
        return false
      }

      if (!keyHasCommandModifier(event) && event.key.toLowerCase() === 'r') {
        event.preventDefault()
        event.stopPropagation()
        disarmLeader()
        setReadOnly((current) => !current)
        return false
      }

      disarmLeader()
      emitLeaderPrefix()
      return true
    })

    try {
      term.loadAddon(new WebglAddon())
    } catch {
      // WebGL not available, canvas fallback is fine
    }

    fitAddon.fit()
    termRef.current = term
    fitAddonRef.current = fitAddon
  }, [armLeader, containerRef, disarmLeader, emitLeaderPrefix])

  useEffect(() => {
    themeRef.current = terminalTheme ?? DEFAULT_TERMINAL_THEME
    if (!termRef.current) return
    termRef.current.options.theme = themeRef.current
  }, [terminalTheme])

  const attach = useCallback(async (target: string) => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    initTerminal()
    const term = termRef.current
    if (!term) return

    term.clear()

    const { token } = await fetchTerminalToken()

    // Guard against StrictMode race: if the terminal was disposed and replaced
    // during the async token fetch, this attach call is stale — bail out.
    if (termRef.current !== term) return

    const mode = readOnlyRef.current ? 'readonly' : 'interactive'
    const url = buildTerminalWsUrl(target, token, mode)

    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      requestAnimationFrame(() => {
        fitAddonRef.current?.fit()
        const dims = fitAddonRef.current?.proposeDimensions()
        if (dims) {
          ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
        }
      })
    }

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(event.data))
      } else {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'error') {
            term.writeln(`\r\n\x1b[31mError: ${msg.message}\x1b[0m`)
          }
        } catch {
          term.write(event.data)
        }
      }
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setConnected(false)
    }

    const onDataDisposable = term.onData((data) => {
      if (!readOnlyRef.current && ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    const onResizeDisposable = term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
      }
    })

    ws.addEventListener('close', () => {
      onDataDisposable.dispose()
      onResizeDisposable.dispose()
    }, { once: true })
  }, [initTerminal])

  const detach = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    disarmLeader()
    setConnected(false)
    termRef.current?.clear()
    termRef.current?.writeln('\x1b[90mDetached.\x1b[0m')
  }, [disarmLeader])

  const focusTerminal = useCallback(() => {
    termRef.current?.focus()
  }, [])

  // Observe the stable wrapper element (not the xterm container) to avoid feedback loops
  useEffect(() => {
    const wrapper = wrapperRef.current
    if (!wrapper) return

    let rafId: number | null = null
    const observer = new ResizeObserver(() => {
      if (rafId) cancelAnimationFrame(rafId)
      rafId = requestAnimationFrame(() => {
        if (!fitAddonRef.current) return
        fitAddonRef.current.fit()
        // Sync new dimensions to backend
        const dims = fitAddonRef.current.proposeDimensions()
        if (dims && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
        }
      })
    })
    observer.observe(wrapper)
    return () => {
      observer.disconnect()
      if (rafId) cancelAnimationFrame(rafId)
    }
  }, [wrapperRef])

  useEffect(() => {
    return () => {
      clearLeaderTimeout()
      if (leaderArmedRef.current) {
        leaderArmedRef.current = false
        notifyLeaderState(false)
      }
      wsRef.current?.close()
      wsRef.current = null
      termRef.current?.dispose()
      termRef.current = null
      fitAddonRef.current = null
    }
  }, [clearLeaderTimeout, notifyLeaderState])

  return { connected, readOnly, setReadOnly, attach, detach, focusTerminal }
}
