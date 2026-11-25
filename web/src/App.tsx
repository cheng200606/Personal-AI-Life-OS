import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type Source = { id: string; kind: string; name: string; status: string; selected_scope: Record<string, unknown>; last_sync_at: string | null }
type Item = { id: string; source_id: string; kind: string; title: string; content_text: string; occurred_at: string | null; source_locator: Record<string, unknown>; metadata: Record<string, unknown> }
type Job = { id: string; kind: string; status: string; attempt_count: number; max_attempts: number; error_code: string | null; result_json: Record<string, unknown> | null }
type ReviewSuggestion = { text: string; source_ids: string[] }
type Review = { id: string; period_start: string; period_end: string; status: string; final_text: string | null; draft: { suggestions?: ReviewSuggestion[]; model?: { job_id?: string; status?: string } }; source_items: Item[] }
type Reminder = { id: string; title: string; notes: string | null; due_at: string | null; status: string }
type User = { id: string; email: string; timezone: string; ai_consent_at: string | null }
type Conversation = { id: string; title: string; created_at: number | null }
type Page = 'timeline' | 'reviews' | 'account'
type Disclosure = { available: boolean; provider: string | null; model: string | null; disclosure_version: string | null; data_sent: string; retention: string; privacy_url: string | null; input_cost_per_million_usd: string | null; output_cost_per_million_usd: string | null; max_cost_per_call_usd: string | null }

const API = (import.meta.env.VITE_API_BASE_URL || '') + '/api/v1'

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
  if (source.kind === 'photo') {
    const count = typeof source.selected_scope.file_count === 'number' ? source.selected_scope.file_count : 1
    return `${count} selected photo(s) · image pixels, optional capture time, and searchable OCR text; location metadata is stripped`
  }
  return `Selected Markdown file · UTF-8 section text, headings, dates, and line locations (${source.name})`
}

function selectedFileDisclosure(file: File, selectedConversationCount: number): string {
  if (file.type.startsWith('image/')) {
    return 'This selected photo will be uploaded for re-encoding and OCR. EXIF and location metadata are removed from the stored copy. External description is a separate, optional action.'
  }
  if (file.name.toLowerCase().endsWith('.json')) {
    return `Only the ${selectedConversationCount} selected conversations will be uploaded. Their user/assistant text, message IDs, and available timestamps are processed; other conversations stay on this device.`
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
  const [query, setQuery] = useState('')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
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
      const [me, sourceList, timeline, reviewList, reminderList, modelDisclosure] = await Promise.all([
        api<User>('/auth/me', token), api<Source[]>('/sources', token), api<{ items: Item[]; total: number; next_cursor: string | null }>('/timeline?' + params.toString(), token),
        api<Review[]>('/reviews', token), api<Reminder[]>('/reminders', token), fetch(API + '/auth/model-disclosure').then((response) => response.json() as Promise<Disclosure>),
      ])
      if (activeToken.current !== token) return
      setUser(me); setSources(sourceList); setItems(timeline.items); setTimelineTotal(timeline.total); setTimelineCursor(timeline.next_cursor); setReviews(reviewList); setReminders(reminderList); setDisclosure(modelDisclosure)
    } catch (e) { if (activeToken.current === token) setError(e instanceof Error ? e.message : 'Could not load your workspace.') }
  }, [dateEnd, dateStart, query, sourceFilter, token])

  // This effect loads remote account state whenever its filters or token change.
  // eslint-disable-next-line react/set-state-in-effect
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { activeToken.current = token }, [token])
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
    if (!fromDirectory && selectedFiles.length === 1 && imageFiles.length === 0 && !/\.(md|markdown|json)$/i.test(selectedFiles[0].name)) {
      setError('Choose a UTF-8 Markdown file, ChatGPT conversations.json, or a supported JPEG, PNG, or WebP photo.')
      return
    }
    if (nextFiles.length > 10) { setError('Select at most 10 photos per import.'); return }
    if (nextFiles.length > 1 && (imageFiles.length !== nextFiles.length || !fromDirectory && selectedFiles.some((selectedFile) => !/\.(jpe?g|png|webp)$/i.test(selectedFile.name)))) {
      setError('Select one Markdown or ChatGPT file, or choose only supported photo files.'); return
    }
    if (fromDirectory && nextFiles.length === 0) { setError('The selected folder contains no supported JPEG, PNG, or WebP photos.'); return }
    const next = nextFiles[0] || null
    setFile(next); setPhotoFiles(nextFiles.length && nextFiles.every((selectedFile) => /\.(jpe?g|png|webp)$/i.test(selectedFile.name)) ? nextFiles : [])
    setPhotoPreview(next && /\.(jpe?g|png|webp)$/i.test(next.name) ? URL.createObjectURL(next) : '')
    if (fromDirectory && skipped) setNotice(`${skipped} non-photo file(s) in the folder were ignored.`)
    if (nextFiles.length === 1 && next?.name.toLowerCase().endsWith('.json')) {
      try { setConversations(parseConversations(await next.text())) } catch (e) { setError(e instanceof Error ? e.message : 'Could not preview this file.') }
    }
  }

  async function importSelected(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return
    const kind = photoFiles.length ? 'photo' : file.name.toLowerCase().endsWith('.json') ? 'chatgpt_export' : 'memory_markdown'
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
    if (!window.confirm('Deleting this item will remove its source and every selected file and timeline item attached to that source. Continue?')) return
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

  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark small">L</span><span>Life OS</span></div><nav aria-label="Main navigation"><button className={page === 'timeline' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('timeline')}>◷ <span>Timeline</span></button><button className={page === 'reviews' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('reviews')}>✳ <span>Weekly review</span></button><button className={page === 'account' ? 'nav-link active' : 'nav-link'} onClick={() => setPage('account')}>⚙ <span>Account & sources</span></button></nav><div className="sidebar-foot"><span className="avatar">{user?.email.slice(0, 1).toUpperCase()}</span><span className="user-email">{user?.email}</span><button className="icon-button" title="Sign out" onClick={() => { sessionStorage.removeItem('lifeos-token'); activeToken.current = ''; setToken(''); setUser(null) }}>↗</button></div></aside>
    <main className="main"><header className="topbar"><div><p className="eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</p><h1>{page === 'timeline' ? 'Timeline' : page === 'reviews' ? 'Weekly review' : 'Account & sources'}</h1></div><span className="privacy-pill"><span className="live-dot" /> Private workspace</span></header>
      {error && <div className="notice error" role="alert">{error}<button className="icon-button" onClick={() => setError('')}>×</button></div>}
      {notice && <div className="notice success" role="status">{notice}<button className="icon-button" onClick={() => setNotice('')}>×</button></div>}
      {page === 'timeline' && <><section className="hero-panel"><div><p className="eyebrow">CAPTURE WHAT MATTERS</p><h2>Make your context useful.</h2><p className="muted">Import selected notes, conversations, or photos. Your timeline keeps every detail connected to its source.</p></div><div className="stat"><strong>{timelineTotal}</strong><span>timeline items</span></div></section>
        <section className="panel import-panel"><div className="panel-heading"><div><p className="eyebrow">ADD A SOURCE</p><h2>Import selected material</h2></div><span className="limit-pill">Up to 5 MB text · 20 MB photo</span></div><form onSubmit={importSelected} className="import-form"><label className="file-drop"><span className="upload-icon">↑</span><span><strong>{file ? file.name : 'Choose a file'}</strong><small>Markdown, ChatGPT conversations.json, JPEG, PNG, or WebP</small></span><input type="file" accept=".md,.markdown,.json,image/jpeg,image/png,image/webp" multiple onChange={(event) => void previewFiles(event.target.files)} /></label><label className="folder-picker">Choose a photo folder<input ref={directoryInput} type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => void previewFiles(event.target.files, true)} /></label>{conversations.length > 0 && <div className="selection-box"><div className="selection-head"><strong>Select conversations to import</strong><button type="button" className="text-button" onClick={() => setSelected(selected.length === conversations.length ? [] : conversations.map((entry) => entry.id))}>{selected.length === conversations.length ? 'Clear selection' : 'Select all'}</button></div><div className="conversation-list">{conversations.map((entry) => <label className="conversation" key={entry.id}><input type="checkbox" checked={selected.includes(entry.id)} onChange={(event) => setSelected(event.target.checked ? [...selected, entry.id] : selected.filter((value) => value !== entry.id))} /><span>{entry.title}<small>{entry.created_at ? new Date(entry.created_at * 1000).toLocaleDateString() : 'Date unknown'}</small></span></label>)}</div><p className="small-note">Unselected conversations stay on this device and are not uploaded.</p></div>}{photoFiles.length > 0 && <><p className="small-note">{photoFiles.length} photo(s) selected. Each photo is uploaded separately; folder paths and unsupported files are not sent.</p>{photoFiles.length === 1 && <div className="local-photo-preview"><img src={photoPreview} alt="Selected photo preview" /><p className="small-note">The saved photo is re-encoded to remove EXIF location and other metadata. OCR text is searchable.</p></div>}{photoFiles.length === 1 && <label className="inline-field">Photo date (optional)<input type="datetime-local" value={photoDate} onChange={(event) => setPhotoDate(event.target.value)} /></label>}</>}<div className="import-actions"><p className="small-note">Files are processed only after you submit this selection.</p>{photoFiles.length > 1 ? <p className="selection-disclosure"><strong>{photoFiles.length} photos · {photoFiles.reduce((total, selectedFile) => total + selectedFile.size, 0).toLocaleString()} bytes.</strong> Selected photos will be sanitized and processed; EXIF/GPS metadata is removed.</p> : file && <p className="selection-disclosure"><strong>{file.name} · {file.size.toLocaleString()} bytes.</strong> {selectedFileDisclosure(file, selected.length)}</p>}<button className="primary" disabled={busy || !file}>{busy ? 'Importing…' : 'Import selected'}</button></div></form></section>
        <section className="timeline-layout"><div className="panel timeline-panel"><div className="panel-heading"><div><p className="eyebrow">YOUR RECORD</p><h2>Recent activity</h2></div><span className="count-pill">{visibleItems.length} / {timelineTotal}</span></div><label className="search"><span>⌕</span><input aria-label="Search timeline" placeholder="Search notes and conversations" value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label><div className="filter-row"><label>From<input type="date" value={dateStart} onChange={(event) => setDateStart(event.target.value)} /></label><label>Until<input type="date" value={dateEnd} onChange={(event) => setDateEnd(event.target.value)} /></label><label>Source<select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">All sources</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label></div><div className="timeline-list">{visibleItems.map((item) => { const source = sources.find((entry) => entry.id === item.source_id); return <article className="timeline-item" id={'timeline-item-' + item.id} key={item.id}><span className="timeline-marker">{item.kind === 'chat_message' ? '✳' : item.kind === 'photo' ? '▧' : '▤'}</span><div className="item-content"><div className="item-meta"><span>{item.occurred_at ? new Date(item.occurred_at).toLocaleString() : 'Date unknown'}</span><span className="dot-separator">·</span><span>{source?.name || 'Imported source'}</span></div><h3>{item.title}</h3>{item.kind === 'photo' && Boolean(item.metadata.ocr_status) && <div className="photo-ocr-state"><span>OCR: {String(item.metadata.ocr_status).replace('_', ' ')}</span>{['failed', 'cancelled'].includes(String(item.metadata.ocr_status)) && <button className="text-button" onClick={() => void retryPhotoOcr(item)}>Retry OCR</button>}</div>}{item.kind === 'photo' && <><PhotoImage itemId={item.id} token={token} />{disclosure?.available && <div className="photo-description"><button className="text-button" disabled={!user?.ai_consent_at || ['queued', 'running'].includes(String(item.metadata.description_status))} onClick={() => void describePhoto(item)}>{['queued', 'running'].includes(String(item.metadata.description_status)) ? 'Generating…' : photoDescriptions[item.id] || item.metadata.description_status === 'confirmed' ? 'Generate another draft' : item.metadata.description_status === 'draft' ? 'Review saved draft' : ['failed', 'cancelled'].includes(String(item.metadata.description_status)) ? 'Retry description' : 'Describe with AI'}</button><span className="small-note">Sends this sanitized photo to {disclosure.provider} after consent.</span>{photoDescriptions[item.id] && <><textarea value={photoDescriptions[item.id]} onChange={(event) => setPhotoDescriptions((current) => ({ ...current, [item.id]: event.target.value }))} rows={3} aria-label="Photo description draft" /><button className="secondary" onClick={() => void confirmPhotoDescription(item)}>Add description to timeline</button></>}</div>}</>}<p>{item.content_text.slice(0, 360)}{item.content_text.length > 360 ? '…' : ''}</p><div className="item-actions"><span className="source-tag">{String(item.source_locator.role || item.kind)}</span><button className="text-button" onClick={() => void exportItem(item)}>Export Markdown ↗</button><button className="text-button" onClick={() => void downloadSource(item)}>Download source ↗</button><button className="text-button danger-text" onClick={() => void deleteItem(item)}>Delete imported source</button></div></div></article> })}{visibleItems.length === 0 && <div className="empty-state"><span>◷</span><strong>Your timeline is ready</strong><p>Import a selected Markdown note or ChatGPT conversation to see it here.</p></div>}</div>{timelineCursor && <button className="secondary full" onClick={() => void loadMoreTimeline()}>Load more timeline items</button>}</div><aside className="panel source-rail"><div className="panel-heading"><div><p className="eyebrow">CONNECTED SOURCES</p><h2>Sources</h2></div><span className="count-pill">{sources.length}</span></div>{sources.length === 0 && <p className="muted">Your selected sources will appear here.</p>}{sources.slice(0, 5).map((source) => <div className="source-row" key={source.id}><span className="source-icon">{source.kind === 'photo' ? '▧' : source.kind === 'chatgpt_export' ? '✳' : '▤'}</span><div><strong>{source.name}</strong><small>{source.status.replace('_', ' ')}</small></div><span className={source.status === 'active' ? 'status-dot' : 'status-dot paused'} /></div>)}<button className="secondary full" onClick={() => setPage('account')}>Manage sources</button></aside></section></>}
      {page === 'reviews' && <section className="review-grid"><div className="panel"><div className="panel-heading"><div><p className="eyebrow">A MOMENT TO REFLECT</p><h2>Start a weekly review</h2></div></div><p className="muted">Build an editable draft from this period’s timeline. Every generated fact links back to its source.</p><form className="review-form" onSubmit={generateReview}><label>From<input name="start" type="date" required /></label><label>Until <small>(exclusive)</small><input name="end" type="date" required /></label><label className="check-row"><input type="checkbox" checked={externalModel} disabled={!disclosure?.available || !user?.ai_consent_at} onChange={(event) => setExternalModel(event.target.checked)} /><span>Use external AI model<br /><small>Enable current provider consent in Account first.</small></span></label><button className="primary" disabled={busy}>{busy ? 'Preparing…' : 'Generate draft'}</button></form><div className="subsection"><div className="panel-heading"><h2>Reminders</h2></div><form className="reminder-form" onSubmit={createReminder}><input name="title" placeholder="What should you follow up on?" required /><input name="due_at" type="datetime-local" aria-label="Reminder due date" /><button className="secondary">Add reminder</button></form>{reminders.map((reminder) => <div className="reminder-row" key={reminder.id}><div><strong>{reminder.title}</strong><small>{reminder.due_at ? new Date(reminder.due_at).toLocaleString() : 'No due date'} · {reminder.status}</small></div>{reminder.status !== 'completed' && reminder.status !== 'cancelled' && <><button className="text-button" onClick={() => void updateReminder(reminder, 'completed')}>Complete</button><button className="text-button" onClick={() => void updateReminder(reminder, 'snoozed')}>Snooze</button><button className="text-button" onClick={() => void updateReminder(reminder, 'cancelled')}>Dismiss</button></>}</div>)}</div></div><div className="review-list">{reviews.map((review) => <ReviewCard key={review.id + (review.final_text || "")} review={review} onSave={saveReview} onOpenSource={openSource} onExport={downloadReview} onCreateReminder={createReminderFromSuggestion} />)}{reviews.length === 0 && <div className="panel empty-state"><span>✳</span><strong>Your reviews will appear here</strong><p>Choose a date range to make a draft from sourced timeline items.</p></div>}</div></section>}
      {page === 'account' && <section className="account-grid"><div className="panel"><p className="eyebrow">PROFILE</p><h2>{user?.email}</h2><p className="muted">Timezone: {user?.timezone}</p><div className="subsection"><p className="eyebrow">MODEL DATA CONSENT</p>{disclosure?.available ? <><p className="muted">Provider: {disclosure.provider} · Model: {disclosure.model}</p><p className="muted">Data sent: {disclosure.data_sent}</p><p className="muted">Retention: {disclosure.retention}</p><p className="muted">Configured estimate: ${disclosure.input_cost_per_million_usd} per million input tokens and ${disclosure.output_cost_per_million_usd} per million output tokens. Per-call budget check: ${disclosure.max_cost_per_call_usd}. A call that fails or exceeds the estimate may still incur provider charges.</p>{disclosure.privacy_url && <p><a href={disclosure.privacy_url} target="_blank" rel="noreferrer">Provider privacy terms ↗</a></p>}<label className="check-row consent-check"><input type="checkbox" checked={consentAcknowledged} onChange={(event) => setConsentAcknowledged(event.target.checked)} /><span>I have reviewed the provider and data handling disclosure above.</span></label><p className="small-note">Current consent: {user?.ai_consent_at ? 'Enabled' : 'Off'}</p><div className="button-row"><button className="primary" disabled={!consentAcknowledged || Boolean(user?.ai_consent_at)} onClick={() => void setModelConsent(true)}>Enable external AI</button><button className="secondary" disabled={!user?.ai_consent_at} onClick={() => void setModelConsent(false)}>Turn off</button></div></> : <p className="muted">No external model is configured. Template-based reviews remain available, and no review data is sent to a model provider.</p>}</div><div className="subsection"><p className="eyebrow">YOUR DATA</p><p className="muted">Download a portable archive or permanently delete your account and stored records.</p><div className="button-row"><button className="secondary" onClick={() => void downloadAccountArchive()}>Download archive</button><button className="danger" onClick={() => void deleteAccount()}>Delete account</button></div></div></div><div className="panel"><div className="panel-heading"><div><p className="eyebrow">YOUR SELECTIONS</p><h2>Manage sources</h2></div></div>{sources.map((source) => <div className="manage-source" key={source.id}><div><strong>{source.name}</strong><small>{source.kind.replace('_', ' ')} · {source.status}</small><p className="source-scope">{sourceScopeDescription(source)}</p><small>Last import: {source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : 'Never'}</small></div><div className="button-row">{source.status === 'active' && <button className="text-button" onClick={() => void sourceAction(source, 'pause')}>Pause</button>}{source.status === 'paused' && <button className="text-button" onClick={() => void sourceAction(source, 'resume')}>Resume</button>}{source.status !== 'revoked' && <button className="text-button" onClick={() => void sourceAction(source, 'revoke')}>Revoke</button>}<button className="text-button danger-text" onClick={() => void sourceAction(source, 'delete')}>Delete data</button></div></div>)}{sources.length === 0 && <p className="muted">No sources yet.</p>}</div></section>}
    </main></div>
}

function ReviewCard({ review, onSave, onOpenSource, onExport, onCreateReminder }: { review: Review; onSave: (review: Review, text: string) => void; onOpenSource: (item: Item) => void; onExport: (review: Review) => void; onCreateReminder: (suggestion: ReviewSuggestion) => void }) {
  const [text, setText] = useState(review.final_text || '')
  const processing = review.status === 'processing'
  return <article className="panel review-card">
    <div className="panel-heading"><div><p className="eyebrow">{review.status.toUpperCase()}</p><h2>{new Date(review.period_start).toLocaleDateString()} — {new Date(review.period_end).toLocaleDateString()}</h2></div><div className="button-row"><button className="secondary" onClick={() => onExport(review)} disabled={processing || review.status === 'invalidated'}>Export Markdown</button><button className="primary" onClick={() => onSave(review, text)} disabled={processing || review.status === 'invalidated'}>Confirm & save</button></div></div>
    {processing && <p className="notice">The external model is processing. This local template will remain available if the provider fails.</p>}
    {review.status === 'invalidated' && <p className="notice error">A source was deleted. Regenerate this review to restore its evidence.</p>}
    {review.draft?.suggestions?.length ? <div className="review-suggestions"><p className="eyebrow">SUGGESTED ACTIONS</p>{review.draft.suggestions.map((suggestion, index) => <div className="suggestion-row" key={index}><div><strong>{suggestion.text}</strong><small>Evidence: {review.source_items.filter((item) => suggestion.source_ids.includes(item.id)).map((item) => item.title).join(', ') || 'Source details unavailable'}</small></div><button className="secondary" disabled={processing || review.status === 'invalidated'} onClick={() => onCreateReminder(suggestion)}>Create reminder</button></div>)}</div> : null}
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

export default App
