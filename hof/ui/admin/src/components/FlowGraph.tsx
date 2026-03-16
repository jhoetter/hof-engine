import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { DagNode, DagEdge } from "../api";

interface FlowGraphProps {
  nodes: DagNode[];
  edges: DagEdge[];
  executionOrder: string[][];
  nodeStates?: Record<string, string>;
}

const NODE_WIDTH = 220;
const NODE_HEIGHT = 80;
const H_GAP = 60;
const V_GAP = 120;

function getStatusColor(status?: string): string {
  switch (status) {
    case "completed":
      return "#34d399";
    case "running":
      return "#4f8cff";
    case "waiting_for_human":
      return "#fbbf24";
    case "failed":
      return "#f87171";
    default:
      return "#2e3140";
  }
}

export function FlowGraph({ nodes, edges, executionOrder, nodeStates }: FlowGraphProps) {
  const { rfNodes, rfEdges } = useMemo(() => {
    const rfNodes: Node[] = [];
    const rfEdges: Edge[] = [];

    executionOrder.forEach((wave, waveIndex) => {
      wave.forEach((nodeId, nodeIndex) => {
        const dagNode = nodes.find((n) => n.id === nodeId);
        if (!dagNode) return;

        const x = nodeIndex * (NODE_WIDTH + H_GAP) - ((wave.length - 1) * (NODE_WIDTH + H_GAP)) / 2 + 400;
        const y = waveIndex * (NODE_HEIGHT + V_GAP) + 40;

        const status = nodeStates?.[nodeId];

        rfNodes.push({
          id: nodeId,
          position: { x, y },
          data: {
            label: (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
                  {dagNode.is_human ? "👤 " : ""}
                  {dagNode.label}
                </div>
                {dagNode.description && (
                  <div style={{ fontSize: 11, opacity: 0.7, lineHeight: 1.3 }}>
                    {dagNode.description.slice(0, 60)}
                  </div>
                )}
              </div>
            ),
          },
          sourcePosition: Position.Bottom,
          targetPosition: Position.Top,
          style: {
            width: NODE_WIDTH,
            background: "#1a1d27",
            border: `2px solid ${getStatusColor(status)}`,
            borderRadius: 8,
            padding: "10px 12px",
            color: "#e4e6eb",
            fontSize: 12,
          },
        });
      });
    });

    edges.forEach((edge, i) => {
      rfEdges.push({
        id: `e-${i}`,
        source: edge.source,
        target: edge.target,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#4f8cff" },
        style: { stroke: "#4f8cff", strokeWidth: 2 },
        animated: nodeStates?.[edge.target] === "running",
      });
    });

    return { rfNodes, rfEdges };
  }, [nodes, edges, executionOrder, nodeStates]);

  return (
    <div className="flow-graph-container">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#2e3140" gap={20} />
        <Controls />
      </ReactFlow>
    </div>
  );
}
