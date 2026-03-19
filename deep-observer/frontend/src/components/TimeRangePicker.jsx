import { getPresetOptions, toDateTimeLocal } from "../timeRange";

export default function TimeRangePicker({
  value,
  customStart,
  customEnd,
  onPresetChange,
  onCustomChange,
  onApplyCustom,
  canApplyCustom,
  customHint,
  onClearCustom,
}) {
  return (
    <div className="flex flex-col gap-3 rounded-3xl border border-white/10 bg-slate-900/60 p-5">
      <label className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">Time Range</label>
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
        <select
          value={value}
          onChange={(event) => onPresetChange(event.target.value)}
          className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
        >
          {getPresetOptions().map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {value === "custom" ? (
          <div className="flex flex-1 flex-col gap-3">
            <div className="grid gap-3 md:grid-cols-2">
              <input
                type="datetime-local"
                value={toDateTimeLocal(customStart)}
                onChange={(event) => onCustomChange("start", event.target.value)}
                step="60"
                placeholder="Start date/time"
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
              />
              <input
                type="datetime-local"
                value={toDateTimeLocal(customEnd)}
                onChange={(event) => onCustomChange("end", event.target.value)}
                step="60"
                placeholder="End date/time"
                className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-slate-500">{customHint || "Select a valid start and end time."}</p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClearCustom}
                  className="rounded-full border border-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.3em] text-slate-300 hover:bg-white/5"
                >
                  Clear
                </button>
                <button
                  type="button"
                  onClick={onApplyCustom}
                  disabled={!canApplyCustom}
                  className={`rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.3em] ${
                    canApplyCustom ? "bg-cyan-500 text-slate-950 hover:bg-cyan-400" : "bg-slate-700 text-slate-300"
                  }`}
                >
                  Apply
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
