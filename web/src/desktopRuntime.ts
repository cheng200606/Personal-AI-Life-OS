import { invoke, isTauri } from '@tauri-apps/api/core'
import type { VaultConflictPolicy, VaultDocument, VaultWriteResult } from './vaultExport'

type DesktopRuntime = { origin: string; secret: string }

export const desktop = isTauri()
let runtime: DesktopRuntime | undefined

export async function connectDesktop() {
  runtime = await invoke<DesktopRuntime>('desktop_runtime')
  const response = await apiFetch('/ready', { signal: AbortSignal.timeout(5000) })
  if (!response.ok) throw new Error('本机服务暂不可用。')
}

export function apiFetch(path: string, init: RequestInit = {}) {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('无效的 API 路径。')
  if (!desktop) return fetch((import.meta.env.VITE_API_BASE_URL || '') + '/api/v1' + path, init)
  if (!runtime) throw new Error('本机服务尚未就绪。')
  const headers = new Headers(init.headers)
  headers.set('X-LifeOS-Desktop', runtime.secret)
  return fetch(runtime.origin + '/api/v1' + path, {
    ...init, headers, cache: 'no-store', redirect: 'error', credentials: 'omit',
  })
}

export async function desktopRequest<T = void>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', 'Bearer ' + token)
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await apiFetch(path, { ...init, headers })
  if (response.status === 204) return undefined as T
  const result = await response.json()
  if (!response.ok) throw new Error(result.error?.message || '本机操作失败。')
  return result as T
}

export async function desktopExport(
  token: string, document: VaultDocument, policy: VaultConflictPolicy,
): Promise<VaultWriteResult | null> {
  const grant = await invoke('desktop_pick_folder', { purpose: 'export' })
  if (!grant) return null
  return desktopRequest<VaultWriteResult>(token, '/desktop/data/export', {
    method: 'POST', body: JSON.stringify({ grant, policy, ...document }),
  })
}
