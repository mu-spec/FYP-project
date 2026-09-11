import Icon from './Icon.jsx'

export default function Footer({ onNavigate }) {
  return (
    <footer className="site-footer">
      <div className="container footer-inner">
        <div className="footer-brand">
          <span className="brand-mark small"><Icon name="shield" size={16} strokeWidth={2} /></span>
          <div>
            <strong>JobGuard AI</strong>
            <span>Evidence-led job screening for safer decisions.</span>
          </div>
        </div>
        <div className="footer-links">
          <button type="button" onClick={() => onNavigate('about')}>About the model</button>
          <button type="button" onClick={() => onNavigate('history')}>Prediction history</button>
          <span>FYP application · 2025</span>
        </div>
      </div>
    </footer>
  )
}
