import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/config': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
      '/alerts': 'http://127.0.0.1:8000',
      '/segment': 'http://127.0.0.1:8000',
      '/translate': 'http://127.0.0.1:8000',
      '/evaluate': 'http://127.0.0.1:8000',
      '/submissions': 'http://127.0.0.1:8000',
      '/templates': 'http://127.0.0.1:8000',
      '/pipeline': 'http://127.0.0.1:8000',
    },
  },
})
