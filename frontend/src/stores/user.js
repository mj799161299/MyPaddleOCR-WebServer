import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('token') || '')
  const userInfo = ref(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => userInfo.value?.role === 'admin')

  // 登录
  async function login(username, password) {
    const res = await api.post('/api/auth/login', { username, password })
    token.value = res.data.access_token
    localStorage.setItem('token', token.value)
    await getUserInfo()
    return res.data
  }

  // 注册
  async function register(username, password, invitationCode) {
    const res = await api.post('/api/auth/register', { username, password, invitation_code: invitationCode })
    return res.data
  }

  // 获取用户信息
  async function getUserInfo() {
    try {
      const res = await api.get('/api/auth/me')
      userInfo.value = res.data
    } catch (e) {
      console.error('获取用户信息失败', e)
    }
  }

  // 登出
  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('token')
  }

  // 修改密码
  async function changePassword(oldPassword, newPassword) {
    await api.put('/api/auth/me/password', {
      old_password: oldPassword,
      new_password: newPassword
    })
  }

  return {
    token,
    userInfo,
    isLoggedIn,
    isAdmin,
    login,
    register,
    getUserInfo,
    logout,
    changePassword
  }
})
