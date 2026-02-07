import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer'

interface Props {
  text: string
}

export function TextBlock({ text }: Props) {
  return <MarkdownRenderer content={text} />
}
