export default function Header({ liveMode, onToggleLive, rangeLabel }) {
  return (
    <header className="rounded-[2rem] border border-white/10 bg-slate-900/70 p-8 shadow-2xl shadow-sky-950/30 backdrop-blur">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-[0.4em] text-cyan-300">Deep Observer</p>
          <h1 className="text-4xl font-semibold tracking-tight text-white">AI Root Cause Analysis for Live Telemetry</h1>
          <p className="max-w-3xl text-sm leading-6 text-slate-300">
            Metrics, logs, traces, topology, deployment clues, and historical incidents are correlated into a single
            operational narrative.
          </p>
        </div>
        <div className="flex flex-col gap-3 rounded-3xl border border-white/10 bg-slate-950/70 px-5 py-4 text-sm text-slate-300">
          <span className="font-medium text-white">Window: {rangeLabel}</span>
          <label className="flex items-center gap-3">
            <span className={liveMode ? "text-emerald-300" : "text-slate-400"}>Live Mode</span>
            <button
              type="button"
              onClick={onToggleLive}
              className={`relative h-7 w-14 rounded-full transition ${
                liveMode ? "bg-emerald-500/80" : "bg-slate-700"
              }`}
            >
              <span
                className={`absolute top-1 h-5 w-5 rounded-full bg-white transition ${
                  liveMode ? "left-8" : "left-1"
                }`}
              />
            </button>
          </label>
        </div>
      </div>
    </header>
  );
}
