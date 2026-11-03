# Earnest: auditory cognition research roadmap

Earnest aims to help an agent listen to sound, explain its observations, reason about competing interpretations, and improve from human feedback. The research joins acoustics, hearing, audio engineering, machine learning and the experience of musicians and listeners. A confident description alone is not evidence that a sound has been understood.

## Research loop

1. Capture or import source and processed audio with known settings and a dry reference. Keep provenance, level, routing and alignment alongside each pair.
2. Measure features, compare listening judgments, and formulate hypotheses about what changed.
3. Predict or render a candidate, evaluate against held-out audio and measurements, and record disagreement and uncertainty.
4. Use level-matched, blinded listening, including the developer as an initial expert case and additional listeners as the study matures.

## Connected components

- **Analysis and measurement:** recover what can be inferred from reference recordings, impulse responses and controlled comparisons. A mixed recording does not uniquely determine a room or plugin internals.
- **Room creation and solving:** edit geometry, surfaces, sources and listener positions; estimate reflections and decay; produce a room representation for rendering.
- **Live engine and virtual device:** route applications through Earnest and provide direct, wet, center, spatial and output controls. The current VM device is experimental and stereo; shared-mode output does not enforce exclusive routing.
- **Listening and language:** build an A/B comparison workflow and link listener descriptions to measurements without treating preferences as physical ground truth.
- **Model training:** develop paired datasets and learned models for instruments and effects, with held-out evaluation. Dataset preparation is not model training.
- **Visualization:** show measurements and room-model estimates, with a live head view where available. Decorative displays and stereo energy do not establish spatial direction.
- **Agent integration:** expose explicit analysis and control interfaces so an agent can inspect evidence, propose actions, report uncertainty and learn from user feedback.
- **Accessibility research:** investigate descriptions of sound and direction with deaf and hard-of-hearing collaborators; safety-critical detection requires separate validation.

## First research milestone: the Univerb study

Compare known dry and processed material, control latency and loudness, and use multiple settings and held-out examples. Measure decay, spectral balance, stereo correlation and direct-to-reverberant behavior where the source supports those estimates. Compare Earnest with the reference by blind listening and report successes, differences and failure cases. Listening indistinguishability has not been demonstrated.

## Current evidence and limitations

The VM user reported that the virtual route produced audible room processing. This is an individual observation, not a controlled equivalence result. Driver format handling, reliability, buffering, hot controls and surround remain in development. The current main application, advanced Frankenjack bridge, visualizer and VM installer are experimental and have distinct capabilities. Training a general audio model and human-level auditory reasoning remain research goals.

The original planning snapshot is a private Claude artifact; this document reconstructs the noncommercial technical goals from the local ideas index and current project discussion. Component names from that snapshot were provisional.
