import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./pet.css";
import "./i18n";
import App from "./App";
import { ThemeProvider } from "./lib/theme";
import { Toaster } from "./components/ui/Toast";
import { AppErrorBoundary } from "./components/AppErrorBoundary";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <AppErrorBoundary>
        <App />
      </AppErrorBoundary>
      <Toaster />
    </ThemeProvider>
  </StrictMode>,
);
