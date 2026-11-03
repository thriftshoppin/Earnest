"""Energy-time diagnostics for modeled room impulse responses."""
from __future__ import annotations
import math
import numpy as np


def energy_time_metrics(impulse, sample_rate: int, arrival_sample: int) -> dict:
    """Calculate finite-window C50/C80, D50 and center time from a known arrival.

    The caller selects the arrival; no noise subtraction or onset detection is done.
    Undefined clarity ratios are returned as None with their energy terms intact.
    """
    x = np.asarray(impulse, dtype=np.float64)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ValueError('impulse must be finite, nonempty, and one-dimensional')
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError('sample_rate must be a positive integer')
    if isinstance(arrival_sample, bool) or not isinstance(arrival_sample, int) or not 0 <= arrival_sample < len(x):
        raise ValueError('arrival_sample must index the impulse')
    energy = np.square(x[arrival_sample:])
    total = float(energy.sum())
    early50 = float(energy[:math.ceil(.05*sample_rate)].sum())
    early80 = float(energy[:math.ceil(.08*sample_rate)].sum())
    late50, late80 = max(total-early50, 0.0), max(total-early80, 0.0)
    def clarity(early, late):
        return 10 * math.log10(early/late) if early > 0 and late > 0 else None
    return {'c50_db': clarity(early50, late50), 'c80_db': clarity(early80, late80),
            'd50': early50/total if total > 0 else None,
            'center_time_ms': (1000 * float(np.dot(np.arange(len(energy)),energy)) / (sample_rate*total)) if total > 0 else None,
            'early_50_energy': early50, 'late_50_energy': late50,
            'early_80_energy': early80, 'late_80_energy': late80,
            'arrival_sample': arrival_sample, 'window_end_sample': len(x),
            'interpretation': 'Finite modeled impulse response; not a calibrated or noise-corrected measurement.'}
