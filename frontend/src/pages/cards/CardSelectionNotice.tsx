import { getCardSelectionWarnings } from '@/utils/cardRelations'
import type { SelectableCard } from '@/api/cards'

type Selection = Pick<SelectableCard, 'id' | 'source' | 'enabled' | 'is_multi_spec' | 'spec_name' | 'spec_value'>

export function CardSelectionNotice({cards}: {cards: Selection[]}) {
  const warnings = getCardSelectionWarnings(cards)
  return (
    <div className="space-y-1.5 text-xs leading-5">
      <p className="text-slate-500 dark:text-slate-400">按订单规格匹配卡券；来源优先级：自有 → 一级对接 → 二级对接。同一来源需唯一匹配。</p>
      {warnings.length > 0 && (
        <div role="status" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          {warnings.map(message => <p key={message}>{message}</p>)}
        </div>
      )}
    </div>
  )
}
