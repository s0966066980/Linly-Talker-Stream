import { computed, reactive, ref, watch } from 'vue'

const runtime = reactive({
  llm: {
    model: '',
    base_url: '',
    provider: 'ollama',
    system_prompt: '',
    response_max_chars: 120,
    reply_mode: 'legacy'
  },
  avatar: {
    type: '',
    avatar_id: ''
  },
  avatar_quality: {
    mouth_sharpen: 0.5,
    paste_interpolation: 'lanczos',
    musetalk: {
      bbox_shift: 0,
      extra_margin: 10,
      parsing_mode: 'jaw',
      left_cheek_width: 90,
      right_cheek_width: 90,
      upper_boundary_ratio: 0.5,
      expand: 1.5,
      mask_blur_ratio: 0.05
    },
    wav2lip: {
      pad_top: 0,
      pad_bottom: 10,
      pad_left: 0,
      pad_right: 0
    }
  },
  engines: [],
  characters: [],
  session_count: 0,
  switching: false,
  ready: false,
  model_ready: false
})

const ollama = reactive({
  models: [],
  reachable: false,
  error: '',
  current: '',
  base_url: ''
})

const llamacpp = reactive({
  models: [],
  reachable: false,
  error: '',
  base_url: '',
  server_running: false,
  binary: ''
})

const SILERO_ENGINE = {
  id: 'silero',
  label: 'Silero VAD',
  available: true,
  install: 'uv pip install "silero-vad>=5.1"'
}

const vad = reactive({
  supported: false,
  enabled: true,
  type: 'silero',
  threshold: 0.5,
  aggressiveness: 2,
  min_speech_ms: 250,
  min_silence_ms: 500,
  speech_pad_ms: 150,
  engines: [SILERO_ENGINE],
  asr_mode: 'server',
  effective: false
})

// 面板上正在編輯的值；啟用開關會立刻提交
const vadDraft = reactive({
  enabled: true,
  type: 'silero',
  threshold: 0.5,
  aggressiveness: 2,
  min_silence_ms: 500,
  asr_mode: 'server'
})

const speech = reactive({
  stt: {
    type: 'whisper',
    model_size: 'base',
    language: 'zh',
    output_script: 'traditional-tw',
    device: 'auto',
    local_model_ready: false,
    engines: [],
    model_sizes: ['tiny', 'base', 'small', 'medium', 'large-v3'],
    models_by_engine: {
      whisper: ['tiny', 'base', 'small', 'medium', 'large-v3'],
      funasr: ['paraformer-zh']
    },
    languages: ['zh', 'en', 'auto'],
    devices: ['auto', 'cpu', 'cuda']
  },
  tts: {
    type: 'edgetts',
    ref_file: 'zh-TW-HsiaoChenNeural',
    ref_text: '',
    tts_server: '',
    model: '',
    language: 'Chinese',
    speaker: 'Vivian',
    instruct: '',
    device: 'auto',
    engines: [],
    models: [],
    languages: [],
    speakers: [],
    edge_voices: [],
    devices: ['auto', 'cpu', 'cuda']
  }
})

const sttDraft = reactive({
  type: 'whisper',
  model_size: 'base',
  language: 'zh',
  output_script: 'traditional-tw',
  device: 'auto'
})
const ttsDraft = reactive({
  type: 'edgetts',
  ref_file: 'zh-TW-HsiaoChenNeural',
  ref_text: '',
  tts_server: '',
  model: '',
  language: 'Chinese',
  speaker: 'Vivian',
  instruct: '',
  device: 'auto'
})
const applyingStt = ref(false)
const applyingTts = ref(false)
const speechError = ref('')

const selectedProvider = ref('ollama')

const loadingSettings = ref(false)
const loadingModels = ref(false)
const applyingLlm = ref(false)
const applyingAvatar = ref(false)
const applyingVad = ref(false)
const comparingVad = ref(false)
const settingsError = ref('')
const modelsError = ref('')
const vadError = ref('')
const vadCompareError = ref('')
const vadCompareResult = ref(null)

const selectedEngine = ref('')
const selectedAvatarId = ref('')
const selectedLlm = ref('')
const selectedSystemPrompt = ref('')
const selectedResponseMaxChars = ref(120)
const selectedReplyMode = ref('legacy')

const responseLengthError = computed(() => {
  const value = Number(selectedResponseMaxChars.value)
  return !Number.isInteger(value) || value < 20 || value > 2000
})

const filteredCharacters = computed(() => {
  if (!selectedEngine.value) return runtime.characters
  return runtime.characters.filter((item) => item.type === selectedEngine.value)
})

const currentProviderModels = computed(() => {
  return selectedProvider.value === 'llamacpp' ? llamacpp.models : ollama.models
})

const llmDirty = computed(() => {
  if (!selectedLlm.value || !selectedSystemPrompt.value.trim() || responseLengthError.value) return false
  return (
    selectedProvider.value !== runtime.llm.provider ||
    selectedLlm.value !== runtime.llm.model ||
    selectedSystemPrompt.value !== (runtime.llm.system_prompt || '') ||
    Number(selectedResponseMaxChars.value) !== Number(runtime.llm.response_max_chars || 120) ||
    selectedReplyMode.value !== (runtime.llm.reply_mode || 'legacy')
  )
})

const avatarDirty = computed(() => {
  const changed = (
    selectedEngine.value !== runtime.avatar.type ||
    selectedAvatarId.value !== runtime.avatar.avatar_id
  )
  return changed || !runtime.model_ready
})

const vadDirty = computed(() => {
  return (
    vadDraft.enabled !== vad.enabled ||
    vadDraft.type !== vad.type ||
    Number(vadDraft.threshold) !== Number(vad.threshold) ||
    Number(vadDraft.aggressiveness) !== Number(vad.aggressiveness) ||
    Number(vadDraft.min_silence_ms) !== Number(vad.min_silence_ms) ||
    vadDraft.asr_mode !== vad.asr_mode
  )
})

const sttDirty = computed(() => (
  sttDraft.type !== speech.stt.type ||
  sttDraft.model_size !== speech.stt.model_size ||
  sttDraft.language !== speech.stt.language ||
  sttDraft.output_script !== speech.stt.output_script ||
  sttDraft.device !== speech.stt.device
))

const ttsDirty = computed(() => (
  ttsDraft.type !== speech.tts.type ||
  ttsDraft.ref_file !== speech.tts.ref_file ||
  ttsDraft.ref_text !== speech.tts.ref_text ||
  ttsDraft.tts_server !== speech.tts.tts_server ||
  ttsDraft.model !== speech.tts.model ||
  ttsDraft.language !== speech.tts.language ||
  ttsDraft.speaker !== speech.tts.speaker ||
  ttsDraft.instruct !== speech.tts.instruct ||
  ttsDraft.device !== speech.tts.device
))

const sttModelOptions = computed(() => (
  speech.stt.models_by_engine?.[sttDraft.type] || speech.stt.model_sizes || []
))

watch(() => sttDraft.type, () => {
  if (sttModelOptions.value.length && !sttModelOptions.value.includes(sttDraft.model_size)) {
    sttDraft.model_size = sttModelOptions.value[0]
  }
})

const EDGE_VOICE_ID = /^zh-TW-.+Neural$/

watch(() => ttsDraft.type, (type, previous) => {
  if (previous === 'edgetts' && type !== 'edgetts' && EDGE_VOICE_ID.test(ttsDraft.ref_file)) {
    ttsDraft.ref_file = ''
  }
  if (
    type === 'edgetts' &&
    speech.tts.edge_voices?.length &&
    !speech.tts.edge_voices.some((voice) => voice.id === ttsDraft.ref_file)
  ) {
    ttsDraft.ref_file = speech.tts.edge_voices[0].id
  }
})

const selectedVadEngine = computed(() => {
  return vad.engines.find((item) => item.id === vadDraft.type) || null
})

const selectedEngineInfo = computed(() => {
  return runtime.engines.find((item) => item.id === selectedEngine.value) || null
})

const QUALITY_DEFAULTS = {
  mouth_sharpen: 0.5,
  paste_interpolation: 'lanczos',
  musetalk: {
    bbox_shift: 0,
    extra_margin: 10,
    parsing_mode: 'jaw',
    left_cheek_width: 90,
    right_cheek_width: 90,
    upper_boundary_ratio: 0.5,
    expand: 1.5,
    mask_blur_ratio: 0.05
  },
  wav2lip: {
    pad_top: 0,
    pad_bottom: 10,
    pad_left: 0,
    pad_right: 0
  }
}

function mergeQuality(raw) {
  const value = raw || {}
  return {
    mouth_sharpen: Number(value.mouth_sharpen ?? QUALITY_DEFAULTS.mouth_sharpen),
    paste_interpolation: value.paste_interpolation || QUALITY_DEFAULTS.paste_interpolation,
    musetalk: { ...QUALITY_DEFAULTS.musetalk, ...(value.musetalk || {}) },
    wav2lip: { ...QUALITY_DEFAULTS.wav2lip, ...(value.wav2lip || {}) }
  }
}

const qualityDraft = reactive(mergeQuality())
const applyingQuality = ref(false)
const qualityError = ref('')

function assignQualityDraft(value) {
  const merged = mergeQuality(value)
  qualityDraft.mouth_sharpen = merged.mouth_sharpen
  qualityDraft.paste_interpolation = merged.paste_interpolation
  Object.assign(qualityDraft.musetalk, merged.musetalk)
  Object.assign(qualityDraft.wav2lip, merged.wav2lip)
}

const qualityDirty = computed(() => (
  JSON.stringify(mergeQuality(qualityDraft)) !== JSON.stringify(mergeQuality(runtime.avatar_quality))
))

async function parseJson(response) {
  let data = {}
  try {
    data = await response.json()
  } catch (error) {
    if (response.status === 404) {
      throw new Error('後端尚未更新設定介面，請重啟後端與前端服務')
    }
    throw error
  }
  if (!response.ok || data.code !== 0) {
    const message = data.msg || (
      response.status === 404
        ? '後端尚未更新設定介面，請重啟後端與前端服務'
        : `HTTP ${response.status}`
    )
    const error = new Error(message)
    error.status = response.status
    error.payload = data
    throw error
  }
  return data.data
}

function applyVadSnapshot(data) {
  if (!data) return
  Object.assign(vad, data)
  vad.type = 'silero'
  vad.engines = [SILERO_ENGINE]
  vadDraft.enabled = Boolean(data.enabled)
  vadDraft.type = 'silero'
  vadDraft.threshold = Number(data.threshold ?? 0.5)
  vadDraft.aggressiveness = Number(data.aggressiveness ?? 2)
  vadDraft.min_silence_ms = Number(data.min_silence_ms ?? 500)
  vadDraft.asr_mode = data.asr_mode || 'browser'
}

function applySpeechSnapshot(data) {
  if (!data) return
  if (data.stt) {
    Object.assign(speech.stt, data.stt)
    Object.assign(sttDraft, {
      type: data.stt.type,
      model_size: data.stt.model_size,
      language: data.stt.language,
      output_script: data.stt.output_script || 'traditional-tw',
      device: data.stt.device
    })
  }
  if (data.tts) {
    Object.assign(speech.tts, data.tts)
    Object.assign(ttsDraft, {
      type: data.tts.type,
      ref_file: data.tts.ref_file || '',
      ref_text: data.tts.ref_text || '',
      tts_server: data.tts.tts_server || '',
      model: data.tts.model || '',
      language: data.tts.language || 'Chinese',
      speaker: data.tts.speaker || 'Vivian',
      instruct: data.tts.instruct || '',
      device: data.tts.device || 'auto'
    })
  }
}

async function loadSpeechSettings() {
  speechError.value = ''
  try {
    const data = await parseJson(await fetch('/api/speech'))
    applySpeechSnapshot(data)
    return data
  } catch (error) {
    speechError.value = error.message
    throw error
  }
}

async function applySttSettings() {
  applyingStt.value = true
  speechError.value = ''
  try {
    const data = await parseJson(await fetch('/api/speech/stt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sttDraft)
    }))
    applySpeechSnapshot({ stt: data })
    return data
  } catch (error) {
    speechError.value = error.message
    throw error
  } finally {
    applyingStt.value = false
  }
}

async function applyTtsSettings() {
  applyingTts.value = true
  speechError.value = ''
  try {
    const data = await parseJson(await fetch('/api/speech/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ttsDraft)
    }))
    applySpeechSnapshot({ tts: data })
    if (data.preview_audio) {
      const preview = new Audio(data.preview_audio)
      await preview.play()
    }
    return data
  } catch (error) {
    speechError.value = error.message
    throw error
  } finally {
    applyingTts.value = false
  }
}

async function loadVadSettings() {
  vadError.value = ''
  try {
    const data = await parseJson(await fetch('/api/vad'))
    applyVadSnapshot(data)
    return data
  } catch (error) {
    vadError.value = error.message
    throw error
  }
}

async function compareVadEngines(file) {
  comparingVad.value = true
  vadCompareError.value = ''
  vadCompareResult.value = null
  try {
    const form = new FormData()
    form.append('file', file)
    const data = await parseJson(await fetch('/api/vad/compare', {
      method: 'POST',
      body: form
    }))
    vadCompareResult.value = data
    return data
  } catch (error) {
    vadCompareError.value = error.message
    throw error
  } finally {
    comparingVad.value = false
  }
}

async function applyVadSettings() {
  applyingVad.value = true
  vadError.value = ''
  try {
    const data = await parseJson(await fetch('/api/vad', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: vadDraft.enabled,
        type: 'silero',
        threshold: Number(vadDraft.threshold),
        aggressiveness: Number(vadDraft.aggressiveness),
        min_silence_ms: Number(vadDraft.min_silence_ms),
        asr_mode: vadDraft.enabled ? 'server' : 'browser'
      })
    }))
    applyVadSnapshot(data)
    if (data.warmup_error) {
      vadError.value = data.warmup_error
    }
    return data
  } catch (error) {
    vadError.value = error.message
    throw error
  } finally {
    applyingVad.value = false
  }
}

async function applyMouthQuality() {
  applyingQuality.value = true
  qualityError.value = ''
  try {
    const data = await parseJson(await fetch('/api/avatar/quality', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mergeQuality(qualityDraft))
    }))
    runtime.avatar_quality = mergeQuality(data)
    assignQualityDraft(data)
    return data
  } catch (error) {
    qualityError.value = error.message
    throw error
  } finally {
    applyingQuality.value = false
  }
}

function applySnapshot(data) {
  runtime.llm = data.llm
  runtime.avatar = data.avatar
  runtime.avatar_quality = mergeQuality(data.avatar_quality)
  assignQualityDraft(runtime.avatar_quality)
  runtime.engines = data.engines || []
  runtime.characters = data.characters || []
  runtime.session_count = data.session_count || 0
  runtime.switching = Boolean(data.switching)
  runtime.ready = Boolean(data.ready)
  runtime.model_ready = Boolean(data.model_ready)
  applyVadSnapshot(data.vad)
  applySpeechSnapshot(data.speech)
  selectedEngine.value = data.avatar?.type || ''
  selectedAvatarId.value = data.avatar?.avatar_id || ''
  selectedProvider.value = data.llm?.provider || selectedProvider.value || 'ollama'
  if (!selectedLlm.value || selectedLlm.value === runtime.llm.model) {
    selectedLlm.value = data.llm?.model || ''
  }
  selectedSystemPrompt.value = data.llm?.system_prompt || ''
  selectedResponseMaxChars.value = Number(data.llm?.response_max_chars || 120)
  selectedReplyMode.value = data.llm?.reply_mode || 'legacy'
}

async function loadRuntimeSettings() {
  loadingSettings.value = true
  settingsError.value = ''
  try {
    const data = await parseJson(await fetch('/api/settings'))
    applySnapshot(data)
    return data
  } catch (error) {
    settingsError.value = error.message
    throw error
  } finally {
    loadingSettings.value = false
  }
}

function applyProviderBlock(target, block) {
  target.models = block.models || []
  target.reachable = Boolean(block.reachable)
  target.error = block.error || ''
  target.base_url = block.base_url || ''
}

async function loadOllamaModels() {
  loadingModels.value = true
  modelsError.value = ''
  try {
    const data = await parseJson(await fetch('/api/llm/models'))
    const current = data.current || {}
    const providers = data.providers || {}

    if (providers.ollama) {
      applyProviderBlock(ollama, providers.ollama)
    } else {
      applyProviderBlock(ollama, data)
    }
    ollama.current = current.model || runtime.llm.model

    if (providers.llamacpp) {
      applyProviderBlock(llamacpp, providers.llamacpp)
      llamacpp.server_running = Boolean(providers.llamacpp.server_running)
      llamacpp.binary = providers.llamacpp.binary || ''
    }

    if (current.provider) {
      selectedProvider.value = current.provider
    }
    if (current.model) {
      selectedLlm.value = current.model
    }

    const active = selectedProvider.value === 'llamacpp' ? llamacpp : ollama
    modelsError.value = active.reachable ? '' : (active.error || '')
    return data
  } catch (error) {
    ollama.reachable = false
    ollama.models = []
    modelsError.value = error.message
    throw error
  } finally {
    loadingModels.value = false
  }
}

async function applyLlmModel(
  model = selectedLlm.value,
  provider = selectedProvider.value,
  systemPrompt = selectedSystemPrompt.value,
  responseMaxChars = selectedResponseMaxChars.value,
  replyMode = selectedReplyMode.value
) {
  applyingLlm.value = true
  try {
    const data = await parseJson(await fetch('/api/llm/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        provider,
        system_prompt: systemPrompt,
        response_max_chars: Number(responseMaxChars),
        reply_mode: replyMode
      })
    }))
    runtime.llm.model = data.model
    runtime.llm.provider = data.provider || provider
    runtime.llm.base_url = data.base_url || runtime.llm.base_url
    runtime.llm.system_prompt = data.system_prompt || systemPrompt
    runtime.llm.response_max_chars = Number(data.response_max_chars || responseMaxChars)
    runtime.llm.reply_mode = data.reply_mode || replyMode
    ollama.current = data.model
    selectedLlm.value = data.model
    selectedProvider.value = data.provider || provider
    selectedSystemPrompt.value = runtime.llm.system_prompt
    selectedResponseMaxChars.value = runtime.llm.response_max_chars
    selectedReplyMode.value = runtime.llm.reply_mode
    return data
  } finally {
    applyingLlm.value = false
  }
}

const importing = ref(false)
const importJob = ref(null)
const importError = ref('')

async function importCharacter({ file, engine, avatarId, overwrite = false }) {
  if (!file) {
    throw new Error('請選擇影片檔案')
  }
  importing.value = true
  importError.value = ''
  importJob.value = { status: 'queued', progress: 0, message: '正在上傳影片' }
  try {
    const form = new FormData()
    form.append('video', file)
    form.append('type', engine)
    if (avatarId) form.append('avatar_id', avatarId)
    if (overwrite) form.append('overwrite', 'true')
    form.append('quality', JSON.stringify(mergeQuality(qualityDraft)))

    const started = await parseJson(await fetch('/api/avatars/import', {
      method: 'POST',
      body: form
    }))
    importJob.value = started
    return await pollImportJob(started.id)
  } catch (error) {
    importError.value = error.message
    throw error
  } finally {
    importing.value = false
  }
}

async function pollImportJob(jobId) {
  const started = Date.now()
  while (Date.now() - started < 30 * 60 * 1000) {
    const data = await parseJson(await fetch(`/api/avatars/import/${jobId}`))
    importJob.value = data
    if (data.status === 'done') {
      return data
    }
    if (data.status === 'failed') {
      throw new Error(data.error || data.message || '製作失敗')
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error('製作超時，請檢視後端日誌')
}

async function applyAvatar(engine = selectedEngine.value, avatarId = selectedAvatarId.value) {
  applyingAvatar.value = true
  try {
    const data = await parseJson(await fetch('/api/avatar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: engine, avatar_id: avatarId })
    }))
    runtime.avatar.type = data.type
    runtime.avatar.avatar_id = data.avatar_id
    runtime.model_ready = true
    selectedEngine.value = data.type
    selectedAvatarId.value = data.avatar_id
    return data
  } finally {
    applyingAvatar.value = false
  }
}

function selectProvider(id) {
  selectedProvider.value = id
  const models = id === 'llamacpp' ? llamacpp.models : ollama.models
  if (runtime.llm.provider === id && runtime.llm.model) {
    selectedLlm.value = runtime.llm.model
  } else if (models.length) {
    selectedLlm.value = models[0].name
  } else {
    selectedLlm.value = ''
  }
  const active = id === 'llamacpp' ? llamacpp : ollama
  modelsError.value = active.reachable ? '' : (active.error || '')
}

function selectEngine(engineId) {
  const engine = runtime.engines.find((item) => item.id === engineId)
  if (!engine || (!engine.available && !engine.can_import)) return
  selectedEngine.value = engineId
  const stillValid = filteredCharacters.value.some((item) => item.id === selectedAvatarId.value)
  if (!stillValid) {
    const first = filteredCharacters.value[0]
    selectedAvatarId.value = first ? first.id : ''
  }
}

function selectCharacter(avatarId) {
  const character = runtime.characters.find((item) => item.id === avatarId)
  if (!character) return
  selectedEngine.value = character.type
  selectedAvatarId.value = character.id
}

export function useRuntimeSettings() {
  return {
    runtime,
    ollama,
    llamacpp,
    selectedProvider,
    currentProviderModels,
    loadingSettings,
    loadingModels,
    applyingLlm,
    applyingAvatar,
    settingsError,
    modelsError,
    selectedEngine,
    selectedAvatarId,
    selectedLlm,
    selectedSystemPrompt,
    selectedResponseMaxChars,
    selectedReplyMode,
    responseLengthError,
    filteredCharacters,
    llmDirty,
    avatarDirty,
    selectedEngineInfo,
    loadRuntimeSettings,
    loadOllamaModels,
    applyLlmModel,
    applyAvatar,
    applyMouthQuality,
    qualityDraft,
    qualityDirty,
    applyingQuality,
    qualityError,
    importCharacter,
    importing,
    importJob,
    importError,
    selectProvider,
    selectEngine,
    selectCharacter,
    vad,
    vadDraft,
    vadDirty,
    vadError,
    applyingVad,
    comparingVad,
    selectedVadEngine,
    vadCompareError,
    vadCompareResult,
    loadVadSettings,
    applyVadSettings,
    compareVadEngines,
    speech,
    sttDraft,
    ttsDraft,
    sttDirty,
    sttModelOptions,
    ttsDirty,
    applyingStt,
    applyingTts,
    speechError,
    loadSpeechSettings,
    applySttSettings,
    applyTtsSettings
  }
}
