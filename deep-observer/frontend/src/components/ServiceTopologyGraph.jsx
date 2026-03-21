export default function ServiceTopologyGraph({ topology, selectedService }) {
  const { nodes, edges } = buildRenderableTopology(topology);

  if (!nodes.length) {
    return (
      <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <h2 className="text-lg font-semibold text-white">Service Topology Graph</h2>
        <p className="mt-4 text-sm text-slate-400">No topology data available for the selected time range.</p>
      </section>
    );
  }

  const positionedNodes = nodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / nodes.length;
    const radius = 120;
    return {
      ...node,
      x: 180 + Math.cos(angle) * radius,
      y: 160 + Math.sin(angle) * radius,
    };
  });

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Service Topology Graph</h2>
        <span className="text-xs uppercase tracking-[0.3em] text-slate-400">{edges.length} edges</span>
      </div>
      <svg viewBox="0 0 360 320" className="h-[320px] w-full rounded-3xl bg-slate-950/80">
        {edges.map((edge) => {
          const source = positionedNodes.find((node) => node.id === edge.source);
          const target = positionedNodes.find((node) => node.id === edge.target);
          if (!source || !target) return null;
          return (
            <g key={`${edge.source}-${edge.target}`}>
              <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="rgba(56, 189, 248, 0.4)" strokeWidth="2" />
              <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2} fill="#94a3b8" fontSize="10" textAnchor="middle">
                {edge.call_count}
              </text>
            </g>
          );
        })}
        {positionedNodes.map((node) => (
          <g key={node.id}>
            <circle
              cx={node.x}
              cy={node.y}
              r={selectedService === node.id ? 24 : 18}
              fill={selectedService === node.id ? "#f97316" : "#0f766e"}
              stroke="white"
              strokeOpacity="0.2"
            />
            <text x={node.x} y={node.y + 40} fill="#e2e8f0" fontSize="11" textAnchor="middle">
              {node.label}
            </text>
          </g>
        ))}
      </svg>
    </section>
  );
}

function buildRenderableTopology(topology) {
  const rawNodes = Array.isArray(topology?.nodes) ? topology.nodes : [];
  const rawEdges = Array.isArray(topology?.edges) ? topology.edges : [];
  const infraAliases = new Set();

  rawNodes.forEach((node) => {
    const id = String(node?.id || "").trim().toLowerCase();
    if (id.startsWith("db:") || id.startsWith("messaging:")) {
      const alias = id.split(":", 2)[1]?.split("/", 1)[0]?.trim();
      if (alias) {
        infraAliases.add(alias);
      }
    }
  });

  const nodes = rawNodes.filter((node) => {
    const id = String(node?.id || "").trim().toLowerCase();
    const type = String(node?.node_type || "").trim().toLowerCase();
    if (type === "service" && infraAliases.has(id)) {
      return false;
    }
    return true;
  });

  const allowedIds = new Set(nodes.map((node) => String(node?.id || "").trim()));
  const edges = rawEdges.filter((edge) => allowedIds.has(String(edge?.source || "").trim()) && allowedIds.has(String(edge?.target || "").trim()));

  return { nodes, edges };
}
