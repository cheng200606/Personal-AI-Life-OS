import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { registerLifeosServiceWorker, trackLifeosClientFocus } from './pwa'

registerLifeosServiceWorker()
trackLifeosClientFocus()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
