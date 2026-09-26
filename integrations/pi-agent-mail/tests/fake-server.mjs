import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { manifest, privateTools } from '../manifest.ts'

const server = new Server({ name: 'fixture', version: '1' }, { capabilities: { tools: {} } })
let loseClose = false
let errorClose = false
let calls = 0
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [...manifest, ...privateTools] }))
server.setRequestHandler(CallToolRequestSchema, async request => {
  calls++
  const body = request.params.arguments?.body_markdown
  if (body === 'disconnect') process.exit(0)
  if (body === 'lose-close') loseClose = true
  if (body === 'error-close') errorClose = true
  if (body === 'delay') await new Promise(resolve => setTimeout(resolve, 100))
  if (body === 'protocol-error') return { content: [{ type: 'text', text: 'post-write failure' }], isError: true }
  if (body === 'malformed-json') return { content: [{ type: 'text', text: 'not JSON' }] }
  if (body === 'malformed-envelope') return { content: [{ type: 'text', text: JSON.stringify({ committed: true }) }] }
  if (body === 'unsupported-content') return { content: [{ type: 'resource', resource: { uri: 'fixture://result', text: 'committed' } }] }
  const result = request.params.name === '__deck_mail_close_generation'
    ? { ok: !loseClose, closed: !loseClose }
    : body === 'conflict' ? { ok: false, error: { code: 'stale_nonce', status_code: 409 } }
      : body === 'offline' ? { ok: false, error: { code: 'deck_unreachable' } }
        : { ok: true, calls, environmentKeys: Object.keys(process.env) }
  return { content: [{ type: 'text', text: JSON.stringify(result) }], structuredContent: result,
    ...(request.params.name === '__deck_mail_close_generation' && errorClose ? { isError: true } : {}) }
})
await server.connect(new StdioServerTransport())
