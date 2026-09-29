/**
 * Orion's Firestore layout — everything under the signed-in user's uid:
 *
 *   users/{uid}/profile/main                         profile + AI-access choices
 *   users/{uid}/settings/app                         theme, motion, web search…
 *   users/{uid}/conversations/{conversationId}       title, dates, message count
 *   users/{uid}/conversations/{id}/messages/{msgId}  one document per message
 *
 * (A Firestore document path needs an even number of segments, so the profile
 * lives at users/{uid}/profile/main rather than users/{uid}/profile.)
 *
 * What is deliberately NOT here: document/PDF contents, camera frames, photos,
 * audio, model files, and the backend's SQLite memory. Messages keep only text
 * and structure; any inline image (data:/blob: URL) is stripped before upload.
 */
import {
  collection, doc, getDoc, getDocs, serverTimestamp, writeBatch,
  type DocumentData, type Firestore,
} from 'firebase/firestore'
import type { Access, Conversation, Message, Prefs, Profile } from '../app/types'
import { firestore } from './firebase'

export interface RemoteProfile { profile: Partial<Profile>; access?: Access; clientUpdatedAt: number }
export interface RemoteSettings { settings: SyncedSettings; clientUpdatedAt: number }
export interface RemoteSnapshot {
  profile: RemoteProfile | null
  settings: RemoteSettings | null
  conversations: Conversation[]
}

/** The app settings that follow the account across devices. */
export type SyncedSettings = Pick<Prefs, 'reduceMotion' | 'webSearch' | 'onboarded'> & { theme: 'dark' | 'light' }

export const settingsOf = (p: Prefs): SyncedSettings => ({
  theme: p.theme ?? 'dark', reduceMotion: p.reduceMotion, webSearch: p.webSearch, onboarded: p.onboarded,
})

/* ------------------------------------------------------------ paths */

export const paths = {
  profile: (uid: string) => `users/${uid}/profile/main`,
  settings: (uid: string) => `users/${uid}/settings/app`,
  conversation: (uid: string, cid: string) => `users/${uid}/conversations/${cid}`,
  message: (uid: string, cid: string, mid: string) => `users/${uid}/conversations/${cid}/messages/${mid}`,
}

/* ------------------------------------------------------------ serialise */

/** Firestore rejects `undefined`; JSON round-trip drops it (all data here is plain JSON). */
const plain = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

const isInlineMedia = (url?: string) => !!url && /^(data|blob):/i.test(url)

/** A message as stored in the cloud: text and structure only, no inline media. */
export function messageDoc(m: Message): DocumentData {
  return plain({
    ...m,
    evidence: m.evidence?.map((e) => (isInlineMedia(e.url) ? { id: e.id, caption: e.caption } : e)),
  })
}

export function conversationDoc(c: Conversation): DocumentData {
  return plain({
    id: c.id,
    title: c.title,
    machine: c.machine,
    startedAt: c.startedAt,
    openedAt: c.openedAt,
    // Local file ids only — never the files themselves.
    fileIds: c.fileIds,
    messageCount: c.messages.length,
  })
}

export const profileDoc = (profile: Profile, access: Access, at: number): DocumentData =>
  plain({ ...profile, access, clientUpdatedAt: at })

export const settingsDoc = (s: SyncedSettings, at: number): DocumentData => plain({ ...s, clientUpdatedAt: at })

/* ------------------------------------------------------------ read */

const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined)
const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d)
const bool = (v: unknown, d: boolean): boolean => (typeof v === 'boolean' ? v : d)

function readProfile(d: DocumentData): RemoteProfile {
  const profile: Partial<Profile> = {}
  for (const k of ['name', 'age', 'profession', 'experience', 'site'] as const) {
    const v = str(d[k])
    if (v !== undefined) profile[k] = v
  }
  const a = d.access as Partial<Access> | undefined
  const access = a && typeof a === 'object'
    ? { identity: bool(a.identity, true), experience: bool(a.experience, true), age: bool(a.age, false), history: bool(a.history, true) }
    : undefined
  return { profile, access, clientUpdatedAt: num(d.clientUpdatedAt) }
}

function readSettings(d: DocumentData): RemoteSettings {
  return {
    settings: {
      theme: d.theme === 'light' ? 'light' : 'dark',
      reduceMotion: bool(d.reduceMotion, false),
      webSearch: bool(d.webSearch, true),
      onboarded: bool(d.onboarded, false),
    },
    clientUpdatedAt: num(d.clientUpdatedAt),
  }
}

function readMessage(id: string, d: DocumentData): Message | null {
  if (d.role !== 'user' && d.role !== 'assistant') return null
  // Stored by messageDoc() from a local Message, so the rest of the shape
  // is ours; only the fields every renderer relies on are checked here.
  // `updatedAt` is the server's bookkeeping, not part of an Orion message.
  const { updatedAt: _server, ...rest } = d
  void _server
  return { ...(rest as Omit<Message, 'id'>), id, at: num(d.at), mode: d.mode === 'live' ? 'live' : 'normal' }
}

/** Everything this user has in the cloud. One read per document. */
export async function fetchAll(uid: string): Promise<RemoteSnapshot> {
  const db = firestore()
  const [p, s, convos] = await Promise.all([
    getDoc(doc(db, paths.profile(uid))),
    getDoc(doc(db, paths.settings(uid))),
    getDocs(collection(db, `users/${uid}/conversations`)),
  ])
  const conversations = await Promise.all(convos.docs.map(async (c): Promise<Conversation> => {
    const d = c.data()
    const msgs = await getDocs(collection(db, `users/${uid}/conversations/${c.id}/messages`))
    const messages = msgs.docs
      .map((m) => readMessage(m.id, m.data()))
      .filter((m): m is Message => m !== null)
      .sort((a, b) => a.at - b.at)
    return {
      id: c.id,
      title: str(d.title) ?? 'Conversation',
      machine: str(d.machine),
      startedAt: num(d.startedAt, messages[0]?.at ?? Date.now()),
      openedAt: num(d.openedAt, messages[messages.length - 1]?.at ?? Date.now()),
      fileIds: Array.isArray(d.fileIds) ? d.fileIds.filter((x): x is string => typeof x === 'string') : [],
      messages,
    }
  }))
  return {
    profile: p.exists() ? readProfile(p.data()) : null,
    settings: s.exists() ? readSettings(s.data()) : null,
    conversations,
  }
}

/* ------------------------------------------------------------ write */

export type Write =
  | { kind: 'set'; path: string; data: DocumentData }
  | { kind: 'delete'; path: string }

/**
 * Apply writes in batches (Firestore allows 500 operations per batch).
 * Every `set` merges and stamps `updatedAt` with the server's clock.
 */
export async function commit(writes: Write[], db: Firestore = firestore()): Promise<void> {
  for (let i = 0; i < writes.length; i += 450) {
    const batch = writeBatch(db)
    for (const w of writes.slice(i, i + 450)) {
      const ref = doc(db, w.path)
      if (w.kind === 'set') batch.set(ref, { ...w.data, updatedAt: serverTimestamp() }, { merge: true })
      else batch.delete(ref)
    }
    await batch.commit()
  }
}

/** Every document a conversation owns, for deleting it from the cloud. */
export async function conversationDeletes(uid: string, cid: string): Promise<Write[]> {
  const msgs = await getDocs(collection(firestore(), `users/${uid}/conversations/${cid}/messages`))
  return [
    ...msgs.docs.map((m): Write => ({ kind: 'delete', path: paths.message(uid, cid, m.id) })),
    { kind: 'delete', path: paths.conversation(uid, cid) },
  ]
}
