import TimeRangePicker from "./TimeRangePicker";

export default function FilterBar({
  filters,
  options,
  timeRange,
  customRange,
  onFilterChange,
  onTimeRangeChange,
  onCustomRangeChange,
}) {
  return (
    <section className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
      <div className="grid gap-3 rounded-3xl border border-white/10 bg-slate-900/60 p-4 md:grid-cols-3">
        <FilterSelect label="Cluster" value={filters.cluster} options={options.clusters} onChange={(value) => onFilterChange("cluster", value)} />
        <FilterSelect
          label="Namespace"
          value={filters.namespace}
          options={options.namespaces}
          onChange={(value) => onFilterChange("namespace", value)}
        />
        <FilterSelect label="Service" value={filters.service} options={options.services} onChange={(value) => onFilterChange("service", value)} />
      </div>
      <TimeRangePicker
        value={timeRange}
        customStart={customRange.start}
        customEnd={customRange.end}
        onPresetChange={onTimeRangeChange}
        onCustomChange={onCustomRangeChange}
      />
    </section>
  );
}

function FilterSelect({ label, value, options = [], onChange }) {
  return (
    <label className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm tracking-normal text-white outline-none"
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
