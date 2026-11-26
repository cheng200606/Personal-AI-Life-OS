import { invoke } from '@tauri-apps/api/core'
import { useCallback, useEffect, useState } from 'react'
import { desktopRequest } from './desktopRuntime'

type Backup = { path: string | null; latest: string | null; available: boolean; error: string | null }

export function DesktopData({ token, onRestore }: { token: string; onRestore: () => Promise<void> }) {
  const [backup, setBackup] = useState<Backup>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const load = useCallback(async () => setBackup(
    await desktopRequest<Backup>(token, '/desktop/data/backup'),
  ), [token])
  useEffect(() => {
    // This loads the persisted backup settings from the local service.
    // eslint-disable-next-line react/set-state-in-effect
    void load().catch((reason) => setError(String(reason.message || reason)))
  }, [load])

  async function run(action: () => Promise<void>, reload = true) {
    setError(''); setNotice(''); setBusy(true)
    try {
      await action()
      if (reload) await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel stack desktop-tool-panel">
    <h2>备份与恢复</h2>
    <p className="muted">授权目录后每日备份，保留最近 7 份。备份包含本机资料，不包含 API 密钥。</p>
    {backup?.path && <p className="source-scope">{backup.path}</p>}
    {backup?.latest && <small>最近备份 · {backup.latest}</small>}
    <div className="button-row">
      <button className="secondary" disabled={busy} onClick={() => void run(async () => {
        const grant = await invoke('desktop_pick_folder', { purpose: 'backup' })
        if (!grant) return
        await desktopRequest(token, '/desktop/data/backup', { method: 'PUT', body: JSON.stringify(grant) })
        const result = await desktopRequest<{ filename: string }>(token, '/desktop/data/backup', { method: 'POST' })
        setNotice('已创建 ' + result.filename)
      })}>选择备份目录</button>
      <button className="secondary" disabled={busy || !backup?.available} onClick={() => void run(async () => {
        const result = await desktopRequest<{ filename: string }>(token, '/desktop/data/backup', { method: 'POST' })
        setNotice('已创建 ' + result.filename)
      })}>立即备份</button>
      <button className="secondary" disabled={busy} onClick={() => void run(async () => {
        const grant = await invoke('desktop_pick_backup')
        if (!grant || !window.confirm('用此备份替换当前本机资料并重启工作区？恢复后需要重新授权后台同步和外部 AI。')) return
        await desktopRequest(token, '/desktop/data/restore', { method: 'POST', body: JSON.stringify(grant) })
        await invoke('desktop_stop_sidecar')
        await onRestore()
      }, false)}>从备份恢复</button>
    </div>
    {busy && <p role="status">正在处理本机数据…</p>}
    {notice && <p role="status">{notice}</p>}
    {(error || backup?.error) && <p role="alert" className="notice error">{error || backup?.error}</p>}
  </section>
}
