/** 统一账号名称。业务 value 和关联始终使用原账号 ID。 */
export interface AccountIdentity {
  id?: string
  account_id?: string
  member_name?: string
  nickname?: string
}

const cleanName = (value?: string): string => {
  const name = (value || '').trim()
  return name.includes('*') ? '' : name
}

export const getAccountMemberName = (account: AccountIdentity): string =>
  cleanName(account.member_name)

export const getAccountNickname = (account: AccountIdentity): string =>
  cleanName(account.nickname) || getAccountMemberName(account) || account.id || account.account_id || ''

export const getAccountName = (account: AccountIdentity): string => {
  const member = getAccountMemberName(account)
  const nickname = cleanName(account.nickname)
  return [member, nickname].filter((name, index, names) => name && names.indexOf(name) === index).join(' · ')
    || account.id || account.account_id || ''
}

export const getAccountOptionLabel = getAccountName
