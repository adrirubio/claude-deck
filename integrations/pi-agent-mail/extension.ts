import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'
import type { TSchema } from 'typebox'
import { MailGeneration, PaneFence, failure, resolvePaneIdentity, toolResultOverride } from './client.ts'
import { manifest } from './manifest.ts'

export default function deckMail(pi: ExtensionAPI) {
  if (process.env.CLAUDE_DECK_MAIL_OPT_IN !== '1') return
  let generation: MailGeneration | undefined
  let startup: Promise<void> | undefined
  const stop = async () => {
    const old = generation
    generation = undefined
    await old?.close()
    await startup?.catch(() => undefined)
    startup = undefined
  }
  pi.on('session_start', async (_event, ctx) => {
    await stop()
    try {
      generation = new MailGeneration(new PaneFence(resolvePaneIdentity()))
      startup = generation.start(ctx.cwd)
      await startup
    } catch {
      ctx.ui.notify('Deck Agent Mail is unavailable or fenced. Tools remain disabled; operator recovery may be required.', 'error')
    }
  })
  pi.on('session_shutdown', stop)
  pi.on('tool_result', event => toolResultOverride(event))
  for (const tool of manifest) {
    pi.registerTool({
      name: tool.name,
      label: tool.name,
      description: tool.description,
      parameters: tool.inputSchema as unknown as TSchema,
      async execute(_toolCallId, params, signal) {
        const selected = generation
        const pending = startup
        if (!selected) return failure('mail_not_ready')
        await pending?.catch(() => undefined)
        if (selected !== generation) return failure('mail_generation_changed')
        return selected.call(tool.name, params as Record<string, unknown>, signal)
      },
    })
  }
}
