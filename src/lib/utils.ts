import type { Viewport, LodConfig, TileCoord } from './types';

export function screenToWorld(
  screenX: number,
  screenY: number,
  viewport: Viewport,
  canvasWidth: number,
  canvasHeight: number
): { x: number; y: number } {
  const scale = Math.pow(2, viewport.zoom);
  return {
    x: viewport.x + (screenX - canvasWidth / 2) / scale,
    y: viewport.y + (screenY - canvasHeight / 2) / scale,
  };
}

export function worldToScreen(
  worldX: number,
  worldY: number,
  viewport: Viewport,
  canvasWidth: number,
  canvasHeight: number
): { x: number; y: number } {
  const scale = Math.pow(2, viewport.zoom);
  return {
    x: (worldX - viewport.x) * scale + canvasWidth / 2,
    y: (worldY - viewport.y) * scale + canvasHeight / 2,
  };
}

export function selectLOD(
  zoom: number,
  pixelRatio: number,
  tileSize: number,
  lods: LodConfig[],
  additionalScale: number = 1
): LodConfig {
  const scale = Math.pow(2, zoom) * additionalScale;

  // Sort LODs from highest detail (level 0) to lowest
  const sortedLods = [...lods].sort((a, b) => a.level - b.level);
  const maxGridSize = sortedLods[0]?.gridSize ?? 1;
  const totalMapSize = tileSize * maxGridSize;

  // Find the highest detail LOD where tiles would appear >= 75% of their image resolution
  for (const lod of sortedLods) {
    // Use imageSize if available, otherwise fall back to tileSize
    const imageSize = lod.imageSize ?? tileSize;
    const threshold = imageSize * 0.75;

    const worldTileSize = totalMapSize / lod.gridSize;
    const screenTileSize = worldTileSize * scale * pixelRatio;
    if (screenTileSize >= threshold) {
      return lod;
    }
  }

  return sortedLods[sortedLods.length - 1];
}

export function getVisibleTiles(
  viewport: Viewport,
  canvasWidth: number,
  canvasHeight: number,
  tileSize: number,
  lod: LodConfig,
  maxGridSize: number
): TileCoord[] {
  const totalMapSize = tileSize * maxGridSize;
  const worldTileSize = totalMapSize / lod.gridSize;

  const topLeft = screenToWorld(0, 0, viewport, canvasWidth, canvasHeight);
  const bottomRight = screenToWorld(canvasWidth, canvasHeight, viewport, canvasWidth, canvasHeight);

  const startTileX = Math.floor(topLeft.x / worldTileSize);
  const startTileY = Math.floor(topLeft.y / worldTileSize);
  const endTileX = Math.floor(bottomRight.x / worldTileSize);
  const endTileY = Math.floor(bottomRight.y / worldTileSize);

  const tiles: TileCoord[] = [];
  for (let y = startTileY; y <= endTileY; y++) {
    for (let x = startTileX; x <= endTileX; x++) {
      tiles.push({ x, y, lod: lod.level });
    }
  }

  return tiles;
}

export function getTileUrl(
  basePath: string,
  pattern: string,
  x: number,
  y: number,
  gridSize: number,
  layer: number = 0,
  revealAlpha: string = ''
): string | null {
  if (x < 0 || y < 0 || x >= gridSize || y >= gridSize) {
    return null;
  }
  const index = y * gridSize + x;
  let filename = pattern
    .replace('{index}', String(index))
    .replace('{layer}', String(layer));

  // Add revealAlpha suffix before extension (e.g., split_0 -> split_0a)
  if (revealAlpha) {
    // Check if filename has extension
    const extMatch = filename.match(/\.(png|webp)$/);
    if (extMatch) {
      filename = filename.slice(0, -extMatch[0].length) + revealAlpha + extMatch[0];
    } else {
      filename += revealAlpha;
    }
  }

  // Add extension if not present (prefer WebP for optimal loading)
  if (!filename.endsWith('.png') && !filename.endsWith('.webp')) {
    filename += '.webp';
  }

  return `${basePath}/${filename}`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
