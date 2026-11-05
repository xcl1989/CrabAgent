import { describe, expect, it, vi } from "vitest";
import { ImageLoadQueue } from "./imageLoadQueue";

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe("ImageLoadQueue", () => {
  it("starts newest pending images first, limits concurrency and deduplicates", async () => {
    const queue = new ImageLoadQueue(2);
    const started: number[] = [];
    const finish = new Map<number, () => void>();
    const add = (id: number) => queue.enqueue(id, () => {
      started.push(id);
      return new Promise<void>((resolve) => finish.set(id, resolve));
    });
    add(1); add(3); add(2); add(3);
    await tick();
    expect(started).toEqual([3, 2]);
    add(4); add(2);
    finish.get(3)!();
    await tick();
    expect(started).toEqual([3, 2, 4]);
    finish.get(2)!(); finish.get(4)!();
    await tick();
    expect(started).toEqual([3, 2, 4, 1]);
    finish.get(1)!();
  });

  it("discards queued requests when the view is cancelled", async () => {
    const queue = new ImageLoadQueue(1);
    let finish!: () => void;
    const pending = vi.fn(async () => {});
    queue.enqueue(2, () => new Promise<void>((resolve) => { finish = resolve; }));
    queue.enqueue(1, pending);
    await tick();
    queue.cancel();
    finish();
    await tick();
    queue.enqueue(3, pending);
    await tick();
    expect(pending).not.toHaveBeenCalled();
  });
});
