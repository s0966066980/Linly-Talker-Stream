import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const consoleWebRTC = readFileSync(
  new URL('../src/composables/useWebRTC.js', import.meta.url),
  'utf8'
)
const stage = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const startup = readFileSync(
  new URL('../../scripts/start-all.sh', import.meta.url),
  'utf8'
)

test('控制台與舞台 offer 帶有不同 client role', () => {
  assert.match(consoleWebRTC, /client_role:\s*['"]console['"]/) // console offer
  assert.match(stage, /client_role:\s*['"]stage['"]/) // stage offer
})

test('啟動資訊分別顯示兩頁的 Local 與 Network 網址', () => {
  assert.match(startup, /控制台 Local:/)
  assert.match(startup, /控制台 Network:/)
  assert.match(startup, /數字人舞台 Local:/)
  assert.match(startup, /數字人舞台 Network:/)
})

test('整合啟動使用精簡前端輸出，避免重複顯示網址與配置', () => {
  const viteConfig = readFileSync(
    new URL('../vite.config.js', import.meta.url),
    'utf8'
  )
  assert.match(startup, /VITE_CONFIG_QUIET=1/)
  assert.match(startup, /npm --silent run dev -- --logLevel warn/)
  assert.match(viteConfig, /process\.env\.VITE_CONFIG_QUIET/)
})

test('舞台字幕只接受播放提交事件並取消舊淡出計時', () => {
  assert.doesNotMatch(stage, /ev\.type === 'assistant_text'/)
  assert.match(stage, /ev\.type === 'assistant_fragment'/)
  assert.match(
    stage,
    /function showReply\(text, turnId\)\{[\s\S]*?clearTimeout\(replyTimer\);[\s\S]*?replyRevision\+\+;/
  )
  assert.match(
    stage,
    /function fadeReply\(turnId=replyTurnId\)\{[\s\S]*?revision === replyRevision[\s\S]*?turnId === replyTurnId/
  )
  assert.match(
    stage,
    /if\(ev\.type === 'turn_cancelled'\)\{[\s\S]*?clearReply\(\);[\s\S]*?\}/
  )
})

test('控制台對話只從已播放片段累積助手文字', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(app, /event\.type === 'assistant_text'/)
  assert.match(app, /event\.type === 'assistant_fragment'/)
  assert.match(app, /lastMessage\.voiceTurnId === event\.turn_id/)
})
