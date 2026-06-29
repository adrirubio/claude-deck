import { useRef, useCallback, useState, useEffect } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebglAddon } from '@xterm/addon-webgl'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import { fetchTerminalToken, buildTerminalWsUrl } from './api'
import type { TeamSlotTerminalTheme } from '@/lib/agentTeamColors'

const DEFAULT_TERMINAL_THEME: TeamSlotTerminalTheme = {
  background: '#1e1e2e',
  foreground: '#cdd6f4',
  cursor: '#f5e0dc',
  selectionBackground: '#585b7066',
}

export function useTerminal(
  containerRef: React.RefObject<HTMLDivElement | null>,
  wrapperRef: React.RefObject<HTMLDivElement | null>,
  terminalTheme?: TeamSlotTerminalTheme | null,
) {
  const termRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const themeRef = useRef<TeamSlotTerminalTheme>(terminalTheme ?? DEFAULT_TERMINAL_THEME)
  const [connected, setConnected] = useState(false)
  const [readOnly, setReadOnly] = useState(true)
  const readOnlyRef = useRef(true)

  useEffect(() => {
    readOnlyRef.current = readOnly
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'mode', readOnly }))
    }
  }, [readOnly])

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

    try {
      term.loadAddon(new WebglAddon())
    } catch {
      // WebGL not available, canvas fallback is fine
    }

    fitAddon.fit()
    termRef.current = term
    fitAddonRef.current = fitAddon
  }, [containerRef])

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
    setConnected(false)
    termRef.current?.clear()
    termRef.current?.writeln('\x1b[90mDetached.\x1b[0m')
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
      wsRef.current?.close()
      wsRef.current = null
      termRef.current?.dispose()
      termRef.current = null
      fitAddonRef.current = null
    }
  }, [])

  return { connected, readOnly, setReadOnly, attach, detach }
}
