"use client";

import dynamic from "next/dynamic";
import { List, Map, Pin, PinOff, RefreshCw } from "lucide-react";
import { useMemo } from "react";

const CytoscapeComponent = dynamic(() => import("react-cytoscapejs"), { ssr: false });

export type GraphNode = {
  id: string;
  node_type: string;
  label: string;
  target_type: string | null;
  target_id: string | null;
  status: string | null;
  weight: number;
  meta: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  edge_type: string;
  from_node_id: string;
  to_node_id: string;
  status: string | null;
  weight: number;
};

export type GraphSummary = {
  visible_node_count: number;
  total_node_count: number;
  visible_edge_count: number;
  page_count: number;
  weak_page_count: number;
  orphan_page_count: number;
  hub_page_count: number;
  core_page_count?: number;
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total_node_count: number;
  graph_stale: boolean;
  layout_key: string;
  summary: GraphSummary;
};

type GraphPanelProps = {
  graph: GraphData | null;
  graphMode: "map" | "list";
  graphNodeType: string;
  graphStatus: string;
  graphError: string | null;
  selectedGraphNode: GraphNode | null;
  canWrite: boolean;
  onGraphModeChange: (mode: "map" | "list") => void;
  onGraphNodeTypeChange: (nodeType: string) => void;
  onGraphStatusChange: (status: string) => void;
  onRebuildGraph: () => void;
  onOpenGraphNode: (node: GraphNode) => void;
  onToggleGraphNodePin: (node: GraphNode, pinned: boolean) => void;
};

export function GraphPanel({
  graph,
  graphMode,
  graphNodeType,
  graphStatus,
  graphError,
  selectedGraphNode,
  canWrite,
  onGraphModeChange,
  onGraphNodeTypeChange,
  onGraphStatusChange,
  onRebuildGraph,
  onOpenGraphNode,
  onToggleGraphNodePin,
}: GraphPanelProps) {
  const selectedNodeId = selectedGraphNode?.id || "";
  const graphElements = useMemo(() => {
    if (!graph) {
      return [];
    }
    const nodes = graph.nodes.map((node) => ({
      data: {
        id: node.id,
        label: node.label,
        type: node.node_type,
        status: node.status || "",
        weight: node.weight,
        core: node.meta.core ? "true" : "false",
        autoCore: node.meta.auto_core ? "true" : "false",
        userPinned: node.meta.user_pinned ? "true" : "false",
        selected: node.id === selectedNodeId ? "true" : "false",
        labelText: node.meta.user_pinned ? "📌" : node.label,
      },
    }));
    const edges = graph.edges.map((edge) => ({
      data: {
        id: edge.id,
        source: edge.from_node_id,
        target: edge.to_node_id,
        type: edge.edge_type,
        status: edge.status || "",
        weight: edge.weight,
      },
    }));
    return [...nodes, ...edges];
  }, [graph, selectedNodeId]);

  return (
    <section className="graph-panel">
      <div className="graph-head">
        <div>
          <p className="eyebrow">Knowledge Map</p>
          <h2>Graph</h2>
        </div>
        <div className="graph-actions">
          <select aria-label="Graph node type" value={graphNodeType} onChange={(event) => onGraphNodeTypeChange(event.target.value)}>
            <option value="page">Pages</option>
            <option value="page,source,citation_audit,unresolved,tag,review,finding,commit">All nodes</option>
            <option value="review,finding,commit">AI reviews</option>
            <option value="citation_audit">Citation audits</option>
            <option value="unresolved">Unresolved</option>
          </select>
          <select aria-label="Graph citation status" value={graphStatus} onChange={(event) => onGraphStatusChange(event.target.value)}>
            <option value="">Any status</option>
            <option value="unsupported,stale,needs_review,contradicted">Weak citations</option>
            <option value="unresolved">Unresolved</option>
            <option value="supported">Supported</option>
          </select>
          <button onClick={() => onGraphModeChange(graphMode === "map" ? "list" : "map")} type="button">
            {graphMode === "map" ? <List aria-hidden size={15} /> : <Map aria-hidden size={15} />}
            {graphMode === "map" ? "List" : "Map"}
          </button>
          <button disabled={!canWrite} onClick={onRebuildGraph} type="button">
            <RefreshCw aria-hidden size={15} />
            Rebuild
          </button>
        </div>
      </div>
      {graph ? (
        <>
          <div className="graph-summary">
            <span>{graph.summary.total_node_count} nodes</span>
            <span>{graph.summary.visible_edge_count} edges</span>
            <span>{graph.summary.core_page_count || 0} core</span>
            <span>{graph.summary.orphan_page_count} orphan</span>
            <span>{graph.summary.weak_page_count} weak</span>
            {graph.truncated ? <strong>Truncated</strong> : null}
            {graph.graph_stale ? <strong>Rebuilding</strong> : null}
          </div>
          {graph.truncated ? <p className="graph-warning">Graph was truncated. Use filters or open neighborhoods from a node.</p> : null}
          <div className="graph-legend" aria-label="Graph legend">
            <span><i className="legend-core" /> Auto core</span>
            <span><i className="legend-selected" /> Selected</span>
            <span><i className="legend-pinned" /> Pinned</span>
          </div>
          {graphMode === "map" && graphElements.length ? (
            <div className="graph-canvas">
              <CytoscapeComponent
                elements={graphElements}
                layout={{ name: "cose", animate: false, fit: true, padding: 24 }}
                stylesheet={[
                  { selector: "node", style: { label: "data(labelText)", "font-size": 10, color: "#1b2028", "text-valign": "bottom", "text-halign": "center", "background-color": "#bfe3f5", width: 24, height: 24, "border-width": 1, "border-color": "#ffffff", shape: "ellipse" } },
                  { selector: "node[autoCore = 'true']", style: { "background-color": "#0b3f73", color: "#0b3f73", width: 32, height: 32, "font-size": 12, "font-weight": 700 } },
                  { selector: "node[userPinned = 'true']", style: { label: "📌", color: "#1b2028", "font-size": 16, "text-valign": "center", "text-halign": "center" } },
                  { selector: "node[selected = 'true']", style: { "border-width": 4, "border-color": "#2563eb", "z-index": 20 } },
                  { selector: "node[type = 'source']", style: { "background-color": "#4568a8", shape: "round-rectangle" } },
                  { selector: "node[type = 'citation_audit']", style: { "background-color": "#c26a45", shape: "diamond" } },
                  { selector: "node[type = 'review']", style: { "background-color": "#7c5aa6", shape: "round-rectangle" } },
                  { selector: "node[type = 'finding']", style: { "background-color": "#d08b39", shape: "diamond" } },
                  { selector: "node[type = 'commit']", style: { "background-color": "#2f855a", shape: "hexagon" } },
                  { selector: "node[type = 'unresolved']", style: { "background-color": "#9a6b27", shape: "triangle" } },
                  { selector: "node[type = 'tag']", style: { "background-color": "#6c7890", shape: "hexagon" } },
                  { selector: "node[status = 'unsupported'], node[status = 'stale'], node[status = 'needs_review']", style: { "border-width": 3, "border-color": "#b33a32" } },
                  { selector: "edge", style: { width: 1.5, "line-color": "#aeb7aa", "target-arrow-color": "#aeb7aa", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
                ]}
                style={{ height: 360, width: "100%" }}
                cy={(cyInstance) => {
                  const cy = cyInstance as { on: (event: string, selector: string, handler: (event: { target: { id: () => string } }) => void) => void };
                  cy.on("tap", "node", (event) => {
                    const id = event.target.id();
                    const node = graph.nodes.find((item) => item.id === id);
                    if (node) {
                      onOpenGraphNode(node);
                    }
                  });
                }}
              />
            </div>
          ) : (
            <div className="graph-list">
              {[...(graph.nodes || [])]
                .sort((left, right) => Number(right.meta.weak_citation_count || 0) - Number(left.meta.weak_citation_count || 0))
                .slice(0, 80)
                .map((node) => (
                  <button key={node.id} onClick={() => onOpenGraphNode(node)} type="button">
                    <strong>{node.label}</strong>
                    <small>
                      {node.node_type} / {node.meta.core ? "core" : node.status || "ok"} / degree {String(node.meta.degree ?? 0)}
                    </small>
                  </button>
                ))}
            </div>
          )}
          {selectedGraphNode ? (
            <div className="graph-detail">
              <strong>{selectedGraphNode.label}</strong>
              <span>{selectedGraphNode.node_type}</span>
              {selectedGraphNode.meta.user_pinned ? (
                <span className="graph-detail-pin">
                  <Pin aria-hidden size={13} />
                  pinned
                </span>
              ) : null}
              <span>{selectedGraphNode.meta.core ? "core node" : selectedGraphNode.status || "no status"}</span>
              {Array.isArray(selectedGraphNode.meta.core_reasons) && selectedGraphNode.meta.core_reasons.length ? (
                <span>{selectedGraphNode.meta.core_reasons.join(", ")}</span>
              ) : null}
              {selectedGraphNode.node_type === "page" ? (
                <button disabled={!canWrite} onClick={() => onToggleGraphNodePin(selectedGraphNode, !selectedGraphNode.meta.user_pinned)} type="button">
                  {selectedGraphNode.meta.user_pinned ? <PinOff aria-hidden size={15} /> : <Pin aria-hidden size={15} />}
                  {selectedGraphNode.meta.user_pinned ? "Unpin core" : "Pin core"}
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        <p className="graph-warning">{graphError || "Graph metadata is empty. Rebuild the graph to start."}</p>
      )}
    </section>
  );
}
