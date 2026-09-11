const STAGE_REPLY_FADE_EVENTS = new Set([
  'speaking_end',
  'turn_committed'
])

export function shouldFadeStageReply(eventType) {
  return STAGE_REPLY_FADE_EVENTS.has(String(eventType || ''))
}
