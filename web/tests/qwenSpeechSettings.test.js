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

test('Qwen3-ASR 模型會隨 STT 引擎顯示', () => {
  assert.match(settings, /'qwen3-asr': \['Qwen\/Qwen3-ASR-0\.6B'/)
  assert.match(panel, /v-for="model in sttModelOptions"/)
})

test('Qwen3-TTS 顯示模型、聲線、指令及克隆參考欄位', () => {
  assert.match(panel, /ttsDraft\.type === 'qwen3-tts'/)
  assert.match(panel, /ttsDraft\.speaker/)
  assert.match(panel, /ttsDraft\.instruct/)
  assert.match(panel, /qwenTtsKind === 'base'/)
})
