import { invoke } from '@tauri-apps/api/core'
import { useCallback, useEffect, useState } from 'react'
import { desktopRequest } from './desktopRuntime'

type FolderKind = 'markdown' | 'obsidian' | 'chat_folder'
type Folder = {
  id: string
  name: string
  path: string
  kind: FolderKind
  status: 'paused' | 'active'
  scan_status: string
  last_scan_at: string | null
}
type MissingFile = { id: string; path: string; source: string }
const STATUS: Record<string, string> = {
  waiting: '等待同步', up_to_date: '已同步', partial: '部分文件未同步', unavailable: '目录暂不可用',
}

export function DesktopFolders({ token, onChange }: { token: string; onChange: () => void }) {
  const [folders, setFolders] = useState<Folder[]>([])
  const [kind, setKind] = useState<FolderKind>('markdown')
  const [autostart, setAutostart] = useState<boolean>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => setFolders(await desktopRequest<Folder[]>(token, '/desktop/folders')), [token])

  useEffect(() => {
    const fetchFolders = () => void load().catch((reason) => setError(String(reason.message || reason)))
    fetchFolders()
    const timer = window.setInterval(fetchFolders, 3000)
    void invoke<boolean>('desktop_autostart').then(setAutostart).catch((reason) => setError(String(reason)))
    return () => window.clearInterval(timer)
  }, [load])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError('')
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

  return <section className="panel stack desktop-tool-panel">
    <div className="panel-heading"><h2>后台同步</h2></div>
    <p className="muted">关闭窗口后，托盘中的 Life OS 仍会同步授权目录。</p>
    <label className="check-row"><input type="checkbox" checked={autostart || false}
      disabled={busy || autostart === undefined} onChange={(event) => {
        const enabled = event.currentTarget.checked
        void run(async () => setAutostart(await invoke<boolean>('desktop_autostart', { enabled })))
      }} /><span>登录 Windows 时在托盘启动</span></label>
    <div className="button-row">
      <select aria-label="来源类型" value={kind} onChange={(event) => setKind(event.target.value as FolderKind)}>
        <option value="markdown">Markdown 记录</option>
        <option value="obsidian">Obsidian Vault</option>
        <option value="chat_folder">聊天导出目录</option>
      </select>
      <button className="secondary" disabled={busy} onClick={() => void run(async () => {
        const grant = await invoke('desktop_pick_folder', { purpose: kind })
        if (grant) await desktopRequest(token, '/desktop/folders', { method: 'POST', body: JSON.stringify({ kind, grant }) })
      })}>授权文件夹</button>
    </div>
    {folders.map((folder) => <div className="manage-source" key={folder.id}>
      <div><strong>{folder.name}</strong><small className="source-scope">{folder.path}</small>
        <small>{folder.status === 'paused' ? '已暂停' : STATUS[folder.scan_status] || folder.scan_status}
          {folder.last_scan_at && ' · ' + new Date(folder.last_scan_at).toLocaleString()}</small></div>
      <div className="button-row">
        <button className="text-button" disabled={busy} onClick={() => void run(async () => {
          await desktopRequest(token, `/sources/${folder.id}/status`, {
            method: 'PATCH', body: JSON.stringify({ status: folder.status === 'paused' ? 'active' : 'paused' }),
          })
        })}>{folder.status === 'paused' ? '恢复' : '暂停'}</button>
        <button className="text-button" disabled={busy} onClick={() => {
          if (!window.confirm(`撤回「${folder.name}」的目录授权？`)) return
          void run(async () => { await desktopRequest(token, `/sources/${folder.id}/revoke`, { method: 'POST' }) })
        }}>撤回</button>
      </div>
    </div>)}
    {!folders.length && <p className="muted">暂无授权目录。</p>}
    {error && <p role="alert" className="notice error">{error}</p>}
  </section>
}

export function DesktopMissingFiles({ token, onChange }: { token: string; onChange: () => void }) {
  const [files, setFiles] = useState<MissingFile[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => setFiles(
    await desktopRequest<MissingFile[]>(token, '/desktop/folders/missing'),
  ), [token])

  useEffect(() => {
    const fetchFiles = () => void load().catch((reason) => setError(String(reason.message || reason)))
    fetchFiles()
    const timer = window.setInterval(fetchFiles, 3000)
    return () => window.clearInterval(timer)
  }, [load])

  if (!files.length && !error) return null
  return <section className="panel stack desktop-tool-panel">
    <h2>待确认删除</h2>
    <p className="muted">这些文件已从同步目录移除，其记录已暂停检索和分析。</p>
    {files.map((file) => <div className="manage-source" key={file.id}>
      <div><strong>{file.path}</strong><small>{file.source}</small></div>
      <button className="danger" disabled={busy} onClick={() => {
        if (!window.confirm(`从 Life OS 删除「${file.path}」的记录？`)) return
        setBusy(true)
        void desktopRequest(token, `/desktop/folders/missing/${file.id}`, { method: 'DELETE' })
          .then(load).then(onChange).catch((reason) => setError(String(reason.message || reason)))
          .finally(() => setBusy(false))
      }}>确认删除记录</button>
    </div>)}
    {error && <p role="alert" className="notice error">{error}</p>}
  </section>
}
