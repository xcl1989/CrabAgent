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
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-charts": ["recharts"],
          "vendor-markdown": [
            "react-markdown",
            "remark-gfm",
            "rehype-highlight",
            "highlight.js",
          ],
          "vendor-ui": [
            "@radix-ui/react-dialog",
            "@radix-ui/react-tooltip",
            "lucide-react",
            "sonner",
          ],
        },
      },
    },
  },
});
