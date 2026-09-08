import assert from 'node:assert/strict'
import test from 'node:test'
import {
  placeStageBoard,
  previewScale,
  STAGE_LAYOUT_REF_WIDTH,
  STAGE_LAYOUT_REF_HEIGHT
} from '../src/stageBoardLayout.js'

test('右上對齊時看板貼近影像右上，不進入字幕帶', () => {
  const box = placeStageBoard({
    stageW: 405,
    stageH: 720,
    targetW: 252,
    targetH: 300,
    x: 100,
    y: 0,
    scale: 1
  })
  assert.ok(box.top < 20)
  assert.ok(box.left + box.width > 405 - 20)
  assert.ok(box.top + box.height <= 720 - box.captionH + 0.5)
})

test('控制台縮圖與參考舞台使用同一相對位置', () => {
  const full = placeStageBoard({
    stageW: STAGE_LAYOUT_REF_WIDTH,
    stageH: STAGE_LAYOUT_REF_HEIGHT,
    targetW: 252,
    targetH: 300,
    x: 0,
    y: 100,
    scale: 1
  })
  const miniW = 96
  const miniH = 170
  const scale = previewScale(miniW, miniH)
  const mini = placeStageBoard({
    stageW: miniW,
    stageH: miniH,
    targetW: 252,
    targetH: 300,
    x: 0,
    y: 100,
    scale
  })
  const fullX = full.left / STAGE_LAYOUT_REF_WIDTH
  const miniX = mini.left / miniW
  const fullY = (full.top + full.height) / STAGE_LAYOUT_REF_HEIGHT
  const miniY = (mini.top + mini.height) / miniH
  assert.ok(Math.abs(fullX - miniX) < 0.08)
  assert.ok(Math.abs(fullY - miniY) < 0.08)
})
