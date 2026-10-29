import { expect, test } from 'claude-code/testing'
import { LOGOS, modelLogo } from '../hooks/logos'

test('logos are PNG bytes for each supported harness', () => {
  for (const backend of ['codex', 'agy', 'claude', 'opencode'])
    expect(LOGOS[backend]?.startsWith('iVBORw0KGgo')).toBe(true)
})

test('model marks follow known model IDs rather than the harness', () => {
  expect(modelLogo('claude-sonnet-5-5')).toBe('claude')
  expect(modelLogo('openrouter/anthropic/claude-sonnet-5-5')).toBe('claude')
  expect(modelLogo('gpt-6.1-terra')).toBe('codex')
  expect(modelLogo('openrouter/openai/gpt-6-sol')).toBe('codex')
  expect(modelLogo('openrouter/other/gpt-6-sol')).toBeUndefined()
  expect(modelLogo('openai/claude-sonnet-5-5')).toBeUndefined()
  expect(modelLogo('anthropic/gpt-6-sol')).toBeUndefined()
  expect(modelLogo('openrouter/gpt-6-sol')).toBeUndefined()
  expect(modelLogo('/gpt-6-sol')).toBeUndefined()
  expect(modelLogo('sonnet')).toBeUndefined()
  expect(modelLogo('gemini-3-flash')).toBeUndefined()
  expect(modelLogo('unknown-model')).toBeUndefined()
  expect(modelLogo(undefined)).toBeUndefined()
})
