import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'katex/dist/katex.min.css'
import './index.css'
import { ErrorBoundary } from './ErrorBoundary'
import { initializeRuntimeConfig } from './runtimeConfig'

async function bootstrap() {
  try {
    await initializeRuntimeConfig()
  } catch (error) {
    // Continue bootstrapping so App can surface startup diagnostics and retry actions.
    console.error('Desktop runtime initialization failed', error)
  }
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
