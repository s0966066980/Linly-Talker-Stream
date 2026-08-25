import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)
const settings = readFileSync(
  new URL('../src/composables/useRuntimeSettings.js', import.meta.url),
  'utf8'
)

test('設定面板提供有標籤與說明的預設 Prompt 欄位', () => {
  assert.match(panel, /for="llm-system-prompt"/)
  assert.match(panel, /<textarea[\s\S]*id="llm-system-prompt"/)
  assert.match(panel, /aria-describedby="llm-system-prompt-hint llm-system-prompt-count"/)
  assert.match(panel, /maxlength="8000"/)
})

test('套用 LLM 設定時會送出並同步預設 Prompt', () => {
  assert.match(settings, /system_prompt:\s*systemPrompt/)
  assert.match(settings, /runtime\.llm\.system_prompt\s*=\s*data\.system_prompt/)
})
