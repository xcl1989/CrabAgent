import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://localhost:5210",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // Keep vendor chunks
          if (id.includes("node_modules/react")) return "vendor-react";
          if (id.includes("node_modules/recharts")) return "vendor-charts";
          if (id.includes("node_modules/react-markdown") || id.includes("node_modules/remark-gfm") || id.includes("node_modules/rehype-highlight") || id.includes("node_modules/highlight")) return "vendor-markdown";
          if (id.includes("node_modules/@radix-ui") || id.includes("node_modules/lucide") || id.includes("node_modules/sonner")) return "vendor-ui";
          // Merge all Univer sub-chunks (locales, dictionaries, etc.) except main entry points
          if (id.includes("@univerjs") && !id.endsWith("/index.js") && !id.endsWith("/facade.js")) return "univer-data";
        },
      },
    },
  },
});
