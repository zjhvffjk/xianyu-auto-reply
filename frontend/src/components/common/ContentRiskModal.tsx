/**
 * 发布前内容风险提示弹窗
 *
 * 预检命中高危违禁词 / 违规品类时弹出，列出命中词与对应的平台规则原文，
 * 由用户决定「取消发布」还是「仍要发布」（后者会在请求里带 force_publish 跳过拦截）。
 */
import { motion, AnimatePresence } from 'framer-motion'
import { ShieldAlert, X, Loader2 } from 'lucide-react'
import type { ContentRiskResult, MaterialRiskItem } from '@/api/productPublish'

export interface ContentRiskModalProps {
  isOpen: boolean
  risk: ContentRiskResult | null
  /** 命中对象说明，如「第 3 件素材」 */
  subject?: string
  /** 批量预检时逐条素材的命中明细 */
  materialRisks?: MaterialRiskItem[]
  loading?: boolean
  onCancel: () => void
  onForcePublish: () => void
}

export function ContentRiskModal({
  isOpen,
  risk,
  subject,
  materialRisks,
  loading = false,
  onCancel,
  onForcePublish,
}: ContentRiskModalProps) {
  const blockHits = (risk?.hits || []).filter((hit) => hit.level === 'block')
  const warnHits = (risk?.hits || []).filter((hit) => hit.level === 'warn')

  return (
    <AnimatePresence>
      {isOpen && risk && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="relative w-full max-w-lg mx-4 max-h-[85vh] overflow-y-auto bg-white dark:bg-slate-800 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700"
          >
            <button
              onClick={onCancel}
              className="absolute top-3 right-3 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="p-6">
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-full bg-red-100 dark:bg-red-900/30 flex-shrink-0">
                  <ShieldAlert className="w-5 h-5 text-red-500" />
                </div>
                <div className="flex-1 pr-6">
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                    检测到违禁内容风险
                  </h3>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                    {subject ? `${subject}的` : ''}标题或描述命中 {risk.hit_count} 处风险词，
                    继续发布可能被闲鱼判违规、删除商品并扣减闲气值。
                  </p>
                </div>
              </div>

              {materialRisks && materialRisks.length > 0 && (
                <div className="mt-4 space-y-1.5">
                  <p className="text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">
                    命中的素材（{materialRisks.length} 件）
                  </p>
                  {materialRisks.slice(0, 8).map((item) => (
                    <div key={item.material_id} className="flex items-start gap-2 text-xs">
                      <span className="text-slate-400 flex-shrink-0">#{item.material_id}</span>
                      <span className="text-slate-600 dark:text-slate-300 truncate flex-1">{item.title}</span>
                      <span className="text-red-500 flex-shrink-0">
                        {item.risk.hits.filter((hit) => hit.level === 'block').map((hit) => hit.term).slice(0, 3).join('、')}
                      </span>
                    </div>
                  ))}
                  {materialRisks.length > 8 && (
                    <p className="text-xs text-slate-400">…另有 {materialRisks.length - 8} 件</p>
                  )}
                </div>
              )}

              {blockHits.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-medium text-red-600 dark:text-red-400 mb-2">
                    高危命中（会被判定违规）
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {blockHits.map((hit) => (
                      <span
                        key={`${hit.group_id}-${hit.term}`}
                        className="px-2 py-0.5 rounded-md bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-xs border border-red-200 dark:border-red-800"
                        title={hit.label}
                      >
                        {hit.term}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {warnHits.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-amber-600 dark:text-amber-400 mb-2">
                    一般提示（可能限流）
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {warnHits.map((hit) => (
                      <span
                        key={`${hit.group_id}-${hit.term}`}
                        className="px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 text-xs border border-amber-200 dark:border-amber-800"
                        title={hit.label}
                      >
                        {hit.term}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4 space-y-2">
                {risk.rules.map((rule) => (
                  <div
                    key={rule.group_id}
                    className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-3"
                  >
                    <p className="text-xs font-medium text-slate-700 dark:text-slate-200">
                      {rule.label}
                    </p>
                    {rule.rule && (
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{rule.rule}</p>
                    )}
                    {rule.hint && (
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{rule.hint}</p>
                    )}
                  </div>
                ))}
              </div>

              <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
                说明：检测基于本地词库，仅覆盖文字内容，图片里的二维码/微信号不在检测范围内。
                命中不代表必然违规，未命中也不代表一定安全。
              </p>
            </div>

            <div className="flex gap-3 px-6 pb-6">
              <button
                onClick={onForcePublish}
                disabled={loading}
                className="flex-1 px-4 py-2.5 rounded-lg font-medium transition-colors bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                仍要发布
              </button>
              <button
                onClick={onCancel}
                disabled={loading}
                className="flex-1 px-4 py-2.5 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 bg-red-500 hover:bg-red-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                返回修改
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
