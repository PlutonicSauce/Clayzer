// The wind-farm Chip the problem slide shows the records disagreeing on (problem-slide.js): Case
// fixed-dev-uswtdb-3073564.
//
// Turbine positions are Chip pixels (512 x 512, from Chip.pixel), fetched 2026-11-04 from the USGS
// USWTDB API and OpenStreetMap's power=generator nodes. The two agree on 17 turbines to within a
// few pixels. They disagree on one at the top edge: USGS puts it at y = -1, just outside the Chip,
// and OSM at y = 2, just inside, about 2 m apart.

export const CHIP = "/api/chips/ca-uswtdb-3073564-20220702.png";

// The 17 turbines both records place inside the Chip (USGS positions), and the one they disagree on.
export const AGREED = [[98, 282], [237, 92], [354, 315], [2, 39], [277, 414], [471, 159], [167, 187],
  [431, 207], [312, 363], [393, 264], [132, 233], [281, 46], [238, 465], [57, 326], [203, 143],
  [509, 116], [25, 377]];
export const DISPUTED = [316, 2];
