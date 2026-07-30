export type PlanarPoint = { x: number; z: number };

export type PlanarRect = {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
};

export type DepenetrationResult = PlanarPoint & {
  moved: boolean;
  clear: boolean;
  iterations: number;
};

export type PlanarBounds = {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
};

const CONTACT_EPSILON = 0.002;

/**
 * House movement uses a conservative circular body against axis-aligned scene
 * footprints. Treating the rectangle as expanded by the body radius keeps the
 * same semantics as the old overlap check while making the geometry reusable
 * by both the player camera and Alpecca.
 */
export function circleIntersectsRect(
  point: PlanarPoint,
  radius: number,
  rect: PlanarRect,
) {
  return (
    point.x > rect.minX - radius &&
    point.x < rect.maxX + radius &&
    point.z > rect.minZ - radius &&
    point.z < rect.maxZ + radius
  );
}

export function circleIntersectsAnyRect(
  point: PlanarPoint,
  radius: number,
  rects: readonly PlanarRect[],
) {
  return rects.some((rect) => circleIntersectsRect(point, radius, rect));
}

function clearCandidate(
  point: PlanarPoint,
  radius: number,
  rects: readonly PlanarRect[],
) {
  return !circleIntersectsAnyRect(point, radius, rects);
}

/**
 * Recover a body whose center is already inside one or more expanded scene
 * footprints. The previous movement code only tested the next tiny step, so a
 * body restored or hot-reloaded inside furniture could never leave it.
 */
export function depenetrateCircle(
  point: PlanarPoint,
  radius: number,
  rects: readonly PlanarRect[],
  maxIterations = 16,
): DepenetrationResult {
  let x = point.x;
  let z = point.z;
  let moved = false;

  for (let iteration = 0; iteration < maxIterations; iteration += 1) {
    const current = { x, z };
    const overlaps = rects.filter((rect) => circleIntersectsRect(current, radius, rect));
    if (!overlaps.length) {
      return { x, z, moved, clear: true, iterations: iteration };
    }

    const candidates: PlanarPoint[] = [];
    for (const rect of overlaps) {
      candidates.push(
        { x: rect.minX - radius - CONTACT_EPSILON, z },
        { x: rect.maxX + radius + CONTACT_EPSILON, z },
        { x, z: rect.minZ - radius - CONTACT_EPSILON },
        { x, z: rect.maxZ + radius + CONTACT_EPSILON },
      );
    }
    candidates.sort((left, right) => (
      Math.hypot(left.x - x, left.z - z) - Math.hypot(right.x - x, right.z - z)
    ));

    const globallyClear = candidates.find((candidate) => clearCandidate(candidate, radius, rects));
    const chosen = globallyClear ?? candidates[0];
    if (!chosen || (chosen.x === x && chosen.z === z)) break;
    x = chosen.x;
    z = chosen.z;
    moved = true;
  }

  return {
    x,
    z,
    moved,
    clear: !circleIntersectsAnyRect({ x, z }, radius, rects),
    iterations: maxIterations,
  };
}

/** Return the axis-aligned footprint of a rectangle rotated around its center. */
export function orientedRectFootprint(
  center: PlanarPoint,
  sizeX: number,
  sizeZ: number,
  yaw: number,
): PlanarRect {
  const cosine = Math.abs(Math.cos(yaw));
  const sine = Math.abs(Math.sin(yaw));
  const worldSizeX = cosine * sizeX + sine * sizeZ;
  const worldSizeZ = sine * sizeX + cosine * sizeZ;
  return {
    minX: center.x - worldSizeX / 2,
    maxX: center.x + worldSizeX / 2,
    minZ: center.z - worldSizeZ / 2,
    maxZ: center.z + worldSizeZ / 2,
  };
}

export function segmentClearsRects(
  from: PlanarPoint,
  to: PlanarPoint,
  radius: number,
  rects: readonly PlanarRect[],
  sampleStep = 0.12,
) {
  const distance = Math.hypot(to.x - from.x, to.z - from.z);
  const steps = Math.max(1, Math.ceil(distance / Math.max(0.04, sampleStep)));
  for (let index = 0; index <= steps; index += 1) {
    const ratio = index / steps;
    const point = {
      x: from.x + (to.x - from.x) * ratio,
      z: from.z + (to.z - from.z) * ratio,
    };
    if (circleIntersectsAnyRect(point, radius, rects)) return false;
  }
  return true;
}

type GridCell = { x: number; z: number; column: number; row: number };

function nearestReachableCell(
  point: PlanarPoint,
  radius: number,
  rects: readonly PlanarRect[],
  bounds: PlanarBounds,
  cellSize: number,
  columns: number,
  rows: number,
) {
  const centerColumn = Math.round((point.x - bounds.minX) / cellSize);
  const centerRow = Math.round((point.z - bounds.minZ) / cellSize);
  const candidates: GridCell[] = [];
  const searchRadius = Math.max(columns, rows);

  for (let ring = 0; ring <= searchRadius; ring += 1) {
    candidates.length = 0;
    for (let column = centerColumn - ring; column <= centerColumn + ring; column += 1) {
      for (let row = centerRow - ring; row <= centerRow + ring; row += 1) {
        if (column < 0 || row < 0 || column >= columns || row >= rows) continue;
        if (ring > 0 && Math.max(Math.abs(column - centerColumn), Math.abs(row - centerRow)) !== ring) continue;
        const candidate = {
          x: bounds.minX + column * cellSize,
          z: bounds.minZ + row * cellSize,
          column,
          row,
        };
        if (circleIntersectsAnyRect(candidate, radius, rects)) continue;
        if (!segmentClearsRects(point, candidate, radius, rects, cellSize / 2)) continue;
        candidates.push(candidate);
      }
    }
    if (candidates.length) {
      candidates.sort((left, right) => (
        Math.hypot(left.x - point.x, left.z - point.z) - Math.hypot(right.x - point.x, right.z - point.z)
      ));
      return candidates[0];
    }
  }
  return null;
}

/**
 * Find a bounded eight-direction route around the current House footprints.
 * This is deliberately small and deterministic: it runs only when an authored
 * route segment is blocked and never becomes a second simulation authority.
 */
export function findGridRoute(
  from: PlanarPoint,
  to: PlanarPoint,
  radius: number,
  rects: readonly PlanarRect[],
  bounds: PlanarBounds,
  cellSize = 0.24,
  maxVisited = 6000,
): PlanarPoint[] | null {
  const recoveredFrom = depenetrateCircle(from, radius, rects);
  const recoveredTo = depenetrateCircle(to, radius, rects);
  if (!recoveredFrom.clear || !recoveredTo.clear) return null;
  const startPoint = { x: recoveredFrom.x, z: recoveredFrom.z };
  const goalPoint = { x: recoveredTo.x, z: recoveredTo.z };
  if (segmentClearsRects(startPoint, goalPoint, radius, rects, cellSize / 2)) return [goalPoint];

  const columns = Math.floor((bounds.maxX - bounds.minX) / cellSize) + 1;
  const rows = Math.floor((bounds.maxZ - bounds.minZ) / cellSize) + 1;
  if (columns <= 0 || rows <= 0 || columns * rows > 12000) return null;
  const start = nearestReachableCell(startPoint, radius, rects, bounds, cellSize, columns, rows);
  const goal = nearestReachableCell(goalPoint, radius, rects, bounds, cellSize, columns, rows);
  if (!start || !goal) return null;

  const key = (column: number, row: number) => `${column}:${row}`;
  const startKey = key(start.column, start.row);
  const goalKey = key(goal.column, goal.row);
  const open = new Set([startKey]);
  const cells = new Map<string, GridCell>([[startKey, start], [goalKey, goal]]);
  const parents = new Map<string, string>();
  const scores = new Map<string, number>([[startKey, 0]]);
  const estimates = new Map<string, number>([[startKey, Math.hypot(goal.x - start.x, goal.z - start.z)]]);
  const directions = [
    [-1, 0], [1, 0], [0, -1], [0, 1],
    [-1, -1], [-1, 1], [1, -1], [1, 1],
  ] as const;
  let visited = 0;

  while (open.size && visited < maxVisited) {
    let currentKey = "";
    let currentEstimate = Infinity;
    for (const candidateKey of open) {
      const estimate = estimates.get(candidateKey) ?? Infinity;
      if (estimate < currentEstimate) {
        currentEstimate = estimate;
        currentKey = candidateKey;
      }
    }
    if (!currentKey) break;
    if (currentKey === goalKey) {
      const reversed: PlanarPoint[] = [goalPoint];
      let cursor = goalKey;
      while (cursor !== startKey) {
        const cell = cells.get(cursor);
        if (!cell) return null;
        reversed.push({ x: cell.x, z: cell.z });
        const parent = parents.get(cursor);
        if (!parent) return null;
        cursor = parent;
      }
      reversed.push(startPoint);
      reversed.reverse();

      const simplified: PlanarPoint[] = [];
      let anchor = 0;
      while (anchor < reversed.length - 1) {
        let next = reversed.length - 1;
        while (next > anchor + 1 && !segmentClearsRects(reversed[anchor], reversed[next], radius, rects, cellSize / 2)) {
          next -= 1;
        }
        simplified.push(reversed[next]);
        anchor = next;
      }
      return simplified;
    }

    open.delete(currentKey);
    visited += 1;
    const current = cells.get(currentKey);
    if (!current) continue;
    for (const [columnDelta, rowDelta] of directions) {
      const column = current.column + columnDelta;
      const row = current.row + rowDelta;
      if (column < 0 || row < 0 || column >= columns || row >= rows) continue;
      const neighbor: GridCell = {
        x: bounds.minX + column * cellSize,
        z: bounds.minZ + row * cellSize,
        column,
        row,
      };
      if (circleIntersectsAnyRect(neighbor, radius, rects)) continue;
      if (columnDelta !== 0 && rowDelta !== 0) {
        const horizontal = { x: bounds.minX + column * cellSize, z: current.z };
        const vertical = { x: current.x, z: bounds.minZ + row * cellSize };
        if (circleIntersectsAnyRect(horizontal, radius, rects) || circleIntersectsAnyRect(vertical, radius, rects)) continue;
      }
      const neighborKey = key(column, row);
      cells.set(neighborKey, neighbor);
      const stepCost = columnDelta !== 0 && rowDelta !== 0 ? Math.SQRT2 : 1;
      const tentative = (scores.get(currentKey) ?? Infinity) + stepCost;
      if (tentative >= (scores.get(neighborKey) ?? Infinity)) continue;
      parents.set(neighborKey, currentKey);
      scores.set(neighborKey, tentative);
      estimates.set(neighborKey, tentative + Math.hypot(goal.x - neighbor.x, goal.z - neighbor.z) / cellSize);
      open.add(neighborKey);
    }
  }
  return null;
}

