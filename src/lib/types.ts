export interface LodConfig {
  level: number;
  gridSize: number;
  pattern: string;
  imageSize?: number;  // Actual image size in pixels (for downscaled LODs)
}

export interface OverlayConfig {
  map: string;
  offsetX: number;
  offsetY: number;
  scale: number;
}

export interface MapConfig {
  name: string;
  tileSize: number;
  lods: LodConfig[];
  overlays?: OverlayConfig[];
  minLayer?: number;
  maxLayer?: number;
  // For virtual maps (no LODs), defines the world coordinate space size
  virtualSize?: number;
  // When true, automatically enables revealAlpha A tiles on load
  revealTransparency?: boolean;
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface TileCoord {
  x: number;
  y: number;
  lod: number;
}

export interface CachedTile {
  image: HTMLImageElement;
  loaded: boolean;
  error: boolean;
}

export interface GameConfig {
  name: string;
  local: string;
  remote: string;
  maps: string[];
}

export interface GamesConfig {
  games: GameConfig[];
}
