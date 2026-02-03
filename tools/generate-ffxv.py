#!/usr/bin/env python3
"""
Generate map tiles for FFXV luchil_final map

This version generates LODs directly from source tiles without creating
a massive macro image in memory. Uses multiprocessing for parallelization.

Usage:
    python tools/generate-ffxv.py
    python tools/generate-ffxv.py --maps-dir public/maps
    python tools/generate-ffxv.py --workers 8
"""

import sys
import json
import argparse
from pathlib import Path
from PIL import Image
import re
import os
from multiprocessing import Pool, cpu_count
from functools import partial

# Allow very large images (disable decompression bomb check)
Image.MAX_IMAGE_PIXELS = None


# Source configuration
SOURCE_DIR = Path("/home/xeeynamo/hacking/ffxv/terabelde_final")
MAP_NAME = "ffxv-terabelde"
SOURCE_TILE_SIZE = 1024  # Source tile size
OUTPUT_TILE_SIZE = 256  # LOD tile size
VIRTUAL_SIZE = 65536  # Fixed virtual world size


def parse_source_files(source_dir: Path) -> dict[tuple[int, int], Path]:
    """Parse source files and return dict mapping (x, y) to file path.

    Y coordinate is flipped so that y=0 in filename appears at the bottom
    of the map (high virtual Y) and y=63 appears at the top (low virtual Y).
    """
    pattern = re.compile(r'x(\d+)_y(\d+)_mrgbout\.png$')

    # First pass: find max Y to know how to flip
    max_y = 0
    files = []
    for f in source_dir.glob("*.png"):
        match = pattern.search(f.name)
        if match:
            x = int(match.group(1))
            y = int(match.group(2))
            max_y = max(max_y, y)
            files.append((x, y, f))

    # Second pass: store with flipped Y
    tiles = {}
    for x, y, f in files:
        flipped_y = max_y - y
        tiles[(x, flipped_y)] = f

    print(f"  Max source Y: {max_y}, flipping Y coordinates")
    return tiles


def generate_output_tile(
    tiles: dict[tuple[int, int], Path],
    output_x: int, output_y: int,
    scale: float,
    output_tile_size: int = 256
) -> Image.Image | None:
    """Generate a single output tile by compositing relevant source tiles.

    Args:
        tiles: Dict mapping (source_x, source_y) to file path (Y already flipped)
        output_x, output_y: Output tile position in output grid
        scale: Scale factor (1.0 = full resolution, 0.5 = half, etc.)
        output_tile_size: Size of output tiles (256)

    Returns:
        PIL Image of the output tile, or None if completely empty
    """
    # Calculate what region of the virtual world this output tile covers
    virtual_left = int(output_x * output_tile_size / scale)
    virtual_top = int(output_y * output_tile_size / scale)
    virtual_right = int((output_x + 1) * output_tile_size / scale)
    virtual_bottom = int((output_y + 1) * output_tile_size / scale)

    # Which source tiles overlap this region?
    source_left = virtual_left // SOURCE_TILE_SIZE
    source_top = virtual_top // SOURCE_TILE_SIZE
    source_right = (virtual_right - 1) // SOURCE_TILE_SIZE
    source_bottom = (virtual_bottom - 1) // SOURCE_TILE_SIZE

    # Create temporary canvas at the virtual resolution we need
    canvas_width = virtual_right - virtual_left
    canvas_height = virtual_bottom - virtual_top
    canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))

    has_content = False

    # Composite each overlapping source tile
    for sy in range(source_top, source_bottom + 1):
        for sx in range(source_left, source_right + 1):
            if (sx, sy) not in tiles:
                continue

            has_content = True

            # Load source tile
            src_img = Image.open(tiles[(sx, sy)])
            if src_img.mode != 'RGBA':
                src_img = src_img.convert('RGBA')

            # Source tile position in virtual space
            src_virtual_left = sx * SOURCE_TILE_SIZE
            src_virtual_top = sy * SOURCE_TILE_SIZE

            # Calculate where to paste in canvas
            paste_x = src_virtual_left - virtual_left
            paste_y = src_virtual_top - virtual_top

            canvas.paste(src_img, (paste_x, paste_y))
            src_img.close()

    if not has_content:
        return None

    # Scale down to output tile size
    if canvas.size != (output_tile_size, output_tile_size):
        canvas = canvas.resize((output_tile_size, output_tile_size), Image.Resampling.LANCZOS)

    return canvas


def process_tile(args: tuple) -> tuple[int, bool]:
    """Process a single tile (for multiprocessing).

    Returns (split_index, has_content) tuple.
    """
    tiles, x, y, grid_size, scale, output_tile_size, lod_dir = args
    split_index = y * grid_size + x

    tile_img = generate_output_tile(tiles, x, y, scale, output_tile_size)
    tile_path = lod_dir / f"split_{split_index}.png"

    if tile_img is not None:
        tile_img.save(tile_path, 'PNG')
        tile_img.close()
        return (split_index, True)
    else:
        # Save empty transparent tile
        empty = Image.new('RGBA', (output_tile_size, output_tile_size), (0, 0, 0, 0))
        empty.save(tile_path, 'PNG')
        empty.close()
        return (split_index, False)


def generate_lod(
    tiles: dict[tuple[int, int], Path],
    output_dir: Path,
    lod_level: int,
    scale: float,
    grid_size: int,
    output_tile_size: int,
    num_workers: int
) -> dict:
    """Generate a single LOD level with parallel processing."""
    total_tiles = grid_size * grid_size
    print(f"LOD {lod_level}: scale={scale:.4f}, grid={grid_size}x{grid_size} ({total_tiles} tiles)")

    # Create LOD directory
    lod_dir = output_dir / str(lod_level)
    lod_dir.mkdir(parents=True, exist_ok=True)

    # Prepare work items
    work_items = [
        (tiles, x, y, grid_size, scale, output_tile_size, lod_dir)
        for y in range(grid_size)
        for x in range(grid_size)
    ]

    # Process tiles in parallel
    tiles_generated = 0
    tiles_empty = 0

    with Pool(num_workers) as pool:
        results = pool.map(process_tile, work_items)

    for split_index, has_content in results:
        if has_content:
            tiles_generated += 1
        else:
            tiles_empty += 1

    print(f"  Generated {tiles_generated} tiles, {tiles_empty} empty")

    return {
        'level': lod_level,
        'gridSize': grid_size,
        'pattern': f"{lod_level}/split_{{index}}",
        'imageSize': output_tile_size
    }


def generate_lods(
    tiles: dict[tuple[int, int], Path],
    output_dir: Path,
    output_tile_size: int = 256,
    num_workers: int = None
) -> list[dict]:
    """Generate LOD pyramid directly from source tiles."""
    if num_workers is None:
        num_workers = cpu_count()

    print(f"Virtual world: {VIRTUAL_SIZE}x{VIRTUAL_SIZE}")
    print(f"Using {num_workers} workers")

    lods = []
    lod_level = 0
    current_size = VIRTUAL_SIZE

    while current_size >= output_tile_size:
        scale = current_size / VIRTUAL_SIZE
        grid_size = current_size // output_tile_size

        lod = generate_lod(
            tiles, output_dir, lod_level, scale, grid_size,
            output_tile_size, num_workers
        )
        lods.append(lod)

        lod_level += 1
        current_size = current_size // 2

    return lods


def convert_to_webp(png_path: Path) -> None:
    """Convert a single PNG to WebP."""
    webp_path = png_path.with_suffix('.webp')
    img = Image.open(png_path)
    img.save(webp_path, 'WEBP', quality=90)
    img.close()


def generate_webp(map_dir: Path, num_workers: int = None):
    """Generate WebP versions of all PNGs using parallel processing."""
    if num_workers is None:
        num_workers = cpu_count()

    png_files = list(map_dir.rglob('*.png'))
    total = len(png_files)
    print(f"Converting {total} PNGs to WebP using {num_workers} workers...")

    with Pool(num_workers) as pool:
        pool.map(convert_to_webp, png_files)

    print(f"  Done: {total} WebP files")


def create_config(map_dir: Path, map_name: str, lods: list[dict], tile_size: int):
    """Create config.json for the map"""
    config = {
        'name': map_name,
        'tileSize': tile_size,
        'lods': lods
    }

    config_path = map_dir / 'config.json'
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Created config: {config_path}")


def main():
    parser = argparse.ArgumentParser(description='Generate FFXV luchil map tiles')
    parser.add_argument('--maps-dir', default='public/maps', help='Output maps directory')
    parser.add_argument('--skip-webp', action='store_true', help='Skip WebP generation')
    parser.add_argument('--workers', type=int, default=None, help='Number of parallel workers (default: CPU count)')
    args = parser.parse_args()

    maps_dir = Path(args.maps_dir)
    map_dir = maps_dir / MAP_NAME
    num_workers = args.workers or cpu_count()

    if not SOURCE_DIR.exists():
        print(f"Error: Source directory not found: {SOURCE_DIR}")
        sys.exit(1)

    if not maps_dir.exists():
        print(f"Error: Maps directory not found: {maps_dir}")
        sys.exit(1)

    map_dir.mkdir(parents=True, exist_ok=True)

    print(f"Processing {MAP_NAME} from {SOURCE_DIR}")

    # Parse source tiles (Y coordinate flipped during parsing)
    tiles = parse_source_files(SOURCE_DIR)
    print(f"Found {len(tiles)} source tiles")

    # Generate LODs directly from source tiles
    lods = generate_lods(tiles, map_dir, OUTPUT_TILE_SIZE, num_workers)

    # Create config
    create_config(map_dir, MAP_NAME, lods, OUTPUT_TILE_SIZE)

    # Generate WebP versions
    if not args.skip_webp:
        generate_webp(map_dir, num_workers)
    else:
        print("Skipping WebP generation")

    print(f"\nDone! Created {len(lods)} LOD levels")


if __name__ == "__main__":
    main()
