import { useEffect, useState, useRef } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import 'chart.js/auto'
import './App.css'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const apiUrl = (path) => `${API_BASE_URL}${path}`

function Nav({ current, onChange, collapsed, onToggleCollapse }) {
  const tabs = ['Health', 'Alerts', 'Single Eval', 'Human Eval', 'Batch Eval', 'Whole Eval']
  const icons = { 'Health': '🏠', 'Alerts': '📡', 'Single Eval': '🧪', 'Human Eval': '👤', 'Batch Eval': '📚', 'Whole Eval': '🧾' }
  return (
    <aside className="sidebar">
      <div className="sidebar-tools">
        <button className="collapse-btn" onClick={onToggleCollapse} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          <span className="nav-icon" aria-hidden>{collapsed ? '▶' : '◀'}</span>
          <span className="nav-label">{collapsed ? 'Expand' : 'Collapse'}</span>
        </button>
      </div>
      <nav className="nav-vert">
        {tabs.map(t => (
          <button key={t} className={current === t ? 'active' : ''} onClick={() => onChange(t)}>
            <span className="nav-icon" aria-hidden>{icons[t] || '•'}</span>
            <span className="nav-label">{t}</span>
          </button>
        ))}
      </nav>
    </aside>
  )
}

function Health({ onNavigate }) {
  const [health, setHealth] = useState(null)
  const refresh = async () => {
    try {
      const r = await fetch(apiUrl('/health'))
      if (!r.ok) {
        setHealth({
          status: 'backend_unreachable',
          httpStatus: r.status,
          apiBase: API_BASE_URL || window.location.origin,
        })
        return
      }
      const data = await r.json()
      setHealth({ ...data, apiBase: API_BASE_URL || window.location.origin })
    } catch {
      const isHostedWithoutApi = !API_BASE_URL && /web\.app$|firebaseapp\.com$/.test(window.location.hostname)
      setHealth({
        status: isHostedWithoutApi ? 'backend_not_configured' : 'error',
        apiBase: API_BASE_URL || window.location.origin,
      })
    }
  }
  useEffect(() => {
    refresh()
  }, [])
  const rel = (iso) => {
    try {
      const t = new Date(iso).getTime()
      const d = Math.max(0, Date.now() - t)
      const s = Math.floor(d / 1000)
      if (s < 60) return `${s}s ago`
      const m = Math.floor(s / 60)
      if (m < 60) return `${m}m ago`
      const h = Math.floor(m / 60)
      if (h < 24) return `${h}h ago`
      const days = Math.floor(h / 24)
      return `${days}d ago`
    } catch {
      return ''
    }
  }
  const MenuCard = ({ icon, title, desc, to }) => (
    <div
      className="menu-card"
      role="button"
      tabIndex={0}
      onClick={() => onNavigate && onNavigate(to)}
      onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && onNavigate) onNavigate(to) }}
    >
      <div className="menu-icon" aria-hidden>{icon}</div>
      <div style={{ flex: 1 }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <p style={{ margin: '6px 0 0 0', opacity: 0.85 }}>{desc}</p>
      </div>
    </div>
  )
  return (
    <>
      <div className="card" style={{ marginTop: 12 }}>
        <h2>Welcome</h2>
        <p style={{ opacity: 0.85 }}>Choose an action below to get started.</p>
        <div className="menu-grid" style={{ marginTop: 12 }}>
          <MenuCard icon="📡" title="Alerts" desc="Browse and filter recent alerts." to="Alerts" />
          <MenuCard icon="🧪" title="Single Eval" desc="Translate and evaluate a single message." to="Single Eval" />
          <MenuCard icon="📚" title="Batch Eval" desc="Segmented batch translation and evaluation." to="Batch Eval" />
          <MenuCard icon="🧾" title="Whole Eval" desc="Whole-message translation and evaluation." to="Whole Eval" />
          <MenuCard icon="👤" title="Human Eval" desc="Manually score translations across factors." to="Human Eval" />
        </div>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <h2>API Health</h2>
        {!health && <p>Checking…</p>}
        {health && (
          <div style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{
                padding: '4px 10px',
                borderRadius: 999,
                border: '1px solid',
                borderColor: health.status === 'ok' ? 'rgba(32,150,72,0.5)' : 'rgba(176,0,0,0.5)',
                background: health.status === 'ok' ? 'rgba(32,150,72,0.15)' : 'rgba(176,0,0,0.12)'
              }}>{health.status === 'ok' ? 'OK' : 'Error'}</span>
              <button onClick={refresh}>Refresh</button>
            </div>
            {health.status !== 'ok' && (
              <div style={{ opacity: 0.9 }}>
                {health.status === 'backend_not_configured'
                  ? 'Backend URL is not configured for this hosted frontend. Set VITE_API_BASE_URL to your live API and redeploy.'
                  : 'Backend is unreachable from this frontend.'}
              </div>
            )}
            {health.apiBase && (
              <div style={{ opacity: 0.75 }}>API base: {health.apiBase}</div>
            )}
            {health.time && (
              <div style={{ opacity: 0.9 }}>
                Server time: {new Date(health.time).toLocaleString()} <span style={{ opacity: 0.7 }}>({rel(health.time)})</span>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function AlertsTable({ alerts = [], onSelect, selectedId, pageSizeOptions = [10, 25, 50, 100], initialPageSize = 25 }) {
  const [sortKey, setSortKey] = useState('timestamp')
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(initialPageSize)

  const headers = [
    { key: 'alert_id', label: 'ID' },
    { key: 'category', label: 'Category' },
    { key: 'timestamp', label: 'Time' },
    { key: 'area', label: 'Area' },
    { key: 'source_text', label: 'Text' },
  ]

  const sorted = [...alerts].sort((a, b) => {
    const va = a[sortKey] || ''
    const vb = b[sortKey] || ''
    if (sortKey === 'timestamp') {
      const ta = va ? new Date(va).getTime() : 0
      const tb = vb ? new Date(vb).getTime() : 0
      return sortDir === 'asc' ? ta - tb : tb - ta
    }
    const sa = String(va).toLowerCase()
    const sb = String(vb).toLowerCase()
    if (sa < sb) return sortDir === 'asc' ? -1 : 1
    if (sa > sb) return sortDir === 'asc' ? 1 : -1
    return 0
  })
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const safePage = Math.min(page, totalPages - 1)
  const pageItems = sorted.slice(safePage * pageSize, safePage * pageSize + pageSize)

  const clickHeader = (key) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key); setSortDir('asc')
    }
    setPage(0)
  }

  const exportCsv = () => {
    const rows = alerts.map(a => ({
      id: a.alert_id,
      category: a.category,
      certainty: a.certainty_level || 'unknown',
      time: a.timestamp ? new Date(a.timestamp).toISOString() : '',
      area: a.area || a.state || '',
      text: (a.source_text || '').replace(/\n/g, ' '),
    }))
    const header = ['id','category','certainty','time','area','text']
    const lines = [header.join(','), ...rows.map(r => header.map(h => {
      const v = String(r[h] || '')
      const escaped = '"' + v.replace(/"/g, '""') + '"'
      return escaped
    }).join(','))]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `alerts_${new Date().toISOString().slice(0,19)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <label>Page Size
          <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0) }}>
            {pageSizeOptions.map(v => (
              <option key={String(v)} value={v}>{v}</option>
            ))}
          </select>
        </label>
        <button onClick={exportCsv}>Export CSV</button>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={safePage === 0}>Prev</button>
          <span>Page {safePage + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={safePage >= totalPages - 1}>Next</button>
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {headers.map(h => (
                <th key={h.key} onClick={() => clickHeader(h.key)} style={{ cursor: 'pointer', textAlign: 'left', borderBottom: '1px solid var(--border)', padding: 8 }}>
                  {h.label}{sortKey === h.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageItems.map(a => (
              <tr key={a.alert_id} style={{ background: selectedId === a.alert_id ? 'rgba(70,100,255,0.08)' : 'transparent' }} onClick={() => onSelect && onSelect(a)}>
                <td style={{ borderBottom: '1px solid var(--border)', padding: 8 }}>{a.alert_id}</td>
                <td style={{ borderBottom: '1px solid var(--border)', padding: 8 }}>{a.category} ({a.certainty_level || 'unknown'})</td>
                <td style={{ borderBottom: '1px solid var(--border)', padding: 8 }}>{a.timestamp ? new Date(a.timestamp).toLocaleString() : ''}</td>
                <td style={{ borderBottom: '1px solid var(--border)', padding: 8 }}>{a.area || a.state}</td>
                <td style={{ borderBottom: '1px solid var(--border)', padding: 8 }}>{(a.source_text || '').slice(0, 120)}{(a.source_text || '').length > 120 ? '…' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AlertSummary({ alert }) {
  if (!alert) return null
  return (
    <div className="card" style={{ padding: 8 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div><strong>ID:</strong> {alert.alert_id}</div>
        <div><strong>Category:</strong> {alert.category}</div>
        <div><strong>Time:</strong> {alert.timestamp ? new Date(alert.timestamp).toLocaleString() : ''}</div>
        <div><strong>Area:</strong> {alert.area || alert.state || ''}</div>
      </div>
    </div>
  )
}

function Alerts() {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showViz, setShowViz] = useState(false)
  // Aggregations
  const counts = (arr, key) => arr.reduce((acc, a) => {
    const k = (a[key] || 'unknown')
    acc[k] = (acc[k] || 0) + 1
    return acc
  }, {})
  const [byCategory, setByCategory] = useState({})
  const [byCertainty, setByCertainty] = useState({})
  const [byUrgency, setByUrgency] = useState({})
  const [bySeverity, setBySeverity] = useState({})
  // Interactive filters
  const [filters, setFilters] = useState({
    category: [],
    certainty_level: [],
    urgency_level: [],
    severity_level: [],
    area: [],
    date: [],
  })
  const toggleFilter = (field, label) => {
    setFilters(f => {
      const cur = new Set(f[field] || [])
      if (cur.has(label)) cur.delete(label); else cur.add(label)
      return { ...f, [field]: Array.from(cur) }
    })
  }
  const clearFilters = () => setFilters({ category: [], certainty_level: [], urgency_level: [], severity_level: [], area: [], date: [] })
  const load = async () => {
    setLoading(true); setError(null)
    try {
      const params = new URLSearchParams({ daysBack: '7', state: 'CA' })
      const r = await fetch(apiUrl('/alerts?' + params.toString()))
      const data = await r.json()
      setAlerts(data)
      // Initial charts from full dataset; filtered charts recompute below in render
      setByCategory(counts(data, 'category'))
      setByCertainty(counts(data, 'certainty_level'))
      setByUrgency(counts(data, 'urgency_level'))
      setBySeverity(counts(data, 'severity_level'))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])
  const maxVal = (obj) => Object.values(obj).reduce((m, v) => Math.max(m, v || 0), 0)
  const BarChart = ({ data, title, field, selected = [], onToggle }) => {
    const labels = Object.keys(data || {})
    const values = labels.map(k => data[k] || 0)
    const total = values.reduce((a, b) => a + (b || 0), 0)
    const hasSel = Array.isArray(selected) && selected.length > 0
    const bg = labels.map(l => hasSel ? (selected.includes(l) ? 'rgba(70, 100, 255, 0.7)' : 'rgba(70, 100, 255, 0.18)') : 'rgba(70, 100, 255, 0.6)')
    const bd = labels.map(l => hasSel ? (selected.includes(l) ? 'rgba(70, 100, 255, 1)' : 'rgba(70, 100, 255, 0.3)') : 'rgba(70, 100, 255, 1)')
    const chartData = {
      labels,
      datasets: [{
        label: title || 'Count',
        data: values,
        backgroundColor: bg,
        borderColor: bd,
        borderWidth: 1,
      }]
    }
    const options = {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const val = Number(ctx.parsed.y || 0)
              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : '0.0'
              const lbl = ctx.label || ''
              return `${lbl}: ${val} (${pct}%)`
            }
          }
        }
      },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      onClick: (evt, elements, chart) => {
        if (!onToggle) return
        const el = elements && elements[0]
        if (!el) return
        const idx = el.index
        const label = labels[idx]
        onToggle(field, label)
      }
    }
    if (labels.length === 0) return <p>No data.</p>
    return <Bar data={chartData} options={options} />
  }
  // Derive filtered alerts and recompute distributions from filtered set
  const dateKey = (iso) => { try { return new Date(iso).toISOString().slice(0,10) } catch { return '' } }
  const filteredAlerts = alerts.filter(a => (
    (filters.category.length === 0 || filters.category.includes(a.category)) &&
    (filters.certainty_level.length === 0 || filters.certainty_level.includes(a.certainty_level || '')) &&
    (filters.urgency_level.length === 0 || filters.urgency_level.includes(a.urgency_level || '')) &&
    (filters.severity_level.length === 0 || filters.severity_level.includes(a.severity_level || '')) &&
    (filters.date.length === 0 || filters.date.includes(dateKey(a.timestamp))) &&
    (filters.area.length === 0 || (() => { const areas = (a.area || '').split(',').map(x => x.trim()).filter(Boolean); return areas.some(ar => filters.area.includes(ar)) })())
  ))
  const catDist = counts(filteredAlerts, 'category')
  const certDist = counts(filteredAlerts, 'certainty_level')
  const urgDist = counts(filteredAlerts, 'urgency_level')
  const sevDist = counts(filteredAlerts, 'severity_level')
  // Advanced visuals (moved from Analytics)
  const byDate = alerts.reduce((acc, a) => { const d = dateKey(a.timestamp); if (!d) return acc; acc[d] = (acc[d] || 0) + 1; return acc }, {})
  const dates = Object.keys(byDate).sort()
  const totalTrend = {
    labels: dates,
    datasets: [{ label: 'Alerts per day', data: dates.map(d => byDate[d] || 0), borderColor: 'rgba(70, 100, 255, 1)', backgroundColor: 'rgba(70, 100, 255, 0.25)', fill: true, tension: 0.2 }]
  }
  const categories = Array.from(new Set(alerts.map(a => a.category))).filter(Boolean)
  const colors = ['#4664ff','#00b894','#e17055','#fdcb6e','#6c5ce7','#00cec9','#0984e3','#d63031']
  const byDateCat = {}
  alerts.forEach(a => { const d = dateKey(a.timestamp); if (!d) return; const c = a.category || 'unknown'; byDateCat[d] = byDateCat[d] || {}; byDateCat[d][c] = (byDateCat[d][c] || 0) + 1 })
  const stackedData = {
    labels: dates,
    datasets: categories.map((c, i) => ({
      label: c,
      data: dates.map(d => (byDateCat[d]?.[c] || 0)),
      backgroundColor: colors[i % colors.length] + 'cc',
      borderColor: colors[i % colors.length],
      borderWidth: 1,
      stack: 'cat',
    }))
  }
  // CSV export (Batch Eval charts)
  const exportCsv = (name, header, rows) => {
    try {
      const lines = [header.join(','), ...rows.map(r => header.map(h => '"' + String(r[h] ?? '').replace(/"/g, '""') + '"').join(','))]
      const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${name}_${new Date().toISOString().slice(0,19)}.csv`
      document.body.appendChild(a)
      a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    } catch {}
  }
  const exportTrend = () => exportCsv('alerts_trend', ['date','count'], dates.map(d => ({ date: d, count: byDate[d] || 0 })))
  const exportStacked = () => {
    const rows = []
    dates.forEach(d => { categories.forEach(c => rows.push({ date: d, category: c, count: (byDateCat[d]?.[c] || 0) })) })
    exportCsv('alerts_by_category_daily', ['date','category','count'], rows)
  }
  
  return (
    <div className="card">
      <h2>Recent CA Alerts</h2>
      {loading && <p>Loading…</p>}
      {error && <p className="error">{error}</p>}
      <details className="collapse">
        <summary>Show advanced filters</summary>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
          <div className="card" style={{ padding: 12 }}>
            <h4>Filter by Category</h4>
            {Object.keys(byCategory).map(k => (
              <label key={'cat-cb-'+k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={filters.category.includes(k)} onChange={() => toggleFilter('category', k)} />
                {k}
              </label>
            ))}
          </div>
          <div className="card" style={{ padding: 12 }}>
            <h4>Filter by Certainty</h4>
            {Object.keys(byCertainty).map(k => (
              <label key={'cert-cb-'+k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={filters.certainty_level.includes(k)} onChange={() => toggleFilter('certainty_level', k)} />
                {k || 'unknown'}
              </label>
            ))}
          </div>
          <div className="card" style={{ padding: 12 }}>
            <h4>Filter by Urgency</h4>
            {Object.keys(byUrgency).map(k => (
              <label key={'urg-cb-'+k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={filters.urgency_level.includes(k)} onChange={() => toggleFilter('urgency_level', k)} />
                {k || 'unknown'}
              </label>
            ))}
          </div>
          <div className="card" style={{ padding: 12 }}>
            <h4>Filter by Severity</h4>
            {Object.keys(sevDist).map(k => (
              <label key={'sev-cb-'+k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={filters.severity_level.includes(k)} onChange={() => toggleFilter('severity_level', k)} />
                {k || 'unknown'}
              </label>
            ))}
          </div>
        </div>
      </details>
      {(filters.category.length || filters.certainty_level.length || filters.urgency_level.length || filters.severity_level.length) ? (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <strong>Filters:</strong>
          {filters.category.map(v => (
            <span key={'cat-'+v} className="pill" onClick={() => toggleFilter('category', v)}>{v} ×</span>
          ))}
          {filters.certainty_level.map(v => (
            <span key={'cert-'+v} className="pill" onClick={() => toggleFilter('certainty_level', v)}>{v} ×</span>
          ))}
          {filters.urgency_level.map(v => (
            <span key={'urg-'+v} className="pill" onClick={() => toggleFilter('urgency_level', v)}>{v} ×</span>
          ))}
          {filters.severity_level.map(v => (
            <span key={'sev-'+v} className="pill" onClick={() => toggleFilter('severity_level', v)}>{v} ×</span>
          ))}
          {filters.area.map(v => (
            <span key={'area-'+v} className="pill" onClick={() => toggleFilter('area', v)}>{v} ×</span>
          ))}
          {filters.date.map(v => (
            <span key={'date-'+v} className="pill" onClick={() => toggleFilter('date', v)}>{v} ×</span>
          ))}
          <button style={{ marginLeft: 'auto' }} onClick={clearFilters}>Reset Filters</button>
        </div>
      ) : null}
      <div className="card" style={{ padding: 12, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Alert Visualizations</h3>
          <button onClick={() => setShowViz(v => !v)}>{showViz ? 'Hide' : 'Show'}</button>
        </div>
        {showViz && (
          <>
            <div className="card" style={{ padding: 12, marginTop: 12, marginBottom: 12 }}>
              <h3>Alerts Per Day</h3>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div className="two-col" style={{ marginTop: 8 }}>
          <div>
            <h4 style={{ margin: 0 }}>Source</h4>
            <div className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{currentText}</div>
          </div>
          <div>
            <h4 style={{ margin: 0 }}>Translation</h4>
            <textarea ref={translationRef} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, overflow: 'hidden', resize: 'none' }} placeholder="Translated message" />
          </div>
        </div>
              </div>
              {dates.length ? <Line data={totalTrend} options={{ responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }, onClick: (evt, elements, chart) => { const el = elements && elements[0]; if (!el) return; const idx = el.index; const label = chart.data.labels[idx]; if (!label) return; toggleFilter('date', label) } }} /> : <p>No data.</p>}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              <div className="card" style={{ padding: 12 }}>
                <h3>By Category</h3>
                <BarChart data={catDist} title="Alerts by Category" field="category" selected={filters.category} onToggle={toggleFilter} />
              </div>
              <div className="card" style={{ padding: 12 }}>
                <h3>By Certainty</h3>
                <BarChart data={certDist} title="Alerts by Certainty" field="certainty_level" selected={filters.certainty_level} onToggle={toggleFilter} />
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              <div className="card" style={{ padding: 12 }}>
                <h3>By Urgency</h3>
                <BarChart data={urgDist} title="Alerts by Urgency" field="urgency_level" selected={filters.urgency_level} onToggle={toggleFilter} />
              </div>
              <div className="card" style={{ padding: 12 }}>
                <h3>By Severity</h3>
                <BarChart data={sevDist} title="Alerts by Severity" field="severity_level" selected={filters.severity_level} onToggle={toggleFilter} />
              </div>
            </div>
            <div className="card" style={{ padding: 12, marginBottom: 12 }}>
              <h3>Stacked by Category</h3>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={exportStacked} disabled={!(dates.length && categories.length)}>Export CSV</button>
              </div>
              {dates.length && categories.length ? (
                <Bar data={stackedData} options={{ responsive: true, plugins: { legend: { position: 'bottom' } }, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } }, onClick: (evt, elements, chart) => { const el = elements && elements[0]; if (!el) return; const ds = el.datasetIndex; const label = chart.data.datasets?.[ds]?.label; if (!label) return; toggleFilter('category', label) } }} />
              ) : <p>No data.</p>}
            </div>
          </>
        )}
      </div>
      <AlertsTable alerts={filteredAlerts} />
      <button onClick={load}>Reload</button>
    </div>
  )
}

function Translate() {
  const [source, setSource] = useState('Evacuate immediately due to wildfire.')
  const [target, setTarget] = useState('es')
  const [system, setSystem] = useState('gpt4o')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text || '') } catch {}
  }
  const run = async () => {
    setLoading(true); setResult(null)
    try {
      const r = await fetch(apiUrl('/translate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_text: source, target_language: target, system })
      })
      const data = await r.json()
      setResult(data)
    } catch (e) {
      setResult({ error: String(e) })
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className="card">
      <h2>Translate</h2>
      <textarea value={source} onChange={e => setSource(e.target.value)} rows={4} style={{ width: '100%' }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <label>Language
          <select value={target} onChange={e => setTarget(e.target.value)}>
            <option value="es">Spanish</option>
            <option value="hi">Hindi</option>
          </select>
        </label>
        <label>System
          <select value={system} onChange={e => setSystem(e.target.value)}>
            <option value="gpt4o">GPT-4o</option>
            <option value="google_nmt">Google NMT</option>
            <option value="nllb200">NLLB-200</option>
          </select>
        </label>
        <button onClick={run} disabled={loading}>{loading ? 'Translating…' : 'Translate'}</button>
      </div>
      {result && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3>Translation</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
            <button onClick={() => copy(result.translation)}>Copy</button>
          </div>
          <div style={{ whiteSpace: 'pre-wrap', background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
            {result.translation}
          </div>
          {result.metadata && (
            <div style={{ marginTop: 12 }}>
              <h4>Metadata</h4>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <tbody>
                  {Object.entries(result.metadata).map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ borderBottom: '1px solid var(--border)', padding: 6, opacity: 0.8 }}>{k}</td>
                      <td style={{ borderBottom: '1px solid var(--border)', padding: 6 }}>{String(v ?? '')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ScoreGrid({ scores }) {
  if (!scores) return null
  const entries = Object.entries(scores)
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td style={{ borderBottom: '1px solid #ddd', padding: 6 }}>{k}</td>
            <td style={{ borderBottom: '1px solid #ddd', padding: 6 }}>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Evaluate() {
  const [source, setSource] = useState(() => sessionStorage.getItem('eval_source') || 'Evacuate immediately due to wildfire.')
  const [translated, setTranslated] = useState(() => sessionStorage.getItem('eval_translated') || 'Evacúe de inmediato debido a un incendio forestal.')
  const [language, setLanguage] = useState(() => sessionStorage.getItem('eval_language') || 'es')
  const [context, setContext] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const sourceRef = useRef(null)
  const translatedRef = useRef(null)
  const adjust = (ref) => { const el = ref?.current; if (!el) return; el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' }
  useEffect(() => { adjust(sourceRef) }, [source])
  useEffect(() => { adjust(translatedRef) }, [translated])
  useEffect(() => { try { sessionStorage.setItem('eval_source', source) } catch {} }, [source])
  useEffect(() => { try { sessionStorage.setItem('eval_translated', translated) } catch {} }, [translated])
  useEffect(() => { try { sessionStorage.setItem('eval_language', language) } catch {} }, [language])
  const run = async () => {
    setLoading(true); setResult(null)
    try {
      const r = await fetch(apiUrl('/evaluate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_segment: source, translated_segment: translated, language, context })
      })
      const data = await r.json()
      setResult(data)
    } catch (e) {
      setResult({ error: String(e) })
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className="card">
      <h2>Evaluate Fairness</h2>
      <textarea ref={sourceRef} value={source} onChange={e => setSource(e.target.value)} rows={3} style={{ width: '100%', overflow: 'hidden', resize: 'none' }} placeholder="Source segment" />
      <textarea ref={translatedRef} value={translated} onChange={e => setTranslated(e.target.value)} rows={3} style={{ width: '100%', marginTop: 8, overflow: 'hidden', resize: 'none' }} placeholder="Translated segment" />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <label>Language
          <select value={language} onChange={e => setLanguage(e.target.value)}>
            <option value="es">Spanish</option>
            <option value="hi">Hindi</option>
          </select>
        </label>
        <button onClick={run} disabled={loading}>{loading ? 'Evaluating…' : 'Evaluate'}</button>
      </div>
      {result && (
        <div style={{ marginTop: 12 }}>
          <h3>Scores</h3>
          <ScoreGrid scores={result.scores} />
          {result.rationale && Object.keys(result.rationale).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <h3>Rationale</h3>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <tbody>
                  {Object.entries(result.rationale).map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ borderBottom: '1px solid var(--border)', padding: 6, opacity: 0.8 }}>{k}</td>
                      <td style={{ borderBottom: '1px solid var(--border)', padding: 6 }}>{String(v ?? '')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SingleEval() {
  const [source, setSource] = useState('Evacuate immediately due to wildfire.')
  const [target, setTarget] = useState('es')
  const [system, setSystem] = useState('gpt4o')
  const [translation, setTranslation] = useState('')
  const [evalRes, setEvalRes] = useState(null)
  const [loadingT, setLoadingT] = useState(false)
  const [loadingE, setLoadingE] = useState(false)
  const [compare, setCompare] = useState(true)
  const sourceRef = useRef(null)
  const translationRef = useRef(null)
  const syncingRef = useRef(false)
  const syncScroll = (fromEl, toEl) => {
    if (!fromEl || !toEl) return
    const maxFrom = fromEl.scrollHeight - fromEl.clientHeight
    const maxTo = toEl.scrollHeight - toEl.clientHeight
    const ratio = maxFrom > 0 ? (fromEl.scrollTop / maxFrom) : 0
    toEl.scrollTop = ratio * maxTo
  }
  const onSourceScroll = () => {
    const a = sourceRef.current
    const b = translationRef.current
    if (!a || !b || syncingRef.current) return
    syncingRef.current = true
    syncScroll(a, b)
    setTimeout(() => { syncingRef.current = false }, 0)
  }
  const onTransScroll = () => {
    const a = translationRef.current
    const b = sourceRef.current
    if (!a || !b || syncingRef.current) return
    syncingRef.current = true
    syncScroll(a, b)
    setTimeout(() => { syncingRef.current = false }, 0)
  }
  useEffect(() => {
    const el = translationRef.current
    if (!el) return
    if (compare) return
    el.style.height = 'auto'
    el.style.height = el.scrollHeight + 'px'
  }, [translation, compare])
  const translate = async () => {
    setLoadingT(true)
    try {
      const r = await fetch(apiUrl('/translate'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_text: source, target_language: target, system }) })
      const data = await r.json(); setTranslation(data.translation || '')
    } finally { setLoadingT(false) }
  }
  const evaluateNow = async () => {
    if (!translation) return
    setLoadingE(true)
    try {
      const r = await fetch(apiUrl('/evaluate'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_segment: source, translated_segment: translation, language: target, context: '' }) })
      const data = await r.json(); setEvalRes(data)
    } finally { setLoadingE(false) }
  }
  return (
    <div className="card">
      <h2>Single Evaluation</h2>
      <p style={{ opacity: 0.8 }}>Translate the whole message, then evaluate fairness in one flow.</p>
      <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
        <label>Language
          <select value={target} onChange={e => setTarget(e.target.value)}>
            <option value="es">Spanish</option>
            <option value="hi">Hindi</option>
          </select>
        </label>
        <label>System
          <select value={system} onChange={e => setSystem(e.target.value)}>
            <option value="gpt4o">GPT-4o</option>
            <option value="google_nmt">Google NMT</option>
            <option value="nllb200">NLLB-200</option>
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={compare} onChange={e => setCompare(e.target.checked)} /> Compare mode
        </label>
        <button className="primary" onClick={translate} disabled={loadingT}>{loadingT ? 'Translating…' : 'Translate'}</button>
      </div>
      {compare ? (
        <div className="two-col" style={{ marginTop: 12 }}>
          <div>
            <h4 style={{ margin: 0 }}>Source</h4>
            <textarea ref={sourceRef} onScroll={onSourceScroll} value={source} onChange={e => setSource(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6 }} />
          </div>
          <div>
            <h4 style={{ margin: 0 }}>Translation</h4>
            <textarea ref={translationRef} onScroll={onTransScroll} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6 }} placeholder="Translated message" />
          </div>
        </div>
      ) : (
        <>
          <textarea ref={sourceRef} onScroll={onSourceScroll} value={source} onChange={e => setSource(e.target.value)} rows={4} style={{ width: '100%', marginTop: 12 }} />
          <textarea ref={translationRef} onScroll={onTransScroll} value={translation} onChange={e => setTranslation(e.target.value)} rows={3} style={{ width: '100%', marginTop: 8 }} placeholder="Translated message" />
        </>
      )}
      <div className="sticky-actions">
        <button className="primary" onClick={evaluateNow} disabled={loadingE || !translation}>{loadingE ? 'Evaluating…' : 'Evaluate'}</button>
      </div>
      {evalRes && (
        <div style={{ marginTop: 12 }}>
          <h3>Scores</h3>
          <ScoreGrid scores={evalRes.scores} />
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('Health')
  const [light, setLight] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  useEffect(() => {
    document.body.classList.toggle('light', light)
  }, [light])
  return (
    <>
      <header className="header">
        <div className="brand">IPAWS Research UI</div>
        <div className="row">
          <button className="theme-toggle" onClick={() => setLight(v => !v)}>{light ? 'Dark' : 'Light'} Theme</button>
        </div>
      </header>
      <div className="container">
        <div className={`app-layout ${collapsed ? 'collapsed' : ''}`}>
          <Nav current={tab} onChange={setTab} collapsed={collapsed} onToggleCollapse={() => setCollapsed(v => !v)} />
          <main>
            {tab === 'Health' && <Health onNavigate={setTab} />}
            {tab === 'Alerts' && <Alerts />}
            {tab === 'Single Eval' && <SingleEval />}
            {tab === 'Human Eval' && <HumanEval />}
            {tab === 'Batch Eval' && <BatchEval />}
            {tab === 'Whole Eval' && <WholeEval />}
          </main>
        </div>
      </div>
    </>
  )
}

function HumanEval() {
  const KEYS = [
    ['pf1_urgency_preservation', 'Urgency preservation'],
    ['pf2_directive_clarity', 'Directive clarity'],
    ['pf3_risk_severity', 'Risk severity'],
    ['pf4_authority_attribution', 'Authority attribution'],
    ['pf5_temporal_accuracy', 'Temporal accuracy'],
    ['pf6_procedural_completeness', 'Procedural completeness'],
    ['if1_respectful_tone', 'Respectful tone'],
    ['if2_inclusion', 'Inclusion'],
    ['if3_empathy_marker', 'Empathy marker'],
    ['if4_linguistic_clarity', 'Linguistic clarity'],
    ['if5_cultural_appropriateness', 'Cultural appropriateness'],
    ['if6_trust_signal', 'Trust signal'],
  ]
  const [source, setSource] = useState(() => sessionStorage.getItem('he_source') || 'Evacuate immediately due to wildfire.')
  const [translated, setTranslated] = useState(() => sessionStorage.getItem('he_translated') || 'Evacúe de inmediato debido a un incendio forestal.')
  const [language, setLanguage] = useState(() => sessionStorage.getItem('he_language') || 'es')
  const [evaluatorId, setEvaluatorId] = useState('')
  const [scores, setScores] = useState(Object.fromEntries(KEYS.map(([k]) => [k, 1])))
  const [notes, setNotes] = useState(() => sessionStorage.getItem('he_notes') || '')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const half = Math.ceil(KEYS.length / 2)
  const LEFT_KEYS = KEYS.slice(0, half)
  const RIGHT_KEYS = KEYS.slice(half)
  const heSourceRef = useRef(null)
  const heTranslatedRef = useRef(null)
  const heNotesRef = useRef(null)
  const adjust = (ref) => { const el = ref?.current; if (!el) return; el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' }
  useEffect(() => { adjust(heSourceRef) }, [source])
  useEffect(() => { adjust(heTranslatedRef) }, [translated])
  useEffect(() => { adjust(heNotesRef) }, [notes])
  useEffect(() => { try { sessionStorage.setItem('he_source', source) } catch {} }, [source])
  useEffect(() => { try { sessionStorage.setItem('he_translated', translated) } catch {} }, [translated])
  useEffect(() => { try { sessionStorage.setItem('he_notes', notes) } catch {} }, [notes])
  useEffect(() => { try { sessionStorage.setItem('he_language', language) } catch {} }, [language])
  const changeScore = (k, v) => setScores(s => ({ ...s, [k]: Number(v) }))
  const submit = async () => {
    setLoading(true); setResult(null)
    try {
      const r = await fetch(apiUrl('/evaluate/human'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_segment: source,
          translated_segment: translated,
          language,
          evaluator_id: evaluatorId,
          scores,
          rationale: notes ? { notes } : {},
        })
      })
      const data = await r.json()
      setResult(data)
    } catch (e) {
      setResult({ error: String(e) })
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className="card">
      <h2>Human Evaluation</h2>
      <p style={{ opacity: 0.8, marginTop: 4 }}>Scoring guide: 0 = Not present, 1 = Partial, 2 = Fully present.</p>
      <input value={evaluatorId} onChange={e => setEvaluatorId(e.target.value)} placeholder="Evaluator ID (optional)" />
      <textarea ref={heSourceRef} value={source} onChange={e => setSource(e.target.value)} rows={3} style={{ width: '100%', marginTop: 8, overflow: 'hidden', resize: 'none' }} placeholder="Source segment" />
      <textarea ref={heTranslatedRef} value={translated} onChange={e => setTranslated(e.target.value)} rows={3} style={{ width: '100%', marginTop: 8, overflow: 'hidden', resize: 'none' }} placeholder="Translated segment" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
        <div>
          <h4 style={{ margin: '0 0 6px 0' }}>Performance Factors</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 8 }}>
          {LEFT_KEYS.map(([k, label]) => (
            <>
              <label key={k + '-lbl'}>{label}</label>
              <select key={k} value={scores[k]} onChange={e => changeScore(k, e.target.value)}>
                <option value={0}>0</option>
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </>
          ))}
          </div>
        </div>
        <div>
          <h4 style={{ margin: '0 0 6px 0' }}>Inclusivity Factors</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 8 }}>
          {RIGHT_KEYS.map(([k, label]) => (
            <>
              <label key={k + '-lbl'}>{label}</label>
              <select key={k} value={scores[k]} onChange={e => changeScore(k, e.target.value)}>
                <option value={0}>0</option>
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </>
          ))}
          </div>
        </div>
      </div>
      <textarea ref={heNotesRef} value={notes} onChange={e => setNotes(e.target.value)} rows={3} style={{ width: '100%', marginTop: 12, overflow: 'hidden', resize: 'none' }} placeholder="Notes / rationale (optional)" />
      <button className="primary" onClick={submit} disabled={loading} style={{ marginTop: 8 }}>{loading ? 'Saving…' : 'Save Evaluation'}</button>
      {result && result.saved && (
        <div className="card" style={{ marginTop: 8, padding: 8 }}>
          <strong>Saved.</strong> Appended to: <span style={{ opacity: 0.8 }}>{result.path}</span>
        </div>
      )}
    </div>
  )
}

function BatchEval() {
  const [daysBack, setDaysBack] = useState('7')
  const [stateCode, setStateCode] = useState('CA')
  const [targetLanguage, setTargetLanguage] = useState(() => sessionStorage.getItem('batch_language') || 'es')
  const [useWholeMessage, setUseWholeMessage] = useState(() => {
    try { return sessionStorage.getItem('batch_use_whole') === '1' } catch { return true }
  })
  const [alerts, setAlerts] = useState([])
  const [loadingAlerts, setLoadingAlerts] = useState(false)
  const [alertError, setAlertError] = useState(null)
  const [idx, setIdx] = useState(0)
  const [segments, setSegments] = useState([])
  const [segIdx, setSegIdx] = useState(0)
  const [loadingSegs, setLoadingSegs] = useState(false)
  const [segmentError, setSegmentError] = useState(null)
  const [translation, setTranslation] = useState(() => sessionStorage.getItem('batch_translation') || '')
  const [autoEval, setAutoEval] = useState(null)
  const [humanSaved, setHumanSaved] = useState(null)
  const [autoLoading, setAutoLoading] = useState(false)
  const KEYS = [
    ['pf1_urgency_preservation', 'Urgency preservation'],
    ['pf2_directive_clarity', 'Directive clarity'],
    ['pf3_risk_severity', 'Risk severity'],
    ['pf4_authority_attribution', 'Authority attribution'],
    ['pf5_temporal_accuracy', 'Temporal accuracy'],
    ['pf6_procedural_completeness', 'Procedural completeness'],
    ['if1_respectful_tone', 'Respectful tone'],
    ['if2_inclusion', 'Inclusion'],
    ['if3_empathy_marker', 'Empathy marker'],
    ['if4_linguistic_clarity', 'Linguistic clarity'],
    ['if5_cultural_appropriateness', 'Cultural appropriateness'],
    ['if6_trust_signal', 'Trust signal'],
  ]
  const [scores, setScores] = useState(Object.fromEntries(KEYS.map(([k]) => [k, 1])))
  const [notes, setNotes] = useState('')
  const KEY_NAMES = Object.fromEntries(KEYS)
  const half = Math.ceil(KEYS.length / 2)
  const LEFT_KEYS = KEYS.slice(0, half)
  const RIGHT_KEYS = KEYS.slice(half)
  const [showViz, setShowViz] = useState(false)
  const translationRef = useRef(null)
  const sourcePaneRef = useRef(null)
  const syncingRef = useRef(false)
  const syncScroll = (fromEl, toEl) => {
    if (!fromEl || !toEl) return
    const maxFrom = fromEl.scrollHeight - fromEl.clientHeight
    const maxTo = toEl.scrollHeight - toEl.clientHeight
    const ratio = maxFrom > 0 ? (fromEl.scrollTop / maxFrom) : 0
    toEl.scrollTop = ratio * maxTo
  }
  const onSourceScroll = () => {
    const a = sourcePaneRef.current
    const b = translationRef.current
    if (!a || !b || syncingRef.current) return
    syncingRef.current = true
    syncScroll(a, b)
    setTimeout(() => { syncingRef.current = false }, 0)
  }
  const onTransScroll = () => {
    const a = translationRef.current
    const b = sourcePaneRef.current
    if (!a || !b || syncingRef.current) return
    syncingRef.current = true
    syncScroll(a, b)
    setTimeout(() => { syncingRef.current = false }, 0)
  }

  useEffect(() => {
    const el = translationRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = el.scrollHeight + 'px'
  }, [translation])
  useEffect(() => { try { sessionStorage.setItem('batch_language', targetLanguage) } catch {} }, [targetLanguage])
  useEffect(() => { try { sessionStorage.setItem('batch_translation', translation) } catch {} }, [translation])
  useEffect(() => { try { sessionStorage.setItem('batch_use_whole', useWholeMessage ? '1' : '0') } catch {} }, [useWholeMessage])

  const loadBatch = async () => {
    setLoadingAlerts(true); setAlertError(null)
    try {
      const params = new URLSearchParams({ daysBack, state: stateCode })
      const r = await fetch(apiUrl('/alerts?' + params.toString()))
      const data = await r.json()
      setAlerts(data)
      setIdx(0)
      setSegments([])
      setSegIdx(0)
      setTranslation('')
      setAutoEval(null)
    } catch (e) {
      setAlertError(String(e))
    } finally {
      setLoadingAlerts(false)
    }
  }

  const currentAlert = alerts[idx]
  const currentSegment = segments[segIdx]?.segment_text || ''
  const currentFunction = segments[segIdx]?.communicative_function || ''
  const currentText = useWholeMessage ? (currentAlert?.source_text || '') : currentSegment

  const loadSegments = async () => {
    if (!currentAlert) return
    setLoadingSegs(true); setSegmentError(null)
    try {
      const r = await fetch(apiUrl('/segment'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: currentAlert.source_text || '', language: 'en' })
      })
      const data = await r.json()
      setSegments(data.segments || [])
      setSegIdx(0)
      setTranslation('')
      setAutoEval(null)
    } catch (e) {
      setSegmentError(String(e))
    } finally {
      setLoadingSegs(false)
    }
  }

  const autoTranslate = async () => {
    if (!currentText) return
    setAutoLoading(true)
    try {
      const r = await fetch(apiUrl('/translate'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_text: currentText, target_language: targetLanguage, system: 'gpt4o' })
      })
      const data = await r.json()
      setTranslation(data.translation || '')
    } finally {
      setAutoLoading(false)
    }
  }

  const runAutoEval = async () => {
    if (!currentText || !translation) return
    setAutoLoading(true)
    try {
      const r = await fetch(apiUrl('/evaluate'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_segment: currentText, translated_segment: translation, language: targetLanguage, context: '' })
      })
      const data = await r.json()
      setAutoEval(data)
    } finally {
      setAutoLoading(false)
    }
  }

  const saveHuman = async () => {
    if (!currentText || !translation) return
    setAutoLoading(true)
    try {
      const r = await fetch(apiUrl('/evaluate/human'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_segment: currentText, translated_segment: translation, language: targetLanguage, evaluator_id: '', scores, rationale: notes ? { notes } : {} })
      })
      const data = await r.json()
      // Show minimal confirmation without overwriting automated scores
      setHumanSaved({ saved: data.saved, path: data.path })
    } finally {
      setAutoLoading(false)
    }
  }

  const changeScore = (k, v) => setScores(s => ({ ...s, [k]: Number(v) }))

  // Visuals based on loaded alerts (moved from Analytics)
  const dateKey = (iso) => { try { return new Date(iso).toISOString().slice(0,10) } catch { return '' } }
  const byDate = alerts.reduce((acc, a) => { const d = dateKey(a.timestamp); if (!d) return acc; acc[d] = (acc[d] || 0) + 1; return acc }, {})
  const dates = Object.keys(byDate).sort()
  const totalTrend = {
    labels: dates,
    datasets: [{ label: 'Alerts per day', data: dates.map(d => byDate[d] || 0), borderColor: 'rgba(70, 100, 255, 1)', backgroundColor: 'rgba(70, 100, 255, 0.25)', fill: true, tension: 0.2 }]
  }
  const categories = Array.from(new Set(alerts.map(a => a.category))).filter(Boolean)
  const colors = ['#4664ff','#00b894','#e17055','#fdcb6e','#6c5ce7','#00cec9','#0984e3','#d63031']
  const byDateCat = {}
  alerts.forEach(a => { const d = dateKey(a.timestamp); if (!d) return; const c = a.category || 'unknown'; byDateCat[d] = byDateCat[d] || {}; byDateCat[d][c] = (byDateCat[d][c] || 0) + 1 })
  const stackedData = {
    labels: dates,
    datasets: categories.map((c, i) => ({
      label: c,
      data: dates.map(d => (byDateCat[d]?.[c] || 0)),
      backgroundColor: colors[i % colors.length] + 'cc',
      borderColor: colors[i % colors.length],
      borderWidth: 1,
      stack: 'cat',
    }))
  }
  // CSV export helpers for Batch Eval charts
  const exportCsv = (name, header, rows) => {
    try {
      const lines = [header.join(','), ...rows.map(r => header.map(h => '"' + String(r[h] ?? '').replace(/"/g, '""') + '"').join(','))]
      const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${name}_${new Date().toISOString().slice(0,19)}.csv`
      document.body.appendChild(a)
      a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    } catch {}
  }
  const exportTrend = () => exportCsv('batch_alerts_trend', ['date','count'], dates.map(d => ({ date: d, count: byDate[d] || 0 })))
  const exportStacked = () => {
    const rows = []
    dates.forEach(d => { categories.forEach(c => rows.push({ date: d, category: c, count: (byDateCat[d]?.[c] || 0) })) })
    exportCsv('batch_alerts_by_category_daily', ['date','category','count'], rows)
  }


  const steps = [
    { key: 'load', label: 'Load Alerts', done: alerts.length > 0 },
    { key: 'select', label: 'Select Alert', done: !!currentAlert },
    { key: 'translate', label: 'Translate', done: !!translation },
    { key: 'evaluate', label: 'Evaluate', done: !!autoEval },
  ]
  return (
    <div className="card">
      <h2>Batch Evaluation</h2>
      <div className="card" style={{ padding: 8, marginTop: 8 }}>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {steps.map(s => (
            <span key={s.key} className="pill" style={{ opacity: s.done ? 1 : 0.6 }}>{s.label}</span>
          ))}
        </div>
      </div>
      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <label>Days Back
            <input value={daysBack} onChange={e => setDaysBack(e.target.value)} style={{ width: 80 }} />
          </label>
          <label>State
            <input value={stateCode} onChange={e => setStateCode(e.target.value)} style={{ width: 80 }} />
          </label>
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              <option value="es">Spanish</option>
              <option value="hi">Hindi</option>
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={useWholeMessage} onChange={e => setUseWholeMessage(e.target.checked)} />
            Use whole message (no segmentation)
          </label>
          <button className="primary" onClick={loadBatch} disabled={loadingAlerts}>{loadingAlerts ? 'Loading…' : 'Load Batch'}</button>
        </div>
        {alertError && <p className="error" style={{ marginTop: 8 }}>{alertError}</p>}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <h3>Alerts</h3>
        <AlertSummary alert={currentAlert} />
        <AlertsTable alerts={alerts} selectedId={alerts[idx]?.alert_id} pageSizeOptions={[1,10,25,50,100]} initialPageSize={1} onSelect={(a) => {
          const i = alerts.findIndex(x => x.alert_id === a.alert_id)
          setIdx(i >= 0 ? i : 0)
          setSegments([]); setSegIdx(0); setAutoEval(null); setTranslation('')
        }} />
        {!useWholeMessage && (
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button onClick={loadSegments} disabled={!currentAlert || loadingSegs}>{loadingSegs ? 'Segmenting…' : 'Segment Selected'}</button>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Alert Visualizations</h3>
          <button onClick={() => setShowViz(v => !v)}>{showViz ? 'Hide' : 'Show'}</button>
        </div>
        {showViz && (
          <>
            <div className="card" style={{ padding: 12, marginTop: 12, marginBottom: 12 }}>
              <h4>Alerts Per Day</h4>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={exportTrend} disabled={!dates.length}>Export CSV</button>
              </div>
              {dates.length ? <Line data={totalTrend} options={{ responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }} /> : <p>No data.</p>}
            </div>
            <div className="card" style={{ padding: 12 }}>
              <h4>Stacked by Category</h4>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={exportStacked} disabled={!(dates.length && categories.length)}>Export CSV</button>
              </div>
              {dates.length && categories.length ? (
                <Bar data={stackedData} options={{ responsive: true, plugins: { legend: { position: 'bottom' } }, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } }} />
              ) : <p>No data.</p>}
            </div>
          </>
        )}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <h3>{useWholeMessage ? 'Selected Alert Text' : 'Segments'}</h3>
        {useWholeMessage ? (
          currentAlert ? (
            <div style={{ whiteSpace: 'pre-wrap', background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
              {currentText || 'No text.'}
            </div>
          ) : <p>No alert selected.</p>
        ) : (
          <>
            {segments.length === 0 && <p>No segments loaded yet.</p>}
            {segments.length > 0 && (
              <>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button onClick={() => setSegIdx(i => Math.max(0, i - 1))} disabled={segIdx === 0}>Prev</button>
                  <span>{segIdx + 1} / {segments.length}</span>
                  <button onClick={() => setSegIdx(i => Math.min(segments.length - 1, i + 1))} disabled={segIdx >= segments.length - 1}>Next</button>
                </div>
                <p style={{ marginTop: 8 }}><strong>Source:</strong> {currentSegment}</p>
                {currentFunction && <p><em>Function:</em> {currentFunction}</p>}
              </>
            )}
          </>
        )}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Translation</h3>
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              <option value="es">Spanish</option>
              <option value="hi">Hindi</option>
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={true} onChange={() => {}} /> Compare mode
          </label>
        </div>
        <div className="two-col" style={{ marginTop: 8 }}>
          <div>
            <h4 style={{ margin: 0 }}>Source</h4>
            <div ref={sourcePaneRef} onScroll={onSourceScroll} className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{currentText}</div>
          </div>
          <div>
            <h4 style={{ margin: 0 }}>Translation</h4>
            <textarea ref={translationRef} onScroll={onTransScroll} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, resize: 'none' }} placeholder="Translated segment" />
          </div>
        </div>
        <div className="sticky-actions">
          <button className="primary" onClick={autoTranslate} disabled={autoLoading || !currentText}>Auto Translate</button>
          <button className="primary" onClick={runAutoEval} disabled={autoLoading || !translation}>Auto Evaluate</button>
          <button onClick={saveHuman} disabled={autoLoading || !translation}>Save Human</button>
        </div>
      </div>

      {autoEval && (
        <div className="card" style={{ padding: 12, marginTop: 12 }}>
          <h3>Automated Evaluation</h3>
          {autoEval.scores ? (
            <>
              <ScoreGrid scores={autoEval.scores} />
              {autoEval.rationale && (
                <div style={{ marginTop: 8 }}>
                  <h4>Rationale</h4>
                  <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(autoEval.rationale, null, 2)}</pre>
                </div>
              )}
            </>
          ) : (
            <div className="card" style={{ marginTop: 8, padding: 8 }}>
              {autoEval.error ? (
                <span style={{ color: 'var(--danger, #b00)' }}>Error: {String(autoEval.error)}</span>
              ) : (
                <span style={{ opacity: 0.8 }}>No scores available.</span>
              )}
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <h3>Human Evaluation</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
          <div>
            <h4 style={{ margin: '0 0 6px 0' }}>Performance Factors</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 8 }}>
              {LEFT_KEYS.map(([k, label]) => (
                <>
                  <label key={k + '-lbl'}>{label}</label>
                  <select key={k} value={scores[k]} onChange={e => changeScore(k, e.target.value)}>
                    <option value={0}>0</option>
                    <option value={1}>1</option>
                    <option value={2}>2</option>
                  </select>
                </>
              ))}
            </div>
          </div>
          <div>
            <h4 style={{ margin: '0 0 6px 0' }}>Inclusivity Factors</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 8 }}>
              {RIGHT_KEYS.map(([k, label]) => (
                <>
                  <label key={k + '-lbl'}>{label}</label>
                  <select key={k} value={scores[k]} onChange={e => changeScore(k, e.target.value)}>
                    <option value={0}>0</option>
                    <option value={1}>1</option>
                    <option value={2}>2</option>
                  </select>
                </>
              ))}
            </div>
          </div>
        </div>
        <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3} style={{ width: '100%', marginTop: 12 }} placeholder="Notes / rationale (optional)" />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button onClick={saveHuman} disabled={autoLoading || !translation}>Save Human Evaluation</button>
        </div>
        {humanSaved && humanSaved.saved && (
          <div className="card" style={{ marginTop: 8, padding: 8 }}>
            <strong>Human score saved.</strong> Appended to: <span style={{ opacity: 0.8 }}>{humanSaved.path}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function Analytics() {
  return (
    <div className="card">
      <h2>Analytics</h2>
      <p style={{ opacity: 0.8 }}>Visualizations moved to Alerts and Batch Eval. Empty for now.</p>
    </div>
  )
}

function WholeEval() {
  const [daysBack, setDaysBack] = useState('7')
  const [stateCode, setStateCode] = useState('CA')
  const [targetLanguage, setTargetLanguage] = useState(() => sessionStorage.getItem('whole_language') || 'es')
  const [alerts, setAlerts] = useState([])
  const [loadingAlerts, setLoadingAlerts] = useState(false)
  const [alertError, setAlertError] = useState(null)
  const [idx, setIdx] = useState(0)
  const [translation, setTranslation] = useState(() => sessionStorage.getItem('whole_translation') || '')
  const [autoEval, setAutoEval] = useState(null)
  const [humanSaved, setHumanSaved] = useState(null)
  const [autoLoading, setAutoLoading] = useState(false)
  const translationRef = useRef(null)
  const sourcePaneRef = useRef(null)

  useEffect(() => { try { sessionStorage.setItem('whole_language', targetLanguage) } catch {} }, [targetLanguage])
  useEffect(() => { try { sessionStorage.setItem('whole_translation', translation) } catch {} }, [translation])
  useEffect(() => {
    const el = translationRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxH = 320
    const h = el.scrollHeight
    el.style.height = Math.min(h, maxH) + 'px'
    el.style.overflow = h > maxH ? 'auto' : 'hidden'
  }, [translation])

  const onSourceScroll = (e) => {
    const src = e.currentTarget
    const tgt = translationRef.current
    if (!tgt) return
    const frac = src.scrollTop / ((src.scrollHeight - src.clientHeight) || 1)
    tgt.scrollTop = frac * (tgt.scrollHeight - tgt.clientHeight)
  }

  const onTransScroll = (e) => {
    const src = sourcePaneRef.current
    const tgt = e.currentTarget
    if (!src) return
    const frac = tgt.scrollTop / ((tgt.scrollHeight - tgt.clientHeight) || 1)
    src.scrollTop = frac * (src.scrollHeight - src.clientHeight)
  }

  const loadBatch = async () => {
    setLoadingAlerts(true); setAlertError(null)
    try {
      const params = new URLSearchParams({ daysBack, state: stateCode })
      const r = await fetch(apiUrl('/alerts?' + params.toString()))
      const data = await r.json()
      setAlerts(data)
      setIdx(0)
      setTranslation('')
      setAutoEval(null)
      setHumanSaved(null)
    } catch (e) {
      setAlertError(String(e))
    } finally {
      setLoadingAlerts(false)
    }
  }

  const currentAlert = alerts[idx]
  const currentText = currentAlert?.source_text || ''

  const autoTranslate = async () => {
    if (!currentText) return
    setAutoLoading(true)
    try {
      const r = await fetch(apiUrl('/translate'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_text: currentText, target_language: targetLanguage, system: 'gpt4o' })
      })
      const data = await r.json()
      setTranslation(data.translation || '')
    } finally {
      setAutoLoading(false)
    }
  }

  const runAutoEval = async () => {
    if (!currentText || !translation) return
    setAutoLoading(true)
    try {
      const r = await fetch(apiUrl('/evaluate'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_segment: currentText, translated_segment: translation, language: targetLanguage, context: '' })
      })
      const data = await r.json()
      setAutoEval(data)
    } finally {
      setAutoLoading(false)
    }
  }

  const KEYS = [
    ['pf1_urgency_preservation', 'Urgency preservation'],
    ['pf2_directive_clarity', 'Directive clarity'],
    ['pf3_risk_severity', 'Risk severity'],
    ['pf4_authority_attribution', 'Authority attribution'],
    ['pf5_temporal_accuracy', 'Temporal accuracy'],
    ['pf6_procedural_completeness', 'Procedural completeness'],
    ['if1_respectful_tone', 'Respectful tone'],
    ['if2_inclusion', 'Inclusion'],
    ['if3_empathy_marker', 'Empathy marker'],
    ['if4_linguistic_clarity', 'Linguistic clarity'],
    ['if5_cultural_appropriateness', 'Cultural appropriateness'],
    ['if6_trust_signal', 'Trust signal'],
  ]
  const [scores, setScores] = useState(Object.fromEntries(KEYS.map(([k]) => [k, 1])))
  const [notes, setNotes] = useState('')
  const half = Math.ceil(KEYS.length / 2)
  const LEFT_KEYS = KEYS.slice(0, half)
  const RIGHT_KEYS = KEYS.slice(half)
  const changeScore = (k, v) => setScores(s => ({ ...s, [k]: Number(v) }))

  const saveHuman = async () => {
    if (!currentText || !translation) return
    setAutoLoading(true)
    try {
      const r = await fetch(apiUrl('/evaluate/human'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_segment: currentText, translated_segment: translation, language: targetLanguage, evaluator_id: '', scores, rationale: notes ? { notes } : {} })
      })
      const data = await r.json()
      setHumanSaved({ saved: data.saved, path: data.path })
    } finally {
      setAutoLoading(false)
    }
  }

  // Visuals based on loaded alerts (optional, same as Batch Eval)
  const dateKey = (iso) => { try { return new Date(iso).toISOString().slice(0,10) } catch { return '' } }
  const byDate = alerts.reduce((acc, a) => { const d = dateKey(a.timestamp); if (!d) return acc; acc[d] = (acc[d] || 0) + 1; return acc }, {})
  const dates = Object.keys(byDate).sort()
  const totalTrend = {
    labels: dates,
    datasets: [{ label: 'Alerts per day', data: dates.map(d => byDate[d] || 0), borderColor: 'rgba(70, 100, 255, 1)', backgroundColor: 'rgba(70, 100, 255, 0.25)', fill: true, tension: 0.2 }]
  }
  const categories = Array.from(new Set(alerts.map(a => a.category))).filter(Boolean)
  const colors = ['#4664ff','#00b894','#e17055','#fdcb6e','#6c5ce7','#00cec9','#0984e3','#d63031']
  const byDateCat = {}
  alerts.forEach(a => { const d = dateKey(a.timestamp); if (!d) return; const c = a.category || 'unknown'; byDateCat[d] = byDateCat[d] || {}; byDateCat[d][c] = (byDateCat[d][c] || 0) + 1 })
  const stackedData = {
    labels: dates,
    datasets: categories.map((c, i) => ({
      label: c,
      data: dates.map(d => (byDateCat[d]?.[c] || 0)),
      backgroundColor: colors[i % colors.length] + 'cc',
      borderColor: colors[i % colors.length],
      borderWidth: 1,
      stack: 'cat',
    }))
  }
  const exportCsv = (name, header, rows) => {
    try {
      const lines = [header.join(','), ...rows.map(r => header.map(h => '"' + String(r[h] ?? '').replace(/"/g, '""') + '"').join(','))]
      const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${name}_${new Date().toISOString().slice(0,19)}.csv`
      document.body.appendChild(a)
      a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    } catch {}
  }
  const exportTrend = () => exportCsv('whole_alerts_trend', ['date','count'], dates.map(d => ({ date: d, count: byDate[d] || 0 })))
  const exportStacked = () => {
    const rows = []
    dates.forEach(d => { categories.forEach(c => rows.push({ date: d, category: c, count: (byDateCat[d]?.[c] || 0) })) })
    exportCsv('whole_alerts_by_category_daily', ['date','category','count'], rows)
  }

  return (
    <div className="card">
      <h2>Whole Message Evaluation</h2>
      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <label>Days Back
            <input value={daysBack} onChange={e => setDaysBack(e.target.value)} style={{ width: 80 }} />
          </label>
          <label>State
            <input value={stateCode} onChange={e => setStateCode(e.target.value)} style={{ width: 80 }} />
          </label>
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              <option value="es">Spanish</option>
              <option value="hi">Hindi</option>
            </select>
          </label>
          <button onClick={loadBatch} disabled={loadingAlerts}>{loadingAlerts ? 'Loading…' : 'Load Batch'}</button>
        </div>
        {alertError && <p className="error" style={{ marginTop: 8 }}>{alertError}</p>}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <h3>Alerts</h3>
        <AlertsTable alerts={alerts} selectedId={alerts[idx]?.alert_id} pageSizeOptions={[1,10,25,50,100]} initialPageSize={1} onSelect={(a) => {
          const i = alerts.findIndex(x => x.alert_id === a.alert_id)
          setIdx(i >= 0 ? i : 0)
          setTranslation(''); setAutoEval(null); setHumanSaved(null)
        }} />
        {currentAlert && (
          <div style={{ marginTop: 8 }}>
            <h4>Selected Alert Text</h4>
            <div style={{ whiteSpace: 'pre-wrap', background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
              {currentText}
            </div>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Translation</h3>
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              <option value="es">Spanish</option>
              <option value="hi">Hindi</option>
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={true} onChange={() => {}} /> Compare mode
          </label>
        </div>
        <div className="two-col" style={{ marginTop: 8 }}>
          <div>
            <h4 style={{ margin: 0 }}>Source</h4>
            <div ref={sourcePaneRef} onScroll={onSourceScroll} className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{currentText}</div>
          </div>
          <div>
            <h4 style={{ margin: 0 }}>Translation</h4>
            <textarea ref={translationRef} onScroll={onTransScroll} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, resize: 'none' }} placeholder="Translated message" />
          </div>
        </div>
        <div className="sticky-actions">
          <button className="primary" onClick={autoTranslate} disabled={autoLoading || !currentText}>Auto Translate</button>
          <button className="primary" onClick={runAutoEval} disabled={autoLoading || !translation}>Auto Evaluate</button>
        </div>
      </div>

      {autoEval && (
        <div className="card" style={{ padding: 12, marginTop: 12 }}>
          <h3>Automated Evaluation</h3>
          {autoEval.scores ? (
            <>
              <ScoreGrid scores={autoEval.scores} />
              {autoEval.rationale && (
                <div style={{ marginTop: 8 }}>
                  <h4>Rationale</h4>
                  <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(autoEval.rationale, null, 2)}</pre>
                </div>
              )}
            </>
          ) : (
            <div className="card" style={{ marginTop: 8, padding: 8 }}>
              {autoEval.error ? (
                <span style={{ color: 'var(--danger, #b00)' }}>Error: {String(autoEval.error)}</span>
              ) : (
                <span style={{ opacity: 0.8 }}>No scores available.</span>
              )}
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <h3>Human Evaluation</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
          <div>
            <h4 style={{ margin: '0 0 6px 0' }}>Performance Factors</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 8 }}>
              {LEFT_KEYS.map(([k, label]) => (
                <>
                  <label key={k + '-lbl'}>{label}</label>
                  <select key={k} value={scores[k]} onChange={e => changeScore(k, e.target.value)}>
                    <option value={0}>0</option>
                    <option value={1}>1</option>
                    <option value={2}>2</option>
                  </select>
                </>
              ))}
            </div>
          </div>
          <div>
            <h4 style={{ margin: '0 0 6px 0' }}>Inclusivity Factors</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 8 }}>
              {RIGHT_KEYS.map(([k, label]) => (
                <>
                  <label key={k + '-lbl'}>{label}</label>
                  <select key={k} value={scores[k]} onChange={e => changeScore(k, e.target.value)}>
                    <option value={0}>0</option>
                    <option value={1}>1</option>
                    <option value={2}>2</option>
                  </select>
                </>
              ))}
            </div>
          </div>
        </div>
        <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3} style={{ width: '100%', marginTop: 12 }} placeholder="Notes / rationale (optional)" />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button onClick={saveHuman} disabled={autoLoading || !translation}>Save Human Evaluation</button>
        </div>
        {humanSaved && humanSaved.saved && (
          <div className="card" style={{ marginTop: 8, padding: 8 }}>
            <strong>Human score saved.</strong> Appended to: <span style={{ opacity: 0.8 }}>{humanSaved.path}</span>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Alert Visualizations</h3>
          {/* Toggle removed to keep simple; charts always visible when data exists */}
        </div>
        {dates.length ? (
          <div className="card" style={{ padding: 12, marginTop: 12, marginBottom: 12 }}>
            <h4>Alerts Per Day</h4>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button onClick={exportTrend} disabled={!dates.length}>Export CSV</button>
            </div>
            <Line data={totalTrend} options={{ responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }} />
          </div>
        ) : <p>No data.</p>}
        {dates.length && categories.length ? (
          <div className="card" style={{ padding: 12 }}>
            <h4>Stacked by Category</h4>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button onClick={exportStacked} disabled={!(dates.length && categories.length)}>Export CSV</button>
            </div>
            <Bar data={stackedData} options={{ responsive: true, plugins: { legend: { position: 'bottom' } }, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } }} />
          </div>
        ) : null}
      </div>
    </div>
  )
}
