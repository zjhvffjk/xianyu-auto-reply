import type { Account } from '@/types'

/**
 * 账号展示名（会员名 + 昵称，不含备注）
 *
 * 背景：用户认的是闲鱼**会员名**（如 xy813599502354，与手机「账号与安全 - 会员名」一致），
 * 数字 account_id（如 2217291130670）对他没有辨识度。
 *
 * 规则：
 *   1. 有会员名 → 会员名，后面附昵称（闲鱼里自设的店铺名，如「明星周边奢侈品」）
 *   2. 没有会员名（老账号 Cookie 缺 tracknick）→ 退回备注，再退回数字账号ID，
 *      保证数据源没升级时表现与改造前一致
 *
 * 适用于备注会单独占一列/一行展示的场景（如批量维护列表）。
 */
export const getAccountName = (
  account: Pick<Account, 'id' | 'member_name' | 'nickname' | 'note'>,
): string => {
  const memberName = (account.member_name || '').trim()
  if (!memberName) return account.note || account.id

  const nickname = (account.nickname || '').trim()
  return nickname ? `${memberName} · ${nickname}` : memberName
}

/**
 * 账号下拉框的展示文案（会员名 + 昵称，昵称缺失时用备注补充）
 *
 * 下拉只有一行文字，没有备注列，所以昵称缺失时把备注接上，避免几个账号看起来一模一样。
 */
export const getAccountOptionLabel = (
  account: Pick<Account, 'id' | 'member_name' | 'nickname' | 'note'>,
): string => {
  const memberName = (account.member_name || '').trim()
  if (!memberName) {
    return account.note ? `${account.id} (${account.note})` : account.id
  }

  const extra = (account.nickname || account.note || '').trim()
  return extra ? `${memberName} · ${extra}` : memberName
}
