import type { ClientModule } from 'claude-code'

// Pointer capture only: drawing over the Raster invalidates terminal compositing.
const ScenePointer: ClientModule = (_props, surface) => {
  surface.onPointer(event => surface.post({ type: event.type, x: event.x, y: event.y }))
  return surface.elements.Box({})
}

export default ScenePointer
