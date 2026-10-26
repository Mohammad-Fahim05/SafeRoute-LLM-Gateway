import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'dev-auth-helper',
      configureServer(server) {
        server.middlewares.use('/_dev/key', (_req, res) => {
          const keyPath = path.resolve(process.cwd(), '../.dev_api_key.txt');
          if (fs.existsSync(keyPath)) {
            const key = fs.readFileSync(keyPath, 'utf-8').trim();
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ key }));
          } else {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: 'not found' }));
          }
        });
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ready': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/metrics': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
