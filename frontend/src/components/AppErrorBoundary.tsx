import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("CrabAgent UI crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="min-h-dvh flex items-center justify-center p-6 bg-[var(--bg-primary)]">
        <section className="max-w-md w-full rounded-2xl border border-[var(--danger-border)] bg-[var(--bg-secondary)] p-6 shadow-[var(--shadow-lg)]">
          <div className="flex items-center gap-3 text-[var(--danger)]">
            <AlertTriangle size={22} />
            <h1 className="text-lg font-semibold">页面遇到异常</h1>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
            已阻止异常继续影响页面。请刷新以恢复当前界面；若问题重复出现，请复制控制台错误反馈给我们。
          </p>
          <button
            className="mt-5 inline-flex items-center gap-2 rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--brand-hover)]"
            onClick={() => window.location.reload()}
          >
            <RefreshCw size={15} />刷新页面
          </button>
        </section>
      </main>
    );
  }
}
