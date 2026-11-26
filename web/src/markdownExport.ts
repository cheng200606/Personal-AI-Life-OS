import { withObsidianFrontmatter } from './vaultExport'

export interface MarkdownItem {
  id: string
  kind: string
  title: string
  content_text: string
  occurred_at: string | null
  source_locator: Record<string, unknown>
}

export function buildItemMarkdown(
  item: MarkdownItem,
  sourceName: string,
  tags: string[],
  collections: string[],
  exportedAt = new Date().toISOString(),
): string {
  return withObsidianFrontmatter(
    ['# ' + item.title, '', item.content_text].join('\n'),
    {
      id: item.id,
      lifeos_id: item.id,
      title: item.title,
      type: item.kind,
      source: sourceName,
      occurred_at: item.occurred_at || 'unknown',
      source_locator: JSON.stringify(item.source_locator),
      tags,
      collections,
      exported_at: exportedAt,
    },
  )
}

export function buildReviewMarkdown(
  markdown: string,
  review: { id: string; period_start: string; period_end: string; status: string; version_number: number },
  exportedAt = new Date().toISOString(),
): string {
  const sourceIdsMatch = markdown.match(/^source_ids:\s*(\[[^\n]*\])\s*$/m);
  let sourceIds: string[] = [];
  if (sourceIdsMatch) {
    try {
      const parsed: unknown = JSON.parse(sourceIdsMatch[1]);
      if (Array.isArray(parsed)) sourceIds = parsed.filter((value): value is string => typeof value === "string");
    } catch {
      sourceIds = [];
    }
  }
  return withObsidianFrontmatter(markdown, {
    id: review.id,
    lifeos_id: review.id,
    title: `周复盘 ${review.period_start.slice(0, 10)} — ${review.period_end.slice(0, 10)}`,
    type: 'weekly_review',
    source: 'Life OS',
    occurred_at: review.period_end,
    period_start: review.period_start,
    period_end: review.period_end,
    status: review.status,
    version: review.version_number,
    source_ids: sourceIds,
    tags: [],
    collections: [],
    exported_at: exportedAt,
  })
}
