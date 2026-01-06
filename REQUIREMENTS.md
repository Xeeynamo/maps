# Video game map viewer

## Overview

I want to create a map viewer similar to how Google Map works. It should work on a browser.

## Technical requirements

It needs to be future-proof and use modern technologies. It needs to be fast, efficient
and portable (so use browser).

## Stage 1: map viewer

The map is a infinite grid that starts at 0,0 . Each grid element is a square tile.

The map is a grid of tiles that get loaded only when they are required to be on screen.

Each tile has a LOD (Level of Detail). A LOD of 0 means the highest possible quality,
LOD 1 is half quality, LOD 2 a quarter of quality, and so on.

The righr LOD is selected based on the map zoom and canvas pixel density. For example
if the LOD 0 is a 2048x2048 PNG image, it should be loaded if at least 1536x1536 needs
to be visible on screen. If less than that, then select the LOD 1 of 1024x1024 size.

If a higher LOD is not available, load the previous available LOD and stretch it. For
example, if the LOD 0 at 2048x2048 is not available, then load the LOD 1 at 1024x1024
and stretch it.

All images of a given LOD are guaranteed to have the same resolution.

Some games use different LOD systems. For example GAME-A has 16 2048x2048 images
as LOD 0, then 4 2048x2048 images at LOD 1 and only 1 image at LOD 2.
GAME-B has 16 1024x1024 images at LOD 0, 16 512x512 images at LOD 1, 16 256x256
images at LOD 2. I want both combinations to work interchangeably.

As the map is infinite, have a debug option enabled by default where if a tile
is missing, draw instead a dummy tile with information such as coordinate and LOD.

Allow to zoom and move the map with gestures, mouse wheel and keyboard. Zooming
will of course change the LOD level.

Use `assets/1300-JUNOA` as a reference for a map to render.

## Stage 2: locations

Allow to have a simple JSON file to describe overlays. An overlay has the following info:

* Coordinate X, Y
* Name
* Image path

This will allow to optionally show on the map the location of various important locations,
a bit like what Google Maps does with the different locations.

