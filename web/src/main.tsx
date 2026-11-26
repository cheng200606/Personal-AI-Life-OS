import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { registerLifeosServiceWorker, trackLifeosClientFocus } from './pwa'
import { desktop } from './desktopRuntime'

if (!desktop) {
  registerLifeosServiceWorker()
  trackLifeosClientFocus()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
