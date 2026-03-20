import request from './index'

// 上传并翻译漫画图片（单张）
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

// 批量上传并翻译漫画图片
export function translateImagesApi(files) {
  const formData = new FormData()
  files.forEach(file => {
    formData.append('files', file)
  })
  return request.post('/comic/translateImages', formData, {
    responseType: 'blob',
    timeout: 600000,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}
