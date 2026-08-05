import request from './index'

// 用户注册
export function registerApi(data) {
  return request.post('/user/register', data)
}

// 用户登录
export function loginApi(data) {
  return request.post('/user/login', data)
}
