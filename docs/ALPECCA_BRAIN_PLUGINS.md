# Alpecca Brain Graph Plugins

Status: CURRENT - implemented 2026-07-15

House HQ exposes the live graph at `/house-hq?system=internals`. The protected
JSON source is `GET /brain/graph`.

## Accuracy Contract

- A node is `healthy` only when its allowlisted probe has positive evidence.
- Missing evidence is `unknown`, never assumed healthy.
- Implemented foundations with open soak or integration gates are `degraded`
  or `unfinished`, not complete.
- Every snapshot includes `observedAt`, evidence labels, plugin validation
  errors, and aggregate state counts.
- The graph describes operational evidence. It does not claim consciousness,
  AGI, or seven independent transformer processes.

## Plugin Discovery

Built-in manifests live in `alpecca/brain_plugins/*.json`. Creator-local
manifests may be placed in `data/brain_plugins/*.json`; that directory is
runtime data and is not a source-code execution surface.

```json
{
  "schemaVersion": 1,
  "id": "creator-hardware",
  "name": "Creator Hardware",
  "nodes": [
    {
      "id": "runtime",
      "label": "Runtime",
      "parent": null,
      "probe": "server",
      "system": "runtime",
      "group": "Infrastructure",
      "detail": "Authoritative local runtime status."
    }
  ]
}
```

Manifests cannot import Python, execute commands, provide expressions, or call
URLs. `probe` must name an allowlisted probe in `alpecca/brain_graph.py`.
Invalid plugins are rejected and reported in the graph without breaking valid
plugins.

## Visual Contract

The central node represents the single authoritative Alpecca runtime. Major
systems branch symmetrically around it, with the central disk and petal ring
inspired by a sunflower and the paired branches inspired by wings. Subsystems
are collapsed by default, expansion state survives live refresh, and mobile
uses a single-column hierarchy without horizontal overflow.

State colors are intentionally distinct:

- Green: healthy
- Coral: degraded / needs attention
- Gold: unfinished
- Gray: disabled
- Lavender: unknown

The roadmap children use the July 15 verified gate matrix: P0, P2, P3, P4,
and P5 have met their bounded phase gates; P1, P6, P8, P9, P10, P11, and P12
remain operationally partial; P7, P13, and P14 expose blocked gates. A blocked
node is still rendered as unfinished, with its blocking prerequisite stated in
the detail panel. Baseline completion does not imply unrestricted autonomy or
literal consciousness.

## Adding Probes

Adding a new probe is a source change and requires tests. A probe must be
read-only, bounded, content-safe, and return concrete evidence. Network probes
need short timeouts. A manifest alone cannot create a new probe.
