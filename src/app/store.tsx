import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { Access, Conversation, Message, Mode, Prefs, Profile, Route, Step, VFile } from './types'
import { answer, planSteps, type AskContext } from './assistant'
import * as api from './api'
import { DEFAULT_ACCESS, DEFAULT_PREFS, DEFAULT_PROFILE, SEED_CONVERSATIONS, SEED_FILES } from './seed'
import { load, loadList, save, uid } from './util'

const K = {
  convos: 'vf.conversations',
  files: 'vf.files',
  profile: 'vf.profile',
  access: 'vf.access',
  prefs: 'vf.prefs',
}

export interface Toast { id: string; title: string; detail?: string }

/** The assistant's visible work trail while it thinks. */
export interface Asking { conversationId: string; steps: Step[]; index: number }

interface Store {
  route: Route
  go: (r: Route, opts?: { conversation?: string; doc?: string }) => void

  conversations: Conversation[]
  activeId: string | null
  active: Conversation | null
  openConversation: (id: string) => void
  newConversation: (title?: string) => string
  renameConversation: (id: string, title: string) => void
  deleteConversation: (id: string) => void
  addMessage: (conversationId: string, msg: Message) => void

  files: VFile[]
  addFiles: (list: FileList | File[]) => VFile[]
  removeFile: (id: string) => void
  attachToActive: (ids: string[]) => void
  openDocId: string | null

  profile: Profile
  setProfile: (p: Profile) => void
  access: Access
  setAccess: (a: Access) => void
  prefs: Prefs
  setPrefs: (p: Prefs) => void

  asking: Asking | null
  ask: (text: string, mode: Mode, attachments?: string[]) => string
  stopAsking: () => void

  /** What the local backend reports about itself, or offline. */
  backend: api.BackendInfo
  refreshBackend: () => void

  toasts: Toast[]
  toast: (title: string, detail?: string) => void
  dismiss: (id: string) => void
}

const Ctx = createContext<Store | null>(null)

function kindOf(name: string, type: string): VFile['kind'] {
  if (type.startsWith('image/')) return 'image'
  if (type === 'application/pdf' || /\.pdf$/i.test(name)) return 'pdf'
  if (type.startsWith('text/') || /\.(txt|md|csv)$/i.test(name)) return 'text'
  return 'other'
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [prefs, setPrefsState] = useState<Prefs>(() => {
    // First run takes its cue from the operating system; after that the in-app
    // switch is authoritative, so motion can be turned back ON here even when
    // the OS asks for less of it elsewhere.
    const stored = localStorage.getItem(K.prefs)
    if (stored) return load(K.prefs, DEFAULT_PREFS)
    let osReduce = false
    try { osReduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch { /* no matchMedia */ }
    return { ...DEFAULT_PREFS, reduceMotion: osReduce }
  })
  const [route, setRoute] = useState<Route>(() => (load(K.prefs, DEFAULT_PREFS).onboarded ? 'home' : 'onboarding'))
  const [conversations, setConversations] = useState<Conversation[]>(() => loadList(K.convos, SEED_CONVERSATIONS))
  const [files, setFiles] = useState<VFile[]>(() => loadList(K.files, SEED_FILES))
  const [activeId, setActiveIdState] = useState<string | null>(null)
  // State updates are not visible until the next render, but `ask` can be
  // called in the same tick as `newConversation()` — Home does exactly that.
  // Without a synchronous mirror, `ask` reads a stale null and opens a second,
  // empty conversation alongside the one just created.
  const activeIdRef = useRef<string | null>(null)
  const setActiveId = useCallback((next: string | null |
    ((cur: string | null) => string | null)) => {
    setActiveIdState((cur) => {
      const resolved = typeof next === 'function' ? next(cur) : next
      activeIdRef.current = resolved
      return resolved
    })
    if (typeof next !== 'function') activeIdRef.current = next
  }, [])
  const [openDocId, setOpenDocId] = useState<string | null>(null)
  const [profile, setProfileState] = useState<Profile>(() => load(K.profile, DEFAULT_PROFILE))
  const [access, setAccessState] = useState<Access>(() => load(K.access, DEFAULT_ACCESS))
  const [toasts, setToasts] = useState<Toast[]>([])
  const [asking, setAsking] = useState<Asking | null>(null)
  const [backend, setBackend] = useState<api.BackendInfo>(() => api.lastKnownBackend())
  const backendRef = useRef(backend)
  backendRef.current = backend
  /** Conversation id on the backend, keyed by the local conversation id. */
  const remoteConvo = useRef<Record<string, string>>({})
  const inFlight = useRef<AbortController | null>(null)
  const timers = useRef<number[]>([])
  const askTimers = useRef<number[]>([])
  const latest = useRef({ conversations, files, prefs, profile })
  latest.current = { conversations, files, prefs, profile }

  useEffect(() => save(K.convos, conversations), [conversations])
  useEffect(() => save(K.files, files.map((f) => ({ ...f, url: undefined }))), [files])
  useEffect(() => save(K.profile, profile), [profile])
  useEffect(() => save(K.access, access), [access])
  useEffect(() => save(K.prefs, prefs), [prefs])

  useEffect(() => {
    document.documentElement.classList.toggle('reduce-motion', prefs.reduceMotion)
  }, [prefs.reduceMotion])

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), [])

  const refreshBackend = useCallback(() => {
    void api.probe().then(setBackend)
  }, [])

  // The backend is optional. If it is not running the app still works, on the
  // local demo responder, and says so rather than pretending.
  useEffect(() => {
    refreshBackend()
    const onFocus = () => refreshBackend()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [refreshBackend])

  const go = useCallback<Store['go']>((r, opts) => {
    if (opts?.conversation) setActiveId(opts.conversation)
    if (opts?.doc) setOpenDocId(opts.doc)
    setRoute(r)
  }, [])

  const toast = useCallback((title: string, detail?: string) => {
    const t = { id: uid('t'), title, detail }
    setToasts((prev) => [...prev, t])
    const h = window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== t.id)), 6000)
    timers.current.push(h)
  }, [])

  const dismiss = useCallback((id: string) => setToasts((p) => p.filter((t) => t.id !== id)), [])

  const openConversation = useCallback((id: string) => {
    setActiveId(id)
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, openedAt: Date.now() } : c)))
  }, [])

  const newConversation = useCallback((title = 'New conversation') => {
    const id = uid('c')
    const c: Conversation = {
      id,
      title,
      startedAt: Date.now(),
      openedAt: Date.now(),
      messages: [],
      fileIds: [],
    }
    setConversations((prev) => [c, ...prev])
    setActiveId(id)
    return id
  }, [])

  const renameConversation = useCallback((id: string, title: string) => {
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)))
  }, [])

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id))
    setActiveId((cur) => (cur === id ? null : cur))
  }, [])

  const addMessage = useCallback((conversationId: string, msg: Message) => {
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== conversationId) return c
        const next: Conversation = { ...c, messages: [...c.messages, msg], openedAt: Date.now() }
        if (msg.role === 'user' && c.messages.length === 0 && msg.text) {
          next.title = msg.text.length > 52 ? `${msg.text.slice(0, 52).trimEnd()}…` : msg.text
        }
        return next
      }),
    )
  }, [])

  /** Ingest real files and walk them through the processing states. */
  const addFiles = useCallback<Store['addFiles']>((list) => {
    const incoming = Array.from(list as ArrayLike<File>)
    const made: VFile[] = incoming.map((f) => {
      const kind = kindOf(f.name, f.type)
      const supported = kind !== 'other'
      return {
        id: uid('f'),
        name: f.name,
        kind,
        size: f.size,
        state: supported ? 'uploading' : 'failed',
        progress: 0,
        addedAt: Date.now(),
        url: kind === 'image' ? URL.createObjectURL(f) : undefined,
        pages: kind === 'pdf' ? Math.max(1, Math.round(f.size / 90_000)) : undefined,
        note: supported ? undefined : 'Unsupported file type — export a PDF, PNG, JPG or TXT',
      }
    })
    setFiles((prev) => [...made, ...prev])

    const usable = made.filter((m) => m.state !== 'failed')

    if (backendRef.current.online) {
      // Real ingest: the backend extracts text, renders every page to an image
      // and indexes the chunks. The states below are what actually happened.
      usable.forEach((m, i) => {
        const source = incoming[made.indexOf(m)]
        const patch = (p: Partial<VFile>) =>
          setFiles((prev) => prev.map((f) => (f.id === m.id ? { ...f, ...p } : f)))
        patch({ state: 'uploading', progress: 25 })
        void api
          .uploadDocument(source)
          .then((doc) => {
            patch({
              state: doc.indexed ? 'ready' : 'failed',
              progress: 100,
              pages: doc.pageCount,
              docId: doc.documentId,
              indexedChunks: doc.chunks,
              note: doc.indexed
                ? undefined
                : 'Stored and viewable, but no text could be extracted — it may be a scan '
                  + 'that needs OCR',
            })
          })
          .catch((err: unknown) => {
            patch({
              state: 'failed',
              progress: 100,
              note: err instanceof Error ? err.message : 'The local backend refused this file',
            })
          })
        void i
      })
      return made
    }

    // No backend: walk the same states on a timer so the UI is exercisable.
    usable.forEach((m, i) => {
      const bump = (state: VFile['state'], progress: number, delay: number) => {
        const h = window.setTimeout(() => {
          setFiles((prev) => prev.map((f) => (f.id === m.id ? { ...f, state, progress } : f)))
        }, delay + i * 120)
        timers.current.push(h)
      }
      bump('uploading', 60, 300)
      bump(m.kind === 'pdf' ? 'reading' : 'indexing', 80, 900)
      if (m.kind === 'pdf') bump('indexing', 92, 1600)
      bump('ready', 100, 2400)
    })
    return made
  }, [])

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => {
      const f = prev.find((x) => x.id === id)
      if (f?.url) URL.revokeObjectURL(f.url)
      return prev.filter((x) => x.id !== id)
    })
    setConversations((prev) => prev.map((c) => ({ ...c, fileIds: c.fileIds.filter((x) => x !== id) })))
  }, [])

  const attachToActive = useCallback((ids: string[]) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeId ? { ...c, fileIds: Array.from(new Set([...c.fileIds, ...ids])) } : c,
      ),
    )
  }, [activeId])

  const stopAsking = useCallback(() => {
    askTimers.current.forEach((t) => window.clearTimeout(t))
    askTimers.current = []
    inFlight.current?.abort()
    inFlight.current = null
    setAsking(null)
  }, [])

  /**
   * One question, start to finish: record the user turn, walk the work trail,
   * then append the structured answer. Chat and Live both call this, which is
   * what keeps the two modes a single conversation.
   */
  const ask = useCallback<Store['ask']>((text, mode, attachments = []) => {
    const convoId = activeIdRef.current ?? activeId ?? newConversation()
    const snapshot = latest.current
    const convo = snapshot.conversations.find((c) => c.id === convoId)

    // Files sent with a message belong to that conversation, so they stay in
    // its Files dock and can be referred to later. Doing it here rather than
    // at the call site also avoids the stale-`activeId` trap: Home attaches
    // and sends in the same tick, before `attachToActive` would have seen the
    // new conversation.
    if (attachments.length) {
      setConversations((prev) => prev.map((c) => (
        c.id === convoId
          ? { ...c, fileIds: Array.from(new Set([...c.fileIds, ...attachments])) }
          : c
      )))
    }

    addMessage(convoId, {
      id: uid('u'),
      role: 'user',
      at: Date.now(),
      mode,
      text,
      attachments: attachments.length ? attachments : undefined,
    })

    const ctx: AskContext = {
      files: snapshot.files.filter((f) => f.state === 'ready' || convo?.fileIds.includes(f.id)),
      hasHistory: (convo?.messages.length ?? 0) > 1,
      machine: convo?.machine,
      webSearch: snapshot.prefs.webSearch,
      mode,
      profession: snapshot.profile.profession || undefined,
      hasAttachments: attachments.length > 0,
    }

    askTimers.current.forEach((t) => window.clearTimeout(t))
    askTimers.current = []
    inFlight.current?.abort()

    if (backendRef.current.online) {
      // The backend owns the loop: it decides which tools to run, gathers the
      // evidence, reasons over it and applies the safety review. The trail
      // below is what really happened, not a simulation of it.
      const controller = new AbortController()
      inFlight.current = controller
      setAsking({
        conversationId: convoId,
        steps: [{ icon: 'spark', label: 'Working on device', ms: 0 }],
        index: 0,
      })

      void api
        .ask(text, {
          conversationId: remoteConvo.current[convoId],
          imageIds: [],
          mode,
          web: snapshot.prefs.webSearch,
          profession: snapshot.profile.profession || undefined,
          experience: snapshot.profile.experience || undefined,
          signal: controller.signal,
          onStep: (steps) =>
            setAsking({ conversationId: convoId, steps, index: steps.length }),
        })
        .then((res) => {
          remoteConvo.current[convoId] = res.conversationId
          setAsking(null)
          inFlight.current = null
          addMessage(convoId, {
            ...res.message,
            attachments: attachments.length ? attachments : undefined,
          })
          if (res.degradedTools.length) {
            toast(
              'Some senses are unavailable',
              `${res.degradedTools.join(', ')} — the answer says what could not be confirmed.`,
            )
          }
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return
          inFlight.current = null
          setAsking(null)
          setBackend({ online: false, reason: err instanceof Error ? err.message : 'unreachable' })
          toast(
            'Lost the local backend',
            'Falling back to the offline demo responder. Ask again once it is running.',
          )
          addMessage(convoId, {
            ...answer(text, ctx),
            attachments: attachments.length ? attachments : undefined,
          })
        })
      return convoId
    }

    const steps = planSteps(text, ctx)
    // A conversational turn plans no steps, so there is no work trail to show.
    if (steps.length) setAsking({ conversationId: convoId, steps, index: 0 })

    let elapsed = 0
    steps.forEach((_, i) => {
      elapsed += steps[i].ms
      askTimers.current.push(
        window.setTimeout(() => setAsking({ conversationId: convoId, steps, index: i + 1 }), elapsed),
      )
    })
    askTimers.current.push(
      window.setTimeout(() => {
        setAsking(null)
        addMessage(convoId, {
          ...answer(text, ctx),
          attachments: attachments.length ? attachments : undefined,
        })
      }, elapsed + 220),
    )
    return convoId
  }, [activeId, addMessage, newConversation, toast])

  useEffect(() => () => askTimers.current.forEach((t) => window.clearTimeout(t)), [])

  const active = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? null,
    [conversations, activeId],
  )

  const value: Store = {
    route, go,
    conversations, activeId, active,
    openConversation, newConversation, renameConversation, deleteConversation, addMessage,
    files, addFiles, removeFile, attachToActive, openDocId,
    asking, ask, stopAsking,
    backend, refreshBackend,
    profile, setProfile: setProfileState,
    access, setAccess: setAccessState,
    prefs, setPrefs: setPrefsState,
    toasts, toast, dismiss,
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('useStore must be used inside <StoreProvider>')
  return s
}
