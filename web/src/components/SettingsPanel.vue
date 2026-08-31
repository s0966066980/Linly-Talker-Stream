<template>
  <div class="settings-wrapper">
    <!-- 設定按鈕 -->
    <button class="settings-trigger" @click="toggleSettings" :class="{ active: showSettings }">
      <i class="bi bi-gear-fill"></i>
      <span>{{ t('settings.title') }}</span>
    </button>

    <!-- 設定面板 -->
    <transition name="slide-fade">
      <div v-if="showSettings" class="settings-panel" role="dialog" aria-modal="true" :aria-label="t('settings.systemSettings')">
        <div class="settings-header">
          <h3><i class="bi bi-sliders"></i> {{ t('settings.systemSettings') }}</h3>
          <button class="close-btn" @click="showSettings = false" :aria-label="t('settings.close')">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>

        <nav class="settings-tabs" role="tablist" :aria-label="t('settings.tabs.label')">
          <button
            v-for="(tab, index) in settingsTabs"
            :id="`settings-tab-${tab.id}`"
            :key="tab.id"
            type="button"
            class="settings-tab"
            role="tab"
            :class="{ active: activeSettingsTab === tab.id }"
            :aria-selected="activeSettingsTab === tab.id"
            :aria-controls="`settings-panel-${tab.id}`"
            :tabindex="activeSettingsTab === tab.id ? 0 : -1"
            @click="selectSettingsTab(tab.id)"
            @keydown="handleTabKeydown($event, index)"
          >
            <i :class="tab.icon" aria-hidden="true"></i>
            <span>{{ tab.label }}</span>
          </button>
        </nav>

        <div ref="settingsContentRef" class="settings-content">
          <div class="runtime-summary" v-if="runtime.llm.model || runtime.avatar.type">
            <span class="summary-chip" :title="t('settings.llm.title')">
              <i class="bi bi-cpu"></i>
              {{ runtime.llm.model || t('settings.llm.unknown') }}
            </span>
            <span class="summary-chip" :title="t('settings.avatar.engineTitle')">
              <i class="bi bi-layers"></i>
              {{ currentEngineLabel }}
            </span>
            <span class="summary-chip" :title="t('settings.avatar.characterTitle')">
              <i class="bi bi-person-bounding-box"></i>
              {{ runtime.avatar.avatar_id || t('settings.avatar.noCharacter') }}
            </span>
            <span class="summary-chip" :title="t('settings.vad.title')">
              <i class="bi bi-soundwave"></i>
              {{ currentVadLabel }}
            </span>
          </div>

          <section
            v-show="activeSettingsTab === 'ai'"
            id="settings-panel-ai"
            class="settings-tab-panel"
            role="tabpanel"
            aria-labelledby="settings-tab-ai"
            tabindex="0"
          >
            <!-- 對話模型：Ollama / llama.cpp -->
            <div class="settings-section">
            <h4><i class="bi bi-cpu"></i> {{ t('settings.llm.title') }}</h4>
            <p class="section-hint">{{ t('settings.llm.providerDesc') }}</p>

            <div class="engine-grid" role="listbox" :aria-label="t('settings.llm.provider')">
              <button
                type="button"
                class="engine-card"
                role="option"
                :aria-selected="selectedProvider === 'ollama'"
                :class="{ selected: selectedProvider === 'ollama', current: runtime.llm.provider === 'ollama' }"
                :disabled="applyingLlm"
                @click="selectProvider('ollama')"
              >
                <span class="card-title">Ollama</span>
                <span class="card-desc">{{ t('settings.llm.ollamaDesc') }}</span>
                <span class="card-status" v-if="runtime.llm.provider === 'ollama'">{{ t('settings.avatar.inUse') }}</span>
              </button>
              <button
                type="button"
                class="engine-card"
                role="option"
                :aria-selected="selectedProvider === 'llamacpp'"
                :class="{ selected: selectedProvider === 'llamacpp', current: runtime.llm.provider === 'llamacpp' }"
                :disabled="applyingLlm"
                @click="selectProvider('llamacpp')"
              >
                <span class="card-title">llama.cpp</span>
                <span class="card-desc">{{ t('settings.llm.llamacppDesc') }}</span>
                <span class="card-status" v-if="runtime.llm.provider === 'llamacpp'">{{ t('settings.avatar.inUse') }}</span>
              </button>
            </div>

            <div class="setting-item info-banner" :class="{ 'status-ok': activeLlmBackend.reachable, 'status-error': modelsError }">
              <div class="info-content">
                <i :class="activeLlmBackend.reachable ? 'bi bi-check-circle' : 'bi bi-exclamation-circle'"></i>
                <div>
                  <strong>{{ llmStatusTitle }}</strong>
                  <p>{{ t('settings.llm.endpoint') }}: {{ activeLlmBackend.base_url || runtime.llm.base_url || '—' }}</p>
                  <p v-if="selectedProvider === 'llamacpp' && llamacpp.binary" class="field-hint">
                    llama-server: {{ llamacpp.binary }}
                  </p>
                  <p v-if="modelsError" class="note" role="alert">{{ modelsError }}</p>
                </div>
              </div>
              <button
                class="icon-action-btn"
                type="button"
                :disabled="loadingModels"
                :aria-label="t('settings.llm.refresh')"
                @click="refreshOllama"
              >
                <i class="bi bi-arrow-clockwise" :class="{ spin: loadingModels }"></i>
              </button>
            </div>

            <div class="setting-item setting-item-stack">
              <div class="setting-label">
                <label for="llm-reply-mode">{{ t('settings.llm.replyMode') }}</label>
                <span id="llm-reply-mode-hint" class="setting-desc">
                  {{ selectedReplyMode === 'legacy' ? t('settings.llm.legacyModeDesc') : t('settings.llm.streamingModeDesc') }}
                </span>
              </div>
              <div class="setting-control setting-control-grow">
                <select
                  id="llm-reply-mode"
                  v-model="selectedReplyMode"
                  :disabled="applyingLlm || loadingSettings"
                  aria-describedby="llm-reply-mode-hint"
                >
                  <option value="legacy">{{ t('settings.llm.legacyMode') }}</option>
                  <option value="streaming">{{ t('settings.llm.streamingMode') }}</option>
                </select>
              </div>
            </div>

            <div class="setting-item setting-item-stack">
              <div class="setting-label">
                <label for="llm-model">{{ t('settings.llm.model') }}</label>
                <span class="setting-desc">{{ selectedProvider === 'llamacpp' ? t('settings.llm.llamacppModelDesc') : t('settings.llm.modelDesc') }}</span>
              </div>
              <div class="setting-control setting-control-grow">
                <select
                  id="llm-model"
                  v-if="currentProviderModels.length"
                  v-model="selectedLlm"
                  :disabled="applyingLlm || loadingModels"
                >
                  <option
                    v-for="model in currentProviderModels"
                    :key="model.name"
                    :value="model.name"
                  >
                    {{ formatOllamaOption(model) }}
                  </option>
                </select>
                <input
                  v-else
                  id="llm-model"
                  type="text"
                  v-model="selectedLlm"
                  :placeholder="selectedProvider === 'llamacpp' ? t('settings.llm.ggufPlaceholder') : t('settings.llm.manualPlaceholder')"
                  :disabled="applyingLlm"
                  autocomplete="off"
                >
                <p v-if="!currentProviderModels.length" class="field-hint">
                  {{ selectedProvider === 'llamacpp' ? t('settings.llm.llamacppEmpty') : t('settings.llm.empty') }}
                </p>
              </div>
            </div>

            <div class="setting-item setting-item-stack">
              <div class="setting-label">
                <label for="llm-response-max-chars">{{ t('settings.llm.responseLength') }}</label>
                <span id="llm-response-max-chars-hint" class="setting-desc">
                  {{ t('settings.llm.responseLengthDesc') }}
                </span>
              </div>
              <div class="setting-control setting-control-grow">
                <input
                  id="llm-response-max-chars"
                  v-model.number="selectedResponseMaxChars"
                  type="number"
                  inputmode="numeric"
                  min="20"
                  max="2000"
                  step="10"
                  :disabled="applyingLlm || loadingSettings"
                  :aria-invalid="responseLengthError"
                  aria-describedby="llm-response-max-chars-hint llm-response-max-chars-meta"
                >
                <div id="llm-response-max-chars-meta" class="field-meta">
                  <span v-if="responseLengthError" class="field-error" role="alert">
                    {{ t('settings.llm.responseLengthRange') }}
                  </span>
                  <span class="character-count">
                    {{ selectedResponseMaxChars || '—' }} {{ t('settings.llm.responseLengthUnit') }}
                  </span>
                </div>
              </div>
            </div>

            <div class="setting-item setting-item-stack">
              <div class="setting-label">
                <label for="llm-system-prompt">{{ t('settings.llm.defaultPrompt') }}</label>
                <span id="llm-system-prompt-hint" class="setting-desc">
                  {{ t('settings.llm.defaultPromptDesc') }}
                </span>
              </div>
              <div class="setting-control setting-control-grow">
                <textarea
                  id="llm-system-prompt"
                  v-model="selectedSystemPrompt"
                  rows="8"
                  maxlength="8000"
                  :placeholder="t('settings.llm.defaultPromptPlaceholder')"
                  :disabled="applyingLlm || loadingSettings"
                  aria-describedby="llm-system-prompt-hint llm-system-prompt-count"
                ></textarea>
                <div id="llm-system-prompt-count" class="field-meta">
                  <span v-if="!selectedSystemPrompt.trim()" class="field-error" role="alert">
                    {{ t('settings.llm.defaultPromptRequired') }}
                  </span>
                  <span class="character-count">{{ selectedSystemPrompt.length }} / 8000</span>
                </div>
              </div>
            </div>

            <button
              class="btn-apply"
              type="button"
              :disabled="!llmDirty || applyingLlm || !selectedLlm || !selectedSystemPrompt.trim() || responseLengthError"
              @click="handleApplyLlm"
            >
              <i class="bi bi-hourglass-split spin" v-if="applyingLlm"></i>
              <i class="bi bi-check-lg" v-else></i>
              {{ applyingLlm ? t('settings.llm.applying') : t('settings.llm.apply') }}
            </button>
            </div>
          </section>

          <section
            v-show="activeSettingsTab === 'avatar'"
            id="settings-panel-avatar"
            class="settings-tab-panel"
            role="tabpanel"
            aria-labelledby="settings-tab-avatar"
            tabindex="0"
          >
            <!-- 數字人引擎 -->
            <div class="settings-section">
            <h4><i class="bi bi-layers"></i> {{ t('settings.avatar.engineTitle') }}</h4>
            <p class="section-hint">{{ t('settings.avatar.engineDesc') }}</p>

            <div v-if="loadingSettings" class="skeleton-grid" aria-hidden="true">
              <div class="skeleton-card" v-for="n in 4" :key="n"></div>
            </div>
            <p v-else-if="settingsError" class="field-error" role="alert">{{ settingsError }}</p>
            <div v-else class="engine-grid" role="listbox" :aria-label="t('settings.avatar.engineTitle')">
              <button
                v-for="engine in runtime.engines"
                :key="engine.id"
                type="button"
                class="engine-card"
                role="option"
                :aria-selected="selectedEngine === engine.id"
                :aria-disabled="!engine.available && !engine.can_import"
                :disabled="(!engine.available && !engine.can_import) || applyingAvatar || importing"
                :class="{
                  selected: selectedEngine === engine.id,
                  current: runtime.avatar.type === engine.id,
                  unavailable: !engine.available && !engine.can_import
                }"
                @click="selectEngine(engine.id)"
              >
                <span class="card-title">{{ engine.label }}</span>
                <span class="card-desc">{{ engine.description }}</span>
                <span class="card-status" v-if="runtime.avatar.type === engine.id">
                  {{ t('settings.avatar.inUse') }}
                </span>
                <span class="card-status muted" v-else-if="!engine.available">
                  {{ engine.message || t('settings.avatar.unavailable') }}
                </span>
              </button>
            </div>
            </div>

            <!-- 數字人角色 -->
            <div class="settings-section">
            <h4><i class="bi bi-person-bounding-box"></i> {{ t('settings.avatar.characterTitle') }}</h4>
            <p class="section-hint">{{ t('settings.avatar.characterDesc') }}</p>

            <div v-if="filteredCharacters.length" class="character-grid" role="listbox" :aria-label="t('settings.avatar.characterTitle')">
              <button
                v-for="character in filteredCharacters"
                :key="character.id"
                type="button"
                class="character-card"
                role="option"
                :aria-selected="selectedAvatarId === character.id"
                :disabled="applyingAvatar"
                :class="{
                  selected: selectedAvatarId === character.id,
                  current: runtime.avatar.avatar_id === character.id
                }"
                @click="selectCharacter(character.id)"
              >
                <span class="character-thumb">
                  <img
                    v-if="character.preview_url"
                    :src="character.preview_url"
                    :alt="character.label"
                    width="160"
                    height="160"
                    loading="lazy"
                  >
                  <i v-else class="bi bi-person-video3"></i>
                </span>
                <span class="character-meta">
                  <span class="card-title">{{ character.label }}</span>
                  <span class="card-status" v-if="runtime.avatar.avatar_id === character.id">
                    {{ t('settings.avatar.inUse') }}
                  </span>
                </span>
              </button>
            </div>
            <div v-else class="empty-state">
              <i class="bi bi-person-x"></i>
              <p>{{ t('settings.avatar.emptyCharacters') }}</p>
            </div>

            <div class="settings-section quality-section">
              <h4><i class="bi bi-brush"></i> {{ t('settings.quality.title') }}</h4>
              <p class="section-hint">{{ t('settings.quality.desc') }}</p>

              <div class="setting-item">
                <div class="setting-label">
                  <label for="mouth-sharpen">{{ t('settings.quality.sharpen') }}</label>
                  <span id="mouth-sharpen-hint" class="setting-desc">{{ t('settings.quality.sharpenDesc') }}</span>
                </div>
                <div class="setting-control">
                  <input
                    id="mouth-sharpen"
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    v-model.number="qualityDraft.mouth_sharpen"
                    :disabled="applyingQuality || importing"
                    aria-describedby="mouth-sharpen-hint"
                  >
                  <span class="range-value">{{ Number(qualityDraft.mouth_sharpen).toFixed(1) }}</span>
                </div>
              </div>

              <div class="setting-item setting-item-stack">
                <div class="setting-label">
                  <label for="paste-interpolation">{{ t('settings.quality.interpolation') }}</label>
                  <span id="paste-interpolation-hint" class="setting-desc">{{ t('settings.quality.interpolationDesc') }}</span>
                </div>
                <div class="setting-control setting-control-grow">
                  <select
                    id="paste-interpolation"
                    v-model="qualityDraft.paste_interpolation"
                    :disabled="applyingQuality || importing"
                    aria-describedby="paste-interpolation-hint"
                  >
                    <option value="lanczos">{{ t('settings.quality.lanczos') }}</option>
                    <option value="cubic">{{ t('settings.quality.cubic') }}</option>
                    <option value="linear">{{ t('settings.quality.linear') }}</option>
                  </select>
                </div>
              </div>

              <template v-if="selectedEngine === 'musetalk'">
                <div class="setting-item">
                  <div class="setting-label">
                    <label for="bbox-shift">{{ t('settings.quality.bboxShift') }}</label>
                    <span id="bbox-shift-hint" class="setting-desc">{{ t('settings.quality.bboxShiftDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="bbox-shift"
                      type="range"
                      min="-30"
                      max="30"
                      step="1"
                      v-model.number="qualityDraft.musetalk.bbox_shift"
                      :disabled="applyingQuality || importing"
                      aria-describedby="bbox-shift-hint"
                    >
                    <span class="range-value">{{ qualityDraft.musetalk.bbox_shift }}</span>
                  </div>
                </div>

                <div class="setting-item">
                  <div class="setting-label">
                    <label for="extra-margin">{{ t('settings.quality.extraMargin') }}</label>
                    <span id="extra-margin-hint" class="setting-desc">{{ t('settings.quality.extraMarginDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="extra-margin"
                      type="range"
                      min="0"
                      max="40"
                      step="1"
                      v-model.number="qualityDraft.musetalk.extra_margin"
                      :disabled="applyingQuality || importing"
                      aria-describedby="extra-margin-hint"
                    >
                    <span class="range-value">{{ qualityDraft.musetalk.extra_margin }} px</span>
                  </div>
                </div>

                <div class="setting-item setting-item-stack">
                  <div class="setting-label">
                    <label for="parsing-mode">{{ t('settings.quality.parsingMode') }}</label>
                    <span id="parsing-mode-hint" class="setting-desc">{{ t('settings.quality.parsingModeDesc') }}</span>
                  </div>
                  <div class="setting-control setting-control-grow">
                    <select
                      id="parsing-mode"
                      v-model="qualityDraft.musetalk.parsing_mode"
                      :disabled="applyingQuality || importing"
                      aria-describedby="parsing-mode-hint"
                    >
                      <option value="jaw">{{ t('settings.quality.jaw') }}</option>
                      <option value="raw">{{ t('settings.quality.raw') }}</option>
                    </select>
                  </div>
                </div>

                <div class="setting-item">
                  <div class="setting-label">
                    <label for="mask-blur">{{ t('settings.quality.maskBlur') }}</label>
                    <span id="mask-blur-hint" class="setting-desc">{{ t('settings.quality.maskBlurDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="mask-blur"
                      type="range"
                      min="0"
                      max="0.15"
                      step="0.01"
                      v-model.number="qualityDraft.musetalk.mask_blur_ratio"
                      :disabled="applyingQuality || importing"
                      aria-describedby="mask-blur-hint"
                    >
                    <span class="range-value">{{ Number(qualityDraft.musetalk.mask_blur_ratio).toFixed(2) }}</span>
                  </div>
                </div>

                <div class="setting-item">
                  <div class="setting-label">
                    <label for="upper-boundary">{{ t('settings.quality.upperBoundary') }}</label>
                    <span id="upper-boundary-hint" class="setting-desc">{{ t('settings.quality.upperBoundaryDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="upper-boundary"
                      type="range"
                      min="0.3"
                      max="0.7"
                      step="0.05"
                      v-model.number="qualityDraft.musetalk.upper_boundary_ratio"
                      :disabled="applyingQuality || importing"
                      aria-describedby="upper-boundary-hint"
                    >
                    <span class="range-value">{{ Number(qualityDraft.musetalk.upper_boundary_ratio).toFixed(2) }}</span>
                  </div>
                </div>

                <div class="setting-item">
                  <div class="setting-label">
                    <label for="left-cheek">{{ t('settings.quality.leftCheek') }}</label>
                    <span id="left-cheek-hint" class="setting-desc">{{ t('settings.quality.cheekDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="left-cheek"
                      type="range"
                      min="20"
                      max="160"
                      step="5"
                      v-model.number="qualityDraft.musetalk.left_cheek_width"
                      :disabled="applyingQuality || importing"
                      aria-describedby="left-cheek-hint"
                    >
                    <span class="range-value">{{ qualityDraft.musetalk.left_cheek_width }}</span>
                  </div>
                </div>

                <div class="setting-item">
                  <div class="setting-label">
                    <label for="right-cheek">{{ t('settings.quality.rightCheek') }}</label>
                    <span id="right-cheek-hint" class="setting-desc">{{ t('settings.quality.cheekDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="right-cheek"
                      type="range"
                      min="20"
                      max="160"
                      step="5"
                      v-model.number="qualityDraft.musetalk.right_cheek_width"
                      :disabled="applyingQuality || importing"
                      aria-describedby="right-cheek-hint"
                    >
                    <span class="range-value">{{ qualityDraft.musetalk.right_cheek_width }}</span>
                  </div>
                </div>
              </template>

              <template v-else-if="selectedEngine === 'wav2lip'">
                <div class="setting-item">
                  <div class="setting-label">
                    <label for="wav2lip-pad-bottom">{{ t('settings.quality.padBottom') }}</label>
                    <span id="wav2lip-pad-bottom-hint" class="setting-desc">{{ t('settings.quality.padBottomDesc') }}</span>
                  </div>
                  <div class="setting-control">
                    <input
                      id="wav2lip-pad-bottom"
                      type="range"
                      min="0"
                      max="40"
                      step="1"
                      v-model.number="qualityDraft.wav2lip.pad_bottom"
                      :disabled="applyingQuality || importing"
                      aria-describedby="wav2lip-pad-bottom-hint"
                    >
                    <span class="range-value">{{ qualityDraft.wav2lip.pad_bottom }} px</span>
                  </div>
                </div>
              </template>

              <p class="field-hint">{{ t('settings.quality.rebuildHint') }}</p>
              <p v-if="qualityError" class="field-error" role="alert">{{ qualityError }}</p>

              <button
                class="btn-apply"
                type="button"
                :disabled="!qualityDirty || applyingQuality || importing"
                @click="handleApplyMouthQuality"
              >
                <i class="bi bi-hourglass-split spin" v-if="applyingQuality"></i>
                <i class="bi bi-check-lg" v-else></i>
                {{ applyingQuality ? t('settings.quality.applying') : t('settings.quality.apply') }}
              </button>
            </div>

            <div class="import-card">
              <div class="setting-label">
                <label for="avatar-import-file">{{ t('settings.import.title') }}</label>
                <span class="setting-desc">{{ t('settings.import.desc') }}</span>
              </div>
              <p class="section-hint">
                {{ t('settings.import.engineHint') }}
                <strong>{{ selectedEngineLabel }}</strong>
              </p>

              <div
                class="dropzone"
                :class="{ disabled: !canImportSelected, dragging: importDragging }"
                @dragover.prevent="onImportDragOver"
                @dragleave.prevent="importDragging = false"
                @drop.prevent="onImportDrop"
              >
                <input
                  id="avatar-import-file"
                  ref="importFileInput"
                  type="file"
                  accept="video/mp4,video/quicktime,video/webm,video/x-msvideo,.mp4,.mov,.webm,.avi"
                  :disabled="!canImportSelected || importing"
                  @change="onImportFileChange"
                >
                <i class="bi bi-cloud-arrow-up"></i>
                <p v-if="importFile">{{ importFile.name }}</p>
                <p v-else>{{ t('settings.import.dropHint') }}</p>
                <button
                  class="btn-secondary pick-file-btn"
                  type="button"
                  :disabled="!canImportSelected || importing"
                  @click="importFileInput?.click()"
                >
                  {{ t('settings.import.pickFile') }}
                </button>
              </div>

              <div class="setting-item setting-item-stack">
                <div class="setting-label">
                  <label for="import-avatar-id">{{ t('settings.import.roleName') }}</label>
                  <span class="setting-desc">{{ t('settings.import.roleNameDesc') }}</span>
                </div>
                <div class="setting-control setting-control-grow">
                  <input
                    id="import-avatar-id"
                    type="text"
                    v-model="importAvatarId"
                    :placeholder="importNamePlaceholder"
                    :disabled="!canImportSelected || importing"
                    autocomplete="off"
                  >
                </div>
              </div>

              <p v-if="!canImportSelected" class="field-hint warning-hint">
                {{ t('settings.import.unsupported') }}
              </p>
              <p v-else-if="isConnected" class="field-hint warning-hint">
                {{ t('settings.import.needDisconnect') }}
              </p>

              <div v-if="importJob && importing" class="import-progress" role="status" aria-live="polite">
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: `${importJob.progress || 0}%` }"></div>
                </div>
                <p>{{ importJob.message || t('settings.import.working') }} · {{ importJob.progress || 0 }}%</p>
              </div>
              <p v-if="importError" class="field-error" role="alert">{{ importError }}</p>

              <button
                class="btn-apply"
                type="button"
                :disabled="!canStartImport"
                @click="handleImportCharacter"
              >
                <i class="bi bi-hourglass-split spin" v-if="importing"></i>
                <i class="bi bi-plus-circle" v-else></i>
                {{ importing ? t('settings.import.working') : t('settings.import.start') }}
              </button>
            </div>

            <p v-if="isConnected && avatarDirty" class="field-hint warning-hint">
              {{ t('settings.avatar.needDisconnect') }}
            </p>

            <button
              class="btn-apply"
              type="button"
              :disabled="!avatarDirty || applyingAvatar || importing || !selectedEngine || !selectedAvatarId"
              @click="handleApplyAvatar"
            >
              <i class="bi bi-hourglass-split spin" v-if="applyingAvatar"></i>
              <i class="bi bi-person-check" v-else></i>
              {{ applyingAvatar ? t('settings.avatar.applying') : t('settings.avatar.apply') }}
            </button>
            </div>
          </section>

          <section
            v-show="activeSettingsTab === 'experience'"
            id="settings-panel-experience"
            class="settings-tab-panel"
            role="tabpanel"
            aria-labelledby="settings-tab-experience"
            tabindex="0"
          >
            <!-- 錄製設定 -->
            <div class="settings-section">
            <h4><i class="bi bi-record-circle"></i> {{ t('settings.recording.title') }}</h4>
            
            <div class="setting-item">
              <div class="setting-label">
                <label for="auto-record">{{ t('settings.recording.autoRecord') }}</label>
                <span class="setting-desc">{{ t('settings.recording.autoRecordDesc') }}</span>
              </div>
              <div class="setting-control">
                <label class="switch">
                  <input type="checkbox" id="auto-record" v-model="settings.autoRecord">
                  <span class="slider"></span>
                </label>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="record-format">{{ t('settings.recording.format') }}</label>
              </div>
              <div class="setting-control">
                <select v-model="settings.recordFormat" id="record-format">
                  <option value="mp4">MP4 (H.264)</option>
                  <option value="webm">WebM (VP8)</option>
                  <option value="avi">AVI</option>
                </select>
              </div>
            </div>
            </div>

            <!-- 介面設定 -->
            <div class="settings-section">
            <h4><i class="bi bi-palette"></i> {{ t('settings.display.title') }}</h4>
            
            <div class="setting-item">
              <div class="setting-label">
                <label for="show-debug">{{ t('settings.display.showDebug') }}</label>
                <span class="setting-desc">{{ t('settings.display.showDebugDesc') }}</span>
              </div>
              <div class="setting-control">
                <label class="switch">
                  <input type="checkbox" id="show-debug" v-model="settings.showDebugPanel">
                  <span class="slider"></span>
                </label>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="show-timestamp">{{ t('settings.display.showTimestamp') }}</label>
                <span class="setting-desc">{{ t('settings.display.showTimestampDesc') }}</span>
              </div>
              <div class="setting-control">
                <label class="switch">
                  <input type="checkbox" id="show-timestamp" v-model="settings.showTimestamp">
                  <span class="slider"></span>
                </label>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="theme">{{ t('settings.display.theme') }}</label>
              </div>
              <div class="setting-control">
                <select v-model="settings.theme" id="theme">
                  <option value="dark">{{ t('settings.display.themeDark') }}</option>
                  <option value="light">{{ t('settings.display.themeLight') }}</option>
                  <option value="auto">{{ t('settings.display.themeAuto') }}</option>
                </select>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="ui-language">{{ t('settings.display.language') }}</label>
              </div>
              <div class="setting-control">
                <select v-model="settings.uiLanguage" id="ui-language">
                  <option value="zh-TW">{{ t('settings.display.langZhTW') }}</option>
                  <option value="en-US">{{ t('settings.display.langEnUS') }}</option>
                </select>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="video-size">{{ t('settings.display.videoSize') }}</label>
                <span class="setting-desc">{{ t('settings.display.videoSizeDesc') }}</span>
              </div>
              <div class="setting-control setting-range">
                <input 
                  type="range" 
                  id="video-size" 
                  v-model="settings.videoSize"
                  min="50" 
                  max="150"
                  step="5"
                >
                <span class="range-value">{{ settings.videoSize }}%</span>
              </div>
            </div>
            </div>
          </section>

          <section
            v-show="activeSettingsTab === 'voice'"
            id="settings-panel-voice"
            class="settings-tab-panel"
            role="tabpanel"
            aria-labelledby="settings-tab-voice"
            tabindex="0"
          >
            <!-- 語音設定 -->
            <div class="settings-section">
            <h4><i class="bi bi-mic"></i> {{ t('settings.voice.title') }}</h4>
            
            <div class="setting-item info-banner">
              <div class="info-content">
                <i class="bi bi-info-circle"></i>
                <div>
                  <strong>{{ t('settings.voice.currentMode') }}</strong>
                  <p>{{ t('settings.voice.currentModeDesc') }}</p>
                  <p class="note">{{ t('settings.voice.currentModeNote') }}</p>
                </div>
              </div>
            </div>
            
            </div>

            <!-- STT -->
            <div class="settings-section">
              <h4><i class="bi bi-chat-square-text"></i> {{ t('settings.speech.sttTitle') }}</h4>
              <p class="section-hint">{{ t('settings.speech.sttDesc') }}</p>

              <div class="setting-item">
                <div class="setting-label">
                  <label for="stt-engine">{{ t('settings.speech.engine') }}</label>
                </div>
                <div class="setting-control">
                  <select id="stt-engine" v-model="sttDraft.type" :disabled="applyingStt">
                    <option
                      v-for="engine in speech.stt.engines"
                      :key="engine.id"
                      :value="engine.id"
                      :disabled="!engine.available"
                    >
                      {{ engine.label }}{{ engine.available ? '' : ` — ${engine.message}` }}
                    </option>
                  </select>
                </div>
              </div>

              <div class="setting-item">
                <div class="setting-label"><label for="stt-model">{{ t('settings.speech.model') }}</label></div>
                <div class="setting-control">
                  <select id="stt-model" v-model="sttDraft.model_size" :disabled="applyingStt">
                    <option v-for="model in sttModelOptions" :key="model" :value="model">{{ model }}</option>
                  </select>
                </div>
              </div>

              <div class="setting-item">
                <div class="setting-label"><label for="stt-language">{{ t('settings.speech.language') }}</label></div>
                <div class="setting-control">
                  <select id="stt-language" v-model="sttDraft.language" :disabled="applyingStt">
                    <option value="zh">{{ t('settings.speech.zh') }}</option>
                    <option value="en">English</option>
                    <option value="auto">{{ t('settings.speech.auto') }}</option>
                  </select>
                </div>
              </div>

              <div v-if="sttDraft.type === 'funasr'" class="setting-item">
                <div class="setting-label">
                  <label for="stt-output-script">{{ t('settings.speech.outputScript') }}</label>
                  <span class="setting-desc">{{ t('settings.speech.outputScriptDesc') }}</span>
                </div>
                <div class="setting-control">
                  <select
                    id="stt-output-script"
                    v-model="sttDraft.output_script"
                    :disabled="applyingStt"
                  >
                    <option value="traditional-tw">{{ t('settings.speech.traditionalTw') }}</option>
                    <option value="simplified">{{ t('settings.speech.simplified') }}</option>
                  </select>
                </div>
              </div>

              <div class="setting-item">
                <div class="setting-label"><label for="stt-device">{{ t('settings.speech.device') }}</label></div>
                <div class="setting-control">
                  <select id="stt-device" v-model="sttDraft.device" :disabled="applyingStt">
                    <option value="auto">{{ t('settings.speech.auto') }}</option>
                    <option value="cuda">CUDA</option>
                    <option value="cpu">CPU</option>
                  </select>
                </div>
              </div>

              <p v-if="speechError" class="inline-error" role="alert">{{ speechError }}</p>
              <div
                v-if="applyingStt"
                class="stt-prewarm-progress"
                role="status"
                aria-live="polite"
              >
                <div
                  class="progress-track"
                  role="progressbar"
                  :aria-label="t('settings.speech.prewarmProgressLabel')"
                  :aria-valuetext="t('settings.speech.prewarming')"
                >
                  <div class="progress-fill progress-fill-indeterminate"></div>
                </div>
                <p>
                  {{ speech.stt.local_model_ready && sttDraft.type === 'funasr'
                    ? t('settings.speech.localPrewarmProgressHint')
                    : t('settings.speech.prewarmProgressHint') }}
                </p>
              </div>
              <button
                class="btn-apply"
                type="button"
                :disabled="!sttDirty || applyingStt"
                @click="handleApplySpeech('stt')"
              >
                <i :class="applyingStt ? 'bi bi-hourglass-split spin' : 'bi bi-check-lg'"></i>
                {{ applyingStt ? t('settings.speech.prewarming') : t('settings.speech.applyStt') }}
              </button>
            </div>

            <!-- Silero VAD：伺服器端語音端點偵測 -->
            <div class="settings-section">
            <h4><i class="bi bi-soundwave"></i> {{ t('settings.vad.title') }}</h4>
            <p class="section-hint">{{ t('settings.vad.desc') }}</p>

            <div class="setting-item info-banner">
              <div class="info-content">
                <i class="bi bi-info-circle"></i>
                <div>
                  <strong>{{ t('settings.vad.purposeTitle') }}</strong>
                  <p>{{ t('settings.vad.purpose') }}</p>
                </div>
              </div>
            </div>

            <div
              class="setting-item info-banner"
              :class="{ 'status-ok': vad.effective, 'status-error': vadError }"
            >
              <div class="info-content">
                <i :class="vad.effective ? 'bi bi-check-circle' : 'bi bi-exclamation-circle'"></i>
                <div>
                  <strong>
                    {{ vad.effective ? t('settings.vad.statusActive') : t('settings.vad.statusInactive') }}
                    · Silero VAD
                  </strong>
                  <p v-if="!vad.enabled">{{ t('settings.vad.hintDisabled') }}</p>
                  <p v-else-if="vad.asr_mode === 'browser'">{{ t('settings.vad.hintBrowser') }}</p>
                  <p v-else>{{ t('settings.vad.hintServer') }}</p>
                  <p v-if="vadError" class="note" role="alert">{{ vadError }}</p>
                </div>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="vad-enabled">{{ t('settings.vad.enabled') }}</label>
                <span class="setting-desc">{{ t('settings.vad.enabledDesc') }}</span>
              </div>
              <div class="setting-control">
                <label class="switch">
                  <input
                    type="checkbox"
                    id="vad-enabled"
                    v-model="vadDraft.enabled"
                    :disabled="applyingVad"
                    @change="handleApplyVad"
                  >
                  <span class="slider"></span>
                </label>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="vad-threshold">{{ t('settings.vad.threshold') }}</label>
                <span class="setting-desc">{{ t('settings.vad.thresholdDesc') }}</span>
              </div>
              <div class="setting-control">
                <input
                  type="range"
                  id="vad-threshold"
                  v-model.number="vadDraft.threshold"
                  min="0.1"
                  max="0.95"
                  step="0.05"
                  :disabled="applyingVad"
                >
                <span class="range-value">{{ Number(vadDraft.threshold).toFixed(2) }}</span>
              </div>
            </div>

            <div class="setting-item">
              <div class="setting-label">
                <label for="vad-silence">{{ t('settings.vad.minSilence') }}</label>
                <span class="setting-desc">{{ t('settings.vad.minSilenceDesc') }}</span>
              </div>
              <div class="setting-control">
                <input
                  type="range"
                  id="vad-silence"
                  v-model.number="vadDraft.min_silence_ms"
                  min="100"
                  max="2000"
                  step="50"
                  :disabled="applyingVad"
                >
                <span class="range-value">{{ vadDraft.min_silence_ms }} ms</span>
              </div>
            </div>

            <button
              class="btn-apply"
              type="button"
              :disabled="!vadDirty || applyingVad"
              @click="handleApplyVad"
            >
              <i class="bi bi-hourglass-split spin" v-if="applyingVad"></i>
              <i class="bi bi-check-lg" v-else></i>
              {{ applyingVad ? t('settings.vad.applying') : t('settings.vad.apply') }}
            </button>
            </div>

            <!-- TTS -->
            <div class="settings-section">
              <h4><i class="bi bi-volume-up"></i> {{ t('settings.speech.ttsTitle') }}</h4>
              <p class="section-hint">{{ t('settings.speech.ttsDesc') }}</p>

              <div class="setting-item">
                <div class="setting-label"><label for="tts-engine">{{ t('settings.speech.engine') }}</label></div>
                <div class="setting-control">
                  <select id="tts-engine" v-model="ttsDraft.type" :disabled="applyingTts">
                    <option
                      v-for="engine in speech.tts.engines"
                      :key="engine.id"
                      :value="engine.id"
                      :disabled="!engine.available"
                    >
                      {{ engine.label }}{{ engine.available ? '' : ` — ${engine.message}` }}
                    </option>
                  </select>
                </div>
              </div>

              <div v-if="ttsDraft.type === 'edgetts'" class="setting-item setting-item-stack">
                <div class="setting-label">
                  <label for="edge-tts-voice">{{ t('settings.speech.voice') }}</label>
                  <span id="edge-tts-voice-hint" class="setting-desc">
                    {{ t('settings.speech.edgeVoiceDesc') }}
                  </span>
                </div>
                <div class="setting-control setting-control-grow">
                  <select
                    id="edge-tts-voice"
                    v-model="ttsDraft.ref_file"
                    :disabled="applyingTts || !speech.tts.edge_voices.length"
                    aria-describedby="edge-tts-voice-hint"
                  >
                    <option
                      v-for="voice in speech.tts.edge_voices"
                      :key="voice.id"
                      :value="voice.id"
                    >
                      {{ voice.name }} · {{ t(`settings.speech.${voice.gender}`) }} — {{ voice.id }}
                    </option>
                  </select>
                </div>
              </div>

              <div v-else class="setting-item setting-item-stack">
                <div class="setting-label">
                  <label for="tts-reference">{{ t('settings.speech.reference') }}</label>
                  <span id="tts-reference-hint" class="setting-desc">
                    {{ t('settings.speech.referencePathDesc') }}
                  </span>
                </div>
                <div class="setting-control setting-control-grow">
                  <input
                    id="tts-reference"
                    v-model.trim="ttsDraft.ref_file"
                    type="text"
                    :placeholder="t('settings.speech.referencePathPlaceholder')"
                    :disabled="applyingTts"
                    aria-describedby="tts-reference-hint"
                  >
                </div>
              </div>

              <template v-if="ttsDraft.type !== 'edgetts'">
                <div class="setting-item">
                  <div class="setting-label"><label for="tts-server">{{ t('settings.speech.server') }}</label></div>
                  <div class="setting-control">
                    <input id="tts-server" v-model.trim="ttsDraft.tts_server" type="url" :disabled="applyingTts">
                  </div>
                </div>
                <div class="setting-item">
                  <div class="setting-label"><label for="tts-ref-text">{{ t('settings.speech.referenceText') }}</label></div>
                  <div class="setting-control">
                    <input id="tts-ref-text" v-model.trim="ttsDraft.ref_text" type="text" :disabled="applyingTts">
                  </div>
                </div>
              </template>

              <button
                class="btn-apply"
                type="button"
                :disabled="!ttsDirty || applyingTts"
                @click="handleApplySpeech('tts')"
              >
                <i :class="applyingTts ? 'bi bi-hourglass-split spin' : 'bi bi-check-lg'"></i>
                {{ applyingTts ? t('settings.speech.applying') : t('settings.speech.applyTts') }}
              </button>
            </div>
          </section>
        </div>

        <div class="settings-footer">
          <button class="btn-secondary" @click="confirmKind = 'reset'">
            <i class="bi bi-arrow-counterclockwise"></i>
            {{ t('settings.resetDefault') }}
          </button>
          <button class="btn-primary" @click="saveSettings">
            <i class="bi bi-check-lg"></i>
            {{ t('settings.save') }}
          </button>
        </div>
      </div>
    </transition>

    <!-- 確認對話方塊 -->
    <transition name="fade">
      <div v-if="confirmKind" class="confirm-dialog-overlay" @click="confirmKind = ''">
        <div class="confirm-dialog" @click.stop role="dialog" aria-modal="true">
          <div class="confirm-header">
            <i class="bi bi-exclamation-triangle"></i>
            <h4>{{ confirmDialogTitle }}</h4>
          </div>
          <div class="confirm-body">
            {{ confirmDialogMessage }}
          </div>
          <div class="confirm-footer">
            <button class="btn-secondary" @click="confirmKind = ''">{{ t('settings.cancel') }}</button>
            <button
              :class="confirmKind === 'reset' ? 'btn-danger' : 'btn-primary'"
              @click="confirmAction"
            >
              {{ t('settings.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- 遮罩層 -->
    <transition name="fade">
      <div v-if="showSettings" class="settings-overlay" @click="showSettings = false"></div>
    </transition>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useI18n } from '../composables/useI18n'
import { useRuntimeSettings } from '../composables/useRuntimeSettings'

const { t } = useI18n()
const showSettings = ref(false)
const confirmKind = ref('')
const activeSettingsTab = ref('ai')
const settingsContentRef = ref(null)

const settingsTabs = computed(() => [
  { id: 'ai', icon: 'bi bi-cpu', label: t('settings.tabs.ai') },
  { id: 'avatar', icon: 'bi bi-person-video3', label: t('settings.tabs.avatar') },
  { id: 'voice', icon: 'bi bi-mic', label: t('settings.tabs.voice') },
  { id: 'experience', icon: 'bi bi-sliders2', label: t('settings.tabs.experience') }
])

const props = defineProps({
  isConnected: {
    type: Boolean,
    default: false
  }
})

const {
  runtime,
  ollama,
  llamacpp,
  selectedProvider,
  currentProviderModels,
  loadingSettings,
  loadingModels,
  applyingLlm,
  applyingAvatar,
  applyMouthQuality,
  qualityDraft,
  qualityDirty,
  applyingQuality,
  qualityError,
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
  loadRuntimeSettings,
  loadOllamaModels,
  applyLlmModel,
  selectProvider,
  applyAvatar,
  importCharacter,
  importing,
  importJob,
  importError,
  selectEngine,
  selectCharacter,
  vad,
  vadDraft,
  vadDirty,
  vadError,
  applyingVad,
  applyVadSettings,
  speech,
  sttDraft,
  ttsDraft,
  sttDirty,
  sttModelOptions,
  ttsDirty,
  applyingStt,
  applyingTts,
  speechError,
  applySttSettings,
  applyTtsSettings
} = useRuntimeSettings()

const currentVadLabel = computed(() => 'Silero VAD')

const activeLlmBackend = computed(() => {
  return selectedProvider.value === 'llamacpp' ? llamacpp : ollama
})

const llmStatusTitle = computed(() => {
  if (selectedProvider.value === 'llamacpp') {
    if (llamacpp.server_running) return t('settings.llm.llamacppRunning')
    if (llamacpp.reachable) return t('settings.llm.llamacppReady')
    return t('settings.llm.llamacppMissing')
  }
  return ollama.reachable ? t('settings.llm.connected') : t('settings.llm.disconnected')
})

const currentEngineLabel = computed(() => {
  const engine = runtime.engines.find((item) => item.id === runtime.avatar.type)
  return engine ? engine.label : (runtime.avatar.type || '—')
})

const selectedEngineMeta = computed(() => {
  return runtime.engines.find((item) => item.id === selectedEngine.value) || null
})

const selectedEngineLabel = computed(() => {
  return selectedEngineMeta.value?.label || selectedEngine.value || '—'
})

const canImportSelected = computed(() => Boolean(selectedEngineMeta.value?.can_import))

const importFile = ref(null)
const importAvatarId = ref('')
const importDragging = ref(false)
const importFileInput = ref(null)

const importNamePlaceholder = computed(() => {
  const engine = selectedEngine.value || 'avatar'
  return `${engine}_custom`
})

const canStartImport = computed(() => {
  return canImportSelected.value && !!importFile.value && !importing.value && !applyingAvatar.value
})

const confirmDialogTitle = computed(() => {
  if (confirmKind.value === 'avatar') return t('settings.avatar.confirmTitle')
  if (confirmKind.value === 'stt' || confirmKind.value === 'tts') {
    return t('settings.speech.confirmTitle')
  }
  return t('settings.confirmTitle')
})

const confirmDialogMessage = computed(() => {
  if (confirmKind.value === 'avatar') return t('settings.avatar.confirmMessage')
  if (confirmKind.value === 'stt' || confirmKind.value === 'tts') {
    return t('settings.speech.confirmMessage')
  }
  return t('settings.confirmMessage')
})

// 預設設定
const defaultSettings = {
  // WebRTC：預設關閉 STUN，本機直連
  useStun: false,
  stunServer: 'stun:stun.miwifi.com:3478',
  customStunServer: '',
  
  // 錄製
  autoRecord: false,
  recordFormat: 'mp4',
  
  // 介面
  showDebugPanel: false,
  showTimestamp: true,
  theme: 'dark',
  uiLanguage: 'zh-TW',
  videoSize: 100,
  
  // 語音引擎由伺服器執行時設定管理
}

const settings = ref({ ...defaultSettings })

// 定義事件
const emit = defineEmits(['settings-changed', 'notification', 'request-disconnect', 'avatar-ready'])

const toggleSettings = () => {
  showSettings.value = !showSettings.value
}

const selectSettingsTab = (tabId) => {
  if (!settingsTabs.value.some((tab) => tab.id === tabId)) return
  activeSettingsTab.value = tabId
  if (settingsContentRef.value) settingsContentRef.value.scrollTop = 0
}

const handleTabKeydown = (event, currentIndex) => {
  const lastIndex = settingsTabs.value.length - 1
  let nextIndex = currentIndex
  if (event.key === 'ArrowRight') nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1
  else if (event.key === 'ArrowLeft') nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1
  else if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = lastIndex
  else return

  event.preventDefault()
  const nextTab = settingsTabs.value[nextIndex]
  selectSettingsTab(nextTab.id)
  document.getElementById(`settings-tab-${nextTab.id}`)?.focus()
}

const formatOllamaOption = (model) => {
  const extras = [model.parameter_size, model.size_label].filter(Boolean)
  return extras.length ? `${model.name} · ${extras.join(' · ')}` : model.name
}

const refreshOllama = async () => {
  try {
    await loadOllamaModels()
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplyVad = async () => {
  try {
    vadDraft.type = 'silero'
    const data = await applyVadSettings()
    if (data.warmup_error) {
      emit('notification', data.warmup_error, 'warning')
      return
    }
    emit('notification', `${t('notifications.vadSwitched')}: ${currentVadLabel.value}`, 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const applySpeechChange = async (kind) => {
  try {
    if (props.isConnected) {
      emit('request-disconnect')
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    const apply = kind === 'stt' ? applySttSettings : applyTtsSettings
    try {
      await apply()
    } catch (error) {
      if (!error.payload?.need_disconnect) throw error
      await new Promise((resolve) => setTimeout(resolve, 750))
      await apply()
    }
    if (kind === 'stt') {
      emit('notification', t('settings.speech.sttApplied'), 'success')
    } else {
      emit('notification', t('settings.speech.ttsApplied'), 'success')
    }
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplySpeech = (kind) => {
  if (props.isConnected) {
    confirmKind.value = kind
    return
  }
  applySpeechChange(kind)
}

const handleApplyLlm = async () => {
  try {
    await applyLlmModel()
    emit('notification', t('notifications.llmSettingsUpdated'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplyAvatar = () => {
  if (props.isConnected) {
    confirmKind.value = 'avatar'
    return
  }
  applyAvatarChange()
}

const applyAvatarChange = async () => {
  try {
    if (props.isConnected) {
      emit('request-disconnect')
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    await applyAvatar()
    emit('avatar-ready')
    emit('notification', t('notifications.avatarSwitched'), 'success')
  } catch (error) {
    if (error.status === 409 && error.payload?.need_disconnect) {
      emit('request-disconnect')
      emit('notification', t('settings.avatar.needDisconnect'), 'warning')
      return
    }
    emit('notification', error.message, 'error')
  }
}

const confirmAction = () => {
  const kind = confirmKind.value
  confirmKind.value = ''
  if (kind === 'reset') {
    resetSettings()
  } else if (kind === 'avatar') {
    applyAvatarChange()
  } else if (kind === 'stt' || kind === 'tts') {
    applySpeechChange(kind)
  }
}

const loadRuntimePanel = async () => {
  try {
    await Promise.all([loadRuntimeSettings(), loadOllamaModels()])
    vadDraft.type = 'silero'
    if (vad.type !== 'silero' || (vad.enabled && vad.asr_mode !== 'server')) {
      await applyVadSettings()
    }
  } catch (error) {
    console.error('Failed to load runtime settings:', error)
  }
}

const onImportDragOver = () => {
  if (canImportSelected.value && !importing.value) {
    importDragging.value = true
  }
}

const onImportDrop = (event) => {
  importDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) importFile.value = file
}

const onImportFileChange = (event) => {
  const file = event.target.files?.[0]
  importFile.value = file || null
}

const handleApplyMouthQuality = async () => {
  try {
    await applyMouthQuality()
    emit('notification', t('notifications.qualityApplied'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleImportCharacter = async () => {
  if (!canStartImport.value) return
  try {
    if (props.isConnected) {
      emit('request-disconnect')
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    const result = await importCharacter({
      file: importFile.value,
      engine: selectedEngine.value,
      avatarId: importAvatarId.value.trim()
    })
    await loadRuntimeSettings()
    selectedEngine.value = result.engine
    selectedAvatarId.value = result.avatar_id
    importFile.value = null
    importAvatarId.value = ''
    if (importFileInput.value) importFileInput.value.value = ''
    emit('notification', t('notifications.avatarImported'), 'success')
  } catch (error) {
    if (error.status === 409 && error.payload?.need_disconnect) {
      emit('request-disconnect')
      emit('notification', t('settings.import.needDisconnect'), 'warning')
      return
    }
    emit('notification', error.message, 'error')
  }
}

const persistLocalSettings = () => {
  localStorage.setItem('linly-talker-stream-settings', JSON.stringify(settings.value))
  emit('settings-changed', settings.value)
}

const saveSettings = () => {
  persistLocalSettings()
  showSettings.value = false
  emit('notification', t('notifications.settingsSaved'), 'success')
}

const resetSettings = () => {
  settings.value = { ...defaultSettings }
  localStorage.removeItem('linly-talker-stream-settings')
  emit('settings-changed', settings.value)
  emit('notification', t('notifications.settingsReset'), 'success')
}

const migrateLocalSettings = (saved) => {
  const next = { ...defaultSettings, ...saved }
  if (next.uiLanguage === 'zh-CN' || next.uiLanguage === 'zh') {
    next.uiLanguage = 'zh-TW'
  }
  const clearedKey = 'linly-talker-stream-webrtc-cleared-v1'
  if (!localStorage.getItem(clearedKey)) {
    next.useStun = false
    next.customStunServer = ''
    next.stunServer = defaultSettings.stunServer
    localStorage.setItem(clearedKey, '1')
  }
  return next
}

onMounted(() => {
  const savedSettings = localStorage.getItem('linly-talker-stream-settings')
  if (savedSettings) {
    try {
      settings.value = migrateLocalSettings(JSON.parse(savedSettings))
      persistLocalSettings()
    } catch (e) {
      console.error('Failed to load settings:', e)
      emit('settings-changed', settings.value)
    }
  } else {
    localStorage.setItem('linly-talker-stream-webrtc-cleared-v1', '1')
    persistLocalSettings()
  }
})

watch(showSettings, (open) => {
  if (open) {
    loadRuntimePanel()
  }
})

// 監聽設定變化，自動儲存
watch(settings, () => {
  emit('settings-changed', settings.value)
}, { deep: true })
</script>

<style scoped>
.settings-wrapper {
  position: relative;
}

.settings-trigger {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 600;
}

.settings-trigger:hover {
  background: var(--primary);
  border-color: var(--primary);
  transform: translateY(-2px);
}

.settings-trigger.active {
  background: var(--primary);
  border-color: var(--primary);
}

.settings-trigger i {
  font-size: 1.125rem;
}

.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 999;
}

.settings-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: min(560px, 100vw);
  height: 100vh;
  height: 100dvh;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  z-index: 1000;
  display: flex;
  flex-direction: column;
}

.settings-header {
  flex-shrink: 0;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-tertiary);
}

.settings-header h3 {
  margin: 0;
  font-size: 1.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.close-btn {
  width: 44px;
  height: 44px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.settings-tabs {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  overflow-x: auto;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  scrollbar-width: none;
}

.settings-tabs::-webkit-scrollbar {
  display: none;
}

.settings-tab {
  position: relative;
  min-width: 0;
  min-height: 48px;
  padding: 0.625rem 0.5rem;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  touch-action: manipulation;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  font: inherit;
  font-size: 0.8125rem;
  font-weight: 600;
  white-space: nowrap;
  transition: color 0.2s ease, background 0.2s ease, border-color 0.2s ease;
}

.settings-tab:hover {
  color: var(--text-primary);
  background: var(--bg-secondary);
}

.settings-tab.active {
  color: var(--primary-light);
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.35);
}

.settings-tab.active::after {
  content: '';
  position: absolute;
  right: 0.75rem;
  bottom: 0.25rem;
  left: 0.75rem;
  height: 2px;
  border-radius: 999px;
  background: var(--primary-light);
}

.settings-tab i {
  flex-shrink: 0;
  font-size: 1rem;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}

.settings-tab-panel {
  animation: settings-tab-enter 0.2s ease-out;
}

.settings-tab-panel:focus-visible {
  outline: 2px solid var(--primary-light);
  outline-offset: 4px;
  border-radius: 10px;
}

.settings-section {
  margin-bottom: 2rem;
}

.settings-tab-panel > .settings-section:last-child {
  margin-bottom: 0;
}

.settings-tab-panel > .settings-section + .settings-section {
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
}

.quality-section {
  margin: 1.5rem 0 0;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
}

.settings-section h4 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 1rem 0;
  color: var(--primary-light);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  background: var(--bg-tertiary);
  border-radius: 8px;
  margin-bottom: 0.75rem;
}

.setting-label {
  flex: 1;
}

.setting-label label {
  display: block;
  font-weight: 500;
  margin-bottom: 0.25rem;
  color: var(--text-primary);
}

.setting-desc {
  display: block;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.setting-control {
  margin-left: 1rem;
}

.setting-control select,
.setting-control input[type="text"],
.setting-control input[type="number"],
.setting-control textarea {
  padding: 0.5rem 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.875rem;
  min-width: 150px;
}

.setting-control select:focus,
.setting-control input[type="text"]:focus,
.setting-control input[type="number"]:focus,
.setting-control textarea:focus {
  outline: none;
  border-color: var(--primary);
}

/* Range Slider */
.setting-range {
  display: flex;
  align-items: center;
  gap: 1rem;
  min-width: 200px;
}

.setting-control input[type="range"] {
  flex: 1;
  height: 6px;
  background: var(--bg-secondary);
  border-radius: 3px;
  outline: none;
  -webkit-appearance: none;
}

.setting-control input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  background: var(--primary);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.setting-control input[type="range"]::-webkit-slider-thumb:hover {
  transform: scale(1.2);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.2);
}

.setting-control input[type="range"]::-moz-range-thumb {
  width: 16px;
  height: 16px;
  background: var(--primary);
  border-radius: 50%;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.setting-control input[type="range"]::-moz-range-thumb:hover {
  transform: scale(1.2);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.2);
}

.range-value {
  font-size: 0.875rem;
  color: var(--primary);
  font-weight: 600;
  min-width: 45px;
  text-align: right;
}

/* Toggle Switch */
.switch {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 26px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--bg-secondary);
  border: 2px solid var(--border);
  transition: 0.3s;
  border-radius: 26px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 2px;
  bottom: 2px;
  background: var(--text-muted);
  transition: 0.3s;
  border-radius: 50%;
}

input:checked + .slider {
  background: var(--primary);
  border-color: var(--primary);
}

input:checked + .slider:before {
  transform: translateX(22px);
  background: white;
}

.settings-footer {
  padding: 1.5rem;
  border-top: 1px solid var(--border);
  display: flex;
  gap: 1rem;
  background: var(--bg-tertiary);
}

.settings-footer button {
  flex: 1;
  min-height: 44px;
  padding: 0.75rem;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border);
}

.btn-secondary:hover {
  background: var(--bg-tertiary);
}

.btn-primary {
  background: var(--primary);
  color: white;
}

.btn-primary:hover {
  background: var(--primary-dark);
}

/* 動畫 */
.slide-fade-enter-active {
  transition: all 0.3s ease;
}

.slide-fade-leave-active {
  transition: all 0.3s ease;
}

.slide-fade-enter-from,
.slide-fade-leave-to {
  transform: translateX(100%);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes settings-tab-enter {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 捲軸 */
.settings-content::-webkit-scrollbar {
  width: 6px;
}

.settings-content::-webkit-scrollbar-track {
  background: var(--bg-secondary);
}

.settings-content::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}

/* 資訊提示框 */
.info-banner {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(139, 92, 246, 0.1));
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
}

.info-content {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  flex: 1;
}

.info-content > i {
  font-size: 1.25rem;
  color: var(--primary-light);
  flex-shrink: 0;
  margin-top: 2px;
}

.info-content strong {
  display: block;
  color: var(--primary-light);
  margin-bottom: 0.5rem;
  font-size: 0.95rem;
}

.info-content p {
  margin: 0.25rem 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

.info-content .note {
  color: var(--warning);
  font-size: 0.8rem;
  margin-top: 0.5rem;
}

.settings-content::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

.runtime-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 36px;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 0.8125rem;
}

.section-hint {
  margin: -0.25rem 0 0.85rem;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--text-muted);
}

.setting-item-stack {
  align-items: flex-start;
  flex-direction: column;
  gap: 0.75rem;
}

.setting-control-grow {
  width: 100%;
  margin-left: 0;
}

.setting-control-with-clear {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.setting-control-with-clear input[type="text"] {
  min-width: 0;
  flex: 1;
}

.setting-control-grow select,
.setting-control-grow input[type="text"],
.setting-control-grow input[type="number"],
.setting-control-grow textarea {
  width: 100%;
  min-width: 0;
  min-height: 44px;
}

.setting-control-grow textarea {
  min-height: 11rem;
  resize: vertical;
  line-height: 1.6;
}

.field-meta {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.field-meta .field-error {
  margin-right: auto;
}

.character-count {
  margin: 0.5rem 0 0 auto;
  color: var(--text-muted);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
}

.setting-control select:focus-visible,
.setting-control input[type="text"]:focus-visible,
.setting-control input[type="number"]:focus-visible,
.setting-control textarea:focus-visible,
.icon-action-btn:focus-visible,
.engine-card:focus-visible,
.character-card:focus-visible,
.btn-apply:focus-visible,
.settings-tab:focus-visible,
.close-btn:focus-visible {
  outline: 2px solid var(--primary-light);
  outline-offset: 2px;
}

.icon-action-btn {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.15s ease;
}

.icon-action-btn:hover:not(:disabled) {
  background: var(--bg-secondary);
  border-color: var(--primary);
  color: var(--primary-light);
}

.icon-action-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.icon-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.info-banner.status-ok {
  border-color: rgba(16, 185, 129, 0.35);
}

.info-banner.status-error {
  border-color: rgba(239, 68, 68, 0.4);
}

.info-banner .icon-action-btn {
  margin-left: auto;
}

.field-hint,
.field-error {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.field-hint {
  color: var(--text-muted);
}

.field-error,
.warning-hint {
  color: var(--warning);
}

.btn-apply {
  width: 100%;
  min-height: 44px;
  margin-top: 0.25rem;
  padding: 0.75rem 1rem;
  border: none;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  transition: background 0.2s ease, transform 0.15s ease, opacity 0.2s ease;
}

.btn-apply:hover:not(:disabled) {
  background: var(--primary-dark);
}

.btn-apply:active:not(:disabled) {
  transform: scale(0.98);
}

.btn-apply:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-apply.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border);
}

.btn-apply.btn-secondary:hover:not(:disabled) {
  background: var(--bg-tertiary);
  border-color: var(--primary);
}

.engine-grid,
.character-grid,
.skeleton-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}

.engine-card,
.character-card {
  text-align: left;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: 10px;
  padding: 0.85rem;
  min-height: 88px;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  transition: border-color 0.2s ease, transform 0.15s ease, background 0.2s ease;
}

.engine-card:hover:not(:disabled),
.character-card:hover:not(:disabled) {
  border-color: var(--primary-light);
  transform: translateY(-1px);
}

.engine-card.selected,
.character-card.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

.engine-card.unavailable,
.engine-card:disabled {
  opacity: 0.48;
  cursor: not-allowed;
  transform: none;
}

.card-title {
  font-weight: 600;
  font-size: 0.95rem;
}

.card-desc {
  font-size: 0.75rem;
  line-height: 1.45;
  color: var(--text-muted);
}

.card-status {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--primary-light);
}

.card-status.muted {
  color: var(--text-muted);
  font-weight: 500;
}

.character-thumb {
  aspect-ratio: 1;
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 1.75rem;
}

.character-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.character-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1.25rem 1rem;
  margin-bottom: 0.75rem;
  border: 1px dashed var(--border);
  border-radius: 10px;
  color: var(--text-muted);
  text-align: center;
}

.empty-state i {
  font-size: 1.5rem;
}

.import-card {
  margin: 1rem 0 0.75rem;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-tertiary);
}

.dropzone {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  min-height: 140px;
  margin: 0.75rem 0;
  padding: 1rem;
  border: 1px dashed var(--border);
  border-radius: 10px;
  color: var(--text-muted);
  text-align: center;
  background: var(--bg-secondary);
  transition: border-color 0.2s ease, background 0.2s ease;
}

.dropzone.dragging {
  border-color: var(--primary);
  background: rgba(99, 102, 241, 0.08);
}

.dropzone.disabled {
  opacity: 0.5;
}

.dropzone input[type="file"] {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.dropzone.disabled input[type="file"] {
  cursor: not-allowed;
}

.dropzone i {
  font-size: 1.75rem;
  color: var(--primary-light);
}

.dropzone p {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.5;
}

.compare-card {
  margin-top: 1.25rem;
  padding: 1rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.compare-actions {
  position: relative;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: center;
  margin-top: 0.5rem;
}

.compare-actions .pick-file-btn {
  pointer-events: auto;
}

.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-top: 0.85rem;
}

.compare-result {
  padding: 0.85rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.compare-result.current {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

.compare-result.unavailable {
  opacity: 0.7;
}

.compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.dropzone.recording {
  border-color: var(--warning);
}

.pick-file-btn {
  position: relative;
  z-index: 1;
  min-height: 44px;
  padding: 0.5rem 1rem;
  pointer-events: none;
}

.import-progress {
  margin: 0.75rem 0;
}

.progress-track {
  height: 8px;
  border-radius: 999px;
  background: var(--bg-secondary);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.25s ease;
}

.import-progress p {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.stt-prewarm-progress {
  margin: 0 0 0.75rem;
}

.stt-prewarm-progress p {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--text-secondary);
}

.progress-fill-indeterminate {
  width: 42%;
  animation: prewarm-progress 1.35s ease-in-out infinite;
  transform: translateX(-110%);
  will-change: transform;
}

.skeleton-card {
  min-height: 88px;
  border-radius: 10px;
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-secondary) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.2s ease-in-out infinite;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes prewarm-progress {
  0% { transform: translateX(-110%); }
  50% { transform: translateX(135%); }
  100% { transform: translateX(265%); }
}

@media (prefers-reduced-motion: reduce) {
  .engine-card,
  .character-card,
  .btn-apply,
  .icon-action-btn,
  .settings-trigger,
  .settings-tab,
  .slide-fade-enter-active,
  .slide-fade-leave-active,
  .fade-enter-active,
  .fade-leave-active {
    transition: none;
  }

  .skeleton-card,
  .spin,
  .settings-tab-panel,
  .progress-fill-indeterminate {
    animation: none;
  }

  .progress-fill-indeterminate {
    width: 100%;
    transform: none;
  }
}

/* 響應式 */
@media (max-width: 768px) {
  .settings-panel {
    width: 100%;
  }

  .settings-tabs {
    padding-inline: 0.75rem;
  }

  .settings-content {
    padding: 1rem;
  }

  .settings-footer {
    padding: 1rem;
    padding-bottom: max(1rem, env(safe-area-inset-bottom));
  }

  .engine-grid,
  .character-grid,
  .skeleton-grid,
  .compare-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .settings-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* 確認對話方塊 */
.confirm-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10001;
}

.confirm-dialog {
  background: var(--bg-secondary);
  border-radius: 12px;
  min-width: 400px;
  max-width: 500px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
  border: 1px solid var(--border);
}

.confirm-header {
  padding: 1.5rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.confirm-header i {
  font-size: 1.5rem;
  color: var(--warning);
}

.confirm-header h4 {
  margin: 0;
  font-size: 1.125rem;
  color: var(--text-primary);
}

.confirm-body {
  padding: 1.5rem;
  color: var(--text-secondary);
  line-height: 1.6;
}

.confirm-footer {
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-danger {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--danger);
  color: white;
}

.btn-danger:hover {
  background: #dc2626;
}

@media (max-width: 768px) {
  .confirm-dialog {
    min-width: auto;
    width: 90%;
    max-width: 400px;
  }
}
</style>
