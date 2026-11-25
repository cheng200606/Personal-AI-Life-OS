import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type Source = { id: string; kind: string; name: string; status: string; selected_scope: Record<string, unknown>; last_sync_at: string | null; cloud_consent_at: string | null; cloud_consent_version: string | null }
type Item = { id: string; source_id: string; kind: string; title: string; content_text: string; occurred_at: string | null; source_locator: Record<string, unknown>; metadata: Record<string, unknown> }
type Job = { id: string; kind: string; status: string; attempt_count: number; max_attempts: number; error_code: string | null; result_json: Record<string, unknown> | null }
type ReviewSuggestion = { text: string; source_ids: string[]; status?: 'pending' | 'dismissed' }
type ReviewModel = { job_id?: string; provider?: string; status?: string; model?: string | null; latency_ms?: number; estimated_cost_usd?: string }
type Review = { id: string; period_start: string; period_end: string; status: string; final_text: string | null; draft: { suggestions?: ReviewSuggestion[]; model?: ReviewModel }; source_items: Item[] }
type Reminder = { id: string; title: string; notes: string | null; due_at: string | null; status: string }
type ReviewSchedule = { enabled: boolean; weekday: number; local_hour: number; local_minute: number; timezone: string; use_external_model: boolean; last_run_at: string | null; next_run_at: string | null; last_review_id: string | null }
type SchedulePayload = { enabled: boolean; weekday: number; local_hour: number; local_minute: number; timezone: string; use_external_model: boolean }
type User = { id: string; email: string; timezone: string; ai_consent_at: string | null }
type Conversation = { id: string; title: string; created_at: number | null }
type Page = 'timeline' | 'ask' | 'graph' | 'reviews' | 'search' | 'account'
type SearchTimelineHit = { id: string; source_id: string; source_name: string; title: string; snippet: string; occurred_at: string | null; kind: string }
type SearchReviewHit = { id: string; period_start: string; period_end: string; status: string; snippet: string; updated_at: string }
type SearchReminderHit = { id: string; title: string; snippet: string; due_at: string | null; status: string }
type SearchGroup<T> = { total: number; results: T[] }
type SearchResults = { query: string; timeline: SearchGroup<SearchTimelineHit>; reviews: SearchGroup<SearchReviewHit>; reminders: SearchGroup<SearchReminderHit> }
type Disclosure = { available: boolean; provider: string | null; model: string | null; disclosure_version: string | null; data_sent: string; retention: string; privacy_url: string | null; input_cost_per_million_usd: string | null; output_cost_per_million_usd: string | null; max_cost_per_call_usd: string | null }
type GraphEvidence = { id: string; quote: string; confidence: number; availability: string; source_id: string; source_item_id: string; locator: Record<string, unknown> }
type GraphEntity = { id: string; entity_type: string; name: string; summary: string | null; confidence: number; status: string; evidence: GraphEvidence[] }
type GraphRelation = { id: string; from_entity_id: string; to_entity_id: string; relation_type: string; confidence: number; status: string; evidence: GraphEvidence[] }
type ReviewPayload = { entity_id?: string; relation_id?: string; name?: string; type?: string; relation_type?: string; from_entity_id?: string; to_entity_id?: string; ontology_type_id?: string; source_entity_id?: string; target_entity_id?: string }
type GraphReviewItem = { id: string; kind: string; payload: ReviewPayload; confidence: number; status: string; reason: string | null; extraction_run_id: string | null; created_at: string; resolved_at: string | null }
type GraphMerge = { id: string; source_entity_id: string | null; target_entity_id: string | null; source_name: string | null; target_name: string | null; status: string; evidence_count: number; relation_count: number; created_at: string; undone_at: string | null }
type OntologyType = { id: string; kind: string; name: string; description: string | null; status: string; source: string; created_by: string; version: number; created_at: string; updated_at: string }
type QaScope = { source_ids: string[]; entity_ids: string[]; start: string | null; end: string | null }
type QaCitation = { evidence_id: string; quote: string; confidence: number; availability: string; source_id: string; source_name: string; source_item_id: string; item_title: string; occurred_at: string | null; locator: Record<string, unknown> }
type QaFact = { label: string; detail: string; basis: 'fact' | 'inference' | 'uncertain'; confidence: number; entity_id: string | null; relation_id: string | null; citation_ids: string[] }
type QaSuggestion = { label: string; kind: string; entity_id: string | null; source_item_id: string | null }
type QaTimelineMatch = { source_item_id: string; source_id: string; source_name: string; title: string; snippet: string; occurred_at: string | null; kind: string }
type QaReviewMatch = { id: string; period_start: string; period_end: string; status: string; snippet: string }
type QaAnswer = { status: 'answered' | 'insufficient_evidence'; summary: string; facts: QaFact[]; citations: QaCitation[]; timeline_matches: QaTimelineMatch[]; review_matches: QaReviewMatch[]; missing_info: string[]; suggestions: QaSuggestion[]; confidence: number; scope: Record<string, unknown>; keywords: string[]; intent: string | null; latency_ms: number; version: string }
type QaMessage = { id: string; role: string; content: string; answer: QaAnswer | null; created_at: string }
type QaThread = { id: string; title: string; scope: QaScope; created_at: string; updated_at: string; messages: QaMessage[] }

const API = (import.meta.env.VITE_API_BASE_URL || '') + '/api/v1'
const GRAPH_CLOUD_CONSENT_VERSION = 'graph-cloud-v1'

async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', 'Bearer ' + token)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(API + path, { ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message || 'Request failed (' + response.status + ')')
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
  throw new Error('Background work is still running. Check the item status and retry if needed.')
}

function parseConversations(text: string): Conversation[] {
  const document = JSON.parse(text)
  const list = Array.isArray(document) ? document : document.conversations
  if (!Array.isArray(list)) throw new Error('Unsupported ChatGPT export. Choose conversations.json.')
  return list.map((entry: Record<string, unknown>, index: number) => ({
    id: String(entry.conversation_id || entry.id || 'conversation-' + (index + 1)),
    title: String(entry.title || 'Untitled conversation'),
    created_at: typeof entry.create_time === 'number' ? entry.create_time : null,
  }))
}

function sourceScopeDescription(source: Source): string {
  if (source.kind === 'chatgpt_export') {
    const ids = source.selected_scope.conversation_ids
    const count = Array.isArray(ids) ? ids.length : 0
    return `${count} selected conversations · user/assistant text, message IDs, and available timestamps`
  }
  if (source.kind === 'chat_export') {
    return 'Selected chat export · user/assistant text, conversation/message IDs, and available timestamps'
  }
  if (source.kind === 'photo') {
    const count = typeof source.selected_scope.file_count === 'number' ? source.selected_scope.file_count : 1
    return `${count} selected photo(s) · image pixels, optional capture time, and searchable OCR text; location metadata is stripped`
  }
  if (source.kind === 'document') {
    return 'Selected document · Markdown/TXT/PDF/DOCX text, headings/pages/paragraphs, and source locations'
  }
  return `Selected Markdown file · UTF-8 section text, headings, dates, and line locations (${source.name})`
}

function selectedFileDisclosure(file: File, selectedConversationCount: number): string {
  if (file.type.startsWith('image/')) {
    return 'This selected photo will be uploaded for re-encoding and OCR. EXIF and location metadata are removed from the stored copy. External description is a separate, optional action.'
  }
  const name = file.name.toLowerCase()
  if (name.endsWith('.jsonl')) {
    return 'The full selected JSONL chat export will be uploaded and parsed into user/assistant messages with available timestamps.'
  }
  if (name.endsWith('.json')) {
    return `If this is a ChatGPT export, only the ${selectedConversationCount} selected conversations are uploaded. Other JSON chat exports are uploaded as a whole file.`
  }
  if (name.endsWith('.pdf') || name.endsWith('.docx')) {
    return 'The full selected document will be uploaded; text is extracted locally and page/paragraph locations are retained. Scanned PDFs are not supported yet.'
  }
  if (name.endsWith('.txt')) {
    return 'The full selected text document will be uploaded and stored as one source item with line locations.'
  }
  return 'The full selected UTF-8 Markdown file will be uploaded and split into heading sections with dates and line locations. No other files are read.'
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('lifeos-token') || '')
  const [user, setUser] = useState<User | null>(null)
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null)
  const [page, setPage] = useState<Page>('timeline')
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
  const [pendingReviewTotal, setPendingReviewTotal] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [photoFiles, setPhotoFiles] = useState<File[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [photoDate, setPhotoDate] = useState('')
  const [photoPreview, setPhotoPreview] = useState('')
  const [photoDescriptions, setPhotoDescriptions] = useState<Record<string, string>>({})
  const directoryInput = useRef<HTMLInputElement>(null)
  const backgroundPolls = useRef(new Set<string>())
  const [consentAcknowledged, setConsentAcknowledged] = useState(false)
  const [externalModel, setExternalModel] = useState(false)
  const [loginMode, setLoginMode] = useState<'login' | 'register'>('login')
  const activeToken = useRef(token)

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const params = new URLSearchParams({ limit: '100', include_undated: 'true' })
      if (query) params.set('q', query)
      if (dateStart) params.set('start', dateStart)
      if (dateEnd) params.set('end', dateEnd)
      if (sourceFilter) params.set('source_id', sourceFilter)
      const [me, sourceList, timeline, reviewList, reminderList, modelDisclosure, reviewSchedule, reviewQueue] = await Promise.all([
        api<User>('/auth/me', token), api<Source[]>('/sources', token), api<{ items: Item[]; total: number; next_cursor: string | null }>('/timeline?' + params.toString(), token),
        api<Review[]>('/reviews', token), api<Reminder[]>('/reminders', token), fetch(API + '/auth/model-disclosure').then((response) => response.json() as Promise<Disclosure>),
        api<ReviewSchedule>('/review-schedule', token), api<{ total: number }>('/graph/review?status=pending&limit=1', token),
      ])
      if (activeToken.current !== token) return
      setUser(me); setSources(sourceList); setItems(timeline.items); setTimelineTotal(timeline.total); setTimelineCursor(timeline.next_cursor); setReviews(reviewList); setReminders(reminderList); setDisclosure(modelDisclosure); setSchedule(reviewSchedule); setPendingReviewTotal(reviewQueue.total)
    } catch (e) { if (activeToken.current === token) setError(e instanceof Error ? e.message : 'Could not load your workspace.') }
  }, [dateEnd, dateStart, query, sourceFilter, token])

  // This effect loads remote account state whenever its filters or token change.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { activeToken.current = token }, [token])
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 60000); return () => window.clearInterval(timer) }, [])
  useEffect(() => {
    if (!token || page !== 'reviews') return
    const load = () => Promise.all([
      api<Review[]>('/reviews', token), api<Reminder[]>('/reminders', token), api<ReviewSchedule>('/review-schedule', token),
    ]).then(([nextReviews, nextReminders, nextSchedule]) => { setReviews(nextReviews); setReminders(nextReminders); setSchedule(nextSchedule) }).catch(() => undefined)
    void load()
    const timer = window.setInterval(() => { void load() }, 60000)
    return () => window.clearInterval(timer)
  }, [page, token])
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
            ? result === 'fallback' ? 'The provider did not return a usable draft. The template review is ready.' : 'Weekly review draft is ready.'
            : kind === 'photo_description' ? 'Photo description draft is ready.' : 'Photo OCR processing finished.')
        } else setError(kind === 'weekly_review'
          ? 'The model review did not finish. The template draft remains available.'
          : kind === 'photo_description' ? 'Photo description did not finish. Retry it when ready.' : 'Photo OCR did not finish. Review the timeline and retry when ready.')
      }).catch((reason) => { if (activeToken.current === token) setError(reason instanceof Error ? reason.message : 'Background job status could not be loaded.') })
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
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load more timeline items.') }
  }

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    const data = new FormData(event.currentTarget)
    const body: Record<string, string> = { email: String(data.get('email')), password: String(data.get('password')) }
    if (loginMode === 'register') { body.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; body.invite_code = String(data.get('invite_code') || '') }
    try {
      const result = await fetch(API + '/auth/' + loginMode, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const payload = await result.json()
      if (!result.ok) throw new Error(payload?.error?.message || 'Authentication failed.')
      sessionStorage.setItem('lifeos-token', payload.access_token); activeToken.current = payload.access_token; setToken(payload.access_token)
    } catch (e) { setError(e instanceof Error ? e.message : 'Authentication failed.') } finally { setBusy(false) }
  }

  async function previewFiles(fileList: FileList | null, fromDirectory = false) {
    setFile(null); setPhotoFiles([]); setPhotoPreview('')
    setConversations([]); setSelected([]); setError(''); setNotice('')
    const selectedFiles = Array.from(fileList || [])
    const imageFiles = selectedFiles.filter((selectedFile) => /\.(jpe?g|png|webp)$/i.test(selectedFile.name))
    const skipped = selectedFiles.length - imageFiles.length
    const nextFiles = fromDirectory ? imageFiles : selectedFiles
    if (!fromDirectory && selectedFiles.length === 1 && imageFiles.length === 0 && !/\.(md|markdown|txt|pdf|docx|json|jsonl)$/i.test(selectedFiles[0].name)) {
      setError('Choose a Markdown, TXT, PDF, DOCX, or chat export file, or a supported JPEG, PNG, or WebP photo.')
      return
    }
    if (nextFiles.length > 10) { setError('Select at most 10 photos per import.'); return }
    if (nextFiles.length > 1 && (imageFiles.length !== nextFiles.length || !fromDirectory && selectedFiles.some((selectedFile) => !/\.(jpe?g|png|webp)$/i.test(selectedFile.name)))) {
      setError('Select one text/document/chat file, or choose only supported photo files.'); return
    }
    if (fromDirectory && nextFiles.length === 0) { setError('The selected folder contains no supported JPEG, PNG, or WebP photos.'); return }
    const next = nextFiles[0] || null
    setFile(next); setPhotoFiles(nextFiles.length && nextFiles.every((selectedFile) => /\.(jpe?g|png|webp)$/i.test(selectedFile.name)) ? nextFiles : [])
    setPhotoPreview(next && /\.(jpe?g|png|webp)$/i.test(next.name) ? URL.createObjectURL(next) : '')
    if (fromDirectory && skipped) setNotice(`${skipped} non-photo file(s) in the folder were ignored.`)
    if (nextFiles.length === 1 && next?.name.toLowerCase().endsWith('.json')) {
      try {
        const text = await next.text()
        const document = JSON.parse(text)
        const list = Array.isArray(document) ? document : document.conversations
        const hasMessages = !Array.isArray(list) && document && typeof document === 'object' && ['messages', 'chat_messages', 'turns'].some((key) => Array.isArray(document[key]))
        if (!Array.isArray(list) && !hasMessages) throw new Error('Unsupported chat export. Choose a JSON/JSONL chat export or a document.')
        const isChatGPT = Array.isArray(list) && list.some((entry) => entry && typeof entry === 'object' && 'mapping' in entry)
        setConversations(isChatGPT ? parseConversations(text) : [])
        if (!isChatGPT) setNotice('This JSON chat export will be uploaded as a whole file.')
      } catch (e) { setError(e instanceof Error ? e.message : 'Could not preview this file.') }
    }
  }

  async function importSelected(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return
    const lower = file.name.toLowerCase()
    let kind = photoFiles.length ? 'photo' : lower.endsWith('.jsonl') ? 'chat_export' : lower.endsWith('.json') ? 'chatgpt_export' : 'document'
    if (kind === 'chatgpt_export') {
      try {
        const document = JSON.parse(await file.text())
        const conversations = Array.isArray(document) ? document : document.conversations
        const looksLikeChatGPT = Array.isArray(conversations) && conversations.some((entry) => entry && typeof entry === 'object' && 'mapping' in entry)
        if (!looksLikeChatGPT) kind = 'chat_export'
      } catch { setError('Could not read this JSON file.'); return }
    }
    if (kind === 'chatgpt_export' && selected.length === 0) { setError('Select at least one conversation.'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const created = await api<Source>('/sources', token, { method: 'POST', body: JSON.stringify({ kind, name: kind === 'photo' ? `Photo import · ${photoFiles.length} photos` : file.name, selected_scope: kind === 'chatgpt_export' ? { conversation_ids: selected } : kind === 'photo' ? { file_count: photoFiles.length } : {} }) })
      const uploads = kind === 'photo' ? photoFiles : [file]
      const jobIds: string[] = []
      const uploadErrors: string[] = []
      let createdItems = 0
      let duplicateItems = 0
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
          const result = await api<{ sync_run: { items_created: number; items_duplicate: number }; job_ids: string[] }>('/sources/' + created.id + '/imports', token, { method: 'POST', body: form })
          createdItems += result.sync_run.items_created
          duplicateItems += result.sync_run.items_duplicate
          jobIds.push(...result.job_ids)
        } catch (reason) {
          if (kind !== 'photo') throw reason
          uploadErrors.push(selectedFile.name)
        }
      }
      setNotice(jobIds.length ? `Uploaded ${jobIds.length} photo(s); OCR is processing.` : `Imported ${createdItems} new item(s); ${duplicateItems} unchanged.`)
      if (uploadErrors.length) setError(`${uploadErrors.length} photo(s) could not be imported: ${uploadErrors.join(', ')}`)
      setFile(null); setPhotoFiles([]); setPhotoDate(''); setPhotoPreview(''); setSelected([]); setConversations([]); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Import failed.') } finally { setBusy(false) }
  }

  async function retryPhotoOcr(item: Item) {
    const jobId = typeof item.metadata.ocr_job_id === 'string' ? item.metadata.ocr_job_id : ''
    if (!jobId) return
    try {
      await api<Job>('/jobs/' + jobId + '/retry', token, { method: 'POST' })
      setNotice('Photo OCR retry queued.')
      const result = await waitForJob(jobId, token)
      await refresh()
      if (result.status === 'completed') setNotice(`Photo processing finished: ${String(result.result_json?.ocr_status || 'complete')}.`)
      else setError('Photo OCR failed again. The sanitized photo remains available.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not retry photo OCR.') }
  }

  async function sourceAction(source: Source, action: 'pause' | 'resume' | 'revoke' | 'delete') {
    if (action === 'delete' && !window.confirm('Delete this source and its imported data?')) return
    setError('')
    try {
      if (action === 'delete') await api('/sources/' + source.id, token, { method: 'DELETE' })
      else if (action === 'revoke') await api('/sources/' + source.id + '/revoke', token, { method: 'POST' })
      else await api('/sources/' + source.id + '/status', token, { method: 'PATCH', body: JSON.stringify({ status: action === 'pause' ? 'paused' : 'active' }) })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Source update failed.') }
  }

  async function setCloudConsent(source: Source, enabled: boolean) {
    setError('')
    try {
      await api('/sources/' + source.id + '/cloud-consent', token, { method: 'PATCH', body: JSON.stringify({ enabled, consent_version: GRAPH_CLOUD_CONSENT_VERSION }) })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not update cloud extraction consent.') }
  }

  async function exportItem(item: Item) {
    const source = sources.find((entry) => entry.id === item.source_id)
    const text = ['---', 'id: ' + item.id, 'source: ' + JSON.stringify(source?.name || 'Life OS'), 'occurred_at: ' + (item.occurred_at || 'unknown'), 'source_locator: ' + JSON.stringify(item.source_locator), '---', '', '# ' + item.title, '', item.content_text].join('\n')
    const filename = (item.title.replace(/[^\p{L}\p{N}-]+/gu, '-').replace(/^-|-$/g, '').slice(0, 72) || 'lifeos-note') + '-' + item.id.slice(0, 8)
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename + '.md'; link.click(); URL.revokeObjectURL(link.href)
  }

  async function downloadSource(item: Item) {
    try {
      const response = await fetch(API + '/items/' + item.id + '/raw', { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('Source file is unavailable or access was revoked.')
      const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'lifeos-source.bin'; link.click(); URL.revokeObjectURL(link.href)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not download the source.') }
  }

  async function deleteItem(item: Item) {
    const source = sources.find((entry) => entry.id === item.source_id)
    const label = source ? '"' + source.name + '"' : 'this imported source'
    if (!window.confirm('Delete ' + label + '? This removes the original file and every timeline entry created from that source, not just this entry. This cannot be undone.')) return
    try { await api('/items/' + item.id, token, { method: 'DELETE' }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete the source data.') }
  }

  async function describePhoto(item: Item) {
    setError('')
    try {
      const regenerate = Boolean(photoDescriptions[item.id]) || item.metadata.description_status === 'confirmed'
      const result = await api<{ description?: string; job_id?: string }>('/items/' + item.id + '/describe' + (regenerate ? '?regenerate=true' : ''), token, { method: 'POST' })
      if (result.job_id) {
        setNotice('Photo description is processing.')
        const job = await waitForJob(result.job_id, token)
        if (job.status !== 'completed' || typeof job.result_json?.description !== 'string') throw new Error('Photo description did not finish. You can retry from the photo.')
        result.description = job.result_json.description as string
      }
      const description = result.description
      if (!description) throw new Error('The model did not return a description.')
      setPhotoDescriptions((current) => ({ ...current, [item.id]: description }))
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Photo description failed.'); await refresh() }
  }

  async function confirmPhotoDescription(item: Item) {
    const description = photoDescriptions[item.id]
    if (!description) return
    try {
      await api('/items/' + item.id + '/description', token, { method: 'POST', body: JSON.stringify({ description }) })
      setPhotoDescriptions((current) => { const next = { ...current }; delete next[item.id]; return next })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save the photo description.') }
  }

  async function generateReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); setBusy(true); setError('')
    try {
      const review = await api<Review>('/reviews/generate', token, { method: 'POST', body: JSON.stringify({ period_start: data.get('start'), period_end: data.get('end'), use_external_model: externalModel }) })
      await refresh()
      const jobId = review.draft.model?.job_id
      if (jobId) setNotice('Weekly review is processing. The local template is available while it runs.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Review generation failed.') } finally { setBusy(false) }
  }

  async function saveReview(review: Review, text: string) {
    try { await api('/reviews/' + review.id, token, { method: 'PATCH', body: JSON.stringify({ final_text: text }) }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not save review.') }
  }

  async function updateSuggestion(review: Review, index: number, patch: { text?: string; status?: 'pending' | 'dismissed' }) {
    try { await api('/reviews/' + review.id + '/suggestions/' + index, token, { method: 'PATCH', body: JSON.stringify(patch) }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not update this suggestion.') }
  }

  async function saveSchedule(payload: SchedulePayload) {
    try {
      const saved = await api<ReviewSchedule>('/review-schedule', token, { method: 'PUT', body: JSON.stringify(payload) })
      setSchedule(saved)
      setNotice(saved.enabled ? 'Weekly review schedule saved.' : 'Weekly review schedule turned off.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save the weekly review schedule.') }
  }

  async function updateReminder(reminder: Reminder, status: string) {
    try { await api('/reminders/' + reminder.id + '/status', token, { method: 'PATCH', body: JSON.stringify({ status }) }); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not update reminder.') }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const dueValue = String(data.get('due_at') || '')
    try { await api('/reminders', token, { method: 'POST', body: JSON.stringify({ title: data.get('title'), due_at: dueValue ? new Date(dueValue).toISOString() : null }) }); form.reset(); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not create reminder.') }
  }

  async function createReminderFromSuggestion(suggestion: ReviewSuggestion) {
    try {
      await api('/reminders', token, {
        method: 'POST',
        body: JSON.stringify({ title: suggestion.text, source_item_ids: suggestion.source_ids }),
      })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create reminder from this suggestion.') }
  }

  async function setModelConsent(enabled: boolean) {
    if (!disclosure?.disclosure_version || (enabled && !consentAcknowledged)) return
    try {
      await api('/auth/ai-consent', token, { method: 'PUT', body: JSON.stringify({ enabled, disclosure_version: disclosure.disclosure_version }) })
      setConsentAcknowledged(false); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not update AI consent.') }
  }

  async function downloadReview(review: Review) {
    try {
      const response = await fetch(API + '/reviews/' + review.id + '/export.md', { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('This review cannot be exported yet.')
      const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'weekly-review-' + review.period_start.slice(0, 10) + '.md'; link.click(); URL.revokeObjectURL(link.href)
    } catch (e) { setError(e instanceof Error ? e.message : 'Review export failed.') }
  }

  function openSource(item: Item) {
    setPage('timeline'); setSourceFilter(item.source_id); setDateStart(''); setDateEnd(''); setQuery('')
    window.setTimeout(() => document.getElementById('timeline-item-' + item.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450)
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = searchQuery.trim()
    if (!trimmed) return
    setSearchLoading(true); setError('')
    try {
      const results = await api<SearchResults>('/search?q=' + encodeURIComponent(trimmed), token)
      setSearchResults(results)
    } catch (e) { setError(e instanceof Error ? e.message : 'Search failed. Try again.') }
    finally { setSearchLoading(false) }
  }

  function openTimelineHit(hit: SearchTimelineHit) {
    setPage('timeline'); setSourceFilter(hit.source_id); setDateStart(''); setDateEnd(''); setQuery('')
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
      const response = await fetch(API + '/account/archive', { headers: { Authorization: 'Bearer ' + token } })
      if (!response.ok) throw new Error('Could not create account archive.')
      const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'lifeos-archive.zip'; link.click(); URL.revokeObjectURL(link.href)
    } catch (e) { setError(e instanceof Error ? e.message : 'Archive failed.') }
  }

  async function deleteAccount() {
    if (!window.confirm('Permanently delete your account and all stored data? Export your archive first if you need a copy.')) return
    try { await api('/account', token, { method: 'DELETE' }); sessionStorage.removeItem('lifeos-token'); activeToken.current = ''; setToken(''); setUser(null) }
    catch (e) { setError(e instanceof Error ? e.message : 'Account deletion failed.') }
  }

  if (!token) return <main className="auth-shell"><section className="auth-card"><div className="brand-mark">L</div><p className="eyebrow">PERSONAL AI LIFE OS</p><h1>Your life, with context.</h1><p className="muted">Choose what to remember. Review it with sources. Keep your notes portable.</p><form onSubmit={authenticate} className="stack"><label>Email<input name="email" type="email" required autoComplete="email" /></label><label>Password<input name="password" type="password" minLength={12} required autoComplete={loginMode === 'login' ? 'current-password' : 'new-password'} /></label>{loginMode === 'register' && <label>Invitation code <span className="muted">(if required)</span><input name="invite_code" /></label>}<button className="primary" disabled={busy}>{busy ? 'Please wait…' : loginMode === 'login' ? 'Sign in' : 'Create account'}</button></form><button className="text-button" onClick={() => setLoginMode(loginMode === 'login' ? 'register' : 'login')}>{loginMode === 'login' ? 'Create an account' : 'Back to sign in'}</button>{error && <p className="notice error">{error}</p>}</section></main>

  const searchTotal = searchResults ? searchResults.timeline.total + searchResults.reviews.total + searchResults.reminders.total : 0
  const dueReminders = reminders.filter((reminder) => ['pending', 'snoozed'].includes(reminder.status) && reminder.due_at && new Date(reminder.due_at).getTime() <= now)
  const readyReview = schedule?.last_review_id ? reviews.find((review) => review.id === schedule.last_review_id && review.status === 'draft') : undefined
  const pageTitle: Record<Page, string> = { timeline: 'Timeline', ask: '提问', graph: '图谱与待审', search: 'Search', reviews: 'Weekly review', account: 'Account & sources' }

  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark small">L</span><span>Life OS</span></div><nav aria-label="Main navigation"><button className={page === 'timeline' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('timeline')}>◷ <span>Timeline</span></button><button className={page === 'ask' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('ask')}>✦ <span>提问</span></button><button className={page === 'graph' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('graph')}>◇ <span>图谱与待审</span>{pendingReviewTotal > 0 && <span className="nav-badge">{pendingReviewTotal}</span>}</button><button className={page === 'search' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('search')}>⌕ <span>Search</span></button><button className={page === 'reviews' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('reviews')}>✳ <span>Weekly review</span>{dueReminders.length > 0 && <span className="nav-badge">{dueReminders.length}</span>}</button><button className={page === 'account' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('account')}>⚙ <span>Account & sources</span></button></nav><div className="sidebar-foot"><span className="avatar">{user?.email.slice(0, 1).toUpperCase()}</span><span className="user-email">{user?.email}</span><button className="icon-button" title="Sign out" onClick={() => { sessionStorage.removeItem('lifeos-token'); activeToken.current = ''; setToken(''); setUser(null) }}>↗</button></div></aside>
    <main className="main"><header className="topbar"><div><p className="eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</p><h1>{pageTitle[page]}</h1></div><span className="privacy-pill"><span className="live-dot" /> Private workspace</span></header>
      {error && <div className="notice error" role="alert">{error}<button className="icon-button" onClick={() => setError('')}>×</button></div>}
      {notice && <div className="notice success" role="status">{notice}<button className="icon-button" onClick={() => setNotice('')}>×</button></div>}
      {page === 'ask' && <AskPanel token={token} sources={sources} onError={setError} onNotice={setNotice} onOpenCitation={openTimelineCitation} />}
      {page === 'graph' && <GraphPanel token={token} onError={setError} onNotice={setNotice} onPendingChange={setPendingReviewTotal} />}
      {page === 'timeline' && <><section className="hero-panel"><div><p className="eyebrow">CAPTURE WHAT MATTERS</p><h2>Make your context useful.</h2><p className="muted">Import selected notes, conversations, or photos. Your timeline keeps every detail connected to its source.</p></div><div className="stat"><strong>{timelineTotal}</strong><span>timeline items</span></div></section>
        {pendingReviewTotal > 0 && <div className="notice success">有 {pendingReviewTotal} 条低置信度图谱条目待审。<button className="text-button" onClick={() => setPage('graph')}>去处理 ↗</button></div>}
        <section className="panel import-panel"><div className="panel-heading"><div><p className="eyebrow">ADD A SOURCE</p><h2>Import selected material</h2></div><span className="limit-pill">Up to 5 MB text · 20 MB photo</span></div><form onSubmit={importSelected} className="import-form"><label className="file-drop"><span className="upload-icon">↑</span><span><strong>{file ? file.name : 'Choose a file'}</strong><small>Markdown, TXT, PDF, DOCX, chat JSON/JSONL, JPEG, PNG, or WebP</small></span><input type="file" accept=".md,.markdown,.txt,.pdf,.docx,.json,.jsonl,image/jpeg,image/png,image/webp" multiple onChange={(event) => void previewFiles(event.target.files)} /></label><label className="folder-picker">Choose a photo folder<input ref={directoryInput} type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => void previewFiles(event.target.files, true)} /></label>{conversations.length > 0 && <div className="selection-box"><div className="selection-head"><strong>Select conversations to import</strong><button type="button" className="text-button" onClick={() => setSelected(selected.length === conversations.length ? [] : conversations.map((entry) => entry.id))}>{selected.length === conversations.length ? 'Clear selection' : 'Select all'}</button></div><div className="conversation-list">{conversations.map((entry) => <label className="conversation" key={entry.id}><input type="checkbox" checked={selected.includes(entry.id)} onChange={(event) => setSelected(event.target.checked ? [...selected, entry.id] : selected.filter((value) => value !== entry.id))} /><span>{entry.title}<small>{entry.created_at ? new Date(entry.created_at * 1000).toLocaleDateString() : 'Date unknown'}</small></span></label>)}</div><p className="small-note">Unselected conversations stay on this device and are not uploaded.</p></div>}{photoFiles.length > 0 && <><p className="small-note">{photoFiles.length} photo(s) selected. Each photo is uploaded separately; folder paths and unsupported files are not sent.</p>{photoFiles.length === 1 && <div className="local-photo-preview"><img src={photoPreview} alt="Selected photo preview" /><p className="small-note">The saved photo is re-encoded to remove EXIF location and other metadata. OCR text is searchable.</p></div>}{photoFiles.length === 1 && <label className="inline-field">Photo date (optional)<input type="datetime-local" value={photoDate} onChange={(event) => setPhotoDate(event.target.value)} /></label>}</>}<div className="import-actions"><p className="small-note">Files are processed only after you submit this selection.</p>{photoFiles.length > 1 ? <p className="selection-disclosure"><strong>{photoFiles.length} photos · {photoFiles.reduce((total, selectedFile) => total + selectedFile.size, 0).toLocaleString()} bytes.</strong> Selected photos will be sanitized and processed; EXIF/GPS metadata is removed.</p> : file && <p className="selection-disclosure"><strong>{file.name} · {file.size.toLocaleString()} bytes.</strong> {selectedFileDisclosure(file, selected.length)}</p>}<button className="primary" disabled={busy || !file}>{busy ? 'Importing…' : 'Import selected'}</button></div></form></section>
        <section className="timeline-layout"><div className="panel timeline-panel"><div className="panel-heading"><div><p className="eyebrow">YOUR RECORD</p><h2>Recent activity</h2></div><span className="count-pill">{visibleItems.length} / {timelineTotal}</span></div><label className="search"><span>⌕</span><input aria-label="Search timeline" placeholder="Search notes and conversations" value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label><div className="filter-row"><label>From<input type="date" value={dateStart} onChange={(event) => setDateStart(event.target.value)} /></label><label>Until<input type="date" value={dateEnd} onChange={(event) => setDateEnd(event.target.value)} /></label><label>Source<select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">All sources</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label></div><div className="timeline-list">{visibleItems.map((item) => { const source = sources.find((entry) => entry.id === item.source_id); return <article className="timeline-item" id={'timeline-item-' + item.id} key={item.id}><span className="timeline-marker">{item.kind === 'chat_message' ? '✳' : item.kind === 'photo' ? '▧' : '▤'}</span><div className="item-content"><div className="item-meta"><span>{item.occurred_at ? new Date(item.occurred_at).toLocaleString() : 'Date unknown'}</span><span className="dot-separator">·</span><span>{source?.name || 'Imported source'}</span></div><h3>{item.title}</h3>{item.kind === 'photo' && Boolean(item.metadata.ocr_status) && <div className="photo-ocr-state"><span>OCR: {String(item.metadata.ocr_status).replace('_', ' ')}</span>{['failed', 'cancelled'].includes(String(item.metadata.ocr_status)) && <button className="text-button" onClick={() => void retryPhotoOcr(item)}>Retry OCR</button>}</div>}{item.kind === 'photo' && <><PhotoImage itemId={item.id} token={token} />{disclosure?.available && <div className="photo-description"><button className="text-button" disabled={!user?.ai_consent_at || ['queued', 'running'].includes(String(item.metadata.description_status))} onClick={() => void describePhoto(item)}>{['queued', 'running'].includes(String(item.metadata.description_status)) ? 'Generating…' : photoDescriptions[item.id] || item.metadata.description_status === 'confirmed' ? 'Generate another draft' : item.metadata.description_status === 'draft' ? 'Review saved draft' : ['failed', 'cancelled'].includes(String(item.metadata.description_status)) ? 'Retry description' : 'Describe with AI'}</button><span className="small-note">Sends this sanitized photo to {disclosure.provider} after consent.</span>{photoDescriptions[item.id] && <><textarea value={photoDescriptions[item.id]} onChange={(event) => setPhotoDescriptions((current) => ({ ...current, [item.id]: event.target.value }))} rows={3} aria-label="Photo description draft" /><button className="secondary" onClick={() => void confirmPhotoDescription(item)}>Add description to timeline</button></>}</div>}</>}<p>{item.content_text.slice(0, 360)}{item.content_text.length > 360 ? '…' : ''}</p><div className="item-actions"><span className="source-tag">{String(item.source_locator.role || item.kind)}</span><button className="text-button" onClick={() => void exportItem(item)}>Export Markdown ↗</button><button className="text-button" onClick={() => void downloadSource(item)}>Download source ↗</button><button className="text-button danger-text" onClick={() => void deleteItem(item)}>Delete imported source</button></div></div></article> })}{visibleItems.length === 0 && <div className="empty-state"><span>◷</span><strong>Your timeline is ready</strong><p>Import a selected Markdown note or ChatGPT conversation to see it here.</p></div>}</div>{timelineCursor && <button className="secondary full" onClick={() => void loadMoreTimeline()}>Load more timeline items</button>}</div><aside className="panel source-rail"><div className="panel-heading"><div><p className="eyebrow">CONNECTED SOURCES</p><h2>Sources</h2></div><span className="count-pill">{sources.length}</span></div>{sources.length === 0 && <p className="muted">Your selected sources will appear here.</p>}{sources.slice(0, 5).map((source) => <div className="source-row" key={source.id}><span className="source-icon">{source.kind === 'photo' ? '▧' : source.kind === 'chatgpt_export' ? '✳' : '▤'}</span><div><strong>{source.name}</strong><small>{source.status.replace('_', ' ')}</small></div><span className={source.status === 'active' ? 'status-dot' : 'status-dot paused'} /></div>)}<button className="secondary full" onClick={() => setPage('account')}>Manage sources</button></aside></section></>}
      {page === 'search' && <section className="panel search-page">
        <div className="panel-heading"><div><p className="eyebrow">UNIFIED SEARCH</p><h2>Find anything you kept</h2></div></div>
        <form className="search-form" onSubmit={submitSearch}>
          <label>Search timeline, reviews, and reminders<input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Try a topic, person, or promise" /></label>
          <button className="primary" disabled={searchLoading || !searchQuery.trim()}>{searchLoading ? 'Searching…' : 'Search'}</button>
        </form>
        {searchLoading && <p className="muted" role="status">Searching your timeline, reviews, and reminders…</p>}
        {!searchLoading && !searchResults && <p className="muted">Search titles and text across your timeline, weekly reviews, and reminders. Each result links back to the original record.</p>}
        {!searchLoading && searchResults && searchTotal === 0 && <div className="empty-state"><span>⌕</span><strong>No results</strong><p>Nothing matched “{searchResults.query}”. Try a different or shorter word.</p></div>}
        {!searchLoading && searchResults && searchTotal > 0 && <div className="search-results">
          {searchResults.timeline.results.length > 0 && <section className="search-group">
            <div className="panel-heading"><h3>Timeline <span className="count-pill">{searchResults.timeline.total}</span></h3></div>
            {searchResults.timeline.results.map((hit) => <button type="button" className="search-result" key={hit.id} onClick={() => openTimelineHit(hit)}><strong>{hit.title}</strong><span className="search-result-meta">{hit.source_name} · {hit.occurred_at ? new Date(hit.occurred_at).toLocaleString() : 'Date unknown'}</span><span className="search-result-snippet">{hit.snippet}</span></button>)}
          </section>}
          {searchResults.reviews.results.length > 0 && <section className="search-group">
            <div className="panel-heading"><h3>Weekly reviews <span className="count-pill">{searchResults.reviews.total}</span></h3></div>
            {searchResults.reviews.results.map((hit) => <button type="button" className="search-result" key={hit.id} onClick={() => openReviewHit(hit)}><strong>{new Date(hit.period_start).toLocaleDateString()} — {new Date(hit.period_end).toLocaleDateString()}</strong><span className="search-result-meta">{hit.status}</span><span className="search-result-snippet">{hit.snippet}</span></button>)}
          </section>}
          {searchResults.reminders.results.length > 0 && <section className="search-group">
            <div className="panel-heading"><h3>Reminders <span className="count-pill">{searchResults.reminders.total}</span></h3></div>
            {searchResults.reminders.results.map((hit) => <button type="button" className="search-result" key={hit.id} onClick={() => openReminderHit(hit)}><strong>{hit.title}</strong><span className="search-result-meta">{hit.status} · {hit.due_at ? new Date(hit.due_at).toLocaleString() : 'No due date'}</span><span className="search-result-snippet">{hit.snippet}</span></button>)}
          </section>}
        </div>}
      </section>}
      {page === 'reviews' && schedule && <ReviewSchedulePanel schedule={schedule} timezone={user?.timezone || 'UTC'} consentEnabled={Boolean(user?.ai_consent_at)} onSave={saveSchedule} readyReview={readyReview} onOpenReview={(review) => document.getElementById('review-' + review.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })} />}
      {page === 'reviews' && dueReminders.length > 0 && <DueRemindersPanel reminders={dueReminders} onAction={updateReminder} />}
      {page === 'reviews' && <section className="review-grid"><div className="panel"><div className="panel-heading"><div><p className="eyebrow">A MOMENT TO REFLECT</p><h2>Start a weekly review</h2></div></div><p className="muted">Build an editable draft from this period’s timeline. Every generated fact links back to its source.</p><form className="review-form" onSubmit={generateReview}><label>From<input name="start" type="date" required /></label><label>Until <small>(exclusive)</small><input name="end" type="date" required /></label><label className="check-row"><input type="checkbox" checked={externalModel} disabled={!disclosure?.available || !user?.ai_consent_at} onChange={(event) => setExternalModel(event.target.checked)} /><span>Use external AI model<br /><small>Enable current provider consent in Account first.</small></span></label><button className="primary" disabled={busy}>{busy ? 'Preparing…' : 'Generate draft'}</button></form><div className="subsection"><div className="panel-heading"><h2>Reminders</h2></div><form className="reminder-form" onSubmit={createReminder}><input name="title" placeholder="What should you follow up on?" required /><input name="due_at" type="datetime-local" aria-label="Reminder due date" /><button className="secondary">Add reminder</button></form>{reminders.map((reminder) => <div className="reminder-row" id={'reminder-' + reminder.id} key={reminder.id}><div><strong>{reminder.title}</strong><small>{reminder.due_at ? new Date(reminder.due_at).toLocaleString() : 'No due date'} · {reminder.status}</small></div>{reminder.status !== 'completed' && reminder.status !== 'cancelled' && <><button className="text-button" onClick={() => void updateReminder(reminder, 'completed')}>Complete</button><button className="text-button" onClick={() => void updateReminder(reminder, 'snoozed')}>Snooze</button><button className="text-button" onClick={() => void updateReminder(reminder, 'cancelled')}>Dismiss</button></>}</div>)}</div></div><div className="review-list">{reviews.map((review) => <ReviewCard key={review.id + (review.final_text || "")} review={review} onSave={saveReview} onOpenSource={openSource} onExport={downloadReview} onCreateReminder={createReminderFromSuggestion} onUpdateSuggestion={updateSuggestion} />)}{reviews.length === 0 && <div className="panel empty-state"><span>✳</span><strong>Your reviews will appear here</strong><p>Choose a date range to make a draft from sourced timeline items.</p></div>}</div></section>}
      {page === 'account' && <section className="account-grid"><div className="panel"><p className="eyebrow">PROFILE</p><h2>{user?.email}</h2><p className="muted">Timezone: {user?.timezone}</p><div className="subsection"><p className="eyebrow">MODEL DATA CONSENT</p>{disclosure?.available ? <><p className="muted">Provider: {disclosure.provider} · Model: {disclosure.model}</p><p className="muted">Data sent: {disclosure.data_sent}</p><p className="muted">Retention: {disclosure.retention}</p><p className="muted">Configured estimate: ${disclosure.input_cost_per_million_usd} per million input tokens and ${disclosure.output_cost_per_million_usd} per million output tokens. Per-call budget check: ${disclosure.max_cost_per_call_usd}. A call that fails or exceeds the estimate may still incur provider charges.</p>{disclosure.privacy_url && <p><a href={disclosure.privacy_url} target="_blank" rel="noreferrer">Provider privacy terms ↗</a></p>}<label className="check-row consent-check"><input type="checkbox" checked={consentAcknowledged} onChange={(event) => setConsentAcknowledged(event.target.checked)} /><span>I have reviewed the provider and data handling disclosure above.</span></label><p className="small-note">Current consent: {user?.ai_consent_at ? 'Enabled' : 'Off'}</p><div className="button-row"><button className="primary" disabled={!consentAcknowledged || Boolean(user?.ai_consent_at)} onClick={() => void setModelConsent(true)}>Enable external AI</button><button className="secondary" disabled={!user?.ai_consent_at} onClick={() => void setModelConsent(false)}>Turn off</button></div></> : <p className="muted">No external model is configured. Template-based reviews remain available, and no review data is sent to a model provider.</p>}</div><div className="subsection"><p className="eyebrow">YOUR DATA</p><p className="muted">Download a portable archive or permanently delete your account and stored records.</p><div className="button-row"><button className="secondary" onClick={() => void downloadAccountArchive()}>Download archive</button><button className="danger" onClick={() => void deleteAccount()}>Delete account</button></div></div></div><div className="panel"><div className="panel-heading"><div><p className="eyebrow">YOUR SELECTIONS</p><h2>Manage sources</h2></div></div>{sources.map((source) => <div className="manage-source" key={source.id}><div><strong>{source.name}</strong><small>{source.kind.replace('_', ' ')} · {source.status}</small><p className="source-scope">{sourceScopeDescription(source)}</p><small>Last import: {source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : 'Never'}</small><small>Cloud extraction: {source.cloud_consent_at ? 'Allowed' : 'Off'}</small></div><div className="button-row">{source.status === 'active' && <button className="text-button" onClick={() => void sourceAction(source, 'pause')}>Pause</button>}{source.status === 'paused' && <button className="text-button" onClick={() => void sourceAction(source, 'resume')}>Resume</button>}{source.status !== 'revoked' && <button className="text-button" onClick={() => void sourceAction(source, 'revoke')}>Revoke</button>}<button className="text-button" disabled={source.status === 'revoked' || source.status === 'deleting'} onClick={() => void setCloudConsent(source, !source.cloud_consent_at)}>{source.cloud_consent_at ? 'Turn off cloud extraction' : 'Allow cloud extraction'}</button><button className="text-button danger-text" onClick={() => void sourceAction(source, 'delete')}>Delete data</button></div></div>)}{sources.length === 0 && <p className="muted">No sources yet.</p>}</div></section>}
    </main></div>
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const pad2 = (value: number) => String(value).padStart(2, '0')

function ReviewSchedulePanel({ schedule, timezone, consentEnabled, onSave, readyReview, onOpenReview }: { schedule: ReviewSchedule; timezone: string; consentEnabled: boolean; onSave: (payload: SchedulePayload) => void; readyReview?: Review; onOpenReview: (review: Review) => void }) {
  const [enabled, setEnabled] = useState(schedule.enabled)
  const [weekday, setWeekday] = useState(schedule.weekday)
  const [time, setTime] = useState(pad2(schedule.local_hour) + ':' + pad2(schedule.local_minute))
  const [external, setExternal] = useState(schedule.use_external_model)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const [hour, minute] = time.split(':').map(Number)
    onSave({ enabled, weekday, local_hour: hour, local_minute: minute, timezone, use_external_model: external })
  }

  return <section className="panel schedule-panel">
    <div className="panel-heading"><div><p className="eyebrow">AUTOMATIC REVIEW</p><h2>Weekly review schedule</h2></div>{schedule.next_run_at && <span className="count-pill">Next {new Date(schedule.next_run_at).toLocaleString()}</span>}</div>
    <p className="muted">Generate a draft in your timezone while the local API worker is running. External AI still requires consent and budget.</p>
    <form className="schedule-form" onSubmit={submit}>
      <label className="check-row"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>Enable automatic weekly review</span></label>
      <label>Day<select value={weekday} onChange={(event) => setWeekday(Number(event.target.value))}>{WEEKDAYS.map((label, index) => <option value={index} key={label}>{label}</option>)}</select></label>
      <label>Time<input type="time" value={time} onChange={(event) => setTime(event.target.value)} required /></label>
      <label className="check-row"><input type="checkbox" checked={external} onChange={(event) => setExternal(event.target.checked)} /><span>Use external AI when available</span></label>
      <div className="button-row"><button className="secondary" type="submit">Save schedule</button></div>
    </form>
    {schedule.last_run_at && <p className="small-note">Last scheduled run: {new Date(schedule.last_run_at).toLocaleString()}</p>}
    {external && !consentEnabled && <p className="small-note">External AI is off; scheduled reviews will use the template until consent is enabled.</p>}
    {readyReview && <p className="notice success">A scheduled weekly review is ready. <button className="text-button" type="button" onClick={() => onOpenReview(readyReview)}>Open review</button></p>}
  </section>
}

function DueRemindersPanel({ reminders, onAction }: { reminders: Reminder[]; onAction: (reminder: Reminder, status: string) => void }) {
  return <section className="panel due-reminders">
    <div className="panel-heading"><div><p className="eyebrow">DUE NOW</p><h2>Follow-ups need attention</h2></div><span className="count-pill">{reminders.length}</span></div>
    {reminders.map((reminder) => <div className="reminder-row" key={reminder.id}><div><strong>{reminder.title}</strong><small>{reminder.due_at ? new Date(reminder.due_at).toLocaleString() : 'No due date'} · {reminder.status}</small></div><div className="button-row"><button className="text-button" onClick={() => onAction(reminder, 'completed')}>Complete</button><button className="text-button" onClick={() => onAction(reminder, 'snoozed')}>Snooze</button></div></div>)}
  </section>
}

function ReviewCard({ review, onSave, onOpenSource, onExport, onCreateReminder, onUpdateSuggestion }: { review: Review; onSave: (review: Review, text: string) => void; onOpenSource: (item: Item) => void; onExport: (review: Review) => void; onCreateReminder: (suggestion: ReviewSuggestion) => void; onUpdateSuggestion: (review: Review, index: number, patch: { text?: string; status?: 'pending' | 'dismissed' }) => void }) {
  const [text, setText] = useState(review.final_text || '')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [suggestionDraft, setSuggestionDraft] = useState('')
  const processing = review.status === 'processing'
  const suggestions = review.draft?.suggestions || []
  const pendingSuggestions = suggestions.map((suggestion, index) => ({ suggestion, index })).filter(({ suggestion }) => suggestion.status !== 'dismissed')
  const dismissedSuggestions = suggestions.map((suggestion, index) => ({ suggestion, index })).filter(({ suggestion }) => suggestion.status === 'dismissed')
  const suggestionEditable = review.status === 'draft'
  const evidence = (suggestion: ReviewSuggestion) => review.source_items.filter((item) => suggestion.source_ids.includes(item.id)).map((item) => item.title).join(', ') || 'Source details unavailable'
  return <article className="panel review-card" id={'review-' + review.id}>
    <div className="panel-heading"><div><p className="eyebrow">{review.status.toUpperCase()}</p><h2>{new Date(review.period_start).toLocaleDateString()} — {new Date(review.period_end).toLocaleDateString()}</h2></div><div className="button-row"><button className="secondary" onClick={() => onExport(review)} disabled={processing || review.status === 'invalidated'}>Export Markdown</button><button className="primary" onClick={() => onSave(review, text)} disabled={processing || review.status === 'invalidated'}>Confirm & save</button></div></div>
    {processing && <p className="notice">The external model is processing. This local template will remain available if the provider fails.</p>}
    {review.draft?.model?.provider && review.draft.model.provider !== 'template' && <p className="small-note">{review.draft.model.status === 'ready'
      ? 'AI draft · ' + (review.draft.model.model || 'model') + ' · ' + (review.draft.model.latency_ms ?? 0) + ' ms · $' + (review.draft.model.estimated_cost_usd || '0')
      : 'Template draft · external model ' + (review.draft.model.status || 'unavailable')}</p>}
    {review.status === 'invalidated' && <p className="notice error">A source was deleted. Regenerate this review to restore its evidence.</p>}
    {suggestions.length > 0 ? <div className="review-suggestions"><p className="eyebrow">SUGGESTED ACTIONS</p>
      {pendingSuggestions.map(({ suggestion, index }) => <div className="suggestion-row" key={index}>
        <div>
          {editingIndex === index
            ? <input aria-label="Suggestion text" value={suggestionDraft} onChange={(event) => setSuggestionDraft(event.target.value)} />
            : <strong>{suggestion.text}</strong>}
          <small>Evidence: {evidence(suggestion)}</small>
        </div>
        <div className="button-row">
          {editingIndex === index ? <>
            <button className="secondary" disabled={!suggestionDraft.trim()} onClick={() => { onUpdateSuggestion(review, index, { text: suggestionDraft.trim() }); setEditingIndex(null) }}>Save suggestion</button>
            <button className="text-button" onClick={() => setEditingIndex(null)}>Cancel</button>
          </> : <>
            <button className="text-button" disabled={!suggestionEditable} onClick={() => { setEditingIndex(index); setSuggestionDraft(suggestion.text) }}>Edit</button>
            <button className="text-button" disabled={!suggestionEditable} onClick={() => onUpdateSuggestion(review, index, { status: 'dismissed' })}>Dismiss</button>
            <button className="secondary" disabled={processing || review.status === 'invalidated'} onClick={() => onCreateReminder(suggestion)}>Create reminder</button>
          </>}
        </div>
      </div>)}
      {pendingSuggestions.length === 0 && <p className="muted">No open suggestions.</p>}
      {dismissedSuggestions.length > 0 && <details className="dismissed-suggestions"><summary>Dismissed suggestions ({dismissedSuggestions.length})</summary>
        {dismissedSuggestions.map(({ suggestion, index }) => <div className="suggestion-row" key={index}>
          <div><strong>{suggestion.text}</strong><small>Evidence: {evidence(suggestion)}</small></div>
          <button className="text-button" disabled={!suggestionEditable} onClick={() => onUpdateSuggestion(review, index, { status: 'pending' })}>Restore</button>
        </div>)}
      </details>}
    </div> : null}
    <textarea value={text} onChange={(event) => setText(event.target.value || '')} placeholder="Edit your review. Use the source list below to verify facts." rows={9} disabled={processing || review.status === 'invalidated'} /><details><summary>Evidence ({review.source_items.length})</summary>{review.source_items.map((item) => <p className="evidence" key={item.id}><strong>{item.title}</strong><span>{item.content_text.slice(0, 180)}</span><button className="text-button" onClick={() => onOpenSource(item)}>Open source in timeline ↗</button></p>)}</details>
  </article>
}

function PhotoImage({ itemId, token }: { itemId: string; token: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let objectUrl = ''
    let active = true
    void fetch(API + '/items/' + itemId + '/raw', { headers: { Authorization: 'Bearer ' + token } }).then((response) => response.ok ? response.blob() : null).then((blob) => {
      if (blob && active) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }
    }).catch(() => undefined)
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [itemId, token])
  return url ? <img className="timeline-photo" src={url} alt="Imported photo" /> : null
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

function GraphPanel({ token, onError, onNotice, onPendingChange }: { token: string; onError: (message: string) => void; onNotice: (message: string) => void; onPendingChange: (total: number) => void }) {
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
    <section className="panel">
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
    </section>

    <section className="graph-grid">
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
            {entity.evidence.map((evidence) => <p className="evidence" key={evidence.id}>{evidence.quote}<small>{evidence.availability}</small></p>)}
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
    </section>
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
      const response = await fetch(API + '/qa/threads/' + threadId + '/export?format=' + format, { headers: { Authorization: 'Bearer ' + token } })
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
