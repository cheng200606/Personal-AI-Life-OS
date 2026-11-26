import { invoke } from '@tauri-apps/api/core'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import './desktop.css'
import { buildItemMarkdown, buildReviewMarkdown } from './markdownExport'
import { clearPendingSharedCapture, enableDueNotifications, normalizeSharedCapture, readPendingSharedCapture, sharedCaptureBody } from './pwa'
import type { SharedCapture } from './pwa'
import { exportToVault } from './vaultExport'
import type { VaultConflictPolicy } from './vaultExport'
import { apiFetch, connectDesktop, desktop, desktopExport, desktopRequest } from './desktopRuntime'
import { DesktopChatImport } from './DesktopChatImport'
import { DesktopFolders, DesktopMissingFiles } from './DesktopFolders'
import { DesktopDrafts, DesktopProviderSettings } from './DesktopAnalysis'
import { DesktopData } from './DesktopData'

type Source = { id: string; kind: string; name: string; status: string; selected_scope: Record<string, unknown>; last_sync_at: string | null; cloud_consent_at: string | null; cloud_consent_version: string | null }
type Item = { id: string; source_id: string; kind: string; title: string; content_text: string; occurred_at: string | null; source_timezone: string | null; source_locator: Record<string, unknown>; metadata: Record<string, unknown> }
type SyncRunSummary = { items_created: number; items_updated: number; items_duplicate: number; items_removed: number; items_skipped: number }
type CalendarPreview = { events: number; recurring: number }
type Job = { id: string; kind: string; status: string; attempt_count: number; max_attempts: number; error_code: string | null; result_json: Record<string, unknown> | null }
type ReviewSuggestion = { text: string; source_ids: string[]; status?: 'pending' | 'dismissed' }
type ReviewModel = { job_id?: string; provider?: string; status?: string; model?: string | null; latency_ms?: number; estimated_cost_usd?: string }
type Review = { id: string; period_start: string; period_end: string; status: string; final_text: string | null; draft: { suggestions?: ReviewSuggestion[]; model?: ReviewModel; insights?: ReviewInsights }; source_items: Item[]; version_number: number; insights: ReviewInsights }
type ReviewInsights = { trends: Array<{ topic: string; current_count: number; previous_count: number; direction: string; source_ids: string[] }>; commitments: Array<{ text: string; due_date: string | null; source_ids: string[] }>; goals: Array<{ entity_id: string; name: string; source_ids: string[]; confidence: number }> }
type ReviewVersion = { id: string; version_number: number; status: string; draft: { suggestions?: ReviewSuggestion[]; model?: ReviewModel; insights?: ReviewInsights }; final_text: string | null; reason: string; created_at: string }
type ModelProvider = { id: string; model: string; models: string[]; input_cost_per_million_usd: string; output_cost_per_million_usd: string; disclosure_version: string; data_sent: string; retention: string; privacy_url: string | null; max_cost_per_call_usd: string; local: boolean; builtin: boolean; available: boolean; consent: { provider_id: string; disclosure_version: string; consented: boolean; granted_at: string | null; revoked_at: string | null } }
type Reminder = { id: string; title: string; notes: string | null; due_at: string | null; status: string }
type ReviewSchedule = { enabled: boolean; weekday: number; local_hour: number; local_minute: number; timezone: string; use_external_model: boolean; provider_id: string; model: string | null; last_run_at: string | null; next_run_at: string | null; last_review_id: string | null }
type SchedulePayload = { enabled: boolean; weekday: number; local_hour: number; local_minute: number; timezone: string; use_external_model: boolean; provider_id: string; model: string | null }
type User = { id: string; email: string; timezone: string; ai_consent_at: string | null }
type Conversation = { id: string; title: string; created_at: number | null }
type Page = 'timeline' | 'ask' | 'graph' | 'pending' | 'projects' | 'reviews' | 'search' | 'organize' | 'account' | 'capture'
const PAGE_PATHS: Record<Page, string> = { timeline: '/timeline', ask: '/ask', graph: '/graph', pending: '/pending', projects: '/projects', reviews: '/reviews', search: '/search', organize: '/organize', account: '/account', capture: '/capture' }
function pageFromPath(pathname: string): Page {
  return (Object.entries(PAGE_PATHS).find(([, path]) => path === pathname)?.[0] as Page | undefined) || 'timeline'
}
type AppIconName = 'timeline' | 'capture' | 'ask' | 'graph' | 'pending' | 'projects' | 'reviews' | 'search' | 'organize' | 'settings' | 'logout' | 'chevron'
function AppIcon({ name, size = 18 }: { name: AppIconName; size?: number }) {
  const paths = {
    timeline: <><circle cx="12" cy="12" r="8.25" /><path d="M12 7v5l3.2 2" /></>,
    capture: <><path d="M12 5v14M5 12h14" /></>,
    ask: <><path d="M8 10h8M8 14h5" /><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5 8 8 0 0 1-3.5-.8L4 20l1.8-4.1a7.5 7.5 0 1 1 14.2-4.4Z" /></>,
    graph: <><circle cx="6" cy="7" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="13" cy="18" r="2" /><path d="m8 7 8-1M7 9l5 7m5-8-3 8" /></>,
    pending: <><path d="M5 4.5h14v15H5z" /><path d="m8 12 2.4 2.4L16 9" /></>,
    projects: <><path d="M3.8 7.5h6l1.8 2H20v9.2H3.8z" /><path d="M3.8 7.5V5.8h6l1.8 1.7" /></>,
    reviews: <><rect x="4" y="5.5" width="16" height="15" rx="2" /><path d="M8 3.5v4M16 3.5v4M4 9.5h16M8 13h3M8 16.5h6" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.2 4.2" /></>,
    organize: <><path d="M4 5.5h16M4 12h16M4 18.5h10" /><circle cx="7" cy="5.5" r="1" /><circle cx="15" cy="12" r="1" /><circle cx="10" cy="18.5" r="1" /></>,
    settings: <><path d="M4 7h9M17 7h3M4 17h3M11 17h9" /><circle cx="15" cy="7" r="2" /><circle cx="9" cy="17" r="2" /></>,
    logout: <><path d="M10 5H5.5A1.5 1.5 0 0 0 4 6.5v11A1.5 1.5 0 0 0 5.5 19H10" /><path d="M14 8l4 4-4 4M8 12h10" /></>,
    chevron: <><path d="m9 18 6-6-6-6" /></>,
  }[name]
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths}</svg>
}
type SearchTimelineHit = { id: string; source_id: string; source_name: string; title: string; snippet: string; occurred_at: string | null; kind: string }
type SearchReviewHit = { id: string; period_start: string; period_end: string; status: string; snippet: string; updated_at: string }
type SearchReminderHit = { id: string; title: string; snippet: string; due_at: string | null; status: string }
type SearchGroup<T> = { total: number; results: T[] }
type SearchResults = { query: string; index_backend: string; timeline: SearchGroup<SearchTimelineHit>; reviews: SearchGroup<SearchReviewHit>; reminders: SearchGroup<SearchReminderHit> }
type SearchFilters = { types: Array<'timeline' | 'reviews' | 'reminders'>; start: string | null; end: string | null; source_id: string | null; status: string[]; tag_id: string | null; collection_id: string | null }
type SavedSearch = { id: string; name: string; query: string; filters: SearchFilters; created_at: string; updated_at: string }
type Tag = { id: string; name: string; color: string | null; created_at: string; updated_at: string }
type Collection = { id: string; name: string; description: string | null; created_at: string; updated_at: string }
type ItemOrganization = { item_id: string; tags: Tag[]; collections: Collection[] }
type Disclosure = { available: boolean; provider: string | null; model: string | null; disclosure_version: string | null; data_sent: string; retention: string; privacy_url: string | null; input_cost_per_million_usd: string | null; output_cost_per_million_usd: string | null; max_cost_per_call_usd: string | null }
type GraphEvidence = { id: string; quote: string; confidence: number; availability: string; source_id: string; source_item_id: string; locator: Record<string, unknown> }
type GraphEntity = { id: string; entity_type: string; name: string; summary: string | null; confidence: number; status: string; evidence: GraphEvidence[] }
type GraphRelation = { id: string; from_entity_id: string; to_entity_id: string; relation_type: string; confidence: number; status: string; evidence: GraphEvidence[] }
type ReviewPayload = { entity_id?: string; relation_id?: string; name?: string; type?: string; relation_type?: string; from_entity_id?: string; to_entity_id?: string; ontology_type_id?: string; source_entity_id?: string; target_entity_id?: string }
type GraphReviewItem = { id: string; kind: string; payload: ReviewPayload; confidence: number; status: string; reason: string | null; extraction_run_id: string | null; created_at: string; resolved_at: string | null }
type GraphMerge = { id: string; source_entity_id: string | null; target_entity_id: string | null; source_name: string | null; target_name: string | null; status: string; evidence_count: number; relation_count: number; created_at: string; undone_at: string | null }
type OntologyType = { id: string; kind: string; name: string; description: string | null; status: string; source: string; created_by: string; version: number; created_at: string; updated_at: string }
type InsightEvidence = { evidence_id: string; quote: string; confidence: number; source_id: string; source_name: string; source_item_id: string; item_title: string; occurred_at: string | null }
type Insight = { insight_key: string; rule: string; rule_label: string; entity_id: string; entity_type: string; entity_name: string; severity: 'high' | 'medium' | 'low'; confidence: number; trigger: string; evidence: InsightEvidence[]; suggestion: string; dismissed: boolean; dismissed_reason: string | null }
type Plugin = { id: string; name: string; version: string; kind: string; description: string; entrypoint: string; status: string; permissions: string[]; created_at: string; updated_at: string }
type PluginCatalogEntry = { name: string; version: string; kind: string; entrypoint: string; description: string; permissions: string[] }
type PluginAudit = { id: string; plugin_id: string | null; action: string; status: string; detail: Record<string, unknown>; created_at: string }
type AgentActionSummary = { id: string; kind: string; target_type: string; target_id: string | null; status: string; approval: string; error_code: string | null; expires_at: string; undo_available: boolean; created_at: string; undone_at: string | null; audit: Record<string, unknown> }
type BudgetInfo = { month: string; period: 'day' | 'week' | 'month'; spent_usd: string; limit_usd: string; remaining_usd: string; warning: boolean; over_budget: boolean; runs: number; input_tokens: number; output_tokens: number; avg_latency_ms: number; failure_reserve_usd: string; by_purpose: { purpose: string; cost_usd: string; runs: number }[]; by_provider: { provider: string; cost_usd: string; runs: number; input_tokens: number; output_tokens: number; avg_latency_ms: number }[] }
type QaScope = { source_ids: string[]; entity_ids: string[]; start: string | null; end: string | null }
type QaCitation = { evidence_id: string; quote: string; confidence: number; availability: string; source_id: string; source_name: string; source_item_id: string; item_title: string; occurred_at: string | null; locator: Record<string, unknown> }
type QaFact = { label: string; detail: string; basis: 'fact' | 'inference' | 'uncertain'; confidence: number; entity_id: string | null; relation_id: string | null; citation_ids: string[] }
type QaSuggestion = { label: string; kind: string; entity_id: string | null; source_item_id: string | null }
type QaTimelineMatch = { source_item_id: string; source_id: string; source_name: string; title: string; snippet: string; occurred_at: string | null; kind: string }
type QaReviewMatch = { id: string; period_start: string; period_end: string; status: string; snippet: string }
type QaAnswer = { status: 'answered' | 'insufficient_evidence'; summary: string; facts: QaFact[]; citations: QaCitation[]; timeline_matches: QaTimelineMatch[]; review_matches: QaReviewMatch[]; missing_info: string[]; suggestions: QaSuggestion[]; confidence: number; scope: Record<string, unknown>; keywords: string[]; intent: string | null; latency_ms: number; version: string }
type QaMessage = { id: string; role: string; content: string; answer: QaAnswer | null; created_at: string }
type QaThread = { id: string; title: string; scope: QaScope; created_at: string; updated_at: string; messages: QaMessage[] }

const GRAPH_CLOUD_CONSENT_VERSION = 'graph-cloud-v1'

async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', 'Bearer ' + token)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await apiFetch(path, { ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message || '请求失败（' + response.status + ')')
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function waitForJob(jobId: string, token: string): Promise<Job> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await api<Job>('/jobs/' + jobId, token)
    if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') return job
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error('后台任务仍在运行，请检查条目状态后重试。')
}

function previewCalendarText(text: string): CalendarPreview {
  if (!/BEGIN:VCALENDAR/i.test(text) || !/BEGIN:VEVENT/i.test(text) || !/END:VCALENDAR/i.test(text)) {
    throw new Error('请选择包含 VEVENT 的 iCalendar (.ics) 文件。')
  }
  const eventBlocks = text.match(/BEGIN:VEVENT[\s\S]*?END:VEVENT/gi) || []
  const events = eventBlocks.length
  if (events > 1000) throw new Error('日历每次最多导入 1,000 个日程。')
  const recurring = eventBlocks.filter((block) => /^(RRULE|RDATE|EXDATE|RECURRENCE-ID)[;:]/im.test(block)).length
  return { events, recurring }
}

function parseConversations(text: string): Conversation[] {
  const document = JSON.parse(text)
  const list = Array.isArray(document) ? document : document.conversations
  if (!Array.isArray(list)) throw new Error('不支持的 ChatGPT 导出，请选择 conversations.json。')
  return list.map((entry: Record<string, unknown>, index: number) => ({
    id: String(entry.conversation_id || entry.id || 'conversation-' + (index + 1)),
    title: String(entry.title || '未命名会话'),
    created_at: typeof entry.create_time === 'number' ? entry.create_time : null,
  }))
}

function sourceScopeDescription(source: Source): string {
  if (source.kind === 'chatgpt_export') {
    const ids = source.selected_scope.conversation_ids
    const count = Array.isArray(ids) ? ids.length : 0
    return `${count} 个已选会话 · 用户/助手文本、消息 ID 与可用时间戳`
  }
  if (source.kind === 'chat_export') {
    return '已选聊天导出 · 用户/助手文本、会话/消息 ID 与可用时间戳'
  }
  if (source.kind === 'photo') {
    const count = typeof source.selected_scope.file_count === 'number' ? source.selected_scope.file_count : 1
    return `${count} 张已选照片 · 图像像素、可选拍摄时间与可搜索 OCR 文本；位置元数据会被移除`
  }
  if (source.kind === 'document') {
    return '已选文档 · Markdown/TXT/PDF/DOCX 文本、标题/页码/段落与来源定位'
  }
  if (source.kind === 'calendar_ics') {
    return '已选日历快照 · 单次日程/全天日程、UID、时区、地点与描述；重复规则暂不展开'
  }
  return `已选 Markdown 文件 · UTF-8 章节文本、标题、日期与行定位（${source.name}）`
}

function selectedFileDisclosure(file: File, selectedConversationCount: number): string {
  if (file.type.startsWith('image/')) {
    return '所选照片会上传并重新编码、执行 OCR。存储副本会移除 EXIF 与位置元数据；外部描述是单独的可选操作。'
  }
  const name = file.name.toLowerCase()
  if (name.endsWith('.jsonl')) {
    return '完整的已选 JSONL 聊天导出会上传，并解析为用户/助手消息与可用时间戳。'
  }
  if (name.endsWith('.json')) {
    return `如果是 ChatGPT 导出，只会上传 ${selectedConversationCount} 个已选会话；其他 JSON 聊天导出会整文件上传。`
  }
  if (name.endsWith('.pdf') || name.endsWith('.docx')) {
    return '完整的已选文档会上传；文本在本地提取，并保留页码/段落定位。扫描版 PDF 暂不支持。'
  }
  if (name.endsWith('.txt')) {
    return '完整的已选文本会上传，并作为一个带行定位的来源条目保存。'
  }
  if (name.endsWith('.ics')) {
    return '完整的已选日历快照会在本地解析。更新现有来源时，取消或消失的日程会退出时间线；重复规则会明确跳过。'
  }
  return '完整的已选 UTF-8 Markdown 文件会上传，并按标题章节拆分，保留日期与行定位；不会读取其他文件。'
}

function App() {
  const [token, setToken] = useState(() => desktop ? '' : sessionStorage.getItem('lifeos-token') || '')
  const [desktopStatus, setDesktopStatus] = useState<'loading' | 'setup' | 'error'>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null)
  const [page, setPageState] = useState<Page>(() => pageFromPath(window.location.pathname))
  const [vaultPolicy, setVaultPolicy] = useState<VaultConflictPolicy>('keep')
  const [sources, setSources] = useState<Source[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [timelineTotal, setTimelineTotal] = useState(0)
  const [timelineCursor, setTimelineCursor] = useState<string | null>(null)
  const [reviews, setReviews] = useState<Review[]>([])
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [schedule, setSchedule] = useState<ReviewSchedule | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [query, setQuery] = useState('')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResults | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchTypes, setSearchTypes] = useState<Array<'timeline' | 'reviews' | 'reminders'>>(['timeline', 'reviews', 'reminders'])
  const [searchStart, setSearchStart] = useState('')
  const [searchEnd, setSearchEnd] = useState('')
  const [searchSourceId, setSearchSourceId] = useState('')
  const [searchStatus, setSearchStatus] = useState('')
  const [searchTagId, setSearchTagId] = useState('')
  const [searchCollectionId, setSearchCollectionId] = useState('')
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([])
  const [savedSearchName, setSavedSearchName] = useState('')
  const [tags, setTags] = useState<Tag[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [organizingItemId, setOrganizingItemId] = useState('')
  const [pendingReviewTotal, setPendingReviewTotal] = useState(0)
  const [agentActiveTotal, setAgentActiveTotal] = useState(0)
  const [extractSelected, setExtractSelected] = useState<string[]>([])
  const [extracting, setExtracting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [photoFiles, setPhotoFiles] = useState<File[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [photoDate, setPhotoDate] = useState('')
  const [photoPreview, setPhotoPreview] = useState('')
  const [calendarPreview, setCalendarPreview] = useState<CalendarPreview | null>(null)
  const [calendarSourceId, setCalendarSourceId] = useState('')
  const [editingNoteId, setEditingNoteId] = useState('')
  const [photoDescriptions, setPhotoDescriptions] = useState<Record<string, string>>({})
  const directoryInput = useRef<HTMLInputElement>(null)
  const backgroundPolls = useRef(new Set<string>())
  const notifiedReminderKey = useRef('')
  const [consentAcknowledged, setConsentAcknowledged] = useState(false)
  const [externalModel, setExternalModel] = useState(false)
  const [providers, setProviders] = useState<ModelProvider[]>([])
  const [reviewProviderId, setReviewProviderId] = useState('')
  const [reviewModel, setReviewModel] = useState('')
  const [loginMode, setLoginMode] = useState<'login' | 'register'>('login')
  const activeToken = useRef(token)

  const openDesktopProfile = useCallback(async (create = false) => {
    setDesktopStatus('loading')
    setError('')
    try {
      await connectDesktop()
      const response = await apiFetch('/auth/desktop-profile', create ? {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' }),
      } : {})
      if (response.status === 404 && !create) {
        setDesktopStatus('setup')
        return
      }
      const body = await response.json()
      if (!response.ok) throw new Error(body.error?.message || '无法打开本机资料。')
      activeToken.current = body.access_token
      setToken(body.access_token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setDesktopStatus('error')
    }
  }, [])

  useEffect(() => {
    // The first desktop profile request starts the native service.
    // eslint-disable-next-line react/set-state-in-effect
    if (desktop) void openDesktopProfile()
  }, [openDesktopProfile])

  function setPage(next: Page) {
    setPageState(next)
    const path = PAGE_PATHS[next]
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
  }

  useEffect(() => {
    function onGlobalShortcut(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k' || !token) return
      const target = event.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      event.preventDefault()
      const path = PAGE_PATHS.search
      setPageState('search')
      if (window.location.pathname !== path) window.history.pushState({}, '', path)
      window.setTimeout(() => document.querySelector<HTMLInputElement>('.search-page input[type="search"]')?.focus(), 60)
    }
    window.addEventListener('keydown', onGlobalShortcut)
    return () => window.removeEventListener('keydown', onGlobalShortcut)
  }, [token])

  useEffect(() => {
    const onPopState = () => setPageState(pageFromPath(window.location.pathname))
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const params = new URLSearchParams({ limit: '100', include_undated: 'true' })
      if (query) params.set('q', query)
      if (dateStart) params.set('start', dateStart)
      if (dateEnd) params.set('end', dateEnd)
      if (sourceFilter) params.set('source_id', sourceFilter)
      const [me, sourceList, timeline, reviewList, reminderList, modelDisclosure, reviewSchedule, reviewQueue, agentQueue, tagList, collectionList, savedList, providerList] = await Promise.all([
        api<User>('/auth/me', token), api<Source[]>('/sources', token), api<{ items: Item[]; total: number; next_cursor: string | null }>('/timeline?' + params.toString(), token),
        api<Review[]>('/reviews', token), api<Reminder[]>('/reminders', token), apiFetch('/auth/model-disclosure').then((response) => response.json() as Promise<Disclosure>),
        api<ReviewSchedule>('/review-schedule', token), api<{ total: number }>('/graph/review?status=pending&limit=1', token),
        api<{ total: number }>('/agent/actions?status=active&limit=1', token), api<Tag[]>('/tags', token),
        api<Collection[]>('/collections', token), api<SavedSearch[]>('/saved-searches', token),
        api<ModelProvider[]>('/model-providers', token),
      ])
      if (activeToken.current !== token) return
      setUser(me); setSources(sourceList); setItems(timeline.items); setTimelineTotal(timeline.total); setTimelineCursor(timeline.next_cursor); setReviews(reviewList); setReminders(reminderList); setDisclosure(modelDisclosure); setSchedule(reviewSchedule); setPendingReviewTotal(reviewQueue.total); setAgentActiveTotal(agentQueue.total); setTags(tagList); setCollections(collectionList); setSavedSearches(savedList); setProviders(providerList)
      setReviewProviderId((current) => providerList.some((provider) => provider.id === current) ? current : providerList[0]?.id || '')
    } catch (e) { if (activeToken.current === token) setError(e instanceof Error ? e.message : '无法加载工作区。') }
  }, [dateEnd, dateStart, query, sourceFilter, token])

  // This effect loads remote account state whenever its filters or token change.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { activeToken.current = token }, [token])
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 60000); return () => window.clearInterval(timer) }, [])
  useEffect(() => {
    if (!token || (desktop
      ? localStorage.getItem('lifeos-desktop-notifications') !== 'enabled'
      : !('Notification' in window) || Notification.permission !== 'granted')) return
    const due = reminders.filter((reminder) => ['pending', 'snoozed'].includes(reminder.status) && reminder.due_at && new Date(reminder.due_at).getTime() <= now)
    const key = due.map((reminder) => reminder.id + ':' + reminder.due_at).sort().join(',')
    if (!key) { notifiedReminderKey.current = ''; return }
    if (notifiedReminderKey.current === key) return
    if (desktop) {
      if (localStorage.getItem('lifeos-last-due-notification') === key) return
      void invoke('desktop_notify_due', { count: due.length }).then(() => {
        notifiedReminderKey.current = key
        localStorage.setItem('lifeos-last-due-notification', key)
      }).catch(() => undefined)
      return
    }
    void enableDueNotifications(due.length, '/reviews').then((result) => {
      if (result.status === 'enabled' || result.status === 'already-enabled') notifiedReminderKey.current = key
    })
  }, [now, reminders, token])
  useEffect(() => {
    if (!token || (!desktop && page !== 'reviews')) return
    const load = () => Promise.all([
      api<Review[]>('/reviews', token), api<Reminder[]>('/reminders', token), api<ReviewSchedule>('/review-schedule', token),
    ]).then(([nextReviews, nextReminders, nextSchedule]) => { setReviews(nextReviews); setReminders(nextReminders); setSchedule(nextSchedule) }).catch(() => undefined)
    void load()
    const timer = window.setInterval(() => { void load() }, 60000)
    return () => window.clearInterval(timer)
  }, [page, token])
  useEffect(() => {
    if (!desktop || !token) return
    let active = true
    const timer = window.setInterval(() => {
      void desktopRequest<{ status: string; scan_status: string }[]>(token, '/desktop/folders').then((folders) => {
        if (!active) return
        const syncing = folders.filter((folder) => folder.status === 'active')
        return invoke('desktop_tray_status', {
          active: syncing.length,
          needsAttention: syncing.some((folder) => ['partial', 'unavailable'].includes(folder.scan_status)),
        })
      }).catch(() => undefined)
      void apiFetch('/ready', { signal: AbortSignal.timeout(5000) }).catch(() => {
        if (!active || activeToken.current !== token) return
        activeToken.current = ''
        setToken('')
        void openDesktopProfile()
      })
    }, 15000)
    const refreshProfile = window.setTimeout(() => void openDesktopProfile(), 6 * 60 * 60 * 1000)
    return () => { active = false; window.clearInterval(timer); window.clearTimeout(refreshProfile) }
  }, [openDesktopProfile, token])
  useEffect(() => () => { if (photoPreview) URL.revokeObjectURL(photoPreview) }, [photoPreview])
  useEffect(() => { directoryInput.current?.setAttribute('webkitdirectory', '') }, [token])
  useEffect(() => {
    if (!token) return
    const watchJob = (jobId: string, kind: string) => {
      if (!jobId || backgroundPolls.current.has(jobId)) return
      backgroundPolls.current.add(jobId)
      void waitForJob(jobId, token).then(async (job) => {
        if (activeToken.current !== token) return
        await refresh()
        if (activeToken.current !== token) return
        if (job.status === 'completed') {
          const result = job.result_json?.model_status
          setNotice(kind === 'weekly_review'
            ? result === 'fallback' ? '提供方未返回可用草稿，模板复盘已准备好。' : '周复盘草稿已准备好。'
            : kind === 'photo_description' ? '照片描述草稿已准备好。' : '照片 OCR 处理完成。')
        } else setError(kind === 'weekly_review'
          ? '模型复盘未完成，模板草稿仍然可用。'
          : kind === 'photo_description' ? '照片描述未完成，可在照片上重试。' : '照片 OCR 未完成，请查看时间线后重试。')
      }).catch((reason) => { if (activeToken.current === token) setError(reason instanceof Error ? reason.message : '无法加载后台任务状态。') })
        .finally(() => backgroundPolls.current.delete(jobId))
    }
    for (const item of items) {
      const ocrActive = ['pending', 'processing'].includes(String(item.metadata.ocr_status))
      const descriptionActive = ['queued', 'running'].includes(String(item.metadata.description_status))
      const jobId = ocrActive
        ? (typeof item.metadata.ocr_job_id === 'string' ? item.metadata.ocr_job_id : '')
        : descriptionActive
          ? (typeof item.metadata.description_job_id === 'string' ? item.metadata.description_job_id : '')
          : ''
      if (jobId) watchJob(jobId, descriptionActive ? 'photo_description' : 'photo_ocr')
    }
    for (const review of reviews) {
      const jobId = review.status === 'processing' ? review.draft.model?.job_id : undefined
      if (jobId) watchJob(jobId, 'weekly_review')
    }
  }, [items, refresh, reviews, token])
  const visibleItems = useMemo(() => items, [items])

  async function loadMoreTimeline() {
    if (!timelineCursor) return
    try {
      const params = new URLSearchParams({ limit: '100', include_undated: 'true', cursor: timelineCursor })
      if (query) params.set('q', query)
      if (dateStart) params.set('start', dateStart)
      if (dateEnd) params.set('end', dateEnd)
      if (sourceFilter) params.set('source_id', sourceFilter)
      const next = await api<{ items: Item[]; total: number; next_cursor: string | null }>('/timeline?' + params.toString(), token)
      setItems((current) => [...current, ...next.items])
      setTimelineTotal(next.total)
      setTimelineCursor(next.next_cursor)
    } catch (e) { setError(e instanceof Error ? e.message : '无法加载更多时间线。') }
  }

  async function extractItems() {
    if (!extractSelected.length || extracting) return
    setExtracting(true); setError(''); setNotice('')
    try {
      const run = await api<{ id: string; status: string; entity_count: number; relation_count: number; review_count: number; budget_warning: boolean }>('/extractions', token, { method: 'POST', body: JSON.stringify({ item_ids: extractSelected }) })
      if (run.status !== 'completed') throw new Error('抽取未完成，请查看运行记录后重试。')
      setNotice(`抽取完成：${run.entity_count} 个实体、${run.relation_count} 条关系、${run.review_count} 条待审${run.budget_warning ? '；已达到 80% 预算提醒' : ''}。`)
      setExtractSelected([])
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '抽取失败，请检查来源授权与模型配置。') } finally { setExtracting(false) }
  }

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    const data = new FormData(event.currentTarget)
    const body: Record<string, string> = { email: String(data.get('email')), password: String(data.get('password')) }
    if (loginMode === 'register') { body.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; body.invite_code = String(data.get('invite_code') || '') }
    try {
      const result = await apiFetch('/auth/' + loginMode, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const payload = await result.json()
      if (!result.ok) throw new Error(payload?.error?.message || '认证失败。')
      sessionStorage.setItem('lifeos-token', payload.access_token); activeToken.current = payload.access_token; setToken(payload.access_token)
    } catch (e) { setError(e instanceof Error ? e.message : '认证失败。') } finally { setBusy(false) }
  }

  async function previewFiles(fileList: FileList | null, fromDirectory = false) {
    setFile(null); setPhotoFiles([]); setPhotoPreview(''); setCalendarPreview(null); setCalendarSourceId('')
    setConversations([]); setSelected([]); setError(''); setNotice('')
    const selectedFiles = Array.from(fileList || [])
    const imageFiles = selectedFiles.filter((selectedFile) => /\.(jpe?g|png|webp)$/i.test(selectedFile.name))
    const skipped = selectedFiles.length - imageFiles.length
    const nextFiles = fromDirectory ? imageFiles : selectedFiles
    if (!fromDirectory && selectedFiles.length === 1 && imageFiles.length === 0 && !/\.(md|markdown|txt|pdf|docx|json|jsonl|ics)$/i.test(selectedFiles[0].name)) {
      setError('请选择 Markdown、TXT、PDF、DOCX、ICS 日历或聊天导出文件，或支持的 JPEG、PNG、WebP 照片。')
      return
    }
    if (nextFiles.length > 10) { setError('每次最多选择 10 张照片。'); return }
    if (nextFiles.length > 1 && (imageFiles.length !== nextFiles.length || !fromDirectory && selectedFiles.some((selectedFile) => !/\.(jpe?g|png|webp)$/i.test(selectedFile.name)))) {
      setError('请选择一个文本/文档/聊天文件，或只选择支持的照片文件。'); return
    }
    if (fromDirectory && nextFiles.length === 0) { setError('所选文件夹中没有支持的 JPEG、PNG 或 WebP 照片。'); return }
    const next = nextFiles[0] || null
    if (desktop && next && /\.(json|jsonl)$/i.test(next.name)) {
      setPage('capture')
      setNotice('请用「从聊天导出导入」选择文件和会话。')
      return
    }
    if (next && !imageFiles.length && next.size > 5 * 1024 * 1024) {
      setError('此类文件不能超过 5 MB。')
      return
    }
    setFile(next); setPhotoFiles(nextFiles.length && nextFiles.every((selectedFile) => /\.(jpe?g|png|webp)$/i.test(selectedFile.name)) ? nextFiles : [])
    setPhotoPreview(next && /\.(jpe?g|png|webp)$/i.test(next.name) ? URL.createObjectURL(next) : '')
    if (fromDirectory && skipped) setNotice(`${skipped} 个非照片文件已忽略。`)
    if (nextFiles.length === 1 && next?.name.toLowerCase().endsWith('.ics')) {
      try {
        if (next.size > 5 * 1024 * 1024) throw new Error('日历文件不能超过 5 MB。')
        setCalendarPreview(previewCalendarText(await next.text()))
      } catch (e) {
        setFile(null)
        setError(e instanceof Error ? e.message : '无法预览此日历。')
      }
    }
    if (nextFiles.length === 1 && next?.name.toLowerCase().endsWith('.json')) {
      try {
        const text = await next.text()
        const document = JSON.parse(text)
        const list = Array.isArray(document) ? document : document.conversations
        const hasMessages = !Array.isArray(list) && document && typeof document === 'object' && ['messages', 'chat_messages', 'turns'].some((key) => Array.isArray(document[key]))
        if (!Array.isArray(list) && !hasMessages) throw new Error('不支持的聊天导出，请选择 JSON/JSONL 聊天导出或文档。')
        const isChatGPT = Array.isArray(list) && list.some((entry) => entry && typeof entry === 'object' && 'mapping' in entry)
        setConversations(isChatGPT ? parseConversations(text) : [])
        if (!isChatGPT) setNotice('这个 JSON 聊天导出会整文件上传。')
      } catch (e) { setError(e instanceof Error ? e.message : '无法预览此文件。') }
    }
  }

  async function importSelected(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return
    const lower = file.name.toLowerCase()
    let kind = photoFiles.length ? 'photo' : lower.endsWith('.ics') ? 'calendar_ics' : lower.endsWith('.jsonl') ? 'chat_export' : lower.endsWith('.json') ? 'chatgpt_export' : 'document'
    if (kind === 'chatgpt_export') {
      try {
        const document = JSON.parse(await file.text())
        const conversations = Array.isArray(document) ? document : document.conversations
        const looksLikeChatGPT = Array.isArray(conversations) && conversations.some((entry) => entry && typeof entry === 'object' && 'mapping' in entry)
        if (!looksLikeChatGPT) kind = 'chat_export'
      } catch { setError('无法读取这个 JSON 文件。'); return }
    }
    if (kind === 'chatgpt_export' && selected.length === 0) { setError('请至少选择一个会话。'); return }
    if (kind === 'calendar_ics' && !calendarPreview) { setError('请先选择有效的 ICS 日历文件。'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      let source: Source
      if (kind === 'calendar_ics' && calendarSourceId) {
        const existing = sources.find((entry) => entry.id === calendarSourceId && entry.kind === 'calendar_ics')
        if (!existing) throw new Error('所选日历来源已不存在，请重新选择。')
        source = existing
      } else {
        source = await api<Source>('/sources', token, { method: 'POST', body: JSON.stringify({ kind, name: kind === 'photo' ? `照片导入 · ${photoFiles.length} 张` : file.name, selected_scope: kind === 'chatgpt_export' ? { conversation_ids: selected } : kind === 'photo' ? { file_count: photoFiles.length } : {} }) })
      }
      const uploads = kind === 'photo' ? photoFiles : [file]
      const jobIds: string[] = []
      const uploadErrors: string[] = []
      let createdItems = 0
      let duplicateItems = 0
      let calendarRun: SyncRunSummary | null = null
      for (const selectedFile of uploads) {
        let upload = selectedFile
        if (kind === 'chatgpt_export') {
          const document = JSON.parse(await selectedFile.text())
          const list = Array.isArray(document) ? document : document.conversations
          const map = new Map<string, unknown>(list.map((entry: Record<string, unknown>, index: number) => [String(entry.conversation_id || entry.id || 'conversation-' + (index + 1)), entry]))
          const chosen = selected.map((id) => map.get(id)).filter(Boolean)
          const minimized = Array.isArray(document) ? chosen : { ...document, conversations: chosen }
          upload = new File([JSON.stringify(minimized)], selectedFile.name, { type: 'application/json' })
        }
        const form = new FormData(); form.append('file', upload)
        if (kind === 'chatgpt_export') form.append('conversation_ids', JSON.stringify(selected))
        if (kind === 'photo' && photoFiles.length === 1 && photoDate) {
          form.append('captured_at', new Date(photoDate).toISOString())
          form.append('captured_timezone', Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
        }
        try {
          const result = await api<{ sync_run: SyncRunSummary; job_ids: string[] }>('/sources/' + source.id + '/imports', token, { method: 'POST', body: form })
          createdItems += result.sync_run.items_created
          duplicateItems += result.sync_run.items_duplicate
          if (kind === 'calendar_ics') calendarRun = result.sync_run
          jobIds.push(...result.job_ids)
        } catch (reason) {
          if (kind !== 'photo') throw reason
          uploadErrors.push(selectedFile.name)
        }
      }
      if (jobIds.length && kind === 'photo') setNotice(`已上传 ${jobIds.length} 张照片，OCR 正在处理。`)
      else if (desktop && jobIds.length) setNotice(`已导入 ${createdItems} 条新记录，${jobIds.length} 项分析已排队。`)
      else if (calendarRun) setNotice(`日历已对账：新增 ${calendarRun.items_created}，更新 ${calendarRun.items_updated}，未变化 ${calendarRun.items_duplicate}，撤销 ${calendarRun.items_removed}，跳过 ${calendarRun.items_skipped}。`)
      else setNotice(`已导入 ${createdItems} 条新记录；${duplicateItems} 条未变化。`)
      if (uploadErrors.length) setError(`${uploadErrors.length} 张照片无法导入：${uploadErrors.join(', ')}`)
      setFile(null); setPhotoFiles([]); setPhotoDate(''); setPhotoPreview(''); setCalendarPreview(null); setCalendarSourceId(''); setSelected([]); setConversations([]); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '导入失败。') } finally { setBusy(false) }
  }

  async function retryPhotoOcr(item: Item) {
    const jobId = typeof item.metadata.ocr_job_id === 'string' ? item.metadata.ocr_job_id : ''
    if (!jobId) return
    try {
      await api<Job>('/jobs/' + jobId + '/retry', token, { method: 'POST' })
      setNotice('照片 OCR 重试已排队。')
      const result = await waitForJob(jobId, token)
      await refresh()
      if (result.status === 'completed') setNotice(`照片处理完成：${String(result.result_json?.ocr_status || 'complete')}。`)
      else setError('照片 OCR 再次失败，清理后的照片仍然可用。')
    } catch (e) { setError(e instanceof Error ? e.message : '无法重试照片 OCR。') }
  }

  async function sourceAction(source: Source, action: 'pause' | 'resume' | 'revoke' | 'delete') {
    if (action === 'delete' && !window.confirm('删除这个来源及其导入数据？')) return
    setError('')
    try {
      if (action === 'delete') await api('/sources/' + source.id, token, { method: 'DELETE' })
      else if (action === 'revoke') await api('/sources/' + source.id + '/revoke', token, { method: 'POST' })
      else await api('/sources/' + source.id + '/status', token, { method: 'PATCH', body: JSON.stringify({ status: action === 'pause' ? 'paused' : 'active' }) })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '来源更新失败。') }
  }

  async function setCloudConsent(source: Source, enabled: boolean) {
    if (desktop && enabled && !window.confirm(`允许所配置的提供方接收「${source.name}」以后导入和更新的文本摘录？`)) return
    setError('')
    try {
      await api('/sources/' + source.id + '/cloud-consent', token, { method: 'PATCH', body: JSON.stringify({ enabled, consent_version: GRAPH_CLOUD_CONSENT_VERSION }) })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '无法更新云端抽取同意。') }
  }

  async function exportItem(item: Item) {
    setError('')
    try {
      const source = sources.find((entry) => entry.id === item.source_id)
      const sourceName = source?.name || (item.kind === 'quick_note' ? 'Quick notes' : 'Life OS')
      const organization = await api<ItemOrganization>('/items/' + item.id + '/organization', token)
      const filename = (item.title.replace(/[^\p{L}\p{N}-]+/gu, '-').replace(/^-|-$/g, '').slice(0, 72) || 'lifeos-note') + '-' + item.id.slice(0, 8)
      const document = {
        filename: filename + '.md',
        markdown: buildItemMarkdown(item, sourceName, organization.tags.map((tag) => tag.name), organization.collections.map((collection) => collection.name)),
      }
      const result = desktop ? await desktopExport(token, document, vaultPolicy) : await exportToVault(document, vaultPolicy)
      if (!result) return
      setNotice(result.status === 'kept'
        ? `已保留现有文件 ${result.filename}，未覆盖你的修改。`
        : result.status === 'downloaded'
          ? `${result.filename} 已下载。${result.reason}`
          : `已写入 Vault：${result.filename}`)
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) setError(e instanceof Error ? e.message : '导出失败。')
    }
  }

  async function downloadSource(item: Item) {
    try {
      const response = await apiFetch('/items/' + item.id + '/raw', { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('来源文件不可用或访问已被撤回。')
      const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'lifeos-source.bin'; link.click(); URL.revokeObjectURL(link.href)
    } catch (e) { setError(e instanceof Error ? e.message : '无法下载来源。') }
  }

  async function deleteItem(item: Item) {
    if (item.kind === 'quick_note') {
      if (!window.confirm('只删除这条快速笔记？其他笔记和导入来源不会受影响。')) return
      try { await api('/quick-notes/' + item.id, token, { method: 'DELETE' }); await refresh(); setNotice('快速笔记已删除。') }
      catch (e) { setError(e instanceof Error ? e.message : '无法删除笔记。') }
      return
    }
    const source = sources.find((entry) => entry.id === item.source_id)
    const label = source ? '"' + source.name + '"' : '这个导入来源'
    if (!window.confirm('删除 ' + label + '？这会移除原始文件以及该来源产生的全部时间线条目，而不只是当前条目。此操作不可撤销。')) return
    try { await api('/items/' + item.id, token, { method: 'DELETE' }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : '无法删除来源数据。') }
  }

  async function describePhoto(item: Item) {
    setError('')
    try {
      const regenerate = Boolean(photoDescriptions[item.id]) || item.metadata.description_status === 'confirmed'
      const result = await api<{ description?: string; job_id?: string }>('/items/' + item.id + '/describe' + (regenerate ? '?regenerate=true' : ''), token, { method: 'POST' })
      if (result.job_id) {
        setNotice('照片描述处理中。')
        const job = await waitForJob(result.job_id, token)
        if (job.status !== 'completed' || typeof job.result_json?.description !== 'string') throw new Error('照片描述未完成，可在照片上重试。')
        result.description = job.result_json.description as string
      }
      const description = result.description
      if (!description) throw new Error('模型没有返回描述。')
      setPhotoDescriptions((current) => ({ ...current, [item.id]: description }))
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '照片描述失败。'); await refresh() }
  }

  async function confirmPhotoDescription(item: Item) {
    const description = photoDescriptions[item.id]
    if (!description) return
    try {
      await api('/items/' + item.id + '/description', token, { method: 'POST', body: JSON.stringify({ description }) })
      setPhotoDescriptions((current) => { const next = { ...current }; delete next[item.id]; return next })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '无法保存照片描述。') }
  }

  async function generateReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); setBusy(true); setError('')
    try {
      const review = await api<Review>('/reviews/generate', token, { method: 'POST', body: JSON.stringify({ period_start: data.get('start'), period_end: data.get('end'), use_external_model: externalModel, provider_id: externalModel ? reviewProviderId || undefined : undefined, model: externalModel ? reviewModel || undefined : undefined }) })
      await refresh()
      const jobId = review.draft.model?.job_id
      if (jobId) setNotice('周复盘处理中，本地模板在运行期间仍可用。')
    } catch (e) { setError(e instanceof Error ? e.message : '复盘生成失败。') } finally { setBusy(false) }
  }

  async function saveReview(review: Review, text: string) {
    try { await api('/reviews/' + review.id, token, { method: 'PATCH', body: JSON.stringify({ final_text: text }) }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : '无法保存复盘。') }
  }

  async function updateSuggestion(review: Review, index: number, patch: { text?: string; status?: 'pending' | 'dismissed' }) {
    try { await api('/reviews/' + review.id + '/suggestions/' + index, token, { method: 'PATCH', body: JSON.stringify(patch) }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : '无法更新这条建议。') }
  }

  async function saveSchedule(payload: SchedulePayload) {
    try {
      const saved = await api<ReviewSchedule>('/review-schedule', token, { method: 'PUT', body: JSON.stringify(payload) })
      setSchedule(saved)
      setNotice(saved.enabled ? '周复盘计划已保存。' : '周复盘计划已关闭。')
    } catch (e) { setError(e instanceof Error ? e.message : '无法保存周复盘计划。') }
  }

  async function updateReminder(reminder: Reminder, status: string) {
    try { await api('/reminders/' + reminder.id + '/status', token, { method: 'PATCH', body: JSON.stringify({ status }) }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : '无法更新提醒。') }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const dueValue = String(data.get('due_at') || '')
    try { await api('/reminders', token, { method: 'POST', body: JSON.stringify({ title: data.get('title'), due_at: dueValue ? new Date(dueValue).toISOString() : null }) }); form.reset(); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : '无法创建提醒。') }
  }

  async function createReminderFromSuggestion(suggestion: ReviewSuggestion) {
    try {
      await api('/reminders', token, {
        method: 'POST',
        body: JSON.stringify({ title: suggestion.text, source_item_ids: suggestion.source_ids }),
      })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '无法从这条建议创建提醒。') }
  }

  async function setModelConsent(enabled: boolean) {
    if (!disclosure?.disclosure_version || (enabled && !consentAcknowledged)) return
    try {
      await api('/auth/ai-consent', token, { method: 'PUT', body: JSON.stringify({ enabled, disclosure_version: disclosure.disclosure_version }) })
      setConsentAcknowledged(false); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '无法更新 AI 同意。') }
  }

  async function downloadReview(review: Review) {
    setError('')
    try {
      const response = await apiFetch('/reviews/' + review.id + '/export.md', { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('这条复盘暂时无法导出。')
      const document = {
        filename: 'weekly-review-' + review.period_start.slice(0, 10) + '.md',
        markdown: buildReviewMarkdown(await response.text(), review),
      }
      const result = desktop ? await desktopExport(token, document, vaultPolicy) : await exportToVault(document, vaultPolicy)
      if (!result) return
      setNotice(result.status === 'kept'
        ? `已保留现有文件 ${result.filename}，未覆盖你的修改。`
        : result.status === 'downloaded'
          ? `${result.filename} 已下载。${result.reason}`
          : `已写入 Vault：${result.filename}`)
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) setError(e instanceof Error ? e.message : '复盘导出失败。')
    }
  }

  function openSource(item: Item) {
    setPage('timeline'); setSourceFilter(item.source_id); setDateStart(''); setDateEnd(''); setQuery('')
    window.setTimeout(() => document.getElementById('timeline-item-' + item.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450)
  }

  function currentSearchFilters(): SearchFilters {
    return {
      types: searchTypes,
      start: searchStart || null,
      end: searchEnd || null,
      source_id: searchSourceId || null,
      status: searchStatus ? [searchStatus] : [],
      tag_id: searchTagId || null,
      collection_id: searchCollectionId || null,
    }
  }

  async function runSearch(trimmed: string, filters: SearchFilters) {
    if (!trimmed) return
    setSearchLoading(true); setError('')
    try {
      const params = new URLSearchParams({ q: trimmed, types: filters.types.join(',') })
      if (filters.start) params.set('start', filters.start)
      if (filters.end) params.set('end', filters.end)
      if (filters.source_id) params.set('source_id', filters.source_id)
      if (filters.status.length) params.set('status', filters.status.join(','))
      if (filters.tag_id) params.set('tag_id', filters.tag_id)
      if (filters.collection_id) params.set('collection_id', filters.collection_id)
      setSearchResults(await api<SearchResults>('/search?' + params.toString(), token))
    } catch (e) { setError(e instanceof Error ? e.message : '搜索失败，请重试。') }
    finally { setSearchLoading(false) }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await runSearch(searchQuery.trim(), currentSearchFilters())
  }

  async function saveCurrentSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = savedSearchName.trim()
    if (!name || !searchQuery.trim()) return
    try {
      await api<SavedSearch>('/saved-searches', token, {
        method: 'POST',
        body: JSON.stringify({ name, query: searchQuery.trim(), filters: currentSearchFilters() }),
      })
      setSavedSearchName('')
      setNotice('检索已保存。')
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '无法保存检索。') }
  }

  function applySavedSearch(entry: SavedSearch) {
    setSearchQuery(entry.query)
    setSearchTypes(entry.filters.types)
    setSearchStart(entry.filters.start || '')
    setSearchEnd(entry.filters.end || '')
    setSearchSourceId(entry.filters.source_id || '')
    setSearchStatus(entry.filters.status[0] || '')
    setSearchTagId(entry.filters.tag_id || '')
    setSearchCollectionId(entry.filters.collection_id || '')
    void runSearch(entry.query, entry.filters)
  }

  async function deleteSavedSearch(entry: SavedSearch) {
    if (!window.confirm(`删除保存的检索“${entry.name}”？`)) return
    try {
      await api('/saved-searches/' + entry.id, token, { method: 'DELETE' })
      setNotice('保存的检索已删除。')
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : '无法删除保存的检索。') }
  }

  function openTimelineHit(hit: SearchTimelineHit) {
    setPage('timeline'); setSourceFilter(hit.kind === 'quick_note' ? '' : hit.source_id); setDateStart(''); setDateEnd(''); setQuery('')
    window.setTimeout(() => document.getElementById('timeline-item-' + hit.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450)
  }

  function openTimelineCitation(itemId: string, sourceId: string) {
    setPage('timeline'); setSourceFilter(sourceId); setDateStart(''); setDateEnd(''); setQuery('')
    window.setTimeout(() => document.getElementById('timeline-item-' + itemId)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450)
  }

  function openReviewHit(hit: SearchReviewHit) {
    setPage('reviews')
    window.setTimeout(() => document.getElementById('review-' + hit.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450)
  }

  function openReminderHit(hit: SearchReminderHit) {
    setPage('reviews')
    window.setTimeout(() => document.getElementById('reminder-' + hit.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450)
  }

  async function downloadAccountArchive() {
    try {
      const response = await apiFetch('/account/archive', { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('无法创建账号归档。')
      const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'lifeos-archive.zip'; link.click(); URL.revokeObjectURL(link.href)
    } catch (e) { setError(e instanceof Error ? e.message : '归档失败。') }
  }

  async function deleteAccount() {
    if (!window.confirm('永久删除账号与全部已存数据？如需副本请先下载归档。')) return
    try { await api('/account', token, { method: 'DELETE' }); sessionStorage.removeItem('lifeos-token'); void clearPendingSharedCapture(); activeToken.current = ''; setToken(''); setUser(null); if (desktop) setDesktopStatus('setup') }
    catch (e) { setError(e instanceof Error ? e.message : '账号删除失败。') }
  }

  if (!token && desktop) return <main className="auth-shell"><section className="auth-card">
    <div className="brand-mark">L</div>
    <h1>Personal AI Life OS</h1>
    {desktopStatus === 'loading' && <p role="status">正在打开本机工作区…</p>}
    {desktopStatus === 'setup' && <>
      <p className="muted">工作区保存在此 Windows 用户账户的本机目录。外部 AI 默认关闭。</p>
      <button className="primary" onClick={() => void openDesktopProfile(true)}>创建本机个人资料</button>
    </>}
    {desktopStatus === 'error' && <>
      <p role="alert" className="notice error">{error}</p>
      <button className="secondary" onClick={() => void openDesktopProfile()}>重试</button>
    </>}
  </section></main>

  if (!token) return <main className="auth-shell"><section className="auth-card"><div className="brand-mark">L</div><p className="eyebrow">PERSONAL AI LIFE OS</p><h1>你的生活，有据可循。</h1><p className="muted">选择要记住的内容，带着来源复盘，让笔记始终可移植。</p><form onSubmit={authenticate} className="stack"><label>邮箱<input name="email" type="email" required autoComplete="email" /></label><label>密码<input name="password" type="password" minLength={12} required autoComplete={loginMode === 'login' ? 'current-password' : 'new-password'} /></label>{loginMode === 'register' && <label>邀请码 <span className="muted">（如需要）</span><input name="invite_code" /></label>}<button className="primary" disabled={busy}>{busy ? '请稍候…' : loginMode === 'login' ? '登录' : '创建账号'}</button></form><button className="text-button" onClick={() => setLoginMode(loginMode === 'login' ? 'register' : 'login')}>{loginMode === 'login' ? '创建账号' : '返回登录'}</button>{error && <p className="notice error">{error}</p>}</section></main>

  const searchTotal = searchResults ? searchResults.timeline.total + searchResults.reviews.total + searchResults.reminders.total : 0
  const dueReminders = reminders.filter((reminder) => ['pending', 'snoozed'].includes(reminder.status) && reminder.due_at && new Date(reminder.due_at).getTime() <= now)
  const readyReview = schedule?.last_review_id ? reviews.find((review) => review.id === schedule.last_review_id && review.status === 'draft') : undefined
  const selectedReviewProvider = providers.find((provider) => provider.id === reviewProviderId)
  const pageTitle: Record<Page, string> = { timeline: '时间线', ask: '提问', graph: '图谱', pending: '待审', projects: '项目与目标', reviews: '复盘', search: '搜索', organize: '整理', account: '设置', capture: '快速捕获' }
  const pageDescription: Record<Page, string> = {
    timeline: '把重要经历、想法与来源放在同一条时间线上。',
    ask: '基于已有记录和可追溯证据，寻找答案。',
    graph: '查看人物、项目、主题及其证据关系。',
    pending: '检查待确认的线索，再决定是否纳入知识图谱。',
    projects: '跟进目标、项目进展与相关行动。',
    reviews: '回顾一段时间的进展，整理下一步行动。',
    search: '跨时间线、复盘与提醒查找资料。',
    organize: '通过标签和集合整理个人知识。',
    account: '管理资料来源、模型授权和工作区偏好。',
    capture: '快速记下进展、想法或待办。',
  }
  const activeSourcesTotal = sources.filter((source) => source.status === 'active').length

  return <div className="app-shell app-shell-desktop">
    <aside className="sidebar desktop-sidebar">
      <button className="brand" onClick={() => setPage('timeline')} aria-label="返回时间线">
        <span className="brand-mark"><span className="brand-mark-glyph">L</span><span className="brand-mark-orbit" /></span>
        <span className="brand-copy"><strong>Life OS</strong><small>PERSONAL WORKSPACE</small></span>
      </button>
      <button className="sidebar-compose" aria-label="快速记录" onClick={() => setPage('capture')}>
        <span className="compose-icon"><AppIcon name="capture" size={17} /></span>
        <span>快速记录</span>
      </button>
      <nav className="sidebar-nav" aria-label="主导航">
        <div className="nav-group">
          <p className="nav-group-label">工作区</p>
          <button aria-label="时间线" className={page === 'timeline' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('timeline')}><span className="nav-icon"><AppIcon name="timeline" /></span><span className="nav-label">时间线</span></button>
          <button aria-label="捕获" className={page === 'capture' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('capture')}><span className="nav-icon"><AppIcon name="capture" /></span><span className="nav-label">捕获</span></button>
          <button aria-label="导航：提问" className={page === 'ask' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('ask')}><span className="nav-icon"><AppIcon name="ask" /></span><span className="nav-label">提问</span></button>
          <button aria-label="待审" className={page === 'pending' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('pending')}><span className="nav-icon"><AppIcon name="pending" /></span><span className="nav-label">待审</span>{pendingReviewTotal > 0 && <span className="nav-badge">{pendingReviewTotal}</span>}</button>
        </div>
        <div className="nav-group">
          <p className="nav-group-label">知识与回顾</p>
          <button aria-label="图谱" className={page === 'graph' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('graph')}><span className="nav-icon"><AppIcon name="graph" /></span><span className="nav-label">图谱</span></button>
          <button aria-label="项目与目标" className={page === 'projects' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('projects')}><span className="nav-icon"><AppIcon name="projects" /></span><span className="nav-label">项目与目标</span></button>
          <button aria-label="复盘" className={page === 'reviews' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('reviews')}><span className="nav-icon"><AppIcon name="reviews" /></span><span className="nav-label">复盘</span>{dueReminders.length > 0 && <span className="nav-badge subtle-badge">{dueReminders.length}</span>}</button>
        </div>
        <div className="nav-group">
          <p className="nav-group-label">资料管理</p>
          <button aria-label="导航：搜索" className={page === 'search' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('search')}><span className="nav-icon"><AppIcon name="search" /></span><span className="nav-label">搜索</span></button>
          <button aria-label="导航：整理" className={page === 'organize' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('organize')}><span className="nav-icon"><AppIcon name="organize" /></span><span className="nav-label">整理</span></button>
          <button aria-label="设置" className={page === 'account' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('account')}><span className="nav-icon"><AppIcon name="settings" /></span><span className="nav-label">设置</span></button>
        </div>
      </nav>
      <section className="sidebar-source-card" aria-label="来源状态">
        <div className="sidebar-source-heading"><span className={`source-live-indicator ${activeSourcesTotal > 0 ? 'active' : sources.length > 0 ? 'paused' : 'idle'}`} /><span>来源状态</span><span className="source-total">{activeSourcesTotal}</span></div>
        <p>{sources.length === 0 ? '添加来源后，记录会显示在这里。' : `${activeSourcesTotal} 个来源正在使用`}</p>
        <button onClick={() => setPage('account')}>管理来源 <AppIcon name="chevron" size={14} /></button>
      </section>
      <div className="sidebar-foot">
        <span className="avatar">{desktop ? '我' : user?.email.slice(0, 1).toUpperCase() || '我'}</span>
        <span className="user-details"><strong>{desktop ? '本机个人资料' : user?.email || '个人空间'}</strong><small>私人工作区</small></span>
        {!desktop && <button className="icon-button signout-button" aria-label="退出登录" title="退出登录" onClick={() => { sessionStorage.removeItem('lifeos-token'); void clearPendingSharedCapture(); activeToken.current = ''; setToken(''); setUser(null) }}><AppIcon name="logout" size={16} /></button>}
      </div>
    </aside>
    <main className="main desktop-main">
      <header className="topbar desktop-topbar">
        <div className="page-heading"><div className="page-breadcrumb"><span>Life OS</span><span className="breadcrumb-divider">/</span><strong>{pageTitle[page]}</strong></div><h1>{pageTitle[page]}</h1><p className="page-subtitle">{pageDescription[page]}</p></div>
        <div className="topbar-actions">
          <button className="search-launcher" onClick={() => setPage('search')} aria-label="打开搜索"><AppIcon name="search" size={16} /><span>搜索你的记录</span><kbd>Ctrl K</kbd></button>
          {page !== 'capture' && <label className="vault-policy"><span>导出冲突</span><select aria-label="Vault 冲突策略" value={vaultPolicy} onChange={(event) => setVaultPolicy(event.target.value as VaultConflictPolicy)}><option value="keep">保留现有</option><option value="copy">另存副本</option><option value="overwrite">明确覆盖</option></select></label>}
          <span className="privacy-pill"><span className="live-dot" /> 私有空间</span>
        </div>
      </header>
      {error && <div className="notice error" role="alert">{error}<button className="icon-button" onClick={() => setError('')}>×</button></div>}
      {notice && <div className="notice success" role="status">{notice}<button className="icon-button" onClick={() => setNotice('')}>×</button></div>}
      {agentActiveTotal > 0 && <div className="notice success">Agent 自动写入了 {agentActiveTotal} 项内部记录，可在设置中查看并一键撤销。<button className="text-button" onClick={() => setPage('account')}>查看并撤销 ↗</button></div>}
      {page === 'capture' && <CapturePage token={token} items={items} reminders={reminders} now={now} onSaved={() => void refresh()} onError={setError} onNotice={setNotice} onOpenTimeline={() => setPage('timeline')} onReminderAction={updateReminder} />}
      {page === 'capture' && desktop && <DesktopChatImport token={token} onComplete={refresh} />}
      {page === 'ask' && <AskPanel token={token} sources={sources} onError={setError} onNotice={setNotice} onOpenCitation={openTimelineCitation} />}
      {page === 'graph' && <GraphPanel view="graph" token={token} onError={setError} onNotice={setNotice} onPendingChange={setPendingReviewTotal} onOpenItem={openTimelineCitation} />}
      {page === 'pending' && <GraphPanel view="pending" token={token} onError={setError} onNotice={setNotice} onPendingChange={setPendingReviewTotal} onOpenItem={openTimelineCitation} />}
      {page === 'pending' && desktop && <DesktopMissingFiles token={token} onChange={refresh} />}
      {page === 'pending' && desktop && <DesktopDrafts token={token} onOpenItem={openTimelineCitation} onChange={refresh} />}
      {page === 'account' && desktop && <DesktopFolders token={token} onChange={refresh} />}
      {page === 'account' && desktop && <DesktopProviderSettings token={token} onChange={refresh} />}
      {page === 'account' && desktop && <DesktopData token={token} onRestore={async () => {
        activeToken.current = ''
        setToken('')
        setUser(null)
        await openDesktopProfile()
      }} />}
      {page === 'projects' && <ProjectsPanel token={token} onError={setError} onNotice={setNotice} onOpenItem={openTimelineCitation} />}
      {page === 'timeline' && <><section className="hero-panel"><div><p className="eyebrow">记录重要内容</p><h2>让上下文真正有用。</h2><p className="muted">导入选中的笔记、会话或照片。时间线会把每条记录与它的来源保持连接。</p></div><div className="stat"><strong>{timelineTotal}</strong><span>条时间线记录</span></div></section>
        {pendingReviewTotal > 0 && <div className="notice success">有 {pendingReviewTotal} 条低置信度图谱条目待审。<button className="text-button" onClick={() => setPage('graph')}>去处理 ↗</button></div>}
        <QuickNotePanel token={token} onSaved={() => void refresh()} onError={setError} onNotice={setNotice} />
        <section className="panel import-panel"><div className="panel-heading"><div><p className="eyebrow">添加来源</p><h2>导入已选材料</h2></div><span className="limit-pill">文本 ≤5 MB · 照片 ≤20 MB</span></div>{desktop && <button type="button" className="text-button" onClick={() => setPage("capture")}>选择聊天会话（最多 1 GiB）</button>}<form onSubmit={importSelected} className="import-form"><label className="file-drop"><span className="upload-icon">↑</span><span><strong>{file ? file.name : '选择文件'}</strong><small>支持 Markdown、TXT、PDF、DOCX、ICS 日历、聊天 JSON/JSONL、JPEG、PNG、WebP</small></span><input type="file" accept=".md,.markdown,.txt,.pdf,.docx,.ics,.json,.jsonl,image/jpeg,image/png,image/webp" multiple onChange={(event) => void previewFiles(event.target.files)} /></label><label className="folder-picker">选择照片文件夹<input ref={directoryInput} type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => void previewFiles(event.target.files, true)} /></label>{calendarPreview && <div className="calendar-preview"><strong>日历预览：{calendarPreview.events} 个日程</strong><p className="small-note">每次上传按完整快照对账；取消或消失的日程会退出时间线。{calendarPreview.recurring > 0 ? `检测到 ${calendarPreview.recurring} 个含重复规则的日程，首版会明确跳过。` : '未检测到重复规则属性。'}</p><label>导入方式<select aria-label="日历导入方式" value={calendarSourceId} onChange={(event) => setCalendarSourceId(event.target.value)}><option value="">作为新日历来源导入</option>{sources.filter((source) => source.kind === 'calendar_ics').map((source) => <option value={source.id} key={source.id} disabled={source.status !== 'active'}>更新现有日历：{source.name}（{source.status}）</option>)}</select></label></div>}{conversations.length > 0 && <div className="selection-box"><div className="selection-head"><strong>选择要导入的会话</strong><button type="button" className="text-button" onClick={() => setSelected(selected.length === conversations.length ? [] : conversations.map((entry) => entry.id))}>{selected.length === conversations.length ? '清空选择' : '全选'}</button></div><div className="conversation-list">{conversations.map((entry) => <label className="conversation" key={entry.id}><input type="checkbox" checked={selected.includes(entry.id)} onChange={(event) => setSelected(event.target.checked ? [...selected, entry.id] : selected.filter((value) => value !== entry.id))} /><span>{entry.title}<small>{entry.created_at ? new Date(entry.created_at * 1000).toLocaleDateString() : '日期未知'}</small></span></label>)}</div><p className="small-note">未选中的会话不会上传。</p></div>}{photoFiles.length > 0 && <><p className="small-note">已选择 {photoFiles.length} 张照片。每张单独上传；不会发送文件夹路径或不支持的文件。</p>{photoFiles.length === 1 && <div className="local-photo-preview"><img src={photoPreview} alt="所选照片预览" /><p className="small-note">保存的照片会重新编码以移除 EXIF 位置等元数据，OCR 文本可搜索。</p></div>}{photoFiles.length === 1 && <label className="inline-field">照片日期（可选）<input type="datetime-local" value={photoDate} onChange={(event) => setPhotoDate(event.target.value)} /></label>}</>}<div className="import-actions"><p className="small-note">提交后才会处理所选文件。</p>{photoFiles.length > 1 ? <p className="selection-disclosure"><strong>{photoFiles.length} 张照片 · {photoFiles.reduce((total, selectedFile) => total + selectedFile.size, 0).toLocaleString()} 字节。</strong> 所选照片会被清理并处理；EXIF/GPS 元数据会被移除。</p> : file && <p className="selection-disclosure"><strong>{file.name} · {file.size.toLocaleString()} 字节。</strong> {selectedFileDisclosure(file, selected.length)}</p>}<button className="primary" disabled={busy || !file}>{busy ? '导入中…' : '导入所选'}</button></div></form></section>
        <section className="timeline-layout"><div className="panel timeline-panel"><div className="panel-heading"><div><p className="eyebrow">你的记录</p><h2>最近活动</h2></div><span className="count-pill">{visibleItems.length} / {timelineTotal}</span></div><label className="search"><span>⌕</span><input aria-label="搜索时间线" placeholder="搜索笔记与会话" value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label><div className="filter-row"><label>从<input type="date" value={dateStart} onChange={(event) => setDateStart(event.target.value)} /></label><label>至<input type="date" value={dateEnd} onChange={(event) => setDateEnd(event.target.value)} /></label><label>来源<select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">全部来源</option>{sourceFilter && !sources.some((source) => source.id === sourceFilter) && <option value={sourceFilter}>当前筛选（快速笔记）</option>}{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label></div><div className="button-row extract-toolbar"><span className="small-note">已选 {extractSelected.length} 条</span><button className="secondary" disabled={!extractSelected.length || extracting} onClick={() => void extractItems()}>{extracting ? '抽取中…' : '抽取所选'}</button>{extractSelected.length > 0 && <button className="text-button" onClick={() => setExtractSelected([])}>清空选择</button>}</div><div className="timeline-list">{visibleItems.map((item) => { const source = sources.find((entry) => entry.id === item.source_id); return <article className="timeline-item" id={'timeline-item-' + item.id} key={item.id}><input type="checkbox" className="timeline-select" aria-label={'选择抽取 ' + item.title} checked={extractSelected.includes(item.id)} onChange={(event) => setExtractSelected(event.target.checked ? [...extractSelected, item.id] : extractSelected.filter((id) => id !== item.id))} /><span className="timeline-marker">{item.kind === 'chat_message' ? '✳' : item.kind === 'photo' ? '▧' : item.kind === 'calendar_event' ? '▦' : item.kind === 'quick_note' ? '✎' : '▤'}</span><div className="item-content"><div className="item-meta"><span>{item.occurred_at ? new Date(item.occurred_at).toLocaleString() : '日期未知'}</span><span className="dot-separator">·</span><span>{source?.name || (item.kind === 'quick_note' ? '快速笔记' : item.kind === 'calendar_event' ? '日历' : '导入来源')}</span></div><h3>{item.title}</h3>{item.kind === 'quick_note' && editingNoteId === item.id && <QuickNoteEditor item={item} token={token} onCancel={() => setEditingNoteId('')} onSaved={() => { setEditingNoteId(''); void refresh() }} onError={setError} onNotice={setNotice} />}{item.kind === 'photo' && Boolean(item.metadata.ocr_status) && <div className="photo-ocr-state"><span>OCR: {String(item.metadata.ocr_status).replace('_', ' ')}</span>{['failed', 'cancelled'].includes(String(item.metadata.ocr_status)) && <button className="text-button" onClick={() => void retryPhotoOcr(item)}>重试 OCR</button>}</div>}{item.kind === 'photo' && <><PhotoImage itemId={item.id} token={token} />{disclosure?.available && <div className="photo-description"><button className="text-button" disabled={!user?.ai_consent_at || ['queued', 'running'].includes(String(item.metadata.description_status))} onClick={() => void describePhoto(item)}>{['queued', 'running'].includes(String(item.metadata.description_status)) ? '生成中…' : photoDescriptions[item.id] || item.metadata.description_status === 'confirmed' ? '再生成一版' : item.metadata.description_status === 'draft' ? '查看已保存草稿' : ['failed', 'cancelled'].includes(String(item.metadata.description_status)) ? '重试描述' : '使用 AI 描述'}</button><span className="small-note">同意后会把清理后的照片发送给 {disclosure.provider}。</span>{photoDescriptions[item.id] && <><textarea value={photoDescriptions[item.id]} onChange={(event) => setPhotoDescriptions((current) => ({ ...current, [item.id]: event.target.value }))} rows={3} aria-label="Photo description draft" /><button className="secondary" onClick={() => void confirmPhotoDescription(item)}>把描述加入时间线</button></>}</div>}</>}{!(item.kind === 'quick_note' && editingNoteId === item.id) && <p>{item.content_text.slice(0, 360)}{item.content_text.length > 360 ? '…' : ''}</p>}<div className="item-actions"><span className="source-tag">{String(item.source_locator.role || item.kind)}</span><button className="text-button" onClick={() => { setOrganizingItemId(item.id); setPage('organize') }}>整理</button>{item.kind === 'quick_note' ? <><button className="text-button" onClick={() => setEditingNoteId(item.id)}>编辑笔记</button><button className="text-button" onClick={() => void exportItem(item)}>导出 Markdown ↗</button><button className="text-button danger-text" onClick={() => void deleteItem(item)}>删除笔记</button></> : <><button className="text-button" onClick={() => void exportItem(item)}>导出 Markdown ↗</button><button className="text-button" onClick={() => void downloadSource(item)}>下载原件 ↗</button><button className="text-button danger-text" onClick={() => void deleteItem(item)}>删除导入来源</button></>}</div></div></article> })}{visibleItems.length === 0 && <div className="empty-state"><span>◷</span><strong>时间线已就绪</strong><p>添加快速笔记，或导入选中的 Markdown、聊天、日历与照片后会显示在这里。</p></div>}</div>{timelineCursor && <button className="secondary full" onClick={() => void loadMoreTimeline()}>加载更多时间线</button>}</div><aside className="panel source-rail"><div className="panel-heading"><div><p className="eyebrow">已连接来源</p><h2>Sources</h2></div><span className="count-pill">{sources.length}</span></div>{sources.length === 0 && <p className="muted">选择的来源会显示在这里。</p>}{sources.slice(0, 5).map((source) => <div className="source-row" key={source.id}><span className="source-icon">{source.kind === 'photo' ? '▧' : source.kind === 'chatgpt_export' ? '✳' : '▤'}</span><div><strong>{source.name}</strong><small>{source.status.replace('_', ' ')}</small></div><span className={source.status === 'active' ? 'status-dot' : 'status-dot paused'} /></div>)}<button className="secondary full" onClick={() => setPage('account')}>管理来源</button></aside></section></>}
      {page === 'search' && <section className="panel search-page">
        <div className="panel-heading"><div><p className="eyebrow">统一搜索</p><h2>找回你保存的一切</h2></div>{searchResults && <span className="count-pill">{searchResults.index_backend}</span>}</div>
        <form className="search-form" onSubmit={submitSearch}>
          <label>搜索时间线、复盘与提醒<input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="试试主题、人物或承诺" /></label>
          <button className="primary" disabled={searchLoading || !searchQuery.trim() || searchTypes.length === 0}>{searchLoading ? '搜索中…' : '搜索'}</button>
        </form>
        <div className="search-filter-grid">
          <fieldset className="type-filters"><legend>结果类型</legend>{(['timeline', 'reviews', 'reminders'] as const).map((type) => <label className="check-row compact" key={type}><input type="checkbox" checked={searchTypes.includes(type)} onChange={(event) => setSearchTypes(event.target.checked ? [...searchTypes, type] : searchTypes.filter((value) => value !== type))} /><span>{type === 'timeline' ? '时间线' : type === 'reviews' ? '周复盘' : '提醒'}</span></label>)}</fieldset>
          <label>从<input type="date" value={searchStart} onChange={(event) => setSearchStart(event.target.value)} /></label>
          <label>至<input type="date" value={searchEnd} onChange={(event) => setSearchEnd(event.target.value)} /></label>
          <label>来源<select value={searchSourceId} onChange={(event) => setSearchSourceId(event.target.value)}><option value="">全部来源</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label>
          <label>状态<select value={searchStatus} onChange={(event) => setSearchStatus(event.target.value)}><option value="">全部状态</option>{['draft', 'processing', 'confirmed', 'pending', 'snoozed', 'completed', 'cancelled'].map((status) => <option value={status} key={status}>{status}</option>)}</select></label>
          <label>标签<select value={searchTagId} onChange={(event) => setSearchTagId(event.target.value)}><option value="">全部标签</option>{tags.map((tag) => <option value={tag.id} key={tag.id}>{tag.name}</option>)}</select></label>
          <label>集合<select value={searchCollectionId} onChange={(event) => setSearchCollectionId(event.target.value)}><option value="">全部集合</option>{collections.map((collection) => <option value={collection.id} key={collection.id}>{collection.name}</option>)}</select></label>
        </div>
        <div className="saved-search-bar">
          <form className="saved-search-form" onSubmit={saveCurrentSearch}><label>保存当前检索<input value={savedSearchName} maxLength={120} onChange={(event) => setSavedSearchName(event.target.value)} placeholder="检索名称" /></label><button className="secondary" disabled={!savedSearchName.trim() || !searchQuery.trim()}>保存检索</button></form>
          {savedSearches.length > 0 && <div className="saved-search-list">{savedSearches.map((entry) => <div className="saved-search-row" key={entry.id}><button className="text-button" onClick={() => applySavedSearch(entry)}>{entry.name}<small>{entry.query}</small></button><button className="text-button danger-text" onClick={() => void deleteSavedSearch(entry)}>删除</button></div>)}</div>}
        </div>
        {searchLoading && <p className="muted" role="status">正在搜索你的时间线、复盘与提醒…</p>}
        {!searchLoading && !searchResults && <p className="muted">按标题和正文搜索时间线、周复盘与提醒；每条结果都能回到原始记录。</p>}
        {!searchLoading && searchResults && searchTotal === 0 && <div className="empty-state"><span>⌕</span><strong>没有结果</strong><p>没有匹配“{searchResults.query}”的记录，试试调整关键词或筛选条件。</p></div>}
        {!searchLoading && searchResults && searchTotal > 0 && <div className="search-results">
          {searchResults.timeline.results.length > 0 && <section className="search-group">
            <div className="panel-heading"><h3>时间线 <span className="count-pill">{searchResults.timeline.total}</span></h3></div>
            {searchResults.timeline.results.map((hit) => <button type="button" className="search-result" key={hit.id} onClick={() => openTimelineHit(hit)}><strong>{hit.title}</strong><span className="search-result-meta">{hit.source_name} · {hit.occurred_at ? new Date(hit.occurred_at).toLocaleString() : '日期未知'}</span><span className="search-result-snippet">{hit.snippet}</span></button>)}
          </section>}
          {searchResults.reviews.results.length > 0 && <section className="search-group">
            <div className="panel-heading"><h3>周复盘 <span className="count-pill">{searchResults.reviews.total}</span></h3></div>
            {searchResults.reviews.results.map((hit) => <button type="button" className="search-result" key={hit.id} onClick={() => openReviewHit(hit)}><strong>{new Date(hit.period_start).toLocaleDateString()} — {new Date(hit.period_end).toLocaleDateString()}</strong><span className="search-result-meta">{hit.status}</span><span className="search-result-snippet">{hit.snippet}</span></button>)}
          </section>}
          {searchResults.reminders.results.length > 0 && <section className="search-group">
            <div className="panel-heading"><h3>提醒 <span className="count-pill">{searchResults.reminders.total}</span></h3></div>
            {searchResults.reminders.results.map((hit) => <button type="button" className="search-result" key={hit.id} onClick={() => openReminderHit(hit)}><strong>{hit.title}</strong><span className="search-result-meta">{hit.status} · {hit.due_at ? new Date(hit.due_at).toLocaleString() : '无到期时间'}</span><span className="search-result-snippet">{hit.snippet}</span></button>)}
          </section>}
        </div>}
      </section>}
      {page === 'organize' && <OrganizationPanel token={token} items={items} tags={tags} collections={collections} selectedItemId={organizingItemId} onSelect={setOrganizingItemId} onChanged={() => void refresh()} onError={setError} onNotice={setNotice} />}
      {page === 'reviews' && schedule && <ReviewSchedulePanel schedule={schedule} timezone={user?.timezone || 'UTC'} providers={providers} onSave={saveSchedule} readyReview={readyReview} onOpenReview={(review) => document.getElementById('review-' + review.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })} />}
      {page === 'reviews' && dueReminders.length > 0 && <DueRemindersPanel reminders={dueReminders} onAction={updateReminder} />}
      {page === 'reviews' && <section className="review-grid"><div className="panel"><div className="panel-heading"><div><p className="eyebrow">复盘时刻</p><h2>开始周复盘</h2></div></div><p className="muted">从这段时间线生成可编辑草稿。每条生成事实都能回到来源核对。</p><form className="review-form" onSubmit={generateReview}><label>从<input name="start" type="date" required /></label><label>至 <small>（不含）</small><input name="end" type="date" required /></label><label className="check-row"><input type="checkbox" checked={externalModel} disabled={!selectedReviewProvider?.available || !selectedReviewProvider?.consent.consented} onChange={(event) => setExternalModel(event.target.checked)} /><span>使用外部 AI 模型<br /><small>请先在设置中同意所选提供方。</small></span></label>{externalModel && <><label>提供方<select value={reviewProviderId} onChange={(event) => { setReviewProviderId(event.target.value); setReviewModel('') }}>{providers.map((provider) => <option value={provider.id} key={provider.id}>{provider.id}{provider.consent.consented ? ' · 已同意' : ''}</option>)}</select></label><label>模型<select value={reviewModel} onChange={(event) => setReviewModel(event.target.value)}><option value="">默认模型</option>{(selectedReviewProvider?.models || []).map((name) => <option value={name} key={name}>{name}</option>)}</select></label></>}<button className="primary" disabled={busy}>{busy ? '准备中…' : '生成草稿'}</button></form><div className="subsection"><div className="panel-heading"><h2>提醒</h2></div><form className="reminder-form" onSubmit={createReminder}><input name="title" placeholder="需要跟进什么？" required /><input name="due_at" type="datetime-local" aria-label="提醒到期时间" /><button className="secondary">添加提醒</button></form>{reminders.map((reminder) => <div className="reminder-row" id={'reminder-' + reminder.id} key={reminder.id}><div><strong>{reminder.title}</strong><small>{reminder.due_at ? new Date(reminder.due_at).toLocaleString() : '无到期时间'} · {reminder.status}</small></div>{reminder.status !== 'completed' && reminder.status !== 'cancelled' && <><button className="text-button" onClick={() => void updateReminder(reminder, 'completed')}>完成</button><button className="text-button" onClick={() => void updateReminder(reminder, 'snoozed')}>稍后提醒</button><button className="text-button" onClick={() => void updateReminder(reminder, 'cancelled')}>忽略</button></>}</div>)}</div></div><div className="review-list">{reviews.map((review) => <ReviewCard key={review.id + (review.final_text || "")} review={review} token={token} onSave={saveReview} onOpenSource={openSource} onExport={downloadReview} onCreateReminder={createReminderFromSuggestion} onUpdateSuggestion={updateSuggestion} />)}{reviews.length === 0 && <div className="panel empty-state"><span>✳</span><strong>复盘会显示在这里</strong><p>选择日期范围后，从有来源的时间线条目生成草稿。</p></div>}</div></section>}
      {page === 'account' && <section className="account-grid"><div className="panel"><p className="eyebrow">账户</p><h2>{desktop ? '本机个人资料' : user?.email}</h2><p className="muted">时区：{user?.timezone}</p><div className="subsection"><p className="eyebrow">模型数据同意</p>{disclosure?.available ? <><p className="muted">提供方：{disclosure.provider} · 模型：{disclosure.model}</p><p className="muted">发送内容：{disclosure.data_sent}</p><p className="muted">保留说明：{disclosure.retention}</p><p className="muted">配置估算：每百万输入 token ${disclosure.input_cost_per_million_usd}，每百万输出 token ${disclosure.output_cost_per_million_usd}。单次预算检查：${disclosure.max_cost_per_call_usd}。调用失败或超出估算仍可能产生提供方费用。</p>{disclosure.privacy_url && <p><a href={disclosure.privacy_url} target="_blank" rel="noreferrer">提供方隐私条款 ↗</a></p>}<label className="check-row consent-check"><input type="checkbox" checked={consentAcknowledged} onChange={(event) => setConsentAcknowledged(event.target.checked)} /><span>我已阅读上述提供方与数据处理说明。</span></label><p className="small-note">当前同意状态：{user?.ai_consent_at ? '已启用' : '未启用'}</p><div className="button-row"><button className="primary" disabled={!consentAcknowledged || Boolean(user?.ai_consent_at)} onClick={() => void setModelConsent(true)}>启用外部 AI</button><button className="secondary" disabled={!user?.ai_consent_at} onClick={() => void setModelConsent(false)}>关闭</button></div></> : <p className="muted">未配置外部模型。模板复盘仍可用，不会向模型提供方发送复盘数据。</p>}</div><div className="subsection"><p className="eyebrow">你的数据</p><p className="muted">下载可移植归档，或永久删除账号与已存记录。</p><div className="button-row"><button className="secondary" onClick={() => void downloadAccountArchive()}>下载归档</button><button className="danger" onClick={() => void deleteAccount()}>删除账号</button></div></div></div><div className="panel"><div className="panel-heading"><div><p className="eyebrow">你的选择</p><h2>管理来源</h2></div></div>{sources.map((source) => <div className="manage-source" key={source.id}><div><strong>{source.name}</strong><small>{source.kind.replace('_', ' ')} · {source.status}</small><p className="source-scope">{sourceScopeDescription(source)}</p><small>上次导入：{source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : '从未'}</small><small>云端抽取：{source.cloud_consent_at ? '已允许' : '未启用'}</small></div><div className="button-row">{source.status === 'active' && <button className="text-button" onClick={() => void sourceAction(source, 'pause')}>暂停</button>}{source.status === 'paused' && <button className="text-button" onClick={() => void sourceAction(source, 'resume')}>恢复</button>}{source.status !== 'revoked' && <button className="text-button" onClick={() => void sourceAction(source, 'revoke')}>撤回</button>}<button className="text-button" disabled={source.status === 'revoked' || source.status === 'deleting'} onClick={() => void setCloudConsent(source, !source.cloud_consent_at)}>{source.cloud_consent_at ? '关闭云端抽取' : '允许云端抽取'}</button><button className="text-button danger-text" onClick={() => void sourceAction(source, 'delete')}>删除数据</button></div></div>)}{sources.length === 0 && <p className="muted">还没有来源。</p>}</div></section>}
      {page === 'account' && <ModelProviderSettings token={token} providers={providers} onChanged={() => void refresh()} onError={setError} onNotice={setNotice} />}
      {page === 'account' && <PluginSettingsPanel token={token} onError={setError} onNotice={setNotice} />}
      {page === 'account' && <AgentActionsPanel token={token} onError={setError} onNotice={setNotice} />}
    </main></div>
}

function OrganizationPanel({ token, items, tags, collections, selectedItemId, onSelect, onChanged, onError, onNotice }: { token: string; items: Item[]; tags: Tag[]; collections: Collection[]; selectedItemId: string; onSelect: (itemId: string) => void; onChanged: () => void; onError: (message: string) => void; onNotice: (message: string) => void }) {
  const [tagName, setTagName] = useState('')
  const [tagColor, setTagColor] = useState('#647D59')
  const [collectionName, setCollectionName] = useState('')
  const [collectionDescription, setCollectionDescription] = useState('')
  const [editingTag, setEditingTag] = useState<Tag | null>(null)
  const [editTagName, setEditTagName] = useState('')
  const [editTagColor, setEditTagColor] = useState('#647D59')
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null)
  const [editCollectionName, setEditCollectionName] = useState('')
  const [editCollectionDescription, setEditCollectionDescription] = useState('')
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([])
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const loadOrganization = useCallback(async (itemId: string) => {
    if (!itemId) { setSelectedTagIds([]); setSelectedCollectionIds([]); return }
    try {
      const organization = await api<ItemOrganization>('/items/' + itemId + '/organization', token)
      setSelectedTagIds(organization.tags.map((tag) => tag.id))
      setSelectedCollectionIds(organization.collections.map((collection) => collection.id))
    } catch (e) { onError(e instanceof Error ? e.message : '无法加载条目整理信息。') }
  }, [onError, token])

  // Organization is loaded from the owner-scoped API when the selected item changes.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void loadOrganization(selectedItemId) }, [loadOrganization, selectedItemId])

  async function createTag(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!tagName.trim()) return
    setBusy(true)
    try {
      await api<Tag>('/tags', token, { method: 'POST', body: JSON.stringify({ name: tagName.trim(), color: tagColor }) })
      setTagName(''); setTagColor('#647D59'); onNotice('标签已创建。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法创建标签。') }
    finally { setBusy(false) }
  }

  async function createCollection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!collectionName.trim()) return
    setBusy(true)
    try {
      await api<Collection>('/collections', token, { method: 'POST', body: JSON.stringify({ name: collectionName.trim(), description: collectionDescription.trim() || null }) })
      setCollectionName(''); setCollectionDescription(''); onNotice('集合已创建。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法创建集合。') }
    finally { setBusy(false) }
  }

  async function saveTag() {
    if (!editingTag || !editTagName.trim()) return
    setBusy(true)
    try {
      await api<Tag>('/tags/' + editingTag.id, token, { method: 'PATCH', body: JSON.stringify({ name: editTagName.trim(), color: editTagColor }) })
      setEditingTag(null); onNotice('标签已更新。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法更新标签。') }
    finally { setBusy(false) }
  }

  async function saveCollection() {
    if (!editingCollection || !editCollectionName.trim()) return
    setBusy(true)
    try {
      await api<Collection>('/collections/' + editingCollection.id, token, { method: 'PATCH', body: JSON.stringify({ name: editCollectionName.trim(), description: editCollectionDescription.trim() || null, clear_description: !editCollectionDescription.trim() }) })
      setEditingCollection(null); onNotice('集合已更新。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法更新集合。') }
    finally { setBusy(false) }
  }

  async function removeTag(tag: Tag) {
    if (!window.confirm(`删除标签“${tag.name}”？条目本身不会删除。`)) return
    try {
      await api('/tags/' + tag.id, token, { method: 'DELETE' })
      setSelectedTagIds((current) => current.filter((id) => id !== tag.id))
      onNotice('标签已删除。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法删除标签。') }
  }

  async function removeCollection(collection: Collection) {
    if (!window.confirm(`删除集合“${collection.name}”？条目本身不会删除。`)) return
    try {
      await api('/collections/' + collection.id, token, { method: 'DELETE' })
      setSelectedCollectionIds((current) => current.filter((id) => id !== collection.id))
      onNotice('集合已删除。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法删除集合。') }
  }

  async function saveOrganization() {
    if (!selectedItemId) return
    setBusy(true)
    try {
      await api<ItemOrganization>('/items/' + selectedItemId + '/organization', token, { method: 'PUT', body: JSON.stringify({ tag_ids: selectedTagIds, collection_ids: selectedCollectionIds }) })
      onNotice('条目整理已保存。'); onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法保存条目整理。') }
    finally { setBusy(false) }
  }

  const selectedItem = items.find((item) => item.id === selectedItemId)
  return <section className="organization-layout">
    <div className="panel organization-catalog">
      <div className="panel-heading"><div><p className="eyebrow">知识组织</p><h2>标签</h2></div><span className="count-pill">{tags.length}</span></div>
      <form className="organization-form" onSubmit={createTag}><label>新标签<input value={tagName} maxLength={80} onChange={(event) => setTagName(event.target.value)} placeholder="例如：研究" /></label><label>颜色<input type="color" value={tagColor} onChange={(event) => setTagColor(event.target.value)} /></label><button className="secondary" disabled={busy || !tagName.trim()}>添加标签</button></form>
      <div className="organization-list">{tags.map((tag) => <div className="organization-row" key={tag.id}>
        {editingTag?.id === tag.id ? <div className="organization-edit"><input aria-label="编辑标签名称" value={editTagName} onChange={(event) => setEditTagName(event.target.value)} /><input aria-label="编辑标签颜色" type="color" value={editTagColor} onChange={(event) => setEditTagColor(event.target.value)} /><button className="secondary" disabled={busy || !editTagName.trim()} onClick={() => void saveTag()}>保存</button><button className="text-button" onClick={() => setEditingTag(null)}>取消</button></div> : <><span className="tag-dot" style={{ background: tag.color || '#647D59' }} /><strong>{tag.name}</strong><div className="button-row"><button className="text-button" onClick={() => { setEditingTag(tag); setEditTagName(tag.name); setEditTagColor(tag.color || '#647D59') }}>编辑</button><button className="text-button danger-text" onClick={() => void removeTag(tag)}>删除</button></div></>}
      </div>)}{tags.length === 0 && <p className="muted">还没有标签。</p>}</div>
      <div className="panel-heading"><div><p className="eyebrow">主题归档</p><h2>集合</h2></div><span className="count-pill">{collections.length}</span></div>
      <form className="organization-form" onSubmit={createCollection}><label>新集合<input value={collectionName} maxLength={120} onChange={(event) => setCollectionName(event.target.value)} placeholder="例如：毕业论文" /></label><label>说明<input value={collectionDescription} maxLength={1000} onChange={(event) => setCollectionDescription(event.target.value)} placeholder="可选" /></label><button className="secondary" disabled={busy || !collectionName.trim()}>添加集合</button></form>
      <div className="organization-list">{collections.map((collection) => <div className="organization-row" key={collection.id}>
        {editingCollection?.id === collection.id ? <div className="organization-edit"><input aria-label="编辑集合名称" value={editCollectionName} onChange={(event) => setEditCollectionName(event.target.value)} /><input aria-label="编辑集合说明" value={editCollectionDescription} onChange={(event) => setEditCollectionDescription(event.target.value)} /><button className="secondary" disabled={busy || !editCollectionName.trim()} onClick={() => void saveCollection()}>保存</button><button className="text-button" onClick={() => setEditingCollection(null)}>取消</button></div> : <><div><strong>{collection.name}</strong><small>{collection.description || '无说明'}</small></div><div className="button-row"><button className="text-button" onClick={() => { setEditingCollection(collection); setEditCollectionName(collection.name); setEditCollectionDescription(collection.description || '') }}>编辑</button><button className="text-button danger-text" onClick={() => void removeCollection(collection)}>删除</button></div></>}
      </div>)}{collections.length === 0 && <p className="muted">还没有集合。</p>}</div>
    </div>
    <div className="panel organization-items">
      <div className="panel-heading"><div><p className="eyebrow">条目关联</p><h2>整理时间线条目</h2></div></div>
      <label>选择条目<select value={selectedItemId} onChange={(event) => onSelect(event.target.value)}><option value="">请选择</option>{items.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
      {selectedItem ? <>
        <div className="selected-item-summary"><strong>{selectedItem.title}</strong><p>{selectedItem.content_text.slice(0, 240)}</p></div>
        <fieldset className="organization-checks"><legend>标签</legend>{tags.map((tag) => <label className="check-row compact" key={tag.id}><input type="checkbox" checked={selectedTagIds.includes(tag.id)} onChange={(event) => setSelectedTagIds(event.target.checked ? [...selectedTagIds, tag.id] : selectedTagIds.filter((id) => id !== tag.id))} /><span>{tag.name}</span></label>)}{tags.length === 0 && <p className="muted">先创建标签。</p>}</fieldset>
        <fieldset className="organization-checks"><legend>集合</legend>{collections.map((collection) => <label className="check-row compact" key={collection.id}><input type="checkbox" checked={selectedCollectionIds.includes(collection.id)} onChange={(event) => setSelectedCollectionIds(event.target.checked ? [...selectedCollectionIds, collection.id] : selectedCollectionIds.filter((id) => id !== collection.id))} /><span>{collection.name}</span></label>)}{collections.length === 0 && <p className="muted">先创建集合。</p>}</fieldset>
        <button className="primary" disabled={busy} onClick={() => void saveOrganization()}>{busy ? '保存中…' : '保存条目整理'}</button>
      </> : <div className="empty-state"><span>▤</span><strong>选择一条记录</strong><p>从时间线点击“整理”，或在这里选择条目。</p></div>}
    </div>
  </section>
}

function localDateTimeValue(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

function CapturePage({ token, items, reminders, now, onSaved, onError, onNotice, onOpenTimeline, onReminderAction }: { token: string; items: Item[]; reminders: Reminder[]; now: number; onSaved: () => void; onError: (message: string) => void; onNotice: (message: string) => void; onOpenTimeline: () => void; onReminderAction: (reminder: Reminder, status: string) => void }) {
  const [shared, setShared] = useState<SharedCapture | null>(null)
  const [loadingShare, setLoadingShare] = useState(true)

  useEffect(() => {
    let active = true
    const applyShare = (value: unknown) => {
      if (!active) return
      const next = normalizeSharedCapture(value)
      if (next.title || next.text || next.url) setShared(next)
      setLoadingShare(false)
    }
    const params = new URLSearchParams(window.location.search)
    if (params.has('title') || params.has('text') || params.has('url')) {
      applyShare({ title: params.get('title'), text: params.get('text'), url: params.get('url') })
      window.history.replaceState({}, '', '/capture')
    }
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === 'lifeos-share') applyShare(event.data.payload)
    }
    window.addEventListener('message', onMessage)
    void readPendingSharedCapture().then((pending) => {
      if (pending) applyShare(pending)
      else if (active) setLoadingShare(false)
    }).catch(() => { if (active) setLoadingShare(false) })
    return () => { active = false; window.removeEventListener('message', onMessage) }
  }, [])

  const dueReminders = reminders.filter((reminder) => ['pending', 'snoozed'].includes(reminder.status) && reminder.due_at && new Date(reminder.due_at).getTime() <= now)
  return <div className="capture-page">
    {shared && <p className="notice">已从分享填充标题与正文；保存后即可在时间线查看。</p>}
    {loadingShare && <p className="muted" role="status">正在读取分享内容…</p>}
    {!loadingShare && <QuickNotePanel key={shared?.receivedAt || 'empty'} token={token} initialTitle={shared?.title || ''} initialContent={shared ? sharedCaptureBody(shared) : ''} onSaved={onSaved} onError={onError} onNotice={onNotice} />}
    {dueReminders.length > 0 && <DueRemindersPanel reminders={dueReminders} onAction={onReminderAction} />}
    <section className="panel capture-recent"><div className="panel-heading"><div><p className="eyebrow">随时查看</p><h2>最近记录</h2></div><button className="secondary" onClick={onOpenTimeline}>查看时间线</button></div>{items.slice(0, 8).map((item) => <article className="capture-item" key={item.id}><strong>{item.title}</strong><small>{item.occurred_at ? new Date(item.occurred_at).toLocaleString() : '日期未知'}</small><p>{item.content_text.slice(0, 240)}{item.content_text.length > 240 ? '…' : ''}</p></article>)}{items.length === 0 && <p className="muted">保存第一条笔记后会显示在这里。</p>}</section>
  </div>
}

function QuickNotePanel({ token, onSaved, onError, onNotice, initialTitle = '', initialContent = '' }: { token: string; onSaved: () => void; onError: (message: string) => void; onNotice: (message: string) => void; initialTitle?: string; initialContent?: string }) {
  const [title, setTitle] = useState(initialTitle)
  const [content, setContent] = useState(initialContent)
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!content.trim()) return
    setBusy(true)
    try {
      await api<Item>('/quick-notes', token, {
        method: 'POST',
        body: JSON.stringify({
          title: title.trim() || null,
          content_text: content,
          occurred_at: date ? new Date(date).toISOString() : null,
          source_timezone: date ? Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' : null,
        }),
      })
      setTitle(''); setContent(''); setDate('')
      onNotice('快速笔记已保存。')
      onSaved()
    } catch (e) { onError(e instanceof Error ? e.message : '无法保存快速笔记。') }
    finally { setBusy(false) }
  }

  return <section className="panel quick-note-panel">
    <div className="panel-heading"><div><p className="eyebrow">快速捕获</p><h2>添加笔记</h2></div><span className="limit-pill">无需外部 AI</span></div>
    <form className="quick-note-form" onSubmit={submit}>
      <label>标题（可选）<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} placeholder="给这条笔记一个标题" /></label>
      <label>正文<textarea value={content} maxLength={20000} rows={3} required onChange={(event) => setContent(event.target.value)} placeholder="记录决定、想法或待跟进事项…" /></label>
      <label>时间（可选）<input type="datetime-local" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      <button className="primary" disabled={busy || !content.trim()}>{busy ? '保存中…' : '保存笔记'}</button>
    </form>
  </section>
}

function QuickNoteEditor({ item, token, onCancel, onSaved, onError, onNotice }: { item: Item; token: string; onCancel: () => void; onSaved: () => void; onError: (message: string) => void; onNotice: (message: string) => void }) {
  const [title, setTitle] = useState(item.title)
  const [content, setContent] = useState(item.content_text)
  const [date, setDate] = useState(localDateTimeValue(item.occurred_at))
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!content.trim()) return
    setBusy(true)
    try {
      await api<Item>('/quick-notes/' + item.id, token, {
        method: 'PATCH',
        body: JSON.stringify({
          title: title.trim() || null,
          content_text: content,
          ...(date
            ? { occurred_at: new Date(date).toISOString(), source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' }
            : { clear_occurred_at: true, clear_source_timezone: true }),
        }),
      })
      onNotice('快速笔记已更新。')
      onSaved()
    } catch (e) { onError(e instanceof Error ? e.message : '无法更新快速笔记。') }
    finally { setBusy(false) }
  }

  return <form className="note-editor" onSubmit={submit}>
    <label>标题<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
    <label>正文<textarea value={content} maxLength={20000} rows={5} required onChange={(event) => setContent(event.target.value)} /></label>
    <label>时间（可选）<input type="datetime-local" value={date} onChange={(event) => setDate(event.target.value)} /></label>
    <div className="button-row"><button className="primary" disabled={busy || !content.trim()}>{busy ? '保存中…' : '保存修改'}</button><button className="text-button" type="button" onClick={onCancel}>取消</button></div>
  </form>
}

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const pad2 = (value: number) => String(value).padStart(2, '0')

function ReviewSchedulePanel({ schedule, timezone, providers, onSave, readyReview, onOpenReview }: { schedule: ReviewSchedule; timezone: string; providers: ModelProvider[]; onSave: (payload: SchedulePayload) => void; readyReview?: Review; onOpenReview: (review: Review) => void }) {
  const [enabled, setEnabled] = useState(schedule.enabled)
  const [weekday, setWeekday] = useState(schedule.weekday)
  const [time, setTime] = useState(pad2(schedule.local_hour) + ':' + pad2(schedule.local_minute))
  const [external, setExternal] = useState(schedule.use_external_model)
  const [providerId, setProviderId] = useState(schedule.provider_id)
  const [model, setModel] = useState(schedule.model || '')
  const selectedProvider = providers.find((provider) => provider.id === providerId)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const [hour, minute] = time.split(':').map(Number)
    onSave({ enabled, weekday, local_hour: hour, local_minute: minute, timezone, use_external_model: external, provider_id: providerId, model: model || null })
  }

  return <section className="panel schedule-panel">
    <div className="panel-heading"><div><p className="eyebrow">自动复盘</p><h2>周复盘计划</h2></div>{schedule.next_run_at && <span className="count-pill">下次 {new Date(schedule.next_run_at).toLocaleString()}</span>}</div>
    <p className="muted">本地 worker 运行时，会按你的时区生成草稿。外部 AI 仍需同意与预算。</p>
    <form className="schedule-form" onSubmit={submit}>
      <label className="check-row"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>启用自动周复盘</span></label>
      <label>星期<select value={weekday} onChange={(event) => setWeekday(Number(event.target.value))}>{WEEKDAYS.map((label, index) => <option value={index} key={label}>{label}</option>)}</select></label>
      <label>时间<input type="time" value={time} onChange={(event) => setTime(event.target.value)} required /></label>
      <label className="check-row"><input type="checkbox" checked={external} onChange={(event) => setExternal(event.target.checked)} /><span>有可用模型时使用外部 AI</span></label>
      {external && <><label>提供方<select value={providerId} onChange={(event) => { setProviderId(event.target.value); setModel('') }}>{providers.map((provider) => <option value={provider.id} key={provider.id}>{provider.id}{provider.consent.consented ? ' · 已同意' : ''}</option>)}</select></label><label>模型<select value={model} onChange={(event) => setModel(event.target.value)}><option value="">默认模型</option>{(selectedProvider?.models || []).map((name) => <option value={name} key={name}>{name}</option>)}</select></label></>}
      <div className="button-row"><button className="secondary" type="submit">保存计划</button></div>
    </form>
    {schedule.last_run_at && <p className="small-note">上次计划运行： {new Date(schedule.last_run_at).toLocaleString()}</p>}
    {external && !selectedProvider?.consent.consented && <p className="small-note">所选提供方尚未同意；启用同意前，计划复盘会使用模板。</p>}
    {readyReview && <p className="notice success">计划复盘已就绪。 <button className="text-button" type="button" onClick={() => onOpenReview(readyReview)}>打开复盘</button></p>}
  </section>
}

function DueRemindersPanel({ reminders, onAction }: { reminders: Reminder[]; onAction: (reminder: Reminder, status: string) => void }) {
  const [notificationMessage, setNotificationMessage] = useState('')
  const [enablingNotification, setEnablingNotification] = useState(false)
  async function enableNotifications() {
    if (desktop) {
      const enable = localStorage.getItem('lifeos-desktop-notifications') !== 'enabled'
      localStorage.setItem('lifeos-desktop-notifications', enable ? 'enabled' : 'disabled')
      setNotificationMessage(enable ? 'Windows 通知已启用。' : 'Windows 通知已关闭。')
      return
    }
    setEnablingNotification(true)
    const result = await enableDueNotifications(reminders.length, '/reviews')
    setNotificationMessage(result.status === 'enabled' || result.status === 'already-enabled' ? '浏览器通知已启用。' : 'message' in result ? result.message : '通知状态未知。')
    setEnablingNotification(false)
  }
  return <section className="panel due-reminders">
    <div className="panel-heading"><div><p className="eyebrow">到期提醒</p><h2>需要跟进的承诺</h2></div><span className="count-pill">{reminders.length}</span></div>
    <div className="notification-actions"><button className="secondary" disabled={enablingNotification} onClick={() => void enableNotifications()}>{desktop
      ? (localStorage.getItem('lifeos-desktop-notifications') === 'enabled' ? '关闭 Windows 通知' : '启用 Windows 通知')
      : enablingNotification ? '请求授权中…' : '启用浏览器通知'}</button><span className="small-note">应用内提醒始终可用。</span></div>
    {notificationMessage && <p className="small-note" role="status">{notificationMessage}</p>}
    {reminders.map((reminder) => <div className="reminder-row" key={reminder.id}><div><strong>{reminder.title}</strong><small>{reminder.due_at ? new Date(reminder.due_at).toLocaleString() : '无到期时间'} · {reminder.status}</small></div><div className="button-row"><button className="text-button" onClick={() => onAction(reminder, 'completed')}>完成</button><button className="text-button" onClick={() => onAction(reminder, 'snoozed')}>稍后提醒</button></div></div>)}
  </section>
}

function ReviewInsightsPanel({ insights }: { insights: ReviewInsights }) {
  if (!insights || (!insights.trends?.length && !insights.commitments?.length && !insights.goals?.length)) return null
  return <section className="review-insights">
    {insights.trends?.length > 0 && <div><p className="eyebrow">跨周期趋势</p>{insights.trends.map((trend) => <p key={trend.topic}>{trend.topic} · 本期 {trend.current_count} / 前期 {trend.previous_count} · {trend.direction}</p>)}</div>}
    {insights.commitments?.length > 0 && <div><p className="eyebrow">承诺与到期日</p>{insights.commitments.map((commitment, index) => <p key={index}>{commitment.text} · {commitment.due_date || '日期未明确'}</p>)}</div>}
    {insights.goals?.length > 0 && <div><p className="eyebrow">目标关联</p>{insights.goals.map((goal) => <p key={goal.entity_id}>{goal.name} · 置信度 {Math.round(goal.confidence * 100)}%</p>)}</div>}
  </section>
}

function ReviewCard({ review, token, onSave, onOpenSource, onExport, onCreateReminder, onUpdateSuggestion }: { review: Review; token: string; onSave: (review: Review, text: string) => void; onOpenSource: (item: Item) => void; onExport: (review: Review) => void; onCreateReminder: (suggestion: ReviewSuggestion) => void; onUpdateSuggestion: (review: Review, index: number, patch: { text?: string; status?: 'pending' | 'dismissed' }) => void }) {
  const [text, setText] = useState(review.final_text || '')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [suggestionDraft, setSuggestionDraft] = useState('')
  const [versions, setVersions] = useState<ReviewVersion[]>([])
  const [leftVersion, setLeftVersion] = useState(1)
  const [rightVersion, setRightVersion] = useState(1)

  // Version history is loaded from the owner-scoped API for this review.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    let active = true
    void api<ReviewVersion[]>('/reviews/' + review.id + '/versions', token).then((list) => {
      if (!active) return
      setVersions(list)
      setLeftVersion(list[0]?.version_number || 1)
      setRightVersion(list[list.length - 1]?.version_number || 1)
    }).catch(() => undefined)
    return () => { active = false }
  }, [review.id, token])
  const processing = review.status === 'processing'
  const suggestions = review.draft?.suggestions || []
  const pendingSuggestions = suggestions.map((suggestion, index) => ({ suggestion, index })).filter(({ suggestion }) => suggestion.status !== 'dismissed')
  const dismissedSuggestions = suggestions.map((suggestion, index) => ({ suggestion, index })).filter(({ suggestion }) => suggestion.status === 'dismissed')
  const suggestionEditable = review.status === 'draft'
  const evidence = (suggestion: ReviewSuggestion) => review.source_items.filter((item) => suggestion.source_ids.includes(item.id)).map((item) => item.title).join(', ') || '来源详情不可用'
  const compareLeft = versions.find((version) => version.version_number === leftVersion)
  const compareRight = versions.find((version) => version.version_number === rightVersion)
  const leftLines = new Set((compareLeft?.final_text || '').split('\n').filter(Boolean))
  const rightLines = new Set((compareRight?.final_text || '').split('\n').filter(Boolean))
  const addedLines = [...rightLines].filter((line) => !leftLines.has(line))
  const removedLines = [...leftLines].filter((line) => !rightLines.has(line))
  return <article className="panel review-card" id={'review-' + review.id}>
    <div className="panel-heading"><div><p className="eyebrow">{review.status.toUpperCase()}</p><h2>{new Date(review.period_start).toLocaleDateString()} — {new Date(review.period_end).toLocaleDateString()}</h2></div><div className="button-row"><button className="secondary" onClick={() => onExport(review)} disabled={processing || review.status === 'invalidated'}>导出 Markdown</button><button className="primary" onClick={() => onSave(review, text)} disabled={processing || review.status === 'invalidated'}>确认并保存</button></div></div>
    {processing && <p className="notice">外部模型处理中。如果提供方失败，本地模板仍会保留。</p>}
    {review.draft?.model?.provider && review.draft.model.provider !== 'template' && <p className="small-note">{review.draft.model.status === 'ready'
      ? 'AI 草稿 · ' + (review.draft.model.model || 'model') + ' · ' + (review.draft.model.latency_ms ?? 0) + ' ms · $' + (review.draft.model.estimated_cost_usd || '0')
      : '模板草稿 · 外部模型 ' + (review.draft.model.status || 'unavailable')}</p>}
    {review.status === 'invalidated' && <p className="notice error">一个来源已被删除。重新生成复盘以恢复证据。</p>}
    <ReviewInsightsPanel insights={review.insights} />
    {suggestions.length > 0 ? <div className="review-suggestions"><p className="eyebrow">建议行动</p>
      {pendingSuggestions.map(({ suggestion, index }) => <div className="suggestion-row" key={index}>
        <div>
          {editingIndex === index
            ? <input aria-label="Suggestion text" value={suggestionDraft} onChange={(event) => setSuggestionDraft(event.target.value)} />
            : <strong>{suggestion.text}</strong>}
          <small>证据： {evidence(suggestion)}</small>
        </div>
        <div className="button-row">
          {editingIndex === index ? <>
            <button className="secondary" disabled={!suggestionDraft.trim()} onClick={() => { onUpdateSuggestion(review, index, { text: suggestionDraft.trim() }); setEditingIndex(null) }}>保存建议</button>
            <button className="text-button" onClick={() => setEditingIndex(null)}>取消</button>
          </> : <>
            <button className="text-button" disabled={!suggestionEditable} onClick={() => { setEditingIndex(index); setSuggestionDraft(suggestion.text) }}>编辑</button>
            <button className="text-button" disabled={!suggestionEditable} onClick={() => onUpdateSuggestion(review, index, { status: 'dismissed' })}>忽略</button>
            <button className="secondary" disabled={processing || review.status === 'invalidated'} onClick={() => onCreateReminder(suggestion)}>创建提醒</button>
          </>}
        </div>
      </div>)}
      {pendingSuggestions.length === 0 && <p className="muted">没有待处理建议。</p>}
      {dismissedSuggestions.length > 0 && <details className="dismissed-suggestions"><summary>已忽略建议 ({dismissedSuggestions.length})</summary>
        {dismissedSuggestions.map(({ suggestion, index }) => <div className="suggestion-row" key={index}>
          <div><strong>{suggestion.text}</strong><small>证据： {evidence(suggestion)}</small></div>
          <button className="text-button" disabled={!suggestionEditable} onClick={() => onUpdateSuggestion(review, index, { status: 'pending' })}>恢复</button>
        </div>)}
      </details>}
    </div> : null}
    {versions.length > 0 && <details className="review-versions"><summary>版本对比 · 当前 v{review.version_number}</summary><div className="version-controls"><label>基线<select value={leftVersion} onChange={(event) => setLeftVersion(Number(event.target.value))}>{versions.map((version) => <option value={version.version_number} key={version.id}>v{version.version_number} · {version.reason}</option>)}</select></label><label>对比<select value={rightVersion} onChange={(event) => setRightVersion(Number(event.target.value))}>{versions.map((version) => <option value={version.version_number} key={version.id}>v{version.version_number} · {version.reason}</option>)}</select></label></div><p className="small-note">新增 {addedLines.length} 行 · 移除 {removedLines.length} 行</p><div className="version-diff"><section><h4>v{leftVersion}</h4><pre>{compareLeft?.final_text || '（空）'}</pre></section><section><h4>v{rightVersion}</h4><pre>{compareRight?.final_text || '（空）'}</pre></section></div></details>}
    <textarea value={text} onChange={(event) => setText(event.target.value || '')} placeholder="编辑复盘，使用下方来源核对事实。" rows={9} disabled={processing || review.status === 'invalidated'} /><details><summary>证据 ({review.source_items.length})</summary>{review.source_items.map((item) => <p className="evidence" key={item.id}><strong>{item.title}</strong><span>{item.content_text.slice(0, 180)}</span><button className="text-button" onClick={() => onOpenSource(item)}>在时间线中打开来源 ↗</button></p>)}</details>
  </article>
}

function PhotoImage({ itemId, token }: { itemId: string; token: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let objectUrl = ''
    let active = true
    void apiFetch('/items/' + itemId + '/raw', { headers: { Authorization: 'Bearer ' + token } }).then((response) => response.ok ? response.blob() : null).then((blob) => {
      if (blob && active) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }
    }).catch(() => undefined)
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [itemId, token])
  return url ? <img className="timeline-photo" src={url} alt="导入的照片" /> : null
}

function reviewLabel(item: GraphReviewItem): string {
  if (item.kind === 'entity') return [item.payload.name || '未命名实体', item.payload.type].filter(Boolean).join(' · ')
  if (item.kind === 'relation') return item.payload.relation_type || '未命名关系'
  if (item.kind === 'ontology') return '本体类型 · ' + (item.payload.name || '')
  return item.kind
}

function percent(value: number): string {
  return Math.round(value * 100) + '%'
}

function GraphPanel({ view, token, onError, onNotice, onPendingChange, onOpenItem }: { view: 'graph' | 'pending'; token: string; onError: (message: string) => void; onNotice: (message: string) => void; onPendingChange: (total: number) => void; onOpenItem: (itemId: string, sourceId: string) => void }) {
  const [entities, setEntities] = useState<GraphEntity[]>([])
  const [relations, setRelations] = useState<GraphRelation[]>([])
  const [pending, setPending] = useState<GraphReviewItem[]>([])
  const [merges, setMerges] = useState<GraphMerge[]>([])
  const [ontology, setOntology] = useState<OntologyType[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [editing, setEditing] = useState('')
  const [draft, setDraft] = useState('')
  const [mergeSource, setMergeSource] = useState('')
  const [mergeTarget, setMergeTarget] = useState('')
  const [typeKind, setTypeKind] = useState<'entity' | 'relation'>('entity')
  const [typeName, setTypeName] = useState('')
  const [typeDescription, setTypeDescription] = useState('')

  const load = useCallback(async () => {
    try {
      const [entityList, relationList, reviewList, mergeList, typeList] = await Promise.all([
        api<{ items: GraphEntity[]; total: number }>('/graph/entities?limit=100', token),
        api<{ items: GraphRelation[]; total: number }>('/graph/relations?limit=100', token),
        api<{ items: GraphReviewItem[]; total: number }>('/graph/review?status=pending&limit=100', token),
        api<{ items: GraphMerge[]; total: number }>('/graph/merges', token),
        api<{ items: OntologyType[]; total: number }>('/ontology/types', token),
      ])
      setEntities(entityList.items)
      setRelations(relationList.items)
      setPending(reviewList.items)
      setMerges(mergeList.items)
      setOntology(typeList.items)
      onPendingChange(reviewList.total)
    } catch (e) {
      onError(e instanceof Error ? e.message : '图谱数据加载失败。')
    } finally {
      setLoading(false)
    }
  }, [onError, onPendingChange, token])

  // The graph page loads owner-scoped data after mount.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load() }, [load])

  async function decide(item: GraphReviewItem, action: 'approve' | 'reject') {
    try {
      await api('/graph/review/' + item.id + '/decision', token, { method: 'POST', body: JSON.stringify({ action }) })
      setSelected((current) => current.filter((id) => id !== item.id))
      await load()
      onNotice(action === 'approve' ? '已批准待审项。' : '已拒绝待审项。')
    } catch (e) { onError(e instanceof Error ? e.message : '待审操作失败。') }
  }

  async function bulk(action: 'approve' | 'reject') {
    if (!selected.length) return
    try {
      await api('/graph/review/bulk', token, { method: 'POST', body: JSON.stringify({ item_ids: selected, action }) })
      setSelected([])
      await load()
      onNotice(action === 'approve' ? '已批量批准待审项。' : '已批量拒绝待审项。')
    } catch (e) { onError(e instanceof Error ? e.message : '批量操作失败。') }
  }

  async function saveEdit(item: GraphReviewItem) {
    if (!draft.trim()) return
    try {
      await api('/graph/review/' + item.id, token, { method: 'PATCH', body: JSON.stringify({ name: draft.trim() }) })
      setEditing('')
      await load()
      onNotice('待审实体已更新。')
    } catch (e) { onError(e instanceof Error ? e.message : '待审实体更新失败。') }
  }

  async function mergeEntities() {
    if (!mergeSource || !mergeTarget || mergeSource === mergeTarget) {
      onError('请选择两个不同的实体。')
      return
    }
    try {
      await api('/graph/entities/' + mergeSource + '/merge', token, { method: 'POST', body: JSON.stringify({ target_entity_id: mergeTarget }) })
      setMergeSource('')
      setMergeTarget('')
      await load()
      onNotice('实体已合并，可在合并记录中撤销。')
    } catch (e) { onError(e instanceof Error ? e.message : '合并失败。') }
  }

  async function undoMerge(log: GraphMerge) {
    try {
      await api('/graph/merges/' + log.id + '/undo', token, { method: 'POST' })
      await load()
      onNotice('已撤销合并并恢复证据与关系。')
    } catch (e) { onError(e instanceof Error ? e.message : '撤销合并失败。') }
  }

  async function proposeType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      await api('/ontology/types', token, { method: 'POST', body: JSON.stringify({ kind: typeKind, name: typeName.trim(), description: typeDescription.trim() || null }) })
      setTypeName('')
      setTypeDescription('')
      await load()
      onNotice('已提交自定义本体提议。')
    } catch (e) { onError(e instanceof Error ? e.message : '自定义本体提交失败。') }
  }

  async function decideType(entry: OntologyType, status: 'approved' | 'rejected') {
    try {
      await api('/ontology/types/' + entry.id + '/decision', token, { method: 'POST', body: JSON.stringify({ status }) })
      await load()
      onNotice(status === 'approved' ? '本体类型已批准。' : '本体类型已拒绝。')
    } catch (e) { onError(e instanceof Error ? e.message : '本体类型操作失败。') }
  }

  const activeEntities = entities.filter((entity) => entity.status === 'active')
  const entityName = (id: string) => entities.find((entity) => entity.id === id)?.name || id.slice(0, 8)

  return <section className="graph-stack">
    {view === 'graph' && <InsightsPanel token={token} onError={onError} onNotice={onNotice} onOpenItem={onOpenItem} />}
    {view === 'pending' && <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">REVIEW QUEUE</p><h2>低置信度待审</h2></div><span className="count-pill">{pending.length}</span></div>
      <p className="muted">低置信度或缺少原文证据的实体与关系会停在这里。批准后进入问答；拒绝会隐藏该条目。</p>
      {loading ? <p className="muted" role="status">正在加载图谱…</p> : pending.length === 0 ? <div className="empty-state"><span>✓</span><strong>没有待审条目</strong><p>新的抽取结果会出现在这里。</p></div> : <>
        <div className="button-row review-toolbar">
          <label className="check-row compact"><input type="checkbox" checked={selected.length === pending.length && pending.length > 0} onChange={(event) => setSelected(event.target.checked ? pending.map((item) => item.id) : [])} /><span>全选</span></label>
          <button className="secondary" disabled={!selected.length} onClick={() => void bulk('approve')}>批量批准</button>
          <button className="text-button danger-text" disabled={!selected.length} onClick={() => void bulk('reject')}>批量拒绝</button>
        </div>
        {pending.map((item) => <div className="review-row" key={item.id}>
          <input type="checkbox" aria-label={'选择待审 ' + reviewLabel(item)} checked={selected.includes(item.id)} onChange={(event) => setSelected(event.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} />
          <div className="review-row-main">
            <strong>{reviewLabel(item)}</strong>
            <small>{item.kind} · 置信度 {percent(item.confidence)}{item.reason ? ' · ' + item.reason : ''}</small>
            {editing === item.id && <div className="edit-row"><input aria-label="待审名称" value={draft} onChange={(event) => setDraft(event.target.value)} /><button className="secondary" onClick={() => void saveEdit(item)}>保存</button><button className="text-button" onClick={() => setEditing('')}>取消</button></div>}
          </div>
          <div className="button-row">
            {item.kind === 'entity' && <button className="text-button" onClick={() => { setEditing(item.id); setDraft(item.payload.name || '') }}>编辑</button>}
            <button className="secondary" onClick={() => void decide(item, 'approve')}>批准</button>
            <button className="text-button danger-text" onClick={() => void decide(item, 'reject')}>拒绝</button>
          </div>
        </div>)}
      </>}
    </section>}

    {view === 'graph' && <section className="graph-grid">
      <div className="panel">
        <div className="panel-heading"><div><p className="eyebrow">EVIDENCE GRAPH</p><h2>图谱实体</h2></div><span className="count-pill">{entities.length}</span></div>
        {entities.length === 0 && !loading && <p className="muted">暂无可展示的实体。先导入来源并抽取。</p>}
        {entities.map((entity) => <div className="entity-row" key={entity.id}>
          <div className="entity-row-main">
            <strong>{entity.name}</strong>
            <small>{entity.entity_type} · {entity.status} · 置信度 {percent(entity.confidence)}</small>
            {entity.summary && <p>{entity.summary}</p>}
          </div>
          <details>
            <summary>{entity.evidence.length} 条证据</summary>
            {entity.evidence.map((evidence) => <button type="button" className="evidence evidence-button" key={evidence.id} onClick={() => onOpenItem(evidence.source_item_id, evidence.source_id)}>{evidence.quote}<small>{evidence.availability}</small></button>)}
            {entity.evidence.length === 0 && <p className="small-note">没有可用证据。</p>}
          </details>
        </div>)}
      </div>

      <div className="graph-stack">
        <div className="panel">
          <div className="panel-heading"><div><p className="eyebrow">RELATIONS</p><h2>关系</h2></div><span className="count-pill">{relations.length}</span></div>
          {relations.length === 0 && <p className="muted">暂无关系。</p>}
          {relations.map((relation) => <div className="entity-row" key={relation.id}>
            <div className="entity-row-main">
              <strong>{entityName(relation.from_entity_id)} → {entityName(relation.to_entity_id)}</strong>
              <small>{relation.relation_type} · {relation.status} · 置信度 {percent(relation.confidence)}</small>
            </div>
            <span className="count-pill">{relation.evidence.length} 证据</span>
          </div>)}
        </div>

        <div className="panel">
          <div className="panel-heading"><div><p className="eyebrow">MERGE</p><h2>实体合并</h2></div><span className="count-pill">{merges.length}</span></div>
          <form className="merge-form" onSubmit={(event) => { event.preventDefault(); void mergeEntities() }}>
            <label>源实体<select value={mergeSource} onChange={(event) => setMergeSource(event.target.value)}><option value="">选择实体</option>{activeEntities.map((entity) => <option value={entity.id} key={entity.id}>{entity.name}</option>)}</select></label>
            <label>合并到<select value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)}><option value="">选择实体</option>{activeEntities.map((entity) => <option value={entity.id} key={entity.id}>{entity.name}</option>)}</select></label>
            <button className="secondary" disabled={activeEntities.length < 2}>合并</button>
          </form>
          <p className="small-note">合并保留别名与日志，撤销会恢复实体、证据与关系。</p>
          {merges.map((log) => <div className="merge-row" key={log.id}>
            <div><strong>{log.source_name || '已删除实体'} → {log.target_name || '已删除实体'}</strong><small>{log.status} · {log.evidence_count} 证据 · {log.relation_count} 关系</small></div>
            {log.status === 'active' && <button className="text-button" onClick={() => void undoMerge(log)}>撤销合并</button>}
          </div>)}
        </div>

        <div className="panel">
          <div className="panel-heading"><div><p className="eyebrow">ONTOLOGY</p><h2>自定义本体</h2></div><span className="count-pill">{ontology.length}</span></div>
          <form className="ontology-form" onSubmit={(event) => void proposeType(event)}>
            <select aria-label="本体类型种类" value={typeKind} onChange={(event) => setTypeKind(event.target.value as 'entity' | 'relation')}><option value="entity">实体类型</option><option value="relation">关系类型</option></select>
            <input aria-label="本体类型名称" placeholder="例如 habit" value={typeName} onChange={(event) => setTypeName(event.target.value)} required pattern="[a-z][a-z0-9_]{1,63}" />
            <input aria-label="本体类型说明" placeholder="说明（可选）" value={typeDescription} onChange={(event) => setTypeDescription(event.target.value)} />
            <button className="secondary">提议类型</button>
          </form>
          {ontology.length === 0 && <p className="muted">还没有自定义类型。模型提议的新类型也会显示在这里。</p>}
          {ontology.map((entry) => <div className="ontology-row" key={entry.id}>
            <div><strong>{entry.name}</strong><small>{entry.kind} · {entry.status} · {entry.source} · {entry.created_by} · v{entry.version}</small>{entry.description && <p>{entry.description}</p>}</div>
            {entry.status === 'proposed' && <div className="button-row"><button className="text-button" onClick={() => void decideType(entry, 'approved')}>批准</button><button className="text-button danger-text" onClick={() => void decideType(entry, 'rejected')}>拒绝</button></div>}
          </div>)}
        </div>
      </div>
    </section>}
  </section>
}

function severityLabel(severity: Insight['severity']): string {
  if (severity === 'high') return '高'
  if (severity === 'medium') return '中'
  return '低'
}

function InsightsList({ insights, dismissedTotal, showDismissed, onDismiss, onRestore, onOpenItem }: { insights: Insight[]; dismissedTotal: number; showDismissed: boolean; onDismiss: (insight: Insight) => void; onRestore: (insight: Insight) => void; onOpenItem: (itemId: string, sourceId: string) => void }) {
  if (insights.length === 0) {
    return <div className="empty-state compact-empty"><span>✓</span><strong>没有需要关注的洞察</strong><p>{dismissedTotal > 0 ? '已忽略的提示不会重复出现。' : '目标、承诺、项目与技能目前都没有触发规则。'}</p></div>
  }
  return <div className="insight-list">
    {insights.map((insight) => <div className={'insight-row ' + insight.severity} key={insight.insight_key}>
      <div className="insight-main">
        <div className="insight-heading">
          <strong>{insight.rule_label} · {insight.entity_name}</strong>
          <span className={'basis-badge ' + (insight.severity === 'high' ? 'uncertain' : insight.severity === 'medium' ? 'inference' : 'fact')}>{severityLabel(insight.severity)}风险 · {percent(insight.confidence)}</span>
        </div>
        <small>{insight.trigger}</small>
        <p className="small-note">建议：{insight.suggestion}</p>
        <div className="button-row">
          {insight.evidence.map((evidence) => <button type="button" className="text-button" key={evidence.evidence_id} onClick={() => onOpenItem(evidence.source_item_id, evidence.source_id)}>{evidence.item_title} ↗</button>)}
          {insight.dismissed
            ? <button type="button" className="text-button" onClick={() => onRestore(insight)}>恢复提示</button>
            : <button type="button" className="text-button danger-text" onClick={() => onDismiss(insight)}>忽略误报</button>}
          {showDismissed && insight.dismissed && <span className="small-note">已忽略{insight.dismissed_reason ? ' · ' + insight.dismissed_reason : ''}</span>}
        </div>
      </div>
    </div>)}
  </div>
}

function InsightsPanel({ token, onError, onNotice, onOpenItem }: { token: string; onError: (message: string) => void; onNotice: (message: string) => void; onOpenItem: (itemId: string, sourceId: string) => void }) {
  const [insights, setInsights] = useState<Insight[]>([])
  const [dismissedTotal, setDismissedTotal] = useState(0)
  const [showDismissed, setShowDismissed] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const body = await api<{ items: Insight[]; dismissed_total: number }>('/insights/rules?include_dismissed=' + String(showDismissed), token)
      setInsights(body.items)
      setDismissedTotal(body.dismissed_total)
    } catch (e) {
      onError(e instanceof Error ? e.message : '规则洞察加载失败。')
    } finally {
      setLoading(false)
    }
  }, [onError, showDismissed, token])

  // Insights are owner-scoped remote state; load after mount or when the filter changes.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load() }, [load])

  async function dismiss(insight: Insight) {
    try {
      await api('/insights/rules/dismiss', token, { method: 'POST', body: JSON.stringify({ insight_key: insight.insight_key, rule: insight.rule, entity_id: insight.entity_id, reason: '用户标记为误报' }) })
      await load()
      onNotice('已忽略这条规则提示，不会重复出现。')
    } catch (e) { onError(e instanceof Error ? e.message : '忽略提示失败。') }
  }

  async function restore(insight: Insight) {
    try {
      await api('/insights/rules/dismissals/' + encodeURIComponent(insight.insight_key), token, { method: 'DELETE' })
      await load()
      onNotice('已恢复这条规则提示。')
    } catch (e) { onError(e instanceof Error ? e.message : '恢复提示失败。') }
  }

  return <section className="panel">
    <div className="panel-heading"><div><p className="eyebrow">RULE INSIGHTS</p><h2>规则洞察</h2></div><div className="button-row"><span className="count-pill">{insights.length}</span>{dismissedTotal > 0 && <button className="text-button" onClick={() => setShowDismissed(!showDismissed)}>{showDismissed ? '隐藏已忽略' : '显示已忽略 (' + dismissedTotal + ')'}</button>}</div></div>
    <p className="muted">目标延期、承诺未跟进、项目停滞与技能证据不足会触发可解释提示；忽略后不再重复提示。</p>
    {loading ? <p className="muted" role="status">正在评估规则…</p> : <InsightsList insights={insights} dismissedTotal={dismissedTotal} showDismissed={showDismissed} onDismiss={(insight) => void dismiss(insight)} onRestore={(insight) => void restore(insight)} onOpenItem={onOpenItem} />}
  </section>
}

function ProjectsPanel({ token, onError, onNotice, onOpenItem }: { token: string; onError: (message: string) => void; onNotice: (message: string) => void; onOpenItem: (itemId: string, sourceId: string) => void }) {
  const [entities, setEntities] = useState<GraphEntity[]>([])
  const [relations, setRelations] = useState<GraphRelation[]>([])
  const [insights, setInsights] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [entityList, relationList, insightList] = await Promise.all([
        api<{ items: GraphEntity[] }>('/graph/entities?limit=100', token),
        api<{ items: GraphRelation[] }>('/graph/relations?limit=100', token),
        api<{ items: Insight[] }>('/insights/rules', token),
      ])
      setEntities(entityList.items)
      setRelations(relationList.items)
      setInsights(insightList.items)
    } catch (e) {
      onError(e instanceof Error ? e.message : '项目与目标加载失败。')
    } finally {
      setLoading(false)
    }
  }, [onError, token])

  // Remote owner-scoped project state.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load() }, [load])

  const projects = entities.filter((entity) => entity.entity_type === 'project')
  const goals = entities.filter((entity) => entity.entity_type === 'goal')
  const tasks = entities.filter((entity) => entity.entity_type === 'task')
  const nameOf = (id: string) => entities.find((entity) => entity.id === id)?.name || id.slice(0, 8)
  const linksFor = (entityId: string) => relations.filter((relation) => relation.from_entity_id === entityId || relation.to_entity_id === entityId)
  const insightsFor = (entityId: string) => insights.filter((insight) => insight.entity_id === entityId)

  async function dismissInsight(insight: Insight) {
    try {
      await api('/insights/rules/dismiss', token, { method: 'POST', body: JSON.stringify({ insight_key: insight.insight_key, rule: insight.rule, entity_id: insight.entity_id, reason: '用户标记为误报' }) })
      await load()
      onNotice('已忽略这条规则提示。')
    } catch (e) { onError(e instanceof Error ? e.message : '忽略提示失败。') }
  }

  function renderCard(entity: GraphEntity) {
    const links = linksFor(entity.id)
    return <div className="project-card" key={entity.id}>
      <div className="entity-row-main">
        <strong>{entity.name}</strong>
        <small>{entity.entity_type} · {entity.status} · 置信度 {percent(entity.confidence)}</small>
        {entity.summary && <p>{entity.summary}</p>}
        <div className="button-row project-links">
          {links.map((relation) => <span className="count-pill" key={relation.id}>{relation.relation_type} · {nameOf(relation.from_entity_id === entity.id ? relation.to_entity_id : relation.from_entity_id)}</span>)}
          {insightsFor(entity.id).map((insight) => <span className="basis-badge inference" key={insight.insight_key}>{insight.rule_label}</span>)}
        </div>
        {entity.evidence.length > 0 && <details><summary>{entity.evidence.length} 条证据</summary>{entity.evidence.map((evidence) => <button type="button" className="evidence evidence-button" key={evidence.id} onClick={() => onOpenItem(evidence.source_item_id, evidence.source_id)}>{evidence.quote}</button>)}</details>}
      </div>
    </div>
  }

  return <section className="graph-stack">
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">PROJECTS & GOALS</p><h2>项目与目标</h2></div><div className="button-row"><span className="count-pill">{projects.length} 项目</span><span className="count-pill">{goals.length} 目标</span><span className="count-pill">{tasks.length} 任务</span></div></div>
      <p className="muted">这里汇总项目、目标与任务关系，并显示对应的规则洞察和证据。点击证据可回到时间线原文。</p>
      {loading ? <p className="muted" role="status">正在加载项目与目标…</p> : projects.length === 0 && goals.length === 0 && tasks.length === 0 ? <div className="empty-state"><span>◎</span><strong>还没有项目或目标</strong><p>完成图谱抽取或让 Agent 创建项目、任务与目标进度后，这里会显示进度和关系。</p></div> : <>
        {projects.length > 0 && <div className="subsection"><p className="eyebrow">项目进度</p><div className="project-grid">{projects.map(renderCard)}</div></div>}
        {goals.length > 0 && <div className="subsection"><p className="eyebrow">目标</p><div className="project-grid">{goals.map(renderCard)}</div></div>}
        {tasks.length > 0 && <div className="subsection"><p className="eyebrow">任务</p><div className="project-grid">{tasks.map(renderCard)}</div></div>}
      </>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">RULE INSIGHTS</p><h2>项目与目标洞察</h2></div><span className="count-pill">{insights.length}</span></div>
      <InsightsList insights={insights} dismissedTotal={0} showDismissed={false} onDismiss={(insight) => void dismissInsight(insight)} onRestore={() => { void load() }} onOpenItem={onOpenItem} />
    </section>
  </section>
}

function ModelProviderSettings({ token, providers, onChanged, onError, onNotice }: { token: string; providers: ModelProvider[]; onChanged: () => void; onError: (message: string) => void; onNotice: (message: string) => void }) {
  const [acknowledged, setAcknowledged] = useState<string[]>([])
  const [busyId, setBusyId] = useState('')

  async function setConsent(provider: ModelProvider, enabled: boolean) {
    setBusyId(provider.id)
    try {
      await api('/model-providers/consent', token, {
        method: 'PUT',
        body: JSON.stringify({ provider_id: provider.id, enabled, disclosure_version: provider.disclosure_version }),
      })
      setAcknowledged((current) => current.filter((id) => id !== provider.id))
      onNotice(enabled ? `已同意提供方 ${provider.id}。` : `已撤回提供方 ${provider.id} 的同意。`)
      onChanged()
    } catch (e) { onError(e instanceof Error ? e.message : '无法更新模型同意。') }
    finally { setBusyId('') }
  }

  return <section className="panel provider-settings">
    <div className="panel-heading"><div><p className="eyebrow">MODEL PROVIDERS</p><h2>模型提供方与同意</h2></div><span className="count-pill">{providers.length}</span></div>
    <p className="muted">密钥只从环境或本地配置读取。切换提供方需要单独同意，撤回后该提供方的未完成模型任务会取消。</p>
    {providers.length === 0 && <p className="muted">尚未配置外部模型提供方。</p>}
    {providers.map((provider) => <div className="provider-row" key={provider.id}>
      <div><strong>{provider.id} · {provider.model}{provider.local ? ' · 本地' : ''}{provider.builtin ? ' · 默认' : ''}</strong><small>输入 ${provider.input_cost_per_million_usd}/百万 token · 输出 ${provider.output_cost_per_million_usd}/百万 token · 单次上限 ${provider.max_cost_per_call_usd}</small><p className="small-note">发送内容：{provider.data_sent}</p><p className="small-note">保留说明：{provider.retention}</p>{provider.privacy_url && <a href={provider.privacy_url} target="_blank" rel="noreferrer">隐私条款 ↗</a>}<small>状态：{provider.available ? provider.consent.consented ? '已同意' : '未同意' : '配置不完整'}</small></div>
      <div className="button-row">
        {provider.consent.consented ? <button className="secondary" disabled={busyId === provider.id} onClick={() => void setConsent(provider, false)}>撤回同意</button> : <><label className="check-row compact"><input type="checkbox" checked={acknowledged.includes(provider.id)} onChange={(event) => setAcknowledged(event.target.checked ? [...acknowledged, provider.id] : acknowledged.filter((id) => id !== provider.id))} /><span>已阅读上述说明</span></label><button className="primary" disabled={!provider.available || !acknowledged.includes(provider.id) || busyId === provider.id} onClick={() => void setConsent(provider, true)}>同意并启用</button></>}
      </div>
    </div>)}
  </section>
}

function PluginSettingsPanel({ token, onError, onNotice }: { token: string; onError: (message: string) => void; onNotice: (message: string) => void }) {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [catalog, setCatalog] = useState<PluginCatalogEntry[]>([])
  const [audit, setAudit] = useState<PluginAudit[]>([])
  const [budget, setBudget] = useState<BudgetInfo | null>(null)
  const [budgetPeriod, setBudgetPeriod] = useState<'day' | 'week' | 'month'>('month')
  const [selectedPlugin, setSelectedPlugin] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [pluginList, catalogList, auditList, budgetInfo] = await Promise.all([
        api<{ items: Plugin[] }>('/plugins', token),
        api<{ items: PluginCatalogEntry[] }>('/plugins/catalog', token),
        api<{ items: PluginAudit[] }>('/plugins/audit', token),
        api<BudgetInfo>('/budget?period=' + budgetPeriod, token),
      ])
      setPlugins(pluginList.items)
      setCatalog(catalogList.items)
      setAudit(auditList.items)
      setBudget(budgetInfo)
      setSelectedPlugin((current) => current || catalogList.items[0]?.name || '')
    } catch (e) {
      onError(e instanceof Error ? e.message : '设置数据加载失败。')
    } finally {
      setLoading(false)
    }
  }, [budgetPeriod, onError, token])

  // Settings combines several owner-scoped summaries.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load() }, [load])

  async function installPlugin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedPlugin) return
    try {
      await api('/plugins/install', token, { method: 'POST', body: JSON.stringify({ name: selectedPlugin }) })
      await load()
      onNotice('插件已安装，请按需启用。')
    } catch (e) { onError(e instanceof Error ? e.message : '插件安装失败。') }
  }

  async function pluginStatus(plugin: Plugin, status: 'enabled' | 'disabled') {
    try {
      await api('/plugins/' + plugin.id + '/status', token, { method: 'POST', body: JSON.stringify({ status }) })
      await load()
      onNotice(status === 'enabled' ? '插件已启用。' : '插件已停用。')
    } catch (e) { onError(e instanceof Error ? e.message : '插件状态更新失败。') }
  }

  async function removePlugin(plugin: Plugin) {
    if (!window.confirm('卸载插件「' + plugin.name + '」？')) return
    try {
      await api('/plugins/' + plugin.id, token, { method: 'DELETE' })
      await load()
      onNotice('插件已卸载。')
    } catch (e) { onError(e instanceof Error ? e.message : '插件卸载失败。') }
  }

  return <section className="graph-stack settings-extra">
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">BUDGET</p><h2>模型预算与用量</h2></div><label>周期<select value={budgetPeriod} onChange={(event) => setBudgetPeriod(event.target.value as 'day' | 'week' | 'month')}><option value="day">今日</option><option value="week">本周</option><option value="month">本月</option></select></label></div>
      {loading && <p className="muted" role="status">正在加载预算…</p>}
      {budget && <>
        <div className="budget-bar"><span style={{ width: (budget.limit_usd !== '0.00' ? Math.min(100, (Number(budget.spent_usd) / Number(budget.limit_usd)) * 100) : 0) + '%' }} /></div>
        <p className="muted">已用 ${budget.spent_usd} / ${budget.limit_usd} · 剩余 ${budget.remaining_usd}{budget.warning ? ' · 已达到 80% 提醒阈值' : ''}{budget.over_budget ? ' · 已超出月度预算' : ''}</p>
        <p className="small-note">{budget.runs} 次调用 · 输入 {budget.input_tokens} / 输出 {budget.output_tokens} token · 平均 {budget.avg_latency_ms} ms · 失败预留 ${budget.failure_reserve_usd}</p>
        {budget.by_provider.map((entry) => <div className="audit-row" key={entry.provider}><strong>{entry.provider}</strong><small>${entry.cost_usd} · {entry.runs} 次 · {entry.input_tokens}/{entry.output_tokens} token · {entry.avg_latency_ms} ms</small></div>)}
        {budget.by_purpose.length === 0 ? <p className="small-note">本周期还没有模型调用费用。</p> : budget.by_purpose.map((entry) => <div className="audit-row" key={entry.purpose}><strong>{entry.purpose}</strong><small>${entry.cost_usd} · {entry.runs} 次</small></div>)}
      </>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">PLUGINS</p><h2>连接器与 Agent 插件</h2></div><span className="count-pill">{plugins.length}</span></div>
      <p className="muted">插件使用本地清单声明权限；未声明的权限默认拒绝，失败不会影响主流程。</p>
      <form className="plugin-install" onSubmit={(event) => void installPlugin(event)}>
        <select aria-label="插件目录" value={selectedPlugin} onChange={(event) => setSelectedPlugin(event.target.value)}>{catalog.map((entry) => <option value={entry.name} key={entry.name}>{entry.name} · {entry.kind}</option>)}</select>
        <button className="secondary" disabled={!selectedPlugin}>安装插件</button>
      </form>
      {plugins.length === 0 && !loading && <p className="muted">还没有安装插件。</p>}
      {plugins.map((plugin) => <div className="plugin-row" key={plugin.id}>
        <div><strong>{plugin.name}</strong><small>{plugin.kind} · v{plugin.version} · {plugin.status} · {plugin.permissions.join(', ') || '无权限'}</small><p className="small-note">{plugin.description}</p></div>
        <div className="button-row">
          {plugin.status === 'enabled' ? <button className="text-button" onClick={() => void pluginStatus(plugin, 'disabled')}>停用</button> : <button className="text-button" onClick={() => void pluginStatus(plugin, 'enabled')}>启用</button>}
          <button className="text-button danger-text" onClick={() => void removePlugin(plugin)}>卸载</button>
        </div>
      </div>)}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">AUDIT</p><h2>插件审计</h2></div><span className="count-pill">{audit.length}</span></div>
      {audit.length === 0 && <p className="muted">还没有插件操作记录。</p>}
      {audit.slice(0, 20).map((entry) => <div className="audit-row" key={entry.id}><strong>{entry.action} · {entry.status}</strong><small>{new Date(entry.created_at).toLocaleString()}{typeof entry.detail.code === 'string' ? ' · ' + entry.detail.code : ''}</small></div>)}
    </section>
  </section>
}

const AGENT_KIND_LABELS: Record<string, string> = {
  create_reminder: '创建提醒',
  create_task: '创建任务',
  create_project: '创建项目',
  create_growth_record: '创建成长记录',
  update_goal_progress: '更新目标进度',
  create_review_draft: '创建复盘草稿',
  'external.send': '对外发送',
  'file.write': '修改原始文件',
  'payment.charge': '花钱/交易',
  'data.delete': '删除数据',
  'goal.change': '修改目标',
}

function AgentActionsPanel({ token, onError, onNotice }: { token: string; onError: (message: string) => void; onNotice: (message: string) => void }) {
  const [actions, setActions] = useState<AgentActionSummary[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const body = await api<{ items: AgentActionSummary[] }>('/agent/actions?limit=20', token)
      setActions(body.items)
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Agent 行动记录加载失败。')
    } finally {
      setLoading(false)
    }
  }, [onError, token])

  // Owner-scoped agent audit state.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load() }, [load])

  async function undo(action: AgentActionSummary) {
    try {
      await api('/agent/actions/' + action.id + '/undo', token, { method: 'POST' })
      await load()
      onNotice('已撤销这次自动写入。')
    } catch (e) { onError(e instanceof Error ? e.message : '撤销失败。') }
  }

  return <section className="panel settings-extra">
    <div className="panel-heading"><div><p className="eyebrow">AGENT AUDIT</p><h2>Agent 自动写入与撤销</h2></div><span className="count-pill">{actions.length}</span></div>
    <p className="muted">每次自动写入都会留下审计记录，并在 24 小时内可以一键撤销。对外发送、改原始文件、花钱、删除数据或改目标会被工具层拒绝。</p>
    {loading && <p className="muted" role="status">正在加载 Agent 记录…</p>}
    {!loading && actions.length === 0 && <p className="muted">还没有 Agent 行动记录。</p>}
    {actions.map((action) => <div className="agent-row" key={action.id}>
      <div>
        <strong>{AGENT_KIND_LABELS[action.kind] || action.kind} · {action.status}</strong>
        <small>{new Date(action.created_at).toLocaleString()} · 审批：{action.approval}{action.error_code ? ' · ' + action.error_code : ''}{action.undo_available ? ' · 可撤销至 ' + new Date(action.expires_at).toLocaleString() : ''}</small>
      </div>
      {action.undo_available && <button className="text-button danger-text" onClick={() => void undo(action)}>撤销</button>}
    </div>)}
  </section>
}

function basisLabel(basis: QaFact['basis']): string {
  if (basis === 'fact') return '事实'
  if (basis === 'inference') return '推断'
  return '不确定'
}

function intentLabel(intent: string | null): string {
  if (!intent) return '未识别意图'
  return ({ decision: '决定/承诺', project: '项目/目标', growth: '主题/成长', timeline: '时间线' } as Record<string, string>)[intent] || intent
}

function AnswerCard({ answer, onOpenCitation, onSuggestion }: { answer: QaAnswer; onOpenCitation: (itemId: string, sourceId: string) => void; onSuggestion: (suggestion: QaSuggestion) => void }) {
  return <article className="answer-card">
    <p className="answer-summary">{answer.summary}</p>
    <div className="answer-meta">
      <span className={'answer-badge ' + answer.status}>{answer.status === 'answered' ? '有证据' : '证据不足'}</span>
      <span>置信度 {percent(answer.confidence)}</span>
      <span>{intentLabel(answer.intent)}</span>
      <span>{answer.latency_ms} ms</span>
    </div>
    {answer.facts.length > 0 && <div className="answer-section">
      <p className="eyebrow">结构化事实</p>
      {answer.facts.map((fact, index) => <div className="fact-row" key={String(index)}>
        <div><strong>{fact.label}</strong><small>{fact.detail}</small></div>
        <span className={'basis-badge ' + fact.basis}>{basisLabel(fact.basis)} · {percent(fact.confidence)}</span>
      </div>)}
    </div>}
    {answer.citations.length > 0 && <div className="answer-section">
      <p className="eyebrow">原文引用</p>
      {answer.citations.map((citation) => <button type="button" className="citation-row" key={citation.evidence_id} onClick={() => onOpenCitation(citation.source_item_id, citation.source_id)}>
        <strong>{citation.item_title}</strong>
        <small>{citation.source_name} · {citation.occurred_at ? new Date(citation.occurred_at).toLocaleString() : '日期未知'} · {percent(citation.confidence)}</small>
        <span>{citation.quote}</span>
      </button>)}
    </div>}
    {answer.timeline_matches.length > 0 && <div className="answer-section">
      <p className="eyebrow">相关时间线</p>
      {answer.timeline_matches.map((match) => <button type="button" className="citation-row" key={match.source_item_id} onClick={() => onOpenCitation(match.source_item_id, match.source_id)}>
        <strong>{match.title}</strong>
        <small>{match.source_name} · {match.occurred_at ? new Date(match.occurred_at).toLocaleString() : '日期未知'}</small>
        <span>{match.snippet}</span>
      </button>)}
    </div>}
    {answer.review_matches.length > 0 && <div className="answer-section">
      <p className="eyebrow">相关复盘</p>
      {answer.review_matches.map((match) => <p className="small-note" key={match.id}>{new Date(match.period_start).toLocaleDateString()} — {new Date(match.period_end).toLocaleDateString()} · {match.snippet}</p>)}
    </div>}
    {answer.missing_info.length > 0 && <div className="answer-section">
      <p className="eyebrow">缺失信息</p>
      {answer.missing_info.map((item) => <p className="small-note" key={item}>· {item}</p>)}
    </div>}
    {answer.suggestions.length > 0 && <div className="answer-section">
      <p className="eyebrow">行动建议</p>
      <div className="button-row">{answer.suggestions.map((suggestion) => <button className="secondary" key={suggestion.label} onClick={() => onSuggestion(suggestion)}>{suggestion.label}</button>)}</div>
    </div>}
  </article>
}

function AskPanel({ token, sources, onError, onNotice, onOpenCitation }: { token: string; sources: Source[]; onError: (message: string) => void; onNotice: (message: string) => void; onOpenCitation: (itemId: string, sourceId: string) => void }) {
  const [threads, setThreads] = useState<QaThread[]>([])
  const [active, setActive] = useState<QaThread | null>(null)
  const [entities, setEntities] = useState<GraphEntity[]>([])
  const [sourceId, setSourceId] = useState('')
  const [entityId, setEntityId] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [loading, setLoading] = useState(true)

  function applyScope(scope: QaScope) {
    setSourceId(scope.source_ids[0] || '')
    setEntityId(scope.entity_ids[0] || '')
    setStart(scope.start ? scope.start.slice(0, 10) : '')
    setEnd(scope.end ? scope.end.slice(0, 10) : '')
  }

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [threadList, lastScope, entityList] = await Promise.all([
          api<{ items: QaThread[]; total: number }>('/qa/threads', token),
          api<{ thread_id: string | null; scope: QaScope }>('/qa/scope', token),
          api<{ items: GraphEntity[]; total: number }>('/graph/entities?limit=100', token),
        ])
        if (cancelled) return
        setThreads(threadList.items)
        setEntities(entityList.items)
        applyScope(lastScope.scope)
        if (threadList.items.length > 0) {
          const full = await api<QaThread>('/qa/threads/' + threadList.items[0].id, token)
          if (!cancelled) { setActive(full); applyScope(full.scope) }
        }
      } catch (e) {
        if (!cancelled) onError(e instanceof Error ? e.message : '问答历史加载失败。')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [onError, token])

  function currentScope(): QaScope {
    return {
      source_ids: sourceId ? [sourceId] : [],
      entity_ids: entityId ? [entityId] : [],
      start: start ? start + 'T00:00:00' : null,
      end: end ? end + 'T23:59:59' : null,
    }
  }

  async function selectThread(threadId: string) {
    try {
      const full = await api<QaThread>('/qa/threads/' + threadId, token)
      setActive(full)
      applyScope(full.scope)
    } catch (e) { onError(e instanceof Error ? e.message : '问答线程加载失败。') }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = question.trim()
    if (!text || asking) return
    setAsking(true)
    try {
      let thread = active
      if (!thread) {
        thread = await api<QaThread>('/qa/threads', token, { method: 'POST', body: JSON.stringify({ title: text.slice(0, 60), scope: currentScope() }) })
      }
      const updated = await api<QaThread>('/qa/threads/' + thread.id + '/messages', token, { method: 'POST', body: JSON.stringify({ question: text, scope: currentScope() }) })
      setActive(updated)
      setQuestion('')
      setThreads((current) => [updated, ...current.filter((entry) => entry.id !== updated.id)].map((entry) => ({ ...entry, messages: [] })))
    } catch (e) {
      onError(e instanceof Error ? e.message : '提问失败。')
    } finally {
      setAsking(false)
    }
  }

  async function deleteThread(threadId: string) {
    if (!window.confirm('删除这条问答历史？此操作不可撤销。')) return
    try {
      await api('/qa/threads/' + threadId, token, { method: 'DELETE' })
      setThreads((current) => current.filter((entry) => entry.id !== threadId))
      if (active?.id === threadId) setActive(null)
      onNotice('问答历史已删除。')
    } catch (e) { onError(e instanceof Error ? e.message : '问答历史删除失败。') }
  }

  async function exportThread(threadId: string, format: 'markdown' | 'json') {
    try {
      const response = await apiFetch('/qa/threads/' + threadId + '/export?format=' + format, { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('导出的问答历史不可用。')
      const blob = await response.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = 'qa-thread-' + threadId.slice(0, 8) + (format === 'json' ? '.json' : '.md')
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (e) { onError(e instanceof Error ? e.message : '问答历史导出失败。') }
  }

  async function runSuggestion(suggestion: QaSuggestion) {
    if (suggestion.kind === 'reminder') {
      try {
        await api('/reminders', token, { method: 'POST', body: JSON.stringify({ title: suggestion.label }) })
        onNotice('已创建提醒。')
      } catch (e) { onError(e instanceof Error ? e.message : '创建提醒失败。') }
      return
    }
    if (suggestion.source_item_id) {
      onOpenCitation(suggestion.source_item_id, '')
      return
    }
    onNotice('请到图谱或时间线中查看这条建议。')
  }

  function clearScope() {
    setSourceId('')
    setEntityId('')
    setStart('')
    setEnd('')
  }

  const scopeEntities = entities.filter((entity) => ['project', 'goal', 'topic'].includes(entity.entity_type))

  return <section className="ask-layout">
    <aside className="panel ask-history">
      <div className="panel-heading"><div><p className="eyebrow">HISTORY</p><h2>问答历史</h2></div><button className="text-button" onClick={() => setActive(null)}>新提问</button></div>
      {loading && <p className="muted" role="status">正在加载…</p>}
      {!loading && threads.length === 0 && <p className="muted">还没有问答记录。提出第一个问题后会保存在本机。</p>}
      {threads.map((thread) => <div className={'thread-item' + (active?.id === thread.id ? ' active' : '')} key={thread.id}>
        <button type="button" className="thread-open" onClick={() => void selectThread(thread.id)}><strong>{thread.title}</strong><small>{new Date(thread.updated_at).toLocaleString()}</small></button>
        <div className="button-row"><button className="text-button" onClick={() => void exportThread(thread.id, 'markdown')}>导出</button><button className="text-button danger-text" onClick={() => void deleteThread(thread.id)}>删除</button></div>
      </div>)}
    </aside>

    <div className="graph-stack">
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">SCOPE</p><h2>检索范围</h2></div><button className="text-button" onClick={clearScope}>清空范围</button></div>
        <div className="scope-grid">
          <label>来源<select value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">全部来源</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label>
          <label>项目/主题<select value={entityId} onChange={(event) => setEntityId(event.target.value)}><option value="">全部</option>{scopeEntities.map((entity) => <option value={entity.id} key={entity.id}>{entity.name}</option>)}</select></label>
          <label>开始<input type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
          <label>结束<input type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
        </div>
        <p className="small-note">范围会随当前线程记住；撤回或删除的来源不会进入答案。</p>
      </section>

      <InsightsPanel token={token} onError={onError} onNotice={onNotice} onOpenItem={onOpenCitation} />

      <section className="panel ask-chat">
        <div className="panel-heading"><div><p className="eyebrow">EVIDENCE Q&A</p><h2>{active ? active.title : '新的提问'}</h2></div><span className="count-pill">{active?.messages.length || 0} 条</span></div>
        <div className="chat-log">
          {!active && !loading && <div className="empty-state"><span>✦</span><strong>从你的证据图谱提问</strong><p>例如“我和谁约定了什么？”“这个项目进展如何？”“上周发生了什么？”</p></div>}
          {active?.messages.map((message) => message.role === 'user'
            ? <div className="chat-message user" key={message.id}><p>{message.content}</p></div>
            : message.answer ? <AnswerCard key={message.id} answer={message.answer} onOpenCitation={onOpenCitation} onSuggestion={(suggestion) => void runSuggestion(suggestion)} /> : null)}
          {asking && <p className="muted" role="status">正在检索证据并生成回答…</p>}
        </div>
        <form className="ask-form" onSubmit={(event) => void ask(event)}>
          <input aria-label="输入问题" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="问一个关于你的项目、决定、技能或时间线的问题" />
          <button className="primary" disabled={asking || !question.trim()}>{asking ? '检索中…' : '提问'}</button>
        </form>
      </section>
    </div>
  </section>
}

export default App
