// telegram-mcp-stub.js — a do-nothing MCP server over stdio (newline-delimited JSON-RPC), run by telegram-mcp-launch
// when no bot token exists. Claude Code records a successful connection with no tools, instead of the failed start
// (and the 15-minute machine-wide failure cache) the real server causes by exiting without a token.
// Lives until stdin closes.
'use strict'
const EMPTY = { 'tools/list': { tools: [] }, 'prompts/list': { prompts: [] }, 'resources/list': { resources: [] },
  'resources/templates/list': { resourceTemplates: [] } }
function send(msg) { process.stdout.write(JSON.stringify({ jsonrpc: '2.0', ...msg }) + '\n') }
function handle(line) {
  let m
  try { m = JSON.parse(line) } catch { return }
  if (!m || typeof m !== 'object' || m.method === undefined || m.id === undefined) return   // notifications and replies
  if (m.method === 'initialize') {
    send({ id: m.id, result: { protocolVersion: (m.params && m.params.protocolVersion) || '2025-06-18',
      capabilities: { tools: {}, prompts: {}, resources: {} }, serverInfo: { name: 'telegram-stub', version: '0' } } })
  } else if (m.method === 'ping') send({ id: m.id, result: {} })
  else if (EMPTY[m.method]) send({ id: m.id, result: EMPTY[m.method] })
  else send({ id: m.id, error: { code: -32601, message: 'Method not found' } })
}
let buf = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (d) => {
  buf += d
  let i
  while ((i = buf.indexOf('\n')) >= 0) { const l = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (l) handle(l) }
})
process.stdin.on('end', () => process.exit(0))
