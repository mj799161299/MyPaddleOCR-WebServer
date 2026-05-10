<template>
  <div class="login-page">
    <div class="login-header">
      <div class="logo">
        <van-icon name="scan" size="48" color="#1989fa" />
      </div>
      <h1>OCR扫描工具</h1>
      <p>图片文字识别，智能高效</p>
    </div>

    <van-form @submit="onSubmit" class="login-form">
      <van-cell-group inset>
        <van-field
          v-model="username"
          name="username"
          label="用户名"
          placeholder="请输入用户名"
          :rules="[{ required: true, message: '请输入用户名' }]"
        />
        <van-field
          v-model="password"
          type="password"
          name="password"
          label="密码"
          placeholder="请输入密码"
          :rules="[{ required: true, message: '请输入密码' }]"
        />
      </van-cell-group>

      <div class="submit-btn">
        <van-button round block type="primary" native-type="submit" :loading="loading">
          登录
        </van-button>
      </div>

      <div class="register-link">
        还没有账号？<router-link to="/register">立即注册</router-link>
      </div>
    </van-form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showSuccessToast, showFailToast } from 'vant'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onSubmit() {
  loading.value = true
  try {
    await userStore.login(username.value, password.value)
    showSuccessToast('登录成功')
    router.push('/')
  } catch (e) {
    showFailToast(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 0 20px;
}

.login-header {
  text-align: center;
  padding-top: 80px;
  margin-bottom: 40px;
}

.login-header .logo {
  width: 80px;
  height: 80px;
  margin: 0 auto 20px;
  background: white;
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.login-header h1 {
  color: white;
  font-size: 24px;
  margin-bottom: 8px;
}

.login-header p {
  color: rgba(255, 255, 255, 0.8);
  font-size: 14px;
}

.login-form {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.submit-btn {
  margin: 24px 16px 16px;
}

.register-link {
  text-align: center;
  font-size: 14px;
  color: #666;
  padding-bottom: 20px;
}

.register-link a {
  color: #1989fa;
  text-decoration: none;
}
</style>
