import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: String(error?.message || error || "Unknown UI error") };
  }

  componentDidCatch(error, info) {
    console.error("UI crash captured by ErrorBoundary", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="mx-auto flex min-h-screen w-full max-w-[1200px] flex-col gap-4 px-6 py-10 text-slate-200">
          <section className="rounded-3xl border border-rose-400/40 bg-rose-900/20 p-6">
            <h1 className="text-xl font-semibold text-rose-200">UI crashed</h1>
            <p className="mt-2 text-sm text-rose-100">
              {this.state.message}
            </p>
            <p className="mt-2 text-xs text-slate-300">
              Reload the page. If it repeats, send this message so we can fix the exact field causing it.
            </p>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
