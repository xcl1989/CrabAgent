import { useEffect, useRef, useState } from "react";
import type { PetAnimationName, PetState } from "../../lib/pets/petStateMachine";

export interface SpritePetConfig {
  id: string;
  spritesheetUrl: string;
  width: number;
  height: number;
  columns: number;
  rows: number;
  frameCounts: Record<string, number>;
  frameRates: Record<string, number>;
}

interface SpritePetProps {
  config: SpritePetConfig;
  state: PetState;
  scale?: number;
  onAnimationComplete?: () => void;
}

function getFrameCount(frameCounts: Record<string, number>, animation: PetAnimationName): number {
  return frameCounts[animation] ?? frameCounts[animation.replace("-", "_")] ?? 1;
}

function getFrameRate(frameRates: Record<string, number>, animation: PetAnimationName): number {
  return frameRates[animation] ?? frameRates[animation.replace("-", "_")] ?? 150;
}

export function SpritePet({ config, state, scale = 1, onAnimationComplete }: SpritePetProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Load the spritesheet once.
  useEffect(() => {
    const img = new Image();
    // No crossOrigin for same-origin requests — avoids canvas tainting.
    img.src = config.spritesheetUrl;
    img.onload = () => {
      imageRef.current = img;
      setLoaded(true);
    };
    img.onerror = (e) => {
      console.error("SpritePet: failed to load spritesheet", config.spritesheetUrl, e);
      setLoaded(false);
    };
  }, [config.spritesheetUrl]);

  // Frame animation loop.
  useEffect(() => {
    if (!loaded || !imageRef.current || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = config.width * scale;
    canvas.height = config.height * scale;

    const animation = state.animation;
    const row = Math.max(
      0,
      Math.min(config.rows - 1, ROW_INDEX[animation] ?? 0),
    );
    const frameCount = getFrameCount(config.frameCounts, animation);
    const frameRate = getFrameRate(config.frameRates, animation);
    const frameDuration = Math.max(16, frameRate);

    let frame = 0;
    let lastTime = performance.now();
    let rafId = 0;
    let completed = false;

    const render = (time: number) => {
      const elapsed = time - lastTime;
      if (elapsed >= frameDuration) {
        lastTime = time;
        frame += 1;
        if (frame >= frameCount) {
          if (state.loop) {
            frame = 0;
          } else {
            frame = frameCount - 1;
            if (!completed) {
              completed = true;
              onAnimationComplete?.();
            }
          }
        }
      }

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.imageSmoothingEnabled = false;
      const sx = frame * config.width;
      const sy = row * config.height;
      ctx.drawImage(
        imageRef.current!,
        sx,
        sy,
        config.width,
        config.height,
        0,
        0,
        canvas.width,
        canvas.height,
      );

      rafId = requestAnimationFrame(render);
    };

    rafId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(rafId);
  }, [loaded, config, state, scale, onAnimationComplete]);

  return (
    <canvas
      ref={canvasRef}
      width={config.width * scale}
      height={config.height * scale}
      className="sprite-pet"
      style={{
        width: config.width * scale,
        height: config.height * scale,
        opacity: loaded ? 1 : 0,
        transition: "opacity 200ms ease",
      }}
    />
  );
}

/** Codex-compatible row index mapping. */
const ROW_INDEX: Record<PetAnimationName, number> = {
  idle: 0,
  "running-right": 1,
  "running-left": 2,
  waving: 3,
  jumping: 4,
  failed: 5,
  waiting: 6,
  running: 7,
  review: 8,
};