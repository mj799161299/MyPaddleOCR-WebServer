import axios from 'axios'
import { showFailToast } from 'vant'

const api = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.request.use(
  config => {
    const token = sessionStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

api.interceptors.response.use(
  response => response,
  error => {
    const { response } = error

    if (response) {
      switch (response.status) {
        case 401:
          sessionStorage.removeItem('token')
          showFailToast('登录已过期')
          break
        case 403:
          showFailToast('没有权限访问')
          break
        case 404:
          showFailToast('请求的资源不存在')
          break
        case 422:
          showFailToast('请求参数错误')
          break
        case 500:
          showFailToast('服务器错误')
          break
        default:
          showFailToast(response.data?.detail || '请求失败')
      }
    } else {
      showFailToast('网络连接失败')
    }

    return Promise.reject(error)
  }
)

export default api
