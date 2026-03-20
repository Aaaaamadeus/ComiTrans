import axios from 'axios'

// 获取当前翻译 API 配置
export function getConfigApi() {
  return axios.get('/config', { timeout: 10000 })
}

// 更新翻译 API 配置
export function updateConfigApi(data) {
  return axios({
    method: 'post',
    url: '/config',
    data: data,
    timeout: 10000,
    headers: {
      'Content-Type': 'application/json'
    }
  })
}
