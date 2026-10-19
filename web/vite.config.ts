import { createReadStream, existsSync, statSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const fixtures = resolve(process.env.PULSE_FIXTURES_DIR ?? resolve(import.meta.dirname, '../fixtures/exports'))

export default defineConfig({
  test: { include: ['src/**/*.test.{ts,tsx}'], testTimeout: 20_000 },
  // The case study page imports docs/case-study.md, which sits outside web/.
  server: { fs: { allow: ['..'] } },
  plugins: [
    react(),
    {
      name: 'fixture-data',
      configureServer(server) {
        server.middlewares.use('/data', (request, response) => {
          let path: string
          try {
            const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname)
            path = resolve(fixtures, `.${pathname}`)
          } catch {
            response.statusCode = 400
            response.end('Bad request')
            return
          }
          if (!path.startsWith(`${fixtures}${sep}`) || !existsSync(path) || !statSync(path).isFile()) {
            response.statusCode = 404
            response.end('Not found')
            return
          }
          createReadStream(path).on('error', () => {
            if (response.headersSent) response.destroy()
            else {
              response.statusCode = 404
              response.end('Not found')
            }
          }).pipe(response)
        })
      },
    },
  ],
})
