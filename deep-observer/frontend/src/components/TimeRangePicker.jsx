import { getPresetOptions, toDateTimeLocal } from "../timeRange";

export default function TimeRangePicker({ value, customStart, customEnd, onPresetChange, onCustomChange }) {
  return (
    <div className="flex flex-col gap-3 rounded-3xl border border-white/10 bg-slate-900/60 p-4">
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
          <div className="grid flex-1 gap-3 md:grid-cols-2">
            <input
              type="datetime-local"
              value={toDateTimeLocal(customStart)}
              onChange={(event) => onCustomChange("start", event.target.value)}
              className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
            />
            <input
              type="datetime-local"
              value={toDateTimeLocal(customEnd)}
              onChange={(event) => onCustomChange("end", event.target.value)}
              className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm text-white outline-none"
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
