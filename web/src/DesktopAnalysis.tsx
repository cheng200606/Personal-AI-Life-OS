import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { desktopRequest } from './desktopRuntime'

type Settings = {
  base_url: string
  model: string
  input_cost_per_million_usd: string
  output_cost_per_million_usd: string
  monthly_budget_usd: string
  max_cost_per_call_usd: string
  privacy_url: string
  retention: string
  key_configured: boolean
}
type Provider = { disclosure_version: string; consent: { consented: boolean }; available: boolean }
const EMPTY_SETTINGS: Settings = {
  base_url: '', model: '', input_cost_per_million_usd: '', output_cost_per_million_usd: '',
  monthly_budget_usd: '5.00', max_cost_per_call_usd: '0.10', privacy_url: '', retention: '', key_configured: false,
}

export function DesktopProviderSettings({ token, onChange }: { token: string; onChange: () => void }) {
  const [settings, setSettings] = useState(EMPTY_SETTINGS)
  const [provider, setProvider] = useState<Provider | undefined>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const load = useCallback(async () => {
    const [stored, providers] = await Promise.all([
      desktopRequest<Partial<Settings>>(token, '/desktop/analysis/provider'),
      desktopRequest<(Provider & { id: string })[]>(token, '/model-providers'),
    ])
    setSettings({ ...EMPTY_SETTINGS, ...stored })
    setProvider(providers.find((entry) => entry.id === 'desktop'))
  }, [token])
  useEffect(() => {
    // The provider and its consent state are loaded from the local service.
    // eslint-disable-next-line react/set-state-in-effect
    void load().catch((reason) => setError(String(reason.message || reason)))
  }, [load])

  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try {
      await action()
      await load()
      onChange()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = Object.fromEntries(new FormData(form))
    if (!values.api_key) delete values.api_key
    void run(async () => {
      await desktopRequest(token, '/desktop/analysis/provider', { method: 'PUT', body: JSON.stringify(values) })
      form.reset()
      setSaved(true)
    })
  }

  function consent(enabled: boolean) {
    if (!provider) return
    if (enabled && !window.confirm('允许此提供方接收你已授权的来源摘录，用于生成分析草稿和所请求的复盘？')) return
    void run(async () => {
      await desktopRequest(token, '/model-providers/consent', {
        method: 'PUT', body: JSON.stringify({
          provider_id: 'desktop', disclosure_version: provider.disclosure_version, enabled,
        }),
      })
    })
  }

  return <section className="panel stack desktop-tool-panel">
    <h2>外部 AI 提供方</h2>
    <p className="muted">配置 OpenAI 兼容接口。允许提供方并授权单个来源后，才会发送该来源的文本摘录。</p>
    <form className="stack" key={settings.base_url + settings.model + String(saved)} onSubmit={save}>
      <label>接口地址<input name="base_url" type="url" placeholder="https://example.com/v1" required defaultValue={settings.base_url} /></label>
      <label>模型<input name="model" maxLength={160} required defaultValue={settings.model} /></label>
      <label>API 密钥<input name="api_key" type="password" autoComplete="new-password"
        placeholder={settings.key_configured ? '已存入 Windows 凭据管理器' : ''} /></label>
      <div className="button-row">
        <label>每百万输入 token（美元）<input name="input_cost_per_million_usd" type="number" min="0.000001" step="any" required defaultValue={settings.input_cost_per_million_usd} /></label>
        <label>每百万输出 token（美元）<input name="output_cost_per_million_usd" type="number" min="0.000001" step="any" required defaultValue={settings.output_cost_per_million_usd} /></label>
      </div>
      <div className="button-row">
        <label>月预算（美元）<input name="monthly_budget_usd" type="number" min="0" step="any" required defaultValue={settings.monthly_budget_usd} /></label>
        <label>单次预算（美元）<input name="max_cost_per_call_usd" type="number" min="0.000001" step="any" required defaultValue={settings.max_cost_per_call_usd} /></label>
      </div>
      <label>隐私说明地址<input name="privacy_url" type="url" required defaultValue={settings.privacy_url} /></label>
      <label>提供方的数据保留说明<textarea name="retention" minLength={20} maxLength={1000} required defaultValue={settings.retention} /></label>
      <div className="button-row"><button className="primary" disabled={busy}>保存配置</button>
        {provider?.available && <button type="button" className="secondary" disabled={busy}
          onClick={() => consent(!provider.consent.consented)}>
          {provider.consent.consented ? '撤回提供方授权' : '授权提供方'}
        </button>}
        {settings.base_url && <button type="button" className="text-button" disabled={busy} onClick={() => {
          if (window.confirm('移除提供方配置和已保存的 API 密钥？')) void run(async () => {
            await desktopRequest(token, '/desktop/analysis/provider', { method: 'DELETE' })
            setSaved(false)
          })
        }}>移除配置</button>}
      </div>
    </form>
    {saved && !error && <p role="status">配置已保存。提供方授权状态为{provider?.consent.consented ? '已启用' : '待授权'}。</p>}
    {error && <p role="alert" className="notice error">{error}</p>}
  </section>
}

type Draft = {
  id: string; kind: 'experience' | 'knowledge' | 'action'; body: string; quote: string
  confidence: number; item_id: string; item_title: string; source_id: string; source_name: string
}
type Job = { id: string; source_name: string; status: string; error_code: string | null; attempt_count: number }
type ConfirmedNote = Omit<Draft, 'quote' | 'confidence'>
const LABEL = { experience: '工作与学习经历', knowledge: '知识与关系', action: '后续行动' }
const JOB_STATUS: Record<string, string> = {
  queued: '排队', running: '分析中', failed: '失败', cancelled: '已取消', completed: '已完成',
}
const JOB_ERROR: Record<string, string> = {
  model_consent_required: '需要提供方授权', source_consent_required: '需要来源授权',
  model_budget_exceeded: '预算不足', model_request_failed: '模型请求失败',
  model_response_invalid: '模型响应格式错误', model_provider_unavailable: '提供方不可用',
  source_unavailable: '来源记录已变更', model_consent_withdrawn: '提供方授权已撤回',
}

export function DesktopDrafts({ token, onOpenItem, onChange }: {
  token: string; onOpenItem: (id: string, sourceId: string) => void; onChange: () => void
}) {
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [confirmed, setConfirmed] = useState<ConfirmedNote[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<Draft[]>([])
  const [edited, setEdited] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    const [pending, tasks, savedNotes] = await Promise.all([
      desktopRequest<Draft[]>(token, '/desktop/analysis/drafts'),
      desktopRequest<Job[]>(token, '/desktop/analysis/jobs'),
      desktopRequest<ConfirmedNote[]>(token, '/desktop/analysis/confirmed'),
    ])
    setDrafts(pending); setJobs(tasks); setConfirmed(savedNotes)
  }, [token])
  useEffect(() => {
    const pull = () => void load().catch((reason) => setError(String(reason.message || reason)))
    pull()
    const timer = window.setInterval(pull, 3000)
    return () => window.clearInterval(timer)
  }, [load])

  async function run(operation: () => Promise<void>) {
    setBusy(true); setError('')
    try {
      await operation()
      await load()
      onChange()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  function decide(ids: string[], decision: 'accepted' | 'rejected') {
    void run(async () => {
      await desktopRequest(token, '/desktop/analysis/drafts/decision', {
        method: 'POST', body: JSON.stringify({ ids, decision }),
      })
      setSelected((current) => current.filter((id) => !ids.includes(id)))
      setPreview([])
    })
  }

  const groups = new Map<string, Draft[]>()
  for (const draft of drafts) {
    const group = groups.get(draft.source_id) || []
    group.push(draft)
    groups.set(draft.source_id, group)
  }
  return <section className="panel stack desktop-tool-panel">
    <div className="panel-heading"><h2>来源分析草稿</h2>
      <button className="secondary" disabled={busy || !selected.length || Boolean(preview.length)}
        onClick={() => setPreview(drafts.filter((draft) => selected.includes(draft.id)))}>预览批量接受</button>
    </div>
    {preview.length > 0 && <section className="subsection stack" aria-label="批量接受预览">
      <h3>确认接受 {preview.length} 条草稿</h3>
      {preview.map((draft) => <div key={draft.id}><strong>{LABEL[draft.kind]} · {draft.source_name}</strong><p>{draft.body}</p></div>)}
      <div className="button-row">
        <button className="primary" disabled={busy} onClick={() => decide(preview.map((draft) => draft.id), 'accepted')}>接受这些草稿</button>
        <button className="secondary" disabled={busy} onClick={() => setPreview([])}>返回审核</button>
      </div>
    </section>}
    {!drafts.length && <p className="muted">没有待审的来源分析草稿。</p>}
    {!preview.length && [...groups.values()].map((group) => <div className="subsection stack" key={group[0].source_id}>
      <h3>{group[0].source_name}</h3>
      {group.map((draft) => <article key={draft.id} className="stack">
        <label className="check-row"><input type="checkbox" checked={selected.includes(draft.id)}
          disabled={busy || edited[draft.id] !== undefined} onChange={(event) => {
            const checked = event.currentTarget.checked
            setSelected((current) => checked ? [...current, draft.id] : current.filter((id) => id !== draft.id))
          }} /><span>{LABEL[draft.kind]} · 置信度 {Math.round(draft.confidence * 100)}%</span></label>
        <label>草稿<textarea value={edited[draft.id] ?? draft.body} maxLength={1000} onChange={(event) => {
          const value = event.currentTarget.value
          setSelected((current) => current.filter((id) => id !== draft.id))
          setEdited((current) => ({ ...current, [draft.id]: value }))
        }} /></label>
        <blockquote>{draft.quote}</blockquote>
        <button className="text-button" onClick={() => onOpenItem(draft.item_id, draft.source_id)}>打开原文 · {draft.item_title}</button>
        <div className="button-row">
          {edited[draft.id] !== undefined && <button className="secondary" disabled={busy || !edited[draft.id].trim()}
            onClick={() => void run(async () => {
              await desktopRequest(token, '/desktop/analysis/drafts/' + draft.id, {
                method: 'PATCH', body: JSON.stringify({ body: edited[draft.id] }),
              })
              setEdited((current) => { const next = { ...current }; delete next[draft.id]; return next })
            })}>保存编辑</button>}
          <button className="primary" disabled={busy || edited[draft.id] !== undefined} onClick={() => decide([draft.id], 'accepted')}>确认</button>
          <button className="secondary" disabled={busy} onClick={() => decide([draft.id], 'rejected')}>拒绝</button>
        </div>
      </article>)}
    </div>)}
    {confirmed.length > 0 && <details><summary>已确认的经历与知识（{confirmed.length}）</summary>
      {confirmed.map((note) => <article className="subsection" key={note.id}>
        <strong>{LABEL[note.kind]} · {note.source_name}</strong><p>{note.body}</p>
        <button className="text-button" onClick={() => onOpenItem(note.item_id, note.source_id)}>打开原文 · {note.item_title}</button>
      </article>)}
    </details>}
    {jobs.length > 0 && <details><summary>最近分析任务（{jobs.length}）</summary>
      {jobs.map((job) => <div className="manage-source" key={job.id}><div><strong>{job.source_name}</strong>
        <small>{JOB_STATUS[job.status] || job.status}{job.error_code ? ' · ' + (JOB_ERROR[job.error_code] || job.error_code) : ''}</small></div>
        {['failed', 'cancelled'].includes(job.status) && <button className="secondary" disabled={busy}
          onClick={() => void run(async () => { await desktopRequest(token, `/jobs/${job.id}/retry`, { method: 'POST' }) })}>重试</button>}
      </div>)}
    </details>}
    {error && <p role="alert" className="notice error">{error}</p>}
  </section>
}
