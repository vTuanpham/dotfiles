import { expect, test } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'

import { ownedBy, ownersIn, scanCodex } from '../hooks/sources/codex'
import { bridgePaths, bridgeRunnerAlive } from '../hooks/sources/bridge'

const HOME = '/home/u'
const ROOT = `${HOME}/.local/state/agent-bridge/jobs`
const NOW = 10_000_000_000
const sec = (ms: number) => (ms / 1000).toFixed(3)
const ev = (o: Record<string, unknown>) => JSON.stringify({ at: '2026-10-15T10:00:00+00:00', level: 'info', ...o })

type Fake = { content: string; mtime: number; active?: boolean; alive?: boolean; title?: string; retired?: boolean }

/**
 * The test engine's `$` has no env, clock, fs or process nouns (they are not engine-raised events in a test),
 * so the module gets a stand-in with the four calls it makes: `find` lists the files, `tail` serves bytes.
 */
function world(files: Record<string, Fake>, bridgeHome?: string) {
  const calls: string[][] = []
  const acks: Record<string, unknown> = {}
  const enc = new TextEncoder()
  const $ = {
    env: { get: async (key: string) => key === 'AGENT_BRIDGE_HOME' ? bridgeHome : HOME },
    clock: { now: async () => NOW },
    process: {
      run: async (argv: readonly string[]) => {
        calls.push([...argv])
        const [cmd] = argv
        const out = (stdout: string) => ({ exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false })
        if (cmd === 'find') {
          const root = bridgeHome ? `${bridgeHome}/jobs` : ROOT
          return out(
            Object.entries(files)
              .map(([dir, f]) => `${sec(f.mtime)} ${enc.encode(f.content).length} 1:2 ${root}/${dir}/live.jsonl\n${sec(f.mtime)} 0 1:3 ${root}/${dir}/state.json\n`)
              .join(''),
          )
        }
        const dir = argv[3]!.slice(ROOT.length + 1, -'/live.jsonl'.length)
        const all = enc.encode(files[dir]!.content)
        const slice = argv[2]!.startsWith('+') ? all.slice(Number(argv[2]!.slice(1)) - 1) : all.slice(Math.max(0, all.length - Number(argv[2])))
        return out(new TextDecoder().decode(slice))
      },
    },
    fs: {
      read: async (path: string) => {
        if (path === '/proc/123/cmdline') return 'agent-bridge run'
        const root = bridgeHome ? `${bridgeHome}/jobs` : ROOT
        if (path.endsWith('/ack.json')) {
          const ack = acks[path.slice(root.length + 1, -'/ack.json'.length)]
          if (!ack) throw new Error('ENOENT')
          return JSON.stringify(ack)
        }
        const f = files[path.slice(root.length + 1, -'/state.json'.length)]
        if (!f) throw new Error('ENOENT')
        return JSON.stringify({ activeTurnId: f.active ? 't1' : null, runnerPid: f.alive || f.active ? 123 : undefined, backend: 'codex', model: 'gpt-6-luna', effort: 'high', cwd: '/repo', title: f.title, retiredAt: f.retired ? '2026-01-01T00:00:00+00:00' : undefined })
      },
    },
  } as unknown as EngineInterface
  return { $, calls, files, acks }
}

const tails = (calls: string[][]) => calls.filter(c => c[0] === 'tail').map(c => c[2])

test('retired jobs leave the crew until restored', async () => {
  const f: Fake = { content: ev({ kind: 'message', text: 'report' }) + '\n', mtime: NOW, retired: true }
  const { $ } = world({ 'pb/retired': f })
  const first = await scanCodex($, {})
  expect(first.jobs).toEqual([])
  f.retired = false
  const restored = await scanCodex($, first.cursor)
  expect(restored.jobs.map(j => j.name)).toEqual(['retired'])
})

test('first sight reads only the tail, nothing is new, last message is kept', async () => {
  const big = ev({ kind: 'message', text: 'old' }) + '\n' + 'x'.repeat(70_000) + '\n'
  const content = big + ev({ kind: 'message', level: 'urgent', text: 'URGENT: old' }) + '\n' + ev({ kind: 'turn_completed' }) + '\n'
  const { $, calls } = world({ 'pb/a': { content, mtime: NOW - 1000 } })
  const r = await scanCodex($, {})
  const job = r.jobs[0]!

  expect(tails(calls)).toEqual(['65536'])
  expect(job).toMatchObject({ owner: 'pb', name: 'a', title: 'a', model: 'gpt-6-luna', cwd: '/repo', running: false, completedNow: false, urgent: [] })
  expect(job.lastMessage).toBe('URGENT: old')
  expect(job.finishedAt).toBe(Date.parse('2026-10-15T10:00:00+00:00'))
  expect(r.cursor[`${ROOT}/pb/a/live.jsonl`]).toBe(new TextEncoder().encode(content).length)
})

test('AGENT_BRIDGE_HOME overrides the default jobs root', async () => {
  const root = '/state/bridge'
  const { $, calls } = world({ 'pb/a': { content: ev({ kind: 'message', text: 'x' }) + '\n', mtime: NOW - 1000 } }, root)
  await scanCodex($, {})
  expect(calls[0]![1]).toBe(`${root}/jobs`)
})

test('AGENT_BRIDGE_HOME expands a leading tilde', async () => {
  const $ = { env: { get: async (key: string) => key === 'AGENT_BRIDGE_HOME' ? '~/bridge' : HOME } } as unknown as EngineInterface
  expect(await bridgePaths($)).toMatchObject({ jobs: `${HOME}/bridge/jobs` })
})

test('runner liveness requires the agent-bridge command line', async () => {
  const { $ } = world({})
  expect(await bridgeRunnerAlive($, 123)).toBe(true)
  expect(await bridgeRunnerAlive($, 124)).toBe(false)
})

test('a live runner with no recent log is still discovered', async () => {
  const { $, calls } = world({ 'pb/quiet': { content: '', mtime: NOW - 8 * 3600_000, alive: true } })
  const r = await scanCodex($, {}, { recentMs: 1_000 })
  expect(r.jobs.map(j => [j.name, j.running])).toEqual([['quiet', true]])
  expect(calls.filter(c => c[0] === 'tail')).toEqual([])
})

test('later scans read only new bytes; unchanged size costs no read', async () => {
  const w = world({ 'pb/a': { content: ev({ kind: 'message', text: 'one' }) + '\n', mtime: NOW - 1000 } })
  const first = await scanCodex(w.$, {})
  w.calls.length = 0

  const same = await scanCodex(w.$, first.cursor)
  expect(tails(w.calls)).toEqual([])
  expect(same.jobs[0]!.lastMessage).toBe('one')

  w.files['pb/a']!.content += ev({ kind: 'message', text: 'two é' }) + '\n'
  const grown = await scanCodex(w.$, first.cursor)
  expect(tails(w.calls)).toEqual([`+${first.cursor[`${ROOT}/pb/a/live.jsonl`]! + 1}`])
  expect(grown.jobs[0]!.lastMessage).toBe('two é')
  expect(grown.cursor[`${ROOT}/pb/a/live.jsonl`]).toBe(new TextEncoder().encode(w.files['pb/a']!.content).length)
})

test('a half-written line waits for its newline; malformed lines are skipped', async () => {
  const head = ev({ kind: 'message', text: 'a' }) + '\n'
  const w = world({ 'pb/a': { content: head, mtime: NOW - 1000 } })
  const c0 = (await scanCodex(w.$, {})).cursor

  const line = ev({ kind: 'message', level: 'urgent', text: 'URGENT: half' })
  w.files['pb/a']!.content = head + 'not json\n' + line.slice(0, 20)
  const mid = await scanCodex(w.$, c0)
  expect(mid.jobs[0]!.urgent).toEqual([])
  expect(mid.cursor[`${ROOT}/pb/a/live.jsonl`]).toBe(head.length + 'not json\n'.length)

  w.files['pb/a']!.content = head + 'not json\n' + line + '\n'
  const done = await scanCodex(w.$, mid.cursor)
  expect(done.jobs[0]!.urgent.map(u => u.text)).toEqual(['URGENT: half'])
})

test('truncation starts over from byte 0', async () => {
  const w = world({ 'pb/a': { content: ev({ kind: 'message', text: 'long old content' }) + '\n', mtime: NOW - 1000 } })
  const c0 = (await scanCodex(w.$, {})).cursor
  w.files['pb/a']!.content = ev({ kind: 'error', level: 'urgent', text: 'boom' }) + '\n'
  w.calls.length = 0
  const r = await scanCodex(w.$, c0)

  expect(tails(w.calls)).toEqual(['+1'])
  expect(r.jobs[0]!.urgent.map(u => u.text)).toEqual(['boom'])
})

test('urgent events and completedNow are new-only; turn_completed is not urgent; text is clipped', async () => {
  const w = world({ 'pb/a': { content: ev({ kind: 'message', text: 'start' }) + '\n', mtime: NOW - 1000, active: true } })
  const c0 = (await scanCodex(w.$, {})).cursor
  w.files['pb/a']!.content +=
    [
      ev({ kind: 'message', level: 'urgent', text: 'URGENT: ' + 'y'.repeat(500) }),
      ev({ kind: 'command_end', level: 'info', exitCode: 1 }),
      ev({ kind: 'turn_completed', level: 'urgent', status: 'completed' }),
    ].join('\n') + '\n'
  const r = await scanCodex(w.$, c0)

  expect(r.jobs[0]!.completedNow).toBe(true)
  expect(r.jobs[0]!.urgent).toHaveLength(1)
  expect(r.jobs[0]!.urgent[0]!.text).toHaveLength(300)
  expect(r.jobs[0]!.lastMessage).toHaveLength(400)
  expect((await scanCodex(w.$, r.cursor)).jobs[0]).toMatchObject({ completedNow: false, urgent: [] })
})

test('running vs stale, ordering, and quiet jobs outside recentMs drop out', async () => {
  const line = ev({ kind: 'message', text: 'x' }) + '\n'
  const { $ } = world({
    'o/done': { content: line, mtime: NOW - 60_000 },
    'o/stale': { content: line, mtime: NOW - 40 * 60_000, active: true },
    'o/run': { content: line, mtime: NOW - 5_000, alive: true, title: 'Bridge worker' },
    'o/old': { content: line, mtime: NOW - 7 * 3600_000 },
  })
  const r = await scanCodex($, {})

  expect(r.jobs.map(j => [j.name, j.title, j.running, j.isStale])).toEqual([
    ['run', 'Bridge worker', true, false],
    ['stale', 'stale', true, true],
    ['done', 'done', false, false],
  ])
})

test('bridge completion acknowledgements survive reload and keep older done jobs visible until root reads them', async () => {
  const content = ev({ kind: 'turn_started' }) + '\n' + ev({ kind: 'turn_completed' }) + '\n'
  const w = world({ 'waiting/job': { content, mtime: NOW - 8 * 3600_000 } })
  const first = await scanCodex(w.$, {})
  expect(first.jobs[0]).toMatchObject({ awaitingRoot: true, running: false })
  const end = new TextEncoder().encode(content).length
  w.acks.waiting = { version: 1, jobs: { job: { log: '1:2', through: 0, seen: 0, completed: end } } }
  expect((await scanCodex(w.$, first.cursor)).jobs).toEqual([])
  w.acks.waiting = { version: 1, jobs: { job: { log: '1:99', through: 0, seen: 0, completed: end } } }
  expect((await scanCodex(w.$, first.cursor)).jobs[0]!.awaitingRoot).toBe(true)
})

test('explicit ack clears done state; malformed and out-of-bounds cursors keep it visible', async () => {
  const content = ev({ kind: 'turn_completed' }) + '\n'
  const w = world({ 'ack/job': { content, mtime: NOW } })
  const end = new TextEncoder().encode(content).length
  for (const ack of [null, { version: 2, jobs: {} }, { version: 1, jobs: { job: { log: '1:2', through: end + 1, completed: 0, seen: 0 } } }]) {
    w.acks.ack = ack
    expect((await scanCodex(w.$, {})).jobs[0]!.awaitingRoot).toBe(true)
  }
  w.acks.ack = { version: 1, jobs: { job: { log: '1:2', through: end, completed: 0, seen: end } } }
  expect((await scanCodex(w.$, {})).jobs[0]!.awaitingRoot).toBe(false)
})

test('turn start stays separate from activity; 15 minute silence stalls but root_wait does not', async () => {
  const startedAt = new Date(NOW - 16 * 60_000).toISOString()
  const content = ev({ kind: 'turn_started', at: startedAt }) + '\n' + ev({ kind: 'command_end' }) + '\n'
  const w = world({
    'timing/busy': { content, mtime: NOW - 8_000, alive: true },
    'timing/stalled': { content, mtime: NOW - 15 * 60_000, alive: true },
    'timing/wait': { content: content + ev({ kind: 'root_wait' }) + '\n', mtime: NOW - 20 * 60_000, alive: true },
    'timing/noticed': { content: content + ev({ kind: 'stalled', at: new Date(NOW).toISOString(), quietSeconds: 901 }) + '\n', mtime: NOW, alive: true },
  })
  const jobs = (await scanCodex(w.$, {})).jobs
  expect(jobs.find(j => j.name === 'busy')).toMatchObject({ startedAt: NOW - 16 * 60_000, lastEventAt: NOW - 8_000, isStale: false })
  expect(jobs.find(j => j.name === 'stalled')!.isStale).toBe(true)
  expect(jobs.find(j => j.name === 'wait')!.isStale).toBe(false)
  expect(jobs.find(j => j.name === 'noticed')).toMatchObject({ isStale: true, lastEventAt: NOW - 901_000 })
})

test('ownersIn reads only the job owners a command names', () => {
  expect(ownersIn('agent-bridge watch pb --until-event --timeout 1800')).toEqual(['pb'])
  expect(ownersIn('agent-bridge result pb/job; agent-bridge ack pb other')).toEqual(['pb', 'other'])
  expect(ownersIn('agent-bridge start pb-brain/luna-a --backend codex --cwd /r --detach')).toEqual(['pb-brain'])
  expect(ownersIn('mkdir -p ~/.local/state/agent-bridge/jobs/pb/a && agent-bridge steer pb/a "hi"')).toEqual(['pb'])
  expect(ownersIn('timeout 1500 agent-bridge watch poly-audit pb --until-event')).toEqual(['poly-audit', 'pb'])
  expect(ownersIn('rm -rf ~/.local/state/agent-bridge/jobs/.trash/x; tail ~/.local/state/agent-bridge/archive.jsonl')).toEqual([])
  expect(ownersIn('agent-bridge start <owner>/<name> --model x; agent-bridge start ~/abs/job; ls /tmp')).toEqual([])
  expect(ownersIn('agent-bridge start --backend codex --cwd /r pb/worker')).toEqual(['pb'])
  expect(ownersIn('agent-bridge watch --until-event --stall-min 15 pb poly')).toEqual(['pb', 'poly'])
  expect(ownedBy({ owner: 'pb/brain' }, ['pb'])).toBe(true)
  expect(ownedBy({ owner: 'pbx' }, ['pb'])).toBe(false)
})
