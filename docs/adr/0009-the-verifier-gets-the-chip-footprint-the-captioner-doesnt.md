# The verifier gets the Chip's footprint; the captioning model doesn't

Verify-then-write checks each drafted Claim against LGND Geo's imagery at the Claim's grid cell, which needs the cell's coordinates, while the Harness so far saw only a Chip's id and image. We chose to have the Harness code, not the captioning model, do the verification: it reads the Chip's own footprint (bbox and date), finds each cell's centre, and calls LGND itself. The model's inputs stay the image alone. This keeps ADR-0006 intact: the footprint describes the image, not what is on the ground, and LGND reads imagery and an image model, never an Answer Key. Letting the model call LGND with coordinates was rejected: in the agentic runs, models given tools often didn't call them, and verification has to happen every time to be measured.

## Consequences

Verification is deterministic and every lookup and check is a `tool` Step (`role: verify`), so the Workflow Score and Trace summaries can count it. Claims LGND doesn't confirm move to `uncertain`; Claims it couldn't check (an LGND failure) stay, marked unverified, so a verifier outage shows up as Environment Faults rather than as emptier Captions. Giving the model coordinates or location tools later would need its own decision, since it changes what the system under test sees.
