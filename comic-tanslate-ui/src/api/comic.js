import request from './index'

// 上传并翻译漫画图片
export function translateImageApi(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/comic/translateImage', formData, {
    responseType: 'blob',
    timeout: 120000,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}
