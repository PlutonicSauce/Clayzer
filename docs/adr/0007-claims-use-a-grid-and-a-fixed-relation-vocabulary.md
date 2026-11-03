# Claims use a 3×3 position grid and a fixed relation vocabulary

A Caption's Claims give position as one cell of a 3×3 grid over the Chip (north-west … centre … south-east) and relations from a fixed set (north_of, south_of, east_of, west_of, adjacent_to, between, inside). We chose this over pixel bounding boxes, which VLMs produce unreliably, and over free text, which grounding cannot check mechanically against USGS points and OSM shapes. The format is the contract between the group that produces Captions and the group that evaluates them, so changing it means changing both sides.
