import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://localhost:5000',
      '/config': 'http://localhost:5000',
      '/alerts': 'http://localhost:5000',
      '/segment': 'http://localhost:5000',
      '/translate': 'http://localhost:5000',
      '/evaluate': 'http://localhost:5000',
      '/evaluate/human': 'http://localhost:5000',
      '/templates': 'http://localhost:5000',
    },
  },
})
