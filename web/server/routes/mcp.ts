// A stateless MCP server (Streamable HTTP, JSON responses) so Claude can put text on
// the panel, e.g. when a task is done:  claude mcp add --transport http led http://<pi>/mcp
// shortcut: no auth, like the rest of the API, so keep it on the LAN and tailnet, and add a
// token before it faces the internet.

interface RpcRequest {
  jsonrpc: '2.0'
  id?: string | number
  method: string
  params?: { name?: string; arguments?: Record<string, unknown>; protocolVersion?: string }
}

const EFFECTS = { static: 0, scroll_left: 1, scroll_right: 2, blink: 5, fade: 6, snowflake: 7 } as const

const TOOLS = [
  {
    name: 'show_text',
    description:
      'Show a short message on the 64×16 LED panel on the desk, for example "Done ✓" when a task finishes. About 8 characters fit without scrolling; longer text scrolls.',
    inputSchema: {
      type: 'object',
      properties: {
        text: { type: 'string', maxLength: 200, description: 'The message. Emoji work and take two characters of width.' },
        color: { type: 'string', pattern: '^#?[0-9a-fA-F]{6}$', description: 'Hex color, default 5fcf92 (green).' },
        effect: { type: 'string', enum: Object.keys(EFFECTS), description: 'Default: static if it fits, otherwise scroll_left.' },
      },
      required: ['text'],
    },
  },
  {
    name: 'show_stars',
    description: 'Show the GitHub star count of a repository on the panel. It keeps updating.',
    inputSchema: {
      type: 'object',
      properties: { repo: { type: 'string', pattern: '^[\\w.-]+/[\\w.-]+$', description: 'owner/name. Defaults to the saved repo.' } },
    },
  },
  {
    name: 'panel_status',
    description: 'What the panel shows now, and the tracked repository and star count.',
    inputSchema: { type: 'object', properties: {} },
  },
]

async function callTool(name: string | undefined, args: Record<string, unknown>) {
  const api = (path: string, body?: object) => $fetch<Record<string, unknown>>(`${useRuntimeConfig().ledApi}/${path}`, body ? { method: 'POST', body } : {})

  if (name === 'show_text') {
    const text = String(args.text ?? '').slice(0, 200)
    if (!text) throw new Error('text is required')
    const color = String(args.color ?? '5fcf92').replace('#', '')
    if (!/^[0-9a-f]{6}$/i.test(color)) throw new Error('color must be a 6-digit hex value')
    const effect = typeof args.effect === 'string' && args.effect in EFFECTS ? EFFECTS[args.effect as keyof typeof EFFECTS] : undefined
    const { w } = await $fetch<{ w: number }>(`${useRuntimeConfig().ledApi}/preview`, { query: { text } })
    await api('command/send_text', { text, color, animation: effect ?? (w > 64 ? 1 : 0) })
    return `Showing "${text}" on the panel.`
  }
  if (name === 'show_stars') {
    if (args.repo !== undefined) {
      if (typeof args.repo !== 'string' || !REPO_PATTERN.test(args.repo)) throw new Error('repo must look like owner/name')
      const r = await pushStars({ repo: args.repo })
      await saveStars({ repo: r.repo, color: r.color })
    }
    const r = await api('stars', {})
    return `Showing ${r.stars} stars for ${r.repo}.`
  }
  if (name === 'panel_status') return JSON.stringify(await api('health'))
  throw new Error(`Unknown tool: ${name}`)
}

export default defineEventHandler(async (event) => {
  if (event.method !== 'POST') {
    setResponseHeader(event, 'Allow', 'POST')
    throw createError({ statusCode: 405, statusMessage: 'Method Not Allowed' })
  }
  const req = await readBody<RpcRequest>(event)
  const reply = (result: unknown) => ({ jsonrpc: '2.0', id: req.id ?? null, result })
  const fail = (code: number, message: string) => ({ jsonrpc: '2.0', id: req.id ?? null, error: { code, message } })

  // notifications (no id) get no body
  if (req?.id === undefined) {
    setResponseStatus(event, 202)
    return ''
  }

  switch (req.method) {
    case 'initialize':
      return reply({
        protocolVersion: req.params?.protocolVersion ?? '2025-06-18',
        capabilities: { tools: {} },
        serverInfo: { name: 'pi-led', version: '0.1.0' },
        instructions: 'Controls a 64×16 LED panel. Use show_text for short status messages, like when a task is done.',
      })
    case 'ping':
      return reply({})
    case 'tools/list':
      return reply({ tools: TOOLS })
    case 'tools/call':
      try {
        const text = await callTool(req.params?.name, req.params?.arguments ?? {})
        return reply({ content: [{ type: 'text', text }] })
      } catch (e) {
        const message = (e as { data?: { error?: string } }).data?.error ?? (e as Error).message
        return reply({ content: [{ type: 'text', text: `Couldn't update the panel: ${message}` }], isError: true })
      }
    default:
      return fail(-32601, `Method not found: ${req.method}`)
  }
})
