<!-- Linly-Talker-Stream (https://github.com/Kedreamix/Linly-Talker-Stream). Copyright [Linly-talker-stream@kedreamix]. Apache-2.0. -->
<template>
  <div class="app-wrapper">
    <!-- 頂部導航欄 -->
    <header class="app-header">
      <div class="header-content">
        <div class="logo-section">
          <div class="logo-icon">
            <i class="bi bi-robot"></i>
          </div>
          <div class="logo-text">
            <h1>{{ t('header.title') }}</h1>
            <p>{{ t('header.subtitle') }}</p>
          </div>
        </div>
        
        <div class="status-section">
          <div class="status-badge" :class="statusClass">
            <span class="status-dot"></span>
            <span class="status-text">{{ statusText }}</span>
          </div>
          <div class="session-info" v-if="sessionId > 0">
            <i class="bi bi-hash"></i>
            <span>{{ t('header.session') }} {{ sessionId }}</span>
          </div>
          <a 
            href="https://github.com/Kedreamix/Linly-Talker-Stream" 
            target="_blank" 
            class="github-link"
            :title="t('header.github')"
          >
            <i class="bi bi-github"></i>
            <span>{{ t('header.github') }}</span>
          </a>
          <SettingsPanel 
            :is-connected="isConnected || connectionStatus === 'connecting'"
            @settings-changed="onSettingsChanged" 
            @notification="showNotification"
            @request-disconnect="handleStopConnection"
            @avatar-ready="onAvatarReady"
          />
        </div>
      </div>
    </header>

    <!-- 主內容區 -->
    <main class="main-content">
      <div class="content-wrapper">
        <!-- 左側：對話區域 -->
        <div class="chat-section">
          <div class="chat-header">
            <h2><i class="bi bi-chat-dots"></i> {{ t('chat.title') }}</h2>
            <div class="chat-actions">
              <button 
                class="action-btn" 
                :class="{ active: activeMode === 'chat' }"
                @click="activeMode = 'chat'"
              >
                <i class="bi bi-chat-text"></i>
                {{ t('chat.chatMode') }}
              </button>
              <button 
                class="action-btn"
                :class="{ active: activeMode === 'tts' }"
                @click="activeMode = 'tts'"
              >
                <i class="bi bi-volume-up"></i>
                {{ t('chat.ttsMode') }}
              </button>
              <button 
                class="action-btn clear-history-btn"
                @click="clearChatHistory"
                :disabled="!isConnected"
                :title="isConnected ? t('chat.clearHistory') : t('notifications.connectFirst')"
              >
                <i class="bi bi-trash"></i>
                {{ t('chat.clearHistory') }}
              </button>
            </div>
          </div>

          <!-- 對話模式 -->
          <div v-if="activeMode === 'chat'" class="chat-mode">
            <div class="messages-container" ref="messagesRef">
              <div 
                v-for="(msg, index) in chatMessages" 
                :key="index"
                class="message"
                :class="msg.type === 'user' ? 'message-user' : 'message-ai'"
              >
                <div class="message-avatar">
                  <i :class="msg.type === 'user' ? 'bi bi-person-circle' : 'bi bi-robot'"></i>
                </div>
                <div class="message-content">
                  <div class="message-header">
                    <span class="message-sender">{{ msg.type === 'user' ? t('chat.you') : t('chat.ai') }}</span>
                    <span class="message-time" v-if="appSettings.showTimestamp">{{ msg.time }}</span>
                  </div>
                  <div class="message-text" v-html="renderMarkdown(msg.text)"></div>
                </div>
              </div>
              
              <div v-if="isThinking" class="message message-ai typing">
                <div class="message-avatar">
                  <i class="bi bi-robot"></i>
                </div>
                <div class="message-content">
                  <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              </div>
            </div>

            <div class="input-area">
              <div class="input-box">
                <div class="textarea-wrapper">
                  <textarea 
                    v-model="chatInput"
                    @keydown.enter.exact.prevent="sendChatMessage"
                    :placeholder="isConnected ? t('chat.inputPlaceholder') : t('chat.inputPlaceholderDisconnected')"
                    :disabled="!isConnected"
                    rows="1"
                  ></textarea>
                  <button 
                    v-if="chatInput.trim()"
                    class="clear-input-btn"
                    @click="clearInput"
                    :title="t('chat.clearInput')"
                  >
                    <i class="bi bi-x-circle-fill"></i>
                  </button>
                </div>
                <div
                  v-if="isConnected"
                  class="voice-state-badge"
                  :data-state="voiceState"
                  aria-live="polite"
                >
                  <span class="status-dot"></span>
                  {{ voiceStateLabel }}
                </div>
                <div class="input-actions">
                  <button 
                    class="voice-btn"
                    @mousedown="handleVoiceButtonPress"
                    @mouseup="handleVoiceButtonRelease"
                    @click="handleVoiceButtonClick"
                    @touchstart.prevent="handleVoiceButtonPress"
                    @touchend="handleVoiceButtonRelease"
                    :class="{ recording: isRecordingVoice, 'continuous-mode': handsFreeTalk }"
                    :disabled="!isConnected"
                    :title="getVoiceButtonTitle"
                  >
                    <div class="voice-icon-wrapper">
                      <i class="bi bi-mic-fill"></i>
                      <span v-if="isRecordingVoice" class="recording-pulse"></span>
                    </div>
                    <span class="voice-btn-text">{{ voiceButtonLabel }}</span>
                  </button>
                  <button 
                    class="send-btn" 
                    @click="sendChatMessage" 
                    :disabled="!isConnected || !chatInput.trim()"
                    :title="!isConnected ? t('tooltips.connectDisabled') : ''"
                  >
                    <i class="bi bi-send-fill"></i>
                    <span>{{ t('chat.sendButton') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 朗讀模式 -->
          <div v-if="activeMode === 'tts'" class="tts-mode">
            <div class="tts-container">
              <h3><i class="bi bi-file-text"></i> {{ t('chat.ttsTitle') }}</h3>
              <textarea 
                v-model="ttsInput"
                :placeholder="isConnected ? t('chat.ttsInputPlaceholder') : t('chat.inputPlaceholderDisconnected')"
                :disabled="!isConnected"
                rows="12"
              ></textarea>
              <button 
                class="tts-btn" 
                @click="sendTTSMessage" 
                :disabled="!isConnected || !ttsInput.trim()"
                :title="!isConnected ? t('tooltips.connectDisabled') : ''"
              >
                <i class="bi bi-play-circle-fill"></i>
                {{ t('chat.ttsButton') }}
              </button>
            </div>
          </div>
        </div>

        <!-- 右側：影片區域 -->
        <div class="video-section">
          <div class="video-card">
            <div class="video-header">
              <h2><i class="bi bi-camera-video"></i> {{ t('video.title') }}</h2>
              <div class="video-controls-top">
                <button 
                  v-if="!isConnected" 
                  class="connect-btn" 
                  @click="handleStartConnection"
                  :disabled="!canConnect"
                  :title="connectDisabledTitle"
                >
                  <i class="bi bi-play-circle" v-if="canConnect"></i>
                  <i class="bi bi-hourglass-split spin" v-else-if="!backendReady"></i>
                  <i class="bi bi-sliders" v-else></i>
                  {{ connectButtonLabel }}
                </button>
                <button 
                  v-else 
                  class="disconnect-btn" 
                  @click="handleStopConnection"
                >
                  <i class="bi bi-stop-circle"></i>
                  {{ t('video.disconnect') }}
                </button>
              </div>
            </div>

            <div class="video-wrapper">
              <video id="video" autoplay playsinline></video>
              <div class="video-overlay" v-if="!isConnected">
                <i class="bi bi-camera-video-off" v-if="canConnect"></i>
                <i class="bi bi-sliders" v-else-if="backendReady"></i>
                <i class="bi bi-hourglass-split spin" v-else style="font-size: 4rem;"></i>
                <p v-if="canConnect">{{ t('video.overlayTextReady') }}</p>
                <p v-else-if="backendReady">{{ t('video.overlaySelectAvatar') }}</p>
                <p v-else>{{ t('video.overlayTextLoading') }}</p>
              </div>
              <div class="recording-badge" v-if="isRecording">
                <i class="bi bi-record-circle"></i>
                {{ t('video.recording') }}
              </div>
            </div>

            <div class="video-controls">
              <div class="control-buttons">
                <button 
                  class="control-btn"
                  @click="handleStartRecord"
                  :disabled="!isConnected || isRecording"
                  :title="!isConnected ? t('tooltips.recordDisabled') : ''"
                >
                  <i class="bi bi-record-fill"></i>
                  {{ t('video.startRecord') }}
                </button>
                <button 
                  class="control-btn"
                  @click="handleStopRecord"
                  :disabled="!isRecording"
                >
                  <i class="bi bi-stop-fill"></i>
                  {{ t('video.stopRecord') }}
                </button>
                <button 
                  class="control-btn download-btn"
                  @click="downloadRecord"
                  :disabled="!lastRecordFile"
                  :title="lastRecordFile ? '' : t('tooltips.downloadDisabled')"
                >
                  <i class="bi bi-download"></i>
                  {{ t('video.download') }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- 除錯面板 -->
    <DebugPanel 
      v-if="appSettings.showDebugPanel"
      :connection-status="connectionStatus"
      :session-id="sessionId"
    />
    
    <input type="hidden" id="sessionid" :value="sessionId">
    
    <!-- 通知提示 -->
    <div class="notification-container">
      <transition-group name="notification">
        <div 
          v-for="notification in notifications" 
          :key="notification.id"
          class="notification"
          :class="notification.type"
        >
          <i :class="getNotificationIcon(notification.type)"></i>
          <span>{{ notification.message }}</span>
        </div>
      </transition-group>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import DebugPanel from './components/DebugPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import { useWebRTC } from './composables/useWebRTC'
import { useI18n } from './composables/useI18n'
import { useRuntimeSettings } from './composables/useRuntimeSettings'
import { marked } from 'marked'
import hljs from 'highlight.js'

// 配置 marked
marked.setOptions({
  highlight: function(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch (err) {
        console.error('程式碼高亮失敗:', err)
      }
    }
    return hljs.highlightAuto(code).value
  },
  breaks: true,
  gfm: true
})

const { t, setLocale, loadLocale } = useI18n()
const { vad, vadDraft, loadVadSettings, applyVadSettings } = useRuntimeSettings()
const handsFreeTalk = computed(() => Boolean(vad.enabled))

// Markdown 渲染函式
const renderMarkdown = (text) => {
  if (!text) return ''
  try {
    return marked.parse(text)
  } catch (error) {
    console.error('Markdown 解析錯誤:', error)
    return text
  }
}

const sessionId = ref(0)
const connectionStatus = ref('disconnected')
const isRecording = ref(false)
const activeMode = ref('chat')
const chatInput = ref('')
const ttsInput = ref('')
const isThinking = ref(false)
const isRecordingVoice = ref(false)
const handsFreePaused = ref(false)
const voiceState = ref('disconnected')
const avatarSpeaking = computed(() => voiceState.value === 'avatar_speaking')
const messagesRef = ref(null)
const notifications = ref([])
let notificationIdCounter = 0
const lastRecordFile = ref(null)  // 最後一次錄製的檔案資訊
const backendReady = ref(false)  // 後端是否就緒
const modelReady = ref(false)    // 是否已套用數字人引擎

// 應用設定
const appSettings = ref({
  useStun: false,
  stunServer: 'stun:stun.miwifi.com:3478',
  customStunServer: '',
  autoRecord: false,
  recordFormat: 'mp4',
  showDebugPanel: false,
  showTimestamp: true,
  theme: 'dark',
  uiLanguage: 'zh-TW',
  videoSize: 100
})

const chatMessages = ref([
  { 
    type: 'ai', 
    text: '',  // 將在 onMounted 中設定
    time: getCurrentTime()
  }
])

// 每個語音 turn 保留最後接受的 LLM delta 序號；晚到或重複事件不得污染文字預覽。
const assistantStreamState = new Map()

const isConnected = computed(() => connectionStatus.value === 'connected')
const canConnect = computed(() => (
  backendReady.value
  && modelReady.value
  && connectionStatus.value !== 'connecting'
))
const connectButtonLabel = computed(() => {
  if (!backendReady.value) return t('video.backendStarting')
  if (!modelReady.value) return t('video.selectAvatarFirst')
  return t('video.connect')
})
const connectDisabledTitle = computed(() => {
  if (!backendReady.value) return t('tooltips.connectDisabled')
  if (!modelReady.value) return t('tooltips.selectAvatarFirst')
  return ''
})

const statusClass = computed(() => {
  return {
    'status-connected': connectionStatus.value === 'connected',
    'status-connecting': connectionStatus.value === 'connecting',
    'status-disconnected': connectionStatus.value === 'disconnected'
  }
})

const statusText = computed(() => {
  const statusMap = {
    'connected': t('header.status.connected'),
    'connecting': t('header.status.connecting'),
    'disconnected': t('header.status.disconnected')
  }
  return statusMap[connectionStatus.value] || t('header.status.disconnected')
})

const getVoiceButtonTitle = computed(() => {
  if (!isConnected.value) {
    return t('tooltips.voiceDisabled')
  }
  if (avatarSpeaking.value) return t('tooltips.voiceInterrupt')
  if (handsFreeTalk.value) {
    return isRecordingVoice.value ? t('tooltips.voiceRecording') : t('tooltips.voiceContinuous')
  }
  return t('tooltips.voiceHold')
})

const voiceButtonLabel = computed(() => {
  if (avatarSpeaking.value) return t('chat.voiceButtonInterrupt')
  if (handsFreeTalk.value) {
    return isRecordingVoice.value
      ? t('chat.voiceButtonRecordingContinuous')
      : t('chat.voiceButtonContinuous')
  }
  return isRecordingVoice.value
    ? t('chat.voiceButtonRecording')
    : t('chat.voiceButton')
})

const voiceStateLabel = computed(() => {
  const known = new Set([
    'preparing', 'listening', 'speech_detected', 'stt', 'llm', 'tts_ready',
    'avatar_speaking', 'tail_guard', 'paused', 'degraded', 'reconnecting', 'error'
  ])
  const key = known.has(voiceState.value) ? voiceState.value : 'paused'
  return t(`voiceStates.${key}`)
})

function getCurrentTime() {
  const now = new Date()
  return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`
}

// 通知系統
const showNotification = (message, type = 'info') => {
  const id = notificationIdCounter++
  const notification = { id, message, type }
  notifications.value.push(notification)

  // 3秒後自動移除
  setTimeout(() => {
    const index = notifications.value.findIndex(n => n.id === id)
    if (index > -1) {
      notifications.value.splice(index, 1)
    }
  }, 3000)
}

const getNotificationIcon = (type) => {
  switch (type) {
    case 'success': return 'bi bi-check-circle-fill'
    case 'error': return 'bi bi-x-circle-fill'
    case 'warning': return 'bi bi-exclamation-triangle-fill'
    default: return 'bi bi-info-circle-fill'
  }
}

const handleVoiceEvent = (event) => {
  if (event.type === 'state') {
    voiceState.value = event.state
    isRecordingVoice.value = ['listening', 'speech_detected'].includes(event.state)
    isThinking.value = ['stt', 'llm', 'tts_ready'].includes(event.state)
    if (event.state === 'error' && event.error) {
      showNotification(event.error, 'error')
    }
    return
  }
  if (event.type === 'user_transcript' && event.text) {
    addMessage(event.text, 'user')
  } else if (event.type === 'assistant_response_start') {
    isThinking.value = true
    if (event.turn_id) {
      assistantStreamState.set(event.turn_id, { lastSequence: -1, done: false })
    }
    const duplicate = chatMessages.value.some(
      message => message.type === 'ai' && message.voiceTurnId === event.turn_id
    )
    if (!duplicate) {
      addMessage('', 'ai', { voiceTurnId: event.turn_id, streamingPreview: true })
    }
  } else if (event.type === 'assistant_response_delta' && event.text_delta) {
    isThinking.value = false
    const stream = event.turn_id ? assistantStreamState.get(event.turn_id) : null
    const sequence = Number(event.sequence)
    if (!stream || !Number.isInteger(sequence) || sequence <= stream.lastSequence || stream.done) {
      return
    }
    stream.lastSequence = sequence
    const lastMessage = chatMessages.value[chatMessages.value.length - 1]
    if (lastMessage?.type === 'ai' && lastMessage.voiceTurnId === event.turn_id) {
      if (lastMessage.streamingPreview !== false) {
        lastMessage.text += event.text_delta
        scrollMessagesToEnd()
      }
    } else {
      addMessage(event.text_delta, 'ai', {
        voiceTurnId: event.turn_id,
        streamingPreview: true,
      })
    }
  } else if (event.type === 'assistant_response_done') {
    const stream = event.turn_id ? assistantStreamState.get(event.turn_id) : null
    if (stream) {
      stream.done = true
    }
    const message = chatMessages.value.find(
      item => item.type === 'ai' && item.voiceTurnId === event.turn_id
    )
    if (message) message.streamingPreview = true
    isThinking.value = false
  } else if (event.type === 'assistant_response' && event.text) {
    isThinking.value = false
    const duplicate = chatMessages.value.some(
      message => message.type === 'ai' && message.voiceTurnId === event.turn_id
    )
    if (!duplicate) {
      addMessage(event.text, 'ai', { voiceTurnId: event.turn_id })
    }
  } else if (event.type === 'assistant_fragment' && event.text) {
    isThinking.value = false
    const lastMessage = chatMessages.value[chatMessages.value.length - 1]
    if (lastMessage?.type === 'ai' && lastMessage.voiceTurnId === event.turn_id) {
      // Streaming deltas already rendered this text.  Fragments remain the
      // playback-commit signal and must not duplicate the chat transcript.
      if (lastMessage.streamingPreview !== true || !lastMessage.text) {
        lastMessage.text += event.text
      }
      scrollMessagesToEnd()
    } else {
      addMessage(event.text, 'ai', { voiceTurnId: event.turn_id })
    }
  } else if (event.type === 'speaking_start') {
    voiceState.value = 'avatar_speaking'
    isRecordingVoice.value = false
  } else if (event.type === 'speaking_end') {
    voiceState.value = 'tail_guard'
  }
}

const { startPlay, stopPlay, setCaptureEnabled, interruptVoice } = useWebRTC({
  onNotification: showNotification,
  onVoiceEvent: handleVoiceEvent,
  onSessionId: (id) => {
    sessionId.value = id
  },
  onConnectionState: (state) => {
    if (state === 'connected') connectionStatus.value = 'connected'
    if (state === 'failed') connectionStatus.value = 'disconnected'
    if (state === 'reconnecting') voiceState.value = 'reconnecting'
    if (state === 'text_only') voiceState.value = 'degraded'
  }
})

// 設定變更處理
const onSettingsChanged = (newSettings) => {
  appSettings.value = { ...newSettings }
  console.log('設定已更新:', appSettings.value)
  
  // 更新影片大小
  updateVideoSize(newSettings.videoSize)
  
  // 更新主題
  updateTheme(newSettings.theme)
  
  // 更新介面語言
  if (newSettings.uiLanguage) {
    setLocale(newSettings.uiLanguage)
  }
}

const updateVideoSize = (size) => {
  const video = document.getElementById('video')
  if (video) {
    video.style.width = `${size}%`
  }
}

// 更新主題
const updateTheme = (theme) => {
  const root = document.documentElement
  
  if (theme === 'auto') {
    // 跟隨系統
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    theme = prefersDark ? 'dark' : 'light'
  }
  
  if (theme === 'light') {
    // 淺色模式
    root.style.setProperty('--primary', '#6366f1')
    root.style.setProperty('--primary-dark', '#4f46e5')
    root.style.setProperty('--primary-light', '#818cf8')
    root.style.setProperty('--success', '#10b981')
    root.style.setProperty('--warning', '#f59e0b')
    root.style.setProperty('--danger', '#ef4444')
    root.style.setProperty('--bg-primary', '#ffffff')
    root.style.setProperty('--bg-secondary', '#f8fafc')
    root.style.setProperty('--bg-tertiary', '#e2e8f0')
    root.style.setProperty('--text-primary', '#0f172a')
    root.style.setProperty('--text-secondary', '#475569')
    root.style.setProperty('--text-muted', '#64748b')
    root.style.setProperty('--border', '#cbd5e1')
    root.style.setProperty('--shadow', '0 4px 6px -1px rgba(0, 0, 0, 0.1)')
    root.style.setProperty('--shadow-lg', '0 10px 15px -3px rgba(0, 0, 0, 0.15)')
    root.style.setProperty('--bg-gradient', 'linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%)')
  } else {
    // 深色模式（預設）
    root.style.setProperty('--primary', '#6366f1')
    root.style.setProperty('--primary-dark', '#4f46e5')
    root.style.setProperty('--primary-light', '#818cf8')
    root.style.setProperty('--success', '#10b981')
    root.style.setProperty('--warning', '#f59e0b')
    root.style.setProperty('--danger', '#ef4444')
    root.style.setProperty('--bg-primary', '#0f172a')
    root.style.setProperty('--bg-secondary', '#1e293b')
    root.style.setProperty('--bg-tertiary', '#334155')
    root.style.setProperty('--text-primary', '#f8fafc')
    root.style.setProperty('--text-secondary', '#cbd5e1')
    root.style.setProperty('--text-muted', '#94a3b8')
    root.style.setProperty('--border', '#475569')
    root.style.setProperty('--shadow', '0 4px 6px -1px rgba(0, 0, 0, 0.3)')
    root.style.setProperty('--shadow-lg', '0 10px 15px -3px rgba(0, 0, 0, 0.4)')
    root.style.setProperty('--bg-gradient', 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)')
  }
}

// 檢查後端是否就緒
const checkBackendReady = async () => {
  try {
    const response = await fetch('/health')
    if (response.ok) {
      const data = await response.json()
      if (data.ready) {
        backendReady.value = true
        modelReady.value = Boolean(data.model_ready)
        console.log('✅ 後端已就緒, model_ready=', modelReady.value)
        return true
      }
    }
  } catch (error) {
    console.log('⏳ 等待後端啟動...')
  }
  return false
}

const onAvatarReady = async () => {
  modelReady.value = true
  await checkBackendReady()
}

const handleStartConnection = async () => {
  console.log('🚀 使用者點選"開始連線"按鈕')
  if (connectionStatus.value === 'connecting') return
  
  // 再次確認後端是否就緒
  if (!backendReady.value) {
    showNotification(t('notifications.backendNotReady'), 'warning')
    return
  }
  if (!modelReady.value) {
    showNotification(t('notifications.selectAvatarFirst'), 'warning')
    return
  }
  
  connectionStatus.value = 'connecting'
  
  try {
    // 使用設定中的 STUN 配置
    const newSessionId = await startPlay(null, handsFreeTalk.value)
    if (newSessionId) {
      sessionId.value = newSessionId
      showNotification(t('notifications.connectSuccess'), 'success')
    }
    
    const checkConnection = setInterval(() => {
      const video = document.getElementById('video')
      if (video && video.readyState >= 3 && video.videoWidth > 0) {
        connectionStatus.value = 'connected'
        clearInterval(checkConnection)
        
        // 自動錄製
        if (appSettings.value.autoRecord) {
          setTimeout(() => {
            handleStartRecord()
          }, 1000)
        }
      }
    }, 2000)
    
    setTimeout(() => {
      if (connectionStatus.value === 'connecting') {
        connectionStatus.value = 'disconnected'
        showNotification(t('notifications.connectTimeout'), 'error')
      }
      clearInterval(checkConnection)
    }, 60000)
  } catch (error) {
    console.error('連線失敗:', error)
    connectionStatus.value = 'disconnected'
    showNotification(t('notifications.connectFailed'), 'error')
  }
}

const handleStopConnection = () => {
  handsFreePaused.value = false
  stopPlay()
  sessionId.value = 0
  voiceState.value = 'disconnected'
  isRecordingVoice.value = false
  connectionStatus.value = 'disconnected'
  showNotification(t('notifications.disconnected'), 'info')
}

const handleStartRecord = async () => {
  if (!sessionId.value) {
    console.error('無法錄製：sessionId 為空')
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  console.log('🔴 開始錄製，sessionId:', sessionId.value)
  
  try {
    const response = await fetch('/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'start_record',
        sessionid: sessionId.value
      })
    })
    
    console.log('錄製請求響應狀態:', response.status)
    
    if (response.ok) {
      const data = await response.json()
      console.log('錄製開始成功:', data)
      isRecording.value = true
      showNotification(t('notifications.recordStart'), 'success')
    } else {
      const errorText = await response.text()
      console.error('錄製開始失敗:', response.status, errorText)
      showNotification(`${t('notifications.recordStartFailed')}: ${response.status}`, 'error')
    }
  } catch (error) {
    console.error('Failed to start recording:', error)
    showNotification(`${t('notifications.recordStartFailed')}: ${error.message}`, 'error')
  }
}

const handleStopRecord = async () => {
  if (!sessionId.value) {
    console.error('無法停止錄製：sessionId 為空')
    return
  }
  
  console.log('⏹️ 停止錄製，sessionId:', sessionId.value)
  
  try {
    const response = await fetch('/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'end_record',
        sessionid: sessionId.value
      })
    })
    
    console.log('停止錄製響應狀態:', response.status)
    
    if (response.ok) {
      const data = await response.json()
      console.log('錄製停止成功:', data)
      isRecording.value = false
      
      // 儲存檔案資訊
      if (data.filename) {
        lastRecordFile.value = {
          filename: data.filename,
          filepath: data.filepath
        }
        showNotification(t('notifications.recordStop'), 'success')
      } else {
        showNotification(t('notifications.recordStopSimple'), 'success')
      }
    } else {
      const errorText = await response.text()
      console.error('停止錄製失敗:', response.status, errorText)
      showNotification(`${t('notifications.recordStopFailed')}: ${response.status}`, 'error')
    }
  } catch (error) {
    console.error('Failed to stop recording:', error)
    showNotification(`${t('notifications.recordStopFailed')}: ${error.message}`, 'error')
  }
}

const downloadRecord = () => {
  if (!lastRecordFile.value) {
    showNotification(t('notifications.noRecordFile'), 'warning')
    return
  }
  
  const downloadUrl = `/download/${lastRecordFile.value.filename}`
  const link = document.createElement('a')
  link.href = downloadUrl
  link.download = lastRecordFile.value.filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  
  showNotification(t('notifications.downloading'), 'info')
}

const scrollMessagesToEnd = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

const addMessage = (text, type = 'user', metadata = {}) => {
  chatMessages.value.push({
    text,
    type,
    time: getCurrentTime(),
    ...metadata,
  })
  scrollMessagesToEnd()
}

// 清空輸入框
const clearInput = () => {
  chatInput.value = ''
}

const sendChatMessage = async () => {
  if (!chatInput.value.trim()) return
  
  // 檢查是否已連線
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  const message = chatInput.value
  addMessage(message, 'user')
  chatInput.value = ''
  
  isThinking.value = true
  
  try {
    const response = await fetch('/human', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: message,
        type: 'chat',
        interrupt: true,
        sessionid: sessionId.value
      })
    })
    
    const data = await response.json().catch(() => ({}))
    console.log('回覆輪次已接受:', data)
    if (!response.ok || data.code === -1) {
      throw new Error(data.msg || `HTTP ${response.status}`)
    }
  } catch (error) {
    console.error('Failed to send message:', error)
    const detail = error && error.message ? String(error.message) : ''
    showNotification(
      detail ? `${t('notifications.messageFailed')}：${detail}` : t('notifications.messageFailed'),
      'error'
    )
  }
}

const sendTTSMessage = async () => {
  if (!ttsInput.value.trim()) return
  
  // 檢查是否已連線
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  const message = ttsInput.value
  
  try {
    await fetch('/human', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: message,
        type: 'echo',
        interrupt: true,
        sessionid: sessionId.value
      })
    })
    
    addMessage(`已傳送朗讀請求：${message.substring(0, 50)}${message.length > 50 ? '...' : ''}`, 'system')
    ttsInput.value = ''
  } catch (error) {
    console.error('Failed to send TTS message:', error)
    showNotification(t('notifications.ttsFailed'), 'error')
  }
}

// WebRTC microphone controls; server-side Silero owns endpointing and STT.
const handleVoiceButtonPress = () => {
  if (handsFreeTalk.value || !isConnected.value) return
  handsFreePaused.value = false
  voiceState.value = 'listening'
  isRecordingVoice.value = true
  setCaptureEnabled(true)
}

const handleVoiceButtonRelease = () => {
  if (handsFreeTalk.value || !isConnected.value) return
  isRecordingVoice.value = false
  voiceState.value = 'paused'
  setCaptureEnabled(false, { finalize: true })
}

const handleVoiceButtonClick = () => {
  if (!handsFreeTalk.value || !isConnected.value) return
  if (avatarSpeaking.value) {
    handsFreePaused.value = false
    interruptVoice()
    return
  }
  handsFreePaused.value = !handsFreePaused.value
  setCaptureEnabled(!handsFreePaused.value)
}

watch(handsFreeTalk, (enabled) => {
  handsFreePaused.value = false
  if (isConnected.value) setCaptureEnabled(enabled)
})

onUnmounted(() => {
  stopPlay()
})

// 清空對話歷史
const resetChatMessages = () => {
  chatMessages.value = [
    {
      type: 'ai',
      text: t('chat.welcomeMessage'),
      time: getCurrentTime()
    }
  ]
}

const clearChatHistory = async () => {
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }

  try {
    const response = await fetch('/clear_history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sessionid: sessionId.value
      })
    })

    let payload = {}
    try {
      payload = await response.json()
    } catch (error) {
      payload = {}
    }

    if (!response.ok || payload.code === -1) {
      throw new Error(payload.msg || `HTTP ${response.status}`)
    }

    resetChatMessages()
    showNotification(t('notifications.historyCleared'), 'success')
  } catch (error) {
    console.error('Failed to clear history:', error)
    showNotification(`${t('notifications.historyClearFailed')}: ${error.message}`, 'error')
  }
}

onMounted(async () => {
  console.log('✅ Vue 應用已掛載')
  console.log('後端 API 地址: /offer (通過 Vite proxy 轉發到 localhost:8010)')
  
  // 載入語言設定
  loadLocale()
  
  // 設定歡迎訊息
  if (chatMessages.value.length > 0 && !chatMessages.value[0].text) {
    chatMessages.value[0].text = t('chat.welcomeMessage')
  }
  
  // 應用初始主題
  updateTheme(appSettings.value.theme)
  
  // 拉一次 VAD / 識別來源，決定錄音走瀏覽器識別還是後端（後端才過 VAD）
  loadVadSettings().then(async () => {
    vadDraft.type = 'silero'
    if (vad.type !== 'silero' || (vad.enabled && vad.asr_mode !== 'server')) {
      await applyVadSettings()
    }
  }).catch((error) => {
    console.warn('讀取 VAD 設定失敗，按瀏覽器識別處理:', error.message)
  })

  // 開始輪詢檢查後端是否就緒
  console.log('🔍 開始檢查後端狀態...')
  const checkInterval = setInterval(async () => {
    const ready = await checkBackendReady()
    if (ready) {
      clearInterval(checkInterval)
      showNotification(t('notifications.backendReady'), 'success')
    }
  }, 2000)  // 每2秒檢查一次
  
  // 最多檢查60秒
  setTimeout(() => {
    if (!backendReady.value) {
      clearInterval(checkInterval)
      showNotification(t('notifications.backendTimeout'), 'error')
    }
  }, 60000)
})
</script>

<style>
@import 'highlight.js/styles/atom-one-dark.css';

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --primary: #6366f1;
  --primary-dark: #4f46e5;
  --primary-light: #818cf8;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-tertiary: #334155;
  --text-primary: #f8fafc;
  --text-secondary: #cbd5e1;
  --text-muted: #94a3b8;
  --border: #475569;
  --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.4);
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg-gradient, linear-gradient(135deg, #0f172a 0%, #1e293b 100%));
  color: var(--text-primary);
  min-height: 100vh;
}

.app-wrapper {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* 頂部導航欄 */
.app-header {
  background: var(--bg-secondary);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  padding: 1rem 2rem;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: var(--shadow);
}

.header-content {
  max-width: 1800px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.logo-icon {
  width: 50px;
  height: 50px;
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: white;
  box-shadow: var(--shadow);
}

.logo-text h1 {
  font-size: 1.5rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--primary-light), #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
}

.logo-text p {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0;
}

.status-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.status-badge {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

.status-connected .status-dot {
  background: var(--success);
}

.status-connecting .status-dot {
  background: var(--warning);
}

.status-disconnected .status-dot {
  background: var(--danger);
}

.session-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--bg-tertiary);
  border-radius: 20px;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.github-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 20px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.875rem;
  transition: all 0.2s;
}

.github-link:hover {
  background: var(--primary);
  border-color: var(--primary);
  color: white;
  transform: translateY(-2px);
}

.github-link i {
  font-size: 1.125rem;
}

/* 主內容區 */
.main-content {
  flex: 1;
  padding: 2rem;
}

.content-wrapper {
  max-width: 1800px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1fr 500px;
  gap: 2rem;
  height: calc(100vh - 150px);
}

/* 左側對話區 */
.chat-section {
  background: var(--bg-secondary);
  border-radius: 16px;
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

.chat-header {
  padding: 1.5rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-tertiary);
}

.chat-header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
}

.chat-actions {
  display: flex;
  gap: 0.5rem;
}

.action-btn {
  padding: 0.5rem 1rem;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.action-btn:hover {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.action-btn.active {
  background: var(--primary);
  color: white;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.clear-history-btn:hover:not(:disabled) {
  background: var(--danger);
  color: white;
}

/* 對話模式 */
.chat-mode {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.message {
  display: flex;
  gap: 1rem;
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.message-user .message-avatar {
  background: var(--success);
}

.message-content {
  flex: 1;
  max-width: 70%;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.message-sender {
  font-weight: 600;
  font-size: 0.875rem;
}

.message-time {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.message-text {
  background: var(--bg-tertiary);
  padding: 0.75rem 1rem;
  border-radius: 12px;
  line-height: 1.6;
}

.message-user .message-text {
  background: var(--primary);
}

/* Markdown 樣式 */
.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3),
.message-text :deep(h4),
.message-text :deep(h5),
.message-text :deep(h6) {
  margin-top: 0.5rem;
  margin-bottom: 0.5rem;
  font-weight: 600;
  line-height: 1.3;
}

.message-text :deep(h1) { font-size: 1.5rem; }
.message-text :deep(h2) { font-size: 1.3rem; }
.message-text :deep(h3) { font-size: 1.1rem; }
.message-text :deep(h4) { font-size: 1rem; }

.message-text :deep(p) {
  margin: 0.5rem 0;
}

.message-text :deep(p:first-child) {
  margin-top: 0;
}

.message-text :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text :deep(ul),
.message-text :deep(ol) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.message-text :deep(li) {
  margin: 0.25rem 0;
}

.message-text :deep(code) {
  background: rgba(0, 0, 0, 0.2);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.9em;
}

.message-user .message-text :deep(code) {
  background: rgba(255, 255, 255, 0.2);
}

.message-text :deep(pre) {
  background: rgba(0, 0, 0, 0.3);
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.5rem 0;
}

.message-user .message-text :deep(pre) {
  background: rgba(0, 0, 0, 0.2);
}

.message-text :deep(pre code) {
  background: transparent;
  padding: 0;
  border-radius: 0;
  display: block;
  line-height: 1.5;
}

.message-text :deep(blockquote) {
  border-left: 4px solid var(--primary-light);
  padding-left: 1rem;
  margin: 0.5rem 0;
  color: var(--text-secondary);
  font-style: italic;
}

.message-text :deep(a) {
  color: var(--primary-light);
  text-decoration: none;
}

.message-text :deep(a:hover) {
  text-decoration: underline;
}

.message-text :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.5rem 0;
}

.message-text :deep(table th),
.message-text :deep(table td) {
  border: 1px solid var(--border);
  padding: 0.5rem;
  text-align: left;
}

.message-text :deep(table th) {
  background: rgba(0, 0, 0, 0.2);
  font-weight: 600;
}

.message-text :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 1rem 0;
}

.message-text :deep(strong) {
  font-weight: 700;
}

.message-text :deep(em) {
  font-style: italic;
}

.message-text :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  margin: 0.5rem 0;
}

.typing-indicator {
  display: flex;
  gap: 0.25rem;
  padding: 1rem;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--text-muted);
  border-radius: 50%;
  animation: bounce 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 60%, 100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-10px);
  }
}

/* 輸入區 */
.input-area {
  padding: 1.5rem;
  border-top: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.textarea-wrapper {
  position: relative;
  margin-bottom: 1rem;
}

.input-box textarea {
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem;
  padding-right: 3rem; /* 為清空按鈕留空間 */
  color: var(--text-primary);
  font-size: 1rem;
  resize: none;
  min-height: 60px;
  max-height: 120px;
  transition: all 0.2s;
  font-family: inherit;
}

.input-box textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.input-box textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--bg-tertiary);
}

/* 清空輸入框按鈕 */
.clear-input-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  font-size: 1.2rem;
}

.clear-input-btn:hover {
  color: var(--danger);
  transform: translateY(-50%) scale(1.1);
}

.input-actions {
  display: flex;
  gap: 1rem;
}

.voice-state-badge {
  width: fit-content;
  margin: 0.55rem 0 0.65rem;
  padding: 0.3rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--bg-secondary) 88%, transparent);
  font-size: 0.78rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.voice-state-badge[data-state='listening'],
.voice-state-badge[data-state='speech_detected'] {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 45%, var(--border));
}

.voice-state-badge[data-state='avatar_speaking'] {
  color: var(--primary-light);
  border-color: color-mix(in srgb, var(--primary) 55%, var(--border));
}

.voice-state-badge[data-state='error'],
.voice-state-badge[data-state='degraded'],
.voice-state-badge[data-state='reconnecting'] {
  color: var(--warning);
}

.voice-btn,
.send-btn {
  padding: 0.875rem 1.5rem;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  position: relative;
  overflow: hidden;
}

.voice-btn {
  flex: 1;
  background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
  color: var(--text-primary);
  border: 2px solid var(--border);
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.voice-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--bg-tertiary) 0%, var(--bg-secondary) 100%);
  border-color: var(--primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.voice-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.voice-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--bg-secondary);
}

.voice-btn:disabled:hover {
  background: var(--bg-secondary);
  transform: none;
}

/* 錄音狀態樣式 */
.voice-btn.recording {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
  border-color: #dc2626;
  box-shadow: 0 4px 16px rgba(239, 68, 68, 0.4);
}

.voice-btn.recording:hover {
  background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(239, 68, 68, 0.5);
}

/* 連續模式樣式 */
.voice-btn.continuous-mode:not(.recording) {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  border-color: #2563eb;
}

.voice-btn.continuous-mode:not(.recording):hover {
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
}

/* 語音按鈕圖示容器 */
.voice-icon-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
}

.voice-icon-wrapper i {
  font-size: 1.2rem;
  z-index: 1;
}

/* 錄音脈衝動畫 */
.recording-pulse {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.3);
  animation: pulse-ring 1.5s ease-out infinite;
}

@keyframes pulse-ring {
  0% {
    transform: translate(-50%, -50%) scale(0.8);
    opacity: 1;
  }
  100% {
    transform: translate(-50%, -50%) scale(2);
    opacity: 0;
  }
}

.voice-btn-text {
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.send-btn {
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
  color: white;
  border: 2px solid transparent;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.send-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--primary-dark) 0%, #4338ca 100%);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
}

.send-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-btn span {
  font-size: 0.95rem;
}

/* 朗讀模式 */
.tts-mode {
  flex: 1;
  padding: 2rem;
  overflow-y: auto;
}

.tts-container {
  max-width: 800px;
  margin: 0 auto;
}

.tts-container h3 {
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.tts-container textarea {
  width: 100%;
  background: var(--bg-secondary);
  border: 2px solid var(--border);
  border-radius: 12px;
  padding: 1.25rem;
  color: var(--text-primary);
  font-size: 1rem;
  resize: vertical;
  margin-bottom: 1.5rem;
  min-height: 300px;
  transition: all 0.3s;
  font-family: inherit;
  line-height: 1.6;
}

.tts-container textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
  background: var(--bg-primary);
}

.tts-container textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--bg-secondary);
}

.tts-btn {
  width: 100%;
  padding: 1.125rem 1.5rem;
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
  color: white;
  border: 2px solid transparent;
  border-radius: 12px;
  font-size: 1.05rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.625rem;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.tts-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--primary-dark) 0%, #4338ca 100%);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
}

.tts-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.tts-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.tts-btn i {
  font-size: 1.25rem;
}

/* 右側影片區 */
.video-section {
  background: var(--bg-secondary);
  border-radius: 16px;
  border: 1px solid var(--border);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

.video-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.video-header {
  padding: 1.5rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-tertiary);
}

.video-header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
}

.connect-btn,
.disconnect-btn {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  transition: all 0.2s;
}

.connect-btn {
  background: var(--success);
  color: white;
}

.connect-btn:hover:not(:disabled) {
  background: #059669;
}

.connect-btn:disabled {
  background: var(--text-muted);
  cursor: not-allowed;
  opacity: 0.6;
}

.disconnect-btn {
  background: var(--danger);
  color: white;
}

.disconnect-btn:hover {
  background: #dc2626;
}

.video-wrapper {
  flex: 1;
  position: relative;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-wrapper video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.video-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 3rem;
}

.video-overlay p {
  margin-top: 1rem;
  font-size: 1rem;
}

.recording-badge {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: var(--danger);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  animation: pulse 2s infinite;
}

.video-controls {
  padding: 1.5rem;
  border-top: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.control-buttons {
  display: flex;
  gap: 0.75rem;
}

.control-btn {
  flex: 1;
  padding: 0.875rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  transition: all 0.2s;
  font-weight: 500;
}

.control-btn:hover:not(:disabled) {
  background: var(--primary);
  border-color: var(--primary);
  color: white;
  transform: translateY(-2px);
}

.control-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.download-btn:not(:disabled) {
  background: var(--success, #10b981);
  border-color: var(--success, #10b981);
  color: white;
}

.download-btn:hover:not(:disabled) {
  background: #059669;
  border-color: #059669;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.spin {
  animation: spin 2s linear infinite;
}

/* 響應式 */
@media (max-width: 1400px) {
  .content-wrapper {
    grid-template-columns: 1fr 400px;
  }
}

@media (max-width: 1024px) {
  .content-wrapper {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr 400px;
  }
  
  .input-actions {
    flex-direction: column;
  }
  
  .voice-btn, .send-btn {
    width: 100%;
  }
}

@media (max-width: 768px) {
  .chat-header {
    flex-direction: column;
    gap: 1rem;
    align-items: flex-start;
  }
  
  .chat-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  
  .action-btn {
    flex: 1;
    min-width: 100px;
  }
  
  .voice-btn-text {
    font-size: 0.875rem;
  }
  
  .send-btn span {
    display: none;
  }
  
  .send-btn i {
    font-size: 1.25rem;
  }
}

/* 捲軸樣式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--bg-tertiary);
}

::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* 通知樣式 */
.notification-container {
  position: fixed;
  top: 80px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.notification {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  background: var(--bg-secondary);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  border-left: 4px solid var(--primary);
  min-width: 280px;
  max-width: 400px;
}

.notification i {
  font-size: 20px;
  flex-shrink: 0;
}

.notification.success {
  border-left-color: #10b981;
}

.notification.success i {
  color: #10b981;
}

.notification.error {
  border-left-color: #ef4444;
}

.notification.error i {
  color: #ef4444;
}

.notification.warning {
  border-left-color: #f59e0b;
}

.notification.warning i {
  color: #f59e0b;
}

.notification.info {
  border-left-color: var(--primary);
}

.notification.info i {
  color: var(--primary);
}

/* 通知動畫 */
.notification-enter-active {
  animation: notification-in 0.3s ease-out;
}

.notification-leave-active {
  animation: notification-out 0.3s ease-in;
}

@keyframes notification-in {
  from {
    opacity: 0;
    transform: translateX(100px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes notification-out {
  from {
    opacity: 1;
    transform: translateX(0);
  }
  to {
    opacity: 0;
    transform: translateX(100px);
  }
}
</style>
