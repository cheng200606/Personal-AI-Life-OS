import { randomUUID } from 'node:crypto'
import { mkdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { buildItemMarkdown, buildReviewMarkdown } from '../src/markdownExport'
import { normalizeSharedCapture, sharedCaptureBody } from '../src/pwa'
import { safeVaultFilename, withObsidianFrontmatter, writeVaultDocument } from '../src/vaultExport'

async function register(page: import('@playwright/test').Page, prefix: string, path = '/') {
  await page.goto(path)
  await page.getByRole('button', { name: '创建账号' }).click()
  await page.getByLabel('邮箱').fill(`${prefix}-${randomUUID()}@example.test`)
  await page.getByLabel('密码').fill('synthetic-browser-password')
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
}

test('publishes stable Obsidian frontmatter and sanitizes filenames', () => {
  const markdown = buildItemMarkdown({
    id: '11111111-1111-1111-1111-111111111111',
    kind: 'quick_note',
    title: 'M10: 可移植笔记',
    content_text: 'Keep the source link.',
    occurred_at: null,
    source_locator: { kind: 'quick_note' },
  }, 'Quick notes', ['工作', '决策'], ['发布'], '2026-11-26T09:00:00Z')
  expect(markdown).toContain('lifeos_id: "11111111-1111-1111-1111-111111111111"')
  expect(markdown).toContain('type: "quick_note"')
  expect(markdown).toContain('occurred_at: "unknown"')
  expect(markdown).toContain('tags:\n  - "工作"\n  - "决策"')
  expect(markdown).toContain('collections:\n  - "发布"')
  expect(markdown).toContain('exported_at: "2026-11-26T09:00:00Z"')
  expect(safeVaultFilename('../M10: 笔记')).toBe('M10 笔记.md')
  expect(withObsidianFrontmatter('---\nold: value\n---\n\n# Body', { title: 'New' })).not.toContain('old: value')
  const review = buildReviewMarkdown('---\nsource_ids: ["item-1", "item-2"]\n---\n\n# Review', { id: 'review-1', period_start: '2026-11-16', period_end: '2026-11-23', status: 'confirmed', version_number: 2 }, '2026-11-26T09:00:00Z')
  expect(review).toContain('source_ids:\n  - "item-1"\n  - "item-2"')
})

function fakeDirectory(initial: Record<string, string> = {}) {
  const files = new Map(Object.entries(initial))
  const writes: Array<{ name: string; content: string }> = []
  const directory = {
    kind: 'directory',
    name: 'Vault',
    async getFileHandle(name: string, options?: { create?: boolean }) {
      if (!files.has(name) && !options?.create) throw new DOMException('Missing', 'NotFoundError')
      return {
        kind: 'file',
        name,
        async getFile() { return new File([files.get(name) || ''], name, { type: 'text/markdown' }) },
        async createWritable() {
          return {
            async write(content: string) { writes.push({ name, content }) },
            async close() { files.set(name, writes[writes.length - 1].content) },
            async abort() { writes.pop() },
          }
        },
      }
    },
  }
  return { directory, files, writes }
}

test('keeps, copies, and explicitly overwrites Vault conflicts', async () => {
  const kept = fakeDirectory({ 'note.md': 'My manual Obsidian edit.' })
  const document = { filename: 'note.md', markdown: 'Generated Markdown.' }
  expect(await writeVaultDocument(kept.directory as never, document, 'keep')).toEqual({ status: 'kept', filename: 'note.md' })
  expect(kept.files.get('note.md')).toBe('My manual Obsidian edit.')
  expect(kept.writes).toHaveLength(0)

  expect(await writeVaultDocument(kept.directory as never, document, 'copy')).toEqual({ status: 'written', filename: 'note-1.md' })
  expect(kept.files.get('note.md')).toBe('My manual Obsidian edit.')
  expect(kept.files.get('note-1.md')).toBe('Generated Markdown.')

  expect(await writeVaultDocument(kept.directory as never, document, 'overwrite')).toEqual({ status: 'written', filename: 'note.md' })
  expect(kept.files.get('note.md')).toBe('Generated Markdown.')
})

test('normalizes bounded shared text for mobile capture', () => {
  const shared = normalizeSharedCapture({ title: ' Shared ', text: ' Body ', url: ' https://example.test/item ', receivedAt: 'now' })
  expect(sharedCaptureBody(shared)).toBe('Body\n\nhttps://example.test/item')
  expect(normalizeSharedCapture({ text: 'x'.repeat(21000) }).text).toHaveLength(20000)
  expect(normalizeSharedCapture({ title: 'x'.repeat(500) }).title).toHaveLength(200)
  expect(normalizeSharedCapture({ expiresAt: 1 }).expiresAt).toBe(1)
})

test('writes through the Vault picker without silently replacing manual edits', async ({ page }) => {
  await page.addInitScript(() => {
    const files = new Map<string, string>()
    const writes: Array<{ name: string; content: string }> = []
    Object.assign(window, { __vaultFiles: files, __vaultWrites: writes })
    Object.defineProperty(window, 'showDirectoryPicker', {
      configurable: true,
      value: async () => ({
        kind: 'directory',
        name: 'Vault',
        async getFileHandle(name: string, options?: { create?: boolean }) {
          const baseConflict = name.startsWith('M10-note-') && !name.endsWith('-1.md') && !name.endsWith('-2.md')
          if (!files.has(name) && !baseConflict && !options?.create) throw new DOMException('Missing', 'NotFoundError')
          return {
            kind: 'file', name,
            async getFile() { return new File([files.get(name) || 'Manual Obsidian edit.'], name) },
            async createWritable() {
              return {
                async write(content: string) { writes.push({ name, content }) },
                async close() { files.set(name, writes[writes.length - 1].content) },
                async abort() { writes.pop() },
              }
            },
          }
        },
      }),
    })
  })
  await register(page, 'browser-m10-vault')
  const panel = page.locator('.quick-note-panel')
  await panel.getByLabel('标题（可选）').fill('M10 note')
  await panel.getByLabel('正文').fill('Portable capture with source metadata.')
  await panel.getByRole('button', { name: '保存笔记' }).click()
  await expect(page.locator('.timeline-item')).toHaveCount(1)

  await page.getByRole('button', { name: '导出 Markdown ↗' }).click()
  await expect(page.getByRole('status')).toContainText('已保留现有文件')
  expect(await page.evaluate(() => (window as unknown as { __vaultWrites: unknown[] }).__vaultWrites.length)).toBe(0)

  await page.getByLabel('Vault 冲突策略').selectOption('copy')
  await page.getByRole('button', { name: '导出 Markdown ↗' }).click()
  await expect(page.getByRole('status')).toContainText('已写入 Vault')
  const copied = await page.evaluate(() => {
    const files = (window as unknown as { __vaultFiles: Map<string, string> }).__vaultFiles
    return Array.from(files.entries()).find(([name]) => name.endsWith('-1.md'))?.[1] || ''
  })
  expect(copied).toContain('lifeos_id:')
  expect(copied).toContain('type: "quick_note"')
  expect(copied).toContain('Portable capture with source metadata.')

  await page.getByLabel('Vault 冲突策略').selectOption('overwrite')
  await page.getByRole('button', { name: '导出 Markdown ↗' }).click()
  await expect(page.getByRole('status')).toContainText('已写入 Vault')
  await expect.poll(() => page.evaluate(() => (window as unknown as { __vaultWrites: unknown[] }).__vaultWrites.length)).toBe(2)
})

test('falls back to a downloadable Markdown file when Vault permission is denied', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'showDirectoryPicker', {
      configurable: true,
      value: async () => { throw new DOMException('Permission denied', 'NotAllowedError') },
    })
  })
  await register(page, 'browser-m10-fallback')
  const panel = page.locator('.quick-note-panel')
  await panel.getByLabel('标题（可选）').fill('M10 fallback')
  await panel.getByLabel('正文').fill('Download remains available without directory permission.')
  await panel.getByRole('button', { name: '保存笔记' }).click()
  await expect(page.locator('.timeline-item')).toHaveCount(1)
  const itemId = (await page.locator('.timeline-item').getAttribute('id'))!.replace('timeline-item-', '')
  await page.evaluate(async (id) => {
    const token = sessionStorage.getItem('lifeos-token') || ''
    const headers = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
    const tag = await fetch('/api/v1/tags', { method: 'POST', headers, body: JSON.stringify({ name: '工作', color: '#863bff' }) }).then((response) => response.json())
    const collection = await fetch('/api/v1/collections', { method: 'POST', headers, body: JSON.stringify({ name: 'M10 验收', description: 'Synthetic export evidence' }) }).then((response) => response.json())
    const response = await fetch('/api/v1/items/' + id + '/organization', { method: 'PUT', headers, body: JSON.stringify({ tag_ids: [tag.id], collection_ids: [collection.id] }) })
    if (!response.ok) throw new Error('Synthetic organization setup failed')
  }, itemId)
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 Markdown ↗' }).click()
  const download = await downloadEvent
  const vaultDir = join(testInfo.outputPath('M10 Vault'))
  await mkdir(vaultDir, { recursive: true })
  const path = join(vaultDir, 'm10-export.md')
  await download.saveAs(path)
  const markdown = await readFile(path, 'utf8')
  expect(markdown).toContain('lifeos_id:')
  expect(markdown).toContain('tags:\n  - "工作"')
  expect(markdown).toContain('collections:\n  - "M10 验收"')
  expect(markdown).toContain('Download remains available without directory permission.')
  await expect(page.getByRole('status')).toContainText('已改为下载')
})

test.describe('mobile capture', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('captures a shared note and views it in the timeline', async ({ page }) => {
    await register(page, 'browser-m10-mobile', '/capture?shared=1&title=Shared%20decision&text=Verify%20mobile%20capture.&url=https%3A%2F%2Fexample.test%2Fsource')
    await expect(page.getByRole('heading', { name: '快速捕获', exact: true })).toBeVisible()
    await expect(page.getByLabel('标题（可选）')).toHaveValue('Shared decision')
    await expect(page.getByLabel('正文')).toHaveValue('Verify mobile capture.\n\nhttps://example.test/source')
    await page.getByRole('button', { name: '保存笔记' }).click()
    await expect(page.getByRole('status')).toContainText('快速笔记已保存')
    await expect(page.locator('.capture-recent')).toContainText('Shared decision')
    await page.getByRole('button', { name: '查看时间线' }).click()
    await expect(page.locator('.timeline-item')).toContainText('Verify mobile capture.')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })

  test('consumes the service-worker share inbox without caching API data', async ({ page, request }) => {
    const manifestResponse = await request.get('/manifest.webmanifest')
    expect(manifestResponse.ok()).toBe(true)
    const manifest = await manifestResponse.json()
    expect(manifest.share_target).toMatchObject({ action: '/share-target', method: 'POST', params: { title: 'title', text: 'text', url: 'url' } })
    await register(page, 'browser-m10-share')
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/sw.js')
      await navigator.serviceWorker.ready
    })
    if (!await page.evaluate(() => Boolean(navigator.serviceWorker.controller))) await page.reload()
    await expect(page.getByRole('heading', { name: '时间线', exact: true })).toBeVisible()

    await page.evaluate(async () => {
      const form = new FormData()
      form.set('title', 'Service worker share')
      form.set('text', 'Captured through the real fetch handler.')
      form.set('url', 'https://example.test/shared')
      await fetch('/share-target', { method: 'POST', body: form, redirect: 'manual' }).catch(() => undefined)
    }).catch(() => undefined)
    await expect(page.getByRole('heading', { name: '快速捕获', exact: true })).toBeVisible()
    await expect(page.getByLabel('标题（可选）')).toHaveValue('Service worker share')
    await expect(page.getByLabel('正文')).toHaveValue('Captured through the real fetch handler.\n\nhttps://example.test/shared')
    expect(await page.evaluate(async () => {
      const cache = await caches.open('lifeos-share-inbox-v1')
      return Boolean(await cache.match('/__lifeos_pending_share__'))
    })).toBe(false)
    expect(await page.evaluate(async () => {
      const names = await caches.keys()
      const entries = await Promise.all(names.map(async (name) => (await (await caches.open(name)).keys()).map((request) => request.url)))
      return entries.flat().some((url) => url.includes('/api/'))
    })).toBe(false)
  })

  test('keeps due reminders usable when notification permission is denied', async ({ page }) => {
    await register(page, 'browser-m10-notification')
    await page.getByRole('button', { name: /复盘/ }).click()
    await page.getByPlaceholder('需要跟进什么？').fill('Mobile due reminder')
    await page.getByLabel('提醒到期时间').fill('2020-01-01T10:00')
    await page.getByRole('button', { name: '添加提醒' }).click()
    await expect(page.locator('.due-reminders')).toContainText('Mobile due reminder')
    await page.evaluate(() => {
      if ('Notification' in window) Object.defineProperty(Notification, 'permission', { configurable: true, get: () => 'denied' })
    })
    await page.getByRole('button', { name: '启用浏览器通知' }).click()
    await expect(page.locator('.due-reminders')).toContainText(/通知未获授权|不支持通知/)
    await expect(page.locator('.due-reminders')).toContainText('Mobile due reminder')
    await expect(page.locator('.nav-badge')).toHaveText('1')
  })
})
