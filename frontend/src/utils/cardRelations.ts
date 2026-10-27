import type { CardRelationItem } from '@/api/cards'

interface RelationCard {
  id?: number
  source: CardRelationItem['source']
  dock_record_id?: number | null
  dockRecordId?: number
}

interface SelectionCard extends RelationCard {
  enabled?: boolean
  is_multi_spec?: boolean
  spec_name?: string | null
  spec_value?: string | null
}

export function getCardSelectionWarnings(cards: readonly SelectionCard[]): string[] {
  const unique = new Map<number, SelectionCard>()
  for (const card of cards) {
    if (!card.id || card.enabled === false) continue
    if (!unique.has(card.id) || card.source === 'own') unique.set(card.id, card)
  }
  const groups = new Map<string, {count: number; label: string}>()
  const sourceNames = {own: '自有', dock_l1: '一级对接', dock_l2: '二级对接'}
  for (const card of unique.values()) {
    const spec = card.is_multi_spec
      ? [(card.spec_name || '').trim().toLowerCase(), (card.spec_value || '').trim().toLowerCase()]
      : []
    const key = JSON.stringify([card.source, spec])
    const group = groups.get(key) || {count: 0, label: `${sourceNames[card.source]} · ${spec.length ? spec.join('：') : '单规格'}`}
    group.count++
    groups.set(key, group)
  }
  return [...groups.values()].filter(group => group.count > 1).map(group => `${group.label}匹配到 ${group.count} 张启用卡券，可能无法唯一匹配。请保留一张，或为不同规格分别设置。`)
}

/** 已选项缺失时中止保存，避免把未加载的关联当成用户取消。 */
export function buildCardRelations(keys: Iterable<string>, cache: ReadonlyMap<string, RelationCard>): CardRelationItem[] {
  return Array.from(new Set(keys), key => {
    const card = cache.get(key)
    if (!card || !card.id) throw new Error('部分已选卡券尚未加载，请重试后再保存')
    return { card_id: card.id, source: card.source, dock_record_id: card.dock_record_id ?? card.dockRecordId ?? null }
  })
}
