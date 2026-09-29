/**
 * Optional cloud account: Google Sign-In + Firestore sync, layered on top of
 * Orion's local-first store.
 *
 * Ground rules
 *  - localStorage stays the source the UI reads from. Signed out, offline, or
 *    with Firebase not configured at all, nothing here changes how Orion works.
 *  - Firebase code is loaded on demand (dynamic import), so it never delays or
 *    blocks the first paint, and a missing/broken config can't break the app.
 *  - Sync is one-directional at runtime and cannot loop:
 *      sign-in / reload  → fetch the account once, MERGE it into local state
 *                          (union — nothing local is deleted), upload the diff;
 *      after that        → local changes are debounced and only documents whose
 *                          content actually changed are written.
 *    Remote data is only ever read during that merge, never in response to our
 *    own writes, so a write can't echo back into state and trigger another.
 *  - Deleting a conversation while signed in deletes it from the account too
 *    (an explicit user action). Signing out never deletes anything.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Access, Conversation, Prefs, Profile } from './types'
import { SEED_CONVERSATIONS } from './seed'
import type { AccountUser } from '../lib/firebaseAuth'
import type { RemoteSnapshot, SyncedSettings, Write } from '../lib/firestore'

export type AccountState =
  | { status: 'unconfigured' }
  | { status: 'loading' }
  | { status: 'signedOut' }
  | { status: 'signedIn'; user: AccountUser }

export type SyncPhase = 'idle' | 'syncing' | 'synced' | 'offline' | 'error'
export interface SyncState { phase: SyncPhase; at?: number; detail?: string }

export interface Cloud {
  account: AccountState
  sync: SyncState
  busy: boolean
  signIn: () => Promise<void>
  signOut: () => Promise<void>
  syncNow: () => void
}

interface Deps {
  profile: Profile
  setProfile: (p: Profile) => void
  access: Access
  setAccess: (a: Access) => void
  prefs: Prefs
  setPrefs: (p: Prefs) => void
  conversations: Conversation[]
  setConversations: (c: Conversation[]) => void
  toast: (title: string, detail?: string) => void
}

/* ------------------------------------------------------------ local meta */

/** When the profile/settings last changed on THIS device — the tie-breaker
 * when the same field was changed on two devices. */
interface Meta { profileHash: string; profileAt: number; settingsHash: string; settingsAt: number }
const META_KEY = 'vf.sync.meta'

function readMeta(): Meta | null {
  try {
    const raw = localStorage.getItem(META_KEY)
    return raw ? (JSON.parse(raw) as Meta) : null
  } catch {
    return null
  }
}
function writeMeta(m: Meta) {
  try { localStorage.setItem(META_KEY, JSON.stringify(m)) } catch { /* storage blocked */ }
}

/** JSON with sorted keys, so equal content always compares equal. */
export function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(',')}]`
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    return `{${Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${stable(o[k])}`).join(',')}}`
  }
  return JSON.stringify(v) ?? 'null'
}

const profileHash = (p: Profile, a: Access) => stable({ p, a })
const settingsHash = (p: Prefs) => stable({ t: p.theme ?? 'dark', r: p.reduceMotion, w: p.webSearch, o: p.onboarded })

/* ------------------------------------------------------------ merge (pure) */

const PROFILE_KEYS = ['name', 'age', 'profession', 'experience', 'site'] as const

/** Field by field: an empty side never erases a filled one; when both are
 * filled and differ, the side changed most recently wins. */
export function mergeProfile(
  local: Profile, localAccess: Access, localAt: number, remote: RemoteSnapshot['profile'],
): { profile: Profile; access: Access } {
  if (!remote) return { profile: local, access: localAccess }
  const remoteNewer = remote.clientUpdatedAt > localAt
  const profile = { ...local }
  for (const k of PROFILE_KEYS) {
    const r = (remote.profile[k] ?? '').trim()
    const l = local[k].trim()
    if (!l && r) profile[k] = remote.profile[k] ?? ''
    else if (l && r && l !== r && remoteNewer) profile[k] = remote.profile[k] ?? local[k]
  }
  const access = remote.access && remoteNewer ? remote.access : localAccess
  return { profile, access }
}

export function mergeSettings(local: Prefs, localAt: number, remote: RemoteSnapshot['settings']): Prefs {
  if (!remote) return local
  const pick: SyncedSettings = remote.clientUpdatedAt > localAt
    ? remote.settings
    : { theme: local.theme ?? 'dark', reduceMotion: local.reduceMotion, webSearch: local.webSearch, onboarded: local.onboarded }
  // Having finished onboarding anywhere means it's finished.
  return { ...local, ...pick, onboarded: local.onboarded || remote.settings.onboarded }
}

/** Union by id. Messages are unioned by id and kept in time order; title and
 * dates come from whichever copy was opened more recently. */
export function mergeConversations(local: Conversation[], remote: Conversation[]): Conversation[] {
  const remoteById = new Map(remote.map((c) => [c.id, c]))
  const merged = local.map((l) => {
    const r = remoteById.get(l.id)
    if (!r) return l
    remoteById.delete(l.id)
    const byId = new Map(l.messages.map((m) => [m.id, m]))
    for (const m of r.messages) if (!byId.has(m.id)) byId.set(m.id, m)
    const newer = r.openedAt > l.openedAt ? r : l
    return {
      ...l,
      title: newer.title,
      machine: newer.machine ?? l.machine ?? r.machine,
      startedAt: Math.min(l.startedAt, r.startedAt),
      openedAt: Math.max(l.openedAt, r.openedAt),
      fileIds: Array.from(new Set([...l.fileIds, ...r.fileIds])),
      messages: Array.from(byId.values()).sort((a, b) => a.at - b.at),
    }
  })
  const onlyRemote = Array.from(remoteById.values()).sort((a, b) => b.openedAt - a.openedAt)
  return [...onlyRemote, ...merged]
}

/** The demo conversations every install starts with aren't the user's data;
 * they're only uploaded once the user has actually added to them. */
const SEED_SIZE = new Map(SEED_CONVERSATIONS.map((c) => [c.id, c.messages.length]))
const isUntouchedSeed = (c: Conversation) => SEED_SIZE.get(c.id) === c.messages.length

/* ------------------------------------------------------------ the hook */

type Fs = typeof import('../lib/firestore')
type AuthMod = typeof import('../lib/firebaseAuth')

const loadFirebase = async () => {
  const [base, auth, fs] = await Promise.all([
    import('../lib/firebase'), import('../lib/firebaseAuth'), import('../lib/firestore'),
  ])
  return { configured: base.firebaseConfigured, auth, fs }
}

/** Every cloud document the current local state should produce: path → data. */
function desiredDocs(fs: Fs, uid: string, d: Pick<Deps, 'profile' | 'access' | 'prefs' | 'conversations'>, meta: Meta) {
  const out = new Map<string, Record<string, unknown>>()
  out.set(fs.paths.profile(uid), fs.profileDoc(d.profile, d.access, meta.profileAt))
  out.set(fs.paths.settings(uid), fs.settingsDoc(fs.settingsOf(d.prefs), meta.settingsAt))
  for (const c of d.conversations) {
    if (isUntouchedSeed(c)) continue
    out.set(fs.paths.conversation(uid, c.id), fs.conversationDoc(c))
    for (const m of c.messages) out.set(fs.paths.message(uid, c.id, m.id), fs.messageDoc(m))
  }
  return out
}

export function useCloudSync(deps: Deps): Cloud {
  const [account, setAccount] = useState<AccountState>({ status: 'loading' })
  const [sync, setSync] = useState<SyncState>({ phase: 'idle' })
  const [busy, setBusy] = useState(false)

  const d = useRef(deps)
  d.current = deps
  const mods = useRef<{ auth: AuthMod; fs: Fs } | null>(null)
  /** uid whose account has been merged this session; writes wait for it. */
  const mergedUid = useRef<string | null>(null)
  /** What the cloud holds, as far as we know: path → stable JSON. */
  const synced = useRef<Map<string, string>>(new Map())
  const userSignedOut = useRef(false)
  const lastUid = useRef<string | null>(null)
  const pushTimer = useRef<number | null>(null)
  const blocked = useRef(false)

  const fail = useCallback((err: unknown, during: string) => {
    const a = mods.current?.auth
    const code = a?.errorCode(err) ?? ''
    const e = a?.explainFirebaseError(err) ?? { title: 'Cloud sync failed' }
    if (code === 'unavailable' || code === 'auth/network-request-failed') {
      setSync({ phase: 'offline', detail: 'Waiting for a connection — changes are kept on this device.' })
      return
    }
    if (code === 'permission-denied' || code === 'unauthenticated') blocked.current = true
    setSync({ phase: 'error', detail: e.detail })
    d.current.toast(e.title, e.detail ?? `While ${during}.`)
  }, [])

  /* ---- local change timestamps (always on, even signed out) ---- */
  const { profile, access, prefs, conversations } = deps
  useEffect(() => {
    const m = readMeta()
    const ph = profileHash(profile, access)
    const sh = settingsHash(prefs)
    if (!m) {
      // First run with sync support: anything already here predates tracking,
      // so it loses a genuine conflict (it still fills any empty field).
      writeMeta({ profileHash: ph, profileAt: 0, settingsHash: sh, settingsAt: 0 })
      return
    }
    if (m.profileHash !== ph || m.settingsHash !== sh) {
      writeMeta({
        profileHash: ph, profileAt: m.profileHash !== ph ? Date.now() : m.profileAt,
        settingsHash: sh, settingsAt: m.settingsHash !== sh ? Date.now() : m.settingsAt,
      })
    }
  }, [profile, access, prefs])

  /* ---- push: debounced diff of local state against what the cloud has ---- */
  const push = useCallback(async () => {
    const uid = mergedUid.current
    const m = mods.current
    if (!uid || !m || blocked.current) return
    const meta = readMeta()
    if (!meta) return
    const want = desiredDocs(m.fs, uid, d.current, meta)
    const writes: Write[] = []
    const next = new Map(synced.current)
    for (const [path, data] of want) {
      const s = stable(data)
      if (synced.current.get(path) !== s) { writes.push({ kind: 'set', path, data }); next.set(path, s) }
    }
    // Conversations that were here after the last sync and are gone now were
    // deleted by the user: delete them (and every message) from the account.
    const prefix = `users/${uid}/conversations/`
    const gone = new Set<string>()
    for (const path of synced.current.keys()) {
      if (!path.startsWith(prefix)) continue
      const cid = path.slice(prefix.length).split('/')[0]
      if (!want.has(`${prefix}${cid}`)) gone.add(cid)
    }
    try {
      for (const cid of gone) {
        writes.push(...await m.fs.conversationDeletes(uid, cid))
        for (const k of Array.from(next.keys())) if (k.startsWith(`${prefix}${cid}`)) next.delete(k)
      }
      if (!writes.length) return
      setSync({ phase: 'syncing' })
      await m.fs.commit(writes)
      synced.current = next
      setSync({ phase: 'synced', at: Date.now() })
    } catch (err) {
      fail(err, 'saving your changes')
    }
  }, [fail])

  useEffect(() => {
    if (!mergedUid.current) return
    if (pushTimer.current) window.clearTimeout(pushTimer.current)
    pushTimer.current = window.setTimeout(() => { void push() }, 1200)
    return () => { if (pushTimer.current) window.clearTimeout(pushTimer.current) }
  }, [profile, access, prefs, conversations, push])

  /* ---- merge: once per sign-in / reload ---- */
  const merge = useCallback(async (user: AccountUser) => {
    const m = mods.current
    if (!m) return
    setSync({ phase: 'syncing' })
    try {
      const remote = await m.fs.fetchAll(user.uid)
      const cur = d.current
      const meta = readMeta() ?? { profileHash: '', profileAt: 0, settingsHash: '', settingsAt: 0 }

      const { profile: p, access: a } = mergeProfile(cur.profile, cur.access, meta.profileAt, remote.profile)
      // A signed-in Google name fills an empty profile name.
      const profile = !p.name.trim() && user.displayName ? { ...p, name: user.displayName } : p
      const prefs = mergeSettings(cur.prefs, meta.settingsAt, remote.settings)
      const conversations = mergeConversations(cur.conversations, remote.conversations)

      // Record the merged values as already-seen so they don't count as fresh
      // local edits (which would bump timestamps and cause a needless rewrite).
      const merged: Meta = {
        profileHash: profileHash(profile, a),
        profileAt: Math.max(meta.profileAt, remote.profile?.clientUpdatedAt ?? 0),
        settingsHash: settingsHash(prefs),
        settingsAt: Math.max(meta.settingsAt, remote.settings?.clientUpdatedAt ?? 0),
      }
      writeMeta(merged)

      // What the cloud actually holds right now, in the same serialised form.
      const have = new Map<string, string>()
      if (remote.profile) {
        have.set(m.fs.paths.profile(user.uid), stable(m.fs.profileDoc(
          { name: '', age: '', profession: '', experience: '', site: '', ...remote.profile.profile },
          remote.profile.access ?? cur.access, remote.profile.clientUpdatedAt)))
      }
      if (remote.settings) have.set(m.fs.paths.settings(user.uid), stable(m.fs.settingsDoc(remote.settings.settings, remote.settings.clientUpdatedAt)))
      for (const c of remote.conversations) {
        have.set(m.fs.paths.conversation(user.uid, c.id), stable(m.fs.conversationDoc(c)))
        for (const msg of c.messages) have.set(m.fs.paths.message(user.uid, c.id, msg.id), stable(m.fs.messageDoc(msg)))
      }

      if (stable(profile) !== stable(cur.profile)) cur.setProfile(profile)
      if (stable(a) !== stable(cur.access)) cur.setAccess(a)
      if (stable(prefs) !== stable(cur.prefs)) cur.setPrefs(prefs)
      if (stable(conversations) !== stable(cur.conversations)) cur.setConversations(conversations)

      synced.current = have
      blocked.current = false
      mergedUid.current = user.uid
      lastUid.current = user.uid
      // Upload whatever the account didn't have yet (with the merged state).
      d.current = { ...cur, profile, access: a, prefs, conversations }
      const added = remote.conversations.filter((r) => !cur.conversations.some((l) => l.id === r.id)).length
      await push()
      setSync((s) => (s.phase === 'error' ? s : { phase: 'synced', at: Date.now() }))
      if (added) d.current.toast('Synced with your account', `${added} conversation${added > 1 ? 's' : ''} from your other devices added.`)
    } catch (err) {
      mergedUid.current = null
      fail(err, 'loading your account')
    }
  }, [fail, push])

  /* ---- auth: restore the session and follow it ---- */
  useEffect(() => {
    let stop: (() => void) | undefined
    let alive = true
    void loadFirebase()
      .then(({ configured, auth, fs }) => {
        if (!alive) return
        if (!configured) { setAccount({ status: 'unconfigured' }); return }
        mods.current = { auth, fs }
        stop = auth.watchAuth((user) => {
          if (user) {
            setAccount({ status: 'signedIn', user })
            if (mergedUid.current !== user.uid) void merge(user)
            return
          }
          const wasSignedIn = lastUid.current !== null
          mergedUid.current = null
          synced.current = new Map()
          lastUid.current = null
          setAccount({ status: 'signedOut' })
          setSync({ phase: 'idle' })
          if (wasSignedIn && !userSignedOut.current) {
            d.current.toast('Your session has ended', 'Sign in again to resume cloud sync. Everything on this device is kept.')
          }
          userSignedOut.current = false
        })
      })
      .catch(() => { if (alive) setAccount({ status: 'unconfigured' }) })
    return () => { alive = false; stop?.() }
  }, [merge])

  // Offline during the merge? Try again as soon as the connection returns.
  useEffect(() => {
    const retry = () => {
      if (account.status !== 'signedIn') return
      if (mergedUid.current !== account.user.uid) void merge(account.user)
      else void push()
    }
    window.addEventListener('online', retry)
    return () => window.removeEventListener('online', retry)
  }, [account, merge, push])

  const signIn = useCallback(async () => {
    const m = mods.current
    if (!m) return
    setBusy(true)
    try {
      const user = await m.auth.signInWithGoogle()
      d.current.toast('Signed in', `${user.email ?? user.displayName ?? 'Google account'} — syncing your profile and conversations.`)
    } catch (err) {
      const e = m.auth.explainFirebaseError(err)
      if (!e.quiet) d.current.toast(e.title, e.detail)
    } finally {
      setBusy(false)
    }
  }, [])

  const signOut = useCallback(async () => {
    const m = mods.current
    if (!m) return
    setBusy(true)
    try {
      if (pushTimer.current) window.clearTimeout(pushTimer.current)
      await push() // don't leave the last few seconds of changes behind
      userSignedOut.current = true
      await m.auth.signOutUser()
      d.current.toast('Signed out', 'Everything stays on this device. Sign in again to resume sync.')
    } catch (err) {
      userSignedOut.current = false
      const e = m.auth.explainFirebaseError(err)
      d.current.toast(e.title, e.detail)
    } finally {
      setBusy(false)
    }
  }, [push])

  const syncNow = useCallback(() => {
    if (account.status !== 'signedIn') return
    blocked.current = false
    mergedUid.current = null
    void merge(account.user)
  }, [account, merge])

  return { account, sync, busy, signIn, signOut, syncNow }
}
