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
const app = readFileSync(
  new URL('../src/App.vue', import.meta.url),
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

test('設定面板提供可存取且有範圍限制的約略回覆字數欄位', () => {
  assert.match(panel, /for="llm-response-max-chars"/)
  assert.match(panel, /id="llm-response-max-chars"[\s\S]*type="number"/)
  assert.match(panel, /min="20"/)
  assert.match(panel, /max="2000"/)
  assert.match(panel, /aria-describedby="llm-response-max-chars-hint llm-response-max-chars-meta"/)
})

test('設定面板可調整嘴型銳化、貼回插值與 MuseTalk 製作參數', () => {
  assert.match(panel, /for="mouth-sharpen"/)
  assert.match(panel, /id="mouth-sharpen"[\s\S]*type="range"/)
  assert.match(panel, /for="paste-interpolation"/)
  assert.match(panel, /for="bbox-shift"/)
  assert.match(panel, /for="extra-margin"/)
  assert.match(panel, /settings\.quality\.rebuildHint/)
  assert.match(settings, /\/api\/avatar\/quality/)
  assert.match(settings, /form\.append\('quality'/)
})

test('從 Edge 切到本機 TTS 時會清掉聲線名稱並要求音訊路徑', () => {
  assert.match(settings, /EDGE_VOICE_ID/)
  assert.match(settings, /previous === 'edgetts'/)
  assert.match(panel, /settings\.speech\.referencePathDesc/)
  assert.match(panel, /settings\.speech\.referencePathPlaceholder/)
})

test('套用 LLM 設定時會送出並同步回覆字數', () => {
  assert.match(settings, /response_max_chars:\s*Number\(responseMaxChars\)/)
  assert.match(settings, /runtime\.llm\.response_max_chars\s*=\s*Number/)
  assert.match(settings, /value < 20 \|\| value > 2000/)
})

test('設定面板可選擇舊有或串流回覆模式並持久化', () => {
  assert.match(panel, /for="llm-reply-mode"/)
  assert.match(panel, /id="llm-reply-mode"[\s\S]*value="legacy"[\s\S]*value="streaming"/)
  assert.match(settings, /reply_mode:\s*replyMode/)
  assert.match(settings, /runtime\.llm\.reply_mode\s*=\s*data\.reply_mode/)
})

test('文字回覆由事件模式呈現而非 HTTP 完整 response', () => {
  assert.match(app, /assistant_response/)
  assert.match(app, /assistant_fragment/)
  assert.match(app, /assistant_response_delta/)
  assert.match(app, /streamingPreview/)
  assert.doesNotMatch(app, /if \(data\.response \|\| data\.text\) \{[\s\S]*addMessage\(data\.response/)
})

test('文字 delta 拒絕重複、逆序與完成後的舊事件', () => {
  assert.match(app, /assistantStreamState = new Map\(\)/)
  assert.match(app, /sequence <= stream\.lastSequence \|\| stream\.done/)
  assert.match(app, /stream\.done = true/)
})
