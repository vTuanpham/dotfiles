import type { EngineInterface } from 'claude-code'

export async function bridgePaths($: EngineInterface): Promise<{ jobs: string; archive: string } | undefined> {
  const configured = await $.env.get('AGENT_BRIDGE_HOME')
  const userHome = await $.env.get('HOME')
  const home = configured?.startsWith('~') && userHome ? `${userHome}${configured.slice(1)}` : configured || userHome
  if (!home) return undefined
  const base = configured ? home : `${home.replace(/\/+$/, '')}/.local/state/agent-bridge`
  const root = base.replace(/\/+$/, '') || '/'
  return { jobs: `${root}/jobs`, archive: `${root}/archive.jsonl` }
}

export async function bridgeRunnerAlive($: EngineInterface, pid: unknown): Promise<boolean> {
  if (typeof pid !== 'number' || !Number.isSafeInteger(pid) || pid < 1) return false
  const cmdline = await $.fs.read(`/proc/${pid}/cmdline`).catch(() => '')
  return cmdline.includes('agent-bridge')
}
