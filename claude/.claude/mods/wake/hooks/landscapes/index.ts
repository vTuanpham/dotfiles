import type { WakePreset } from '../../types'
import { beach } from './beach'
import { city } from './city'
import { countryside } from './countryside'
import { desert } from './desert'
import { forest } from './forest'
import { harbor } from './harbor'
import type { Landscape } from './kit'
import { mountains } from './mountains'
import { tundra } from './tundra'

export const LANDSCAPES: Record<WakePreset, Landscape> = { city, harbor, beach, mountains, countryside, forest, desert, tundra }
