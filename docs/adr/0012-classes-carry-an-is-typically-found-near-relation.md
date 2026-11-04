# Classes carry an "is typically found near" relation

The ontology had one relation between classes — is-a (a greenhouse is a kind of building). A
customer asked whether it could also express that two classes **tend to occur together in space**:
a parking lot is typically found near a building. That is a different kind of relation (an
association, not a taxonomy), and Noy & McGuinness explicitly list "relationships to other
individuals" as a slot a class can carry alongside its hierarchy. So we add it.

Each class may list a `near` field in `ontology/objects.toml`: other class ids it is **typically
found near**, a **directed** relation as authored (`parking_lot` near `building`; we don't
auto-add the reverse). It is validated like `confusers` — every target must be a known class, and
a class may not be near itself. It is separate from `parent`: `near` never changes the is-a tree,
grounding's partial-credit `distance`, or which classes are claimable or keyed.

## What it's for

- **The captioner (relationality, CAP-01).** `ontology.prompt_context` adds a "typical spatial
  neighbours" line for the classes in focus, so the writer knows, e.g., parking lots sit by
  buildings. It is framed as a **world prior, not a claim**: the line says to state a relation
  only if it is visible in the image. Verify-then-write and grounding's relation precision catch
  a relation asserted from the prior but not present, so the prior can help phrasing without
  licensing unsupported claims (ADR-0006 still holds — `near` is general knowledge, never a Case's
  Answer Key).
- **The Ontology explainer UI.** The class graph draws `near` as dashed amber arrows (distinct
  from the solid is-a arrows), with a toggle and a per-class "typically found near" list.
- **Served data.** `GET /api/ontology` returns `near` per class.

## Alternatives and future work

Hand-authored for now, a small set of well-justified pairs. The same relation is what Layer B's
co-occurrence statistics (ADR-0010) and the induction agent (ADR-0011, N&M step 5) can learn from
data later — measured neighbours would then populate or cross-check `near`, exactly as
`learned_confusers` do for look-alikes. We kept it directed and un-weighted to stay simple; a
weight or a symmetric form can be added if a use needs it.
