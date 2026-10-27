/** 批量关联保留每个商品的保存结果；重试由调用方传入上次失败项。 */
export interface AssociationFailure { itemId: string; reason: string }

export async function saveAssociations(
  itemIds: string[],
  save: (itemId: string) => Promise<{ success: boolean; message?: string }>,
  onProgress: (done: number, total: number) => void,
): Promise<AssociationFailure[]> {
  const targets = [...new Set(itemIds)]
  const failures: AssociationFailure[] = []
  for (const [index, itemId] of targets.entries()) {
    try {
      const result = await save(itemId)
      if (!result.success) failures.push({itemId, reason: result.message || '关联失败'})
    } catch (error) {
      failures.push({itemId, reason: error instanceof Error ? error.message : '请求失败'})
    }
    onProgress(index + 1, targets.length)
  }
  return failures
}
