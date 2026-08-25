import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/composables/useWebRTC.js', import.meta.url),
  'utf8'
)

test('WebRTC 同時承載麥克風上行與語音事件', () => {
  assert.match(source, /getUserMedia/)
  assert.match(source, /pc\.addTrack\(microphoneStream\.getAudioTracks\(\)\[0\]/)
  assert.match(source, /createDataChannel\('voice-events'/)
})

test('麥克風請求啟用瀏覽器迴音與噪音處理', () => {
  assert.match(source, /echoCancellation:\s*true/)
  assert.match(source, /noiseSuppression:\s*true/)
  assert.match(source, /autoGainControl:\s*true/)
})

test('資料通道失效時會關閉收音並進入重連狀態', () => {
  assert.match(source, /eventChannel\.onclose/)
  assert.match(source, /setCaptureEnabled\(false\)/)
  assert.match(source, /notifyConnection\('reconnecting'\)/)
})
