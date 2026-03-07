export default function ServiceFilter({ filters, options, onChange }) {
  return (
    <div className="service-filter">
      {options.map((service) => (
        <button
          key={service}
          type="button"
          className={filters.service === service ? "chip active" : "chip"}
          onClick={() => onChange("service", filters.service === service ? "" : service)}
        >
          {service}
        </button>
      ))}
    </div>
  );
}
