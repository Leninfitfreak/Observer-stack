import { useEffect, useMemo, useState } from "react";
import { fetchIncidentAnalysis, fetchIncidentSummary, getReportExcel } from "./api";
import { HistoryFilters } from "./HistoryFilters";
import { HistorySummary } from "./HistorySummary";
import { HistoryTable } from "./HistoryTable";
import { IncidentDetailDrawer } from "./IncidentDetailDrawer";
import type { HistoryFiltersState, IncidentAnalysis, IncidentSummaryResponse } from "../types";
import "./history.css";

const DEFAULT_LIMIT = 20;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function sevenDaysAgoIso(): string {
  const dt = new Date();
  dt.setDate(dt.getDate() - 7);
  return dt.toISOString().slice(0, 10);
}

const DEFAULT_CLASSIFICATIONS = [
  "False Positive",
  "Performance Degradation",
  "Infra Issue",
  "Observability Gap",
];

export default function HistoryPage() {
  const [filters, setFilters] = useState<HistoryFiltersState>({
    startDate: sevenDaysAgoIso(),
    endDate: todayIso(),
    serviceName: "",
    classification: "",
    minConfidence: 0,
  });
  const [appliedFilters, setAppliedFilters] = useState<HistoryFiltersState>(filters);
  const [incidents, setIncidents] = useState<IncidentAnalysis[]>([]);
  const [summary, setSummary] = useState<IncidentSummaryResponse | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(DEFAULT_LIMIT);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<IncidentAnalysis | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);

  const loadData = async (activeFilters: HistoryFiltersState, nextOffset: number) => {
    setLoading(true);
    setError(null);
    try {
      const [listData, summaryData] = await Promise.all([
        fetchIncidentAnalysis({
          start_date: activeFilters.startDate,
          end_date: activeFilters.endDate,
          service_name: activeFilters.serviceName || undefined,
          classification: activeFilters.classification || undefined,
          min_confidence: activeFilters.minConfidence,
          limit,
          offset: nextOffset,
        }),
        fetchIncidentSummary({
          start_date: activeFilters.startDate,
          end_date: activeFilters.endDate,
          service_name: activeFilters.serviceName || undefined,
          classification: activeFilters.classification || undefined,
          min_confidence: activeFilters.minConfidence,
        }),
      ]);
      setIncidents(listData.items);
      setTotal(listData.total);
      setSummary(summaryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(appliedFilters, offset);
  }, [appliedFilters, offset]);

  const services = useMemo(() => {
    const values = new Set<string>();
    incidents.forEach((item) => values.add(item.service_name));
    return Array.from(values).sort();
  }, [incidents]);

  const sortedIncidents = useMemo(() => {
    const copy = [...incidents];
    copy.sort((a, b) => {
      const aT = new Date(a.created_at).getTime();
      const bT = new Date(b.created_at).getTime();
      return sortDirection === "desc" ? bT - aT : aT - bT;
    });
    return copy;
  }, [incidents, sortDirection]);

  return (
    <main className="history-page">
      <header className="history-header">
        <h1>Incident History</h1>
      </header>

      <HistoryFilters
        filters={filters}
        services={services}
        classifications={DEFAULT_CLASSIFICATIONS}
        onChange={setFilters}
        onApply={() => {
          setOffset(0);
          setAppliedFilters(filters);
        }}
        onExport={async () => {
          setExportLoading(true);
          try {
            const blob = await getReportExcel({
              start_date: appliedFilters.startDate,
              end_date: appliedFilters.endDate,
              service_name: appliedFilters.serviceName || undefined,
              classification: appliedFilters.classification || undefined,
              min_confidence: appliedFilters.minConfidence,
            });
            const link = document.createElement("a");
            const url = URL.createObjectURL(blob);
            const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
            link.href = url;
            link.download = `incident_report_${stamp}.xlsx`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to export report");
          } finally {
            setExportLoading(false);
          }
        }}
        exportLoading={exportLoading}
      />

      {loading && <div className="status">Loading incident history...</div>}
      {error && <div className="status error">{error}</div>}

      <HistorySummary summary={summary} />

      <HistoryTable
        incidents={sortedIncidents}
        total={total}
        limit={limit}
        offset={offset}
        sortDirection={sortDirection}
        onSortToggle={() => setSortDirection((prev) => (prev === "desc" ? "asc" : "desc"))}
        onPageChange={setOffset}
        onView={(incident) => {
          setSelectedIncident(incident);
          setDrawerOpen(true);
        }}
      />

      <IncidentDetailDrawer
        incident={selectedIncident}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setSelectedIncident(null);
        }}
      />
    </main>
  );
}
