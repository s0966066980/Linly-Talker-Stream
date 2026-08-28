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

test('舞台字幕會取消分段語音之間的舊淡出計時', () => {
  assert.match(
    stage,
    /if\(ev\.type === 'speaking_start'\)\{[\s\S]*?clearTimeout\(replyTimer\);[\s\S]*?return;/
  )
  assert.match(
    stage,
    /if\(ev\.type === 'speaking_end'\)\{[\s\S]*?fadeReply\(\);[\s\S]*?return;/
  )
})
