import type { JsonValue } from '@/bot/schema';

export type TreeLocation = { parentId: string | null; slot: 'root' | string };
export type BotNodeData = { actionType: string; params: Record<string, JsonValue>; readOnly: boolean };
export type BotEditorNode = { id: string; data: BotNodeData; slots: Record<string, string[]> };
export type BotMetadata = { schemaVersion: 1 | 2; id: string; name: string; description: string; icon?: string };
export type BotEditorState = {
  metadata: BotMetadata;
  nodes: BotEditorNode[];
  root: string[];
  selectedNodeId: string | null;
  collapsedNodeIds: string[];
  representation: 'tree' | 'readOnlyGraph';
  legacyEdges: Array<{ id: string; source: string; target: string }>;
};
