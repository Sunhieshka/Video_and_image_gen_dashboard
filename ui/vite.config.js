import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The API port, so `API_PORT=8010 npm run dev` follows a backend that is not
// on the default port.
const apiPort = process.env.API_PORT || '8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev server talks to the FastAPI backend, so the app can use relative /api
    // paths in both development and the built bundle. /files is where uploaded
    // reference media is served from.
    proxy: {
      '/api': `http://127.0.0.1:${apiPort}`,
      '/files': `http://127.0.0.1:${apiPort}`,
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
