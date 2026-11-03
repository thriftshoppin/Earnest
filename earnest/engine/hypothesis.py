"""Evaluate one explicitly supplied reconstruction and note hypothesis."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
from .comparison import compare_audio
from .frequency_trace import trace_frequencies


def read_note_events(path: str) -> dict:
    """Normalize Basic Pitch note CSV or Earnest note-event JSON externally."""
    import json
    file = Path(path)
    if file.suffix.lower() == '.json':
        doc = json.loads(file.read_text(encoding='utf-8-sig'))
        if not isinstance(doc, dict) or doc.get('schema') != 'earnest.note-events.v1':
            raise ValueError('expected earnest.note-events.v1 JSON')
        return doc
    if file.suffix.lower() != '.csv':
        raise ValueError('note events must be Basic Pitch CSV or earnest.note-events.v1 JSON')
    events = []
    with file.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, restkey='_extra')
        if not {'start_time_s', 'end_time_s', 'pitch_midi'}.issubset(reader.fieldnames or []):
            raise ValueError('CSV requires start_time_s, end_time_s and pitch_midi columns')
        for row in reader:
            events.append({'start_s': float(row['start_time_s']), 'end_s': float(row['end_time_s']),
                           'midi_pitch': float(row['pitch_midi']),
                           'velocity': float(row['velocity']) if row.get('velocity') else None})
    return {'schema': 'earnest.note-events.v1', 'events': events,
            'source': str(file.resolve()), 'limits': ['Pitch bends are not interpreted by this normalizer.']}


def evaluate(reference, stems, sample_rate_hz: int, notes: dict | None = None, *,
             max_harmonics: int = 8, tolerance_cents: float = 50.0,
             window_size: int = 4096, hop_size: int = 1024) -> tuple[dict, np.ndarray]:
    """Measure reconstruction and peak support; no inferred source correctness.

    Peak support is a heuristic sum of squared peak amplitudes, not total energy.
    The center of each complete Hann window is used for event activity.
    """
    if not isinstance(stems, (list, tuple)) or not stems:
        raise ValueError('at least one aligned stem is required')
    if isinstance(max_harmonics, bool) or not isinstance(max_harmonics, int) or not 1 <= max_harmonics <= 64:
        raise ValueError('max_harmonics must be an integer from 1 to 64')
    if isinstance(tolerance_cents, bool) or not isinstance(tolerance_cents, (int, float)) or not math.isfinite(tolerance_cents) or not 0 < tolerance_cents <= 600:
        raise ValueError('tolerance_cents must be finite and between 0 and 600')
    ref = np.asarray(reference, dtype=np.float64)
    if ref.ndim == 1: ref = ref[:, None]
    mix = np.zeros_like(ref)
    for stem in stems:
        s = np.asarray(stem, dtype=np.float64)
        if s.ndim == 1: s = s[:, None]
        if s.shape != ref.shape or not np.isfinite(s).all():
            raise ValueError('stems must be finite and have exactly the reference shape')
        mix += s
    comparison, residual = compare_audio(ref, mix, sample_rate_hz)
    total_ref = sum(c['reference_mean_square'] for c in comparison['channels'])
    total_err = sum(c['residual_mean_square'] for c in comparison['channels'])
    reconstruction = {'mean_square_error': total_err / len(comparison['channels']),
                      'relative_error_power': total_err / total_ref if total_ref > 0 else None,
                      'channels': comparison['channels']}
    event_rows = None
    if notes is not None:
        if not isinstance(notes, dict) or notes.get('schema') != 'earnest.note-events.v1' or not isinstance(notes.get('events'), list):
            raise ValueError('notes must use earnest.note-events.v1')
        event_rows = []
        for event in notes['events']:
            try: start, end, pitch = (float(event[k]) for k in ('start_s', 'end_s', 'midi_pitch'))
            except (KeyError, TypeError, ValueError) as exc: raise ValueError('each note needs numeric start_s, end_s, midi_pitch') from exc
            if not all(math.isfinite(x) for x in (start, end, pitch)) or start < 0 or end <= start or not 0 <= pitch <= 127:
                raise ValueError('invalid note timing or MIDI pitch')
            event_rows.append((start, end, pitch))
    spectral = None
    if event_rows is not None:
        trace = trace_frequencies(ref, sample_rate_hz, window_size=window_size, hop_size=hop_size)
        total_peak_power = 0.0; matched_peak_power = 0.0; frames_used = 0
        for frame in trace['frames']:
            if frame['valid_samples'] != window_size: continue
            frames_used += 1
            center = frame['center_s']
            partials = [440.0 * 2 ** ((pitch - 69) / 12) * harmonic
                        for start, end, pitch in event_rows if start <= center < end
                        for harmonic in range(1, max_harmonics + 1)
                        if 440.0 * 2 ** ((pitch - 69) / 12) * harmonic < sample_rate_hz / 2]
            for channel in frame['channels']:
                for peak in channel['peaks']:
                    power = 10 ** (peak['level_dbfs'] / 10)
                    total_peak_power += power
                    if partials and min(abs(1200 * math.log2(peak['hz'] / f)) for f in partials) <= tolerance_cents:
                        matched_peak_power += power
        spectral = {'peak_power_proxy': total_peak_power, 'matched_peak_power_proxy': matched_peak_power,
                    'unexplained_peak_fraction': 1 - matched_peak_power / total_peak_power if total_peak_power else None,
                    'complete_frames': frames_used, 'window_size': window_size, 'hop_size': hop_size,
                    'max_harmonics': max_harmonics, 'tolerance_cents': tolerance_cents}
    return {'schema': 'earnest.hypothesis-evaluation.v1', 'sample_rate_hz': sample_rate_hz,
            'frame_count': len(ref), 'stem_count': len(stems), 'reconstruction': reconstruction,
            'spectral_support': spectral, 'note_count': len(event_rows) if event_rows is not None else None,
            'temporal_mismatch': None, 'combined_score': None,
            'limits': ['Inputs must be time-aligned with matching rate, duration and channel count; no gain adjustment is performed.',
                       'Spectral peak power is a heuristic proxy, not total signal energy or source identification.',
                       'A note is active only at window center; partial frames are excluded and 440 Hz equal temperament is assumed.',
                       'Harmonic overlap can match the wrong source; reverb, inharmonic modes, bends and transients are not modeled.',
                       'Temporal mismatch and combined scores need separate evidence and are not computed.']}, residual


def rank_evaluations(reports: list[dict], weights: dict) -> dict:
    """Rank comparable reports using only explicit, nonnegative weights."""
    allowed = {'reconstruction', 'spectral', 'complexity'}
    if not isinstance(reports, list) or not reports or not isinstance(weights, dict) or set(weights) - allowed:
        raise ValueError('provide reports and reconstruction, spectral or complexity weights')
    if not weights or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in weights.values()) or not any(weights.values()):
        raise ValueError('weights must be finite, nonnegative and at least one positive')
    rows = []; reference_hash = None; reference_format = None; spectral_config = None
    for index, report in enumerate(reports):
        if not isinstance(report, dict) or report.get('schema') != 'earnest.hypothesis-evaluation.v1':
            raise ValueError('expected earnest.hypothesis-evaluation.v1 reports')
        try:
            ref_hash = report['inputs']['reference']['sha256']
            duration = report['frame_count'] / report['sample_rate_hz']
            recon = report['reconstruction']['relative_error_power']
            spectral = report['spectral_support']
            complexity = report['note_count'] / duration if report['note_count'] is not None and duration > 0 else None
        except (KeyError, TypeError, ZeroDivisionError) as exc:
            raise ValueError('evaluation is missing required metadata') from exc
        if not isinstance(ref_hash, str) or len(ref_hash) != 64 or any(c not in '0123456789abcdef' for c in ref_hash):
            raise ValueError('reference SHA-256 is required for each report')
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('evaluation duration must be positive and finite')
        current_format = (report['sample_rate_hz'], report['frame_count'], len(report['reconstruction']['channels']))
        if reference_format is None: reference_format = current_format
        if reference_format != current_format: raise ValueError('reference formats must match')
        if reference_hash is None: reference_hash = ref_hash
        if reference_hash != ref_hash: raise ValueError('reports must refer to the same reference hash')
        if weights.get('spectral', 0):
            if not isinstance(spectral, dict): raise ValueError('spectral evidence missing')
            config = tuple(spectral.get(k) for k in ('window_size','hop_size','max_harmonics','tolerance_cents'))
            if spectral_config is None: spectral_config = config
            if config != spectral_config: raise ValueError('spectral settings must match')
        terms = {'reconstruction': recon, 'spectral': spectral.get('unexplained_peak_fraction') if isinstance(spectral, dict) else None,
                 'complexity': complexity}
        for key, weight in weights.items():
            value = terms[key]
            if weight and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError('weighted term %s is unavailable or invalid' % key)
        penalty = sum(weight * terms[key] for key, weight in weights.items() if weight)
        rows.append({'input_index': index, 'score': -penalty, 'terms': terms})
    rows.sort(key=lambda row: row['score'], reverse=True)
    return {'schema': 'earnest.hypothesis-ranking.v1', 'reference_sha256': reference_hash,
            'weights': weights, 'ranked': rows,
            'limits': ['Weights are user choices; scores are not calibrated probabilities or source accuracy.',
                       'Complexity is note events per second; temporal mismatch is not evaluated.',
                       'Only reports using the same reference and spectral settings can be compared.']}
