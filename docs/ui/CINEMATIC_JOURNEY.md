# The image stays. The story changes.

## Experience audit and design decisions

The earlier frontend restarts on each route, repeats rounded cards and separates imagery from
recorded descriptions. Its How page explains a process but does not carry a visitor through one.

Apple's actual homepage was inspected in a desktop browser: large central imagery, restrained
copy and alternating visual scale. Lando Norris was also inspected: the initial capture hit its
lime loading screen; a later rendered inspection is required before claiming more of its motion.
Made with Clay and Watermelon UI were inspected during the preceding refinement. No reference
assets, branding, proprietary fonts or layout templates are copied. Figma is intentionally not
retried: its documented plan limit remains a blocker. These changes are unsynced.

The flagship is one continuous document, not five cards or pages. One sticky image persists
beside five editorial scenes. Scrolling chooses the active scene; native links provide keyboard
navigation and deep links. No text is hidden pending animation, no scroll is intercepted, and
no loading interstitial is added. The visual changes carry meaning: framing → position grid →
recorded description → independent reference cells → conclusion. Motion only embellishes the
same complete static story. No animation library, WebGL or additional runtime dependency.

| Scene      | Visual and interaction                                                       | Evidence contract                                                                                                  |
| ---------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Discover   | Large aerial image, direct question, begin link                              | Actual API chip; source and date visible                                                                           |
| Explore    | Same image, optional full-image expansion and nine-cell grid                 | Position vocabulary, not detections                                                                                |
| Describe   | Same image, adjacent complete recorded caption if verified                   | No evaluated caption means no invented caption; explicit path to recorded synthetic illustration                   |
| Verify     | Toggle reference areas, choose reference entry, read equivalent spatial text | Frozen references for a recording, current references for a gallery preview; outcomes come only from recorded rows |
| Understand | Still image and concise conclusion; continue to Case or full Run             | Correctness/coverage separate; scorer and denominators remain recorded, not recomputed in UI                       |

Synthetic input imagery and a scripted caption provider are tracked separately; the image source alone does not establish that no vision model ran.

The actual gallery input has zero evaluated model captions in this offline demo. A separate
recording route can demonstrate the scorer on a genuine saved synthetic Run and its actual
Pillow fixture. Before displaying a recording against an image, compare the served bytes'
SHA256 with recorded provenance. Missing hashes or mismatches do not qualify as a verified pair.
Bounded recording discovery must not claim an exhaustive search of a larger store.

Scene links update the URL without remounting the image. Passive scrolling replaces the current
scene URL; deliberate scene links create normal history entries. Back/Forward, direct scene URLs
and route exit work normally. Narration stops on scene changes and route exit; it never restarts
automatically. The current scene alone supplies the guided narration summary.

A native dialog expands imagery with browser-managed focus, Escape and return focus. Reference
cells are coarse named areas, never precise segmentation. User toggles remain authoritative.

Gallery filters and return position persist in memory. A small progressive native view transition
can carry the selected image into a Case; reduced motion and unsupported browsers use immediate
navigation. Case/Run pages gain contextual story links. Experiment/dataset/tool treatments become
more editorial rather than uniform rounded-card grids; technical views and report contracts stay.

## Acceptance checks

End-to-end five-scene route; verified scripted Run to report; reference-only and unavailable image
states; missing/mismatched provenance; stale navigation; gallery filters and Back/Forward; direct
scene links; keyboard links, dialog and overlays; mobile/tablet/desktop; reduced motion; narration
cancellation; escaping; existing tests; axe, overflow, runtime errors; image/network size and timing
observations. Actual screenshots and optional recording must exist before claiming capture success.
