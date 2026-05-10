import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useOcrStore = defineStore('ocr', () => {
  const uploadedImages = ref([])
  const tasks = ref([])
  const results = ref([])
  const currentTask = ref(null)
  const loading = ref(false)

  // 上传图片
  async function uploadImages(files) {
    const formData = new FormData()
    files.forEach(file => {
      formData.append('files', file)
    })

    const res = await api.post('/api/upload/images', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    uploadedImages.value = [...uploadedImages.value, ...res.data]
    return res.data
  }

  // 获取已上传图片
  async function getUploadedImages() {
    const res = await api.get('/api/upload/images')
    uploadedImages.value = res.data.results
    return res.data
  }

  // 删除已上传图片
  async function deleteImage(imageId) {
    await api.delete(`/api/upload/images/${imageId}`)
    uploadedImages.value = uploadedImages.value.filter(img => img.id !== imageId)
  }

  // 提交识别任务
  async function submitTask(imageIds) {
    const res = await api.post('/api/ocr/recognize', { image_ids: imageIds })
    currentTask.value = res.data
    return res.data
  }

  // 获取任务列表
  async function getTasks() {
    const res = await api.get('/api/ocr/tasks')
    tasks.value = res.data.tasks
    return res.data
  }

  // 获取任务详情
  async function getTask(taskId) {
    const res = await api.get(`/api/ocr/tasks/${taskId}`)
    currentTask.value = res.data
    return res.data
  }

  // 获取识别结果
  async function getResults(taskId = null) {
    let url = '/api/ocr/results'
    if (taskId) url += `?task_id=${taskId}`

    const res = await api.get(url)
    results.value = res.data.results
    return res.data
  }

  // 导出结果
  async function exportResults(resultIds, format) {
    const res = await api.post('/api/export/download', {
      result_ids: resultIds,
      format: format
    }, {
      responseType: 'blob'
    })

    // 创建下载链接
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url

    // 获取文件名
    const contentDisposition = res.headers['content-disposition']
    let filename = `ocr_result.${format === 'markdown' ? 'md' : format}`
    if (contentDisposition) {
      const match = contentDisposition.match(/filename=(.+)/)
      if (match) filename = match[1]
    }

    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  }

  // 删除任务
  async function deleteTask(taskId) {
    await api.delete(`/api/ocr/tasks/${taskId}`)
    tasks.value = tasks.value.filter(t => t.id !== taskId)
  }

  // 批量删除任务
  async function batchDeleteTasks(taskIds) {
    await api.post('/api/ocr/tasks/batch-delete', { ids: taskIds })
    tasks.value = tasks.value.filter(t => !taskIds.includes(t.id))
  }

  return {
    uploadedImages,
    tasks,
    results,
    currentTask,
    loading,
    uploadImages,
    getUploadedImages,
    deleteImage,
    submitTask,
    getTasks,
    getTask,
    getResults,
    exportResults,
    deleteTask,
    batchDeleteTasks
  }
})
