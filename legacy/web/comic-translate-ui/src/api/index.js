import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api',
  timeout: 120000
})

// 请求拦截器 - 自动附加 Token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = token
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理统一响应和错误
request.interceptors.response.use(
  (response) => {
    // 如果是 blob 类型（图片下载等），直接返回
    if (response.config.responseType === 'blob') {
      return response
    }
    const res = response.data
    // 后端统一响应格式: { code: 0/1, message, data }
    if (res.code === 0) {
      return res
    } else {
      ElMessage.error(res.message || '操作失败')
      return Promise.reject(new Error(res.message || '操作失败'))
    }
  },
  (error) => {
    if (error.response) {
      const status = error.response.status
      if (status === 401) {
        // Token 过期或无效，清除登录状态并跳转到登录页
        localStorage.removeItem('token')
        localStorage.removeItem('user')
        ElMessage.warning('登录已过期，请重新登录')
        router.push('/login')
      } else {
        const msg = error.response.data?.message || `服务器错误 (${status})`
        ElMessage.error(msg)
      }
    } else if (error.request) {
      ElMessage.error('无法连接到服务器')
    } else {
      ElMessage.error(error.message)
    }
    return Promise.reject(error)
  }
)

export default request
