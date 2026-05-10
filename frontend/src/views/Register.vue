<template>
  <div class="register-page">
    <div class="register-header">
      <div class="logo">
        <van-icon name="scan" size="48" color="#1989fa" />
      </div>
      <h1>用户注册</h1>
      <p>创建账号，开始使用OCR服务</p>
    </div>

    <van-form @submit="onSubmit" class="register-form">
      <van-cell-group inset>
        <van-field
          v-model="username"
          name="username"
          label="用户名"
          placeholder="请输入用户名（3-50字符）"
          :rules="[
            { required: true, message: '请输入用户名' },
            { min: 3, message: '用户名至少3个字符' }
          ]"
        />
        <van-field
          v-model="password"
          type="password"
          name="password"
          label="密码"
          placeholder="请输入密码（至少6位）"
          :rules="[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少6个字符' }
          ]"
        />
        <van-field
          v-model="confirmPassword"
          type="password"
          name="confirmPassword"
          label="确认密码"
          placeholder="请再次输入密码"
          :rules="[
            { required: true, message: '请确认密码' },
            { validator: v => v === password, message: '两次密码不一致' }
          ]"
        />
        <van-field
          v-model="invitationCode"
          name="invitationCode"
          label="邀请码"
          placeholder="请输入邀请码"
          :rules="[
            { required: true, message: '请输入邀请码' }
          ]"
        />
      </van-cell-group>

      <div class="submit-btn">
        <van-button round block type="primary" native-type="submit" :loading="loading">
          注册
        </van-button>
      </div>

      <div class="login-link">
        已有账号？<router-link to="/login">立即登录</router-link>
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
const confirmPassword = ref('')
const invitationCode = ref('')
const loading = ref(false)

async function onSubmit() {
  loading.value = true
  try {
    await userStore.register(username.value, password.value, invitationCode.value)
    showSuccessToast('注册成功')
    router.push('/login')
  } catch (e) {
    showFailToast(e.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 0 20px;
}

.register-header {
  text-align: center;
  padding-top: 60px;
  margin-bottom: 40px;
}

.register-header .logo {
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

.register-header h1 {
  color: white;
  font-size: 24px;
  margin-bottom: 8px;
}

.register-header p {
  color: rgba(255, 255, 255, 0.8);
  font-size: 14px;
}

.register-form {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.submit-btn {
  margin: 24px 16px 16px;
}

.login-link {
  text-align: center;
  font-size: 14px;
  color: #666;
  padding-bottom: 20px;
}

.login-link a {
  color: #1989fa;
  text-decoration: none;
}
</style>
