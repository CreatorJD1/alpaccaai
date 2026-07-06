# Alpecca VRM Companion Tool Drop

This folder contains local test VRM exports for Jason's VRM/VRoid companion tooling.

Current test file:

`alpecca_vroid_proxy_v0_first_test_20260706.vrm`

Source VRoid project:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\alpecca_vroid_proxy_v0.vroid`

Status:

- First test export only.
- VRM 1.0.
- Full-fidelity export with no reduction applied.
- Not production-ready.
- Do not treat this as the final Alpecca model.

Known current caveats:

- Hair and face still need additional design locking.
- Hoodie is closer but may still need material cleanup.
- Model should be tested in the companion tool for import compatibility, scale, material loading, expression support, and animation behavior.
- Clothing/body integrity must be checked: the base body should remain fully rendered under clothing, with no missing torso or missing limbs if clothing layers are hidden or changed.

Companion import checklist:

1. Load `alpecca_vroid_proxy_v0_first_test_20260706.vrm` as VRM 1.0.
2. Verify adult-scale import and stable floor contact.
3. Verify all materials/textures load.
4. Verify expressions/blend shapes are detectable.
5. Verify idle and simple animation retargeting do not distort the hoodie, hair, legs, or body scale.
6. Capture front, 3/4, side, and back screenshots for design comparison.

Do not treat the compatibility pass as model approval. Continue design edits in the source `.vroid` file.
