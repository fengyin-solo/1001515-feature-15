<template>
  <section class="page" data-module="sparepart">
    <header class="page-head">
      <div>
        <h2>备件器材管理</h2>
        <p class="page-desc">维护备件器材，围绕备件编号、备件名称、适用型号、结存数量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记备件器材</button>
        <button class="btn" type="button" @click="exportRows">导出备件器材清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>备件编号</span>
        <input v-model="filters.keyword" placeholder="按备件编号检索" />
      </label>
      <label class="filter-item">
        <span>备件状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item checkbox-item">
        <input v-model="filters.flagged" type="checkbox" />
        <span>只看异常标记（结存低于下限或库位为空）</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <span>已勾选 {{ selectedIds.length }} 条</span>
      <button class="btn" type="button" :disabled="!selectedIds.length" @click="runBatch('冻结备件')">批量冻结</button>
      <button class="btn" type="button" :disabled="!selectedIds.length" @click="runBatch('解冻备件')">批量解冻</button>
      <span v-if="batchMessage" class="batch-message">{{ batchMessage }}</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col"><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-flagged': rowFlags(row).length > 0 }">
          <td class="check-col"><input type="checkbox" :checked="isSelected(row)" @change="toggleRow(row)" /></td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '标记'">
              <span v-for="flag in rowFlags(row)" :key="flag" class="flag-tag">{{ flag }}</span>
              <span v-if="!rowFlags(row).length">—</span>
            </template>
            <template v-else>{{ displayCell(row, column) }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无备件器材数据，可先登记备件器材</td>
        </tr>
      </tbody>
    </table>

    <ul v-if="batchResults.length" class="result-list">
      <li v-for="item in batchResults" :key="item.id" :class="item.ok ? 'ok-text' : 'error-text'">
        {{ item.message }}
      </li>
    </ul>

    <footer class="page-foot">
      <span>共 {{ total }} 条备件器材记录</span>
      <span v-if="infoMessage" class="ok-text">{{ infoMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="createVisible" class="modal-mask">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3 class="modal-title">登记备件器材</h3>
        <label v-for="field in createFields" :key="field.name" class="modal-field">
          <span>{{ field.label }}<em v-if="field.required" class="required-mark">*</em></span>
          <input v-model="createForm[field.name]" :placeholder="field.placeholder ?? ''" />
        </label>
        <p class="modal-hint">备件编号与已有记录重复时，会合并到原记录并累加结存数量。</p>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit" :disabled="submitting">提交登记</button>
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface Row {
  id: number
  [key: string]: unknown
}

interface StatCard {
  label: string
  value: number
}

interface ActionPayload {
  ok: boolean
  message: string
}

interface BatchItem {
  id: number
  ok: boolean
  message: string
}

interface BatchPayload extends ActionPayload {
  results: BatchItem[]
}

const ENDPOINT = '/api/sparepart'
const columns = ["备件编号", "备件名称", "适用型号", "结存数量", "储备下限", "计量单位", "存放库位", "可用量", "保管人员", "备件状态", "标记"]
const actions = ["冻结备件", "解冻备件", "登记耗尽"]
const statuses = ["正常可用", "储备不足", "已冻结", "已耗尽"]
const createFields = [
  { name: '备件编号', label: '备件编号', required: true },
  { name: '备件名称', label: '备件名称', required: true },
  { name: '适用型号', label: '适用型号', required: true },
  { name: '结存数量', label: '结存数量', required: false, placeholder: '非负整数，留空按 0 登记' },
  { name: '储备下限', label: '储备下限', required: false, placeholder: '留空按 5 处理' },
  { name: '计量单位', label: '计量单位', required: false },
  { name: '存放库位', label: '存放库位', required: false },
  { name: '保管人员', label: '保管人员', required: false },
]

const rows = ref<Row[]>([])
const stats = ref<StatCard[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const filters = ref({ keyword: '', status: '', flagged: false })
const selectedIds = ref<number[]>([])
const batchMessage = ref('')
const batchResults = ref<BatchItem[]>([])
const createVisible = ref(false)
const createError = ref('')
const createForm = ref<Record<string, string>>({})
const submitting = ref(false)

const allChecked = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(row.id)),
)

function rowFlags(row: Row): string[] {
  const flags = row['标记']
  return Array.isArray(flags) ? (flags as string[]) : []
}

function displayCell(row: Row, column: string): string {
  const value = row[column]
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  return String(value)
}

function isSelected(row: Row): boolean {
  return selectedIds.value.includes(row.id)
}

function toggleRow(row: Row) {
  if (isSelected(row)) {
    selectedIds.value = selectedIds.value.filter((id) => id !== row.id)
  } else {
    selectedIds.value = [...selectedIds.value, row.id]
  }
}

function toggleAll() {
  if (allChecked.value) {
    const visible = new Set(rows.value.map((row) => row.id))
    selectedIds.value = selectedIds.value.filter((id) => !visible.has(id))
  } else {
    selectedIds.value = [...new Set([...selectedIds.value, ...rows.value.map((row) => row.id)])]
  }
}

function resetFilters() {
  filters.value = { keyword: '', status: '', flagged: false }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createError.value = ''
  createVisible.value = true
}

function closeCreate() {
  createVisible.value = false
}

function validateCreate(): string {
  const missing = createFields
    .filter((field) => field.required && !(createForm.value[field.name] ?? '').trim())
    .map((field) => field.label)
  if (missing.length) {
    return `缺少必填字段：${missing.join('、')}`
  }
  const raw = (createForm.value['结存数量'] ?? '').trim()
  if (!raw) {
    return ''
  }
  if (/^-?\d+$/.test(raw)) {
    if (Number.parseInt(raw, 10) < 0) {
      return `结存数量不能为负数：当前填的是 ${raw}，请改为 0 或正整数`
    }
    return ''
  }
  if (/^-?(?:\d+\.\d+|\.\d+)$/.test(raw)) {
    return `结存数量不能填小数：当前是「${raw}」，备件按整件登记，请改填整数`
  }
  return `结存数量填写有误：「${raw}」不是数字，请填非负整数`
}

async function submitCreate() {
  const error = validateCreate()
  if (error) {
    createError.value = error
    return
  }
  const values: Record<string, string> = {}
  for (const field of createFields) {
    const text = (createForm.value[field.name] ?? '').trim()
    if (text) {
      values[field.name] = text
    }
  }
  submitting.value = true
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = (await response.json()) as ActionPayload
    if (!response.ok || !payload.ok) {
      createError.value = payload.message || '备件器材登记失败，请稍后重试'
      return
    }
    createVisible.value = false
    infoMessage.value = payload.message
    await refresh()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '备件器材登记失败'
  } finally {
    submitting.value = false
  }
}

async function runBatch(action: string) {
  errorMessage.value = ''
  infoMessage.value = ''
  batchMessage.value = ''
  batchResults.value = []
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action, ids: selectedIds.value }),
    })
    const payload = (await response.json()) as BatchPayload
    if (!response.ok) {
      throw new Error(payload.message || '批量动作未生效，请稍后重试')
    }
    batchMessage.value = payload.message
    batchResults.value = payload.results ?? []
    selectedIds.value = []
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材批量操作失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as ActionPayload
    if (!response.ok) {
      throw new Error(payload.message || '备件器材动作未生效，请稍后重试')
    }
    if (payload.ok) {
      infoMessage.value = payload.message
    } else {
      errorMessage.value = payload.message
    }
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword.trim()) {
    query.set('keyword', filters.value.keyword.trim())
  }
  if (filters.value.status) {
    query.set('status', filters.value.status)
  }
  if (filters.value.flagged) {
    query.set('flagged', 'true')
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('备件器材列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材列表读取失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as { cards?: StatCard[] }
    stats.value = payload.cards ?? []
  } catch {
    stats.value = []
  }
}

async function refresh() {
  await Promise.all([reload(), loadSummary()])
}

onMounted(refresh)
</script>

<style scoped>
.check-col {
  width: 32px;
  text-align: center;
}
.batch-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--muted);
}
.batch-message {
  color: var(--brand);
}
.checkbox-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.row-flagged td {
  background: #fffbeb;
}
.flag-tag {
  display: inline-block;
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
  margin-right: 4px;
}
.result-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
}
.ok-text {
  color: #15803d;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.modal-card {
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  width: 380px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal-title {
  margin: 0;
  font-size: 15px;
}
.modal-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
}
.modal-field input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.required-mark {
  color: #b42318;
  font-style: normal;
}
.modal-hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
