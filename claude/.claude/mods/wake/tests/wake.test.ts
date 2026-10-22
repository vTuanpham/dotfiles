import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

type Node = string | { type: string; props?: Record<string, unknown>; children?: Node[] }

/** Every Text's words and Button's label, in order, one Box row per line. */
function flat(node: Node): string {
  const text = (n: Node): string =>
    typeof n === 'string' ? n : n.type === 'Button' ? `[${String(n.props?.label ?? '')}]` : (n.children ?? []).map(text).join('')
  const rows = (n: Node): string[] => {
    if (typeof n === 'string' || n.type === 'Text' || n.type === 'Button') return [text(n)]
    if (n.type === 'Raster') return ['<mochi>']
    const kids = n.children ?? []
    return n.props?.flexDirection === 'column' ? kids.flatMap(rows) : [kids.map(k => rows(k).join(' ')).join(' ')]
  }
  return rows(node).join('\n')
}

function engine(on: On) {
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  on('session.cwd', () => ({ value: '/proj' }))
  on('session.append', () => ({ uuid: 'x' }) as never)
  on('prompt.submit', (_$, e) => e as never)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['engine'] }) as never) // the engine's own drawing
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('tool.call', async (_$, e) => {
    if (e.tool === 'Bash' && e.command.includes('fail')) return { isError: true as const, result: 'Exit code 1' as never, text: 'Exit code 1' }
    return { result: {} as never, text: 'ok' }
  })
  return clock
}

type Engine = Parameters<Extract<Parameters<typeof test>[1], (...args: never[]) => unknown>>[0]

const mount = ($: Engine, component: 'AbovePrompt' | 'Spinner', isWorking = false) =>
  $.ui.mount({
    plugin: 'wake',
    surface: 'terminal',
    component,
    props:
      component === 'AbovePrompt'
        ? { hasSurvey: false, isWorking, maxRows: 16, bodyColumns: 100, scroll: { offset: 0, bodyRows: 16 } }
        : { word: 'Working', message: null, suffix: '', mode: 'tool-use' },
  } as never)

test('the plan rides in the spinner; the dock says what is happening now', async ($, on) => {
  engine(on)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({
    tool: 'TodoWrite',
    todos: [
      { content: 'Read the code', status: 'completed', activeForm: 'Reading the code' },
      { content: 'Migrate callers', status: 'in_progress', activeForm: 'Migrating callers' },
      { content: 'Run tests', status: 'pending', activeForm: 'Running tests' },
    ],
  } as never)
  const spinner = await mount($, 'Spinner')
  const line = flat((await spinner.drawn()) as Node)
  expect(line).toContain('Migrating callers')
  expect(line).toContain('2/3')
  await spinner.unmount()

  const dock = await mount($, 'AbovePrompt', true)
  const drawn = (await dock.drawn()) as Node
  const text = flat(drawn)
  expect(text).toContain('Planning') // what the main agent is doing now
  expect(text).toContain('turn 1')
  expect(text).toContain('plan')
  expect(text).not.toContain('away')
  await dock.unmount()
})

test('after ten idle minutes a recap waits above the prompt, from the log when no model answers', async ($, on) => {
  const clock = engine(on)
  await $.prompt.submit({ text: 'fix the parser' } as never)
  await $.turn.start({ text: 'fix the parser', turnId: 't1' })
  await $.tool.call({ tool: 'Edit', file_path: '/proj/src/parse.ts', old_string: 'a', new_string: 'a\nb' } as never)
  await $.tool.call({ tool: 'Bash', command: 'uv run pytest tests/test_parse.py' } as never)
  await $.turn.complete({ answer: 'Fixed the parser. All parse tests pass.', durationMs: 60_000, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  await clock.advance(10 * 60_000 + 1)

  const bar = await mount($, 'AbovePrompt')
  const tree = (await bar.drawn()) as Node
  const drawn = flat(tree)
  expect(drawn).toContain('+2') // the session's diff tally
  expect(drawn).toContain('−1')
  expect(drawn).toContain('while you were away')
  expect(drawn).toContain('from the log')
  expect(drawn).toContain('<mochi>')
  await bar.unmount()
})
