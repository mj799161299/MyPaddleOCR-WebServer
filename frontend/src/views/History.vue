<template>
  <div class="history-page">
    <van-nav-bar title="识别历史" left-arrow @click-left="goBack" fixed placeholder />

    <!-- ===== 图片预览弹窗（ImagePreview组件） ===== -->
    <!-- 点击展开结果中的缩略图时弹出，支持多图浏览和索引指示 -->
    <van-image-preview
      v-model:show="showPreview"
      :images="previewImages"
      :start-position="previewIndex"
      :show-index="true"
      :closeable="true"
    />

    <div class="content">
      <!-- ===== 批量操作栏 ===== -->
      <!-- 两种模式：普通模式（复选框+批量删除按钮）→ 确认模式（二次确认+取消） -->
      <!-- batchMode为true时进入确认模式，防止误操作 -->
      <div class="batch-bar" v-if="tasks.length > 0">
        <van-checkbox v-model="selectAll" @change="onSelectAll" v-if="!batchMode">全选</van-checkbox>
        <van-button v-if="!batchMode && selectedTaskIds.length > 0" size="small" type="danger" plain @click="batchMode = true">
          批量删除 ({{ selectedTaskIds.length }})
        </van-button>
        <template v-if="batchMode">
          <span class="batch-tip">已选 {{ selectedTaskIds.length }} 项</span>
          <van-button size="small" type="danger" @click="confirmBatchDelete">确认删除</van-button>
          <van-button size="small" plain @click="cancelBatch">取消</van-button>
        </template>
      </div>

      <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
        <van-list
          v-if="tasks.length > 0"
          :finished="true"
          finished-text="没有更多了"
        >
          <!-- ===== 任务卡片列表 ===== -->
          <!-- 每个卡片显示任务ID、时间、状态标签、进度（已处理/总数），可展开查看详情 -->
          <div v-for="task in tasks" :key="task.id" class="task-card">
            <van-cell
              :title="`任务 #${task.id}`"
              :label="formatTime(task.created_at)"
            >
              <template #icon>
                <van-checkbox
                  v-model="task.checked"
                  @click.stop
                  @change="onTaskCheckChange(task)"
                  style="margin-right:8px"
                />
              </template>
              <template #title>
                <span class="task-title" @click="toggleExpand(task.id)">任务 #{{ task.id }}</span>
              </template>
              <template #label>
                <span @click="toggleExpand(task.id)">{{ formatTime(task.created_at) }}</span>
              </template>
              <template #value>
                <div class="task-meta" @click="toggleExpand(task.id)">
                  <van-tag :type="getStatusType(task.status)">
                    {{ getStatusText(task.status) }}
                  </van-tag>
                  <span class="task-count">{{ task.processed_images }}/{{ task.total_images }}</span>
                </div>
              </template>
              <template #right-icon>
                <van-icon
                  name="delete-o"
                  color="#ee0a24"
                  size="18"
                  @click.stop="confirmDeleteTask(task)"
                  style="margin-right:4px"
                />
                <van-icon :name="expandedTask === task.id ? 'arrow-up' : 'arrow-down'" @click.stop="toggleExpand(task.id)" />
              </template>
            </van-cell>

            <!-- ===== 展开的任务详情 ===== -->
            <!-- 显示该任务下所有识别结果缩略图 + 文字预览（截取前150字） -->
            <!-- 识别失败显示错误信息，底部提供导出按钮（MD/JSON/HTML） -->
            <div v-if="expandedTask === task.id" class="task-detail">
              <div v-if="taskResults[task.id]?.loading" class="loading-box">
                <van-loading size="24">加载中...</van-loading>
              </div>

              <div v-else-if="taskResults[task.id]?.results?.length > 0">
                <div
                  v-for="result in taskResults[task.id].results"
                  :key="result.id"
                  class="result-preview"
                >
                  <div class="result-name">{{ result.image_name }}</div>
                  <img
                    v-if="result.image_path"
                    :src="getResultImageUrl(result.image_path)"
                    class="result-thumb"
                    @click="previewResult(result)"
                  />
                  <div class="result-text" v-if="result.markdown_text">
                    {{ result.markdown_text.substring(0, 150) }}{{ result.markdown_text.length > 150 ? '...' : '' }}
                  </div>
                  <div class="result-error" v-if="result.status === 'failed'">
                    <van-icon name="warning-o" color="#ee0a24" /> {{ result.error_message || '识别失败' }}
                  </div>
                </div>

                <div class="export-row">
                  <van-button size="small" type="primary" @click="exportTask(task.id, 'markdown')">导出 MD</van-button>
                  <van-button size="small" type="primary" @click="exportTask(task.id, 'json')">导出 JSON</van-button>
                  <van-button size="small" type="primary" @click="exportTask(task.id, 'html')">导出 HTML</van-button>
                </div>
              </div>

              <van-empty v-else description="暂无结果" />
            </div>
          </div>
        </van-list>

        <van-empty v-else description="暂无识别记录" image="search" />
      </van-pull-refresh>
    </div>
  </div>
</template>

<script setup>
// ===== 依赖导入 =====
// Vue: ref(响应式), computed(计算属性), onMounted(生命周期)
// vant: showSuccessToast/showFailToast(轻提示), showDialog(确认弹窗)
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showSuccessToast, showFailToast, showDialog } from 'vant'
import { useOcrStore } from '../stores/ocr'
import api from '../api'

// ===== 路由与Store初始化 =====
const router = useRouter()           // 页面导航
const ocrStore = useOcrStore()       // OCR任务查询/导出

// ===== 响应式状态 =====
const tasks = ref([])                // 任务列表，每个元素附带 checked 用于批量删除
const refreshing = ref(false)        // 下拉刷新状态
const expandedTask = ref(null)       // 当前展开查看详情的任务ID
const taskResults = ref({})          // 已加载的结果缓存，{ [taskId]: { loading, results } }
const showPreview = ref(false)       // 图片预览弹窗显示状态
const previewImages = ref([])        // 预览图片URL数组
const previewIndex = ref(0)          // 预览起始索引
const batchMode = ref(false)         // 批量删除确认模式（切换后会显示确认/取消按钮）

// ===== 计算属性 =====
// 已勾选的任务ID数组，用于批量删除
const selectedTaskIds = computed(() => tasks.value.filter(t => t.checked).map(t => t.id))

// 全选状态（只读显示），通过 onSelectAll 手动同步
const allSelected = computed({
  get: () => tasks.value.length > 0 && tasks.value.every(t => t.checked),
  set: () => {}
})

// selectAll 与 allSelected 逻辑相同，作为v-model绑定的全选Checkbox数据源
const selectAll = computed({
  get: () => tasks.value.length > 0 && tasks.value.every(t => t.checked),
  set: () => {}
})

// ===== 工具函数 =====
// 格式化ISO时间为中文本地时间字符串
function formatTime(timeStr) {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  return date.toLocaleString('zh-CN')
}

// 任务状态 → Vant Tag type值映射（用于颜色）
function getStatusType(status) {
  const map = { pending: 'warning', processing: 'primary', completed: 'success', failed: 'danger' }
  return map[status] || 'default'
}

// 任务状态 → 中文显示文本
function getStatusText(status) {
  const map = { pending: '等待中', processing: '识别中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

// 将后端存储的图片路径（包含反斜杠）转换为前端静态资源URL
// 路径格式: "uploads\userId\filename" → "/uploads/userId/filename"
function getResultImageUrl(path) {
  if (!path) return ''
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/')
  const userId = parts[parts.length - 2]
  const filename = parts[parts.length - 1]
  return `/uploads/${userId}/${filename}`
}

// 全选/取消全选：同步所有任务的checked状态
function onSelectAll(checked) {
  tasks.value.forEach(t => { t.checked = checked })
}

function onTaskCheckChange(task) {
  task.checked = task.checked
}

// ===== 数据加载 =====
// 加载当前用户的所有历史任务，每个任务附带checked=false
async function loadTasks() {
  try {
    const res = await ocrStore.getTasks()
    tasks.value = (res.tasks || []).map(t => ({ ...t, checked: false }))
  } catch (e) {
    showFailToast('加载失败')
  }
}

// ===== 任务展开/折叠 =====
// 点击展开任务详情，首次展开时从后端加载该任务的识别结果（优先查all端点，fallback到普通端点）
async function toggleExpand(taskId) {
  if (expandedTask.value === taskId) {
    expandedTask.value = null
    return
  }

  expandedTask.value = taskId

  if (!taskResults.value[taskId]) {
    taskResults.value[taskId] = { loading: true, results: [] }
    try {
      const res = await api.get(`/api/ocr/results/all?task_id=${taskId}`)
      taskResults.value[taskId] = { loading: false, results: res.data.results || [] }
    } catch (e) {
      try {
        const res = await api.get(`/api/ocr/results?task_id=${taskId}`)
        taskResults.value[taskId] = { loading: false, results: res.data.results || [] }
      } catch (e2) {
        taskResults.value[taskId] = { loading: false, results: [] }
        showFailToast('加载结果失败')
      }
    }
  }
}

// ===== 导出操作 =====
// 导出当前任务的所有成功结果（过滤掉失败的），以指定格式下载
async function exportTask(taskId, format) {
  const data = taskResults.value[taskId]
  if (!data || !data.results || data.results.length === 0) {
    showFailToast('没有可导出的结果')
    return
  }

  try {
    const ids = data.results.filter(r => r.status === 'completed').map(r => r.id)
    if (ids.length === 0) {
      showFailToast('没有识别成功的结果可导出')
      return
    }
    await ocrStore.exportResults(ids, format)
    showSuccessToast('导出成功')
  } catch (e) {
    showFailToast('导出失败')
  }
}

// ===== 图片预览 =====
// 收集展开任务中所有带图片路径的结果，定位当前点击图片的索引，打开ImagePreview
function previewResult(result) {
  const images = taskResults.value[expandedTask.value]?.results
    .filter(r => r.image_path)
    .map(r => getResultImageUrl(r.image_path)) || []

  const index = images.findIndex(url => url.includes(result.image_name.split('\\').pop() || result.image_name))

  previewImages.value = images
  previewIndex.value = Math.max(0, index)
  showPreview.value = true
}

// ===== 删除操作 =====
// 删除单个任务：弹窗确认后调用后端删除，同步清理展开状态
async function confirmDeleteTask(task) {
  showDialog({
    title: '确认删除',
    message: `确定要删除 "任务 #${task.id}" 吗？所有识别结果将被一并删除。`
  }).then(async () => {
    try {
      await api.delete(`/api/ocr/tasks/${task.id}`)
      tasks.value = tasks.value.filter(t => t.id !== task.id)
      if (expandedTask.value === task.id) expandedTask.value = null
      showSuccessToast('已删除')
    } catch (e) {
      showFailToast('删除失败')
    }
  }).catch(() => {})
}

// 取消批量删除模式，重置所有任务的checked状态
function cancelBatch() {
  batchMode.value = false
  tasks.value.forEach(t => { t.checked = false })
}

// 确认批量删除：收集所有勾选任务ID，一次请求删除多个
async function confirmBatchDelete() {
  const ids = selectedTaskIds.value
  if (ids.length === 0) return
  showDialog({
    title: '批量删除',
    message: `确定要删除选中的 ${ids.length} 个任务吗？所有识别结果将被一并删除。`
  }).then(async () => {
    try {
      await api.post('/api/ocr/tasks/batch-delete', { ids })
      tasks.value = tasks.value.filter(t => !ids.includes(t.id))
      batchMode.value = false
      showSuccessToast(`已删除 ${ids.length} 个任务`)
    } catch (e) {
      showFailToast('删除失败')
    }
  }).catch(() => {})
}

// 下拉刷新：重新加载任务列表
async function onRefresh() {
  await loadTasks()
  refreshing.value = false
}

// 返回首页
function goBack() {
  router.push('/')
}

// ===== 生命周期 =====
// 挂载时自动加载历史任务列表
onMounted(() => {
  loadTasks()
})
</script>

<style scoped>
.history-page {
  min-height: 100vh;
  background: #f7f8fa;
}

.content {
  padding: 12px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: white;
  border-radius: 8px;
  margin-bottom: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}

.batch-tip {
  font-size: 13px;
  color: #ee0a24;
  font-weight: 500;
  flex: 1;
}

.task-title {
  cursor: pointer;
}

.task-card {
  background: white;
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.task-count {
  font-size: 13px;
  color: #999;
}

.task-detail {
  border-top: 1px solid #f5f5f5;
  padding: 12px;
}

.loading-box {
  display: flex;
  justify-content: center;
  padding: 20px;
}

.result-preview {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f5f5f5;
}

.result-preview:last-of-type {
  border-bottom: none;
}

.result-name {
  font-size: 13px;
  font-weight: 500;
  color: #333;
  margin-bottom: 6px;
}

.result-thumb {
  width: 100%;
  max-height: 150px;
  object-fit: contain;
  border-radius: 4px;
  background: #f5f5f5;
  cursor: pointer;
}

.result-text {
  font-size: 13px;
  line-height: 1.5;
  color: #666;
  margin-top: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}

.result-error {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #ee0a24;
  font-size: 13px;
  margin-top: 6px;
}

.export-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  justify-content: center;
}
</style>
