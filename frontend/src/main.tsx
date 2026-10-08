import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./pet.css";
import "./i18n";
import App from "./App";
import { ThemeProvider } from "./lib/theme";
import { Toaster } from "./components/ui/Toast";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { WorkStatusProvider } from "./hooks/useWorkStatus";
import { api } from "./api/client";
import { bootstrapPetAuth } from "./lib/pets/bootstrapPetAuth";

function mountApp() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <ThemeProvider>
        <AppErrorBoundary>
          <WorkStatusProvider>
            <App />
          </WorkStatusProvider>
        </AppErrorBoundary>
        <Toaster />
      </ThemeProvider>
    </StrictMode>,
  );
}

async function initializeApp() {
  const isPet = new URLSearchParams(window.location.search).get("surface") === "pet";
  if (isPet && window.electronAPI?.getPetAuthToken) {
    try {
      await bootstrapPetAuth(api, window.electronAPI.getPetAuthToken);
    } catch {
      // Wait without mounting API consumers or clearing the main window session.
      window.setTimeout(() => void initializeApp(), 1000);
      return;
    }
  }
  mountApp();
}

void initializeApp();
