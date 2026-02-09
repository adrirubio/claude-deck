import { TextBlock } from './blocks/TextBlock'
import { ThinkingBlock } from './blocks/ThinkingBlock'
import { ToolUseBlock } from './blocks/ToolUseBlock'
import { ToolResultBlock } from './blocks/ToolResultBlock'
import { ImageBlock } from './blocks/ImageBlock'
import type { ContentBlock } from '@/types/sessions'

interface Props {
  block: ContentBlock
}

export function ContentBlockRenderer({ block }: Props) {
  switch (block.type) {
    case 'text':
      return <TextBlock text={block.text || ''} />

    case 'thinking':
      return <ThinkingBlock thinking={block.thinking || ''} />

    case 'tool_use':
      return (
        <ToolUseBlock
          name={block.name || ''}
          id={block.id || ''}
          input={block.input || {}}
        />
      )

    case 'tool_result':
      return (
        <ToolResultBlock
          tool_use_id={block.id || ''}
          content={block.content ?? ''}
          is_error={block.is_error || false}
        />
      )

    case 'image':
      return <ImageBlock source={block.source || {}} />

    default:
      return (
        <div className="text-xs text-muted-foreground">
          Unknown block type: {block.type}
        </div>
      )
  }
}
