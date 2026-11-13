// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackgroundTasks } from "./BackgroundTasks";
import { cancelBackgroundTask, getBackgroundTask, listBackgroundTasks, listBackgroundGroups, getBackgroundGroup, cancelBackgroundGroup, getSemanticSummary, startSemanticSummary, getSummaryProvider, deleteSemanticSummary, listDeliveries, authorizeDelivery, revokeDelivery } from "../api/backgroundTasks";

vi.mock("../api/backgroundTasks", () => ({
  listDeliveries: vi.fn(), authorizeDelivery: vi.fn(), revokeDelivery: vi.fn(),
  listBackgroundTasks: vi.fn(), getBackgroundTask: vi.fn(), cancelBackgroundTask: vi.fn(),
  listBackgroundGroups: vi.fn(), getBackgroundGroup: vi.fn(), cancelBackgroundGroup: vi.fn(),
  getSemanticSummary: vi.fn(), startSemanticSummary: vi.fn(), cancelSemanticSummary: vi.fn(), getSummaryProvider: vi.fn(), deleteSemanticSummary: vi.fn(),
}));

const task = { id: "1", agent_name: "coder", task: "work", status: "running" };
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => {
  vi.mocked(listDeliveries).mockResolvedValue({ branch: "main", deliveries: [] });
  vi.mocked(getSemanticSummary).mockResolvedValue({ summary: null });
  vi.mocked(listBackgroundGroups).mockImplementation(async () => ({ branch: "main", groups: [] }));
});
afterEach(() => { document.body.innerHTML = ""; vi.resetAllMocks(); });

describe("background tasks", () => {
  it("hides the panel when there are no tasks and shows it after polling finds one", async () => {
    vi.useFakeTimers();
    vi.mocked(listBackgroundTasks).mockResolvedValueOnce({ branch: "main", tasks: [] })
      .mockResolvedValue({ branch: "main", tasks: [task] });
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="session" />); });
    expect(container.textContent).toBe("");
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(container.textContent).toContain("后台子任务 (1)");
    await act(async () => root.unmount());
    vi.useRealTimers();
  });
  it("shows status, untrusted result and cancellation", async () => {
    vi.mocked(listBackgroundTasks).mockResolvedValue({ branch: "main", tasks: [task] });
    vi.mocked(getBackgroundTask).mockResolvedValue({ ...task, result: "<script>unsafe</script>" });
    vi.mocked(cancelBackgroundTask).mockResolvedValue({ ...task, status: "cancelled", result: "Cancelled" });
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="session" />); });
    await act(async () => { container.querySelector("button")!.click(); });
    expect(container.textContent).toContain("运行中");
    const button = (label: string) => [...container.querySelectorAll("button")].find((b) => b.textContent === label)!;
    await act(async () => { button("查看结果").click(); });
    expect(getBackgroundTask).toHaveBeenCalledWith("session", "main", "1");
    expect(container.textContent).toContain("<script>unsafe</script>");
    expect(container.querySelector("script")).toBeNull();
    await act(async () => { button("取消任务").click(); });
    expect(cancelBackgroundTask).toHaveBeenCalledWith("session", "main", "1");
    expect(container.textContent).toContain("已取消");
    await act(async () => root.unmount());
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("background polling races", () => {
  afterEach(() => vi.useRealTimers());
  it("ignores older branch responses and errors", async () => {
    vi.useFakeTimers();
    vi.mocked(listBackgroundGroups).mockResolvedValue({ branch: "new", groups: [] });
    vi.mocked(listDeliveries).mockResolvedValue({ branch: "new", deliveries: [] });
    const first = deferred<{ branch: string; tasks: typeof task[] }>();
    const second = deferred<{ branch: string; tasks: typeof task[] }>();
    vi.mocked(listBackgroundTasks).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="s" />); });
    expect(container.querySelector("button")).toBeNull();
    await act(async () => { vi.advanceTimersByTime(5000); });
    await act(async () => { second.resolve({ branch: "new", tasks: [{ ...task, task: "new branch" }] }); });
    await act(async () => { container.querySelector("button")!.click(); });
    await act(async () => { first.reject(new Error("late")); });
    expect(container.textContent).toContain("new branch");
    expect(container.textContent).not.toContain("无法获取");
    await act(async () => root.unmount());
  });
  it("clears the old branch and ignores its pending action", async () => {
    vi.mocked(listBackgroundGroups).mockResolvedValueOnce({ branch: "main", groups: [] }).mockResolvedValueOnce({ branch: "other", groups: [] });
    vi.mocked(listDeliveries).mockResolvedValueOnce({ branch: "main", deliveries: [] }).mockResolvedValueOnce({ branch: "other", deliveries: [] });
    const detail = deferred<typeof task & { result: string }>();
    vi.mocked(listBackgroundTasks).mockResolvedValueOnce({ branch: "main", tasks: [task] })
      .mockResolvedValueOnce({ branch: "other", tasks: [{ ...task, id: "2", task: "other branch" }] });
    vi.mocked(getBackgroundTask).mockReturnValueOnce(detail.promise);
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="s" activeBranch="main" />); });
    await act(async () => { container.querySelector("button")!.click(); });
    await act(async () => { [...container.querySelectorAll("button")].find(b => b.textContent === "查看结果")!.click(); });
    await act(async () => { root.render(<BackgroundTasks sessionId="s" activeBranch="other" />); });
    await act(async () => { detail.resolve({ ...task, result: "stale result" }); });
    expect(container.textContent).toContain("other branch");
    expect(container.textContent).not.toContain("stale result");
    await act(async () => root.unmount());
  });
  it("rejects a response for a different active branch and resets on session switch", async () => {
    vi.mocked(listBackgroundTasks).mockResolvedValueOnce({ branch: "old", tasks: [task] })
      .mockResolvedValueOnce({ branch: "main", tasks: [{ ...task, task: "new session" }] });
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="a" activeBranch="main" mobile />); });
    await act(async () => { container.querySelector("button")!.click(); });
    expect(container.textContent).toContain("正在等待同步");
    expect(container.textContent).not.toContain("work");
    await act(async () => { root.render(<BackgroundTasks sessionId="b" activeBranch="main" mobile />); });
    expect(container.textContent).toContain("new session");
    expect(listBackgroundTasks).toHaveBeenLastCalledWith("b");
    await act(async () => root.unmount());
  });
  it("does not let a pending poll undo cancellation", async () => {
    vi.useFakeTimers();
    const poll = deferred<{ branch: string; tasks: typeof task[] }>();
    vi.mocked(listBackgroundTasks).mockResolvedValueOnce({ branch: "main", tasks: [task] }).mockReturnValueOnce(poll.promise);
    vi.mocked(cancelBackgroundTask).mockResolvedValue({ ...task, status: "cancelled" });
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="s" mobile />); });
    await act(async () => { container.querySelector("button")!.click(); vi.advanceTimersByTime(5000); });
    await act(async () => { [...container.querySelectorAll("button")].find(b => b.textContent === "取消任务")!.click(); });
    await act(async () => { poll.resolve({ branch: "main", tasks: [task] }); });
    expect(container.textContent).toContain("已取消");
    await act(async () => root.unmount());
  });
});


describe.each([false, true])("background groups mobile=%s", (mobile) => {
  it("displays details safely and cancels a group", async () => {
    const group = { id: "g1", status: "running" };
    const detail = { ...group, steps: [{ step_id: "s1", agent_name: "coder", task: "work", depends_on: [], status: "running", job_id: "j", result: "<script>bad</script>" }], summary: null };
    vi.mocked(listBackgroundTasks).mockResolvedValue({ branch: "main", tasks: [] });
    vi.mocked(listBackgroundGroups).mockResolvedValue({ branch: "main", groups: [group] });
    vi.mocked(getBackgroundGroup).mockResolvedValue(detail);
    vi.mocked(cancelBackgroundGroup).mockResolvedValue({ ...detail, status: "cancelled" });
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="s" mobile={mobile} />); });
    await act(async () => { container.querySelector("button")!.click(); });
    const button = (label: string) => [...container.querySelectorAll("button")].find(b => b.textContent === label)!;
    await act(async () => { button("查看详情").click(); });
    expect(getBackgroundGroup).toHaveBeenCalledWith("s", "main", "g1");
    expect(container.textContent).toContain("<script>bad</script>");
    expect(container.querySelector("script")).toBeNull();
    await act(async () => { button("取消任务组").click(); });
    expect(cancelBackgroundGroup).toHaveBeenCalledWith("s", "main", "g1");
    expect(container.textContent).toContain("已取消");
    await act(async () => root.unmount());
  });
});


it("requires explicit consent and password before sending step results", async () => {
  const group = { id: "g", status: "succeeded", steps: [] };
  vi.mocked(listBackgroundTasks).mockResolvedValue({ branch: "main", tasks: [] });
  vi.mocked(listBackgroundGroups).mockResolvedValue({ branch: "main", groups: [group] });
  vi.mocked(getBackgroundGroup).mockResolvedValue(group);
  vi.mocked(getSummaryProvider).mockResolvedValue({ name: "Provider", type: "openai", model: "model", endpoint: "endpoint", proxy: "direct", binding: "binding" });
  vi.mocked(startSemanticSummary).mockResolvedValue({ summary: { status: "pending", text: "" } });
  const container = document.createElement("div"); document.body.appendChild(container);
  const root = createRoot(container);
  const button = (label: string) => [...container.querySelectorAll("button")].find(b => b.textContent === label)!;
  await act(async () => { root.render(<BackgroundTasks sessionId="s" />); });
  await act(async () => { container.querySelector("button")!.click(); });
  await act(async () => { button("查看详情").click(); });
  await act(async () => { button("申请语义汇总").click(); });
  expect(container.textContent).toContain("模型供应商");
  expect(container.textContent).toContain("Provider");
  expect(container.textContent).toContain("明文保存在本地数据库");
  expect(button("确认发送并生成").disabled).toBe(true);
  expect(startSemanticSummary).not.toHaveBeenCalled();
  await act(async () => root.unmount());
});


it("requires confirmation before clearing a terminal summary", async () => {
  const group = { id: "g", status: "succeeded", steps: [] };
  vi.mocked(listBackgroundTasks).mockResolvedValue({ branch: "main", tasks: [] });
  vi.mocked(listBackgroundGroups).mockResolvedValue({ branch: "main", groups: [group] });
  vi.mocked(getBackgroundGroup).mockResolvedValue(group);
  vi.mocked(getSemanticSummary).mockResolvedValue({ summary: { status: "succeeded", text: "private" } });
  vi.mocked(deleteSemanticSummary).mockResolvedValue({ deleted: true });
  const container = document.createElement("div"); document.body.appendChild(container);
  const root = createRoot(container);
  const button = (label: string) => [...container.querySelectorAll("button")].find(b => b.textContent === label)!;
  await act(async () => { root.render(<BackgroundTasks sessionId="s" />); });
  await act(async () => { container.querySelector("button")!.click(); });
  await act(async () => { button("查看详情").click(); });
  await act(async () => { button("清理本地语义汇总").click(); });
  expect(deleteSemanticSummary).not.toHaveBeenCalled();
  expect(container.textContent).toContain("不会删除原任务结果");
  await act(async () => { button("确认清理").click(); });
  expect(deleteSemanticSummary).toHaveBeenCalledWith("s", "main", "g");
  expect(container.textContent).not.toContain("private");
  await act(async () => root.unmount());
});

describe.each([false, true])("delivery authorization mobile=%s", (mobile) => {
  it("requires confirmation and supports revocation", async () => {
    const group = { id: "g1", status: "running" };
    vi.mocked(listBackgroundTasks).mockResolvedValue({ branch: "main", tasks: [] });
    vi.mocked(listBackgroundGroups).mockResolvedValue({ branch: "main", groups: [group] });
    vi.mocked(authorizeDelivery).mockResolvedValue({} as never);
    vi.mocked(revokeDelivery).mockResolvedValue({} as never);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="s" mobile={mobile} />); });
    expect(authorizeDelivery).not.toHaveBeenCalled();
    await act(async () => { container.querySelector("button")!.click(); });
    const button = (label: string) => [...container.querySelectorAll("button")].find(b => b.textContent === label)!;
    await act(async () => { button("授权自动展示").click(); });
    expect(authorizeDelivery).not.toHaveBeenCalled();
    await act(async () => { button("授权自动展示").click(); });
    expect(authorizeDelivery).toHaveBeenCalledWith("s", "main", "g1");
    expect(container.textContent).toContain("已授权此任务组");
    await act(async () => { button("撤销展示授权").click(); });
    expect(revokeDelivery).toHaveBeenCalledWith("s", "main", "g1");
    expect(container.textContent).toContain("已撤销展示授权");
    confirm.mockRestore();
    await act(async () => root.unmount());
  });

  it("renders untrusted results as text and removes a revoked card", async () => {
    vi.mocked(listBackgroundTasks).mockResolvedValue({ branch: "main", tasks: [] });
    vi.mocked(listDeliveries).mockResolvedValue({ branch: "main", deliveries: [{ id: "g1", status: "succeeded", steps: [{ step_id: "step", status: "succeeded", result: "<script>unsafe</script>" }] }] });
    vi.mocked(revokeDelivery).mockResolvedValue({} as never);
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(<BackgroundTasks sessionId="s" mobile={mobile} />); });
    expect(container.textContent).toContain("未验证数据");
    expect(container.textContent).toContain("不会发送给模型");
    expect(container.textContent).toContain("<script>unsafe</script>");
    expect(container.querySelector("script")).toBeNull();
    expect(authorizeDelivery).not.toHaveBeenCalled();
    await act(async () => { container.querySelector<HTMLButtonElement>('article button')!.click(); });
    expect(revokeDelivery).toHaveBeenCalledWith("s", "main", "g1");
    expect(container.querySelector('article')).toBeNull();
    await act(async () => root.unmount());
  });
});
