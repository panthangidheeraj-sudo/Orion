import { useMemo, useState } from 'react'
import { Icon } from '../ui/Icon'
import { Cap, Chip } from '../ui/bits'
import { useStore } from '../app/store'

/** Stand-in page content. A real build renders the indexed PDF here. */
const PAGE = {
  chapter: '6 · Bearings and lubrication',
  title: '6.4 Bearing condition limits',
  paras: [
    'Vibration severity shall be assessed in accordance with ISO 10816-3 for machines of group 2 mounted rigidly. Readings are taken axially and radially at the drive-end housing with the machine at rated load and stable temperature.',
    'Above 7.1 mm/s RMS the bearing has reached the replacement threshold and the machine shall not be returned to continuous service. End-bell bolts are retightened to 48 Nm ± 4 Nm in a diagonal sequence after any bearing work.',
    'Grease quantity for frame 132M is 18 g at intervals of 4,000 operating hours, reduced to 2,000 hours where the ambient temperature exceeds 40 °C.',
  ],
}

export function DocViewer() {
  const { files, openDocId, go } = useStore()
  const doc = useMemo(
    () => files.find((f) => f.id === openDocId) ?? files.find((f) => f.kind === 'pdf') ?? null,
    [files, openDocId],
  )
  const total = doc?.pages ?? 1
  const [page, setPage] = useState(Math.min(42, total))
  const [zoom, setZoom] = useState(100)

  if (!doc) {
    return (
      <section className="panel sheet-page">
        <div className="empty" style={{ padding: 60 }}>
          <Icon name="book" size={34} stroke="var(--vf-text-2)" width={1.4} />
          <h2 style={{ fontSize: 22 }}>No document open</h2>
          <p>Add a manual on the Files page and VisionField will cite it by page number.</p>
          <button type="button" className="btn primary" onClick={() => go('files')}>Open files</button>
        </div>
      </section>
    )
  }

  const thumbs = Array.from({ length: 5 }, (_, i) => page - 2 + i).filter((n) => n >= 1 && n <= total)

  return (
    <>
      <div className="panel" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '0 16px', height: 60, marginTop: 16, flexWrap: 'wrap' }}>
        <Icon name="book" size={20} stroke="var(--vf-text)" width={1.7} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
          <b style={{ fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{doc.name}</b>
          <Cap>Indexed on-device · {total} pages</Cap>
        </div>
        <span style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button type="button" className="ibtn sm" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            <Icon name="chevL" size={17} width={1.9} />
          </button>
          <span className="mono" style={{ padding: '0 10px', height: 36, display: 'inline-flex', alignItems: 'center', background: 'var(--vf-inset)', border: '1px solid var(--vf-border)', borderRadius: 10, fontSize: 12 }}>
            {page}<span style={{ color: 'var(--vf-muted)' }}>&nbsp;/ {total}</span>
          </span>
          <button type="button" className="ibtn sm" aria-label="Next page" disabled={page >= total} onClick={() => setPage((p) => Math.min(total, p + 1))}>
            <Icon name="chevR" size={17} width={1.9} />
          </button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button type="button" className="ibtn sm" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(70, z - 10))}>
            <Icon name="zoomout" size={17} />
          </button>
          <span className="mono" style={{ fontSize: 11, minWidth: 38, textAlign: 'center' }}>{zoom}%</span>
          <button type="button" className="ibtn sm" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(160, z + 10))}>
            <Icon name="zoomin" size={17} />
          </button>
        </div>
        <button type="button" className="ibtn sm" aria-label="Close document viewer" onClick={() => go('files')}>
          <Icon name="x" size={17} width={1.9} />
        </button>
      </div>

      <div className="doc">
        <div className="doc-rail">
          {thumbs.map((n) => (
            <button key={n} type="button" aria-label={`Page ${n}${n === page ? ' (current)' : ''}`} onClick={() => setPage(n)}>
              <span className={n === page ? 'doc-thumb on' : 'doc-thumb'}>
                <i style={{ width: '70%', height: 6, marginBottom: 5 }} />
                <i /><i style={{ width: '88%' }} /><i style={{ width: '60%', marginBottom: 10 }} />
                <i style={{ height: 36, background: n === page ? 'var(--vf-border-strong)' : 'var(--vf-track)' }} />
              </span>
              <span className="mono" style={{ fontSize: 10, color: n === page ? 'var(--vf-text)' : 'var(--vf-muted)' }}>{n}</span>
            </button>
          ))}
        </div>

        <div className="doc-page">
          <article className="paper" style={{ fontSize: `${zoom}%` }}>
            <Cap style={{ marginBottom: 26 }}>{PAGE.chapter}</Cap>
            <h3>{PAGE.title}</h3>
            <p>{PAGE.paras[0]}</p>
            <div style={{ margin: '18px 0', padding: 16, background: 'var(--vf-inset)', border: '1px solid var(--vf-border)', borderRadius: 10 }}>
              <Cap style={{ marginBottom: 10 }}>Table 6-3 · Severity limits</Cap>
              <div className="mono" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: '8px 14px', fontSize: 11.5 }}>
                <span style={{ color: 'var(--vf-muted)' }}>Zone A</span>
                <span style={{ color: 'var(--vf-muted)' }}>Zone B</span>
                <span style={{ color: 'var(--vf-muted)' }}>Zone C</span>
                <span>&lt; 2.3 mm/s</span>
                <span>2.3 – 4.5 mm/s</span>
                <span><mark>4.5 – 7.1 mm/s</mark></span>
              </div>
            </div>
            <p>{PAGE.paras[1]}</p>
            <p style={{ marginBottom: 0 }}>{PAGE.paras[2]}</p>
          </article>
        </div>

        <aside className="doc-aside">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon name="sparks" size={15} stroke="var(--vf-text)" width={1.8} />
            <Cap>Why this page is open</Cap>
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--vf-text-2)' }}>
            VisionField opened page {page} to answer <em>“is 6.8 mm/s within limits for Motor #04?”</em>
          </p>
          <div style={{ padding: '12px 14px', background: 'var(--vf-track)', border: '1px solid var(--vf-border-strong)', borderRadius: 12 }}>
            <Cap style={{ marginBottom: 6 }}>Matched passage</Cap>
            <div style={{ fontSize: 13, lineHeight: 1.6 }}>
              “Above 7.1 mm/s RMS the bearing has reached the replacement threshold.”
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Chip icon="grid" size="sm">Table 6-3 · p.42</Chip>
            <Chip icon="ruler" size="sm">Bolt torque · p.44</Chip>
          </div>
          <span style={{ flex: 1 }} />
          <button type="button" className="btn primary wide" onClick={() => go('chat')}>
            <Icon name="sparks" size={17} stroke="var(--vf-on-invert)" />
            Use this page in the answer
          </button>
        </aside>
      </div>
    </>
  )
}
