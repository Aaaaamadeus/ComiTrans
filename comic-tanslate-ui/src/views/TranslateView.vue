<template>
  <div class="translate-page">
    <!-- 顶部导航栏 -->
    <AppHeader />

    <!-- 主体内容 -->
    <div class="main-content">
      <div class="page-header">
        <h1>漫画翻译</h1>
        <p>上传你的漫画图片，AI 自动识别文字并翻译为中文</p>
      </div>

      <div class="translate-container">
        <div class="content-wrapper">
          <!-- 左侧：上传区域 -->
          <div class="upload-section">
            <div class="section-card">
              <h3>
                <el-icon><Upload /></el-icon>
                上传图片
              </h3>

              <el-upload
                class="upload-area"
                drag
                action="#"
                :auto-upload="false"
                :limit="1"
                :on-change="handleFileChange"
                :on-exceed="handleExceed"
                :show-file-list="false"
                ref="uploadRef"
                accept="image/*"
              >
                <!-- 已选择文件时显示预览 -->
                <div v-if="previewUrl" class="preview-in-upload">
                  <img :src="previewUrl" alt="预览" />
                  <div class="preview-overlay">
                    <el-icon :size="24"><RefreshRight /></el-icon>
                    <span>点击更换图片</span>
                  </div>
                </div>
                <!-- 未选择文件时显示上传提示 -->
                <div v-else class="upload-placeholder">
                  <el-icon class="upload-icon" :size="48"><UploadFilled /></el-icon>
                  <div class="upload-text">
                    将图片拖拽到此处，或 <em>点击选择</em>
                  </div>
                  <div class="upload-tip">
                    支持 JPG / PNG 等常见图片格式
                  </div>
                </div>
              </el-upload>

              <div class="upload-actions">
                <el-button
                  type="primary"
                  size="large"
                  :loading="loading"
                  :disabled="!file"
                  @click="uploadAndTranslate"
                  class="translate-btn"
                >
                  <el-icon v-if="!loading"><VideoPlay /></el-icon>
                  {{ loading ? '正在翻译中...' : '开始翻译' }}
                </el-button>
                <el-button
                  v-if="file"
                  size="large"
                  @click="clearFile"
                >
                  清除
                </el-button>
              </div>

              <div v-if="errorMessage" class="error-msg">
                <el-alert :title="errorMessage" type="error" show-icon :closable="true" @close="errorMessage = ''" />
              </div>
            </div>
          </div>

          <!-- 右侧：结果展示 -->
          <div class="result-section">
            <div class="section-card result-card">
              <h3>
                <el-icon><Picture /></el-icon>
                翻译结果
              </h3>

              <!-- 加载中 -->
              <div v-if="loading" class="loading-state">
                <el-icon class="is-loading" :size="48" color="#667eea"><Loading /></el-icon>
                <p>AI 正在识别和翻译中...</p>
                <p class="loading-tip">这可能需要 10-30 秒，请耐心等待</p>
              </div>

              <!-- 有结果 -->
              <div v-else-if="resultImageUrl" class="result-content">
                <div class="image-wrapper">
                  <el-image
                    :src="resultImageUrl"
                    :preview-src-list="[resultImageUrl]"
                    fit="contain"
                    class="result-image"
                  >
                    <template #placeholder>
                      <div class="image-slot">
                        <el-icon class="is-loading"><Loading /></el-icon>
                      </div>
                    </template>
                  </el-image>
                </div>
                <div class="result-actions">
                  <el-button type="success" @click="downloadImage">
                    <el-icon><Download /></el-icon>
                    下载翻译图片
                  </el-button>
                </div>
              </div>

              <!-- 空状态 -->
              <div v-else class="empty-state">
                <el-empty description="上传图片后，翻译结果将显示在这里">
                  <template #image>
                    <el-icon :size="64" color="#c0c4cc"><PictureFilled /></el-icon>
                  </template>
                </el-empty>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, genFileId } from 'element-plus'
import { translateImageApi } from '@/api/comic'
import AppHeader from '@/components/AppHeader.vue'

const router = useRouter()

const uploadRef = ref(null)
const file = ref(null)
const previewUrl = ref('')
const loading = ref(false)
const resultImageUrl = ref('')
const errorMessage = ref('')

const handleFileChange = (uploadFile) => {
  file.value = uploadFile.raw
  errorMessage.value = ''

  // 生成预览
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
  previewUrl.value = URL.createObjectURL(uploadFile.raw)
}

const handleExceed = (files) => {
  uploadRef.value.clearFiles()
  const newFile = files[0]
  newFile.uid = genFileId()
  uploadRef.value.handleStart(newFile)
}

const clearFile = () => {
  file.value = null
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  if (uploadRef.value) {
    uploadRef.value.clearFiles()
  }
  errorMessage.value = ''
}

const downloadImage = () => {
  if (!resultImageUrl.value) return
  const a = document.createElement('a')
  a.href = resultImageUrl.value
  a.download = 'translated_comic.jpg'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

const uploadAndTranslate = async () => {
  if (!file.value) {
    ElMessage.warning('请先选择一张图片！')
    return
  }

  // 检查是否已登录
  const token = localStorage.getItem('token')
  if (!token) {
    try {
      await ElMessageBox.confirm(
        '上传翻译需要登录，是否前往登录页面？',
        '需要登录',
        {
          confirmButtonText: '去登录',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
      router.push('/login')
    } catch {
      // 用户取消
    }
    return
  }

  loading.value = true
  errorMessage.value = ''

  try {
    const response = await translateImageApi(file.value)
    const blob = response.data

    if (resultImageUrl.value) {
      URL.revokeObjectURL(resultImageUrl.value)
    }
    resultImageUrl.value = URL.createObjectURL(blob)
    ElMessage.success('翻译完成！')
  } catch (error) {
    let msg = '请求失败'
    if (error.response) {
      if (error.response.data instanceof Blob) {
        const text = await error.response.data.text()
        try {
          const json = JSON.parse(text)
          msg = json.message || json.error || '服务器错误'
        } catch (e) {
          msg = `服务器错误 (${error.response.status})`
        }
      } else if (error.response.data?.message) {
        msg = error.response.data.message
      } else {
        msg = error.message
      }
    } else if (error.request) {
      msg = '无法连接到服务器'
    } else {
      msg = error.message
    }
    errorMessage.value = '翻译失败: ' + msg
    ElMessage.error('翻译失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.translate-page {
  min-height: 100vh;
  background: #f5f7fa;
  display: flex;
  flex-direction: column;
}

.main-content {
  flex: 1;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
  padding: 32px 24px;
}

.page-header {
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 28px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 8px 0;
}

.page-header p {
  color: #888;
  font-size: 15px;
  margin: 0;
}

.content-wrapper {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

/* 卡片通用样式 */
.section-card {
  background: #fff;
  border-radius: 16px;
  padding: 28px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.section-card h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 20px 0;
}

/* 左侧上传区域 */
.upload-section {
  flex: 0 0 420px;
  position: sticky;
  top: 90px;
}

.upload-area {
  width: 100%;
}

.upload-area :deep(.el-upload) {
  width: 100%;
}

.upload-area :deep(.el-upload-dragger) {
  width: 100%;
  height: auto;
  min-height: 240px;
  border-radius: 12px;
  border: 2px dashed #d9d9d9;
  transition: all 0.3s;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-area :deep(.el-upload-dragger:hover) {
  border-color: #667eea;
}

.upload-placeholder {
  padding: 40px 20px;
  text-align: center;
}

.upload-icon {
  color: #c0c4cc;
  margin-bottom: 16px;
}

.upload-text {
  font-size: 15px;
  color: #606266;
  margin-bottom: 8px;
}

.upload-text em {
  color: #667eea;
  font-style: normal;
  font-weight: 600;
}

.upload-tip {
  font-size: 13px;
  color: #909399;
}

/* 预览图 */
.preview-in-upload {
  position: relative;
  width: 100%;
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 10px;
}

.preview-in-upload img {
  max-width: 100%;
  max-height: 360px;
  object-fit: contain;
}

.preview-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  opacity: 0;
  transition: opacity 0.3s;
  font-size: 14px;
}

.preview-in-upload:hover .preview-overlay {
  opacity: 1;
}

/* 上传操作按钮 */
.upload-actions {
  margin-top: 20px;
  display: flex;
  gap: 12px;
}

.translate-btn {
  flex: 1;
  height: 44px;
  font-size: 16px;
  border-radius: 10px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  border: none;
}

.translate-btn:hover {
  background: linear-gradient(135deg, #5a6fd6, #6a4194);
}

.translate-btn:disabled {
  background: #c0c4cc;
}

.error-msg {
  margin-top: 16px;
}

/* 右侧结果区域 */
.result-section {
  flex: 1;
  min-width: 0;
}

.result-card {
  min-height: 400px;
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.loading-state p {
  margin: 16px 0 0 0;
  color: #606266;
  font-size: 16px;
}

.loading-tip {
  color: #909399 !important;
  font-size: 13px !important;
}

/* 结果内容 */
.result-content {
  animation: fadeSlideIn 0.5s ease;
}

.image-wrapper {
  background: #fafafa;
  border-radius: 12px;
  overflow: hidden;
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #eee;
}

.result-image {
  max-width: 100%;
  max-height: 80vh;
  display: block;
}

.result-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

/* 空状态 */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

@keyframes fadeSlideIn {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 响应式 */
@media (max-width: 900px) {
  .content-wrapper {
    flex-direction: column;
  }

  .upload-section {
    flex: none;
    width: 100%;
    position: static;
  }

  .main-content {
    padding: 20px 16px;
  }
}
</style>
