import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// Set VITE_HTTPS=1 to serve the dev server over TLS with a self-signed
// certificate. Needed to test on a real phone: browsers only expose
// navigator.geolocation in a secure context, and http://<lan-ip> is not one —
// so the "use my location" button silently does nothing without this.
// The certificate is self-signed, so the phone shows a warning to accept once.
const useHttps = process.env.VITE_HTTPS === '1'

export default defineConfig({
  plugins: [react(), ...(useHttps ? [basicSsl()] : [])],
  // maplibre's worker is an ES module and imports a shared chunk, so it has to
  // be emitted as one.
  worker: { format: 'es' },
  optimizeDeps: {
    // maplibre-gl loads its parsing Web Worker from a URL relative to its own
    // module. Vite's dependency pre-bundling rewrites the module but not that
    // worker URL, so the worker 404s. The basemap still draws (raster tiles
    // need no worker) while every GeoJSON layer silently renders nothing —
    // a map with no pins on it and no error in sight.
    exclude: ['maplibre-gl'],
  },
  server: {
    port: 5173,
    // Listen on all interfaces (IPv4 included) so a phone on the same Wi-Fi can
    // open the dev server. This is a development convenience — anyone on that
    // network can reach it, so do not enable it on an untrusted network.
    host: true,
    // Dev server talks to the FastAPI app so the frontend uses the same
    // same-origin paths it will use in production.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/uploads': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 1200 },
})
