<template>
  <div class="translate-page">
    <!-- 顶部导航栏 -->
    <AppHeader />

    <!-- 主体内容 -->
    <div class="main-content">
      <div class="page-header">
        <h1>漫画翻译</h1>
        <p>上传你的漫画图片，AI 自动识别文字并翻译为中文（支持批量上传）</p>
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
                multiple
                :on-change="handleFileChange"
                :show-file-list="false"
                ref="uploadRef"
                accept="image/*"
              >
                <div class="upload-placeholder">
                  <el-icon class="upload-icon" :size="48"><UploadFilled /></el-icon>
                  <div class="upload-text">
                    将图片拖拽到此处，或 <em>点击选择</em>
                  </div>
                  <div class="upload-tip">
                    支持 JPG / PNG 等常见格式，可批量选择多张图片
                  </div>
                </div>
              </el-upload>

              <!-- 已选择的文件列表 -->
              <div v-if="fileList.length > 0" class="file-list">
                <div class="file-list-header">
                  <span>已选择 {{ fileList.length }} 张图片</span>
                  <el-button link type="danger" @click="clearAllFiles">全部清除</el-button>
                </div>
                <div class="file-thumbnails">
                  <div
                    v-for="(item, index) in fileList"
                    :key="index"
                    class="thumbnail-item"
                  >
                    <img :src="item.previewUrl" :alt="item.file.name" />
                    <div class="thumbnail-name">{{ item.file.name }}</div>
                    <el-icon class="thumbnail-remove" @click="removeFile(index)"><Close /></el-icon>
                  </div>
                </div>
              </div>

              <div class="upload-actions">
                <el-button
                  type="primary"
                  size="large"
                  :loading="loading"
                  :disabled="fileList.length === 0"
                  @click="uploadAndTranslate"
                  class="translate-btn"
                >
                  <el-icon v-if="!loading"><VideoPlay /></el-icon>
                  {{ loading ? `正在翻译中 (${progressText})...` : '开始翻译' }}
                </el-button>
                <el-button
                  v-if="fileList.length > 0"
                  size="large"
                  @click="clearAllFiles"
                  :disabled="loading"
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
                <span v-if="resultList.length > 0" class="result-count">
                  （{{ resultList.length }} 张）
                </span>
              </h3>

              <!-- 加载中 -->
              <div v-if="loading" class="loading-state">
                <el-icon class="is-loading" :size="48" color="#667eea"><Loading /></el-icon>
                <p>AI 正在批量识别和翻译中...</p>
                <p class="loading-tip">{{ progressText }}，请耐心等待</p>
                <el-progress
                  v-if="fileList.length > 1"
                  :percentage="progressPercent"
                  :stroke-width="10"
                  style="width: 80%; margin-top: 16px;"
                />
              </div>

              <!-- 有结果 -->
              <div v-else-if="resultList.length > 0" class="result-content">
                <!-- 批量下载按钮 -->
                <div class="result-actions-top" v-if="resultList.length > 1">
                  <el-button type="success" @click="downloadAllAsZip">
                    <el-icon><Download /></el-icon>
                    下载全部翻译图片 (ZIP)
                  </el-button>
                </div>

                <div class="result-grid">
                  <div
                    v-for="(result, index) in resultList"
                    :key="index"
                    class="result-item"
                  >
                    <div class="result-item-header">
                      <span class="result-item-name">{{ result.name }}</span>
                      <el-button link type="primary" @click="downloadSingleImage(result)">
                        <el-icon><Download /></el-icon>
                        下载
                      </el-button>
                    </div>
                    <div class="image-wrapper">
                      <el-image
                        :src="result.url"
                        :preview-src-list="resultPreviewList"
                        :initial-index="index"
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
                  </div>
                </div>

                <!-- 单张时的下载按钮 -->
                <div v-if="resultList.length === 1" class="result-actions">
                  <el-button type="success" @click="downloadSingleImage(resultList[0])">
                    <el-icon><Download /></el-icon>
                    下载翻译图片
                  </el-button>
                </div>
              </div>

              <!-- 显示部分失败的错误 -->
              <div v-if="partialErrors.length > 0" class="partial-errors">
                <el-alert type="warning" :closable="false">
                  <template #title>
                    以下图片翻译失败：
                  </template>
                  <div v-for="(err, i) in partialErrors" :key="i" class="error-item">
                    {{ err }}
                  </div>
                </el-alert>
              </div>

              <!-- 空状态 -->
              <div v-if="!loading && resultList.length === 0" class="empty-state">
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
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { translateImageApi, translateImagesApi } from '@/api/comic'
import AppHeader from '@/components/AppHeader.vue'

const router = useRouter()

const uploadRef = ref(null)
const fileList = ref([])     // [{file, previewUrl}]
const loading = ref(false)
const resultList = ref([])   // [{name, url, blob}]
const errorMessage = ref('')
const partialErrors = ref([])
const currentProgress = ref(0)
const totalFiles = ref(0)

const progressText = computed(() => {
  if (totalFiles.value <= 1) return '处理中'
  return `${currentProgress.value}/${totalFiles.value}`
})

const progressPercent = computed(() => {
  if (totalFiles.value === 0) return 0
  return Math.round((currentProgress.value / totalFiles.value) * 100)
})

const resultPreviewList = computed(() => resultList.value.map(r => r.url))

const handleFileChange = (uploadFile) => {
  // 避免重复添加
  const exists = fileList.value.some(item => 
    item.file.name === uploadFile.raw.name && item.file.size === uploadFile.raw.size
  )
  if (exists) return

  const previewUrl = URL.createObjectURL(uploadFile.raw)
  fileList.value.push({ file: uploadFile.raw, previewUrl })
  errorMessage.value = ''
}

const removeFile = (index) => {
  const item = fileList.value[index]
  URL.revokeObjectURL(item.previewUrl)
  fileList.value.splice(index, 1)
}

const clearAllFiles = () => {
  fileList.value.forEach(item => URL.revokeObjectURL(item.previewUrl))
  fileList.value = []
  if (uploadRef.value) {
    uploadRef.value.clearFiles()
  }
  errorMessage.value = ''
}

const downloadSingleImage = (result) => {
  const a = document.createElement('a')
  a.href = result.url
  a.download = result.name
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

const downloadAllAsZip = async () => {
  if (zipBlob.value) {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(zipBlob.value)
    a.download = 'translated_comics.zip'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }
}

const zipBlob = ref(null)

const uploadAndTranslate = async () => {
  if (fileList.value.length === 0) {
    ElMessage.warning('请先选择图片！')
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
  partialErrors.value = []
  // 清理上次结果
  resultList.value.forEach(r => URL.revokeObjectURL(r.url))
  resultList.value = []
  zipBlob.value = null

  const files = fileList.value.map(item => item.file)
  totalFiles.value = files.length
  currentProgress.value = 0

  if (files.length === 1) {
    // 单张使用原有接口
    try {
      const response = await translateImageApi(files[0])
      const blob = response.data
      const url = URL.createObjectURL(blob)
      resultList.value.push({
        name: 'translated_' + files[0].name,
        url,
        blob
      })
      currentProgress.value = 1
      ElMessage.success('翻译完成！')
    } catch (error) {
      errorMessage.value = '翻译失败: ' + extractErrorMessage(error)
      ElMessage.error('翻译失败')
    }
  } else {
    // 多张使用批量接口
    try {
      const response = await translateImagesApi(files)
      const blob = response.data
      
      // 检查返回类型
      if (blob.type === 'application/json') {
        // 可能是错误响应
        const text = await blob.text()
        const json = JSON.parse(text)
        errorMessage.value = json.message || '翻译失败'
        ElMessage.error('翻译失败')
      } else {
        // 返回zip，保存并解压显示
        zipBlob.value = blob
        currentProgress.value = files.length

        // 使用 JSZip 解压预览（如果可用），否则直接提供下载
        try {
          const { default: JSZip } = await import('jszip')
          const zip = await JSZip.loadAsync(blob)
          const entries = Object.entries(zip.files)
          
          for (const [filename, zipEntry] of entries) {
            if (!zipEntry.dir) {
              const fileBlob = await zipEntry.async('blob')
              const imgBlob = new Blob([fileBlob], { type: 'image/jpeg' })
              const url = URL.createObjectURL(imgBlob)
              resultList.value.push({
                name: filename,
                url,
                blob: imgBlob
              })
            }
          }
          ElMessage.success(`翻译完成！共 ${resultList.value.length} 张`)
        } catch {
          // JSZip 不可用，直接提供打包下载
          resultList.value = []
          ElMessage.success('翻译完成！点击下载按钮获取结果')
        }
      }
    } catch (error) {
      errorMessage.value = '批量翻译失败: ' + extractErrorMessage(error)
      ElMessage.error('批量翻译失败')
    }
  }

  loading.value = false
}

function extractErrorMessage(error) {
  if (error.response) {
    if (error.response.data instanceof Blob) {
      return `服务器错误 (${error.response.status})`
    } else if (error.response.data?.message) {
      return error.response.data.message
    }
    return error.message
  } else if (error.request) {
    return '无法连接到服务器'
  }
  return error.message
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

.result-count {
  font-size: 14px;
  font-weight: 400;
  color: #909399;
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
  min-height: 180px;
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
  padding: 32px 20px;
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

/* 文件列表 */
.file-list {
  margin-top: 16px;
}

.file-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 14px;
  color: #606266;
}

.file-thumbnails {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
  padding: 4px;
}

.thumbnail-item {
  position: relative;
  width: 72px;
  text-align: center;
}

.thumbnail-item img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid #eee;
}

.thumbnail-name {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 4px;
}

.thumbnail-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  background: #f56c6c;
  color: #fff;
  border-radius: 50%;
  width: 18px;
  height: 18px;
  font-size: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s;
}

.thumbnail-item:hover .thumbnail-remove {
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

.result-actions-top {
  margin-bottom: 20px;
  display: flex;
  justify-content: center;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.result-item {
  background: #fafafa;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #eee;
}

.result-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #f5f7fa;
  border-bottom: 1px solid #eee;
}

.result-item-name {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  margin-right: 8px;
}

.image-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  padding: 8px;
}

.result-image {
  max-width: 100%;
  max-height: 60vh;
  display: block;
}

.result-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

/* 部分错误 */
.partial-errors {
  margin-top: 16px;
}

.error-item {
  font-size: 13px;
  color: #e6a23c;
  padding: 2px 0;
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

  .result-grid {
    grid-template-columns: 1fr;
  }
}
</style>
