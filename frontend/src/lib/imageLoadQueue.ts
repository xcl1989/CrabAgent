export class ImageLoadQueue {
  private pending = new Map<number, () => Promise<void>>();
  private active = new Set<number>();
  private scheduled = false;
  private closed = false;

  constructor(private readonly limit = 2) {}

  enqueue(id: number, task: () => Promise<void>) {
    if (this.closed || this.active.has(id) || this.pending.has(id)) return;
    this.pending.set(id, task);
    if (!this.scheduled) {
      this.scheduled = true;
      queueMicrotask(() => { this.scheduled = false; this.drain(); });
    }
  }

  cancel() { this.closed = true; this.pending.clear(); }

  private drain() {
    while (!this.closed && this.active.size < this.limit && this.pending.size) {
      const id = Math.max(...this.pending.keys());
      const task = this.pending.get(id)!;
      this.pending.delete(id);
      this.active.add(id);
      void Promise.resolve().then(task).catch(() => {}).finally(() => {
        this.active.delete(id);
        this.drain();
      });
    }
  }
}
