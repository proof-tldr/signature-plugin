import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The build ships inside the plugin's Python package, which serves it to the customer's browser from this machine.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../server/src/signature_plugin/web',
    emptyOutDir: true,
    // ELK is split out and loaded only for the map, from the customer's own machine: its size costs no download.
    chunkSizeWarningLimit: 1600,
  },
})
