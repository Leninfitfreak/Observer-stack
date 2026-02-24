import type { HistoryFiltersState } from "../types";

interface Props {
  filters: HistoryFiltersState;
  services: string[];
  classifications: string[];
  onChange: (next: HistoryFiltersState) => void;
  onApply: () => void;
  onExport: () => void;
  exportLoading: boolean;
}

export function HistoryFilters({
  filters,
  services,
  classifications,
  onChange,
  onApply,
  onExport,
  exportLoading,
}: Props) {
  return (
    <div className="history-filters">
      <div className="field">
        <label>Start Date</label>
        <input
          type="date"
          value={filters.startDate}
          onChange={(e) => onChange({ ...filters, startDate: e.target.value })}
        />
      </div>
      <div className="field">
        <label>End Date</label>
        <input
          type="date"
          value={filters.endDate}
          onChange={(e) => onChange({ ...filters, endDate: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Service</label>
        <select
          value={filters.serviceName}
          onChange={(e) => onChange({ ...filters, serviceName: e.target.value })}
        >
          <option value="">All Services</option>
          {services.map((service) => (
            <option key={service} value={service}>
              {service}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Classification</label>
        <select
          value={filters.classification}
          onChange={(e) => onChange({ ...filters, classification: e.target.value })}
        >
          <option value="">All</option>
          {classifications.map((classification) => (
            <option key={classification} value={classification}>
              {classification}
            </option>
          ))}
        </select>
      </div>
      <div className="field min-confidence">
        <label>Min Confidence: {filters.minConfidence}%</label>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={filters.minConfidence}
          onChange={(e) => onChange({ ...filters, minConfidence: Number(e.target.value) })}
        />
      </div>
      <button className="apply-btn" onClick={onApply}>
        Apply
      </button>
      <button className="export-btn" onClick={onExport} disabled={exportLoading}>
        {exportLoading ? "Generating..." : "Export to Excel"}
      </button>
    </div>
  );
}
