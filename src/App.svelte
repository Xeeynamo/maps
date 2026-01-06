<script lang="ts">
  import { onMount } from 'svelte';
  import MapViewer from './lib/MapViewer.svelte';
  import type { MapConfig, GameConfig } from './lib/types';

  let config: MapConfig | null = $state(null);
  let error: string | null = $state(null);
  let availableGames: GameConfig[] = $state([]);
  let currentGameIndex = $state(0);
  let currentMapName = $state('0001-WORLD+OpenAll');

  // Derived: maps for the currently selected game
  let availableMaps = $derived(availableGames[currentGameIndex]?.maps ?? []);
  let currentGameName = $derived(availableGames[currentGameIndex]?.name ?? '');

  // Get the base URL for the current game based on environment
  function getGameBaseUrl(game: GameConfig): string {
    return import.meta.env.DEV ? game.local : game.remote;
  }

  let currentGameBaseUrl = $derived(
    availableGames[currentGameIndex]
      ? getGameBaseUrl(availableGames[currentGameIndex])
      : '/maps'
  );

  function handleGameChange(gameName: string) {
    const index = availableGames.findIndex(g => g.name === gameName);
    if (index !== -1) {
      currentGameIndex = index;
      // Load the first map of the new game
      const firstMap = availableGames[index].maps[0];
      if (firstMap) {
        loadMap(firstMap);
      }
    }
  }

  async function loadMap(mapName: string) {
    try {
      const baseUrl = currentGameBaseUrl;
      const response = await fetch(`${baseUrl}/${mapName}/config.json`);
      if (!response.ok) {
        throw new Error(`Failed to load map config: ${response.status}`);
      }
      config = await response.json();
      currentMapName = mapName;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Unknown error';
      config = null;
    }
  }

  onMount(async () => {
    try {
      // Load available games and maps list
      const mapsResponse = await fetch('/maps/config.json');
      if (mapsResponse.ok) {
        const mapsConfig = await mapsResponse.json();
        availableGames = mapsConfig.games || [];
        // Set initial map to first map of first game
        if (availableGames.length > 0 && availableGames[0].maps.length > 0) {
          currentMapName = availableGames[0].maps[0];
        }
      }
    } catch (e) {
      console.warn('Failed to load maps list:', e);
    }

    // Load initial map
    await loadMap(currentMapName);
  });
</script>

{#if error}
  <div class="error">
    <h1>Error loading map</h1>
    <p>{error}</p>
  </div>
{:else if config}
  <MapViewer
    {config}
    basePath={`${currentGameBaseUrl}/${currentMapName}`}
    gameBaseUrl={currentGameBaseUrl}
    {availableGames}
    {currentGameName}
    onGameChange={handleGameChange}
    {availableMaps}
    {currentMapName}
    onMapChange={loadMap}
  />
{:else}
  <div class="loading">
    <p>Loading map...</p>
  </div>
{/if}

<style>
  .error, .loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    color: #888;
    font-family: system-ui, sans-serif;
  }

  .error {
    color: #c44;
  }
</style>
