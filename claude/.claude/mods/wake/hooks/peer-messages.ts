type PeerMessage = { messageId?: string }
type PeerJob = { id: string; owner: string; peers: PeerMessage[] }

/** Tracks observed message IDs per owned job so first-scan history never pulses. */
export class PeerMessageTracker {
  private scope = ''
  private readonly seen = new Map<string, Set<string>>()

  reset() {
    this.scope = ''
    this.seen.clear()
  }

  observe(scope: string, jobs: readonly PeerJob[]): Set<string> {
    if (scope !== this.scope) {
      this.scope = scope
      this.seen.clear()
    }

    const active = new Set<string>()
    const visible = new Map<string, Set<string>>()
    const fresh = new Set<string>()
    for (const job of jobs) {
      const key = JSON.stringify([job.owner, job.id])
      active.add(key)
      visible.set(key, new Set(job.peers.flatMap(peer => peer.messageId ? [peer.messageId] : [])))
      let previous = this.seen.get(key)
      const hasBaseline = previous !== undefined
      if (!previous) {
        previous = new Set()
        this.seen.set(key, previous)
      }
      for (const peer of job.peers) {
        const id = peer.messageId
        if (!id) continue
        if (hasBaseline && !previous.has(id)) fresh.add(JSON.stringify([job.owner, job.id, id]))
        previous.add(id)
      }
    }
    for (const key of this.seen.keys()) if (!active.has(key)) this.seen.delete(key)
    let size = [...this.seen.values()].reduce((sum, ids) => sum + ids.size, 0)
    for (const [key, ids] of this.seen) for (const id of ids) {
      if (size <= 1000) break
      if (visible.get(key)?.has(id)) continue
      ids.delete(id)
      size--
    }
    return fresh
  }
}
