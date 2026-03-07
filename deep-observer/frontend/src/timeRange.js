const PRESETS = {
  "5m": { label: "Last 5 minutes", minutes: 5 },
  "15m": { label: "Last 15 minutes", minutes: 15 },
  "30m": { label: "Last 30 minutes", minutes: 30 },
  "1h": { label: "Last 1 hour", minutes: 60 },
  "6h": { label: "Last 6 hours", minutes: 360 },
  "24h": { label: "Last 24 hours", minutes: 1440 },
  custom: { label: "Custom Range", minutes: null },
};

export function getPresetOptions() {
  return Object.entries(PRESETS).map(([value, preset]) => ({ value, label: preset.label }));
}

export function buildRange(rangeKey, customStart, customEnd) {
  const now = new Date();
  if (rangeKey === "custom" && customStart && customEnd) {
    return {
      start: new Date(customStart).toISOString(),
      end: new Date(customEnd).toISOString(),
      label: PRESETS.custom.label,
    };
  }
  const preset = PRESETS[rangeKey] || PRESETS["1h"];
  const start = new Date(now.getTime() - preset.minutes * 60 * 1000);
  return {
    start: start.toISOString(),
    end: now.toISOString(),
    label: preset.label,
  };
}

export function toDateTimeLocal(value) {
  if (!value) return "";
  const date = new Date(value);
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
