import { useStore } from './store'

/**
 * The asking state lives in the store, not in a component, so the work trail
 * survives navigation — asking a question on Home and landing in Chat shows the
 * same thinking steps rather than dropping them.
 */
export function useAsk() {
  const { ask, asking, stopAsking } = useStore()
  return { ask, asking, stop: stopAsking }
}
