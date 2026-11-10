# ISEKAI GRAVE — Offline Artwork Pack

This build uses pre-rendered artwork bundled in `assets/world_art/`.

## Runtime behavior

- The bot selects a bundled image by artwork category and sends it with Telegram `send_photo`.
- The image files are shipped with the application, so they are available after Railway restarts and redeploys as long as the deployment includes the repository files.
- No `IMAGE_API_URL`, `IMAGE_API_KEY`, `IMAGE_MODEL`, paid API, GPU, or external image service is required.
- Pillow procedural rendering remains only as a fallback if a bundled asset is missing.
- The selected art is reused; it is not regenerated on every button click.

## Included source assets

| Asset | Used for |
|---|---|
| `market.jpg` | Marketplace, desert, forge |
| `character.jpg` | Character profile, inventory |
| `guild_hall.jpg` | Guild, NPC, chronicle, news, ruins, swamp |
| `floating_island.jpg` | World map, regions, quests, forest, sea, castle, snow |
| `world_boss.jpg` | World boss, arena, volcano |

Some biomes currently share a suitable general fantasy illustration because the project bundle only contains these five approved source illustrations. Add biome-specific files later and update `ART_ASSET_MAP` to give every region a unique visual.

## Deploy

Commit the modified Python files and the complete `assets/world_art/` directory to the repository used by Railway. No new environment variables are needed.
