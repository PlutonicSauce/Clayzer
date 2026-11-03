# MCP Servers

The hackathon docs name only one MCP server: **RODA**. Everything else is "Clay's ~99 MCP servers", and Clay will share a free/priority shortlist at kickoff. Clay has not published that catalog. The servers below are my best guesses at what it contains. They come from the public [sparkgeo/geo-mcp-servers](https://github.com/sparkgeo/geo-mcp-servers) catalog (114 geospatial servers), filtered to ones that are free and match the tasks (NAIP, STAC, Source Cooperative, LGND embeddings).

## Named in the docs

### RODA: Registry of Open Data on AWS
Searches, previews, and samples AWS open datasets (NAIP and others). It can also find datasets that have STAC endpoints. Free; no AWS account needed for open buckets. For Requester-Pays data it only returns access instructions, so it can't preview or sample NAIP.
- Source: [awslabs/mcp: roda-mcp-server](https://github.com/awslabs/mcp/tree/main/src/roda-mcp-server) · [blog](https://aws.amazon.com/blogs/opensource/introducing-mcp-server-for-registry-of-open-data-on-aws/)
- Run: `uvx awslabs.roda-mcp-server@latest`

## Likely candidates (free, no key)

### Source Cooperative
Browses and searches Source Cooperative (800 TB+ of public geospatial data; [LGND embeddings](https://source.coop/clay/lgnd-embeddings) are hosted there). Lists organizations, products, and files, and returns file metadata. MIT; no auth.
- Source: [yharby/source-coop-mcp](https://github.com/yharby/source-coop-mcp)
- Run: `uvx source-coop-mcp`

### STAC
A generic STAC API client. Searches collections and items by bbox, datetime, and query, and estimates data size. Can sign Planetary Computer assets. No auth.
- Source: [wayfinder-foundry/stac-mcp](https://github.com/BnJam/stac-mcp)
- Run: `uvx --from git+https://github.com/wayfinder-foundry/stac-mcp stac-mcp`

### GDAL
Raster and vector processing on local files: info, convert, reproject, stats, clip, buffer, query. Set `GDAL_MCP_WORKSPACES` to limit which paths it can touch. MIT; no auth.
- Source: [JordanGunn/gdal-mcp](https://github.com/JordanGunn/gdal-mcp)
- Run: `uvx --from gdal-mcp gdal --transport stdio`

### NASA Earthdata (hosted)
Searches the NASA CMR catalog: collections, granules, services, variables, and citations. The MCP needs no login. Downloading data needs an Earthdata Login account (via `earthaccess`).
- Source: [nasa/earthdata-mcp](https://github.com/nasa/earthdata-mcp)
- URL: `https://cmr.earthdata.nasa.gov/mcp/v1` (streamable HTTP)

### Planetary Computer
Downloads Microsoft Planetary Computer rasters (Sentinel, DEM, land cover) and vectors (building footprints) by place name or bbox. Apache-2.0. Not on PyPI; clone the repo and run it locally.
- Source: [isaaccorley/planetary-computer-mcp](https://github.com/isaaccorley/planetary-computer-mcp)
- Run: `uv sync && uv run python -m planetary_computer_mcp.server`

## Needs an account or key

### LGND Geo (hosted, free): probably the "Legend" partner
Search, explore, classify, and check places using the LGND/Clay embeddings: Sentinel-2 globally (10 m, monthly, 2017 to April 2026) and NAIP across the contiguous US (sub-meter, annual, 2020 to 2023). Uses OAuth, not an API key. The first time you connect, your MCP client opens a browser window where you create an account in one click. The free **Explorer** tier allows 150 tool calls a day and open imagery only.
- Info: [lgnd.ai/resources/lgnd-geo](https://lgnd.ai/resources/lgnd-geo) · [pricing](https://lgnd.ai/pricing)
- Add: `claude mcp add --transport http lgnd-geo https://geo.lgnd.ai/mcp`, then run `/mcp` → `lgnd-geo` → Authenticate.

### LGND Developer MCP (hosted, paid)
The fuller embeddings API: text, location, and chip-similarity search, change detection, and classification. Needs a **Pro** account (contact sales@lgnd.ai). Academics can apply for the free Research tier. The API key (`sk_live_…`) comes from the [developer portal](https://geo.lgnd.ai/portal).
- Source: [EarthLegend/developer_resources/mcp](https://github.com/EarthLegend/developer_resources/tree/main/mcp)
- Add: `claude mcp add --transport http lgnd https://earth.lgnd.ai/mcp --header "Authorization: Bearer sk_live_<key>"`

### AWS Geospatial Power Pack (Kiro)
An AWS sample: 19 geospatial MCP servers (STAC, OSM, terrain, raster, H3, foundation models, embedding search, AWS compute) packaged as a Kiro "Power". It fits the event's Kiro IDE. You install it from the repo, not uvx. The core servers need no keys.
- Source: [aws-samples/sample-geospatial-kiro-power-pack](https://github.com/aws-samples/sample-geospatial-kiro-power-pack)

## Setup

`.mcp.json` in this folder registers the free servers for Claude Code. For Kiro, copy the same `mcpServers` block into `.kiro/settings/mcp.json`, and use the absolute path to `uvx` (`which uvx`) to avoid `spawn uvx ENOENT`.

## Ask Clay at kickoff
- The free/priority shortlist from their ~99 servers, and whether it is the sparkgeo list.
- Whether teams get LGND Pro (Developer MCP) access, or should use the free LGND Geo.
- How to handle NAIP Requester-Pays (RODA can't sample it).
