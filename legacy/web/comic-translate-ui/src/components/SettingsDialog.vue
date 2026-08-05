<template>
  <el-dialog
    v-model="visible"
    title="翻译 API 设置"
    width="520px"
    :close-on-click-modal="false"
    @open="loadConfig"
    class="settings-dialog"
  >
    <el-form
      :model="form"
      label-position="top"
      v-loading="loadingConfig"
      element-loading-text="加载配置..."
    >
      <el-form-item label="API Key">
        <el-input
          v-model="form.api_key"
          :placeholder="apiKeyPlaceholder"
          :type="showKey ? 'text' : 'password'"
          clearable
        >
          <template #suffix>
            <el-icon class="toggle-eye" @click="showKey = !showKey">
              <View v-if="showKey" />
              <Hide v-else />
            </el-icon>
          </template>
        </el-input>
        <div class="form-tip">留空则保持当前密钥不变</div>
      </el-form-item>

      <el-form-item label="API Base URL">
        <el-input
          v-model="form.api_base_url"
          placeholder="例如: https://api.openai.com/v1"
          clearable
        />
      </el-form-item>

      <el-form-item label="翻译模型">
        <el-input
          v-model="form.translation_model"
          placeholder="例如: gemini-2.5-flash"
          clearable
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig">
          {{ saving ? '保存中...' : '保存设置' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getConfigApi, updateConfigApi } from '@/api/config'

const visible = defineModel({ type: Boolean, default: false })

const loadingConfig = ref(false)
const saving = ref(false)
const showKey = ref(false)
const currentMaskedKey = ref('')
const currentKeyLength = ref(0)

const form = ref({
  api_key: '',
  api_base_url: '',
  translation_model: ''
})

const apiKeyPlaceholder = computed(() => {
  if (currentKeyLength.value > 0) {
    return `当前密钥: ${currentMaskedKey.value}`
  }
  return '请输入 API Key'
})

const loadConfig = async () => {
  loadingConfig.value = true
  showKey.value = false
  form.value.api_key = ''

  try {
    const res = await getConfigApi()
    const data = res.data
    currentMaskedKey.value = data.api_key || ''
    currentKeyLength.value = data.raw_api_key_length || 0
    form.value.api_base_url = data.api_base_url || ''
    form.value.translation_model = data.translation_model || ''
  } catch (error) {
    ElMessage.error('加载配置失败')
    console.error(error)
  } finally {
    loadingConfig.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const payload = {}

    // 只提交有值的字段；API Key 为空时不更新
    if (form.value.api_key) {
      payload.api_key = form.value.api_key
    }
    if (form.value.api_base_url !== undefined) {
      payload.api_base_url = form.value.api_base_url
    }
    if (form.value.translation_model !== undefined) {
      payload.translation_model = form.value.translation_model
    }

    await updateConfigApi(payload)
    ElMessage.success('设置已保存并即时生效')
    visible.value = false
  } catch (error) {
    ElMessage.error('保存设置失败')
    console.error(error)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.toggle-eye {
  cursor: pointer;
  color: #909399;
  transition: color 0.2s;
}

.toggle-eye:hover {
  color: #667eea;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

<style>
.settings-dialog .el-dialog__header {
  border-bottom: 1px solid #f0f0f0;
  padding-bottom: 16px;
}

.settings-dialog .el-dialog__body {
  padding-top: 24px;
}

.settings-dialog .el-dialog__footer {
  border-top: 1px solid #f0f0f0;
  padding-top: 16px;
}
</style>
