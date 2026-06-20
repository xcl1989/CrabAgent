const PROVIDERS_CHANGED_EVENT = "crabagent:providers-changed";

export function emitProvidersChanged() {
  window.dispatchEvent(new CustomEvent(PROVIDERS_CHANGED_EVENT));
}

export function onProvidersChanged(listener: () => void) {
  window.addEventListener(PROVIDERS_CHANGED_EVENT, listener);
  return () => window.removeEventListener(PROVIDERS_CHANGED_EVENT, listener);
}
