# Changelog

Changes are grouped by local build/commit. Dates are local project dates. Entries describe implemented work and material limitations; a local commit is not a public release.

## Unreleased — 2026-11-03

- Added cross-spectral propagation for multiple correlated sources and receivers, with Hermitian/positive-semidefinite validation and a CLI. An explicit-path adapter uses the existing room solution; it does not include the diffuse statistical tail or calibrated absolute SPL.
- Corrected the equation sheet's IACC, source directivity, air attenuation, specular-scattering and cross-spectral convention descriptions.
- Added equation and integration checks under `tests` and a small independent stereo source-spectrum example.

## Local build b7e0b66 — 2026-11-03

- Expanded Room Studio with editable geometry, materials, source/listener controls, decay chart, drag and keyboard interaction, room export, and reconstructable instruction export. Rectangular geometry only.

## Local build 092e434 — 2026-11-03

- Added an experimental supervised instrument reference matcher and CLI training/identification. Real-world accuracy and full-song identification remain unvalidated.

## Local build bfc8387 — 2026-11-03

- Added optional atmospheric attenuation and ideal source/receiver directionality on explicit paths, ideal resonator modes, a frequency trace, room editor, and expanded Frankenjack controls with equation and offline checks.

## Baseline 9cabc1e — 2026-11-02

- Consolidated the experimental room engine, configurable lab, math and documentation baseline. See Git history for earlier work.
