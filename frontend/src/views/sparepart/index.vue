<template>
  <section class="page" data-module="sparepart">
    <header class="page-head">
      <div>
        <h2>备件器材管理</h2>
        <p class="page-desc">结存数量与冻结状态联动：支持批量冻结/解冻、异常备件单独标记与可用量统计，冻结期间不能领用。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记备件器材</button>
        <button class="btn" type="button" @click="exportRows">导出备件器材清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="createVisible" class="create-form" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.name" class="filter-item">
        <span>{{ field.label }}<template v-if="field.required"> *</template></span>
        <input v-model="createForm[field.name]" :placeholder="field.placeholder ?? ''" />
      </label>
      <div class="create-actions">
        <button class="btn primary" type="submit">提交登记</button>
        <button class="btn ghost" type="button" @click="toggleCreate">收起</button>
        <span v-if="createMessage" :class="createOk ? 'ok-text' : 'error-text'">{{ createMessage }}</span>
      </div>
    </form>

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
      <label class="filter-check">
        <input v-model="filters.abnormal" type="checkbox" />
        <span>只看异常备件</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <span>已选 {{ selectedIds.length }} 条备件</span>
      <button class="btn" type="button" :disabled="!selectedIds.length" @click="runBatch('冻结备件')">批量冻结</button>
      <button class="btn" type="button" :disabled="!selectedIds.length" @click="runBatch('解冻备件')">批量解冻</button>
      <button class="btn ghost" type="button" @click="selectAbnormal">选中异常备件</button>
      <button class="btn ghost" type="button" :disabled="!selectedIds.length" @click="clearSelection">清空选择</button>
    </div>

    <ul v-if="batchResults.length" class="batch-results">
      <li v-for="item in batchResults" :key="item.id" :class="item.ok ? 'ok-text' : 'error-text'">
        {{ item.message }}
      </li>
    </ul>

    <table class="data-table">
      <thead>
        <tr>
          <th><input type="checkbox" :checked="allSelected" @change="toggleAll" /></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td><input type="checkbox" :checked="isSelected(row)" @change="toggleSelect(row)" /></td>
          <td v-for="column in columns" :key="column">
            <span v-if="column === '状态标记'">
              <span v-if="row['异常原因']" class="tag warn">{{ row['异常原因'] }}</span>
              <span v-else>—</span>
            </span>
            <template v-else>{{ display(row, column) }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action.name"
              class="link"
              type="button"
              :disabled="action.disabled(row)"
              :title="action.disabled(row) ? action.hint : ''"
              @click="runAction(action.name, row)"
            >
              {{ action.name }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无备件器材数据，可先登记备件器材</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条备件器材记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type BatchResult = { id: number; ok: boolean; message: string; entry: Row | null }

const ENDPOINT = '/api/sparepart'
const columns = ["备件编号", "备件名称", "适用型号", "结存数量", "库存下限", "计量单位", "存放库位", "可用数量", "保管人员", "备件状态", "状态标记"]
const statuses = ["正常可用", "储备不足", "已冻结", "已耗尽"]
const createFields: { name: string; label: string; required?: boolean; placeholder?: string }[] = [
  { name: '备件编号', label: '备件编号', required: true, placeholder: '重复编号会合并到原有记录' },
  { name: '备件名称', label: '备件名称', required: true },
  { name: '适用型号', label: '适用型号', required: true },
  { name: '结存数量', label: '结存数量', placeholder: '非负整数' },
  { name: '库存下限', label: '库存下限', placeholder: '非负整数' },
  { name: '计量单位', label: '计量单位' },
  { name: '存放库位', label: '存放库位' },
  { name: '保管人员', label: '保管人员' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '', abnormal: false })
const stats = ref([
  { label: '可用量（冻结/耗尽不计）', value: 0 },
  { label: '储备不足', value: 0 },
  { label: '已冻结', value: 0 },
  { label: '已耗尽', value: 0 },
  { label: '异常备件', value: 0 },
])
const selectedIds = ref<number[]>([])
const batchResults = ref<BatchResult[]>([])
const createVisible = ref(false)
const createForm = ref<Record<string, string>>({})
const createMessage = ref('')
const createOk = ref(false)

const issuable = (row: Row) => row['备件状态'] === '正常可用' || row['备件状态'] === '储备不足'
const actions = [
  { name: '冻结备件', disabled: (row: Row) => !issuable(row), hint: '已冻结或已耗尽的备件无需冻结' },
  { name: '解冻备件', disabled: (row: Row) => row['备件状态'] !== '已冻结', hint: '仅已冻结的备件可解冻' },
  { name: '登记领用', disabled: (row: Row) => !issuable(row), hint: '已冻结或已耗尽的备件不能领用' },
  { name: '登记耗尽', disabled: (row: Row) => !issuable(row), hint: '已冻结或已耗尽的备件不能登记耗尽' },
]

const allSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => isSelected(row)))

function display(row: Row, column: string) {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function isSelected(row: Row) {
  return selectedIds.value.includes(Number(row.id))
}

function toggleSelect(row: Row) {
  const id = Number(row.id)
  selectedIds.value = isSelected(row)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : rows.value.map((row) => Number(row.id))
}

function selectAbnormal() {
  selectedIds.value = rows.value.filter((row) => row.abnormal).map((row) => Number(row.id))
}

function clearSelection() {
  selectedIds.value = []
  batchResults.value = []
}

function toggleCreate() {
  createVisible.value = !createVisible.value
  createMessage.value = ''
}

function quantityError(value: string, label: string): string {
  const text = value.trim()
  if (!text) return ''
  if (/^[+-]?\d+$/.test(text)) {
    return Number(text) < 0 ? `${label}不能为负数（收到 ${text}）` : ''
  }
  if (!Number.isNaN(Number(text))) {
    return `${label}不能填小数（收到 ${text}），应为非负整数`
  }
  return `${label}应为非负整数（收到 ${text}）`
}

function resetFilters() {
  filters.value = { keyword: '', status: '', abnormal: false }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitCreate() {
  createMessage.value = ''
  for (const field of ['结存数量', '库存下限']) {
    const error = quantityError(createForm.value[field] ?? '', field)
    if (error) {
      createOk.value = false
      createMessage.value = error
      return
    }
  }
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    createOk.value = Boolean(payload.ok)
    createMessage.value = payload.message ?? (payload.ok ? '备件器材已登记' : '备件器材登记失败')
    if (payload.ok) {
      createForm.value = {}
      await Promise.all([reload(), loadStats()])
    }
  } catch (error) {
    createOk.value = false
    createMessage.value = error instanceof Error ? error.message : '备件器材登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values: Record<string, unknown> = { action }
  if (action === '登记领用') {
    const input = window.prompt(`登记领用：${row['备件名称']}（当前结存 ${row['结存数量']}）`, '1')
    if (input === null) return
    values['领用数量'] = input
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '备件器材动作未生效'
      return
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材操作失败'
  }
}

async function runBatch(action: string) {
  errorMessage.value = ''
  batchResults.value = []
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action, ids: selectedIds.value }),
    })
    const payload = await response.json()
    batchResults.value = payload.results ?? []
    // 逐条把结果写回列表，再整体刷新保证可用量、存放库位与状态标记对得上
    for (const item of batchResults.value) {
      if (!item.entry) continue
      const index = rows.value.findIndex((row) => Number(row.id) === Number(item.entry?.id))
      if (index >= 0) rows.value.splice(index, 1, item.entry)
    }
    selectedIds.value = []
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量动作执行失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = await response.json()
    stats.value = [
      { label: '可用量（冻结/耗尽不计）', value: payload.可用量 ?? 0 },
      { label: '储备不足', value: payload.储备不足 ?? 0 },
      { label: '已冻结', value: payload.已冻结 ?? 0 },
      { label: '已耗尽', value: payload.已耗尽 ?? 0 },
      { label: '异常备件', value: payload.异常备件 ?? 0 },
    ]
  } catch {
    // 统计读取失败不阻塞列表展示
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  if (filters.value.abnormal) query.set('abnormal', 'true')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('备件器材列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
