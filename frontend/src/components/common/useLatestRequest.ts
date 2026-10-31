import { useCallback, useEffect, useRef } from 'react'

/** 列表仅接受最后一次请求的结果；卸载后所有在途请求失效。 */
export function useLatestRequest() {
  const generation = useRef(0)
  useEffect(() => () => { generation.current += 1 }, [])
  return useCallback(() => {
    const version = ++generation.current
    return () => version === generation.current
  }, [])
}
