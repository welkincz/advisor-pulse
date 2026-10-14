import { createReadStream, existsSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const fixtures = resolve(process.env.PULSE_FIXTURES_DIR ?? resolve(import.meta.dirname, '../fixtures/exports'))

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'fixture-data',
      configureServer(server) {
        server.middlewares.use('/data', (request, response, next) => {
          const path = resolve(fixtures, `.${decodeURIComponent(request.url ?? '/')}`)
          if (!path.startsWith(`${fixtures}${sep}`) || !existsSync(path)) return next()
          createReadStream(path).on('error', next).pipe(response)
        })
      },
    },
  ],
})
