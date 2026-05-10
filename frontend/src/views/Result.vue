<template>
  <div class="result-page">
    <van-nav-bar title="识别结果" left-arrow @click-left="goBack" fixed placeholder>
      <template #right>
        <van-icon name="share-o" size="20" @click="showExport = true" />
      </template>
    </van-nav-bar>

    <div class="content">
      <!-- 任务信息 -->
      <div class="task-info" v-if="task">
        <div class="info-item">
          <span class="label">任务状态：</span>
          <van-tag :type="getStatusType(task.status)">{{ getStatusText(task.status) }}</van-tag>
        </div>
        <div class="info-item">
          <span class="label">图片数量：</span>
          <span>{{ task.total_images }} 张</span>
        </div>
        <div class="info-item">
          <span class="label">创建时间：</span>
          <span>{{ formatTime(task.created_at) }}</span>
        </div>
      </div>

      <!-- 结果列表 -->
      <div class="result-list" v-if="results.length > 0">
        <div
          v-for="(result, index) in results"
          :key="result.id"
          class="result-item"
        >
          <div class="result-header">
            <div class="result-title">{{ result.image_name }}</div>
            <van-checkbox v-model="selectedIds" :name="result.id" />
          </div>

          <!-- 图片预览 -->
          <div class="result-image">
            <img :src="getImageUrl(result.image_path)" :alt="result.image_name" @click="previewImage(index)" />
          </div>

          <!-- 识别文本 -->
          <div class="result-text" v-if="result.markdown_text">
            <div class="text-header">
              <span>识别结果</span>
              <van-button size="mini" type="primary" @click="copyText(result.markdown_text)">
                复制
              </van-button>
            </div>
            <div class="text-content">{{ result.markdown_text }}</div>
          </div>

          <!-- 错误信息 -->
          <div class="result-error" v-if="result.status === 'failed'">
            <van-icon name="warning-o" color="#ee0a24" />
            <span>{{ result.error_message || '识别失败' }}</span>
          </div>
        </div>
      </div>

      <van-empty v-else-if="!loading" description="暂无识别结果" />

      <!-- 加载中 -->
      <div class="loading-container" v-if="loading">
        <van-loading type="spinner" size="40">加载中...</van-loading>
      </div>
    </div>

    <!-- 底部操作栏 -->
    <div class="bottom-bar" v-if="results.length > 0">
      <div class="select-all">
        <van-checkbox v-model="isAllSelected" @click="toggleSelectAll">
          全选
        </van-checkbox>
      </div>
      <van-button
        type="primary"
        round
        :disabled="selectedIds.length === 0"
        @click="showExport = true"
      >
        导出 ({{ selectedIds.length }})
      </van-button>
    </div>

    <!-- 导出弹窗 -->
    <van-action-sheet
      v-model:show="showExport"
      title="选择导出格式"
      :actions="exportActions"
      @select="onExport"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showSuccessToast, showFailToast, showImagePreview } from 'vant'
import { useOcrStore } from '../stores/ocr'

const route = useRoute()
const router = useRouter()
const ocrStore = useOcrStore()

const taskId = route.params.taskId
const task = ref(null)
const results = ref([])
const selectedIds = ref([])
const loading = ref(true)
const showExport = ref(false)

// 导出选项
const exportActions = [
  { name: 'Markdown (.md)', value: 'markdown' },
  { name: 'JSON (.json)', value: 'json' },
  { name: 'HTML (.html)', value: 'html' }
]

// 计算属性
const isAllSelected = computed({
  get: () => results.value.length > 0 && selectedIds.value.length === results.value.length,
  set: () => {}
})

// 获取图片URL
function getImageUrl(path) {
  if (!path) return ''
  const parts = path.split('\\')
  const userId = parts[parts.length - 2]
  const filename = parts[parts.length - 1]
  return `/uploads/${userId}/${filename}`
}

// 格式化时间
function formatTime(timeStr) {
  if (!timeStr) return ''
  return new Date(timeStr).toLocaleString('zh-CN')
}

// 获取状态类型
function getStatusType(status) {
  const map = {
    pending: 'warning',
    processing: 'primary',
    completed: 'success',
    failed: 'danger'
  }
  return map[status] || 'default'
}

// 获取状态文本
function getStatusText(status) {
  const map = {
    pending: '等待中',
    processing: '识别中',
    completed: '已完成',
    failed: '失败'
  }
  return map[status] || status
}

// 加载数据
async function loadData() {
  loading.value = true
  try {
    // 加载任务信息
    task.value = await ocrStore.getTask(taskId)

    // 加载识别结果
    const res = await ocrStore.getResults(taskId)
    results.value = res.results || []

    // 默认全选
    selectedIds.value = results.value.map(r => r.id)
  } catch (e) {
    showFailToast('加载失败')
  } finally {
    loading.value = false
  }
}

// 全选/取消全选
function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = [...results.value.map(r => r.id)]
  }
}

// 复制文本
function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    showSuccessToast('已复制')
  }).catch(() => {
    showFailToast('复制失败')
  })
}

// 导出
async function onExport(action) {
  if (selectedIds.value.length === 0) {
    showFailToast('请至少选择一个结果')
    return
  }

  try {
    await ocrStore.exportResults(selectedIds.value, action.value)
    showExport.value = false
    showSuccessToast('导出成功')
  } catch (e) {
    showFailToast('导出失败')
  }
}

// 返回
function goBack() {
  router.push('/')
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.result-page {
  min-height: 100vh;
  background: #f7f8fa;
  padding-bottom: 70px;
}

.content {
  padding: 12px;
}

.task-info {
  background: white;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}

.info-item {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
}

.info-item:last-child {
  margin-bottom: 0;
}

.info-item .label {
  color: #666;
  margin-right: 8px;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-item {
  background: white;
  border-radius: 8px;
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f5f5f5;
}

.result-title {
  font-size: 14px;
  font-weight: 500;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 12px;
}

.result-image {
  padding: 12px;
}

.result-image img {
  width: 100%;
  max-height: 200px;
  object-fit: contain;
  border-radius: 4px;
  cursor: pointer;
}

.result-text {
  padding: 12px 16px;
  border-top: 1px solid #f5f5f5;
}

.text-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
  color: #666;
}

.text-content {
  font-size: 14px;
  line-height: 1.6;
  color: #333;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.result-error {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ee0a24;
  font-size: 14px;
  background: #fff1f0;
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 200px;
}

.bottom-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: white;
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.05);
}

.select-all {
  font-size: 14px;
}
</style>
