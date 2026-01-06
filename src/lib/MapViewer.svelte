<script lang="ts">
  import { onMount } from 'svelte';
  import type { MapConfig, Viewport, LodConfig, OverlayConfig, GameConfig } from './types';
  import { TileManager } from './TileManager';
  import { screenToWorld, worldToScreen, selectLOD, getVisibleTiles, clamp } from './utils';

  interface Props {
    config: MapConfig;
    basePath: string;
    gameBaseUrl: string;
    availableGames: GameConfig[];
    currentGameName: string;
    onGameChange: (gameName: string) => void;
    availableMaps: string[];
    currentMapName: string;
    onMapChange: (mapName: string) => void;
  }

  let { config, basePath, gameBaseUrl, availableGames, currentGameName, onGameChange, availableMaps, currentMapName, onMapChange }: Props = $props();

  let canvas: HTMLCanvasElement;
  let ctx: CanvasRenderingContext2D | null = null;
  let tileManager: TileManager;
  let animationId: number;

  interface LoadedOverlay {
    config: OverlayConfig;
    mapConfig: MapConfig;
    tileManager: TileManager;
    // Accumulated transform in root world coordinates
    worldOffsetX: number;
    worldOffsetY: number;
    worldScale: number;
    visible: boolean;
  }

  // Tree node for the UI
  interface MapTreeNode {
    name: string;
    overlayIndex: number | null; // null for root map
    visible: boolean;
    revealTransparency: boolean;
    children: MapTreeNode[];
  }

  // Flattened list of all overlays (including nested ones)
  let overlays: LoadedOverlay[] = $state([]);

  // Tree structure for the visibility UI
  let mapTree: MapTreeNode | null = $state(null);
  let rootMapVisible = $state(true);

  // UI state for panel collapsing
  let panelCollapsed = $state(false);
  let layersCollapsed = $state(false);

  let viewport: Viewport = $state({ x: 0, y: 0, zoom: 0 });
  let isDragging = $state(false);
  let lastMouseX = 0;
  let lastMouseY = 0;

  let lastTouchDist = 0;
  let lastTouchCenter = { x: 0, y: 0 };

  const MIN_ZOOM = -6;
  const MAX_ZOOM = 6;
  const PAN_SPEED = 100;

  function requestRender() {
    if (animationId) cancelAnimationFrame(animationId);
    animationId = requestAnimationFrame(render);
  }

  function render() {
    if (!ctx || !canvas) return;

    const width = canvas.width;
    const height = canvas.height;
    const pixelRatio = window.devicePixelRatio || 1;

    ctx.fillStyle = '#0a0a0f';
    ctx.fillRect(0, 0, width, height);

    const scale = Math.pow(2, viewport.zoom);
    const isVirtualMap = !config.lods || config.lods.length === 0;

    // Only render base map tiles if this is not a virtual map and visible
    if (!isVirtualMap && tileManager && rootMapVisible) {
      const lod = selectLOD(viewport.zoom, pixelRatio, config.tileSize, config.lods);
      const maxGridSize = config.lods[0]?.gridSize ?? 1;
      const visibleTiles = getVisibleTiles(viewport, width / pixelRatio, height / pixelRatio, config.tileSize, lod, maxGridSize);

      const totalMapSize = config.tileSize * maxGridSize;
      const tileWorldSize = totalMapSize / lod.gridSize;
      const tileScreenSize = tileWorldSize * scale;

      for (const tileCoord of visibleTiles) {
        const worldX = tileCoord.x * tileWorldSize;
        const worldY = tileCoord.y * tileWorldSize;
        const screen = worldToScreen(worldX, worldY, viewport, width / pixelRatio, height / pixelRatio);

        const screenX = screen.x * pixelRatio;
        const screenY = screen.y * pixelRatio;
        const screenSize = tileScreenSize * pixelRatio;

        // Render all layers stacked on top of each other
        for (let layer = tileManager.getMinLayer(); layer <= tileManager.getMaxLayer(); layer++) {
          const result = tileManager.getTileWithFallback(tileCoord.x, tileCoord.y, lod, layer);

          if (!result || !result.tile || !result.tile.loaded || result.tile.error) {
            // Only draw debug tile for the first layer
            if (layer === tileManager.getMinLayer()) {
              tileManager.drawDebugTile(ctx, screenX, screenY, screenSize, tileCoord.x, tileCoord.y, lod.level);
            }
          } else {
            if (result.lod.level !== lod.level) {
              const fallbackScale = result.lod.gridSize / lod.gridSize;
              const srcX = (tileCoord.x * fallbackScale - result.fallbackX) * config.tileSize;
              const srcY = (tileCoord.y * fallbackScale - result.fallbackY) * config.tileSize;
              const srcSize = config.tileSize * fallbackScale;

              ctx.drawImage(
                result.tile.image,
                srcX, srcY, srcSize, srcSize,
                screenX, screenY, screenSize, screenSize
              );
            } else {
              ctx.drawImage(result.tile.image, screenX, screenY, screenSize, screenSize);
            }
          }
        }
      }
    }

    // Render overlays on top (flattened list includes all nested overlays)
    for (const overlay of overlays) {
      if (overlay.visible) {
        renderOverlay(ctx, overlay, width, height, pixelRatio, scale);
      }
    }
  }

  function renderOverlay(
    ctx: CanvasRenderingContext2D,
    overlay: LoadedOverlay,
    width: number,
    height: number,
    pixelRatio: number,
    viewScale: number
  ) {
    const { mapConfig: ovConfig, tileManager: ovTileManager, worldOffsetX, worldOffsetY, worldScale } = overlay;

    // Skip virtual maps (no LODs)
    if (!ovConfig.lods || ovConfig.lods.length === 0) {
      return;
    }

    const ovMaxGridSize = ovConfig.lods[0]?.gridSize ?? 1;
    const ovTotalSize = ovConfig.tileSize * ovMaxGridSize;

    // Select LOD for overlay based on current zoom and the overlay's world scale
    const ovLod = selectLOD(viewport.zoom, pixelRatio, ovConfig.tileSize, ovConfig.lods, worldScale);
    const ovTileWorldSize = ovTotalSize / ovLod.gridSize;

    // Transform overlay world coords to root world coords using accumulated transform
    const ovTileWorldSizeInRoot = ovTileWorldSize * worldScale;
    const ovTileScreenSize = ovTileWorldSizeInRoot * viewScale;

    // Get visible tiles for this overlay
    for (let ty = 0; ty < ovLod.gridSize; ty++) {
      for (let tx = 0; tx < ovLod.gridSize; tx++) {
        // Calculate tile position in root world coordinates
        const tileWorldX = worldOffsetX + tx * ovTileWorldSizeInRoot;
        const tileWorldY = worldOffsetY + ty * ovTileWorldSizeInRoot;

        // Check if tile is visible
        const screen = worldToScreen(tileWorldX, tileWorldY, viewport, width / pixelRatio, height / pixelRatio);
        const screenX = screen.x * pixelRatio;
        const screenY = screen.y * pixelRatio;
        const screenSize = ovTileScreenSize * pixelRatio;

        // Skip if off screen
        if (screenX + screenSize < 0 || screenX > width || screenY + screenSize < 0 || screenY > height) {
          continue;
        }

        // Render all layers for overlays too
        for (let layer = ovTileManager.getMinLayer(); layer <= ovTileManager.getMaxLayer(); layer++) {
          const result = ovTileManager.getTileWithFallback(tx, ty, ovLod, layer);

          if (result && result.tile && result.tile.loaded && !result.tile.error) {
            if (result.lod.level !== ovLod.level) {
              const fallbackScale = result.lod.gridSize / ovLod.gridSize;
              const srcX = (tx * fallbackScale - result.fallbackX) * ovConfig.tileSize;
              const srcY = (ty * fallbackScale - result.fallbackY) * ovConfig.tileSize;
              const srcSize = ovConfig.tileSize * fallbackScale;

              ctx.drawImage(
                result.tile.image,
                srcX, srcY, srcSize, srcSize,
                screenX, screenY, screenSize, screenSize
              );
            } else {
              ctx.drawImage(result.tile.image, screenX, screenY, screenSize, screenSize);
            }
          }
        }
      }
    }
  }

  function handleResize() {
    if (!canvas) return;
    const pixelRatio = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * pixelRatio;
    canvas.height = window.innerHeight * pixelRatio;
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    requestRender();
  }

  function handleMouseDown(e: MouseEvent) {
    isDragging = true;
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  }

  function handleMouseMove(e: MouseEvent) {
    if (!isDragging) return;

    const dx = e.clientX - lastMouseX;
    const dy = e.clientY - lastMouseY;
    const scale = Math.pow(2, viewport.zoom);

    viewport.x -= dx / scale;
    viewport.y -= dy / scale;

    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    requestRender();
  }

  function handleMouseUp() {
    isDragging = false;
  }

  function handleWheel(e: WheelEvent) {
    e.preventDefault();

    const pixelRatio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const worldBefore = screenToWorld(mouseX, mouseY, viewport, canvas.width / pixelRatio, canvas.height / pixelRatio);

    const zoomDelta = e.deltaY > 0 ? -0.1 : 0.1;
    viewport.zoom = clamp(viewport.zoom + zoomDelta, MIN_ZOOM, MAX_ZOOM);

    const worldAfter = screenToWorld(mouseX, mouseY, viewport, canvas.width / pixelRatio, canvas.height / pixelRatio);

    viewport.x += worldBefore.x - worldAfter.x;
    viewport.y += worldBefore.y - worldAfter.y;

    requestRender();
  }

  function getTouchDistance(touches: TouchList): number {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function getTouchCenter(touches: TouchList): { x: number; y: number } {
    return {
      x: (touches[0].clientX + touches[1].clientX) / 2,
      y: (touches[0].clientY + touches[1].clientY) / 2,
    };
  }

  function handleTouchStart(e: TouchEvent) {
    if (e.touches.length === 1) {
      isDragging = true;
      lastMouseX = e.touches[0].clientX;
      lastMouseY = e.touches[0].clientY;
    } else if (e.touches.length === 2) {
      isDragging = false;
      lastTouchDist = getTouchDistance(e.touches);
      lastTouchCenter = getTouchCenter(e.touches);
    }
  }

  function handleTouchMove(e: TouchEvent) {
    e.preventDefault();

    if (e.touches.length === 1 && isDragging) {
      const dx = e.touches[0].clientX - lastMouseX;
      const dy = e.touches[0].clientY - lastMouseY;
      const scale = Math.pow(2, viewport.zoom);

      viewport.x -= dx / scale;
      viewport.y -= dy / scale;

      lastMouseX = e.touches[0].clientX;
      lastMouseY = e.touches[0].clientY;
      requestRender();
    } else if (e.touches.length === 2) {
      const pixelRatio = window.devicePixelRatio || 1;
      const dist = getTouchDistance(e.touches);
      const center = getTouchCenter(e.touches);

      const worldBefore = screenToWorld(center.x, center.y, viewport, canvas.width / pixelRatio, canvas.height / pixelRatio);

      const scaleFactor = dist / lastTouchDist;
      const zoomDelta = Math.log2(scaleFactor);
      viewport.zoom = clamp(viewport.zoom + zoomDelta, MIN_ZOOM, MAX_ZOOM);

      const worldAfter = screenToWorld(center.x, center.y, viewport, canvas.width / pixelRatio, canvas.height / pixelRatio);

      viewport.x += worldBefore.x - worldAfter.x;
      viewport.y += worldBefore.y - worldAfter.y;

      const dx = center.x - lastTouchCenter.x;
      const dy = center.y - lastTouchCenter.y;
      const scale = Math.pow(2, viewport.zoom);
      viewport.x -= dx / scale;
      viewport.y -= dy / scale;

      lastTouchDist = dist;
      lastTouchCenter = center;
      requestRender();
    }
  }

  function handleTouchEnd() {
    isDragging = false;
  }

  function handleKeyDown(e: KeyboardEvent) {
    const scale = Math.pow(2, viewport.zoom);
    const panAmount = PAN_SPEED / scale;

    switch (e.key) {
      case 'ArrowUp':
        viewport.y -= panAmount;
        requestRender();
        break;
      case 'ArrowDown':
        viewport.y += panAmount;
        requestRender();
        break;
      case 'ArrowLeft':
        viewport.x -= panAmount;
        requestRender();
        break;
      case 'ArrowRight':
        viewport.x += panAmount;
        requestRender();
        break;
      case '+':
      case '=':
        viewport.zoom = clamp(viewport.zoom + 0.2, MIN_ZOOM, MAX_ZOOM);
        requestRender();
        break;
      case '-':
      case '_':
        viewport.zoom = clamp(viewport.zoom - 0.2, MIN_ZOOM, MAX_ZOOM);
        requestRender();
        break;
    }
  }

  function getMapBasePath(mapName: string): string {
    return `${gameBaseUrl}/${mapName}`;
  }

  interface LoadResult {
    overlays: LoadedOverlay[];
    treeNodes: MapTreeNode[];
  }

  async function loadOverlaysRecursive(
    overlayDefs: OverlayConfig[],
    parentOffsetX: number,
    parentOffsetY: number,
    parentScale: number,
    currentIndex: { value: number }
  ): Promise<LoadResult> {
    const loaded: LoadedOverlay[] = [];
    const treeNodes: MapTreeNode[] = [];

    for (const overlayDef of overlayDefs) {
      try {
        const overlayBasePath = getMapBasePath(overlayDef.map);
        const response = await fetch(`${overlayBasePath}/config.json`);
        if (!response.ok) continue;

        const mapConfig: MapConfig = await response.json();
        const ovTileManager = new TileManager(mapConfig, overlayBasePath, requestRender);

        // Accumulate transform: child position in parent space -> parent position in root space
        const worldOffsetX = parentOffsetX + overlayDef.offsetX * parentScale;
        const worldOffsetY = parentOffsetY + overlayDef.offsetY * parentScale;
        const worldScale = parentScale * overlayDef.scale;

        const myIndex = currentIndex.value++;

        loaded.push({
          config: overlayDef,
          mapConfig,
          tileManager: ovTileManager,
          worldOffsetX,
          worldOffsetY,
          worldScale,
          visible: true,
        });

        const revealTransparency = mapConfig.revealTransparency === true;
        if (revealTransparency) {
          ovTileManager.setRevealAlpha('a');
        }

        const treeNode: MapTreeNode = {
          name: mapConfig.name,
          overlayIndex: myIndex,
          visible: true,
          revealTransparency: revealTransparency,
          children: [],
        };

        // Recursively load this overlay's overlays
        if (mapConfig.overlays && mapConfig.overlays.length > 0) {
          const childResult = await loadOverlaysRecursive(
            mapConfig.overlays,
            worldOffsetX,
            worldOffsetY,
            worldScale,
            currentIndex
          );
          loaded.push(...childResult.overlays);
          treeNode.children = childResult.treeNodes;
        }

        treeNodes.push(treeNode);
      } catch (e) {
        console.warn(`Failed to load overlay ${overlayDef.map}:`, e);
      }
    }

    return { overlays: loaded, treeNodes };
  }

  async function loadOverlays() {
    const rootrevealTransparency = config.revealTransparency === true;

    // Build tree with root map
    mapTree = {
      name: config.name,
      overlayIndex: null,
      visible: true,
      revealTransparency: rootrevealTransparency,
      children: [],
    };

    if (!config.overlays || config.overlays.length === 0) return;

    // Start with identity transform (offset 0,0 and scale 1)
    const result = await loadOverlaysRecursive(config.overlays, 0, 0, 1, { value: 0 });
    overlays = result.overlays;
    mapTree.children = result.treeNodes;
    requestRender();
  }

  function toggleVisibility(node: MapTreeNode) {
    node.visible = !node.visible;

    if (node.overlayIndex === null) {
      // This is the root map
      rootMapVisible = node.visible;
    } else {
      // This is an overlay
      overlays[node.overlayIndex].visible = node.visible;
    }

    requestRender();
  }

  function toggleRevealAlpha(node: MapTreeNode) {
    node.revealTransparency = !node.revealTransparency;
    const revealAlpha = node.revealTransparency ? 'a' : '';

    if (node.overlayIndex === null) {
      // This is the root map
      if (tileManager) {
        tileManager.setRevealAlpha(revealAlpha);
      }
    } else {
      // This is an overlay
      overlays[node.overlayIndex].tileManager.setRevealAlpha(revealAlpha);
    }

    requestRender();
  }

  function calculateOverlaysBoundingBox(): { minX: number; minY: number; maxX: number; maxY: number } | null {
    if (!config.overlays || config.overlays.length === 0) return null;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    for (const overlay of config.overlays) {
      // Estimate overlay size (we don't have the config loaded yet, so use a default)
      // This will be refined once overlays load
      const estimatedSize = 8192 * overlay.scale;
      minX = Math.min(minX, overlay.offsetX);
      minY = Math.min(minY, overlay.offsetY);
      maxX = Math.max(maxX, overlay.offsetX + estimatedSize);
      maxY = Math.max(maxY, overlay.offsetY + estimatedSize);
    }

    return { minX, minY, maxX, maxY };
  }

  function calculateZoomToFit(mapWidth: number, mapHeight: number): number {
    // Calculate zoom level that fits the entire map on screen
    const canvasWidth = canvas?.width ?? window.innerWidth;
    const canvasHeight = canvas?.height ?? window.innerHeight;
    const pixelRatio = window.devicePixelRatio || 1;

    // Leave some padding (90% of screen)
    const availableWidth = (canvasWidth / pixelRatio) * 0.9;
    const availableHeight = (canvasHeight / pixelRatio) * 0.9;

    // Calculate scale needed to fit each dimension
    const scaleX = availableWidth / mapWidth;
    const scaleY = availableHeight / mapHeight;

    // Use the smaller scale to ensure both dimensions fit
    const scale = Math.min(scaleX, scaleY);

    // Convert scale to zoom level (zoom = log2(scale))
    return Math.log2(scale);
  }

  function initializeMap() {
    const isVirtualMap = !config.lods || config.lods.length === 0;

    // Clear previous overlays and tree
    overlays = [];
    mapTree = null;
    rootMapVisible = true;

    // Cleanup old tile manager if it exists
    if (tileManager) {
      // TileManager doesn't have explicit cleanup, but we'll create a new one
    }

    if (!isVirtualMap) {
      tileManager = new TileManager(config, basePath, requestRender);
      if (config.revealTransparency) {
        tileManager.setRevealAlpha('a');
      }

      // Center viewport on the base map
      const gridSize = config.lods[0]?.gridSize ?? 1;
      const mapSize = config.tileSize * gridSize;
      viewport.x = mapSize / 2;
      viewport.y = mapSize / 2;

      // Calculate zoom to fit entire map on screen
      viewport.zoom = clamp(calculateZoomToFit(mapSize, mapSize), MIN_ZOOM, MAX_ZOOM);
    } else {
      // For virtual maps, center on the bounding box of overlays
      const bbox = calculateOverlaysBoundingBox();
      if (bbox) {
        const bboxWidth = bbox.maxX - bbox.minX;
        const bboxHeight = bbox.maxY - bbox.minY;
        viewport.x = (bbox.minX + bbox.maxX) / 2;
        viewport.y = (bbox.minY + bbox.maxY) / 2;
        // Calculate zoom to fit bounding box
        viewport.zoom = clamp(calculateZoomToFit(bboxWidth, bboxHeight), MIN_ZOOM, MAX_ZOOM);
      } else {
        const virtualSize = config.virtualSize ?? 32768;
        viewport.x = virtualSize / 2;
        viewport.y = virtualSize / 2;
        viewport.zoom = clamp(calculateZoomToFit(virtualSize, virtualSize), MIN_ZOOM, MAX_ZOOM);
      }
    }

    loadOverlays();
    requestRender();
  }

  onMount(() => {
    ctx = canvas.getContext('2d');

    handleResize();
    window.addEventListener('resize', handleResize);
    window.addEventListener('keydown', handleKeyDown);

    initializeMap();

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('keydown', handleKeyDown);
      if (animationId) cancelAnimationFrame(animationId);
    };
  });

  // React to config/basePath changes (when map is switched)
  $effect(() => {
    // Access the reactive dependencies
    config;
    basePath;

    // Skip on initial mount (handled by onMount)
    if (ctx) {
      initializeMap();
    }
  });
</script>

{#snippet treeNode(node: MapTreeNode, depth: number)}
  <div class="tree-item" style="padding-left: {depth * 16}px">
    <label class="tree-label">
      <input
        type="checkbox"
        checked={node.visible}
        onchange={() => toggleVisibility(node)}
      />
      <span class="tree-name">{node.name}</span>
    </label>
    <button
      class="revealAlpha-toggle"
      class:active={node.revealTransparency}
      onclick={() => toggleRevealAlpha(node)}
      title={node.revealTransparency ? "Switch to normal revealAlpha" : "Switch to revealAlpha A"}
    >
      A
    </button>
  </div>
  {#each node.children as child}
    {@render treeNode(child, depth + 1)}
  {/each}
{/snippet}

<canvas
  bind:this={canvas}
  onmousedown={handleMouseDown}
  onmousemove={handleMouseMove}
  onmouseup={handleMouseUp}
  onmouseleave={handleMouseUp}
  onwheel={handleWheel}
  ontouchstart={handleTouchStart}
  ontouchmove={handleTouchMove}
  ontouchend={handleTouchEnd}
></canvas>

{#if mapTree}
  <div class="tree-panel" class:collapsed={panelCollapsed}>
    {#if !panelCollapsed}
      <button
        class="panel-toggle"
        onclick={() => panelCollapsed = true}
        title="Collapse panel"
      >
        ✕
      </button>

      {#if availableGames.length > 0}
        <div class="map-selector">
          <label for="game-select" class="tree-header">Game</label>
          <select
            id="game-select"
            value={currentGameName}
            onchange={(e) => onGameChange(e.currentTarget.value)}
          >
            {#each availableGames as game}
              <option value={game.name}>{game.name}</option>
            {/each}
          </select>
        </div>
      {/if}

      {#if availableMaps.length > 0}
        <div class="map-selector">
          <label for="map-select" class="tree-header">Map</label>
          <select
            id="map-select"
            value={currentMapName}
            onchange={(e) => onMapChange(e.currentTarget.value)}
          >
            {#each availableMaps as mapName}
              <option value={mapName}>{mapName}</option>
            {/each}
          </select>
        </div>
      {/if}

      <div class="layers-section">
        <div class="tree-header-container">
          <div class="tree-header">Layers</div>
          <button
            class="section-toggle"
            onclick={() => layersCollapsed = !layersCollapsed}
            title={layersCollapsed ? "Expand layers" : "Collapse layers"}
          >
            {layersCollapsed ? '▸' : '▾'}
          </button>
        </div>

        {#if !layersCollapsed}
          {@render treeNode(mapTree, 0)}
        {/if}
      </div>

    {:else}
      <button
        class="panel-toggle-expand"
        onclick={() => panelCollapsed = false}
        title="Expand panel"
      >
        ☰
      </button>
    {/if}
  </div>
{/if}

<style>
  canvas {
    display: block;
    cursor: grab;
    touch-action: none;
  }

  canvas:active {
    cursor: grabbing;
  }

  .tree-panel {
    position: fixed;
    top: 16px;
    left: 16px;
    background: rgba(20, 20, 30, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 12px;
    color: #eee;
    font-family: system-ui, sans-serif;
    font-size: 13px;
    min-width: 180px;
    max-height: calc(100vh - 32px);
    overflow-y: auto;
    z-index: 100;
    transition: all 0.2s ease;
  }

  .tree-panel.collapsed {
    min-width: auto;
    padding: 8px;
    max-height: none;
    overflow: visible;
  }

  .tree-header {
    font-weight: 600;
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    color: #aaa;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
  }

  .tree-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 2px 0;
  }

  .tree-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }

  .tree-label:hover .tree-name {
    color: #fff;
  }

  .tree-name {
    color: #ccc;
    transition: color 0.15s;
  }

  input[type="checkbox"] {
    width: 14px;
    height: 14px;
    cursor: pointer;
    accent-color: #6a9fff;
  }

  .map-selector {
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }

  .map-selector label {
    display: block;
    margin-bottom: 6px;
  }

  select {
    width: 100%;
    padding: 6px 8px;
    background: rgba(40, 40, 50, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 4px;
    color: #eee;
    font-family: system-ui, sans-serif;
    font-size: 13px;
    cursor: pointer;
    outline: none;
  }

  select:hover {
    border-color: rgba(255, 255, 255, 0.3);
  }

  select:focus {
    border-color: #6a9fff;
  }

  option {
    background: #1a1a20;
    color: #eee;
  }

  .panel-toggle {
    position: absolute;
    top: 8px;
    right: 8px;
    background: transparent;
    border: none;
    color: #888;
    font-size: 16px;
    cursor: pointer;
    padding: 4px 8px;
    line-height: 1;
    border-radius: 4px;
    transition: all 0.15s;
  }

  .panel-toggle:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
  }

  .panel-toggle-expand {
    background: transparent;
    border: none;
    color: #ccc;
    font-size: 20px;
    cursor: pointer;
    padding: 4px;
    line-height: 1;
    border-radius: 4px;
    transition: all 0.15s;
    display: block;
  }

  .panel-toggle-expand:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
  }

  .tree-header-container {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .tree-header-container .tree-header {
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: none;
    flex: 1;
  }

  .section-toggle {
    background: transparent;
    border: none;
    color: #888;
    font-size: 14px;
    cursor: pointer;
    padding: 4px;
    line-height: 1;
    border-radius: 4px;
    transition: all 0.15s;
    margin-bottom: 8px;
  }

  .section-toggle:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
  }

  .layers-section {
    padding-top: 4px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
  }

  .revealAlpha-toggle {
    margin-left: auto;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 600;
    background: rgba(60, 60, 80, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 3px;
    color: #888;
    cursor: pointer;
    transition: all 0.15s;
  }

  .revealAlpha-toggle:hover {
    background: rgba(80, 80, 100, 0.8);
    border-color: rgba(255, 255, 255, 0.3);
    color: #ccc;
  }

  .revealAlpha-toggle.active {
    background: rgba(106, 159, 255, 0.3);
    border-color: #6a9fff;
    color: #6a9fff;
  }

  @media (max-width: 768px) {
    .tree-panel {
      font-size: 12px;
      min-width: 160px;
    }

    .panel-toggle,
    .panel-toggle-expand {
      padding: 8px;
      font-size: 18px;
    }
  }
</style>
