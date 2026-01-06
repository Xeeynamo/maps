#!/usr/bin/env python3
"""
Copy PNG files from game data and generate LODs

Usage:
    python tools/generate.py /path/to/game/data
    python tools/generate.py /path/to/game/data --map 1300-JUNOA
    python tools/generate.py /path/to/game/data --maps-dir public/maps
"""

import sys
import json
import argparse
import shutil
from pathlib import Path
from PIL import Image
import numpy as np
import re
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing


def get_map_names(maps_dir: Path) -> list[str]:
    """Read map names from config.json"""
    config_path = maps_dir / 'config.json'
    with open(config_path) as f:
        config = json.load(f)
    return config.get('maps', [])


def find_source_pngs(base_path: Path, map_name: str) -> list[Path]:
    """Find all source PNGs for a map"""
    pattern = f"U_Map_{map_name}_*.png"
    # Search recursively
    return list(base_path.rglob(pattern))


def copy_highest_lod(source_files: list[Path], dest_dir: Path) -> list[Path]:
    """Copy only highest quality LOD files to destination"""
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Filter for highest LOD (no "Lod" in name) and exclude Background files
    highest_lod_files = [
        f for f in source_files
        if 'Lod' not in f.name and '_Background_' not in f.name
    ]

    copied = []
    for src in highest_lod_files:
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        copied.append(dest)
    return copied


def transform_alpha_image(img: Image.Image) -> Image.Image:
    """Transform alpha channel: 0->0, 1-254->255

    Returns a new image with transformed alpha.
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # Split into channels
    r, g, b, a = img.split()

    # Transform alpha: 0 stays 0, anything else becomes 255
    a = a.point(lambda x: 0 if x == 0 else 255)

    # Merge back
    return Image.merge('RGBA', (r, g, b, a))


def cleanup_source_tiles(map_dir: Path, map_name: str):
    """Remove copied U_Map_ source files after macro image is generated"""
    pattern = f"U_Map_{map_name}_*.png"
    for f in map_dir.glob(pattern):
        f.unlink()


def find_tile(map_dir: Path, map_name: str, layer: int, split: int) -> Path | None:
    """Find a tile file for given layer and split index"""
    # Try pattern without Lod suffix (highest quality)
    pattern = f"U_Map_{map_name}_Billboard_Layer{layer}_Split{split}.png"
    tile_path = map_dir / pattern
    if tile_path.exists():
        return tile_path
    return None


def parse_tile_info(files: list[Path]) -> tuple[int, int, dict[int, set[int]]]:
    """Parse files to determine max layer, max split, and which layer/split combinations exist

    Returns: (max_layer, max_split, layer_splits_dict)
    """
    pattern = re.compile(r'Layer(\d+).*Split(\d+)\.png$')

    max_layer = -1
    max_split = -1
    layer_splits: dict[int, set[int]] = {}

    for f in files:
        match = pattern.search(f.name)
        if match:
            layer = int(match.group(1))
            split = int(match.group(2))
            max_layer = max(max_layer, layer)
            max_split = max(max_split, split)

            if layer not in layer_splits:
                layer_splits[layer] = set()
            layer_splits[layer].add(split)

    return max_layer, max_split, layer_splits


def generate_macro_image(map_dir: Path, map_name: str, tile_size: int = 2048, output_suffix: str = "_Full") -> Path | None:
    """Merge all layers and splits into a single full image"""
    # Find all Billboard Layer/Split files (highest LOD only - no "Lod" in name)
    files = [f for f in map_dir.glob(f"U_Map_{map_name}_Billboard_Layer*_Split*.png")
             if 'Lod' not in f.name]

    if not files:
        return None

    # Parse to determine dimensions
    max_layer, max_split, layer_splits = parse_tile_info(files)

    if max_split < 0:
        return None

    # Calculate grid size (splits are y*grid + x)
    grid_size = int(math.sqrt(max_split + 1))

    # Detect actual tile size from first file
    first_tile = Image.open(files[0])
    actual_tile_size = first_tile.size[0]  # Assume square tiles
    first_tile.close()

    full_size = grid_size * actual_tile_size

    # Create full image (composite all layers)
    full_img = Image.new('RGBA', (full_size, full_size), (0, 0, 0, 0))

    # Layer 0 first, then overlay higher layers
    for layer in range(max_layer + 1):
        if layer not in layer_splits:
            continue

        for split in layer_splits[layer]:
            x = (split % grid_size) * actual_tile_size
            y = (split // grid_size) * actual_tile_size

            tile_path = find_tile(map_dir, map_name, layer, split)
            if tile_path and tile_path.exists():
                tile = Image.open(tile_path)
                # Convert to RGBA if needed for alpha compositing
                if tile.mode != 'RGBA':
                    tile = tile.convert('RGBA')
                full_img.paste(tile, (x, y), tile)  # Use alpha for compositing
                tile.close()

    output_path = map_dir / f"{map_name}{output_suffix}.png"
    full_img.save(output_path, 'PNG')
    return output_path


def regenerate_lods(full_image_path: Path, full_alpha_image_path: Path, output_dir: Path, tile_size: int = 256) -> list[dict]:
    """Generate LOD pyramid with 256x256 tiles

    Creates two variants for each tile:
    - split_N.png: From full_image_path (original alpha)
    - split_Na.png: From full_alpha_image_path (transformed alpha)
    """
    full_img = Image.open(full_image_path)
    full_img_alpha = Image.open(full_alpha_image_path)
    original_size = full_img.size[0]  # Assume square
    current_size = original_size

    lods = []
    lod_level = 0

    while current_size >= tile_size:
        # Resize if not first level
        if lod_level > 0:
            img = full_img.resize((current_size, current_size), Image.Resampling.LANCZOS)
            img_alpha = full_img_alpha.resize((current_size, current_size), Image.Resampling.LANCZOS)
        else:
            img = full_img.copy()
            img_alpha = full_img_alpha.copy()

        # Create LOD directory
        lod_dir = output_dir / str(lod_level)
        lod_dir.mkdir(parents=True, exist_ok=True)

        # Split into tiles
        grid_size = current_size // tile_size
        for y in range(grid_size):
            for x in range(grid_size):
                left = x * tile_size
                top = y * tile_size

                split_index = y * grid_size + x

                # Save original alpha revealAlpha (from full_img)
                tile = img.crop((left, top, left + tile_size, top + tile_size))
                tile_path = lod_dir / f"split_{split_index}.png"
                tile.save(tile_path, 'PNG')

                # Save transformed alpha revealAlpha (from full_img_alpha)
                tile_alpha = img_alpha.crop((left, top, left + tile_size, top + tile_size))
                tile_alpha_path = lod_dir / f"split_{split_index}a.png"
                tile_alpha.save(tile_alpha_path, 'PNG')

        # Pattern without extension - server will choose optimal format
        lods.append({
            'level': lod_level,
            'gridSize': grid_size,
            'pattern': f"{lod_level}/split_{{index}}",
            'imageSize': tile_size
        })

        lod_level += 1
        # Halve for next iteration
        current_size = current_size // 2

    return lods


def update_config(map_dir: Path, map_name: str, lods: list[dict], tile_size: int):
    """Update config.json with new LOD structure, preserving overlays if they exist"""
    config_path = map_dir / 'config.json'

    # Try to load existing config to preserve overlays
    existing_config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing_config = json.load(f)
        except json.JSONDecodeError:
            pass

    config = {
        'name': map_name,
        'tileSize': tile_size,
        'lods': lods
    }

    # Preserve overlays from existing config
    if 'overlays' in existing_config:
        config['overlays'] = existing_config['overlays']

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


def premultiply_alpha(img: Image.Image) -> Image.Image:
    """Pre-multiply RGB channels by alpha for better lossy compression.

    Pre-multiplied alpha: R' = R * A/255, G' = G * A/255, B' = B * A/255
    This allows lossy compression without visible edge artifacts.
    """
    if img.mode != 'RGBA':
        return img

    # Convert to numpy array for fast processing
    arr = np.array(img, dtype=np.float32)

    # Extract channels
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3:4] / 255.0

    # Pre-multiply RGB by alpha
    rgb_premult = (rgb * alpha).astype(np.uint8)

    # Recombine with original alpha
    result = np.concatenate([rgb_premult, arr[:, :, 3:4].astype(np.uint8)], axis=2)

    return Image.fromarray(result, 'RGBA')


def generate_webp(png_dir: Path):
    """Generate WebP versions of all PNGs with pre-multiplied alpha for lossy compression."""
    for png_path in png_dir.rglob('*.png'):
        webp_path = png_path.with_suffix('.webp')
        img = Image.open(png_path)

        # Pre-multiply alpha for better lossy compression
        if img.mode == 'RGBA':
            img = premultiply_alpha(img)

        # Use lossy WebP with pre-multiplied alpha
        img.save(webp_path, 'WEBP', quality=90)
        img.close()


def process_map(args: tuple[Path, Path, str]) -> str:
    """Process a single map through all steps. Returns status message."""
    base_path, maps_dir, map_name = args
    map_dir = maps_dir / map_name

    try:
        # Step 2: Find source files
        source_files = find_source_pngs(base_path, map_name)
        if not source_files:
            return f"{map_name}: No source files found"

        # Step 3: Copy highest LOD
        copied = copy_highest_lod(source_files, map_dir)

        # Step 5: Generate macro image from original source files
        full_path = generate_macro_image(map_dir, map_name)
        if not full_path:
            return f"{map_name}: Failed to generate macro image"

        # Step 5b: Transform alpha on each source file (in-place)
        for f in copied:
            img = Image.open(f)
            transformed = transform_alpha_image(img)
            transformed.save(f, 'PNG')
            img.close()

        # Step 5c: Generate alpha-transformed macro image from transformed source files
        full_alpha_path = generate_macro_image(map_dir, map_name, output_suffix="_FullA")
        if not full_alpha_path:
            return f"{map_name}: Failed to generate alpha macro image"

        # Step 5d: Cleanup source tiles
        cleanup_source_tiles(map_dir, map_name)

        # Step 6: Regenerate LODs (from both full images)
        lods = regenerate_lods(full_path, full_alpha_path, map_dir)

        # Step 7: Update config
        update_config(map_dir, map_name, lods, 256)

        # Step 8: Generate WebP
        generate_webp(map_dir)

        return f"{map_name}: OK ({len(copied)} files, {len(lods)} LODs)"

    except Exception as e:
        return f"{map_name}: ERROR - {e}"


def main():
    parser = argparse.ArgumentParser(description='Generate map tiles from game data')
    parser.add_argument('source', help='Source directory containing game data')
    parser.add_argument('--maps-dir', default='public/maps', help='Output maps directory')
    parser.add_argument('--map', help='Process only this specific map')
    parser.add_argument('--workers', type=int, default=None, help='Number of parallel workers (default: CPU count)')
    args = parser.parse_args()

    base_path = Path(args.source)
    maps_dir = Path(args.maps_dir)

    if not base_path.exists():
        print(f"Error: Source directory not found: {base_path}")
        sys.exit(1)

    if not maps_dir.exists():
        print(f"Error: Maps directory not found: {maps_dir}")
        sys.exit(1)

    if args.map:
        result = process_map((base_path, maps_dir, args.map))
        print(result)
    else:
        # Step 1: Get map names
        map_names = get_map_names(maps_dir)
        print(f"Found {len(map_names)} maps")

        # Determine number of workers
        num_workers = args.workers or multiprocessing.cpu_count()
        print(f"Processing with {num_workers} workers...")

        # Prepare arguments for parallel processing
        map_args = [(base_path, maps_dir, name) for name in map_names]

        # Process maps in parallel
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(process_map, arg): arg[2] for arg in map_args}

            for future in as_completed(futures):
                result = future.result()
                print(result)

        print("\nDone!")


if __name__ == "__main__":
    main()
