import { useEffect, useState, useRef } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import 'chart.js/auto'
import { signInWithPopup, signOut } from 'firebase/auth'
import { auth as firebaseAuth, googleProvider, firebaseConfigured } from './firebase'
import './App.css'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const apiUrl = (path) => `${API_BASE_URL}${path}`
const DEFAULT_TABS = ['Health', 'Alerts', 'Single Eval', 'Human Eval', 'Batch Eval', 'Whole Eval', 'My Submissions', 'Alert Pool', 'Admin Analytics']
const USER_TABS = ['Whole Eval', 'My Submissions']

const LANGUAGE_LABELS = { es: 'Spanish', hi: 'Hindi' }

// Returns the language codes the current signed-in user may evaluate in.
// Evaluators are locked to a single language; admins (no lock) get both.
function getAllowedLanguages() {
  try {
    const raw = sessionStorage.getItem('ui_auth')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed?.language) return [parsed.language]
    }
  } catch {}
  return ['es', 'hi']
}

// Picks a valid initial language: keep the stored choice if still allowed,
// otherwise fall back to the user's first allowed language.
function resolveLanguage(stored) {
  const allowed = getAllowedLanguages()
  if (stored && allowed.includes(stored)) return stored
  return allowed[0]
}

// Renders <option> elements for only the languages the user is allowed to use.
function LanguageOptions() {
  return getAllowedLanguages().map(code => (
    <option key={code} value={code}>{LANGUAGE_LABELS[code]}</option>
  ))
}

// Reads the signed-in user's stored session (set at login).
function getStoredAuth() {
  try {
    const raw = sessionStorage.getItem('ui_auth')
    if (raw) return JSON.parse(raw)
  } catch {}
  return null
}

// Builds request headers including the session Bearer token so the backend can
// attribute actions (e.g. human evaluations) to the signed-in user.
function authHeaders(extra = {}) {
  const a = getStoredAuth()
  return a?.token ? { ...extra, Authorization: `Bearer ${a.token}` } : { ...extra }
}

function Nav({ current, onChange, collapsed, onToggleCollapse, tabs = DEFAULT_TABS }) {
  const icons = { 'Health': '⌂', 'Alerts': '◉', 'Single Eval': '✦', 'Human Eval': '✓', 'Batch Eval': '▤', 'Whole Eval': '▥', 'My Submissions': '☷', 'Alert Pool': '⬚', 'Admin Analytics': '◈' }
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

function LoginPage({ onLogin, light, onToggleTheme }) {
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const signIn = async () => {
    setError('')
    if (!firebaseConfigured || !firebaseAuth) {
      setError('Google sign-in is not configured. Set the VITE_FIREBASE_* environment variables.')
      return
    }
    setLoading(true)
    try {
      const cred = await signInWithPopup(firebaseAuth, googleProvider)
      const idToken = await cred.user.getIdToken()
      const result = await onLogin({ idToken })
      if (!result?.ok) {
        try { await signOut(firebaseAuth) } catch {}
        setError(result?.error || 'Sign-in failed. Please try again.')
      }
    } catch (err) {
      if (err?.code === 'auth/popup-closed-by-user' || err?.code === 'auth/cancelled-popup-request') {
        setError('')
      } else {
        setError('Unable to sign in with Google. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <header className="header">
        <div className="brand">IPAWS Research UI</div>
        <div className="row">
          <button className="theme-toggle" onClick={onToggleTheme}>{light ? 'Dark' : 'Light'} Theme</button>
        </div>
      </header>
      <div className="container" style={{ maxWidth: 560 }}>
        <div className="card" style={{ padding: 16, marginTop: 24 }}>
          <h2 style={{ marginTop: 0 }}>Sign in</h2>
          <p style={{ opacity: 0.8 }}>Use your authorized Google account to continue.</p>
          <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
            {error && <p className="error" style={{ margin: 0 }}>{error}</p>}
            <button className="primary" type="button" onClick={signIn} disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in with Google'}
            </button>
          </div>
        </div>
      </div>
    </>
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

function AlertsTable({ alerts = [], onSelect, selectedId, pageSizeOptions = [10, 25, 50, 100], initialPageSize = 25, showPager = true }) {
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

  useEffect(() => {
    if (selectedId == null) return
    const selectedIndex = sorted.findIndex(a => a.alert_id === selectedId)
    if (selectedIndex < 0) return
    const desiredPage = Math.floor(selectedIndex / pageSize)
    if (desiredPage !== safePage) {
      setPage(desiredPage)
    }
  }, [selectedId, sorted, pageSize, safePage])

  useEffect(() => {
    if (!onSelect || pageItems.length === 0) return
    const selectedExists = selectedId != null && sorted.some(a => a.alert_id === selectedId)
    if (!selectedExists) {
      onSelect(pageItems[0])
    }
  }, [pageItems, onSelect, selectedId, sorted])

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
        {showPager && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={safePage === 0}>Prev</button>
            <span>Page {safePage + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={safePage >= totalPages - 1}>Next</button>
          </div>
        )}
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

function LoadingLabel({ text = 'Loading…' }) {
  return (
    <span className="loading-inline" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{text}</span>
    </span>
  )
}

const formatPercent = (value) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : '—'
const formatScore = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '—'
const formatPValue = (value) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  if (numeric < 0.001) return '< 0.001'
  return numeric.toFixed(4)
}

function DashboardStat({ label, value, subtext }) {
  return (
    <div className="card stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {subtext && <div className="stat-subtext">{subtext}</div>}
    </div>
  )
}

const ANALYTICS_VIEWS = [
  { key: 'overview', label: 'Overview' },
  { key: 'human', label: 'Human Evaluations' },
  { key: 'model', label: 'Model Performance' },
]

function AdminAnalytics({ auth }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [downloadingKey, setDownloadingKey] = useState('')
  const [view, setView] = useState('overview')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch(apiUrl('/admin/analysis'), {
        headers: { Authorization: `Bearer ${auth.token}` }
      })
      const payload = await r.json().catch(() => null)
      if (!r.ok) {
        throw new Error(payload?.detail || `Unable to load analytics (${r.status})`)
      }
      setData(payload)
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [auth?.token])

  const handleDownload = async (download) => {
    if (!download?.url) return
    setDownloadError('')
    setDownloadingKey(download.key || download.filename || '')
    try {
      const r = await fetch(apiUrl(download.url), {
        headers: { Authorization: `Bearer ${auth.token}` }
      })
      if (!r.ok) {
        const payload = await r.json().catch(() => null)
        throw new Error(payload?.detail || `Download failed (${r.status})`)
      }
      const blob = await r.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = download.filename || `${download.key || 'analytics'}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      setDownloadError(e?.message || String(e))
    } finally {
      setDownloadingKey('')
    }
  }

  if (loading) {
    return (
      <div className="card chart-card">
        <h2 style={{ marginTop: 0 }}>Admin Analytics</h2>
        <LoadingLabel text="Loading submitted data…" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="card chart-card">
        <h2 style={{ marginTop: 0 }}>Admin Analytics</h2>
        <p className="error">{error}</p>
        <button className="primary" onClick={load}>Retry</button>
      </div>
    )
  }

  const human = data?.human || {}
  const composite = data?.composite || {}
  const downloads = data?.downloads || []
  const humanLanguages = human.languages || []
  const humanMetrics = human.metrics || []
  const submissionsByDay = human.submissions_by_day || []
  const evaluators = human.evaluators || []
  const recentSubmissions = human.recent_submissions || []
  const distribution = human.normal_distribution || {}
  const systemRows = composite.by_language_system || []
  const bestSystems = composite.best_by_language || []
  const anova = composite.two_way_anova || {}
  const anovaRows = anova.rows || []
  const palette = ['rgba(79, 70, 229, 0.72)', 'rgba(14, 165, 233, 0.72)', 'rgba(16, 185, 129, 0.72)', 'rgba(245, 158, 11, 0.72)', 'rgba(244, 63, 94, 0.72)']

  const humanLanguageChart = {
    labels: humanLanguages.map(item => item.language?.toUpperCase() || 'N/A'),
    datasets: [{
      label: 'Submissions',
      data: humanLanguages.map(item => item.count || 0),
      backgroundColor: humanLanguages.map((_, idx) => palette[idx % palette.length]),
      borderRadius: 8,
    }],
  }

  const metricChart = {
    labels: humanMetrics.map(item => item.label),
    datasets: [{
      label: 'Average score %',
      data: humanMetrics.map(item => item.average_pct || 0),
      backgroundColor: 'rgba(79, 70, 229, 0.72)',
      borderRadius: 6,
    }],
  }

  const trendChart = {
    labels: submissionsByDay.map(item => item.date),
    datasets: [{
      label: 'Daily submissions',
      data: submissionsByDay.map(item => item.count || 0),
      borderColor: 'rgba(14, 165, 233, 1)',
      backgroundColor: 'rgba(14, 165, 233, 0.18)',
      tension: 0.28,
      fill: true,
    }],
  }

  const compositeLanguages = [...new Set(systemRows.map(item => item.language?.toUpperCase() || 'N/A'))]
  const compositeSystems = [...new Set(systemRows.map(item => item.system || 'unknown'))]
  const compositeChart = {
    labels: compositeLanguages,
    datasets: compositeSystems.map((system, idx) => ({
      label: system,
      data: compositeLanguages.map(language => {
        const match = systemRows.find(item => (item.system || 'unknown') === system && (item.language?.toUpperCase() || 'N/A') === language)
        return match ? match.avg_ofs : 0
      }),
      backgroundColor: palette[idx % palette.length],
      borderRadius: 6,
    })),
  }

  const distributionBins = distribution.bins || []
  const distributionChart = {
    labels: distributionBins.map(item => item.label),
    datasets: [
      {
        type: 'bar',
        label: 'Observed submissions',
        data: distributionBins.map(item => item.count || 0),
        backgroundColor: 'rgba(79, 70, 229, 0.55)',
        borderRadius: 6,
      },
      {
        type: 'line',
        label: 'Normal curve',
        data: distributionBins.map(item => item.normal_count || 0),
        borderColor: 'rgba(244, 63, 94, 0.95)',
        backgroundColor: 'rgba(244, 63, 94, 0.15)',
        tension: 0.32,
        pointRadius: 3,
        pointHoverRadius: 4,
        yAxisID: 'y',
      },
    ],
  }

  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginTop: 12, marginBottom: 12, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ margin: 0 }}>Admin Analytics</h2>
          <p style={{ margin: '6px 0 0 0', opacity: 0.8 }}>Human evaluation activity and model fairness benchmarks.</p>
        </div>
        <button className="primary" onClick={load}>Refresh</button>
      </div>

      <div className="stat-grid">
        <DashboardStat label="Human submissions" value={human.total_submissions || 0} subtext={`${human.unique_messages || 0} unique messages`} />
        <DashboardStat label="Average human score" value={formatPercent(human.average_score_pct || 0)} subtext={`Raw average ${formatScore(human.average_score || 0)} / 2.00`} />
        <DashboardStat label="Named evaluators" value={human.named_evaluators || 0} subtext={`${evaluators.length || 0} total evaluator profiles`} />
        <DashboardStat label="Composite records" value={composite.total_records || 0} subtext={`${bestSystems.length || 0} best-system comparisons`} />
      </div>

      <div className="row" style={{ gap: 6, margin: '16px 0 12px', flexWrap: 'wrap' }} role="tablist" aria-label="Analytics sections">
        {ANALYTICS_VIEWS.map(v => (
          <button
            key={v.key}
            role="tab"
            aria-selected={view === v.key}
            className={view === v.key ? 'primary' : 'outline'}
            onClick={() => setView(v.key)}
          >
            {v.label}
          </button>
        ))}
      </div>

      {view === 'overview' && (
        <div className="two-col">
          <div className="card chart-card">
            <h3 style={{ marginTop: 0 }}>Submission Trend</h3>
            <p style={{ marginTop: 0, opacity: 0.75 }}>Daily volume of submitted human scoring rows.</p>
            {submissionsByDay.length > 0 ? (
              <div style={{ height: 280 }}>
                <Line data={trendChart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }} />
              </div>
            ) : <p style={{ opacity: 0.75 }}>No human submissions available yet.</p>}
          </div>

          <div className="card chart-card">
            <h3 style={{ marginTop: 0 }}>Language Coverage</h3>
            <p style={{ marginTop: 0, opacity: 0.75 }}>Submission count by target language.</p>
            {humanLanguages.length > 0 ? (
              <div style={{ height: 280 }}>
                <Bar data={humanLanguageChart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }} />
              </div>
            ) : <p style={{ opacity: 0.75 }}>No language distribution to display.</p>}
          </div>
        </div>
      )}

      {view === 'human' && (
        <>
          <div className="two-col">
            <div className="card chart-card">
              <h3 style={{ marginTop: 0 }}>Metric Performance</h3>
              <p style={{ marginTop: 0, opacity: 0.75 }}>Average human score by fairness dimension (12 rubric measures).</p>
              {humanMetrics.length > 0 ? (
                <div style={{ height: 320 }}>
                  <Bar data={metricChart} options={{ responsive: true, maintainAspectRatio: false, indexAxis: 'y', scales: { x: { suggestedMax: 100 } } }} />
                </div>
              ) : <p style={{ opacity: 0.75 }}>Metric averages will appear after submissions are saved.</p>}
            </div>

            <div className="card chart-card">
              <h3 style={{ marginTop: 0 }}>Score Distribution</h3>
              <p style={{ marginTop: 0, opacity: 0.75 }}>Observed average scores versus a fitted normal curve.</p>
              <div className="metric-inline-grid" style={{ marginBottom: 12 }}>
                <div className="pill">Mean: {formatPercent(distribution.mean || 0)}</div>
                <div className="pill">Std dev: {formatScore(distribution.stddev || 0)}</div>
                <div className="pill">n = {distribution.count || 0}</div>
              </div>
              {distributionBins.length > 0 ? (
                <div style={{ height: 300 }}>
                  <Bar
                    data={distributionChart}
                    options={{
                      responsive: true,
                      maintainAspectRatio: false,
                      scales: { y: { beginAtZero: true, title: { display: true, text: 'Submission count' } } },
                    }}
                  />
                </div>
              ) : <p style={{ opacity: 0.75 }}>Not enough human-score data to fit a distribution yet.</p>}
            </div>
          </div>

          <div className="card chart-card">
            <h3 style={{ marginTop: 0 }}>Evaluator Activity</h3>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Evaluator</th>
                    <th>Submissions</th>
                    <th>Avg score</th>
                    <th>Languages</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluators.length > 0 ? evaluators.slice(0, 8).map(item => (
                    <tr key={item.evaluator_id}>
                      <td title={item.evaluator_id}>{item.evaluator_name || item.evaluator_id}</td>
                      <td>{item.count}</td>
                      <td>{formatPercent(item.average_score_pct)}</td>
                      <td>{(item.languages || []).join(', ') || '—'}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={4} style={{ opacity: 0.75 }}>No evaluator activity yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card chart-card">
            <h3 style={{ marginTop: 0 }}>Recent Submissions</h3>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Evaluator</th>
                    <th>Language</th>
                    <th>Avg score</th>
                    <th>Source preview</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {recentSubmissions.length > 0 ? recentSubmissions.map((item, idx) => (
                    <tr key={`${item.timestamp}-${idx}`}>
                      <td>{item.timestamp ? new Date(item.timestamp).toLocaleString() : '—'}</td>
                      <td title={item.evaluator_id}>{item.evaluator_name || item.evaluator_id}</td>
                      <td>{item.language?.toUpperCase()}</td>
                      <td>{formatPercent(item.average_score_pct)}</td>
                      <td>{item.source_preview || '—'}</td>
                      <td>{item.notes || '—'}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={6} style={{ opacity: 0.75 }}>Submitted rows will appear here after evaluators save scores.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {view === 'model' && (
        <>
          <div className="two-col">
            <div className="card chart-card">
              <h3 style={{ marginTop: 0 }}>Composite OFS by Language & System</h3>
              <p style={{ marginTop: 0, opacity: 0.75 }}>Overall fairness score benchmarks from exported composite data.</p>
              {systemRows.length > 0 ? (
                <div style={{ height: 320 }}>
                  <Bar data={compositeChart} options={{ responsive: true, maintainAspectRatio: false, scales: { y: { suggestedMin: 0 } } }} />
                </div>
              ) : <p style={{ opacity: 0.75 }}>No composite score exports were found.</p>}
            </div>

            <div className="card chart-card">
              <h3 style={{ marginTop: 0 }}>Best System by Language</h3>
              <p style={{ marginTop: 0, opacity: 0.75 }}>Highest-scoring translation system per language.</p>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Language</th>
                      <th>System</th>
                      <th>OFS</th>
                      <th>PFI / IFI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bestSystems.length > 0 ? bestSystems.map(item => (
                      <tr key={item.language}>
                        <td>{item.language?.toUpperCase()}</td>
                        <td>{item.system}</td>
                        <td>{formatScore(item.avg_ofs)}</td>
                        <td>{formatScore(item.avg_pfi)} / {formatScore(item.avg_ifi)}</td>
                      </tr>
                    )) : (
                      <tr>
                        <td colSpan={4} style={{ opacity: 0.75 }}>No composite export data yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="card chart-card">
            <h3 style={{ marginTop: 0 }}>Two-Way ANOVA</h3>
            <p style={{ marginTop: 0, opacity: 0.75 }}>Effect of language and translation system on overall fairness score (OFS).</p>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Factor</th>
                    <th>df</th>
                    <th>F</th>
                    <th>p-value</th>
                    <th>Effect size</th>
                    <th>Variance share</th>
                  </tr>
                </thead>
                <tbody>
                  {anovaRows.length > 0 ? anovaRows.map(item => (
                    <tr key={item.source}>
                      <td>{item.label}</td>
                      <td>{item.df}</td>
                      <td>{item.f_value ?? '—'}</td>
                      <td>{formatPValue(item.p_value)}</td>
                      <td>{item.effect_size ?? '—'}</td>
                      <td>{formatPercent(item.variance_share)}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={6} style={{ opacity: 0.75 }}>Not enough composite data is available to compute a two-way ANOVA.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {!!(anova.insights || []).length && (
              <div style={{ marginTop: 12 }}>
                {(anova.insights || []).map((insight, idx) => (
                  <p key={idx} style={{ margin: '6px 0', opacity: 0.86 }}>{insight}</p>
                ))}
              </div>
            )}
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: 'pointer', opacity: 0.85 }}>How to read this</summary>
              <ul style={{ marginTop: 8, opacity: 0.85 }}>
                <li><strong>p-value</strong> below <strong>0.05</strong> indicates a statistically significant effect.</li>
                <li><strong>Effect size</strong> is the share of variance a factor explains relative to residual noise.</li>
                <li><strong>Variance share</strong> compares each factor's contribution to total variation.</li>
              </ul>
            </details>
          </div>
        </>
      )}

      <details className="card chart-card" style={{ marginTop: 12 }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Export data{downloads.length ? ` (${downloads.length})` : ''}</summary>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
          {downloads.length > 0 ? downloads.map(download => (
            <button
              key={download.key}
              className="outline"
              onClick={() => handleDownload(download)}
              disabled={downloadingKey === download.key}
            >
              {downloadingKey === download.key ? `Downloading ${download.label}…` : `Download ${download.label}`}
            </button>
          )) : <p style={{ opacity: 0.75, margin: 0 }}>No exports available.</p>}
        </div>
        {downloadError && <p className="error" style={{ marginTop: 10, marginBottom: 0 }}>{downloadError}</p>}
      </details>
    </>
  )
}

function EvalContextStrip({ mode, language, currentIndex, total, alertId, loading, error }) {
  return (
    <div className="card" style={{ padding: 10, marginTop: 10 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span className="pill">Mode: {mode}</span>
        <span className="pill">Language: {language === 'es' ? 'Spanish' : 'Hindi'}</span>
        <span className="pill">Message: {total > 0 ? `${currentIndex + 1} / ${total}` : '0 / 0'}</span>
        <span className="pill">Alert: {alertId || 'None selected'}</span>
        <span className="pill" style={{ opacity: loading ? 1 : 0.7 }}>
          {loading ? <LoadingLabel text="Working…" /> : 'Ready'}
        </span>
      </div>
      {error && <p className="error" style={{ marginTop: 8 }}>Translation failed: {error}</p>}
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
      const params = new URLSearchParams({ source: 'research' })
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
  const [target, setTarget] = useState(() => resolveLanguage(null))
  const [system, setSystem] = useState('gemini')
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
            {LanguageOptions()}
          </select>
        </label>
        <label>System
          <select value={system} onChange={e => setSystem(e.target.value)}>
            <option value="gemini">Gemini 2.0 Flash</option>
            <option value="gpt5.5">GPT-5.5</option>
            <option value="llama3">Llama 3 (Replicate)</option>
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
  const [language, setLanguage] = useState(() => resolveLanguage(sessionStorage.getItem('eval_language')))
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
            {LanguageOptions()}
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
  const [target, setTarget] = useState(() => resolveLanguage(null))
  const [system, setSystem] = useState('gemini')
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
            {LanguageOptions()}
          </select>
        </label>
        <label>System
          <select value={system} onChange={e => setSystem(e.target.value)}>
            <option value="gemini">Gemini 2.0 Flash</option>
            <option value="gpt5.5">GPT-5.5</option>
            <option value="llama3">Llama 3 (Replicate)</option>
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

function AlertPool({ auth }) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [expanded, setExpanded] = useState(new Set())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveSuccess, setSaveSuccess] = useState(false)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch(apiUrl('/admin/alert-pool'), {
        headers: { Authorization: `Bearer ${auth.token}` }
      })
      const payload = await r.json().catch(() => null)
      if (!r.ok) {
        throw new Error(payload?.detail || `Unable to load alert pool (${r.status})`)
      }
      setAlerts(payload.alerts || [])
      setSelected(new Set(payload.alerts.filter(a => a.selected).map(a => a.id)))
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [auth?.token])

  const toggleAlert = (id) => {
    const newSelected = new Set(selected)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelected(newSelected)
  }

  const toggleExpand = (id) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const saveSelection = async () => {
    if (selected.size !== 48) {
      setSaveError(`Please select exactly 48 alerts (currently ${selected.size} selected)`)
      return
    }
    setSaving(true)
    setSaveError('')
    setSaveSuccess(false)
    try {
      const r = await fetch(apiUrl('/admin/alert-pool/select'), {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${auth.token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ selected_ids: Array.from(selected) })
      })
      const payload = await r.json().catch(() => null)
      if (!r.ok) {
        throw new Error(payload?.detail || `Save failed (${r.status})`)
      }
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (e) {
      setSaveError(e?.message || String(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="card chart-card">
        <h2 style={{ marginTop: 0 }}>Alert Pool Selection</h2>
        <LoadingLabel text="Loading alert pool…" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="card chart-card">
        <h2 style={{ marginTop: 0 }}>Alert Pool Selection</h2>
        <p className="error">{error}</p>
        <button className="primary" onClick={load}>Retry</button>
      </div>
    )
  }

  // Group alerts by category
  const grouped = {}
  alerts.forEach(alert => {
    if (!grouped[alert.category]) grouped[alert.category] = []
    grouped[alert.category].push(alert)
  })

  const categories = ['weather', 'evacuation', 'public_safety', 'health']
  const categoryLabels = {
    'weather': 'Weather',
    'evacuation': 'Evacuation',
    'public_safety': 'Public Safety',
    'health': 'Health'
  }

  return (
    <div className="card chart-card" style={{ maxHeight: '90vh', overflow: 'auto' }}>
      <h2 style={{ marginTop: 0 }}>Alert Pool Selection</h2>
      <div style={{ marginBottom: 16 }}>
        <p style={{ marginBottom: 8 }}>
          <strong>Selected: {selected.size} / 70 alerts</strong>
        </p>
        {selected.size !== 48 && (
          <p style={{ color: 'var(--color-warn)', marginBottom: 8, fontSize: '0.9em' }}>
            ⚠ Select exactly 48 alerts to enable save
          </p>
        )}
      </div>

      {categories.map(cat => (
        grouped[cat]?.length > 0 && (
          <div key={cat} style={{ marginBottom: 24 }}>
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {categoryLabels[cat]} ({grouped[cat].length})
            </h3>
            <div style={{ display: 'grid', gap: 8 }}>
              {grouped[cat].map(alert => {
                const isExpanded = expanded.has(alert.id)
                const isLong = alert.text.length > 120
                return (
                  <div key={alert.id} style={{ display: 'flex', gap: 8, padding: '10px', borderRadius: '6px', background: 'var(--bg-secondary)', border: '1px solid var(--border-color, rgba(128,128,128,0.35))', alignItems: 'flex-start' }}>
                    <input
                      type="checkbox"
                      checked={selected.has(alert.id)}
                      onChange={() => toggleAlert(alert.id)}
                      style={{ marginTop: '2px', cursor: 'pointer' }}
                    />
                    <div style={{ flex: 1 }}>
                      <span style={{ fontSize: '0.9em', lineHeight: 1.4, whiteSpace: 'pre-wrap', cursor: 'pointer' }} onClick={() => toggleAlert(alert.id)}>
                        {isExpanded || !isLong ? alert.text : `${alert.text.substring(0, 120)}…`}
                      </span>
                      {isLong && (
                        <button
                          type="button"
                          onClick={() => toggleExpand(alert.id)}
                          style={{ marginLeft: 8, background: 'none', border: 'none', color: 'var(--color-accent, #4a9eff)', cursor: 'pointer', fontSize: '0.85em', padding: 0, textDecoration: 'underline' }}
                        >
                          {isExpanded ? 'Show less' : 'Expand'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      ))}

      <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--bg-secondary)', display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          {saveSuccess && <p style={{ color: 'var(--color-success)', margin: 0 }}>✓ Selection saved successfully</p>}
          {saveError && <p className="error" style={{ margin: 0 }}>{saveError}</p>}
        </div>
        <button
          className="primary"
          onClick={saveSelection}
          disabled={saving || selected.size !== 48}
          style={{ opacity: selected.size !== 48 ? 0.5 : 1 }}
        >
          {saving ? 'Saving…' : 'Save Selection'}
        </button>
      </div>
    </div>
  )
}

function MySubmissions({ auth }) {
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
  const isAdminView = auth?.role === 'admin'
  const [subs, setSubs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editScores, setEditScores] = useState({})
  const [editNotes, setEditNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [expanded, setExpanded] = useState(new Set())

  const load = async () => {
    setLoading(true); setError('')
    try {
      const r = await fetch(apiUrl('/submissions'), { headers: authHeaders() })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `Request failed (${r.status})`)
      setSubs(Array.isArray(data.submissions) ? data.submissions : [])
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const fmtDate = (ts) => {
    if (!ts) return 'Unknown date'
    const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : ts + 'Z'
    const d = new Date(iso)
    return isNaN(d.getTime()) ? ts : d.toLocaleString()
  }
  const langLabel = (code) => LANGUAGE_LABELS[code] || code || '—'
  const avgOf = (scores) => {
    const vals = KEYS.map(([k]) => scores?.[k]).filter(v => typeof v === 'number')
    if (!vals.length) return null
    return vals.reduce((a, b) => a + b, 0) / vals.length
  }
  const scoreColor = (v) => v === 2 ? '#1a7f37' : v === 1 ? '#b7791f' : v === 0 ? '#b42318' : 'rgba(128,128,128,0.7)'

  const startEdit = (s) => {
    setEditingId(s.id); setNotice('')
    setEditScores(Object.fromEntries(KEYS.map(([k]) => [k, typeof s.scores?.[k] === 'number' ? s.scores[k] : 1])))
    setEditNotes(s.notes || '')
  }
  const cancelEdit = () => { setEditingId(null); setEditScores({}); setEditNotes('') }
  const changeScore = (k, v) => setEditScores(s => ({ ...s, [k]: Number(v) }))

  const saveEdit = async (id) => {
    setSaving(true); setError('')
    try {
      const r = await fetch(apiUrl(`/submissions/${encodeURIComponent(id)}`), {
        method: 'PUT', headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ scores: editScores, notes: editNotes })
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof d?.detail === 'string' ? d.detail : `Update failed (${r.status})`)
      setSubs(prev => prev.map(s => s.id === id ? (d.submission || s) : s))
      setNotice('Submission updated.')
      cancelEdit()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setSaving(false)
    }
  }
  const removeSub = async (id) => {
    if (!window.confirm('Delete this submission? This action cannot be undone.')) return
    setBusyId(id); setError('')
    try {
      const r = await fetch(apiUrl(`/submissions/${encodeURIComponent(id)}`), { method: 'DELETE', headers: authHeaders() })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof d?.detail === 'string' ? d.detail : `Delete failed (${r.status})`)
      setSubs(prev => prev.filter(s => s.id !== id))
      setNotice('Submission deleted.')
      if (editingId === id) cancelEdit()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setBusyId(null)
    }
  }
  const toggleExpand = (id) => setExpanded(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  const q = query.trim().toLowerCase()
  const filtered = !q ? subs : subs.filter(s =>
    [s.evaluator_name, s.evaluator_id, s.language, s.source_segment, s.translated_segment, s.notes]
      .filter(Boolean).some(v => String(v).toLowerCase().includes(q)))

  const cardBorder = '1px solid var(--border-color, rgba(128,128,128,0.35))'

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0 }}>My Submissions</h2>
          <p style={{ opacity: 0.8, margin: '4px 0 0 0' }}>
            {isAdminView
              ? 'Reviewing every evaluator’s submissions. You can edit or delete any record.'
              : 'Review, edit, or remove the human evaluations you have submitted.'}
          </p>
        </div>
        <button onClick={load} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder={isAdminView ? 'Search by evaluator, language, or text…' : 'Search your submissions…'}
          style={{ flex: 1, minWidth: 220, padding: '8px 10px' }}
        />
        <span className="pill">{filtered.length} {filtered.length === 1 ? 'record' : 'records'}</span>
      </div>

      {notice && <p style={{ marginTop: 10, color: '#1a7f37' }}>{notice}</p>}
      {error && <p className="error" style={{ marginTop: 10 }}>{error}</p>}

      {loading ? (
        <div style={{ marginTop: 16 }}><LoadingLabel text="Loading submissions…" /></div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ marginTop: 12, padding: 16, textAlign: 'center', opacity: 0.85 }}>
          <p style={{ margin: 0 }}>
            {subs.length === 0
              ? 'No submissions yet. Complete a human evaluation to see it here.'
              : 'No submissions match your search.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
          {filtered.map(s => {
            const editing = editingId === s.id
            const avg = avgOf(s.scores)
            const isLongSrc = (s.source_segment || '').length > 220
            const isLongTr = (s.translated_segment || '').length > 220
            const open = expanded.has(s.id)
            return (
              <div key={s.id} className="card" style={{ padding: 14, border: cardBorder }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <strong>{fmtDate(s.timestamp)}</strong>
                    <span className="pill">{langLabel(s.language)}</span>
                    {isAdminView && <span className="pill" title={s.evaluator_id}>{s.evaluator_name || s.evaluator_id || 'Anonymous'}</span>}
                  </div>
                  {avg != null && (
                    <span className="pill" style={{ background: 'transparent', border: `1px solid ${scoreColor(Math.round(avg))}`, color: scoreColor(Math.round(avg)) }}>
                      Avg {avg.toFixed(2)} / 2
                    </span>
                  )}
                </div>

                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 12, opacity: 0.7, textTransform: 'uppercase', letterSpacing: 0.4 }}>Source</div>
                  <div style={{ marginTop: 2 }}>{open || !isLongSrc ? s.source_segment : `${(s.source_segment || '').substring(0, 220)}…`}</div>
                </div>
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 12, opacity: 0.7, textTransform: 'uppercase', letterSpacing: 0.4 }}>Translation</div>
                  <div style={{ marginTop: 2 }}>{open || !isLongTr ? s.translated_segment : `${(s.translated_segment || '').substring(0, 220)}…`}</div>
                </div>
                {(isLongSrc || isLongTr) && (
                  <button onClick={() => toggleExpand(s.id)} style={{ marginTop: 6, padding: '2px 8px', fontSize: 13 }}>
                    {open ? 'Show less' : 'Show full text'}
                  </button>
                )}

                {editing ? (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
                      {KEYS.map(([k, label]) => (
                        <label key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                          <span>{label}</span>
                          <select value={editScores[k]} onChange={e => changeScore(k, e.target.value)}>
                            <option value={0}>0</option>
                            <option value={1}>1</option>
                            <option value={2}>2</option>
                          </select>
                        </label>
                      ))}
                    </div>
                    <textarea
                      value={editNotes}
                      onChange={e => setEditNotes(e.target.value)}
                      rows={3}
                      placeholder="Notes / rationale (optional)"
                      style={{ width: '100%', marginTop: 10, resize: 'vertical' }}
                    />
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <button className="primary" onClick={() => saveEdit(s.id)} disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button>
                      <button onClick={cancelEdit} disabled={saving}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 6, marginTop: 12 }}>
                      {KEYS.map(([k, label]) => (
                        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13 }}>
                          <span style={{ opacity: 0.85 }}>{label}</span>
                          <strong style={{ color: scoreColor(s.scores?.[k]) }}>{typeof s.scores?.[k] === 'number' ? s.scores[k] : '—'}</strong>
                        </div>
                      ))}
                    </div>
                    {s.notes && (
                      <div style={{ marginTop: 10 }}>
                        <div style={{ fontSize: 12, opacity: 0.7, textTransform: 'uppercase', letterSpacing: 0.4 }}>Notes</div>
                        <div style={{ marginTop: 2, whiteSpace: 'pre-wrap' }}>{s.notes}</div>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                      <button className="primary" onClick={() => startEdit(s)}>Edit</button>
                      <button onClick={() => removeSub(s.id)} disabled={busyId === s.id} style={{ color: '#b42318' }}>
                        {busyId === s.id ? 'Deleting…' : 'Delete'}
                      </button>
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('Health')
  const [light, setLight] = useState(() => {
    try {
      const saved = localStorage.getItem('ui_theme')
      if (saved === 'light') return true
      if (saved === 'dark') return false
    } catch {}
    return true
  })
  const [collapsed, setCollapsed] = useState(false)
  const [auth, setAuth] = useState(() => {
    try {
      const raw = sessionStorage.getItem('ui_auth')
      if (!raw) return null
      const parsed = JSON.parse(raw)
      if (!parsed?.role || !parsed?.username || !parsed?.token) return null
      return parsed
    } catch {
      return null
    }
  })
  const [authChecking, setAuthChecking] = useState(true)

  const availableTabs = auth?.role === 'admin' ? DEFAULT_TABS : USER_TABS

  useEffect(() => {
    if (!availableTabs.includes(tab)) {
      setTab(availableTabs[0] || 'Health')
    }
  }, [auth, tab])

  useEffect(() => {
    const validate = async () => {
      if (!auth?.token) {
        setAuthChecking(false)
        return
      }
      try {
        const r = await fetch(apiUrl('/auth/session'), {
          headers: { Authorization: `Bearer ${auth.token}` }
        })
        if (!r.ok) {
          setAuth(null)
          try { sessionStorage.removeItem('ui_auth') } catch {}
        }
      } catch {
        setAuth(null)
        try { sessionStorage.removeItem('ui_auth') } catch {}
      } finally {
        setAuthChecking(false)
      }
    }
    validate()
  }, [])

  useEffect(() => {
    document.body.classList.toggle('light', light)
    try { localStorage.setItem('ui_theme', light ? 'light' : 'dark') } catch {}
  }, [light])

  const handleLogin = async ({ idToken }) => {
    try {
      const r = await fetch(apiUrl('/auth/google'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: idToken })
      })
      const data = await r.json()
      if (!r.ok) {
        return { ok: false, error: data?.detail || 'This account is not authorized' }
      }
      const session = {
        role: data.role,
        username: data.username,
        email: data.email,
        language: data.language || null,
        token: data.token,
        expires_at: data.expires_at,
      }
      setAuth(session)
      try { sessionStorage.setItem('ui_auth', JSON.stringify(session)) } catch {}
      setTab('Health')
      return { ok: true }
    } catch {
      return { ok: false, error: 'Unable to reach authentication service' }
    }
  }

  const handleLogout = () => {
    setAuth(null)
    try { sessionStorage.removeItem('ui_auth') } catch {}
    if (firebaseAuth) { signOut(firebaseAuth).catch(() => {}) }
    setTab('Health')
  }

  if (authChecking) {
    return (
      <div className="container" style={{ maxWidth: 560, paddingTop: 40 }}>
        <div className="card" style={{ padding: 16 }}>
          <LoadingLabel text="Checking session…" />
        </div>
      </div>
    )
  }

  if (!auth) {
    return <LoginPage onLogin={handleLogin} light={light} onToggleTheme={() => setLight(v => !v)} />
  }

  return (
    <>
      <header className="header">
        <div className="brand">IPAWS Research UI ({auth.role === 'admin' ? 'Admin' : 'User'})</div>
        <div className="row">
          <span style={{ opacity: 0.85, marginRight: 4 }}>Welcome, <strong>{auth.username}</strong></span>
          <button className="theme-toggle" onClick={() => setLight(v => !v)}>{light ? 'Dark' : 'Light'} Theme</button>
          <button onClick={handleLogout}>Logout</button>
        </div>
      </header>
      <div className="container">
        <div className={`app-layout ${collapsed ? 'collapsed' : ''}`}>
          <Nav current={tab} onChange={setTab} collapsed={collapsed} onToggleCollapse={() => setCollapsed(v => !v)} tabs={availableTabs} />
          <main>
            {tab === 'Health' && <Health onNavigate={setTab} />}
            {tab === 'Alerts' && <Alerts />}
            {tab === 'Single Eval' && <SingleEval />}
            {tab === 'Human Eval' && <HumanEval />}
            {tab === 'Batch Eval' && <BatchEval />}
            {tab === 'Whole Eval' && <WholeEval />}
            {tab === 'My Submissions' && <MySubmissions auth={auth} />}
            {tab === 'Alert Pool' && auth?.role === 'admin' && <AlertPool auth={auth} />}
            {tab === 'Admin Analytics' && auth?.role === 'admin' && <AdminAnalytics auth={auth} />}
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
  const [language, setLanguage] = useState(() => resolveLanguage(sessionStorage.getItem('he_language')))
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
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          source_segment: source,
          translated_segment: translated,
          language,
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
      <p style={{ opacity: 0.8, marginTop: 4 }}>Signed in as <strong>{getStoredAuth()?.username || 'Unknown'}</strong>{getStoredAuth()?.email ? ` (${getStoredAuth().email})` : ''} — submissions are recorded under this account.</p>
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
  const [targetLanguage, setTargetLanguage] = useState(() => resolveLanguage(sessionStorage.getItem('batch_language')))
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
  const [translationError, setTranslationError] = useState('')
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
  const [compare, setCompare] = useState(true)
  const translationRef = useRef(null)
  const sourcePaneRef = useRef(null)
  const autoTranslateKeyRef = useRef('')
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
    const maxH = 300
    const h = el.scrollHeight
    el.style.height = Math.min(h, maxH) + 'px'
    el.style.overflow = h > maxH ? 'auto' : 'hidden'
  }, [translation, compare])
  useEffect(() => { try { sessionStorage.setItem('batch_language', targetLanguage) } catch {} }, [targetLanguage])
  useEffect(() => { try { sessionStorage.setItem('batch_translation', translation) } catch {} }, [translation])
  useEffect(() => { try { sessionStorage.setItem('batch_use_whole', useWholeMessage ? '1' : '0') } catch {} }, [useWholeMessage])

  const loadBatch = async () => {
    setLoadingAlerts(true); setAlertError(null)
    try {
      const params = new URLSearchParams({ daysBack, state: stateCode })
      const r = await fetch(apiUrl('/alerts?' + params.toString()))
      const data = await r.json()
      const normalizedAlerts = (Array.isArray(data) ? data : []).slice().sort((a, b) => {
        const ta = a?.timestamp ? new Date(a.timestamp).getTime() : 0
        const tb = b?.timestamp ? new Date(b.timestamp).getTime() : 0
        return tb - ta
      })
      setAlerts(normalizedAlerts)
      setIdx(0)
      setSegments([])
      setSegIdx(0)
      setTranslation('')
      setTranslationError('')
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

  const selectAlertIndex = (nextIdx) => {
    const safeIdx = Math.max(0, Math.min(alerts.length - 1, nextIdx))
    setIdx(safeIdx)
    setSegments([])
    setSegIdx(0)
    setAutoEval(null)
    setTranslation('')
    setTranslationError('')
  }

  useEffect(() => {
    const alertId = currentAlert?.alert_id || ''
    const sourceKey = useWholeMessage ? `whole:${alertId}` : `segment:${alertId}:${segIdx}`
    const key = `${targetLanguage}|${sourceKey}|${currentText}`
    if (!currentText || autoLoading) return
    if (autoTranslateKeyRef.current === key) return
    autoTranslateKeyRef.current = key
    autoTranslate()
  }, [currentText, currentAlert, segIdx, useWholeMessage, targetLanguage])

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
    setTranslationError('')
    try {
      const r = await fetch(apiUrl('/translate'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_text: currentText, target_language: targetLanguage, system: 'gemini' })
      })
      const data = await r.json()
      if (!r.ok) {
        setTranslation('')
        setTranslationError(data?.detail || 'Unable to translate right now.')
        return
      }
      setTranslation(data.translation || '')
      if (!data.translation) setTranslationError('No translation was returned for this message.')
    } catch (e) {
      setTranslation('')
      setTranslationError(String(e))
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
        method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ source_segment: currentText, translated_segment: translation, language: targetLanguage, scores, rationale: notes ? { notes } : {} })
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
      <p style={{ opacity: 0.8, marginTop: 4 }}>Use this page for alert-by-alert review with automatic translation and manual scoring.</p>
      <EvalContextStrip
        mode={useWholeMessage ? 'Whole Message' : 'Segmented'}
        language={targetLanguage}
        currentIndex={idx}
        total={alerts.length}
        alertId={currentAlert?.alert_id}
        loading={autoLoading || loadingAlerts || loadingSegs}
        error={translationError}
      />
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
              {LanguageOptions()}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={useWholeMessage} onChange={e => setUseWholeMessage(e.target.checked)} />
            Use whole message (no segmentation)
          </label>
          <button className="primary" onClick={loadBatch} disabled={loadingAlerts}>{loadingAlerts ? <LoadingLabel text="Loading Alerts…" /> : 'Load Alerts'}</button>
        </div>
        {alertError && <p className="error" style={{ marginTop: 8 }}>{alertError}</p>}
      </div>

      <details className="collapse card" style={{ padding: 12, marginTop: 12 }}>
        <summary>Alerts</summary>
        <div style={{ marginTop: 8 }}>
          <AlertSummary alert={currentAlert} />
          <AlertsTable alerts={alerts} selectedId={alerts[idx]?.alert_id} pageSizeOptions={[1,10,25,50,100]} initialPageSize={1} showPager={false} onSelect={(a) => {
            const i = alerts.findIndex(x => x.alert_id === a.alert_id)
            selectAlertIndex(i >= 0 ? i : 0)
          }} />
          {!useWholeMessage && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button onClick={loadSegments} disabled={!currentAlert || loadingSegs}>{loadingSegs ? <LoadingLabel text="Segmenting…" /> : 'Segment Selected'}</button>
            </div>
          )}
        </div>
      </details>

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

      {alerts.length === 0 && (
        <div className="card" style={{ padding: 12, marginTop: 12 }}>
          <p style={{ margin: 0 }}>No alerts loaded yet. Click <strong>Load Alerts</strong> to begin.</p>
        </div>
      )}

      {!useWholeMessage && alerts.length > 0 && (
        <div className="card" style={{ padding: 12, marginTop: 12 }}>
          <h3>Segments</h3>
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
        </div>
      )}

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Translation</h3>
          {autoLoading && <LoadingLabel text="Translating…" />}
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              {LanguageOptions()}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={compare} onChange={e => setCompare(e.target.checked)} /> Compare mode
          </label>
        </div>
        {compare ? (
          <div className="two-col" style={{ marginTop: 8 }}>
            <div>
              <h4 style={{ margin: 0 }}>Source</h4>
              <div ref={sourcePaneRef} onScroll={onSourceScroll} className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap', maxHeight: 300 }}>{currentText}</div>
            </div>
            <div>
              <h4 style={{ margin: 0 }}>Translation</h4>
              <textarea ref={translationRef} onScroll={onTransScroll} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, resize: 'none', maxHeight: 300 }} placeholder="Translated segment" />
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 8 }}>
            <h4 style={{ margin: 0 }}>Source</h4>
            <div className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap', maxHeight: 300 }}>{currentText}</div>
            <h4 style={{ margin: '10px 0 0 0' }}>Translation</h4>
            <textarea ref={translationRef} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, resize: 'none', maxHeight: 300 }} placeholder="Translated segment" />
          </div>
        )}
        <div className="sticky-actions">
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

      <div className="bottom-nav" style={{ marginTop: 12 }}>
        <button className="primary" onClick={() => selectAlertIndex(idx - 1)} disabled={idx <= 0}>Back</button>
        <button className="primary" onClick={() => selectAlertIndex(idx + 1)} disabled={idx >= alerts.length - 1 || alerts.length === 0}>Next</button>
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
  const [targetLanguage, setTargetLanguage] = useState(() => resolveLanguage(sessionStorage.getItem('whole_language')))
  const [alerts, setAlerts] = useState([])
  const [loadingAlerts, setLoadingAlerts] = useState(false)
  const [alertError, setAlertError] = useState(null)
  const [idx, setIdx] = useState(0)
  const [translation, setTranslation] = useState(() => sessionStorage.getItem('whole_translation') || '')
  const [autoEval, setAutoEval] = useState(null)
  const [humanSaved, setHumanSaved] = useState(null)
  const [autoLoading, setAutoLoading] = useState(false)
  const [translationError, setTranslationError] = useState('')
  const [compare, setCompare] = useState(true)
  const translationRef = useRef(null)
  const sourcePaneRef = useRef(null)
  const autoTranslateKeyRef = useRef('')

  useEffect(() => { try { sessionStorage.setItem('whole_language', targetLanguage) } catch {} }, [targetLanguage])
  useEffect(() => { try { sessionStorage.setItem('whole_translation', translation) } catch {} }, [translation])
  useEffect(() => {
    const el = translationRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxH = 300
    const h = el.scrollHeight
    el.style.height = Math.min(h, maxH) + 'px'
    el.style.overflow = h > maxH ? 'auto' : 'hidden'
  }, [translation, compare])

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
      const params = new URLSearchParams({ source: 'research' })
      const r = await fetch(apiUrl('/alerts?' + params.toString()))
      const data = await r.json()
      const normalizedAlerts = (Array.isArray(data) ? data : []).slice().sort((a, b) => {
        const ta = a?.timestamp ? new Date(a.timestamp).getTime() : 0
        const tb = b?.timestamp ? new Date(b.timestamp).getTime() : 0
        return tb - ta
      })
      setAlerts(normalizedAlerts)
      setIdx(0)
      setTranslation('')
      setTranslationError('')
      setAutoEval(null)
      setHumanSaved(null)
    } catch (e) {
      setAlertError(String(e))
    } finally {
      setLoadingAlerts(false)
    }
  }

  // Auto-load the admin-selected alert pool on mount.
  useEffect(() => { loadBatch() }, [])

  const currentAlert = alerts[idx]
  const currentText = currentAlert?.source_text || ''

  const selectAlertIndex = (nextIdx) => {
    const safeIdx = Math.max(0, Math.min(alerts.length - 1, nextIdx))
    setIdx(safeIdx)
    setTranslation('')
    setTranslationError('')
    setAutoEval(null)
    setHumanSaved(null)
  }

  useEffect(() => {
    const alertId = currentAlert?.alert_id || ''
    const key = `${targetLanguage}|${alertId}|${currentText}`
    if (!currentText || autoLoading) return
    if (autoTranslateKeyRef.current === key) return
    autoTranslateKeyRef.current = key
    autoTranslate()
  }, [currentAlert, currentText, targetLanguage])

  const autoTranslate = async () => {
    if (!currentText) return
    setAutoLoading(true)
    setTranslationError('')
    try {
      const r = await fetch(apiUrl('/translate'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_text: currentText, target_language: targetLanguage, system: 'gemini' })
      })
      const data = await r.json()
      if (!r.ok) {
        setTranslation('')
        setTranslationError(data?.detail || 'Unable to translate right now.')
        return
      }
      setTranslation(data.translation || '')
      if (!data.translation) setTranslationError('No translation was returned for this message.')
    } catch (e) {
      setTranslation('')
      setTranslationError(String(e))
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
        method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ source_segment: currentText, translated_segment: translation, language: targetLanguage, scores, rationale: notes ? { notes } : {} })
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
      <p style={{ opacity: 0.8, marginTop: 4 }}>Use this page for full-message translation review and scoring without segmentation.</p>
      <EvalContextStrip
        mode="Whole Message"
        language={targetLanguage}
        currentIndex={idx}
        total={alerts.length}
        alertId={currentAlert?.alert_id}
        loading={autoLoading || loadingAlerts}
        error={translationError}
      />
      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              {LanguageOptions()}
            </select>
          </label>
          {loadingAlerts && <LoadingLabel text="Loading Alerts…" />}
        </div>
        {alertError && <p className="error" style={{ marginTop: 8 }}>{alertError}</p>}
      </div>

      <details className="collapse card" style={{ padding: 12, marginTop: 12 }}>
        <summary>Alerts</summary>
        <div style={{ marginTop: 8 }}>
          <AlertsTable alerts={alerts} selectedId={alerts[idx]?.alert_id} pageSizeOptions={[1,10,25,50,100]} initialPageSize={1} showPager={false} onSelect={(a) => {
            const i = alerts.findIndex(x => x.alert_id === a.alert_id)
            selectAlertIndex(i >= 0 ? i : 0)
          }} />
        </div>
      </details>

      {alerts.length === 0 && (
        <div className="card" style={{ padding: 12, marginTop: 12 }}>
          <p style={{ margin: 0 }}>{loadingAlerts ? 'Loading alerts…' : 'No alerts available.'}</p>
        </div>
      )}

      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0, flex: 1 }}>Translation</h3>
          {autoLoading && <LoadingLabel text="Translating…" />}
          <label>Language
            <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}>
              {LanguageOptions()}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={compare} onChange={e => setCompare(e.target.checked)} /> Compare mode
          </label>
        </div>
        {compare ? (
          <div className="two-col" style={{ marginTop: 8 }}>
            <div>
              <h4 style={{ margin: 0 }}>Source</h4>
              <div ref={sourcePaneRef} onScroll={onSourceScroll} className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap', maxHeight: 300 }}>{currentText}</div>
            </div>
            <div>
              <h4 style={{ margin: 0 }}>Translation</h4>
              <textarea ref={translationRef} onScroll={onTransScroll} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, resize: 'none', maxHeight: 300 }} placeholder="Translated message" />
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 8 }}>
            <h4 style={{ margin: 0 }}>Source</h4>
            <div className="pane" style={{ marginTop: 6, whiteSpace: 'pre-wrap', maxHeight: 300 }}>{currentText}</div>
            <h4 style={{ margin: '10px 0 0 0' }}>Translation</h4>
            <textarea ref={translationRef} value={translation} onChange={e => setTranslation(e.target.value)} rows={6} style={{ width: '100%', marginTop: 6, resize: 'none', maxHeight: 300 }} placeholder="Translated message" />
          </div>
        )}
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

      <div className="bottom-nav" style={{ marginTop: 12 }}>
        <button className="primary" onClick={() => selectAlertIndex(idx - 1)} disabled={idx <= 0}>Back</button>
        <button className="primary" onClick={() => selectAlertIndex(idx + 1)} disabled={idx >= alerts.length - 1 || alerts.length === 0}>Next</button>
      </div>
    </div>
  )
}
