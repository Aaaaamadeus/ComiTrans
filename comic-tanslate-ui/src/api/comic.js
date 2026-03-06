import axios from 'axios'
import request from './index'

// 上传并翻译漫画图片
export function translateImageApi(file) {
  const formData = new FormData()
  formData.append('file', file)
  return axios.post('/process-image', formData, {
    responseType: 'blob',
    timeout: 300000,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}
