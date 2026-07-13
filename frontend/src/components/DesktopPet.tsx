import { useCallback, useEffect, useRef, useState } from "react";
import { connectGlobalSSE, type AgentMonitorSummary } from "../api/monitor";
import { getActivePet, getPet, getSpritesheetUrl, type PetDetail } from "../api/pets";
import { SpritePet, type SpritePetConfig } from "./pets";
import {
  derivePetState,
  oneShotAnimation,
  petStateKey,
  type AgentStatus,
  type PetState,
} from "../lib/pets/petStateMachine";

declare global {
  interface Window {
    electronAPI?: {
      petAction: (action: "open-main" | "hide" | "toggle-always-on-top", sessionId?: string) => Promise<boolean>;
      showPetMenu: () => void;
      startPetDrag: (offsetX: number, offsetY: number) => void;
      movePetDrag: () => void;
      endPetDrag: () => void;
      onOpenSession?: (callback: (sessionId: string) => void) => void;
      onPetDragDirection?: (callback: (data: { direction: string | null }) => void) => void;
    };
  }
}

type PetMood = "idle" | "thinking" | "working" | "celebrating" | "error" | "waiting";

interface SvgPetState {
  mood: PetMood;
  label: string;
  detail: string;
}

const INITIAL_SVG_STATE: SvgPetState = {
  mood: "idle",
  label: "CrabAgent",
  detail: "随时可以开始",
};

function stateFromSummary(summary: AgentMonitorSummary): SvgPetState {
  switch (summary.status) {
    case "waiting":
      return { mood: "waiting", label: "需要你处理", detail: `${summary.message} · 点我打开` };
    case "error":
      return { mood: "error", label: "遇到一点问题", detail: `${summary.message} · 点我查看` };
    case "working":
      return { mood: "working", label: "正在工作", detail: summary.message };
    case "thinking":
      return { mood: "thinking", label: "正在思考", detail: summary.message };
    case "completed":
      return { mood: "celebrating", label: "任务完成", detail: summary.message };
    default:
      return INITIAL_SVG_STATE;
  }
}

function svgStateKey(s: SvgPetState): string {
  return `${s.mood}|${s.label}|${s.detail}`;
}

function animationToSvgMood(animation: PetState["animation"]): PetMood {
  switch (animation) {
    case "running":
    case "running-right":
    case "running-left":
      return "working";
    case "waiting":
      return "waiting";
    case "failed":
      return "error";
    case "review":
      return "celebrating";
    default:
      return "idle";
  }
}

interface ActivePetInfo {
  petId: string;
  detail: PetDetail | null;
  spriteConfig: SpritePetConfig | null;
  useSprite: boolean;
}

export function DesktopPet() {
  // ── Active pet selection ──────────────────────────────────────────
  const [activePet, setActivePet] = useState<ActivePetInfo>({
    petId: "builtin-crab",
    detail: null,
    spriteConfig: null,
    useSprite: false,
  });

  // ── Sprite/SVG shared state machine ───────────────────────────────
  const [petState, setPetState] = useState<PetState>({
    animation: "idle",
    loop: true,
    baseAfter: "idle",
    label: INITIAL_SVG_STATE.label,
    detail: INITIAL_SVG_STATE.detail,
    targetSessionId: null,
  });

  // For one-shot animations we need to know what state to restore to.
  const baseStateRef = useRef<PetState>(petState);

  // ── Legacy SVG-only state (used when sprite pet is disabled) ───────
  const [svgState, setSvgState] = useState<SvgPetState>(INITIAL_SVG_STATE);

  // ── Shared refs ───────────────────────────────────────────────────
  const targetSessionRef = useRef<string | null>(null);
  const stateKeyRef = useRef("");
  const svgStateKeyRef = useRef("");
  const syncInFlightRef = useRef(false);
  const syncTimerRef = useRef<number | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const dragged = useRef(false);

  // ── Load active pet on mount and when storage changes ──────────────
  const loadActivePet = useCallback(async () => {
    try {
      const petId = await getActivePet();
      if (!petId || petId === "builtin-crab") {
        setActivePet({ petId: "builtin-crab", detail: null, spriteConfig: null, useSprite: false });
        return;
      }
      const detail = await getPet(petId);
      if (detail.type !== "spritesheet") {
        setActivePet({ petId, detail, spriteConfig: null, useSprite: false });
        return;
      }
      const spriteConfig: SpritePetConfig = {
        id: detail.id,
        spritesheetUrl: getSpritesheetUrl(detail.id),
        width: detail.width,
        height: detail.height,
        columns: detail.columns,
        rows: detail.rows,
        frameCounts: detail.frame_counts,
        frameRates: detail.frame_rates,
      };
      setActivePet({ petId, detail, spriteConfig, useSprite: true });
    } catch {
      // Keep the built-in crab as fallback.
      setActivePet({ petId: "builtin-crab", detail: null, spriteConfig: null, useSprite: false });
    }
  }, []);

  useEffect(() => {
    void loadActivePet();
    const handleStorage = (event: StorageEvent) => {
      if (event.key === "active_pet_id") void loadActivePet();
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [loadActivePet]);

  // ── Sync agent monitor summary ────────────────────────────────────
  const syncStateFromMonitor = useCallback(async () => {
    if (syncInFlightRef.current) return;
    syncInFlightRef.current = true;
    try {
      const token = localStorage.getItem("crab_token");
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch("/api/agents/monitor/summary", { headers });
      if (res.status === 401) return;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const summary = (await res.json()) as AgentMonitorSummary;
      const nextTarget = summary.target?.session_id || null;
      targetSessionRef.current = nextTarget;

      // Update SVG state (legacy path)
      const nextSvg = stateFromSummary(summary);
      const svgKey = svgStateKey(nextSvg);
      if (svgKey !== svgStateKeyRef.current) {
        svgStateKeyRef.current = svgKey;
        setSvgState(nextSvg);
      }

      // Update unified state machine state.
      const nextState = derivePetState({
        status: (summary.status as AgentStatus) || "idle",
        message: summary.message,
        targetSessionId: nextTarget,
      });
      const key = petStateKey(nextState);
      if (key !== stateKeyRef.current) {
        stateKeyRef.current = key;
        baseStateRef.current = nextState;
        setPetState(nextState);
      }
    } catch {
      // Keep the last known state while the backend is temporarily unavailable.
    } finally {
      syncInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    const scheduleSync = () => {
      if (syncTimerRef.current !== null) return;
      syncTimerRef.current = window.setTimeout(() => {
        syncTimerRef.current = null;
        void syncStateFromMonitor();
      }, 300);
    };
    const handleStorage = (event: StorageEvent) => {
      if (event.key === "crab_token") scheduleSync();
    };
    window.addEventListener("storage", handleStorage);
    void syncStateFromMonitor();
    const monitorTimer = window.setInterval(() => void syncStateFromMonitor(), 5000);
    const es = connectGlobalSSE(scheduleSync);
    return () => {
      es.close();
      window.removeEventListener("storage", handleStorage);
      window.clearInterval(monitorTimer);
      if (syncTimerRef.current !== null) window.clearTimeout(syncTimerRef.current);
    };
  }, [syncStateFromMonitor]);

  // ── Interactions ──────────────────────────────────────────────────
  const openMain = () => window.electronAPI?.petAction("open-main", targetSessionRef.current || undefined);

  const handlePointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    dragStart.current = { x: event.clientX, y: event.clientY };
    dragged.current = false;
    // Do NOT start drag yet — wait until movement exceeds threshold.
    // Starting the drag timer immediately causes a tiny window displacement
    // (screen vs client coordinate mismatch) which pollutes the click/drag
    // detection and makes clicks unreliable.
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const start = dragStart.current;
    if (start && !dragged.current) {
      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      if (Math.hypot(dx, dy) > 4) {
        dragged.current = true;
        // Now it's a real drag — start the drag handler with the original
        // pointer-down position as the grab offset.
        window.electronAPI?.startPetDrag(start.x, start.y);
      }
    }
  };

  const handlePointerEnd = () => {
    if (dragged.current) {
      window.electronAPI?.endPetDrag();
    }
    dragStart.current = null;
  };

  const handleOpenMain = () => {
    if (!dragged.current) openMain();
  };

  const handleClickPet = () => {
    if (dragged.current) return;
    // One-shot jump/wave animation, then open the main window.
    const base = baseStateRef.current;
    if (activePet.useSprite) {
      setPetState(oneShotAnimation("jumping", base.animation));
    } else {
      setPetState(oneShotAnimation("waving", base.animation));
    }
    // Open main after a short delay so the animation is visible.
    setTimeout(() => openMain(), 500);
  };

  const handleAnimationComplete = useCallback(() => {
    setPetState(baseStateRef.current);
  }, []);

  // ── Drag direction IPC: switch to running-left/right during drag ──
  useEffect(() => {
    if (!window.electronAPI?.onPetDragDirection) return;
    const handler = (data: { direction: string | null }) => {
      if (!activePet.useSprite) return;
      if (data.direction === "running-left" || data.direction === "running-right") {
        const base = baseStateRef.current;
        setPetState({
          animation: data.direction,
          loop: true,
          baseAfter: base.animation,
          label: "",
          detail: "",
          targetSessionId: null,
        });
      } else {
        // Drag ended — restore the agent-driven base state.
        setPetState(baseStateRef.current);
      }
    };
    window.electronAPI.onPetDragDirection(handler);
  }, [activePet.useSprite]);

  // ── Render helpers ────────────────────────────────────────────────
  const renderPetSurface = () => {
    if (activePet.useSprite && activePet.spriteConfig) {
      return (
        <SpritePet
          config={activePet.spriteConfig}
          state={petState}
          scale={1}
          onAnimationComplete={handleAnimationComplete}
        />
      );
    }

    // Built-in SVG crab (legacy). We keep its rich mood-based styling but
    // drive it from the state machine output.
    const mood = animationToSvgMood(petState.animation);
    return (
      <>
        <span className="pet-shadow" />
        <svg className="pet-art" viewBox="0 0 260 190" role="img" aria-label="CrabAgent 小螃蟹">
          <defs>
            <linearGradient id="crabShell" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#ff9d68" />
              <stop offset="0.58" stopColor="#f36c4d" />
              <stop offset="1" stopColor="#dc4d3e" />
            </linearGradient>
            <linearGradient id="crabLimb" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ffb077" />
              <stop offset="1" stopColor="#e65745" />
            </linearGradient>
          </defs>
          <g className="pet-svg-legs" fill="none" stroke="url(#crabLimb)" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round">
            <path d="M88 125 L62 135 L48 151" />
            <path d="M94 137 L70 151 L61 166" />
            <path d="M105 145 L87 163 L82 176" />
            <path d="M172 125 L198 135 L212 151" />
            <path d="M166 137 L190 151 L199 166" />
            <path d="M155 145 L173 163 L178 176" />
          </g>
          <g className="pet-svg-claws" fill="url(#crabLimb)">
            <path d="M76 112 C57 105 44 93 32 102 C20 111 25 128 39 132 C51 135 60 128 68 122 L82 119 Z" />
            <path d="M43 105 C27 96 27 78 38 72 C51 66 59 80 55 92 L50 105 Z" />
            <path d="M184 112 C203 105 216 93 228 102 C240 111 235 128 221 132 C209 135 200 128 192 122 L178 119 Z" />
            <path d="M217 105 C233 96 233 78 222 72 C209 66 201 80 205 92 L210 105 Z" />
          </g>
          <g className="pet-svg-shell">
            <path d="M72 132 C72 92 92 73 130 73 C168 73 188 92 188 132 C188 150 170 158 130 158 C90 158 72 150 72 132 Z" fill="url(#crabShell)" />
            <path d="M89 108 C101 88 116 83 130 83 C144 83 159 88 171 108" fill="none" stroke="#ffd1ae" strokeWidth="6" strokeLinecap="round" opacity="0.72" />
            <ellipse cx="104" cy="92" rx="10" ry="4" fill="#fff0df" opacity="0.76" transform="rotate(-25 104 92)" />
          </g>
          <g className="pet-svg-eyes">
            <path d="M103 99 L97 75" fill="none" stroke="#ef6249" strokeWidth="8" strokeLinecap="round" />
            <path d="M157 99 L163 75" fill="none" stroke="#ef6249" strokeWidth="8" strokeLinecap="round" />
            <circle cx="96" cy="67" r="16" fill="#fffaf1" />
            <circle cx="164" cy="67" r="16" fill="#fffaf1" />
            <ellipse className="pet-pupil" cx="98" cy="70" rx="5.5" ry="7.5" fill="#3f3540" />
            <ellipse className="pet-pupil" cx="162" cy="70" rx="5.5" ry="7.5" fill="#3f3540" />
            <circle cx="100" cy="67" r="2" fill="#fff" />
            <circle cx="164" cy="67" r="2" fill="#fff" />
          </g>
          <path className="pet-smile" d="M120 131 Q130 139 140 131" fill="none" stroke="#a93f44" strokeWidth="4" strokeLinecap="round" />
          <circle cx="103" cy="129" r="4.5" fill="#ffb08c" opacity="0.66" />
          <circle cx="157" cy="129" r="4.5" fill="#ffb08c" opacity="0.66" />
        </svg>
        <span className="pet-status-dot" />
      </>
    );
  };

  // Determine which label/detail to show. For sprite pets use state machine output.
  const bubbleLabel = activePet.useSprite ? petState.label || svgState.label : svgState.label;
  const bubbleDetail = activePet.useSprite ? petState.detail || svgState.detail : svgState.detail;

  return (
    <main
      className="pet-surface"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onContextMenu={(event) => {
        event.preventDefault();
        window.electronAPI?.showPetMenu();
      }}
    >
      <button
        type="button"
        className="pet-bubble"
        data-visible="true"
        onClick={handleOpenMain}
        aria-label="打开 CrabAgent"
      >
        <strong>{bubbleLabel}</strong>
        <span>{bubbleDetail}</span>
      </button>
      <button
        type="button"
        className="pet-character"
        data-mood={activePet.useSprite ? animationToSvgMood(petState.animation) : svgState.mood}
        onClick={handleClickPet}
        onDoubleClick={() => window.electronAPI?.petAction("hide")}
        aria-label="CrabAgent 桌面宠物，点击打开主窗口"
      >
        {renderPetSurface()}
      </button>
    </main>
  );
}