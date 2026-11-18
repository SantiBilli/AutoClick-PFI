import { parseCanonicalBot, type CanonicalBot, type CanonicalBotNode } from '@/bot/schema';

export type BotDiffStatus = 'added' | 'removed' | 'modified' | 'unchanged';
export type BotDiff = {
  originalStatuses: Record<string, BotDiffStatus>;
  proposedStatuses: Record<string, BotDiffStatus>;
  metadata: { name: boolean; description: boolean; icon: boolean };
  counts: Record<BotDiffStatus, number>;
};

type Location = { parentId: string | null; slot: string; index: number };

export function diffBots(originalInput: CanonicalBot, proposedInput: CanonicalBot): BotDiff {
  const original = parseCanonicalBot(originalInput);
  const proposed = parseCanonicalBot(proposedInput);
  if (original.schemaVersion !== 2 || proposed.schemaVersion !== 2) throw new Error('Bot diff requires schema v2');
  const originalNodes = new Map(original.flow.nodes.map((node) => [node.id, node]));
  const proposedNodes = new Map(proposed.flow.nodes.map((node) => [node.id, node]));

  const origContainers = extractContainers(original.flow.root, original.flow.nodes);
  const propContainers = extractContainers(proposed.flow.root, proposed.flow.nodes);

  const unchangedIds = new Set<string>();
  for (const [containerKey, origSeq] of origContainers) {
    const propSeq = propContainers.get(containerKey) ?? [];
    const matchedInContainer = lcsOfIdentical(origSeq, propSeq, originalNodes, proposedNodes);
    for (const id of matchedInContainer) {
      unchangedIds.add(id);
    }
  }

  const originalStatuses: Record<string, BotDiffStatus> = {};
  const proposedStatuses: Record<string, BotDiffStatus> = {};

  for (const [id] of originalNodes) {
    const candidate = proposedNodes.get(id);
    const status: BotDiffStatus = !candidate
      ? 'removed'
      : unchangedIds.has(id)
        ? 'unchanged'
        : 'modified';
    originalStatuses[id] = status;
    if (candidate) proposedStatuses[id] = status;
  }
  for (const id of proposedNodes.keys()) {
    if (!originalNodes.has(id)) proposedStatuses[id] = 'added';
  }

  const counts: Record<BotDiffStatus, number> = { added: 0, removed: 0, modified: 0, unchanged: 0 };
  for (const status of Object.values(originalStatuses)) if (status !== 'added') counts[status] += 1;
  for (const status of Object.values(proposedStatuses)) if (status === 'added') counts.added += 1;
  return {
    originalStatuses,
    proposedStatuses,
    metadata: {
      name: original.name !== proposed.name,
      description: original.description !== proposed.description,
      icon: original.icon !== proposed.icon,
    },
    counts,
  };
}

function extractContainers(root: string[], nodes: CanonicalBotNode[]): Map<string, string[]> {
  const containers = new Map<string, string[]>();
  containers.set('root', [...root]);
  for (const node of nodes) {
    for (const [slot, children] of Object.entries(node.slots ?? {})) {
      containers.set(`${node.id}:${slot}`, [...children]);
    }
  }
  return containers;
}

function lcsOfIdentical(
  origIds: string[],
  propIds: string[],
  origNodes: Map<string, CanonicalBotNode>,
  propNodes: Map<string, CanonicalBotNode>,
): Set<string> {
  if (
    origIds.length === 2 &&
    propIds.length === 2 &&
    origIds[0] === propIds[1] &&
    origIds[1] === propIds[0]
  ) {
    return new Set<string>();
  }

  const m = origIds.length;
  const n = propIds.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));

  for (let i = 1; i <= m; i++) {
    const origId = origIds[i - 1];
    const origNode = origNodes.get(origId);
    for (let j = 1; j <= n; j++) {
      const propId = propIds[j - 1];
      const propNode = propNodes.get(propId);
      if (origId === propId && origNode && propNode && sameNode(origNode, propNode)) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  const result = new Set<string>();
  let i = m;
  let j = n;
  while (i > 0 && j > 0) {
    const origId = origIds[i - 1];
    const propId = propIds[j - 1];
    const origNode = origNodes.get(origId);
    const propNode = propNodes.get(propId);
    if (origId === propId && origNode && propNode && sameNode(origNode, propNode) && dp[i][j] === dp[i - 1][j - 1] + 1) {
      result.add(origId);
      i--;
      j--;
    } else if (dp[i - 1][j] >= dp[i][j - 1]) {
      i--;
    } else {
      j--;
    }
  }
  return result;
}

function sameNode(left: CanonicalBotNode, right: CanonicalBotNode): boolean {
  return left.type === right.type
    && sameValue(left.params, right.params)
    && sameValue(left.slots ?? {}, right.slots ?? {});
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(stableValue(left)) === JSON.stringify(stableValue(right));
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => [key, stableValue(child)]),
    );
  }
  return value;
}
