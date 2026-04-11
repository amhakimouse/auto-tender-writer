import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',   // Required for Docker to expose port
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://api:8000',  // 'api' = Docker service name
        changeOrigin: true,
      }
    }
  }
})
