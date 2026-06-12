import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'katex/dist/katex.min.css'
import './index.css'
import { ErrorBoundary } from './ErrorBoundary'

async function bootstrap() {
  // Mount React immediately and let App drive the (potentially slow) desktop
  // sidecar startup. Awaiting the backend here would leave the static
  // index.html placeholder ("Launching backend…") frozen on screen for the
  // entire boot — with no spinner, progress, or error — which on slower
  // machines looks like the app is permanently stuck.
  const { default: App } = await import('./App.tsx')

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </StrictMode>,
  )
}

bootstrap().catch((error) => {
  console.error('Failed to bootstrap runtime', error)
  const root = document.getElementById('root')
  if (root) {
    root.textContent = 'Failed to start app shell. Check logs and restart the app.'
  }
})
