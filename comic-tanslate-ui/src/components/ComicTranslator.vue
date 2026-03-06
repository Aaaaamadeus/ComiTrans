<template>
  <div class="comic-translator">
    <h1>Amadeus 漫画汉化助手</h1>

    <!-- 移除了 :class="{ 'wide-container': ... }"，现在样式由 CSS 媒体查询全权控制 -->
    <div class="container" v-loading="loading" element-loading-text="正在识别并翻译中...可能需要 10-30 秒">

      <!-- 移除了 :class="{ 'has-result': ... }" -->
      <div class="content-wrapper">

        <!-- 左侧：输入/上传区域 -->
        <div class="input-section">
          <el-upload
              class="upload-demo"
              drag
              action="#"
              :auto-upload="false"
              :limit="1"
              :on-change="handleFileChange"
              :on-exceed="handleExceed"
              :show-file-list="true"
              ref="uploadRef"
              accept="image/*"
          >
            <el-icon class="el-icon--upload"><upload-filled /></el-icon>
            <div class="el-upload__text">
              拖拽文件到此处 或 <em>点击选择</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                支持 JPG/PNG 等常见图片格式
              </div>
            </template>
          </el-upload>

          <div class="actions">
            <el-button type="primary" size="large" @click="uploadAndProcess" :disabled="!file" :icon="loading ? 'Loading' : 'VideoPlay'">
              {{ loading ? '正在汉化中...' : '开始汉化' }}
            </el-button>
          </div>

          <div v-if="errorMessage" class="error-msg">
            <el-alert :title="errorMessage" type="error" show-icon :closable="false" />
          </div>
        </div>

        <!-- 右侧：结果区域（始终显示，无结果时显示占位符） -->
        <div class="result-section">
          <!-- 情况 A: 有结果 -->
          <div v-if="resultImageUrl" class="result-content">
            <h3>汉化结果：</h3>
            <div class="image-wrapper">
              <el-image
                  :src="resultImageUrl"
                  :preview-src-list="[resultImageUrl]"
                  fit="contain"
                  class="result-image"
              >
                <template #placeholder>
                  <div class="image-slot">Loading...</div>
                </template>
              </el-image>
            </div>
            <div class="download-btn">
              <el-button type="success" @click="downloadImage" icon="Download">下载图片</el-button>
            </div>
          </div>

          <!-- 情况 B: 无结果 (占位符) -->
          <div v-else class="placeholder-content">
            <el-empty description="请在左侧上传图片，汉化结果将显示在这里" />
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'
import { ElMessage, genFileId } from 'element-plus'

const uploadRef = ref(null)
const file = ref(null)
const loading = ref(false)
const resultImageUrl = ref('')
const errorMessage = ref('')

const handleFileChange = (uploadFile) => {
  file.value = uploadFile.raw
  errorMessage.value = ''
}

const handleExceed = (files) => {
  uploadRef.value.clearFiles()
  const file = files[0]
  file.uid = genFileId()
  uploadRef.value.handleStart(file)
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

const uploadAndProcess = async () => {
  if (!file.value) {
    ElMessage.warning('请先选择一张图片！')
    return
  }

  loading.value = true
  errorMessage.value = ''

    const formData = new FormData()
    formData.append("file", file.value)

    try {
        const response = await axios.post('/process-image', formData, {
            responseType: 'blob',
            timeout: 300000
        })

    const blob = response.data
    if (resultImageUrl.value) {
      URL.revokeObjectURL(resultImageUrl.value)
    }
    resultImageUrl.value = URL.createObjectURL(blob)
    ElMessage.success('汉化成功！')
  } catch (error) {
    console.error(error)
    let msg = "请求失败"
    if (error.response) {
      if (error.response.data instanceof Blob) {
        const text = await error.response.data.text()
        try {
          const json = JSON.parse(text)
          msg = json.message || json.error || "服务器错误"
        } catch (e) {
          msg = `服务器错误 (${error.response.status})`
        }
      } else {
        msg = error.message
      }
    } else if (error.request) {
      msg = "无法连接到服务器"
    } else {
      msg = error.message
    }

    errorMessage.value = "处理失败: " + msg
    ElMessage.error('汉化失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.comic-translator {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  background-color: #f0f2f5;
}

h1 {
  color: #333;
  margin-bottom: 30px;
  font-weight: 600;
}

/* 默认移动端/小屏样式 */
.container {
  background: white;
  padding: 30px;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  text-align: center;
  max-width: 800px;
  width: 95%;
  transition: all 0.4s ease; /* transition 改为 all，让宽度变化更平滑 */
}

.upload-demo {
  margin-bottom: 30px;
}

.actions {
  margin-top: 20px;
  margin-bottom: 20px;
}

.error-msg {
  margin-top: 20px;
  text-align: left;
}

.result-section {
  margin-top: 30px;
  border-top: 1px solid #eee;
  padding-top: 20px;
  animation: fadeIn 0.5s ease;
}

.image-wrapper {
  background-color: #f9fafb;
  border-radius: 8px;
  overflow: hidden;
  min-height: 200px;
  display: flex;
  justify-content: center;
  align-items: center;
  border: 1px solid #eee;
}

.result-image {
  max-width: 100%;
  max-height: 80vh;
  display: block;
}

.download-btn {
  margin-top: 15px;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Desktop Responsive Layout */
/* 只要屏幕够宽，直接启用左右分栏，不再依赖是否有结果 */
@media (min-width: 1024px) {
  .container {
    max-width: 1400px; /* 宽屏模式 */
    padding: 40px;
  }

  .content-wrapper {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    gap: 40px;
    text-align: left;
  }

  .input-section {
    flex: 0 0 350px; /* 左侧固定宽度 */
    position: sticky;
    top: 20px;
    text-align: center;
  }

  .result-section {
    flex: 1; /* 右侧占满剩余空间 */
    margin-top: 0;
    border-top: none;
    border-left: 1px solid #eee; /* 竖向分割线 */
    padding-top: 0;
    padding-left: 40px;
    min-height: 400px; /* 保证有一个最小高度，让布局好看 */
    display: flex;         /* 使得内部的 placeholder 能居中 */
    flex-direction: column;
    justify-content: center;
  }

  .result-content {
    width: 100%;
  }

  .placeholder-content {
    width: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100%;
  }

  .result-section h3 {
    margin-top: 0;
  }
}
</style>
