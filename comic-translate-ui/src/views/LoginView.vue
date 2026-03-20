<template>
  <div class="auth-page">
    <div class="auth-container">
      <!-- 左侧装饰区域 -->
      <div class="auth-banner">
        <div class="banner-content">
          <div class="logo-icon">
            <el-icon :size="48"><Picture /></el-icon>
          </div>
          <h1>ComiTrans</h1>
          <p>智能漫画翻译平台</p>
          <div class="features">
            <div class="feature-item">
              <el-icon><MagicStick /></el-icon>
              <span>AI 驱动的漫画翻译</span>
            </div>
            <div class="feature-item">
              <el-icon><Upload /></el-icon>
              <span>一键上传，自动处理</span>
            </div>
            <div class="feature-item">
              <el-icon><Download /></el-icon>
              <span>高质量翻译结果下载</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧登录表单 -->
      <div class="auth-form-wrapper">
        <div class="auth-form">
          <h2>欢迎回来</h2>
          <p class="subtitle">登录你的账号以继续使用</p>

          <el-form
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            size="large"
            @keyup.enter="handleLogin"
          >
            <el-form-item prop="account">
              <el-input
                v-model="loginForm.account"
                placeholder="邮箱或用户名"
                :prefix-icon="User"
                clearable
              />
            </el-form-item>

            <el-form-item prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="密码"
                :prefix-icon="Lock"
                show-password
                clearable
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                class="submit-btn"
                :loading="loading"
                @click="handleLogin"
              >
                {{ loading ? '登录中...' : '登 录' }}
              </el-button>
            </el-form-item>
          </el-form>

          <div class="auth-footer">
            <span>还没有账号？</span>
            <router-link to="/register" class="link">立即注册</router-link>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { loginApi } from '@/api/user'

const router = useRouter()
const loginFormRef = ref(null)
const loading = ref(false)

const loginForm = reactive({
  account: '',
  password: ''
})

const loginRules = {
  account: [
    { required: true, message: '请输入邮箱或用户名', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return

    loading.value = true
    try {
      const res = await loginApi(loginForm)
      const user = res.data
      // 存储 token 和用户信息
      localStorage.setItem('token', user.token)
      localStorage.setItem('user', JSON.stringify({
        id: user.id,
        email: user.email,
        name: user.name,
        createdAt: user.createdAt
      }))
      ElMessage.success('登录成功！')
      router.push('/')
    } catch (err) {
      // 错误已在拦截器中处理
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.auth-container {
  display: flex;
  background: #fff;
  border-radius: 20px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  overflow: hidden;
  max-width: 900px;
  width: 100%;
  min-height: 520px;
}

/* 左侧装饰 */
.auth-banner {
  flex: 1;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.banner-content {
  text-align: center;
}

.logo-icon {
  margin-bottom: 16px;
}

.banner-content h1 {
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 8px 0;
  letter-spacing: 2px;
}

.banner-content > p {
  font-size: 16px;
  opacity: 0.85;
  margin: 0 0 36px 0;
}

.features {
  text-align: left;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  font-size: 14px;
  opacity: 0.9;
}

.feature-item .el-icon {
  font-size: 20px;
}

/* 右侧表单 */
.auth-form-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.auth-form {
  width: 100%;
  max-width: 360px;
}

.auth-form h2 {
  font-size: 28px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 8px 0;
}

.subtitle {
  color: #888;
  font-size: 14px;
  margin: 0 0 32px 0;
}

.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 16px;
  border-radius: 8px;
}

.auth-footer {
  text-align: center;
  margin-top: 24px;
  font-size: 14px;
  color: #888;
}

.auth-footer .link {
  color: #667eea;
  text-decoration: none;
  font-weight: 600;
  margin-left: 4px;
}

.auth-footer .link:hover {
  text-decoration: underline;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .auth-banner {
    display: none;
  }

  .auth-container {
    max-width: 420px;
  }

  .auth-form-wrapper {
    padding: 32px 24px;
  }
}
</style>
