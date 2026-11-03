"""Cross-spectral propagation for supplied source spectra and transfer functions."""
from __future__ import annotations
import numpy as np


def propagate_spectra(document: dict) -> dict:
    """Compute receiver CSD as H S Hᴴ at each frequency.

    Complex entries use [real, imaginary]. Source CSD is E[X_i conj(X_j)].
    Values are supplied by the caller; this function does not infer acoustics or SPL.
    """
    if not isinstance(document, dict) or document.get('schema') != 'earnest.soundfield-input.v1':
        raise ValueError('expected earnest.soundfield-input.v1')
    sources, receivers = document.get('sources'), document.get('receivers')
    for name, values in [('sources', sources), ('receivers', receivers)]:
        if not isinstance(values, list) or not 1 <= len(values) <= 64 or any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values):
            raise ValueError('%s must be 1-64 unique nonempty IDs' % name)
    try:
        freq = np.asarray(document['frequencies_hz'], dtype=float)
        h_parts = np.asarray(document['transfers'], dtype=float)
        s_parts = np.asarray(document['source_csd'], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('invalid frequencies, transfers, or source CSD') from exc
    if freq.ndim != 1 or not 1 <= len(freq) <= 4096 or not np.isfinite(freq).all() or np.any(freq < 0) or np.any(np.diff(freq) <= 0):
        raise ValueError('frequencies_hz must be finite, nonnegative, strictly increasing, and contain at most 4096 values')
    expected_h = (len(freq), len(receivers), len(sources), 2)
    expected_s = (len(freq), len(sources), len(sources), 2)
    if h_parts.shape != expected_h or s_parts.shape != expected_s or not np.isfinite(h_parts).all() or not np.isfinite(s_parts).all():
        raise ValueError('transfers or source_csd have invalid dimensions or nonfinite values')
    h = h_parts[..., 0] + 1j*h_parts[..., 1]
    source = s_parts[..., 0] + 1j*s_parts[..., 1]
    for i, matrix in enumerate(source):
        tolerance = 1e-10 * max(float(np.max(np.abs(matrix))), 1e-30)
        if np.max(np.abs(matrix - matrix.conj().T)) > tolerance:
            raise ValueError('source_csd[%d] must be Hermitian' % i)
        if np.min(np.linalg.eigvalsh((matrix + matrix.conj().T)/2)) < -tolerance:
            raise ValueError('source_csd[%d] must be positive semidefinite' % i)
    result = h @ source @ h.conj().transpose(0, 2, 1)
    # Remove floating-point asymmetry only; the input must already be physical.
    result = (result + result.conj().transpose(0, 2, 1)) / 2
    output = np.stack((result.real, result.imag), axis=-1)
    return {'schema': 'earnest.soundfield-spectrum.v1', 'frequencies_hz': freq.tolist(),
            'sources': sources, 'receivers': receivers, 'receiver_csd': output.tolist(),
            'receiver_power': np.maximum(np.real(np.diagonal(result, axis1=1, axis2=2)), 0).tolist(),
            'convention': 'Sx[i,j] = E[X_i conjugate(X_j)]; Sy = H Sx H^H',
            'units': document.get('units', 'relative'),
            'limits': ['Results depend on supplied transfers and source cross spectra.',
                       'No source or receiver calibration, SPL reference, or spatial grid is inferred.',
                       'Frequency points are independent; no spectrum integration or binaural perception is inferred.']}


def room_path_spectra(solution: dict, source_config: dict) -> dict:
    """Propagate source CSD through the solver's explicit coherent image paths."""
    if not isinstance(solution, dict) or solution.get('schema') != 'earnest.room-solution.v1':
        raise ValueError('expected earnest.room-solution.v1')
    if not isinstance(source_config, dict) or source_config.get('schema') != 'earnest.source-spectra.v1':
        raise ValueError('expected earnest.source-spectra.v1')
    rows = solution.get('paths')
    if not isinstance(rows, list) or not rows:
        raise ValueError('room solution has no explicit paths')
    sources = source_config.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 64 or any(not isinstance(v, str) or not v for v in sources) or len(sources) != len(set(sources)):
        raise ValueError('source spectra must specify unique source IDs')
    receivers = list(dict.fromkeys(row['receiver_id'] for row in rows))
    pairs = {(row['receiver_id'], row['source_id']): row for row in rows}
    if len(pairs) != len(rows) or any((r, s) not in pairs for r in receivers for s in sources):
        raise ValueError('room paths must contain exactly one entry for each selected source and receiver')
    bands = np.asarray(solution.get('bands_hz'), dtype=float)
    if bands.shape != (7,) or not np.isfinite(bands).all() or np.any(bands <= 0) or np.any(np.diff(bands) <= 0):
        raise ValueError('room bands must be seven increasing positive frequencies')
    frequencies = np.asarray(source_config.get('frequencies_hz'), dtype=float)
    if frequencies.ndim != 1 or not 1 <= len(frequencies) <= 4096 or not np.isfinite(frequencies).all() or np.any(frequencies < bands[0]) or np.any(frequencies > bands[-1]):
        raise ValueError('room-path frequencies must fall within the solver band centers')
    transfers = []
    for f in frequencies:
        band = int(np.argmin(np.abs(np.log(bands / f))))
        matrix = []
        for receiver in receivers:
            row = []
            for source in sources:
                total = 0j
                for path in pairs[receiver, source]['paths']:
                    gain = float(path['gain_by_band'][band]); delay = float(path['delay_s'])
                    if not np.isfinite(gain) or not np.isfinite(delay) or delay < 0:
                        raise ValueError('path gain and delay must be finite, with nonnegative delay')
                    total += gain * np.exp(-2j*np.pi*f*delay)
                row.append([float(total.real), float(total.imag)])
            matrix.append(row)
        transfers.append(matrix)
    result = propagate_spectra({'schema':'earnest.soundfield-input.v1', 'sources':sources,
              'receivers':receivers, 'frequencies_hz':frequencies.tolist(), 'transfers':transfers,
              'source_csd':source_config.get('source_csd'), 'units':source_config.get('units','relative')})
    result['model'] = 'explicit-image-paths-nearest-octave-v1'
    result['limits'] += ['Uses coherent explicit image paths only; the statistical late tail is excluded.',
                         'Path gains use 1/d without an absolute source or pressure calibration.',
                         'Surface and air gains use the nearest modeled octave center; source levels belong in source_csd.']
    return result
