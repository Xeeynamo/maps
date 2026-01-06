import type { MapConfig, CachedTile, LodConfig } from './types';
import { getTileUrl } from './utils';

export class TileManager {
  private cache: Map<string, CachedTile> = new Map();
  private config: MapConfig;
  private basePath: string;
  private onTileLoaded: () => void;
  private revealAlpha: string = '';

  constructor(config: MapConfig, basePath: string, onTileLoaded: () => void) {
    this.config = config;
    this.basePath = basePath;
    this.onTileLoaded = onTileLoaded;
  }

  getRevealAlpha(): string {
    return this.revealAlpha;
  }

  setRevealAlpha(revealAlpha: string): void {
    if (this.revealAlpha !== revealAlpha) {
      this.revealAlpha = revealAlpha;
      this.cache.clear();
      this.onTileLoaded();
    }
  }

  private getCacheKey(x: number, y: number, lod: number, layer: number): string {
    return `${lod}:${x},${y}:L${layer}:V${this.revealAlpha}`;
  }

  getMinLayer(): number {
    return this.config.minLayer ?? 0;
  }

  getMaxLayer(): number {
    return this.config.maxLayer ?? this.getMinLayer();
  }

  getLayerCount(): number {
    return this.getMaxLayer() - this.getMinLayer() + 1;
  }

  getTile(x: number, y: number, lod: LodConfig, layer: number): CachedTile | null {
    const key = this.getCacheKey(x, y, lod.level, layer);

    if (this.cache.has(key)) {
      return this.cache.get(key)!;
    }

    const url = getTileUrl(this.basePath, lod.pattern, x, y, lod.gridSize, layer, this.revealAlpha);
    if (!url) {
      return null;
    }

    const image = new Image();
    const cachedTile: CachedTile = {
      image,
      loaded: false,
      error: false,
    };

    image.onload = () => {
      cachedTile.loaded = true;
      this.onTileLoaded();
    };

    image.onerror = () => {
      cachedTile.error = true;
      this.onTileLoaded();
    };

    image.src = url;
    this.cache.set(key, cachedTile);

    return cachedTile;
  }

  // Check if a tile is already cached and loaded (without initiating a load)
  private getCachedTile(x: number, y: number, lod: LodConfig, layer: number): CachedTile | null {
    const key = this.getCacheKey(x, y, lod.level, layer);
    const cached = this.cache.get(key);
    if (cached && cached.loaded && !cached.error) {
      return cached;
    }
    return null;
  }

  getTileWithFallback(
    x: number,
    y: number,
    preferredLod: LodConfig,
    layer: number
  ): { tile: CachedTile | null; lod: LodConfig; fallbackX: number; fallbackY: number } | null {
    const sortedLods = [...this.config.lods].sort((a, b) => a.level - b.level);
    const startIndex = sortedLods.findIndex(l => l.level === preferredLod.level);

    // First, initiate load for the preferred LOD (but don't wait for it)
    const preferredTile = this.getTile(x, y, preferredLod, layer);

    // If preferred tile is already loaded, use it
    if (preferredTile && preferredTile.loaded && !preferredTile.error) {
      return { tile: preferredTile, lod: preferredLod, fallbackX: x, fallbackY: y };
    }

    // Search for a fallback from already-cached lower-res tiles (don't initiate new loads)
    for (let i = startIndex + 1; i < sortedLods.length; i++) {
      const lod = sortedLods[i];
      const scaleFactor = lod.gridSize / preferredLod.gridSize;
      const fallbackX = Math.floor(x * scaleFactor);
      const fallbackY = Math.floor(y * scaleFactor);

      const cachedTile = this.getCachedTile(fallbackX, fallbackY, lod, layer);
      if (cachedTile) {
        return { tile: cachedTile, lod, fallbackX, fallbackY };
      }
    }

    // No fallback available, return the loading preferred tile
    return { tile: preferredTile, lod: preferredLod, fallbackX: x, fallbackY: y };
  }

  // Get tiles for all layers at a position
  getAllLayerTiles(
    x: number,
    y: number,
    preferredLod: LodConfig
  ): Array<{ tile: CachedTile | null; lod: LodConfig; fallbackX: number; fallbackY: number; layer: number }> {
    const results = [];
    for (let layer = this.getMinLayer(); layer <= this.getMaxLayer(); layer++) {
      const result = this.getTileWithFallback(x, y, preferredLod, layer);
      if (result) {
        results.push({ ...result, layer });
      }
    }
    return results;
  }

  drawDebugTile(
    ctx: CanvasRenderingContext2D,
    screenX: number,
    screenY: number,
    screenSize: number,
    tileX: number,
    tileY: number,
    lod: number
  ): void {
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(screenX, screenY, screenSize, screenSize);

    ctx.strokeStyle = '#4a4a6a';
    ctx.lineWidth = 2;
    ctx.strokeRect(screenX, screenY, screenSize, screenSize);

    ctx.strokeStyle = '#3a3a5a';
    ctx.beginPath();
    ctx.moveTo(screenX, screenY);
    ctx.lineTo(screenX + screenSize, screenY + screenSize);
    ctx.moveTo(screenX + screenSize, screenY);
    ctx.lineTo(screenX, screenY + screenSize);
    ctx.stroke();

    ctx.fillStyle = '#8888aa';
    ctx.font = `${Math.max(12, screenSize / 8)}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const centerX = screenX + screenSize / 2;
    const centerY = screenY + screenSize / 2;
    const lineHeight = Math.max(16, screenSize / 6);

    ctx.fillText(`(${tileX}, ${tileY})`, centerX, centerY - lineHeight / 2);
    ctx.fillText(`LOD ${lod}`, centerX, centerY + lineHeight / 2);
  }
}
