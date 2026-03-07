export default function ReasoningPanel({ incident }) {
  const reasoning = incident.reasoning;

  return (
    <div className="panel reasoning-panel">
      <h2>AI Reasoning</h2>
      {!reasoning ? (
        <p>Reasoning has not been generated yet.</p>
      ) : (
        <>
          <p className="root-cause">{reasoning.root_cause}</p>
          <div className="grid">
            <Metric label="Confidence" value={reasoning.confidence_score} />
            <Metric label="Severity" value={reasoning.severity} />
            <Metric label="Impact" value={reasoning.impact_assessment} />
          </div>
          <Section title="Causal Chain" items={reasoning.causal_chain} />
          <Section title="Correlated Signals" items={reasoning.correlated_signals} />
          <Section title="Recommended Actions" items={reasoning.recommended_actions} />
        </>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{Array.isArray(value) ? value.join(", ") : String(value)}</strong>
    </div>
  );
}

function Section({ title, items }) {
  return (
    <div className="reasoning-section">
      <h3>{title}</h3>
      <ul>
        {(items || []).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
