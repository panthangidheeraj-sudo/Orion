import { useEffect, useRef, useState } from 'react'
import { Composer } from '../ui/Composer'
import { AssistantMessage, UserMessage, WorkTrail } from '../ui/Message'
import { FilesDock } from '../ui/FilesDock'
import { Icon } from '../ui/Icon'
import { useStore } from '../app/store'
import { useAsk } from '../app/useAsk'
import type { Mode } from '../app/types'

export function Chat() {
  const {
    conversations, active, activeId, openConversation, newConversation,
    files, addFiles, attachToActive, go, toast,
  } = useStore()
  const { ask, asking, stop } = useAsk()
  const [mode, setMode] = useState<Mode>('normal')
  // Files staged for the NEXT message, not the conversation's whole vault.
  // Deriving this from `active.fileIds` meant a file stayed pinned above the
  // composer for the rest of the conversation, long after it had been sent.
  const [pending, setPending] = useState<string[]>([])
  const scroll = useRef<HTMLDivElement | null>(null)
  const picker = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!activeId && conversations.length) openConversation(conversations[0].id)
  }, [activeId, conversations, openConversation])

  useEffect(() => {
    const el = scroll.current
    if (el) el.scrollTop = el.scrollHeight
  }, [active?.messages.length, asking?.index])

  // Two different lists, and conflating them is what pinned a sent file above
  // the composer forever:
  //   vaultFiles — everything this conversation can draw on, shown in the dock
  //   staged     — what will ride along with the NEXT message, shown as chips
  const vaultFiles = files.filter((f) => active?.fileIds.includes(f.id))
  const staged = files.filter((f) => pending.includes(f.id))

  const send = (text: string) => {
    ask(text, 'normal', pending)
    setPending([])
  }

  const ingest = (list: FileList) => {
    const made = addFiles(list)
    const ids = made.map((f) => f.id)
    // The file joins the conversation's vault (so it stays searchable and
    // shows in the Files dock) and is staged for the next message.
    attachToActive(ids)
    setPending((p) => [...p, ...ids])
    toast(`${made.length} file${made.length > 1 ? 's' : ''} added`, 'Indexing runs on this device.')
  }

  return (
    <div className="chat">
      <input
        ref={picker} type="file" multiple hidden
        accept="image/*,application/pdf,text/plain,.md,.csv"
        onChange={(e) => { if (e.target.files?.length) ingest(e.target.files); e.target.value = '' }}
      />

      <div className="thread">
        <FilesDock
          files={vaultFiles}
          onOpen={(f) => go('doc', { doc: f.id })}
          onManage={() => go('files')}
          onReport={() => go('reports')}
          onAdd={() => picker.current?.click()}
        />

        <div className="thread-scroll" ref={scroll}>
          {(!active || active.messages.length === 0) && !asking && (
            <div className="empty">
              <Icon name="sparks" size={40} stroke="var(--vf-text-2)" width={1.4} />
              <h2>Start with what you can see</h2>
              <p>Describe the symptom, attach a photo, or open the camera. Nothing is sent off this device.</p>
              <div className="quick">
                <button type="button" onClick={() => { newConversation('Live inspection'); go('live') }}>
                  <span className="ic"><Icon name="cam" size={17} stroke="var(--vf-text)" /></span>
                  <span className="tx">
                    <b>Show me the equipment</b>
                    <span>Switch to Live Mode and inspect with the camera</span>
                  </span>
                  <span style={{ flex: 1 }} />
                  <Icon name="chevR" size={16} stroke="var(--vf-muted)" />
                </button>
                <button type="button" onClick={() => picker.current?.click()}>
                  <span className="ic"><Icon name="file" size={17} stroke="var(--vf-text)" /></span>
                  <span className="tx">
                    <b>Attach a manual or photo</b>
                    <span>Indexed on-device, referenced with page numbers</span>
                  </span>
                  <span style={{ flex: 1 }} />
                  <Icon name="chevR" size={16} stroke="var(--vf-muted)" />
                </button>
              </div>
            </div>
          )}

          {active?.messages.map((m) =>
            m.role === 'user' ? (
              <UserMessage key={m.id} msg={m} files={files} />
            ) : (
              <AssistantMessage
                key={m.id}
                msg={m}
                onOpenDoc={() => go('doc')}
                onFollowUp={(t) => {
                  if (t === 'Open Live Mode' || t === 'Take the reading now') { go('live'); return }
                  if (t === 'Open the report') { go('reports'); return }
                  if (t === 'Attach a photo' || t === 'Attach a manual') { picker.current?.click(); return }
                  send(t)
                }}
              />
            ),
          )}

          {asking && asking.conversationId === activeId && (
            <WorkTrail steps={asking.steps} index={asking.index} />
          )}
        </div>

        <Composer
          narrow
          mode={mode}
          onMode={(m) => { setMode(m); if (m === 'live') go('live') }}
          onSend={send}
          busy={!!asking}
          onStop={stop}
          attached={staged}
          onAttach={ingest}
          onDetach={(id) => setPending((p) => p.filter((x) => x !== id))}
          placeholder="Describe the symptom, or attach a photo"
        />
      </div>
    </div>
  )
}
