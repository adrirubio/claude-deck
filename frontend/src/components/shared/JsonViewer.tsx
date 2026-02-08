interface JsonViewerProps {
  data: string | Record<string, unknown>
  className?: string
}

export function JsonViewer({ data, className = '' }: JsonViewerProps) {
  const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2)

  return (
    <pre className={`bg-muted p-4 rounded-md overflow-auto text-sm ${className}`}>
      <code>{content}</code>
    </pre>
  )
}
