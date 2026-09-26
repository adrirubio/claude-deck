import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'

try {
  const packageRoot = dirname(dirname(dirname(process.argv[2])))
  const require = createRequire(import.meta.url)
  require.resolve('@modelcontextprotocol/sdk/client/stdio.js')
  require.resolve('typebox')
  const metadata = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'))
  if (metadata.name !== '@earendil-works/pi-coding-agent' || metadata.version !== '0.87.1') throw new Error()
  const { loadExtensions } = await import(pathToFileURL(join(packageRoot, 'dist/core/extensions/loader.js')).href)
  delete process.env.CLAUDE_DECK_MAIL_OPT_IN
  const result = await loadExtensions([join(import.meta.dirname, 'extension.ts')], import.meta.dirname)
  if (result.errors.length || result.extensions.length !== 1) throw new Error()
  if (result.extensions[0].tools.size || result.extensions[0].handlers.size) throw new Error()
  process.stdout.write('ready')
} catch {
  process.exitCode = 1
}
