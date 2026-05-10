<template>
  <div class="app" :class="{ 'dark-mode': isDarkMode }">
    <!-- ===== 顶部导航栏 ===== -->
    <!-- 固定顶部栏：Logo + 功能入口（历史记录/管理后台） + 用户下拉菜单（修改密码） + 退出登录 -->
    <header class="header">
      <div class="header-left">
        <h1 class="logo">OCR 扫描工具</h1>
      </div>
      <div class="header-right">
        <van-button size="small" icon="clock-o" plain @click="goHistory">历史记录</van-button>
        <van-button
          v-if="userStore.isAdmin"
          size="small"
          icon="setting-o"
          plain
          type="primary"
          @click="goAdmin"
        >
          管理后台
        </van-button>
        <van-popover v-model:show="showUserMenu" trigger="click" placement="bottom-end" :actions="userMenuActions" @select="onUserMenuSelect">
          <template #reference>
            <span class="username" style="cursor:pointer">
              {{ userStore.userInfo?.username || '用户' }} <van-icon name="arrow-down" size="10" />
            </span>
          </template>
        </van-popover>
        <van-button size="small" plain @click="logout">退出</van-button>
      </div>
    </header>

    <!-- 主内容区 - 三栏布局 -->
    <main class="main-content">
      <!-- ===== 左侧面板：文件管理区 ===== -->
      <!-- 功能：文件上传（点击/拖拽）、排序（按名称/手动拖拽）、复选框选择、批量识别触发 -->
      <aside class="panel left-panel">
        <div class="panel-header">
          <h3>文件列表 ({{ uploadedFiles.length }})</h3>
          <div class="file-actions">
            <van-button size="small" type="primary" @click="triggerUpload">
              <van-icon name="plus" /> 添加
            </van-button>
            <van-button size="small" plain @click="clearAll" v-if="uploadedFiles.length > 0">
              清空
            </van-button>
          </div>
        </div>

        <!-- 排序栏 -->
        <div class="sort-bar" v-if="uploadedFiles.length > 1">
          <span class="sort-label">排序:</span>
          <van-radio-group v-model="sortMode" direction="horizontal" icon-size="14" @change="applySort">
            <van-radio name="name_asc">名称↑</van-radio>
            <van-radio name="name_desc">名称↓</van-radio>
            <van-radio name="manual">手动</van-radio>
          </van-radio-group>
        </div>

        <div class="panel-content file-list">
          <div v-if="uploadedFiles.length > 0">
            <div
              v-for="(file, index) in uploadedFiles"
              :key="file.id"
              class="file-item"
              :class="{
                active: currentFileId === file.id,
                draggable: sortMode === 'manual'
              }"
              :draggable="sortMode === 'manual'"
              @dragstart="onDragStart(index, $event)"
              @dragover.prevent="onDragOver(index, $event)"
              @drop="onDrop(index)"
            >
              <!-- 复选框 -->
              <div class="file-checkbox" @click.stop="toggleSelect(file.id)">
                <van-icon
                  :name="selectedIds.includes(file.id) ? 'checked' : 'circle'"
                  :color="selectedIds.includes(file.id) ? '#1989fa' : '#ccc'"
                  size="20"
                />
              </div>

              <!-- 拖拽手柄 -->
              <div class="file-drag-handle" v-if="sortMode === 'manual'">
                <van-icon name="bars" size="16" color="#c0c4cc" />
              </div>

              <!-- 缩略图 -->
              <div class="file-thumb" @click="previewFile(file)">
                <img :src="getImageUrl(file.image_path)" :alt="file.image_name" />
              </div>

              <!-- 文件信息 -->
              <div class="file-info" @click="previewFile(file)">
                <div class="file-name">{{ file.image_name }}</div>
                <div class="file-status" :class="file.status">
                  {{ getStatusText(file.status) }}
                  <span v-if="file.status === 'failed' && file.error_message" class="file-error-hint" :title="file.error_message">⚠</span>
                </div>
              </div>

              <!-- 重试按钮 -->
              <div class="file-item-actions">
                <van-icon
                  v-if="file.status === 'failed'"
                  name="replay"
                  color="#1989fa"
                  @click.stop="retryFile(file.id)"
                />
                <van-icon name="delete" color="#ee0a24" @click.stop="deleteFile(file.id)" />
              </div>
            </div>
          </div>

          <div v-else class="empty-hint">
            <van-icon name="upgrade" size="48" color="#ddd" />
            <p>拖放或点击添加按钮上传</p>
            <p class="hint-sub">支持 JPG, PNG, BMP, WebP, TIFF, PDF</p>
          </div>

          <!-- 操作按钮区 -->
          <div class="action-bar" v-if="uploadedFiles.length > 0">
            <div class="select-info" @click="toggleSelectAll">
              <van-icon
                :name="allSelected ? 'checked' : 'circle'"
                :color="allSelected ? '#1989fa' : '#ccc'"
                size="20"
              />
              <span>全选 ({{ selectedIds.length }}/{{ uploadedFiles.length }})</span>
            </div>
            <van-button
              type="primary"
              size="small"
              :loading="recognizing"
              :disabled="selectedIds.length === 0"
              @click="startRecognize"
            >
              {{ recognizing ? '识别中...' : '开始识别' }}
            </van-button>
          </div>
        </div>

        <!-- 暗黑模式切换 -->
        <div class="mode-toggle">
          <van-icon :name="isDarkMode ? 'moon-o' : 'sun-o'" size="20" />
          <span>{{ isDarkMode ? '夜间模式' : '日间模式' }}</span>
          <van-switch v-model="isDarkMode" size="20" />
        </div>
      </aside>

      <!-- ===== 中间面板：图片预览区 ===== -->
      <!-- 显示当前选中文件的缩略图，支持左旋/右旋90°（仅视觉旋转，不修改原图） -->
      <section class="panel center-panel">
        <div class="panel-header">
          <h3>预览</h3>
          <div class="preview-actions" v-if="currentPreview">
            <van-button size="small" plain @click="rotateImage(-90)">
              <van-icon name="arrow-left" /> 左旋
            </van-button>
            <van-button size="small" plain @click="rotateImage(90)">
              右旋 <van-icon name="arrow" />
            </van-button>
          </div>
        </div>
        <div class="panel-content preview-area">
          <div v-if="currentPreview" class="preview-container">
            <img
              :src="currentPreview.url"
              :alt="currentPreview.name"
              :style="{ transform: `rotate(${currentPreview.rotation}deg)` }"
              class="preview-image"
            />
            <div class="preview-name">{{ currentPreview.name }}</div>
          </div>
          <div v-else class="empty-hint">
            <van-icon name="photo" size="64" color="#ddd" />
            <p>选择图片或PDF进行预览</p>
          </div>
        </div>
      </section>

      <!-- ===== 右侧面板：OCR识别结果展示 ===== -->
      <!-- 将Markdown文本渲染为HTML显示，提供单页导出(MD/HTML/JSON)和整合下载(MD/HTML) -->
      <!-- 当识别失败时显示错误列表，方便用户排查问题文件 -->
      <aside class="panel right-panel">
        <div class="panel-header">
          <h3>识别结果</h3>
          <div class="export-actions" v-if="hasCompletedFiles">
            <div class="export-dropdown">
              <van-button size="small" type="primary" @click.stop="showMergeDropdown = !showMergeDropdown">
                <van-icon name="down" /> 整合下载 <van-icon name="arrow-down" />
              </van-button>
              <div class="dropdown-menu" v-if="showMergeDropdown">
                <div class="dropdown-item" @click="exportMerge('markdown'); showMergeDropdown = false">Markdown</div>
                <div class="dropdown-item" @click="exportMerge('html'); showMergeDropdown = false">HTML</div>
              </div>
            </div>
            <div class="export-dropdown" v-if="currentResult">
              <van-button size="small" plain @click.stop="showExportDropdown = !showExportDropdown">
                下载本页 <van-icon name="arrow-down" />
              </van-button>
              <div class="dropdown-menu" v-if="showExportDropdown">
                <div class="dropdown-item" @click="exportSingleResult('markdown')">Markdown</div>
                <div class="dropdown-item" @click="exportSingleResult('html')">HTML</div>
                <div class="dropdown-item" @click="exportSingleResult('json')">JSON</div>
              </div>
            </div>
          </div>
        </div>
        <div class="panel-content result-content">
          <div v-if="currentResult" class="result-display">
            <div class="result-name">{{ currentResult.image_name }}</div>
            <div class="result-html" v-html="renderHtml(currentResult.markdown_text)"></div>
          </div>
          <div v-else-if="hasErrors" class="error-list">
            <div v-for="(err, index) in ocrErrors" :key="index" class="error-item">
              <van-icon name="warning-o" color="#ee0a24" />
              <span class="error-name">{{ err.name }}:</span>
              <span class="error-msg">{{ err.message }}</span>
            </div>
          </div>
          <div v-else class="empty-hint">
            <van-icon name="description" size="48" color="#ddd" />
            <p>点击已识别的文件查看结果</p>
          </div>
        </div>
      </aside>
    </main>

    <!-- ===== 隐藏输入与弹窗层 ===== -->
    <!-- 隐藏的文件上传input：通过"添加"按钮触发点击，支持多选，限制图片和PDF格式 -->
    <input
      type="file"
      ref="fileInput"
      multiple
      accept=".jpg,.jpeg,.png,.bmp,.webp,.tiff,.tif,.pdf"
      style="display: none"
      @change="handleFileUpload"
    />

    <!-- 识别进度弹窗 -->
    <van-dialog
      v-model:show="showProgress"
      title="识别进度"
      :show-cancel-button="false"
      :close-on-click-overlay="false"
    >
      <div class="progress-content">
        <van-progress
          :percentage="progressPercentage"
          stroke-width="8"
          :show-pivot="true"
        />
        <p class="progress-text">{{ progressText }}</p>
      </div>
    </van-dialog>

    <!-- 上传进度弹窗 -->
    <van-dialog
      v-model:show="showUploadProgress"
      title="正在上传"
      :show-cancel-button="false"
      :close-on-click-overlay="false"
    >
      <div class="progress-content">
        <van-loading size="32" vertical>{{ uploadProgressText }}</van-loading>
      </div>
    </van-dialog>

    <!-- 修改密码弹窗 -->
    <van-dialog
      v-model:show="showPasswordDialog"
      title="修改密码"
      show-cancel-button
      @confirm="doChangePassword"
    >
      <div class="password-form">
        <van-field v-model="pwdOld" type="password" label="原密码" placeholder="请输入原密码" />
        <van-field v-model="pwdNew" type="password" label="新密码" placeholder="请输入新密码(≥6位)" />
      </div>
    </van-dialog>
  </div>
</template>

<script>
export default { name: 'Home' }
</script>
<script setup>
// ===== 依赖导入 =====
// Vue核心：ref(响应式变量), computed(计算属性), onMounted/onUnmounted(生命周期), nextTick(DOM更新后), watch(监听)
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showSuccessToast, showFailToast } from 'vant'
import { useUserStore } from '../stores/user'
import { useOcrStore } from '../stores/ocr'
import api from '../api'

// ===== 路由与Store初始化 =====
// router: 页面跳转; userStore: 用户认证/权限; ocrStore: OCR任务提交/查询
const router = useRouter()
const userStore = useUserStore()
const ocrStore = useOcrStore()

// ===== 响应式状态定义 =====
// -- UI状态 --
const isDarkMode = ref(false)            // 暗黑模式切换，通过CSS变量实现主题换肤
// -- 文件数据 --
const uploadedFiles = ref([])            // 当前会话已上传的所有文件列表
const selectedIds = ref([])              // 用户勾选的文件ID数组，用于批量识别
const currentFileId = ref(null)          // 当前选中的文件ID，影响左侧高亮和中间预览
// -- 预览相关 --
const currentPreview = ref(null)         // 当前预览信息 { url, name, rotation }
// -- 识别结果 --
const currentResult = ref(null)          // 右侧面板当前展示的识别结果
const fileResults = ref({})              // 以fileId为key的结果缓存，{ [id]: resultObject }
const ocrErrors = ref([])                // 识别失败列表，格式化后供错误面板展示
// -- 识别任务状态 --
const recognizing = ref(false)           // 是否正在提交/执行识别任务
const showProgress = ref(false)          // 是否显示进度弹窗
const progressPercentage = ref(0)        // 轮询进度百分比
const progressText = ref('')             // 进度文字描述
// -- 导出下拉菜单 --
const showExportDropdown = ref(false)    // 单页导出下拉菜单显示状态
const showMergeDropdown = ref(false)     // 整合下载下拉菜单显示状态
// -- 文件上传 --
const fileInput = ref(null)              // 隐藏的file input DOM引用，用于程序化触发文件选择
// -- 排序 --
const sortMode = ref('name_asc')         // 排序模式: name_asc/name_desc/manual
// -- 上传进度 --
const showUploadProgress = ref(false)    // 上传进度弹窗显示
const uploadProgressText = ref('')       // 上传进度文字
// -- 用户操作 --
const showUserMenu = ref(false)          // 用户下拉菜单（修改密码入口）
const showPasswordDialog = ref(false)    // 修改密码弹窗
const pwdOld = ref('')                   // 原密码输入
const pwdNew = ref('')                   // 新密码输入
// ===== 定时器和临时变量（非响应式） =====
let pollTimer = null              // OCR轮询定时器ID，每秒查询任务进度
let renderMathTimer = null        // 数学公式渲染重试定时器，等待KaTeX加载
let renderMathAttempts = 0        // 渲染重试计数，超过15次放弃
const retryTimers = []            // 重试轮询定时器数组，组件销毁时统一清理

// ===== 计算属性 =====
const allSelected = computed(() => {
  return uploadedFiles.value.length > 0 && selectedIds.value.length === uploadedFiles.value.length
})

const hasErrors = computed(() => ocrErrors.value.length > 0)

const hasCompletedFiles = computed(() => {
  return Object.values(fileResults.value).some(r => r.status === 'completed')
})

const userMenuActions = computed(() => [
  { text: '修改密码', icon: 'edit' }
])

// ===== 用户菜单 =====
function onUserMenuSelect(action) {
  showUserMenu.value = false
  if (action.text === '修改密码') {
    pwdOld.value = ''
    pwdNew.value = ''
    showPasswordDialog.value = true
  }
}

async function doChangePassword() {
  if (!pwdOld.value || !pwdNew.value) {
    showFailToast('请填写完整')
    return
  }
  if (pwdNew.value.length < 6) {
    showFailToast('新密码至少6位')
    return
  }
  try {
    await userStore.changePassword(pwdOld.value, pwdNew.value)
    showSuccessToast('密码修改成功')
  } catch (e) {
    showFailToast(e.response?.data?.detail || '密码修改失败')
  }
}

// ===== 数学公式渲染（KaTeX/MathJax） =====
// 等待window.renderMathInElement可用后渲染，最多重试15次（每次间隔200ms）
function renderMathInResult() {
  clearTimeout(renderMathTimer)
  renderMathAttempts = 0
  renderMathTimer = setTimeout(() => {
    const el = document.querySelector('.result-html')
    if (!el) return
    if (!window.renderMathInElement) {
      if (renderMathAttempts++ > 15) return
      renderMathTimer = setTimeout(renderMathInResult, 200)
      return
    }
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: '\\(', right: '\\)', display: false },
          { left: '\\[', right: '\\]', display: true }
        ],
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      })
    } catch (e) { /* ignore */ }
  }, 150)
}

// 监听当前结果变化，在DOM更新后触发数学公式渲染
watch(currentResult, () => {
  nextTick(() => renderMathInResult())
})

// ===== 文件选择操作 =====
// 切换单个文件的勾选状态：已选则移除，未选则添加
function toggleSelect(fileId) {
  const idx = selectedIds.value.indexOf(fileId)
  if (idx === -1) {
    selectedIds.value.push(fileId)
  } else {
    selectedIds.value.splice(idx, 1)
  }
}

// 全选/取消全选：如果已全部选中则清空，否则选中所有文件
function toggleSelectAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = uploadedFiles.value.map(f => f.id)
  }
}

// ===== 拖拽排序 =====
let dragIndex = -1

function onDragStart(index, event) {
  if (sortMode.value !== 'manual') return
  dragIndex = index
  event.dataTransfer.effectAllowed = 'move'
}

function onDragOver(index, event) {
  event.dataTransfer.dropEffect = 'move'
}

function onDrop(targetIndex) {
  if (dragIndex === -1 || dragIndex === targetIndex) return
  const arr = [...uploadedFiles.value]
  const [item] = arr.splice(dragIndex, 1)
  arr.splice(targetIndex, 0, item)
  uploadedFiles.value = arr
  dragIndex = -1
}

// ===== 工具方法 =====
function getImageUrl(path) {
  if (!path) return ''
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/')
  const userId = parts[parts.length - 2]
  const filename = parts[parts.length - 1]
  return `/uploads/${userId}/${filename}`
}

function getStatusText(status) {
  const map = {
    uploaded: '已上传', pending: '待识别', processing: '识别中',
    completed: '已识别', failed: '失败'
  }
  return map[status] || status
}

function _naturalKey(text) {
  return text.replace(/\d+/g, m => m.padStart(10, '0'))
}

function applySort() {
  if (sortMode.value === 'name_asc') {
    uploadedFiles.value.sort((a, b) => _naturalKey(a.image_name).localeCompare(_naturalKey(b.image_name)))
  } else if (sortMode.value === 'name_desc') {
    uploadedFiles.value.sort((a, b) => _naturalKey(b.image_name).localeCompare(_naturalKey(a.image_name)))
  }
}

// 渲染 Markdown → HTML（支持标题、公式、表格、图片）
function renderHtml(text) {
  if (!text) return ''

  let html = text

  // 1. 保护代码块
  const codeBlocks = []
  html = html.replace(/```[\s\S]*?```/g, match => {
    codeBlocks.push(match)
    return `__CODE_BLOCK_${codeBlocks.length - 1}__`
  })

  // 2. 保护行内代码
  const inlineCodes = []
  html = html.replace(/`([^`]+)`/g, (match, code) => {
    inlineCodes.push(code)
    return `__INLINE_CODE_${inlineCodes.length - 1}__`
  })

  // 2.5. 包裹裸 LaTeX 标记（PaddleOCR-VL 在表格 <td> 中输出 _{}、^{} 、\command 等不带 $ 定界符的 LaTeX）
  html = html.replace(/(>)([^<]*?[_^{}\\]{1,3}[^<]*?)(<)/g, (m, open, content, close) => {
    if (!content.trim() || content.includes('$')) return m
    return open + '$' + content.trim() + '$' + close
  })

  // 3. 保护显示公式 $$...$$
  const mathBlocks = []
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, (match, math) => {
    mathBlocks.push({ display: true, math: math.trim() })
    return `__MATH_BLOCK_${mathBlocks.length - 1}__`
  })

  // 4. 保护行内公式 $...$
  // 跳过含 # & 的内容（PaddleOCR-VL 会将标题、HTML 实体误包进 $，导致 KaTeX 报错）
  const mathInline = []
  html = html.replace(/\$\s*(\S[^$]*?)\s*\$/g, (match, math) => {
    const cleaned = math.trim()
    if (/[#&]/.test(cleaned)) return cleaned
    mathInline.push({ display: false, math: cleaned })
    return `__MATH_INLINE_${mathInline.length - 1}__`
  })

  // 5. Markdown → HTML（图片必须在链接之前）
  html = html.replace(/^###### (.*$)/gim, '<h6>$1</h6>')
  html = html.replace(/^##### (.*$)/gim, '<h5>$1</h5>')
  html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>')
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>')
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>')
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>')
  html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<b><i>$1</i></b>')
  html = html.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
  html = html.replace(/\*(.*?)\*/g, '<i>$1</i>')
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, src) => `<img src="${escapeHtml(src)}" alt="${escapeHtml(alt)}" style="max-width:100%">`)
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
  html = html.replace(/^---$/gim, '<hr>')
  html = html.replace(/^\s*[-*+]\s+(.*$)/gim, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`)

  // 6. 恢复公式（用 KaTeX 定界符）
  mathBlocks.forEach((item, i) => {
    html = html.replace(`__MATH_BLOCK_${i}__`, `\\[${escapeHtml(item.math)}\\]`)
  })
  mathInline.forEach((item, i) => {
    html = html.replace(`__MATH_INLINE_${i}__`, `\\(${escapeHtml(item.math)}\\)`)
  })

  // 7. 恢复代码
  inlineCodes.forEach((code, i) => {
    html = html.replace(`__INLINE_CODE_${i}__`, `<code>${escapeHtml(code)}</code>`)
  })
  codeBlocks.forEach((block, i) => {
    const content = block.replace(/```(\w*)\n?/, '').replace(/```$/, '')
    html = html.replace(`__CODE_BLOCK_${i}__`, `<pre><code>${escapeHtml(content)}</code></pre>`)
  })

  // 8. 段落处理：含 HTML 标签/闭合标签的行不包装 <p>
  const htmlBlockRe = /^\s*<\/?(?:table|tr|t[dh]|thead|tbody|tfoot|caption|colgroup|col|div|h[1-6]|ul|ol|li|hr|pre|blockquote|p|img|br)[\s>]/
  html = html.split('\n').map(line => {
    if (!line.trim()) return ''
    if (htmlBlockRe.test(line)) return line
    if (/^\s*<\//.test(line)) return line
    if (/<\/[a-zA-Z][a-zA-Z0-9]*\s*>/.test(line)) return line
    return `<p>${line}</p>`
  }).join('\n')
  html = html.replace(/<p><\/p>/g, '')

  return html
}

function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

// ===== 文件操作 =====
async function loadFiles() {
  try {
    const res = await ocrStore.getUploadedImages()
    uploadedFiles.value = res.results || []
    applySort()
  } catch (e) {
    console.error('加载文件失败', e)
  }
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileUpload(event) {
  const files = Array.from(event.target.files)
  if (files.length === 0) return

  showUploadProgress.value = true
  uploadProgressText.value = `正在上传 ${files.length} 个文件...`

  const formData = new FormData()
  files.forEach(f => formData.append('files', f))

  try {
    const res = await api.post('/api/upload/images', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    const newFiles = res.data
    uploadedFiles.value = [...newFiles, ...uploadedFiles.value]
    selectedIds.value = [...selectedIds.value, ...newFiles.map(f => f.id)]
    applySort()
    showSuccessToast(`成功上传 ${files.length} 个文件`)
  } catch (e) {
    showFailToast(e.response?.data?.detail || '上传失败')
  } finally {
    showUploadProgress.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function previewFile(file) {
  currentFileId.value = file.id
  currentPreview.value = {
    url: getImageUrl(file.image_path),
    name: file.image_name,
    rotation: 0
  }

  if (fileResults.value[file.id]) {
    currentResult.value = fileResults.value[file.id]
    ocrErrors.value = []
  } else if (file.status === 'completed') {
    loadFileResult(file.id)
  } else if (file.status === 'failed' && file.error_message) {
    ocrErrors.value = [{ name: file.image_name, message: file.error_message }]
    currentResult.value = null
  } else {
    currentResult.value = null
    ocrErrors.value = []
  }
}

async function loadFileResult(fileId) {
  try {
    const res = await api.get('/api/ocr/results/all?task_id=0')
    const results = res.data.results || []
    const found = results.find(r => r.id === fileId)
    if (found) {
      fileResults.value[fileId] = found
      if (currentFileId.value === fileId) {
        currentResult.value = found
        ocrErrors.value = []
      }
    }
  } catch (e) {
    console.error('加载结果失败', e)
  }
}

function rotateImage(degrees) {
  if (currentPreview.value) {
    currentPreview.value.rotation = (currentPreview.value.rotation + degrees) % 360
  }
}

// ===== 文件操作：重试/删除/清空 =====
// 对识别失败的文件发起重新识别请求，提交后启动独立轮询监控重试结果
async function retryFile(fileId) {
  try {
    showSuccessToast('开始重试识别...')
    const task = await api.post('/api/ocr/retry', { image_ids: [fileId] })

    // 标记为重试中
    const file = uploadedFiles.value.find(f => f.id === fileId)
    if (file) file.status = 'processing'

    // 轮询结果
    const taskId = task.data.id
    const retryTimer = setInterval(async () => {
      try {
        const taskInfo = await ocrStore.getTask(taskId)
        if (taskInfo.status === 'completed') {
          clearInterval(retryTimer)
          showSuccessToast('重试成功')
          await loadFileResult(fileId)
          if (currentFileId.value === fileId) {
            previewFile(file)
          }
        } else if (taskInfo.status === 'failed') {
          clearInterval(retryTimer)
          const res = await api.get(`/api/ocr/results/all?task_id=${taskId}`)
          const result = res.data.results?.find(r => r.id === fileId)
          if (result && file) {
            file.status = 'failed'
            file.error_message = result.error_message
          }
          showFailToast('重试失败')
        }
      } catch (e) {
        console.error('重试轮询失败', e)
      }
    }, 1000)
    retryTimers.push(retryTimer)
  } catch (e) {
    console.error('重试失败', e)
    showFailToast(e.response?.data?.detail || '重试失败')
  }
}

// 删除单个文件：调用后端删除接口，同步清理本地所有关联状态（列表、选择、结果、预览）
async function deleteFile(fileId) {
  try {
    await ocrStore.deleteImage(fileId)
    uploadedFiles.value = uploadedFiles.value.filter(f => f.id !== fileId)
    selectedIds.value = selectedIds.value.filter(id => id !== fileId)
    delete fileResults.value[fileId]
    if (currentFileId.value === fileId) {
      currentFileId.value = null
      currentPreview.value = null
      currentResult.value = null
    }
    showSuccessToast('已删除')
  } catch (e) {
    showFailToast('删除失败')
  }
}

// 清空所有文件：重置整个会话状态，不调用后端（仅前端清理）
function clearAll() {
  uploadedFiles.value = []
  selectedIds.value = []
  currentFileId.value = null
  currentPreview.value = null
  currentResult.value = null
  fileResults.value = {}
  ocrErrors.value = []
}

// ===== OCR识别：提交任务 + 轮询进度 =====
// 将选中的文件提交为OCR任务，每1秒轮询进度，完成/失败后停止轮询并加载结果
async function startRecognize() {
  if (selectedIds.value.length === 0) {
    showFailToast('请至少选择一个文件')
    return
  }

  recognizing.value = true
  showProgress.value = true
  progressPercentage.value = 0
  progressText.value = '准备开始识别...'
  ocrErrors.value = []
  currentResult.value = null

  try {
    const task = await ocrStore.submitTask(selectedIds.value)
    const taskId = task.id

    selectedIds.value.forEach(id => {
      const file = uploadedFiles.value.find(f => f.id === id)
      if (file) file.status = 'processing'
    })

    pollTimer = setInterval(async () => {
      try {
        const taskInfo = await ocrStore.getTask(taskId)
        progressPercentage.value = taskInfo.total_images > 0
          ? Math.round(taskInfo.processed_images / taskInfo.total_images * 100)
          : 0
        progressText.value = `已处理 ${taskInfo.processed_images}/${taskInfo.total_images} 张`

        if (taskInfo.status === 'completed') {
          clearInterval(pollTimer)
          showProgress.value = false
          recognizing.value = false
          showSuccessToast('识别完成')

          await loadTaskResults(taskId)

          const completedIds = Object.keys(fileResults.value).map(Number)
          selectedIds.value.forEach(id => {
            const file = uploadedFiles.value.find(f => f.id === id)
            if (file) {
              file.status = completedIds.includes(id) ? 'completed' : 'failed'
            }
          })

          const firstResult = Object.values(fileResults.value)[0]
          if (firstResult) {
            const firstFile = uploadedFiles.value.find(f => f.id === firstResult.id)
            if (firstFile) previewFile(firstFile)
          }
        } else if (taskInfo.status === 'failed') {
          clearInterval(pollTimer)
          showProgress.value = false
          recognizing.value = false
          await loadTaskResults(taskId)
          showFailToast('识别失败，请查看结果面板')
        }
      } catch (e) {
        console.error('轮询失败', e)
      }
    }, 1000)
  } catch (e) {
    showProgress.value = false
    recognizing.value = false
    showFailToast(e.response?.data?.detail || '提交任务失败')
  }
}

// 加载某个任务的所有结果，更新fileResults缓存和对应文件状态，提取失败列表
async function loadTaskResults(taskId) {
  try {
    const res = await api.get(`/api/ocr/results/all?task_id=${taskId}`)
    const allResults = res.data.results || []

    allResults.forEach(r => {
      fileResults.value[r.id] = r
      const file = uploadedFiles.value.find(f => f.id === r.id)
      if (file) {
        file.status = r.status
        file.error_message = r.error_message
      }
    })

    ocrErrors.value = allResults
      .filter(r => r.status === 'failed')
      .map(r => ({ name: r.image_name, message: r.error_message || '未知错误' }))
  } catch (e) {
    console.error('加载结果失败', e)
  }
}

// ===== 导出下载 =====
// 导出单个结果：以blob形式下载，自动触发浏览器下载并显示成功提示
async function exportSingleResult(format) {
  showExportDropdown.value = false
  if (!currentResult.value) { showFailToast('没有可导出的结果'); return }

  try {
    const response = await api.post('/api/export/download', {
      result_ids: [currentResult.value.id],
      format: format
    }, { responseType: 'blob' })

    const blob = new Blob([response.data])
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ocr_result.${format === 'markdown' ? 'md' : format}`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    showSuccessToast('下载成功')
  } catch (e) {
    console.error('下载失败', e)
    showFailToast('下载失败')
  }
}

// 整合导出：将所有已完成的结果打包为zip，统一命名"ocr_merged.{格式}.zip"
async function exportMerge(format) {
  const completedIds = Object.entries(fileResults.value)
    .filter(([id, r]) => r.status === 'completed')
    .map(([id]) => parseInt(id))

  if (completedIds.length === 0) { showFailToast('没有已识别的结果'); return }

  try {
    const response = await api.post('/api/export/merge', {
      result_ids: completedIds,
      format: format
    }, { responseType: 'blob' })

    const blob = new Blob([response.data])
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ocr_merged.${format === 'markdown' ? 'md' : format}.zip`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    showSuccessToast('整合下载成功')
  } catch (e) {
    console.error('整合下载失败', e)
    showFailToast('整合下载失败')
  }
}

// ===== 页面导航 =====
// 跳转到历史记录页面
function goHistory() {
  router.push('/history')
}

// 跳转到管理后台（仅管理员可见入口）
function goAdmin() {
  router.push('/admin')
}

// 退出登录：清除用户状态并重定向到登录页
function logout() {
  userStore.logout()
  router.push('/login')
}

// 点击导出菜单外部区域时自动收起下拉菜单
function handleClickOutside(e) {
  if (!e.target.closest('.export-dropdown')) {
    showExportDropdown.value = false
    showMergeDropdown.value = false
  }
}

// ===== 生命周期钩子 =====
// 挂载时：加载文件列表、获取用户信息、注册全局点击监听（用于关闭导出下拉菜单）
onMounted(() => {
  loadFiles()
  userStore.getUserInfo()
  document.addEventListener('click', handleClickOutside)
})

// 销毁时：清除所有定时器（轮询/渲染重试/重试轮询），移除全局事件监听，防止内存泄漏
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (renderMathTimer) clearTimeout(renderMathTimer)
  retryTimers.forEach(clearInterval)
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
.app {
  --bg-color: #f5f7fa;
  --panel-bg: #ffffff;
  --text-color: #333333;
  --text-secondary: #666666;
  --border-color: #e4e7ed;
  --hover-bg: #f5f7fa;
  --active-bg: #ecf5ff;
  --shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}
.dark-mode {
  --bg-color: #1a1a1a;
  --panel-bg: #2d2d2d;
  --text-color: #e0e0e0;
  --text-secondary: #aaaaaa;
  --border-color: #444444;
  --hover-bg: #3d3d3d;
  --active-bg: #1a3a5c;
  --shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}
.app { min-height: 100vh; background: var(--bg-color); color: var(--text-color); }

.header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 24px; background: var(--panel-bg);
  border-bottom: 1px solid var(--border-color); box-shadow: var(--shadow);
}
.header-left .logo { margin: 0; font-size: 18px; font-weight: 600; }
.header-right { display: flex; align-items: center; gap: 12px; }
.username { font-size: 14px; color: var(--text-secondary); }

.main-content { display: flex; height: calc(100vh - 60px); }
.panel {
  display: flex; flex-direction: column; background: var(--panel-bg);
  border-right: 1px solid var(--border-color);
}
.panel-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--border-color);
}
.panel-header h3 { margin: 0; font-size: 14px; font-weight: 600; }
.panel-content { flex: 1; overflow-y: auto; padding: 12px; }

.left-panel { width: 300px; min-width: 250px; }
.file-actions { display: flex; gap: 8px; }
.sort-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; border-bottom: 1px solid var(--border-color);
  background: var(--hover-bg); font-size: 12px;
}
.sort-label { color: var(--text-secondary); flex-shrink: 0; }

.file-list { flex: 1; display: flex; flex-direction: column; }
.file-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 6px; cursor: pointer;
  transition: all 0.2s; border: 2px solid transparent;
  margin-bottom: 4px;
}
.file-item:hover { background: var(--hover-bg); }
.file-item.active { background: var(--active-bg); border-color: #1989fa; }
.file-item.draggable { cursor: grab; }
.file-item.draggable:active { cursor: grabbing; opacity: 0.7; }

.file-checkbox { flex-shrink: 0; cursor: pointer; display: flex; align-items: center; }
.file-drag-handle { flex-shrink: 0; cursor: grab; }
.file-thumb {
  width: 48px; height: 48px; border-radius: 4px;
  overflow: hidden; flex-shrink: 0;
}
.file-thumb img { width: 100%; height: 100%; object-fit: cover; }
.file-info { flex: 1; min-width: 0; }
.file-name {
  font-size: 13px; font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.file-status { font-size: 11px; margin-top: 2px; display: flex; align-items: center; gap: 4px; }
.file-status.uploaded { color: #909399; }
.file-status.pending { color: #e6a23c; }
.file-status.processing { color: #409eff; }
.file-status.completed { color: #67c23a; }
.file-status.failed { color: #f56c6c; }
.file-error-hint { cursor: help; font-size: 13px; }
.file-item-actions { flex-shrink: 0; }
.file-item-actions .van-icon { cursor: pointer; }

.action-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; margin-top: auto;
  border-top: 1px solid var(--border-color);
}
.select-info {
  display: flex; align-items: center; gap: 6px;
  cursor: pointer; font-size: 13px; color: var(--text-secondary);
}

.mode-toggle {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; border-top: 1px solid var(--border-color);
  font-size: 13px; color: var(--text-secondary);
}

.center-panel { flex: 1; min-width: 400px; }
.preview-area {
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-color);
}
.preview-container { text-align: center; }
.preview-image {
  max-width: 100%; max-height: calc(100vh - 200px);
  object-fit: contain; border-radius: 4px; box-shadow: var(--shadow);
  transition: transform 0.3s ease;
}
.preview-name { margin-top: 12px; font-size: 13px; color: var(--text-secondary); }
.preview-actions { display: flex; gap: 8px; }

.right-panel { width: 35%; min-width: 300px; }
.export-actions { display: flex; gap: 6px; align-items: center; }
.export-dropdown { position: relative; }
.dropdown-menu {
  position: absolute; top: 100%; right: 0;
  background: var(--panel-bg); border: 1px solid var(--border-color);
  border-radius: 4px; box-shadow: var(--shadow);
  z-index: 100; min-width: 140px;
}
.dropdown-item { padding: 8px 16px; cursor: pointer; font-size: 13px; }
.dropdown-item:hover { background: var(--hover-bg); }

.result-display { height: 100%; }
.result-name {
  padding: 8px 12px; background: var(--hover-bg);
  font-size: 13px; font-weight: 500;
  border-radius: 6px 6px 0 0; border-bottom: 1px solid var(--border-color);
}
.result-html {
  padding: 12px; font-size: 14px; line-height: 1.6;
  border: 1px solid var(--border-color);
  border-radius: 0 0 6px 6px; border-top: none;
}
.result-html :deep(h1) { font-size: 1.5em; font-weight: 600; margin: 0.5em 0; }
.result-html :deep(h2) { font-size: 1.3em; font-weight: 600; margin: 0.5em 0; }
.result-html :deep(h3) { font-size: 1.1em; font-weight: 600; margin: 0.5em 0; }
.result-html :deep(h4), .result-html :deep(h5), .result-html :deep(h6) { font-size: 1em; font-weight: 600; margin: 0.5em 0; }
.result-html :deep(p) { margin: 0.5em 0; }
.result-html :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.result-html :deep(th), .result-html :deep(td) {
  border: 1px solid var(--border-color); padding: 6px 10px;
  text-align: left; font-size: 13px;
}
.result-html :deep(th) { background: var(--hover-bg); }
.result-html :deep(code) {
  background: var(--hover-bg); padding: 2px 4px;
  border-radius: 3px; font-size: 0.9em;
}
.result-html :deep(pre) {
  background: var(--hover-bg); padding: 12px;
  border-radius: 4px; overflow-x: auto;
}
.result-html :deep(img) { max-width: 100%; height: auto; }
.result-html :deep(blockquote) {
  border-left: 4px solid var(--border-color);
  margin: 0.5em 0; padding: 0.5em 1em; color: var(--text-secondary);
}
.result-html :deep(ul), .result-html :deep(ol) { padding-left: 1.5em; margin: 0.5em 0; }
.result-html :deep(li) { margin: 0.25em 0; }
.result-html :deep(a) { color: #1989fa; text-decoration: none; }
.result-html :deep(a:hover) { text-decoration: underline; }
.result-html :deep(hr) { border: none; border-top: 1px solid var(--border-color); margin: 1em 0; }

.error-list { display: flex; flex-direction: column; gap: 12px; }
.error-item {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 12px; border: 1px solid #fde2e2; background: #fef0f0;
  border-radius: 6px; font-size: 13px;
}
.dark-mode .error-item { border-color: #5c3030; background: #3d2020; }
.error-name { font-weight: 500; color: #ee0a24; flex-shrink: 0; }
.error-msg { color: var(--text-secondary); word-break: break-all; }

.empty-hint {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  height: 100%; color: var(--text-secondary); text-align: center;
}
.empty-hint p { margin: 12px 0 0; font-size: 14px; }
.empty-hint .hint-sub { font-size: 12px; color: #c0c4cc; }

.progress-content { padding: 20px; text-align: center; }
.progress-text { margin-top: 12px; color: #666; font-size: 14px; }

@media (max-width: 1200px) {
  .right-panel { width: 30%; }
  .left-panel { width: 260px; }
}
@media (max-width: 900px) {
  .main-content { flex-direction: column; }
  .panel { width: 100% !important; min-width: auto; border-right: none; border-bottom: 1px solid var(--border-color); }
  .center-panel { min-height: 300px; }
}
</style>
