import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { useSpeechRecognition } from '../src/composables/useSpeechRecognition.js'

test('互動對話不再使用瀏覽器 Web Speech API', () => {
  const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(
    appSource,
    /useSpeechRecognition|MediaRecorder|rmsSpeechEndpointer/,
    'App 的互動麥克風應統一走 WebRTC / Silero / STT'
  )
})

test('支援語音辨識時可以啟動瀏覽器辨識器', () => {
  let startCalls = 0

  class FakeSpeechRecognition {
    start() {
      startCalls += 1
    }
  }

  const previousWindow = globalThis.window
  globalThis.window = { SpeechRecognition: FakeSpeechRecognition }

  try {
    const { isSupported, startRecognition } = useSpeechRecognition()

    if (isSupported) startRecognition()

    assert.equal(startCalls, 1, '獨立使用 composable 時仍可啟動瀏覽器辨識')
  } finally {
    globalThis.window = previousWindow
  }
})
