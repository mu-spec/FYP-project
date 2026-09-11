import Icon from './Icon.jsx'

const NAV_ITEMS = [
  { id: 'home', label: 'Home' },
  { id: 'analyze', label: 'Analyze' },
  { id: 'history', label: 'History' },
  { id: 'insights', label: 'Insights' },
  { id: 'about', label: 'About' },
]

export default function Header({ page, onNavigate, backendUp, health }) {
  const statusLabel = backendUp === null
    ? 'Checking service'
    : backendUp
      ? health?.model_loaded ? 'Model ready' : 'API online'
      : 'API offline'

  return (
    <header className="site-header">
      <div className="container header-inner">
        <button className="brand" type="button" onClick={() => onNavigate('home')} aria-label="Go to home">
          <span className="brand-mark"><Icon name="shield" size={21} strokeWidth={2} /></span>
          <span className="brand-copy">
            <strong>JobGuard</strong>
            <span>AI job screening</span>
          </span>
        </button>

        <nav className="main-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-link ${page === item.id ? 'active' : ''}`}
              onClick={() => onNavigate(item.id)}
              aria-current={page === item.id ? 'page' : undefined}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className={`service-status ${backendUp === null ? 'checking' : backendUp ? 'online' : 'offline'}`}>
          <span className="status-dot" />
          <span>{statusLabel}</span>
        </div>
      </div>
    </header>
  )
}
