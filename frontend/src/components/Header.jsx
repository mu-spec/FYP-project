export default function Header({ backendUp, health }) {
  return (
    <header className="header">
      <div className="container header-inner">
        <div className="brand">
          <span className="brand-icon">🛡️</span>
          <span>JobGuard AI</span>
        </div>
        <nav className="nav">
          <a href="#home">Home</a>
          <a href="#detector">Detector</a>
          <a href="#history">History</a>
        </nav>
        <div className={`status-pill ${backendUp ? 'ok' : backendUp === false ? 'down' : ''}`}>
          {backendUp === null ? '…' : backendUp
            ? `API online${health?.model_loaded ? ' · model ready' : ' · no model'}`
            : 'API offline'}
        </div>
      </div>
    </header>
  )
}
