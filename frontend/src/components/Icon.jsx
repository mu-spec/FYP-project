const ICONS = {
  shield: (
    <path d="M12 3.2 19 6v5.1c0 4.6-2.9 8.5-7 9.7-4.1-1.2-7-5.1-7-9.7V6l7-2.8Z" />
  ),
  search: (
    <><circle cx="10.8" cy="10.8" r="6.4" /><path d="m16 16 4.2 4.2" /></>
  ),
  arrow: <path d="M5 12h13m-5-5 5 5-5 5" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  check: <path d="m5 12 4.2 4.2L19 6.5" />,
  warning: <><path d="m12 4 8 15H4L12 4Z" /><path d="M12 9v4.2M12 16.2h.01" /></>,
  brain: <><path d="M9.2 4.4a3 3 0 0 0-5.1 2.1 3.3 3.3 0 0 0 .4 6.4A3 3 0 0 0 7 18.3a3 3 0 0 0 5-2.2V6.2a3 3 0 0 0-2.8-1.8Z" /><path d="M14.8 4.4a3 3 0 0 1 5.1 2.1 3.3 3.3 0 0 1-.4 6.4 3 3 0 0 1-2.5 5.4 3 3 0 0 1-5-2.2V6.2a3 3 0 0 1 2.8-1.8ZM7.2 8.3h2M14.8 8.3h2M7.5 13.4h1.7M14.8 13.4h1.7" /></>,
  file: <><path d="M6 3.5h7l5 5v12H6z" /><path d="M13 3.5v5h5M9 13h6M9 16.5h6" /></>,
  chart: <><path d="M4 19.5V4.5M4 19.5h16" /><path d="m7 15 3-3 2.2 1.8L17.5 8" /></>,
  history: <><path d="M4.2 8.5A8 8 0 1 1 4 13" /><path d="M4.2 4.5v4h4" /><path d="M12 8v4l2.8 1.8" /></>,
  filter: <><path d="M4 6h16M7 12h10M10 18h4" /></>,
  calendar: <><rect x="4" y="5.5" width="16" height="15" rx="2" /><path d="M8 3.5v4M16 3.5v4M4 10h16" /></>,
  close: <><path d="m6 6 12 12M18 6 6 18" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  external: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 10.7v5M12 7.7h.01" /></>,
  lock: <><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7.5a4 4 0 0 1 8 0V10" /></>,
  spark: <path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" />,
}

export default function Icon({ name, size = 20, strokeWidth = 1.8, className = '' }) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name] || ICONS.info}
    </svg>
  )
}
