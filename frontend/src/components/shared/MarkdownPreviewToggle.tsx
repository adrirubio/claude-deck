import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MarkdownRenderer } from './MarkdownRenderer'

interface MarkdownPreviewToggleProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  minHeight?: string
  disabled?: boolean
  defaultTab?: 'edit' | 'preview'
}

export function MarkdownPreviewToggle({
  value,
  onChange,
  placeholder = 'Write markdown content...',
  minHeight = '300px',
  disabled = false,
  defaultTab = 'edit',
}: MarkdownPreviewToggleProps) {
  return (
    <Tabs defaultValue={defaultTab} className="w-full">
      <TabsList className="grid w-full grid-cols-2">
        <TabsTrigger value="edit">Edit</TabsTrigger>
        <TabsTrigger value="preview">Preview</TabsTrigger>
      </TabsList>
      <TabsContent value="edit" className="mt-2">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full p-4 font-mono text-sm border rounded-md resize-y focus:outline-none focus:ring-2 focus:ring-ring bg-background text-foreground"
          style={{ minHeight }}
          placeholder={placeholder}
          disabled={disabled}
        />
      </TabsContent>
      <TabsContent value="preview" className="mt-2">
        <div
          className="border rounded-md p-4 overflow-auto bg-muted/30"
          style={{ minHeight }}
        >
          {value ? (
            <MarkdownRenderer content={value} />
          ) : (
            <p className="text-muted-foreground italic">Nothing to preview</p>
          )}
        </div>
      </TabsContent>
    </Tabs>
  )
}
