import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderElement, Timer } from 'claude-code'

import type { WakeAgent, WakeCall, WakeChip, WakeQuota, WakeDigest, WakeMood, WakeNeed, WakeNow, WakePreset, WakePulse, WakePulseKind, WakeRecap, WakeRecapLine, WakeStep, WakeSurroundings, WakeTally } from '../types'
import { ownedBy, ownersIn, scanCodex, type CodexCursor } from './sources/codex'
import { makerOf, modelTier, scanQuotas } from './sources/accounts'
import { extractCalls, writeRecap } from './sources/recap'
import { scanTidy, tidyRequest } from './sources/tidy'
import { type BandState, sceneInput } from './band'
import { KIND_COLOR } from './landscapes/kit'
import { EFFECT_FRAMES, SCENE_ROWS, type SceneEffect, eventName, sceneCells, sceneFrame } from './scene'
import { PRESETS, nextRain, skyOf } from './sources/weather'
import { lookAround, namePlace, pinPreset } from './surroundings'
import { COLOR, readable, clock, commandHead, fitSlots, hash, isAnswerText, isTestCommand, lines, patchCounts, shortPath, span } from './util'
import { crewRows, quotaLines } from './crew-row'

// Wake lives in the flow of the chat: a living diorama above the prompt (the session as a
// town in the real weather where you are, Mochi on the street), a line of words and the
// crew at work (subagents, bridge jobs) under it, then whatever needs you; the plan in the
// spinner; cards in the transcript; chips under the answer that made a judgment call.
// It observes; it never blocks.

const AWAY_MS = 10 * 60_000
const ASK_AWAY_MS = 3 * 60_000
const CODEX_POLL_MS = 15_000
const QUOTA_POLL_MS = 60_000 // codex-auth and agy's quota.json are local caches; agy /usage refreshes every AGY_REFRESH polls
const AGY_REFRESH = 30
const ANIMATE_MS = 400
const SCENE_MS = 50 // the diorama paints 20 a second: half steps of its frame, which motion paces at 10 a second
const AGENTS_MS = 2_000
const SURROUNDINGS_MS = 10 * 60_000
const NOTICE = '◈ wake'

/** Nerd Font glyphs (escaped: editors drop private-use characters); the dingbat marks are missing from many fonts. */
const G = {
  done: '\u{f00c}',
  fail: '\u{f00d}',
  needs: '\u{f071}',
  agent: '\u{f021}',
  call: '\u{f0e3}',
  idle: '\u{f10c}',
  sleep: '\u{f186}',
  stale: '\u{f252}',
  wake: '\u{f0eb}',
  umbrella: '\u{e34b}',
  pin: '\u{f041}',
}

const MARK: Record<WakeRecapLine['mark'], { glyph: string; color: string }> = {
  done: { glyph: G.done, color: COLOR.green },
  decision: { glyph: G.call, color: COLOR.mauve },
  needs: { glyph: G.needs, color: COLOR.yellow },
  agent: { glyph: G.agent, color: COLOR.teal },
  fail: { glyph: G.fail, color: COLOR.red },
}

/** Nerd Font circle slices (the status line's spinner); the geometric quarter circles are missing from many fonts. */
const spinner = (frame: number) => String.fromCodePoint(0xf0a9e + (frame % 8))
/** What a bridge job is called to the person: its title, else (old jobs) its name. */
const titleOf = (job: { name: string; title?: string }) => job.title ?? job.name

/** The original three-pip row, with a fourth pip for class 4. */
const pips = (tier: 1 | 2 | 3 | 4) => '▰'.repeat(tier) + '▱'.repeat(Math.max(0, 3 - tier))
const diamond = (frame: number) => '◆◇◈◇◆◇◈◇'[frame % 8]!

const hex = (rgb: number) => '#' + rgb.toString(16).padStart(6, '0')

const PRESET_LABEL: Record<WakePreset, string> = {
  city: 'City',
  harbor: 'Harbor',
  beach: 'Beach',
  mountains: 'Mountains',
  countryside: 'Countryside',
  forest: 'Forest',
  desert: 'Desert',
  tundra: 'Tundra',
}

const freshDigest = (awaySince: number, prompt?: string): WakeDigest => ({
  awaySince, prompt, answers: [], files: [], failures: [], tests: [], agents: [], codex: [], needs: [],
})

const mood = atom({ plugin: 'wake', key: 'mood' } as const, 'idle' as WakeMood)
const plan = atom({ plugin: 'wake', key: 'plan' } as const, [] as WakeStep[])
const needs = atom({ plugin: 'wake', key: 'needs' } as const, [] as WakeNeed[])
const calls = atom({ plugin: 'wake', key: 'calls' } as const, [] as WakeCall[])
const chips = atom({ plugin: 'wake', key: 'chips' } as const, [] as WakeChip[])
const owners = atom({ plugin: 'wake', key: 'owners' } as const, [] as string[])
const quotas = atom({ plugin: 'wake', key: 'quotas' } as const, [] as WakeQuota[])
const recap = atom({ plugin: 'wake', key: 'recap' } as const, null as WakeRecap | null)
const digest = atom({ plugin: 'wake', key: 'digest' } as const, freshDigest(0))
const turnStartedAt = atom({ plugin: 'wake', key: 'turnStartedAt' } as const, null as number | null)
const lastActivity = atom({ plugin: 'wake', key: 'lastActivity' } as const, 0)
const tick = atom({ plugin: 'wake', key: 'tick' } as const, 0)
const doing = atom({ plugin: 'wake', key: 'now' } as const, null as WakeNow | null)
const pulse = atom({ plugin: 'wake', key: 'pulse' } as const, [] as WakePulse[])
const tally = atom({ plugin: 'wake', key: 'tally' } as const, { turns: 0, added: 0, removed: 0, files: [], lastTurnMs: 0 } as WakeTally)
const subagents = atom({ plugin: 'wake', key: 'subagents' } as const, [] as WakeAgent[])
const agentModels = atom({ plugin: 'wake', key: 'agentModels' } as const, {} as Record<string, string>) // subagent id -> the model its spawn resolved to
const parentModel = atom({ plugin: 'wake', key: 'parentModel' } as const, '')
const surroundings = atom({ plugin: 'wake', key: 'surroundings' } as const, null as WakeSurroundings | null)

/** Bookkeeping must never break a tool call or a turn. */
async function safely(work: () => unknown): Promise<void> {
  try {
    await work()
  } catch {
    // observation only
  }
}

// Module state resets on a hot reload; the timers are restarted where they are needed.
let animation: Timer | null = null
let codexPoll: Timer | null = null
let quotaPoll: Timer | null = null
let quotaTicks = 0
let awayTimer: Timer | null = null
let cursor: CodexCursor = {}
let turnFailed = false
let turnTestsOk = false
const taskIds = new Map<string, string>() // tool_use_id of a TaskCreate -> its subject, until the id is known
let frameNo = 0
let effect: { kind: SceneEffect['kind']; start: number } | null = null
let tour: { start: number } | null = null // /wake tour: every landscape in turn, a whole day in each
const TOUR_FRAMES = 120 // 12 s a landscape

/** The landscape and hour the tour shows at a frame, or null when no tour plays. */
function tourAt(frame: number): { preset: WakePreset; hour: number; index: number } | null {
  if (!tour) return null
  const t = frame - tour.start
  const index = Math.floor(t / TOUR_FRAMES)
  if (index >= PRESETS.length) return null
  return { preset: PRESETS[index]!, hour: (4 + ((t % TOUR_FRAMES) / TOUR_FRAMES) * 24) % 24, index }
}

/** The scene input with the tour's landscape and hour laid over, while a tour plays. */
function toured<T extends { preset: WakePreset; hour: number }>(input: T): T {
  const at = tourAt(frameNo)
  return at ? { ...input, preset: at.preset, hour: at.hour } : input
}
let band: { id: string; width: number } | null = null // where the scene is mounted, for blits
let sceneLoop: Timer | null = null
let agentLoop: Timer | null = null
let surroundLoop: Timer | null = null

/** Plays a session effect in the scene: fireworks, a storm, a shooting star. */
const play = (kind: SceneEffect['kind']) => {
  effect = { kind, start: frameNo }
}

/** One frame of the diorama, blitted into the mounted Raster without a redraw. */
async function paint($: EngineInterface) {
  frameNo += 0.5
  if (!band) return
  const age = effect ? frameNo - effect.start : 0
  if (effect && age >= EFFECT_FRAMES[effect.kind]) effect = null
  if (tour && !tourAt(frameNo)) tour = null
  if (tour && (frameNo - tour.start) % TOUR_FRAMES === 0) await update($, tick, n => n + 1) // redraw the words for the next landscape
  const input = toured(sceneInput(await bandState($), band.width, frameNo, effect ? { kind: effect.kind, age } : null, await $.clock.now()))
  const done = await $.ui.blit({ requestId: band.id, key: 'scene', columns: band.width, rows: SCENE_ROWS, cells: sceneCells(input) })
  if (done.deny) band = null // unmounted or resized: the next render mounts it again
}

/** What the scene reads from the session. */
async function bandState($: EngineInterface): Promise<BandState> {
  const crew = await read($, subagents)
  const parent = await read($, parentModel)
  return {
    here: await read($, surroundings),
    tally: await read($, tally),
    turnStartedAt: await read($, turnStartedAt),
    pulse: await read($, pulse),
    plan: await read($, plan),
    mood: await read($, mood),
    chips: await read($, chips),
    subagents: crew.map(a => ({ id: a.id, tier: modelTier('claude', a.model || parent) })),
  }
}

/** Looks around (place, landscape, weather) and keeps what it finds. */
async function refreshSurroundings($: EngineInterface, force = false) {
  const found = await lookAround($, force)
  if (found) await update($, surroundings, () => found)
}

/** The running Claude Code subagents, written only when the list changes. */
async function pollAgents($: EngineInterface) {
  const live = (await $.agent.list()).filter(agent => agent.status === 'running' || agent.status === 'pending' || agent.status === 'waiting')
  const prior = await read($, subagents)
  const now = await $.clock.now()
  const models = await read($, agentModels)
  const next = live.map(agent => ({ id: agent.id, type: agent.type, description: agent.description, name: agent.name, since: prior.find(p => p.id === agent.id)?.since ?? now, model: models[agent.id] }))
  if (JSON.stringify(next) !== JSON.stringify(prior)) await update($, subagents, () => next)
}

function watchScene($: EngineInterface) {
  sceneLoop ??= $.clock.every(SCENE_MS, () => void safely(() => paint($)))
  agentLoop ??= $.clock.every(AGENTS_MS, () => void safely(() => pollAgents($)))
  if (!surroundLoop) {
    surroundLoop = $.clock.every(SURROUNDINGS_MS, () => void safely(() => refreshSurroundings($)))
    void safely(() => refreshSurroundings($))
  }
}

function animate($: EngineInterface, on: boolean) {
  if (on) animation ??= $.clock.every(ANIMATE_MS, () => void update($, tick, n => n + 1).catch(() => {}))
  else {
    animation?.cancel()
    animation = null
  }
}

function pollCodex($: EngineInterface) {
  codexPoll ??= $.clock.every(CODEX_POLL_MS, () => void safely(() => codexTick($)))
  if (!quotaPoll) {
    const tick = () =>
      safely(async () => {
        const found = await scanQuotas($, { refreshAgy: quotaTicks++ % AGY_REFRESH === 0 })
        // an account that timed out this read keeps its last numbers rather than dropping off the line
        await update($, quotas, previous =>
          found.map(q => (q.parts.length > 0 || q.status !== undefined ? q : (previous ?? []).find(p => p.cli === q.cli && p.account === q.account) ?? q)),
        )
      })
    void tick()
    quotaPoll = $.clock.every(QUOTA_POLL_MS, () => void tick())
  }
}

async function isAway($: EngineInterface, threshold: number) {
  return (await $.clock.now()) - (await read($, lastActivity)) >= threshold
}

/** A card in the transcript: a notice the model never reads, drawn richly by the InfoNotice hook. */
function card($: EngineInterface, header: string, body: string[]) {
  return $.session.append({ message: { type: 'system', content: [{ type: 'text', text: [`${NOTICE} · ${header}`, ...body].join('\n') }] } })
}

const base = (file: unknown) => String(file ?? '').split('/').pop() || '…'

/** A tool call in words a person would say, and its kind for the ribbon. */
function activity(e: { tool: string } & Record<string, unknown>): { label: string; kind: WakePulseKind } {
  switch (e.tool) {
    case 'Bash': {
      const command = String(e.command ?? '')
      return isTestCommand(command) ? { label: `Testing · ${commandHead(command)}`, kind: 'test' } : { label: `Running ${commandHead(command)}`, kind: 'run' }
    }
    case 'Edit':
    case 'MultiEdit':
    case 'Write':
    case 'NotebookEdit':
      return { label: `Editing ${base(e.file_path ?? e.notebook_path)}`, kind: 'edit' }
    case 'Read':
      return { label: `Reading ${base(e.file_path)}`, kind: 'read' }
    case 'Grep':
    case 'Glob':
      return { label: `Searching ${String(e.pattern ?? '')}`, kind: 'search' }
    case 'Agent':
    case 'Task':
      return { label: `Agent · ${String(e.description ?? e.subagent_type ?? '')}`, kind: 'agent' }
    case 'WebFetch':
    case 'WebSearch':
      return { label: `Browsing ${String(e.query ?? e.url ?? '')}`, kind: 'web' }
    case 'TodoWrite':
    case 'TaskCreate':
    case 'TaskUpdate':
      return { label: 'Planning', kind: 'plan' }
    default:
      return { label: e.tool.replace(/^mcp__([^_]+)__/, '$1 · '), kind: 'run' }
  }
}

const recapBody = (lines_: WakeRecapLine[]) => lines_.map(line => `${MARK[line.mark].glyph} ${line.text}`)

async function codexTick($: EngineInterface) {
  const scan = await scanCodex($, cursor)
  cursor = scan.cursor
  const mine = await read($, owners)
  scan.jobs = scan.jobs.filter(job => ownedBy(job, mine)) // other sessions share the root
  const now = await $.clock.now()
  await update($, chips, () =>
    scan.jobs
      .filter(job => job.running || job.awaitingRoot || (job.finishedAt ?? 0) > now - 30 * 60_000)
      .map(job => ({ name: job.name, title: titleOf(job), backend: job.backend, account: job.account, model: job.model, effort: job.effort, running: job.running, isStale: job.isStale, since: job.finishedAt ?? job.lastEventAt, startedAt: job.startedAt, lastEventAt: job.eventKnown ? job.lastEventAt : undefined, awaitingRoot: job.awaitingRoot, waitingForRoot: job.waitingForRoot, maker: makerOf(job.model), state: job.state, reason: job.reason, memoryBytes: job.memoryBytes, memoryCap: job.memoryCap, peers: job.peers })),
  )
  const away = await isAway($, ASK_AWAY_MS)
  for (const job of scan.jobs) {
    for (const ask of job.urgent) {
      const text = ask.text.replace(/^URGENT:\s*/, '')
      await update($, needs, list => [...list, { id: hash(job.dir + ask.at), kind: 'codex-ask' as const, job: job.name, title: titleOf(job), text, at: ask.at }].slice(-6))
      await card($, `${job.backend} ${titleOf(job)} asks`, [`${G.needs} ${text}`])
      await update($, digest, d => ({ ...d, codex: [...d.codex, { name: titleOf(job), model: job.model, urgent: text }] }))
      await update($, mood, () => 'alert')
      if (away) await $.ui.notify(`${job.backend} ${titleOf(job)}: ${text.slice(0, 120)}`, { title: 'Wake · needs you' })
    }
    if (job.completedNow) {
      const summary = (job.lastMessage ?? '').split('\n')[0]!.slice(0, 160)
      // one done row per job: a later turn replaces it
      await update($, needs, list => [...list.filter(one => one.kind !== 'codex-done' || one.job !== job.name), { id: hash(job.dir + job.finishedAt), kind: 'codex-done' as const, job: job.name, title: titleOf(job), text: summary, at: now }].slice(-6))
      play('shoot')
      await card($, `${job.backend} ${titleOf(job)} finished · ${job.model} ${job.effort}`, [`${G.agent} ${summary || 'no final message'}`])
      await update($, digest, d => ({ ...d, codex: [...d.codex, { name: titleOf(job), model: job.model, summary }] }))
      if (away) await $.ui.notify(`${job.backend} ${titleOf(job)} finished`, { title: 'Wake' })
    }
  }
}

async function goAway($: EngineInterface, since: number) {
  if ((await read($, lastActivity)) !== since || (await read($, turnStartedAt)) !== null) return
  await update($, mood, () => 'sleep')
  const d = await read($, digest)
  if (d.answers.length === 0 && d.files.length === 0) return
  const open = (await read($, needs)).map(need => `${(need.title ?? need.job)}: ${need.text}`)
  const written = await writeRecap($, { ...d, needs: open })
  await update($, recap, () => ({ lines: written.lines, awaySince: since, source: written.source }))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await safely(async () => {
      await $.command.register({ name: 'wake', description: 'What Wake knows; /wake legend, tour, scene or place', argumentHint: '[legend|tour|scene <name>|place <city>]' })
      await $.tool.register({
        name: 'tidy_scan',
        description:
          'Read-only scan of retired agent-bridge jobs past their purge date ($AGENT_BRIDGE_HOME/jobs, default ~/.local/state/agent-bridge/jobs), with reclaimable sizes and dirty worktrees. Returns a purge request for the root; deletes nothing itself. Restorable jobs before their purge date are excluded.',
        inputSchema: { type: 'object', properties: { olderThanDays: { type: 'number', description: 'Also require this many idle days (default 0); never overrides the purge date' } } },
        isDeferred: true,
      })
      pollCodex($)
      watchScene($)
      await update($, lastActivity, () => Date.now())
    })
    return next(e)
  })

  // /clear, /resume and /branch reset $.state without a new session.start: look around again at once
  on('classic.SessionStart', { source: ['clear', 'resume', 'fork'] }, async ($, e, next) => {
    await safely(async () => {
      await update($, lastActivity, () => Date.now())
      await refreshSurroundings($)
    })
    return next(e)
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'wake' }, async ($, e) => {
    const [verb = '', ...rest] = e.args.trim().split(/\s+/)
    const arg = rest.join(' ')
    if (verb === 'legend') return { text: 'Crew: ◈ Codex · ✦ agy · ◆ Claude · ○ OpenCode; number is model class 1–4. ● running · ⌁ heavy queue · = paused · ↻ retrying · ? needs answer · ! stalled · ✓ done · ○ idle. Dots show effort; bars show event freshness and memory/cap. ↗/↙ peer direction, number is messages, · is older than 15 minutes. Quota bars show remaining per account/window; ? means unknown, ~ means stale or freshness unknown.' }
    if (verb === 'tour') {
      tour = { start: frameNo }
      return { text: `Touring ${PRESETS.length} landscapes, 12 s each, a whole day in each; your own scene comes back after.` }
    }
    if (verb === 'scene') {
      const text = await pinPreset($, await read($, surroundings), arg)
      await refreshSurroundings($)
      return { text }
    }
    if (verb === 'place') {
      if (!arg) return { text: 'Usage: /wake place <city> (or auto to follow your IP).' }
      const text = await namePlace($, arg)
      await refreshSurroundings($, true)
      return { text }
    }
    return { text: await summary($) }
  })

  // The registered tool's name is not among the built-in tool names the matcher type lists.
  on('tool.call', { tool: 'mcp__wake__tidy_scan' as 'Bash' }, async ($, e) => {
    const days = (e as { olderThanDays?: unknown }).olderThanDays
    const scan = await scanTidy($, typeof days === 'number' ? { olderThanDays: days } : {})
    const text = scan.jobs.length + scan.dirty.length === 0 ? 'Nothing to tidy.' : tidyRequest(scan)
    return { result: text as never, text }
  }).catch(() => ({ result: 'Tidy scan failed; nothing was changed.' as never, text: 'Tidy scan failed; nothing was changed.', isError: true as const }))

  on('prompt.submit', async ($, e, next) => {
    await safely(async () => {
      const now = await $.clock.now()
      const waiting = await read($, recap)
      if (waiting) {
        await card($, `while you were away · ${span(now - waiting.awaySince)}`, recapBody(waiting.lines))
        await update($, recap, () => null)
      }
      awayTimer?.cancel()
      await update($, needs, () => [])
      await update($, digest, () => freshDigest(now, String(e.text ?? '').slice(0, 600)))
      await update($, lastActivity, () => now)
      await update($, mood, () => 'work')
    })
    return next(e)
  }).catch(($, e, next) => next(e)) // observer: the prompt always goes through

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      await safely(async () => {
        turnFailed = false
        turnTestsOk = false
        const startedAt = await $.clock.now()
        await update($, turnStartedAt, () => startedAt)
        await update($, tally, t => ({ ...t, turns: t.turns + 1 }))
        await update($, doing, () => ({ label: 'Thinking', kind: 'plan' as const, at: startedAt }))
        await update($, mood, () => 'work')
        animate($, true)
      })
    }
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const isMain = e.agentId === undefined
    const act = activity(e as never)
    if (isMain) await safely(async () => update($, doing, () => ({ ...act, at: Date.now() })))
    // owners are learned when the command starts: a foreground `agent-bridge start` runs as long as its job
    const named = e.tool === 'Bash' ? ownersIn(e.command) : []
    if (named.length) await safely(async () => update($, owners, list => (named.every(o => list.includes(o)) ? list : [...new Set([...list, ...named])])))
    let ran: Awaited<ReturnType<typeof next>> | undefined
    try {
      ran = await next(e)
      return ran
    } finally {
      await safely(async () => {
        if (ran === undefined || ran.deny !== undefined) return
        const failed = ran.isError === true
        if (isMain) {
          const turn = (await read($, tally)).turns
          await update($, pulse, list => [...list, { kind: failed ? ('fail' as const) : act.kind, turn }].slice(-400))
        }
        if (e.tool === 'Bash') {
          const command = commandHead(e.command)
          if (isTestCommand(e.command)) {
            await update($, digest, d => ({ ...d, tests: [...d.tests, { command, ok: !failed }].slice(-20) }))
            if (isMain && !failed) turnTestsOk = true
          }
          if (failed) {
            const code = /Exit code (\d+)/.exec(ran.text ?? '')?.[1]
            await update($, digest, d => ({ ...d, failures: [...d.failures, { command, ...(code ? { code: Number(code) } : {}) }].slice(-10) }))
            if (isMain) turnFailed = true
          }
          return
        }
        if (failed) return
        if (isMain && e.tool === 'TodoWrite') {
          await update($, plan, () => e.todos.map((todo, i) => ({ id: String(i), text: todo.content, active: todo.activeForm, status: todo.status })))
          return
        }
        if (isMain && e.tool === 'TaskCreate') {
          const id = String((ran.result as { task?: { id?: unknown }; taskId?: unknown } | undefined)?.task?.id ?? (ran.result as { taskId?: unknown })?.taskId ?? e.tool_use_id)
          taskIds.set(id, e.subject)
          await update($, plan, list => [...list, { id, text: e.subject, active: e.activeForm ?? e.subject, status: 'pending' as const }])
          return
        }
        if (isMain && e.tool === 'TaskUpdate') {
          await update($, plan, list =>
            list
              .map(step => (step.id === e.taskId ? { ...step, text: e.subject ?? step.text, active: e.activeForm ?? step.active, status: e.status === 'deleted' ? step.status : (e.status ?? step.status) } : step))
              .filter(step => !(step.id === e.taskId && e.status === 'deleted')),
          )
          return
        }
        const file = 'file_path' in e && typeof e.file_path === 'string' ? e.file_path : undefined
        if (file === undefined || !/^(Edit|MultiEdit|Write|NotebookEdit)$/.test(String(e.tool))) return
        const counts =
          patchCounts(ran.result) ??
          (e.tool === 'Edit' ? { added: lines(e.new_string), removed: lines(e.old_string) } : { added: lines((e as { content?: unknown }).content), removed: 0 })
        const path = shortPath(file, await $.session.cwd(), await $.env.get('HOME'))
        await update($, digest, d => {
          const prior = d.files.find(f => f.path === path)
          const merged = prior ? { path, added: prior.added + counts.added, removed: prior.removed + counts.removed } : { path, ...counts }
          return { ...d, files: [merged, ...d.files.filter(f => f.path !== path)].slice(0, 40) }
        })
        if (isMain) {
          await update($, tally, t => ({
            ...t,
            added: t.added + counts.added,
            removed: t.removed + counts.removed,
            files: t.files.includes(path) ? t.files : [...t.files, path],
          }))
        }
      })
    }
  }).catch(($, e, next) => next(e)) // observer only: never refuse, never run twice

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      animate($, false)
      await safely(async () => {
        const now = await $.clock.now()
        const startedAt = await read($, turnStartedAt)
        await update($, tally, t => ({ ...t, lastTurnMs: startedAt === null ? t.lastTurnMs : now - startedAt }))
        await update($, turnStartedAt, () => null)
        await update($, digest, d => ({ ...d, answers: [...d.answers, e.answer.slice(-2500)].slice(-4) }))
        await update($, lastActivity, () => now)
        const open = (await read($, needs)).length > 0
        await update($, mood, () => (open ? 'alert' : turnTestsOk && !turnFailed ? 'happy' : turnFailed ? 'sad' : 'idle'))
        if (turnTestsOk && !turnFailed) play('fireworks')
        else if (turnFailed) play('storm')
        awayTimer?.cancel()
        awayTimer = $.clock.after(AWAY_MS, () => void safely(() => goAway($, now)))
        if (plan && (await read($, plan)).every(step => step.status === 'completed')) await update($, plan, () => [])
        const known = (await read($, calls)).map(({ id, text }) => ({ id, text }))
        const fresh = await extractCalls($, e.answer, known)
        // calls belong to the latest answer: a new answer replaces them, none included
        await update($, calls, () => fresh.map(call => ({ ...call, answer: e.answer })))
      })
    }
    return next(e)
  })

  // learn what each subagent runs on; $.agent.list() does not say
  on('agent.spawn', async ($, e, next) => {
    const out = await next(e)
    if (out.deny === undefined) {
      await safely(async () => {
        await update($, parentModel, () => e.parentModel)
        if (out.agentId) await update($, agentModels, m => ({ ...m, [out.agentId!]: e.model ?? e.parentModel }))
      })
    }
    return out
  }).catch(($, e, next) => next(e))

  on('classic.SubagentStop', async ($, e, next) => {
    await safely(() =>
      update($, digest, d => ({
        ...d,
        agents: [...d.agents, { name: e.agent_type, ok: true, summary: (e.last_assistant_message ?? '').split('\n')[0]!.slice(0, 160) }].slice(-10),
      })),
    )
    return next(e)
  }).catch(($, e, next) => next(e))

  on('classic.PermissionRequest', async ($, e, next) => {
    await safely(async () => {
      await update($, mood, () => 'alert')
      if (await isAway($, ASK_AWAY_MS)) await $.ui.notify(`Claude is waiting for your OK on ${e.tool_name}`, { title: 'Wake · needs you' })
    })
    return next(e)
  }).catch(($, e, next) => next(e))

  // ── the band above the prompt: the diorama, a line of words, what needs you ──
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    pollCodex($) // a hot reload dropped the timers
    watchScene($)
    const waiting = await read($, recap)
    const open = await read($, needs)
    const allCalls = await read($, calls)
    const jobs = await read($, chips)
    const accounts = await read($, quotas)
    const current = await read($, mood)
    const frame = await read($, tick)
    const act = await read($, doing)
    const total = await read($, tally)
    const started = await read($, turnStartedAt)
    const idleSince = await read($, lastActivity)
    const failures = (await read($, digest)).failures
    const here = await read($, surroundings)
    const crewAgents = await read($, subagents)
    const parentTier = modelTier('claude', await read($, parentModel))
    const latest = allCalls.at(-1)?.answer
    const fresh = allCalls.filter(call => call.answer === latest).slice(-3)

    const ui = $.ui.resolve(e)
    const { Box, Text, Button } = ui
    const Raster = 'Raster' in ui ? ui.Raster : undefined // terminal only
    const now = await $.clock.now()
    const working = e.props.isWorking || started !== null
    const width = e.props.bodyColumns
    const bridgeCount = jobs.filter(job => job.running || job.awaitingRoot).length
    const crewRowsNeeded = bridgeCount + Number(crewAgents.length > 0) + (bridgeCount ? quotaLines(accounts, Math.max(0, width - 2)).length : 0)
    const withScene = Raster !== undefined && e.props.maxRows >= SCENE_ROWS + 2 + crewRowsNeeded && width >= 40
    band = withScene ? { id: e.requestId, width } : null
    const input = toured(sceneInput(await bandState($), width, frameNo, effect ? { kind: effect.kind, age: frameNo - effect.start } : null, now))
    const frame0 = withScene ? sceneFrame(input) : null
    // the words sit on the scene's floor colour, their colours pushed for contrast against it
    const floor = frame0 ? hex(frame0.floor) : undefined
    const ink = floor ? readable(floor) : COLOR

    // the headline: what is happening now, or how the last turn went
    let headline: RenderElement
    let clockNote: string
    if (working) {
      headline = (
        <Text wrap="truncate-end">
          <Text color={ink.teal}>{spinner(frame)} </Text>
          <Text color={ink.text} weight="bold">{act?.label ?? 'Working'}</Text>
        </Text>
      )
      clockNote = `turn ${total.turns} · ${clock(now - (started ?? now))}`
    } else {
      const lastFail = failures.at(-1)
      const [glyph, color, words] =
        open.length > 0
          ? [G.needs, ink.yellow, `${open[0]!.job} needs you${open.length > 1 ? ` · +${open.length - 1}` : ''}`]
          : current === 'sleep'
            ? [G.sleep, ink.subtle, waiting ? 'napping · your recap is below' : 'napping']
            : current === 'sad' && lastFail
              ? [G.fail, ink.red, `${lastFail.command}${lastFail.code !== undefined ? ` · exit ${lastFail.code}` : ''}`]
              : total.turns === 0
                ? [G.idle, ink.lavender, 'ready when you are']
                : [current === 'happy' ? G.done : G.idle, current === 'happy' ? ink.green : ink.lavender, `last turn ${span(total.lastTurnMs)}${current === 'happy' ? ' · tests green' : ''}`]
      headline = (
        <Text wrap="truncate-end">
          <Text color={color}>{glyph} </Text>
          <Text color={ink.text}>{words}</Text>
        </Text>
      )
      clockNote = total.turns === 0 ? '' : `idle ${span(now - idleSince)}`
    }
    const touring = tourAt(frameNo)
    if (touring) {
      headline = (
        <Text wrap="truncate-end">
          <Text color={ink.mauve}>{G.pin} </Text>
          <Text color={ink.text} weight="bold">touring · {PRESET_LABEL[touring.preset]}</Text>
          <Text color={ink.subtle}> {touring.index + 1}/{PRESETS.length} · dawn to night</Text>
        </Text>
      )
      clockNote = ''
    }

    // the right side: the weather where you are, then the session and its bridge jobs
    const w = here?.weather
    const sky = w ? skyOf(w.code, w.isDay) : undefined
    const rain = w ? nextRain(w.hours) : undefined
    const running = jobs.filter(job => job.running || job.awaitingRoot)
    const weather = here ? (
      <Text>
        {sky && w ? <Text color={ink.yellow}>{String.fromCodePoint(sky.icon)} </Text> : <Text color={ink.subtle}>{G.pin} </Text>}
        {w ? <Text color={ink.text}>{Math.round(w.temp)}° </Text> : ''}
        <Text color={ink.subtext}>{here.place.name}</Text>
        {sky ? <Text color={ink.subtle}> {sky.label}</Text> : ''}
        {rain ? <Text color={ink.sky}> · {G.umbrella} {rain.pop}% {rain.time.slice(11, 16)}</Text> : ''}
        <Text color={ink.surface}> │ </Text>
      </Text>
    ) : (
      ''
    )
    const words = (
      <Box paddingX={1}>
        <Box flexGrow={1} flexShrink={1}>
          {headline}
        </Box>
        <Text color={ink.subtle}>{clockNote ? ` ${clockNote}` : ''}</Text>
        <Text color={ink.surface}> │ </Text>
        {weather}
        <Text color={ink.subtle}>{total.turns} turns </Text>
        <Text color={ink.green}>+{total.added}</Text> <Text color={ink.red}>−{total.removed}</Text>
      </Box>
    )

    // what needs the person, under the words; first the crew at work: subagents and bridge jobs
    const rows: RenderElement[] = []
    // Keep Claude's native subagent row intact; bridge jobs each get their own line.
    const agentText = (agent: WakeAgent) => `${agent.name ?? agent.description} ${pips(agent.model ? modelTier('claude', agent.model) : parentTier)} claude·${agent.type} · ${span(now - agent.since)}`
    const agentNeeds = crewAgents.map(agent => 2 + agentText(agent).length)
    const rowWidth = Math.max(0, width - 2) // extras has one cell of padding on either side
    const slots = fitSlots(agentNeeds, rowWidth - Math.max(0, crewAgents.length - 1) * 3)
    if (crewAgents.length > 0) {
      rows.push(
        <Box width={rowWidth} overflow="hidden">
          {crewAgents.map((agent, index) => (
            <Box flexShrink={0}>
              {index > 0 ? <Text color={ink.surface}> │ </Text> : ''}
              <Box width={slots[index]!} flexShrink={0} overflow="hidden"><Text wrap="truncate-end">
                <Text color={ink.pink}>{diamond(frame)} </Text>
                <Text color={ink.text}>{agent.name ?? agent.description}</Text>
                <Text color={ink.pink}> {pips(agent.model ? modelTier('claude', agent.model) : parentTier)}</Text>
                <Text color={ink.pink}> claude</Text>
                <Text color={ink.subtle}>·{agent.type} · {span(now - agent.since)}</Text>
              </Text></Box>
            </Box>
          ))}
        </Box>,
      )
    }
    const bridgeRows = crewRows(running, now, rowWidth)
    for (const [index, job] of running.entries()) {
      const row = bridgeRows[index]!
      const familyColor = job.backend === 'agy' ? ink.blue : job.backend === 'claude' ? ink.pink : job.backend === 'opencode' ? ink.green : ink.teal
      const stateColor = row.state === 'stalled' ? ink.red : row.state === 'blocked_on_question' ? ink.peach
        : row.state === 'paused' || row.state === 'waiting_for_heavy' ? ink.yellow
        : row.state === 'retrying' ? ink.mauve : row.state === 'done' || row.state === 'waiting_for_root' ? ink.green : ink.teal
      rows.push(<Box width={rowWidth} overflow="hidden"><Text wrap="truncate-end">
        <Text color={ink.text}>{row.title}</Text>
        {row.family ? <Text> <Text color={familyColor}>{row.family}</Text><Text color={stateColor}> {row.glyph}</Text></Text> : ''}
        <Text color={ink.subtle}>{row.detail}</Text>
      </Text></Box>)
    }
    if (running.length > 0 && accounts.length > 0) {
      const inUse = new Set(running.map(job => job.backend))
      const ordered = [...accounts.filter(q => inUse.has(q.cli)), ...accounts.filter(q => !inUse.has(q.cli))]
      for (const line of quotaLines(ordered, rowWidth)) rows.push(<Box width={rowWidth} overflow="hidden"><Text color={ink.subtle} wrap="truncate-end">{line}</Text></Box>)
    }
    let hotkey = 1
    const key = () => String(hotkey++)
    if (waiting) {
      rows.push(
        <Text color={ink.mauve} italic>
          while you were away · {span(now - waiting.awaySince)}
          {waiting.source === 'digest' ? <Text color={ink.subtle}> · from the log</Text> : ''}
        </Text>,
      )
      for (const line of waiting.lines) {
        rows.push(
          <Text wrap="truncate-end">
            <Text color={MARK[line.mark].color}>{MARK[line.mark].glyph} </Text>
            <Text color={ink.text}>{line.text}</Text>
          </Text>,
        )
      }
    }
    for (const need of open) {
      const isAsk = need.kind === 'codex-ask'
      rows.push(
        <Box>
          <Box flexGrow={1} flexShrink={1}>
            <Text wrap="truncate-end">
              <Text color={isAsk ? ink.yellow : ink.teal}>{isAsk ? G.needs : G.agent} </Text>
              <Text color={ink.subtext}>{need.title ?? need.job} </Text>
              <Text color={ink.text}>{need.text}</Text>
            </Text>
          </Box>
          <Button
            key={`do-${need.id}`}
            hotkey={key()}
            label={isAsk ? 'reply' : 'review'}
            onPress={async () => {
              await $.prompt.fill({ text: isAsk ? `Reply to bridge job ${need.job}: ` : `Review bridge job ${need.job}'s result and merge it if it holds up.`, mode: 'replace' })
              await update($, needs, list => list.filter(one => one.id !== need.id))
            }}
          />
          <Text> </Text>
          <Button key={`drop-${need.id}`} plain label="dismiss" onPress={() => update($, needs, list => list.filter(one => one.id !== need.id))} />
        </Box>,
      )
    }
    if (fresh.length > 0) {
      // the latest answer's judgment calls, folded into one row
      rows.push(
        <Box>
          <Box flexGrow={1} flexShrink={1}>
            <Text wrap="truncate-end">
              <Text color={ink.mauve}>{G.call} </Text>
              <Text color={ink.subtext}>{fresh.length === 1 ? 'call' : `${fresh.length} calls`} · </Text>
              {fresh.map((call, i) => (
                <Text color={ink.text}>
                  {i > 0 ? <Text color={ink.subtle}> · </Text> : ''}
                  {call.text}
                </Text>
              ))}
            </Text>
          </Box>
          <Button
            key="calls-push"
            hotkey={key()}
            label="push back"
            onPress={async () => {
              const text = fresh.length === 1 ? `Revisit your call "${fresh[0]!.text}": I'd rather ` : `Revisit your calls:\n${fresh.map((call, i) => `${i + 1}. ${call.text}`).join('\n')}\nI'd rather `
              await $.prompt.fill({ text, mode: 'replace' })
              await update($, calls, () => [])
            }}
          />
          <Text> </Text>
          <Button key="calls-fine" plain label="fine" onPress={() => update($, calls, () => [])} />
        </Box>,
      )
    }

    const room = Math.max(1, e.props.maxRows - (withScene ? SCENE_ROWS : 0) - 2)
    const visible = rows.slice(0, room)
    const extras = (
      <Box flexDirection="column" paddingX={1}>
        {visible}
        {rows.length > visible.length && <Text color={ink.subtle}>+{rows.length - visible.length} more · /wake</Text>}
      </Box>
    )
    if (!withScene || !Raster) {
      return (
        <Box flexDirection="column">
          {words}
          {extras}
        </Box>
      )
    }

    const playing = eventName(input)
    const swatch = (kind: WakePulseKind, label: string) => (
      <Text>
        <Text color={hex(KIND_COLOR[kind])}>■</Text>
        <Text color={ink.subtext}> {label} </Text>
      </Text>
    )
    // hover the scene for its legend
    const legend = (
      <Box position="absolute" top={0} right={1} display="none" hover={{ display: 'flex' }} flexDirection="column" backgroundColor="#11111b" paddingX={1}>
        <Text color={COLOR.text} weight="bold">
          {PRESET_LABEL[input.preset]}
          {here ? <Text color={COLOR.subtle}> · {here.place.name}{here.presetSource === 'guessed' ? ' · /wake scene <name> to change' : ''}</Text> : ''}
        </Text>
        <Text color={COLOR.subtext}>each building is a turn · each window a tool call · the busy one is this turn</Text>
        <Text>
          {swatch('read', 'read')}
          {swatch('search', 'search')}
          {swatch('edit', 'edit')}
          {swatch('run', 'run')}
          {swatch('test', 'test')}
          {swatch('agent', 'agent')}
          {swatch('web', 'web')}
          {swatch('fail', 'failed')}
        </Text>
        <Text color={COLOR.subtext}>lamps · plan steps done   crew · teal drones and boats: Codex, mauve sparks and comets: agy, pink birds: Claude, balloons: OpenCode (bigger: stronger model)</Text>
        <Text color={COLOR.subtext}>fireworks · tests passed   storm · a command failed   shooting star · a bridge job finished</Text>
        {playing ? <Text color={COLOR.subtle}>now: {playing}</Text> : <Text color={COLOR.subtle}>sky, sun, moon phase and weather are live where you are</Text>}
      </Box>
    )
    return (
      <Box flexDirection="column">
        <Box key="wake-scene">
          <Raster key="scene" columns={width} rows={SCENE_ROWS} cells={frame0!.cells} />
          {legend}
        </Box>
        <Box flexDirection="column" backgroundColor={floor}>
          {words}
          {extras}
        </Box>
      </Box>
    )
  })

  // ── the spinner carries the plan step and progress ──────────────────────
  on('ui.render', { component: 'Spinner' }, async ($, e, next) => {
    const steps = await read($, plan)
    const started = await read($, turnStartedAt)
    const frame = await read($, tick)
    const active = steps.find(step => step.status === 'in_progress')
    if (!active || started === null) return next(e)
    const { Text } = $.ui.resolve(e)
    const done = steps.filter(step => step.status === 'completed').length
    const width = 12
    const filled = Math.round((done / steps.length) * width)
    const spin = spinner(frame)
    return (
      <Text wrap="truncate-end">
        <Text color={COLOR.teal}>{spin} </Text>
        <Text color={COLOR.text} weight="bold">{active.active}</Text>
        <Text color={COLOR.subtle}>  {done + 1}/{steps.length} </Text>
        <Text color={COLOR.green}>{'━'.repeat(filled)}</Text>
        <Text color={COLOR.surface}>{'━'.repeat(width - filled)}</Text>
        <Text color={COLOR.subtle}>  {clock((await $.clock.now()) - started)}</Text>
      </Text>
    )
  })

  // ── Wake's own cards in the transcript ───────────────────────────────────
  on('ui.render', { component: 'InfoNotice' }, async ($, e, next) => {
    if (!e.props.text.startsWith(NOTICE)) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const [header, ...body] = e.props.text.split('\n')
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={COLOR.surface} paddingX={1}>
        <Text color={COLOR.mauve} weight="bold">
          {header!.replace(NOTICE, G.wake)}
        </Text>
        {body.map(line => {
          const mark = Object.values(MARK).find(m => line.startsWith(m.glyph))
          return (
            <Text wrap="wrap">
              <Text color={mark?.color ?? COLOR.subtle}>{line.slice(0, 1)}</Text>
              {line.slice(1)}
            </Text>
          )
        })}
      </Box>
    )
  })

  // ── judgment calls as chips under the answer that made them ─────────────
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const drawn = await next(e)
    const mine = (await read($, calls)).filter(call => isAnswerText(e.props.text, call.answer))
    if (mine.length === 0) return drawn
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {drawn}
        <Box marginTop={0}>
          <Text wrap="truncate-end">
            {mine.map(call => (
              <Text>
                <Text color={COLOR.mauve}>  {G.call} </Text>
                <Text color={COLOR.subtext}>{call.text}</Text>
              </Text>
            ))}
          </Text>
        </Box>
      </Box>
    )
  })
}

/** The /wake answer: everything Wake knows, as plain text in the chat. */
async function summary($: EngineInterface): Promise<string> {
  const steps = await read($, plan)
  const open = await read($, needs)
  const allCalls = await read($, calls)
  const jobs = await read($, chips)
  const waiting = await read($, recap)
  const out: string[] = []
  if (waiting) out.push('While you were away:', ...recapBody(waiting.lines).map(l => `  ${l}`))
  if (steps.length) out.push('Plan:', ...steps.map(s => `  ${s.status === 'completed' ? '✓' : s.status === 'in_progress' ? '◐' : '○'} ${s.text}`))
  if (open.length) out.push('Waiting on you:', ...open.map(n => `  ${n.kind === 'codex-ask' ? '▲' : '⟲'} ${n.job}: ${n.text}`))
  if (allCalls.length) out.push('Judgment calls:', ...allCalls.map(c => `  ◆ ${c.text}`))
  if (jobs.length) out.push('Jobs:', ...jobs.map(j => `  ${j.running ? '◐' : '✓'} ${j.title ?? j.name} · ${j.backend ?? 'codex'}·${j.account ?? ''} ${j.model} ${j.effort}`))
  return out.length ? out.join('\n') : 'Nothing to report: no plan, no open items, no bridge jobs.'
}
