"""Residual pursuit for an aligned dry signal and discrete delayed copies."""
from __future__ import annotations

import math
import numpy as np
from scipy.signal import correlate
from .comparison import compare_audio


def pursue_echoes(observed, dry, sample_rate_hz, *, max_delay_samples, max_layers=8,
                  min_improvement=1e-6, layer_penalty=0.0):
    """Greedy least-squares pursuit; each layer is one shared-gain delay.

    Penalty and improvement are fractions of original observed energy. Delay
    zero is a candidate, not an assumed direct path; all delays compete.
    """
    compare_audio(observed, dry, sample_rate_hz)
    y, x = np.asarray(observed, dtype=np.float64), np.asarray(dry, dtype=np.float64)
    if y.ndim == 1: y = y[:, None]
    if x.ndim == 1: x = x[:, None]
    n = len(y)
    if isinstance(max_delay_samples, bool) or not isinstance(max_delay_samples, int) or not 0 <= max_delay_samples < n:
        raise ValueError('max_delay_samples must be an integer from 0 to frame_count - 1')
    if isinstance(max_layers, bool) or not isinstance(max_layers, int) or not 1 <= max_layers <= 128:
        raise ValueError('max_layers must be an integer from 1 to 128')
    for name, value in [('min_improvement', min_improvement), ('layer_penalty', layer_penalty)]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(name + ' must be finite and nonnegative')
    input_energy = float(np.sum(y*y))
    dry_energy = float(np.sum(x*x))
    if dry_energy == 0: raise ValueError('dry signal must have nonzero energy')
    residual = y.copy()
    # For delay d, denominator includes only x[:n-d], as the tail is truncated.
    prefix = np.concatenate(([0.0], np.cumsum(np.sum(x*x, axis=1))))
    den = prefix[n - np.arange(max_delay_samples + 1)]
    available = den > dry_energy * 1e-12
    layers = []
    if input_energy:
        for _ in range(max_layers):
            corr = sum(correlate(residual[:, c], x[:, c], mode='full', method='fft')[n-1:n+max_delay_samples]
                       for c in range(x.shape[1]))
            improvement = np.zeros(max_delay_samples+1)
            improvement[available] = corr[available] ** 2 / den[available]
            delay = int(np.argmax(improvement))
            relative = float(improvement[delay] / input_energy)
            if relative <= max(min_improvement, layer_penalty): break
            gain = float(corr[delay] / den[delay])
            residual[delay:] -= gain * x[:n-delay]
            layers.append({'family': 'delay', 'delay_samples': delay, 'delay_seconds': delay/sample_rate_hz,
                           'gain': gain, 'relative_energy_improvement': relative,
                           'relative_energy_after': float(np.sum(residual*residual) / input_energy),
                           'penalized_improvement': relative - layer_penalty})
    predicted = y-residual
    comparison, _ = compare_audio(y, predicted, sample_rate_hz)
    dry_comparison, _ = compare_audio(x, predicted, sample_rate_hz)
    report = {'schema': 'earnest.effect-pursuit.v1', 'sample_rate_hz': sample_rate_hz,
              'frame_count': n, 'channels': x.shape[1], 'layers': layers,
              'initial_energy': input_energy, 'residual_energy': float(np.sum(residual*residual)),
              'options': {'max_delay_samples': max_delay_samples, 'max_layers': max_layers,
                          'min_improvement': min_improvement, 'layer_penalty': layer_penalty},
              'conditioning': [], 'final_comparison': comparison, 'prediction_vs_dry': dry_comparison,
              'limits': ['Only integer-sample delayed copies of a known aligned dry signal are modeled.',
                         'One gain is shared across channels; candidates compete greedily and earlier gains are not jointly refit.',
                         'A selected delay is a mathematical fit, not proof of a physical echo or an ordered effects chain.',
                         'No distortion conditioning, reverberation, EQ, modulation, prior or structure score is implemented.',
                         'Prediction-versus-dry includes intentional effects and gain changes; it is not separation accuracy.',
                         'No alignment, input normalization or sample-rate conversion is applied.']}
    return report, predicted, residual
