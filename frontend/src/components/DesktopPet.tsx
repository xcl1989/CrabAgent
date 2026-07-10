import { useEffect, useRef, useState } from "react";
import { connectGlobalSSE, getAgentMonitor, type GlobalSSEEvent } from "../api/monitor";

type PetMood = "idle" | "thinking" | "working" | "celebrating" | "error" | "waiting";

interface PetState {
  mood: PetMood;
  label: string;
  detail: string;
}

declare global {
  interface Window {
    electronAPI?: {
      petAction: (action: "open-main" | "hide" | "toggle-always-on-top") => Promise<boolean>;
      showPetMenu: () => void;
      startPetDrag: (offsetX: number, offsetY: number) => void;
      movePetDrag: () => void;
      endPetDrag: () => void;
    };
  }
}

const INITIAL_STATE: PetState = {
  mood: "idle",
  label: "CrabAgent",
  detail: "随时可以开始",
};

function stateFromEvent(event: GlobalSSEEvent): PetState | null {
  const data = event.data;
  switch (event.type) {
    case "agent_start":
    case "iteration_start":
    case "thinking_delta":
      return { mood: "thinking", label: "正在思考", detail: "我在整理思路" };
    case "tool_call":
      return {
        mood: "working",
        label: "正在工作",
        detail: `使用 ${String(data.name || "工具")}`,
      };
    case "tool_confirm_request":
    case "user_input_request":
      return { mood: "waiting", label: "需要你确认", detail: "点我打开对话" };
    case "agent_end":
      return { mood: "celebrating", label: "任务完成", detail: "做得漂亮！" };
    case "agent_error":
      return { mood: "error", label: "遇到一点问题", detail: "点我查看详情" };
    default:
      return null;
  }
}

export function DesktopPet() {
  const [state, setState] = useState<PetState>(INITIAL_STATE);
  const [bubbleVisible, setBubbleVisible] = useState(true);
  const resetTimer = useRef<number | undefined>(undefined);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const dragged = useRef(false);

  useEffect(() => {
    let disposed = false;
    const syncStateFromMonitor = async () => {
      try {
        const activeAgents = await getAgentMonitor();
        if (disposed) return;
        if (activeAgents.length === 0) {
          setState(INITIAL_STATE);
        } else {
          setState({ mood: "thinking", label: "正在思考", detail: "我在整理思路" });
        }
      } catch {
        // SSE remains the live source of truth when the monitor is unavailable.
      }
    };

    // Initial state and fallback when an SSE "agent_end" is missed.
    void syncStateFromMonitor();
    const monitorTimer = window.setInterval(() => {
      void syncStateFromMonitor();
    }, 5000);

    const es = connectGlobalSSE((event) => {
      const nextState = stateFromEvent(event);
      if (!nextState) return;
      setState(nextState);
      setBubbleVisible(true);

      if (resetTimer.current) window.clearTimeout(resetTimer.current);
      if (nextState.mood === "celebrating" || nextState.mood === "error") {
        resetTimer.current = window.setTimeout(() => setState(INITIAL_STATE), 6000);
      }
    });
    return () => {
      disposed = true;
      es.close();
      window.clearInterval(monitorTimer);
      if (resetTimer.current) window.clearTimeout(resetTimer.current);
    };
  }, []);

  const openMain = () => window.electronAPI?.petAction("open-main");
  const handlePointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    dragStart.current = { x: event.clientX, y: event.clientY };
    dragged.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
    window.electronAPI?.startPetDrag(event.clientX, event.clientY);
  };
  const handlePointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const start = dragStart.current;
    if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4) dragged.current = true;
    window.electronAPI?.movePetDrag();
  };
  const handlePointerEnd = () => {
    dragStart.current = null;
    window.electronAPI?.endPetDrag();
  };
  const handleOpenMain = () => {
    if (!dragged.current) openMain();
  };

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
        data-visible={bubbleVisible}
        onClick={handleOpenMain}
        aria-label="打开 CrabAgent"
      >
        <strong>{state.label}</strong>
        <span>{state.detail}</span>
      </button>
      <button
        type="button"
        className="pet-character"
        data-mood={state.mood}
        onClick={handleOpenMain}
        onDoubleClick={() => window.electronAPI?.petAction("hide")}
        aria-label="CrabAgent 桌面宠物，点击打开主窗口"
      >
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
      </button>
    </main>
  );
}
