<template>
  <div class="admin-page">
    <van-nav-bar title="系统管理" left-arrow @click-left="goBack" fixed placeholder />

    <van-tabs v-model:active="activeTab" sticky offset-top="46">
      <!-- ===== Tab 1: 用户管理 ===== -->
      <!-- 搜索用户名过滤，显示用户列表（角色标签、状态标签），支持升降级/启用禁用/删除操作 -->
      <van-tab title="用户管理">
        <div class="tab-content">
          <van-search
            v-model="searchUsername"
            placeholder="搜索用户名"
            @search="onSearchUsers"
          />

          <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
            <div class="stats-bar">
              <span>共 {{ users.length }} 个用户</span>
              <span>管理员: {{ adminCount }} | 活跃: {{ activeCount }}</span>
            </div>

            <van-list v-if="users.length > 0" :finished="true">
              <van-cell
                v-for="user in users"
                :key="user.id"
                :title="user.username"
                :label="'创建: ' + formatTime(user.created_at)"
              >
                <template #right-icon>
                  <div class="user-actions">
                    <van-tag :type="user.role === 'admin' ? 'danger' : 'primary'" size="small">
                      {{ user.role === 'admin' ? '管理员' : '普通用户' }}
                    </van-tag>
                    <van-tag
                      :type="user.is_active ? 'success' : 'warning'"
                      size="small"
                      style="margin-left:4px"
                    >
                      {{ user.is_active ? '正常' : '已禁用' }}
                    </van-tag>
                    <van-dropdown-menu>
                      <van-dropdown-item :title="'操作'" :close-on-click-option="true">
                        <van-cell
                          v-if="user.id !== currentUserId"
                          :title="user.role === 'admin' ? '降为普通用户' : '升为管理员'"
                          icon="manager-o"
                          @click="toggleRole(user)"
                        />
                        <van-cell
                          v-if="user.id !== currentUserId"
                          :title="user.is_active ? '禁用' : '启用'"
                          :icon="user.is_active ? 'close' : 'success'"
                          @click="toggleStatus(user)"
                        />
                        <van-cell
                          v-if="user.id !== currentUserId"
                          title="删除"
                          icon="delete-o"
                          style="color:#ee0a24"
                          @click="confirmDelete(user)"
                        />
                      </van-dropdown-item>
                    </van-dropdown-menu>
                  </div>
                </template>
              </van-cell>
            </van-list>
            <van-empty v-else description="暂无用户" />
          </van-pull-refresh>
        </div>
      </van-tab>

      <!-- ===== Tab 2: 识别任务管理 ===== -->
      <!-- 搜索用户名过滤，任务卡片列表（可展开查看结果），支持单个/批量删除 -->
      <van-tab title="识别任务">
        <div class="tab-content">
          <van-search
            v-model="taskSearch"
            placeholder="搜索用户名"
            @search="onSearchTasks"
          />

          <!-- 批量操作栏 -->
          <div class="batch-bar" v-if="tasks.length > 0">
            <van-checkbox v-model="taskSelectAll" @change="onTaskSelectAll">全选</van-checkbox>
            <van-button v-if="taskSelectedIds.length > 0" size="small" type="danger" @click="confirmBatchDeleteTasks">
              批量删除 ({{ taskSelectedIds.length }})
            </van-button>
          </div>

          <van-pull-refresh v-model="taskRefreshing" @refresh="onTaskRefresh">
            <van-list v-if="tasks.length > 0" :finished="true">
              <div v-for="task in tasks" :key="task.id" class="task-card">
                <van-cell
                  :label="'用户: ' + (task.username || '未知') + ' | ' + formatTime(task.created_at)"
                >
                  <template #icon>
                    <van-checkbox
                      v-model="task.checked"
                      @click.stop
                      style="margin-right:8px"
                    />
                  </template>
                  <template #title>
                    <span class="task-title" @click="toggleAdminTaskExpand(task)">任务 #{{ task.id }}</span>
                  </template>
                  <template #label>
                    <span @click="toggleAdminTaskExpand(task)">用户: {{ task.username || '未知' }} | {{ formatTime(task.created_at) }}</span>
                  </template>
                  <template #value>
                    <div @click="toggleAdminTaskExpand(task)">
                      <van-tag :type="getTaskStatusType(task.status)">
                        {{ getTaskStatusText(task.status) }}
                      </van-tag>
                      <span style="margin-left:4px;font-size:12px;color:#999">
                        {{ task.processed_images }}/{{ task.total_images }}
                      </span>
                    </div>
                  </template>
                  <template #right-icon>
                    <van-icon
                      name="delete-o"
                      color="#ee0a24"
                      size="18"
                      @click.stop="confirmDeleteAdminTask(task)"
                      style="margin-right:4px"
                    />
                    <van-icon
                      :name="adminExpandedTask === task.id ? 'arrow-up' : 'arrow-down'"
                      @click.stop="toggleAdminTaskExpand(task)"
                    />
                  </template>
                </van-cell>

                <!-- 展开的结果列表 -->
                <div v-if="adminExpandedTask === task.id" class="task-detail">
                  <div v-if="adminTaskResults[task.id]?.loading" class="loading-box">
                    <van-loading size="24">加载中...</van-loading>
                  </div>
                  <div v-else-if="adminTaskResults[task.id]?.results?.length > 0">
                    <div
                      v-for="result in adminTaskResults[task.id].results"
                      :key="result.id"
                      class="result-item"
                    >
                      <span class="result-name">{{ result.image_name }}</span>
                      <van-tag :type="result.status === 'completed' ? 'success' : 'danger'" size="small">
                        {{ result.status === 'completed' ? '成功' : '失败' }}
                      </van-tag>
                      <van-icon
                        name="delete-o"
                        color="#ee0a24"
                        size="16"
                        style="cursor:pointer;margin-left:4px"
                        @click="confirmDeleteAdminResult(result, task.id)"
                      />
                      <div class="result-text" v-if="result.markdown_text">
                        {{ result.markdown_text.substring(0, 100) }}{{ result.markdown_text.length > 100 ? '...' : '' }}
                      </div>
                    </div>
                  </div>
                  <van-empty v-else description="暂无结果" />
                </div>
              </div>
            </van-list>
            <van-empty v-else description="暂无数据" />
          </van-pull-refresh>
        </div>
      </van-tab>

      <!-- ===== Tab 3: 识别结果管理 ===== -->
      <!-- 搜索用户名过滤，结果列表（状态标签），支持单个/批量删除 -->
      <van-tab title="识别结果">
        <div class="tab-content">
          <van-search
            v-model="resultSearch"
            placeholder="搜索用户名"
            @search="onSearchResults"
          />

          <!-- 批量操作栏 -->
          <div class="batch-bar" v-if="results.length > 0">
            <van-checkbox v-model="resultSelectAll" @change="onResultSelectAll">全选</van-checkbox>
            <van-button v-if="resultSelectedIds.length > 0" size="small" type="danger" @click="confirmBatchDeleteResults">
              批量删除 ({{ resultSelectedIds.length }})
            </van-button>
          </div>

          <van-pull-refresh v-model="resultRefreshing" @refresh="onResultRefresh">
            <van-list v-if="results.length > 0" :finished="true">
              <van-cell
                v-for="result in results"
                :key="result.id"
                :title="result.image_name"
                :label="'用户: ' + (result.username || '未知') + ' | ' + formatTime(result.created_at)"
              >
                <template #icon>
                  <van-checkbox
                    v-model="result.checked"
                    @click.stop
                    style="margin-right:8px"
                  />
                </template>
                <template #value>
                  <div class="result-action-row">
                    <van-tag :type="result.status === 'completed' ? 'success' : 'danger'" size="small">
                      {{ result.status === 'completed' ? '成功' : '失败' }}
                    </van-tag>
                    <van-icon
                      name="delete-o"
                      color="#ee0a24"
                      size="16"
                      style="cursor:pointer;margin-left:4px"
                      @click.stop="confirmDeleteAdminResult(result)"
                    />
                  </div>
                </template>
              </van-cell>
            </van-list>
            <van-empty v-else description="暂无数据" />
          </van-pull-refresh>
        </div>
      </van-tab>

      <!-- ===== Tab 4: 邀请码管理 ===== -->
      <!-- 生成新邀请码（可设使用次数），查看使用情况，启用/禁用/删除 -->
      <van-tab title="邀请码">
        <div class="tab-content">
          <div class="action-bar">
            <van-field
              v-model="newCodeMaxUses"
              type="digit"
              label="使用次数"
              placeholder="默认1次"
              style="width:120px"
            />
            <van-button size="small" type="primary" @click="createInvitationCode">
              生成邀请码
            </van-button>
          </div>

          <van-pull-refresh v-model="codeRefreshing" @refresh="onCodeRefresh">
            <van-list v-if="invitationCodes.length > 0" :finished="true">
              <van-cell
                v-for="code in invitationCodes"
                :key="code.id"
                :title="code.code"
                :label="`已使用: ${code.used_count}/${code.max_uses} | 创建: ${formatTime(code.created_at)}`"
              >
                <template #value>
                  <div class="code-actions">
                    <van-tag :type="code.is_active ? 'success' : 'danger'" size="small">
                      {{ code.is_active ? '有效' : '无效' }}
                    </van-tag>
                    <van-button
                      v-if="code.is_active"
                      size="mini"
                      plain
                      type="danger"
                      @click="disableInvitationCode(code)"
                    >
                      禁用
                    </van-button>
                    <van-button
                      v-else
                      size="mini"
                      plain
                      type="primary"
                      @click="enableInvitationCode(code)"
                    >
                      启用
                    </van-button>
                    <van-icon
                      name="delete-o"
                      color="#ee0a24"
                      size="18"
                      style="cursor:pointer; margin-left:4px"
                      @click="deleteInvitationCode(code)"
                    />
                  </div>
                </template>
              </van-cell>
            </van-list>
            <van-empty v-else description="暂无邀请码" />
          </van-pull-refresh>
        </div>
      </van-tab>

      <!-- ===== Tab 5: 系统统计概览 ===== -->
      <!-- 展示总用户/活跃用户/管理员/总任务/已完成任务/总结果，以卡片网格布局呈现 -->
      <van-tab title="统计">
        <div class="tab-content">
          <van-pull-refresh v-model="statsRefreshing" @refresh="onStatsRefresh">
            <div class="stats-grid">
              <div class="stat-card">
                <div class="stat-num">{{ stats.user_count }}</div>
                <div class="stat-label">总用户</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{{ stats.active_user_count }}</div>
                <div class="stat-label">活跃用户</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{{ stats.admin_count }}</div>
                <div class="stat-label">管理员</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{{ stats.task_count }}</div>
                <div class="stat-label">总任务</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{{ stats.completed_task_count }}</div>
                <div class="stat-label">已完成任务</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{{ stats.result_count }}</div>
                <div class="stat-label">总结果</div>
              </div>
            </div>
          </van-pull-refresh>
        </div>
      </van-tab>
    </van-tabs>
  </div>
</template>

<script setup>
// ===== 依赖导入 =====
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showSuccessToast, showFailToast, showDialog } from 'vant'
import { useUserStore } from '../stores/user'
import api from '../api'

// ===== 路由与Store初始化 =====
const router = useRouter()
const userStore = useUserStore()

// ===== Tab切换与搜索状态 =====
const activeTab = ref(0)                    // 当前激活的Tab索引，watch监听后自动加载对应数据
const searchUsername = ref('')             // 用户管理搜索关键词
const taskSearch = ref('')                 // 任务管理搜索关键词
const resultSearch = ref('')               // 结果管理搜索关键词

// ===== 下拉刷新状态 =====
const refreshing = ref(false)
const taskRefreshing = ref(false)
const resultRefreshing = ref(false)
const statsRefreshing = ref(false)
const codeRefreshing = ref(false)

// ===== 数据存储 =====
const users = ref([])                      // 用户列表
const tasks = ref([])                      // 任务列表（每个元素附带 checked 属性用于批量选择）
const results = ref([])                    // 识别结果列表（每个元素附带 checked 属性）
const stats = ref({ user_count: 0, active_user_count: 0, admin_count: 0, task_count: 0, completed_task_count: 0, result_count: 0, completed_result_count: 0 })
const invitationCodes = ref([])            // 邀请码列表
const newCodeMaxUses = ref('1')            // 新建邀请码允许的最大使用次数

// ===== 任务展开详情状态 =====
const adminExpandedTask = ref(null)        // 当前展开查看结果的任务ID（同一时间只有一个展开）
const adminTaskResults = ref({})           // 已加载的任务结果缓存，{ [taskId]: { loading, results } }

// ===== 计算属性 =====
// 当前登录用户ID，用于判断是否允许操作自身（不可删除/修改自己的角色）
const currentUserId = computed(() => userStore.userInfo?.id)

// 管理员数量统计，从用户列表实时计算
const adminCount = computed(() => users.value.filter(u => u.role === 'admin').length)

// 活跃用户数量统计
const activeCount = computed(() => users.value.filter(u => u.is_active).length)

// 任务批量选择：已勾选的任务ID数组（双向绑定computed，通过get/set与全选Checkbox联动）
const taskSelectedIds = computed(() => tasks.value.filter(t => t.checked).map(t => t.id))
const taskSelectAll = computed({
  get: () => tasks.value.length > 0 && tasks.value.every(t => t.checked),
  set: (val) => { tasks.value.forEach(t => { t.checked = val }) }
})

// 结果批量选择：已勾选的结果ID数组
const resultSelectedIds = computed(() => results.value.filter(r => r.checked).map(r => r.id))
const resultSelectAll = computed({
  get: () => results.value.length > 0 && results.value.every(r => r.checked),
  set: (val) => { results.value.forEach(r => { r.checked = val }) }
})

// ===== 工具函数 =====
// 格式化ISO时间字符串为中文可读格式
function formatTime(timeStr) {
  if (!timeStr) return ''
  return new Date(timeStr).toLocaleString('zh-CN')
}

// 将任务状态映射为Vant Tag组件的type属性值（用于颜色区分）
function getTaskStatusType(status) {
  const map = { pending: 'warning', processing: 'primary', completed: 'success', failed: 'danger' }
  return map[status] || 'default'
}

// 将任务状态映射为中文显示文本
function getTaskStatusText(status) {
  const map = { pending: '等待', processing: '进行中', completed: '完成', failed: '失败' }
  return map[status] || status
}

// ===== 数据加载函数 =====
// 加载用户列表，可选按用户名过滤
async function loadUsers(username = '') {
  let url = '/api/auth/users'
  if (username) url += `?username=${username}`
  const res = await api.get(url)
  users.value = res.data.users || []
}

// 加载任务列表，附带checked属性用于批量操作
async function loadTasks(username = '') {
  let url = '/api/admin/tasks'
  if (username) url += `?username=${username}`
  const res = await api.get(url)
  tasks.value = (res.data.tasks || []).map(t => ({ ...t, checked: false }))
}

// 加载识别结果列表，附带checked属性
async function loadResults(username = '') {
  let url = '/api/admin/results'
  if (username) url += `?username=${username}`
  const res = await api.get(url)
  results.value = (res.data.results || []).map(r => ({ ...r, checked: false }))
}

// 加载系统统计概览数据
async function loadStats() {
  const res = await api.get('/api/admin/stats')
  stats.value = res.data
}

// ===== 用户管理操作 =====
// 切换用户角色（管理员 ↔ 普通用户），不可操作自身
async function toggleRole(user) {
  try {
    const newRole = user.role === 'admin' ? 'user' : 'admin'
    await api.put(`/api/auth/users/${user.id}/role`, { role: newRole })
    user.role = newRole
    showSuccessToast(user.role === 'admin' ? '已设为管理员' : '已取消管理员')
  } catch (e) {
    showFailToast('操作失败')
  }
}

// 切换用户启用/禁用状态，不可禁用自身
async function toggleStatus(user) {
  try {
    const newStatus = !user.is_active
    await api.put(`/api/auth/users/${user.id}/status`, { is_active: newStatus })
    user.is_active = newStatus
    showSuccessToast(newStatus ? '已启用' : '已禁用')
  } catch (e) {
    showFailToast('操作失败')
  }
}

// 删除用户：二次确认后调用后端删除，不可恢复
async function confirmDelete(user) {
  showDialog({
    title: '确认删除',
    message: `确定要删除用户 "${user.username}" 吗？此操作不可恢复。`
  }).then(async () => {
    try {
      await api.delete(`/api/auth/users/${user.id}`)
      users.value = users.value.filter(u => u.id !== user.id)
      showSuccessToast('已删除')
    } catch (e) {
      showFailToast('删除失败')
    }
  })
}

function onSearchUsers() { loadUsers(searchUsername.value) }
function onSearchTasks() { loadTasks(taskSearch.value) }
function onSearchResults() { loadResults(resultSearch.value) }

async function onRefresh() { await loadUsers(); refreshing.value = false }
async function onTaskRefresh() { await loadTasks(); taskRefreshing.value = false }
async function onResultRefresh() { await loadResults(); resultRefreshing.value = false }
async function onStatsRefresh() { await loadStats(); statsRefreshing.value = false }
async function onCodeRefresh() { await loadInvitationCodes(); codeRefreshing.value = false }

function onTaskSelectAll(checked) {
  tasks.value.forEach(t => { t.checked = checked })
}

function onResultSelectAll(checked) {
  results.value.forEach(r => { r.checked = checked })
}

// ===== 任务管理操作 =====
// 展开/折叠任务以查看其识别结果详情，首次展开时从后端加载结果数据并缓存
async function toggleAdminTaskExpand(task) {
  if (adminExpandedTask.value === task.id) {
    adminExpandedTask.value = null
    return
  }
  adminExpandedTask.value = task.id
  if (!adminTaskResults.value[task.id]) {
    adminTaskResults.value[task.id] = { loading: true, results: [] }
    try {
      const res = await api.get(`/api/admin/tasks/${task.id}/results`)
      adminTaskResults.value[task.id] = { loading: false, results: res.data.results || [] }
    } catch (e) {
      adminTaskResults.value[task.id] = { loading: false, results: [] }
      showFailToast('加载结果失败')
    }
  }
}

// 删除单个任务：弹窗确认后删除，同步清理展开状态
async function confirmDeleteAdminTask(task) {
  showDialog({
    title: '确认删除',
    message: `确定要删除 "任务 #${task.id}" 吗？所有结果将被删除。`
  }).then(async () => {
    try {
      await api.delete(`/api/admin/tasks/${task.id}`)
      tasks.value = tasks.value.filter(t => t.id !== task.id)
      if (adminExpandedTask.value === task.id) adminExpandedTask.value = null
      showSuccessToast('已删除')
    } catch (e) {
      showFailToast('删除失败')
    }
  }).catch(() => {})
}

// 批量删除任务
// 批量删除任务：收集所有勾选的任务ID，一次请求删除多个
async function confirmBatchDeleteTasks() {
  const ids = taskSelectedIds.value
  if (ids.length === 0) return
  showDialog({
    title: '批量删除',
    message: `确定要删除选中的 ${ids.length} 个任务吗？`
  }).then(async () => {
    try {
      await api.post('/api/admin/tasks/batch-delete', { ids })
      tasks.value = tasks.value.filter(t => !ids.includes(t.id))
      showSuccessToast(`已删除 ${ids.length} 个任务`)
    } catch (e) {
      showFailToast('删除失败')
    }
  }).catch(() => {})
}

// 删除单个结果
// ===== 识别结果管理操作 =====
// 删除单个结果：若来自任务展开面板则同步清理缓存，否则从结果列表移除
async function confirmDeleteAdminResult(result, taskId) {
  showDialog({
    title: '确认删除',
    message: `确定要删除 "${result.image_name}" 的识别结果吗？`
  }).then(async () => {
    try {
      await api.delete(`/api/admin/results/${result.id}`)
      if (taskId && adminTaskResults.value[taskId]) {
        const arr = adminTaskResults.value[taskId].results
        adminTaskResults.value[taskId].results = arr.filter(r => r.id !== result.id)
      }
      results.value = results.value.filter(r => r.id !== result.id)
      showSuccessToast('已删除')
    } catch (e) {
      showFailToast('删除失败')
    }
  }).catch(() => {})
}

// 批量删除结果
// 批量删除结果：一次请求删除所有勾选的结果
async function confirmBatchDeleteResults() {
  const ids = resultSelectedIds.value
  if (ids.length === 0) return
  showDialog({
    title: '批量删除',
    message: `确定要删除选中的 ${ids.length} 个结果吗？`
  }).then(async () => {
    try {
      await api.post('/api/admin/results/batch-delete', { ids })
      results.value = results.value.filter(r => !ids.includes(r.id))
      showSuccessToast(`已删除 ${ids.length} 个结果`)
    } catch (e) {
      showFailToast('删除失败')
    }
  }).catch(() => {})
}

// 邀请码管理
// ===== 邀请码管理操作 =====
// 从后端加载所有邀请码及其使用状态
async function loadInvitationCodes() {
  try {
    const res = await api.get('/api/admin/invitation-codes/')
    invitationCodes.value = res.data.codes || []
  } catch (e) {
    showFailToast('加载邀请码失败')
  }
}

// 创建邀请码：可指定最大使用次数，新码插入列表顶部
async function createInvitationCode() {
  try {
    const maxUses = parseInt(newCodeMaxUses.value) || 1
    const res = await api.post('/api/admin/invitation-codes/', null, {
      params: { max_uses: maxUses }
    })
    invitationCodes.value.unshift(res.data)
    showSuccessToast(`邀请码 ${res.data.code} 已生成`)
  } catch (e) {
    showFailToast('生成邀请码失败')
  }
}

// 禁用邀请码：调用toggle接口，本地更新状态
async function disableInvitationCode(code) {
  try {
    await api.post(`/api/admin/invitation-codes/${code.id}/toggle`)
    code.is_active = false
    showSuccessToast('已禁用')
  } catch (e) {
    showFailToast('操作失败')
  }
}

// 启用邀请码：相同toggle接口，本地标记为有效
async function enableInvitationCode(code) {
  try {
    await api.post(`/api/admin/invitation-codes/${code.id}/toggle`)
    code.is_active = true
    showSuccessToast('已启用')
  } catch (e) {
    showFailToast('操作失败')
  }
}

// 删除邀请码：二次确认后从列表移除
async function deleteInvitationCode(code) {
  showDialog({
    title: '确认删除',
    message: `确定要删除邀请码 "${code.code}" 吗？`
  }).then(async () => {
    try {
      await api.delete(`/api/admin/invitation-codes/${code.id}`)
      invitationCodes.value = invitationCodes.value.filter(c => c.id !== code.id)
      showSuccessToast('已删除')
    } catch (e) {
      showFailToast('删除失败')
    }
  })
}

// 返回首页
function goBack() { router.push('/') }

// ===== Tab切换监听 =====
// 切换Tab时自动加载对应数据，避免一次性请求全部接口
watch(activeTab, (tab) => {
  if (tab === 0) loadUsers()
  else if (tab === 1) loadTasks()
  else if (tab === 2) loadResults()
  else if (tab === 3) loadInvitationCodes()
  else if (tab === 4) loadStats()
})

// ===== 生命周期 =====
// 首次加载默认显示用户管理Tab的数据
onMounted(() => {
  loadUsers()
})
</script>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: #f7f8fa;
}

.tab-content {
  padding: 12px;
}

.stats-bar {
  padding: 8px 16px;
  font-size: 13px;
  color: #666;
  display: flex;
  justify-content: space-between;
  background: #f5f5f5;
  border-radius: 4px;
  margin-bottom: 8px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff;
  border-radius: 8px;
  margin-bottom: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}

.task-card {
  background: white;
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}

.task-title {
  cursor: pointer;
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

.result-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f5f5f5;
  flex-wrap: wrap;
}

.result-item:last-child {
  border-bottom: none;
}

.result-name {
  font-size: 13px;
  font-weight: 500;
  color: #333;
  flex: 1;
  min-width: 120px;
}

.result-text {
  font-size: 12px;
  color: #999;
  width: 100%;
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-all;
}

.result-action-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.user-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  padding: 12px;
}

.stat-card {
  background: white;
  border-radius: 8px;
  padding: 20px 12px;
  text-align: center;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.stat-num {
  font-size: 28px;
  font-weight: 600;
  color: #1989fa;
}

.stat-label {
  font-size: 13px;
  color: #999;
  margin-top: 4px;
}

.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: #f5f5f5;
  border-radius: 8px;
  margin-bottom: 12px;
}

.code-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
