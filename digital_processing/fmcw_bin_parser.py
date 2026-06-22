"""
FMCW radar raw ADC (.bin) parser for the ChronoSense dataset.

Dataset: "FMCW radar-based multi-person vital sign monitoring data"
Hardware: TI IWR6843ISK (60 GHz FMCW) + DCA1000EVM capture card.

The .bin files contain raw, uncompressed ADC samples streamed by the DCA1000
over LVDS. They use TI's standard 2-lane complex (I/Q) layout, i.e. the same
format produced by mmWave Studio and decoded by the well-known
``readDCA1000.m`` reference script. Every group of four consecutive int16
values encodes two complex samples::

    [ I0, I1, Q0, Q1 ]  ->  (I0 + jQ0), (I1 + jQ1)

Radar configuration (from DataSetDescription&ParametersSetting.pdf, Table 2):

    Start frequency .......... 60 GHz
    ADC sample rate .......... 4000 ksps
    ADC samples per chirp .... 200
    Frame period ............. 50 ms
    Number of frames ......... 1200
    Chirp loops per frame .... 1
    RX antennas .............. 4   (IWR6843ISK)
    TX antennas .............. 3   (TDM-MIMO -> 3 chirps/frame on the wire)

The frequency slope is varied (40/50/60 MHz/us) to give modulation bandwidths
of 2 / 2.5 / 3 GHz, encoded in the file name as ``adc_<BW>_position<P>_ (<N>).bin``.

Layout sanity check for a full capture::

    1200 frames * 3 TX * 4 RX * 200 samples * 2 (I+Q) * 2 bytes = 11,520,000 bytes

Some captures are truncated (e.g. test 6). The parser tolerates this: it drops
any trailing partial frame and reports how many complete frames were recovered.

Usage (library)::

    from fmcw_bin_parser import parse_bin, RadarParams
    cube = parse_bin("adc_3GHZ_position1_ (1).bin")      # (frames, chirps, rx, samples)

Usage (CLI)::

    python fmcw_bin_parser.py "adc_3GHZ_position1_ (1).bin"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Bytes the DCA1000 packs per "LVDS group": 4 int16 = 2 complex samples.
_INT16_BYTES = 2
_GROUP_INT16 = 4

# Maps the bandwidth token in a file name to the actual modulation bandwidth.
_BANDWIDTH_HZ = {
    "2GHZ": 2.0e9,
    "2_5GHZ": 2.5e9,
    "3GHZ": 3.0e9,
}


@dataclass(frozen=True)
class RadarParams:
    """Capture geometry needed to reshape the flat ADC stream into a cube.

    Defaults match the ChronoSense IWR6843ISK + DCA1000EVM configuration.
    """

    num_adc_samples: int = 200      # ADC samples per chirp
    num_rx: int = 4                 # RX antennas (IWR6843ISK)
    num_tx: int = 3                 # TX antennas (TDM-MIMO)
    chirp_loops: int = 1            # chirp loops per frame
    num_frames: int = 1200          # nominal frame count (auto-corrected below)
    adc_sample_rate: float = 4.0e6  # Hz
    frame_period: float = 50e-3     # s
    start_freq: float = 60e9        # Hz

    @property
    def chirps_per_frame(self) -> int:
        """Chirps physically present on the wire for each frame."""
        return self.num_tx * self.chirp_loops

    @property
    def complex_per_frame(self) -> int:
        """Complex ADC samples in one frame across all chirps and RX."""
        return self.chirps_per_frame * self.num_rx * self.num_adc_samples


@dataclass(frozen=True)
class FileInfo:
    """Metadata decoded from a dataset .bin file name."""

    bandwidth_token: str
    bandwidth_hz: float
    position: int
    test: int


def parse_filename(path: str | Path) -> FileInfo | None:
    """Decode ``adc_<BW>_position<P>_ (<N>).bin`` into structured metadata.

    Returns ``None`` if the name does not match the dataset convention.
    """
    name = Path(path).name
    m = re.match(
        r"adc_(?P<bw>2GHZ|2_5GHZ|3GHZ)_position(?P<pos>\d+)_\s*\((?P<test>\d+)\)\.bin",
        name,
        re.IGNORECASE,
    )
    if m is None:
        return None
    bw_token = m.group("bw").upper()
    return FileInfo(
        bandwidth_token=bw_token,
        bandwidth_hz=_BANDWIDTH_HZ.get(bw_token, float("nan")),
        position=int(m.group("pos")),
        test=int(m.group("test")),
    )


def read_dca1000(path: str | Path, params: RadarParams | None = None) -> np.ndarray:
    """Decode a DCA1000 .bin file into per-RX complex sample streams.

    Vectorised equivalent of TI's reference ``readDCA1000.m`` for the 2-lane
    complex format. The returned array has shape
    ``(num_rx, total_samples_per_rx)`` with dtype ``complex64``: row ``r`` is
    RX antenna ``r``'s samples, concatenated across every chirp of the capture.

    For a shaped (frames, chirps, rx, adc) cube use :func:`parse_bin` instead.
    """
    params = params or RadarParams()
    cube = parse_bin(path, params)
    # (frames, chirps, rx, adc) -> (rx, frames*chirps*adc)
    return np.moveaxis(cube, 2, 0).reshape(params.num_rx, -1)


def parse_bin(
    path: str | Path,
    params: RadarParams | None = None,
    *,
    strict: bool = False,
) -> np.ndarray:
    """Parse a raw ADC .bin file into a radar data cube.

    Parameters
    ----------
    path:
        Path to the .bin file.
    params:
        Capture geometry. Defaults to :class:`RadarParams` (ChronoSense config).
    strict:
        If ``True``, raise when the file does not contain a whole number of
        frames. If ``False`` (default), the trailing partial frame is dropped.

    Returns
    -------
    numpy.ndarray
        Complex64 cube of shape ``(frames, chirps_per_frame, num_rx,
        num_adc_samples)``. ``frames`` is inferred from the actual file size,
        so truncated captures yield fewer than the nominal 1200 frames.
    """
    params = params or RadarParams()

    raw = np.fromfile(path, dtype=np.int16)
    usable = (raw.size // _GROUP_INT16) * _GROUP_INT16
    dropped_bytes = (raw.size - usable) * _INT16_BYTES
    raw = raw[:usable].reshape(-1, _GROUP_INT16)

    # Decode 2-lane complex: [I0,I1,Q0,Q1] -> (I0+jQ0),(I1+jQ1).
    samples = np.empty(raw.shape[0] * 2, dtype=np.complex64)
    samples[0::2] = raw[:, 0].astype(np.float32) + 1j * raw[:, 2].astype(np.float32)
    samples[1::2] = raw[:, 1].astype(np.float32) + 1j * raw[:, 3].astype(np.float32)

    cpf = params.complex_per_frame
    n_frames = samples.size // cpf
    if n_frames == 0:
        raise ValueError(
            f"{Path(path).name}: file holds {samples.size} complex samples, "
            f"fewer than one frame ({cpf})."
        )

    leftover = samples.size - n_frames * cpf
    if leftover or dropped_bytes:
        msg = (
            f"{Path(path).name}: recovered {n_frames} complete frames; "
            f"dropped {leftover} trailing complex samples"
            + (f" and {dropped_bytes} unaligned bytes" if dropped_bytes else "")
            + "."
        )
        if strict:
            raise ValueError(msg)
        print(f"[parse_bin] {msg}")

    samples = samples[: n_frames * cpf]

    # Within each frame the layout is chirp -> RX -> ADC sample, so a plain
    # reshape lands the axes directly.
    cube = samples.reshape(
        n_frames,
        params.chirps_per_frame,
        params.num_rx,
        params.num_adc_samples,
    )
    return cube


def range_fft(cube: np.ndarray, window: bool = True) -> np.ndarray:
    """Convenience range-FFT along the fast-time (ADC sample) axis.

    Returns a complex array the same shape as ``cube``. A Hann window is applied
    by default to suppress range sidelobes.
    """
    x = cube
    if window:
        w = np.hanning(cube.shape[-1]).astype(np.float32)
        x = cube * w
    return np.fft.fft(x, axis=-1)


def _summarise(path: Path, params: RadarParams) -> None:
    info = parse_filename(path)
    cube = parse_bin(path, params)
    print(f"file            : {path.name}")
    if info is not None:
        print(f"bandwidth       : {info.bandwidth_hz / 1e9:g} GHz")
        print(f"position / test : {info.position} / {info.test}")
    print(f"cube shape      : {cube.shape}  (frames, chirps, rx, adc)")
    print(f"dtype           : {cube.dtype}")
    duration = cube.shape[0] * params.frame_period
    print(f"duration        : {duration:.2f} s ({cube.shape[0]} frames)")
    print(f"|amplitude| mean : {np.abs(cube).mean():.2f}")
    print(f"sample [f0,c0,rx0,:5] : {cube[0, 0, 0, :5]}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Parse ChronoSense FMCW radar .bin files.")
    ap.add_argument("bin", type=Path, nargs="+", help="path(s) to adc_*.bin file(s)")
    ap.add_argument("--adc-samples", type=int, default=200)
    ap.add_argument("--rx", type=int, default=4)
    ap.add_argument("--tx", type=int, default=3)
    ap.add_argument("--chirp-loops", type=int, default=1)
    args = ap.parse_args()

    p = RadarParams(
        num_adc_samples=args.adc_samples,
        num_rx=args.rx,
        num_tx=args.tx,
        chirp_loops=args.chirp_loops,
    )
    for i, b in enumerate(args.bin):
        if i:
            print("-" * 48)
        _summarise(b, p)
