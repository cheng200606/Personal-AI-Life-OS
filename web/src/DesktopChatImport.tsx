import { invoke } from '@tauri-apps/api/core'
import { useEffect, useState } from 'react'
import { apiFetch, desktopRequest } from './desktopRuntime'

type ChatStatus = {
  id: string
  filename: string
  state: 'previewing' | 'ready' | 'importing' | 'complete' | 'failed' | 'canceled'
  bytes_read: number
  total_bytes: number
  items_created: number
  total_conversations: number
  conversations: { id: string; title: string }[]
  error: string | null
}

const PAGE_SIZE = 100

export function DesktopChatImport({ token, onComplete }: { token: string; onComplete: () => void }) {
  const [id, setId] = useState('')
  const [status, setStatus] = useState<ChatStatus>()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [folders, setFolders] = useState<{ id: string; name: string }[]>([])
  const [folderId, setFolderId] = useState('')
  const running = status?.state === 'importing' || status?.state === 'previewing'

  useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    let timer: number | undefined
    async function poll() {
      try {
        const response = await apiFetch(`/desktop/chats/${id}?offset=${offset}&limit=${PAGE_SIZE}`, {
          headers: { Authorization: 'Bearer ' + token }, signal: controller.signal,
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.error?.message || '无法查询导入进度。')
        if (controller.signal.aborted) return
        setStatus(result)
        if (result.state === 'previewing' || result.state === 'importing') {
          timer = window.setTimeout(() => void poll(), 350)
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
      }
    }
    void poll()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [id, offset, token, busy])

  useEffect(() => {
    if (status?.state === 'complete') onComplete()
  }, [status?.state, onComplete])

  useEffect(() => {
    void desktopRequest<{ id: string; name: string; kind: string; status: string }[]>(token, '/desktop/folders')
      .then((entries) => setFolders(entries.filter((entry) => entry.kind === 'chat_folder' && entry.status === 'active')))
      .catch((reason) => setError(String(reason.message || reason)))
  }, [token])

  async function action(path: string, payload?: unknown) {
    const response = await apiFetch('/desktop/chats/' + path, {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: payload ? JSON.stringify(payload) : undefined,
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error?.message || '无法处理所选导出。')
    return result.id as string
  }

  async function run(operation: () => Promise<void>) {
    setError('')
    setBusy(true)
    try {
      await operation()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  async function choose() {
    const grant = await invoke<{ payload: string; signature: string } | null>('desktop_pick_chat')
    if (!grant) return
    const taskId = await action('preview', grant)
    setSelected(new Set())
    setStatus(undefined)
    setOffset(0)
    setFolderId('')
    setId(taskId)
  }

  return <section className="panel desktop-tool-panel desktop-chat-import" aria-label="聊天导出导入">
    <div className="panel-heading"><div><h2>从聊天导出导入</h2>
      <p className="muted">在本机读取 JSON 或 JSONL 文件，只导入你勾选的会话。</p></div>
      <button className="secondary" disabled={running || busy} onClick={() => void run(choose)}>选择导出文件</button>
    </div>
    {status && <>
      <p><strong>{status.filename}</strong></p>
      {running && <div className="stack">
        <progress aria-label="读取导出文件" value={status.bytes_read} max={status.total_bytes || 1} />
        <p role="status">{status.state === 'previewing' ? '正在读取会话…' : '正在本机导入…'}
          {' '}{Math.round(status.bytes_read / (status.total_bytes || 1) * 100)}%</p>
        <button className="secondary" disabled={busy} onClick={() => void run(async () => { await action(id + '/cancel') })}>取消</button>
      </div>}
      {status.state === 'complete' && <p role="status">已完成，新增 {status.items_created} 条记录。</p>}
      {status.state === 'canceled' && <p role="status">已取消。此前写入的 {status.items_created} 条记录已保留。</p>}
      {status.state === 'failed' && <p role="alert" className="notice error">{status.error}</p>}
      {!running && status.total_conversations > 0 && <>
        <fieldset className="conversation-picker">
          <legend>选择会话（已选 {selected.size} / {status.total_conversations}）</legend>
          {status.conversations.map((row) => <label key={row.id} className="check-row">
            <input type="checkbox" disabled={busy} checked={selected.has(row.id)} onChange={(event) => {
              const checked = event.currentTarget.checked
              setSelected((previous) => {
                const next = new Set(previous)
                if (checked) next.add(row.id)
                else next.delete(row.id)
                return next
              })
            }} />
            <span>{row.title}</span>
          </label>)}
        </fieldset>
        {folders.length > 0 && <label>同步方式<select value={folderId}
          onChange={(event) => setFolderId(event.target.value)}>
          <option value="">仅本次导入</option>
          {folders.map((folder) => <option value={folder.id} key={folder.id}>同步所选会话 · {folder.name}</option>)}
        </select></label>}
        <div className="button-row">
          <button className="secondary" disabled={!offset || busy} onClick={() => setOffset(offset - PAGE_SIZE)}>上一页</button>
          <button className="secondary" disabled={offset + PAGE_SIZE >= status.total_conversations || busy} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button>
          <button className="primary" disabled={!selected.size || busy}
            onClick={() => void run(async () => {
              await action(id + '/import', { conversation_ids: [...selected], folder_id: folderId || null })
            })}>导入所选会话</button>
        </div>
      </>}
      {status.state === 'ready' && !status.total_conversations && <p>文件中没有会话。</p>}
    </>}
    {error && <p role="alert" className="notice error">{error}</p>}
  </section>
}
