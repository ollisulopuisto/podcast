#!/usr/bin/env python3
"""Generoi Hindenburg-parserin validointiin testisignaaleita.

Luo PARSER-NEEDS.md:n kolme viiteistuntoa:
- File A: lait (tasot, panorointi, häivytykset, vahvistukset)
- File B: formaatit (16/24-bittiset, mono/stereo, offsetit, päällekkäisyys, mykistys)
- File C: rakenne (bukset, efektit, master-vaimennin, automaatio)

Pee-sääntö: WAV on pelkkää ääntä. Lait — pan, häivytys, gain, fader,
autamaatio, efektit — asetetaan Hindenburgin UI:ssa alueittain, ja
manifesti sanoo mihin kukin alue tulee. Export on mittaustulos, ei
lähdetiedosto: jos laki paalautuu WAV:iin, testisignaali mittaisi
generointiohjelmaa eikä Hindenburgia.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 48000


def db_to_lin(db: float) -> float:
    """dBFS → lineaarinen amplitudi."""
    return 10 ** (db / 20)


def generate_white_noise(duration: float, sr: int, level_db: float = -20.0) -> np.ndarray:
    """Tasainen valkoinen kohina annetulla RMS-tasolla."""
    rng = np.random.default_rng()
    noise = rng.standard_normal(int(duration * sr))
    rms = np.sqrt(np.mean(noise**2))
    return noise / rms * db_to_lin(level_db)


def generate_pink_noise(duration: float, sr: int, level_db: float = -20.0) -> np.ndarray:
    """Pinkki kohina (1/f-spektri), musiikiksi tunnistettava."""
    rng = np.random.default_rng()
    white = rng.standard_normal(int(duration * sr))
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
    a = np.array([1, -2.494956002, 2.017265875, -0.522189400])
    from scipy import signal

    pink = signal.lfilter(b, a, white)
    rms = np.sqrt(np.mean(pink**2))
    return pink / rms * db_to_lin(level_db)


def write_wav(path: Path, audio: np.ndarray, sr: int = SAMPLE_RATE, subtype: str = "PCM_24"):
    """Kirjoita WAV-tiedosto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sr, subtype=subtype)


def generate_file_a_laws(out_dir: Path):
    """File A: lait — tasot, pan, häivytykset, vahvistukset.

    Lähde on aina tasainen −20 dBFS kohina ellei toisin mainita; lait
    asetetaan UI:ssa manifestin ohjeiden mukaan.
    """
    print(f"Generoi File A (lait) kansioon {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tasot: lähteen amplitudi on laki, UI:ssä ei mitään
    write_wav(out_dir / "A1_level_m20.wav", generate_white_noise(5.0, SAMPLE_RATE, -20.0))
    write_wav(out_dir / "A2_level_m35.wav", generate_white_noise(5.0, SAMPLE_RATE, -35.0))
    write_wav(out_dir / "A3_level_m50.wav", generate_white_noise(5.0, SAMPLE_RATE, -50.0))

    # Pan: tasainen mono-lähde, alueen Pan asetetaan UI:ssa
    for name in ("A4_pan_0.625.wav", "A5_pan_m0.55.wav", "A6_pan_0.wav"):
        write_wav(out_dir / name, generate_white_noise(5.0, SAMPLE_RATE, -20.0))

    # Häivytykset: tasainen lähde, häivytys asetetaan UI:ssa
    write_wav(out_dir / "A7_fade_plateau.wav", generate_white_noise(15.0, SAMPLE_RATE, -20.0))
    write_wav(out_dir / "A8_fade_short.wav", generate_white_noise(3.0, SAMPLE_RATE, -20.0))

    # Vahvistukset: tasainen lähde, Gain/ClipGain/fader asetetaan UI:ssa
    for name in ("A9_gain_plus6.wav", "A10_both_gain_clipgain.wav", "A11_track_fader_m6.wav"):
        write_wav(out_dir / name, generate_white_noise(5.0, SAMPLE_RATE, -20.0))

    manifest = {
        "A1_level_m20.wav": {
            "ui": None,
            "expect": "renderöidyn alueen huippu ≈ −20 dBFS",
        },
        "A2_level_m35.wav": {
            "ui": None,
            "expect": "renderöidyn alueen huippu ≈ −35 dBFS",
        },
        "A3_level_m50.wav": {
            "ui": None,
            "expect": "renderöidyn alueen huippu ≈ −50 dBFS",
        },
        "A4_pan_0.625.wav": {
            "ui": "alueen Pan = 0.625",
            "expect": "L/R-RMS-suhde mittaa pan-lain",
        },
        "A5_pan_m0.55.wav": {
            "ui": "alueen Pan = −0.55",
            "expect": "L/R-RMS-suhde mittaa pan-lain",
        },
        "A6_pan_0.wav": {
            "ui": "alueen Pan = 0 (keskitetty)",
            "expect": "L/R-RMS-suhde ≈ 1",
        },
        "A7_fade_plateau.wav": {
            "ui": "häivytys tasolle: 2,5 s ramp, 10 s hold, 2,5 s ramp alas",
            "expect": "verhouksen muoto — käyrä, ei vain päätepisteet",
        },
        "A8_fade_short.wav": {
            "ui": "0,5 s häivytys ilman Gainia",
            "expect": "päätteen lukema: palaaako yhden vai",
        },
        "A9_gain_plus6.wav": {
            "ui": "alueen Gain +6 dB",
            "expect": "huippu ≈ −14 dBFS",
        },
        "A10_both_gain_clipgain.wav": {
            "ui": "Gain +6 dB JA ClipGain +6 dB",
            "expect": "ClipGain voittaa (≈ −14 dBFS), ei summa (≈ −8)",
        },
        "A11_track_fader_m6.wav": {
            "ui": "oman raidan vaimennin −6 dB, vain tämä alue raidalla",
            "expect": "huippu ≈ −26 dBFS — raidan fader osallistuu summaan",
        },
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Kirjoitti {len(manifest)} tiedostoa + manifestin")


def generate_file_b_formats(out_dir: Path):
    """File B: formaatit — bittisyvyydet, kanavat, offsetit, raidat, mykistys."""
    print(f"Generoi File B (formaarit) kansioon {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 16-bittinen mono
    write_wav(out_dir / "B1_16bit_mono.wav", generate_white_noise(3.0, SAMPLE_RATE, -20.0), subtype="PCM_16")

    # 24-bittinen mono
    write_wav(out_dir / "B2_24bit_mono.wav", generate_white_noise(3.0, SAMPLE_RATE, -20.0))

    # 24-bittinen stereo: kanavat eri tasoisia jotta ne erottuvat toisistaan
    noise = generate_white_noise(3.0, SAMPLE_RATE, -20.0)
    write_wav(out_dir / "B3_24bit_stereo.wav", np.column_stack([noise, noise * 0.5]))

    # Pitkä tiedosto: alue alkaa 1,5 s tiedoston sisältä (UI:ssä Offset)
    write_wav(out_dir / "B4_long_file.wav", generate_white_noise(5.0, SAMPLE_RATE, -20.0))

    # Päällekkäiset alueet kahdella raidalla
    write_wav(out_dir / "B5_lane1.wav", generate_white_noise(5.0, SAMPLE_RATE, -20.0))
    write_wav(out_dir / "B6_lane2.wav", generate_white_noise(5.0, SAMPLE_RATE, -30.0))

    # Mykistetty alue: hiljaisuus
    write_wav(out_dir / "B7_muted_silence.wav", np.zeros(int(3.0 * SAMPLE_RATE)))

    # Musiikki: pinkki kohina, eri spektrinen sisältö
    write_wav(out_dir / "B8_music_pink.wav", generate_pink_noise(3.0, SAMPLE_RATE, -20.0))

    manifest = {
        "B1_16bit_mono.wav": {"ui": None, "expect": "16-bittinen mono purkautuu"},
        "B2_24bit_mono.wav": {"ui": None, "expect": "24-bittinen mono purkautuu"},
        "B3_24bit_stereo.wav": {
            "ui": None,
            "expect": "stereo-alue: mitä kanavat olivat (yhdistetty? toinen puoli?)",
        },
        "B4_long_file.wav": {
            "ui": "alue alkaa 1,5 s tiedoston sisältä (Offset)",
            "expect": "Offset-lukema: ääni oikeasta kohdasta",
        },
        "B5_lane1.wav": {
            "ui": "lane 1, päällekkäin B6:n kanssa",
            "expect": "molemmat alueet summautuvat",
        },
        "B6_lane2.wav": {
            "ui": "lane 2, päällekkäin B5:n kanssa",
            "expect": "molemmat alueet summautuvat",
        },
        "B7_muted_silence.wav": {
            "ui": "alue mykistetty (Mute)",
            "expect": "exportissa ei ääntä",
        },
        "B8_music_pink.wav": {
            "ui": "musiikkiradan tyyppi",
            "expect": "raidan tyyppi näkyy .nhsx:stä",
        },
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Kirjoitti {len(manifest)} tiedostoa + manifestin")


def generate_file_c_structure(out_dir: Path):
    """File C: rakenne — buksit, efektit, master-vaimennin, automaatio.

    Lähde on aina tasainen kohina; rakenne (lähetys, efekt, automaatio)
    rakennetaan UI:ssa manifestin ohjeiden mukaan.
    """
    print(f"Generoi File C (rakenne) kansioon {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Bussi/aux: kaksi raitaa, lähetys asetetaan UI:ssa
    write_wav(out_dir / "C1_main_track.wav", generate_white_noise(5.0, SAMPLE_RATE, -20.0))
    write_wav(out_dir / "C2_aux_send.wav", generate_white_noise(5.0, SAMPLE_RATE, -26.0))

    # Effekti raidalla: reverberi asetetaan UI:ssa
    write_wav(out_dir / "C3_reverb.wav", generate_white_noise(2.0, SAMPLE_RATE, -20.0))

    # Master-vaimentimen automaatio asetetaan UI:ssa
    write_wav(out_dir / "C4_master_fade.wav", generate_white_noise(10.0, SAMPLE_RATE, -20.0))

    # Pan-autamaatio asetetaan UI:ssa
    write_wav(out_dir / "C5_pan_sweep.wav", generate_white_noise(5.0, SAMPLE_RATE, -20.0))

    manifest = {
        "C1_main_track.wav": {
            "ui": "pääraita + aux-lähetys C2-raitaan",
            "expect": "bussin osuus summassa",
        },
        "C2_aux_send.wav": {
            "ui": "aux-raita",
            "expect": "lähetystaso näkyy",
        },
        "C3_reverb.wav": {
            "ui": "raidalla reverberointi (decay 0,5 s)",
            "expect": "efekti osallistuu renderöintiin",
        },
        "C4_master_fade.wav": {
            "ui": "master-vaimentimen automaatio: 0 → −20 dB / 10 s",
            "expect": "autamaation käyrä",
        },
        "C5_pan_sweep.wav": {
            "ui": "panorama-automatio: −1 → 1 / 5 s",
            "expect": "L/R-suhde muuttuu ajan funktiona",
        },
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Kirjoitti {len(manifest)} tiedostoa + manifestin")


def generate_sine(freq: float, duration: float, sr: int, level_db: float = -20.0) -> np.ndarray:
    """Puhdas siniaalto annetulla taajuudella ja tasolla.

    Taajuudet valitaan niin, että jakso on tasainen näytemäärä (400 Hz =
    120 näytettä, 1000 Hz = 48): liukuvan ikkunan vuoto ei sitten valehtele.
    """
    t = np.arange(int(duration * sr)) / sr
    return np.sin(2 * np.pi * freq * t) * db_to_lin(level_db)


def generate_file_d_joints(out_dir: Path):
    """File D: saumat — mitä Hindenburg tekee leikkeiden liitoksissa.

    Kaksi eri taajuista siniaaltoa ja yksi yhtenäinen kohina. Siniaallot
    tunnistetaan taajuudella (sama temppu kuin make_fixture.py:ssä), joten
    päällekkäin asetettujen leikkeiden kuoret voidaan mitata erikseen.
    Kohina on differenssimittaan: koko tiedoston renderöinti vs. kahteen
    leikkeeseen pilkottu — residyyli on itse sauman muokkaus.
    """
    print(f"Generoi File D (saumat) kansioon {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    write_wav(out_dir / "D1_tone_400.wav", generate_sine(400.0, 10.0, SAMPLE_RATE))
    write_wav(out_dir / "D2_tone_1000.wav", generate_sine(1000.0, 10.0, SAMPLE_RATE))
    write_wav(out_dir / "D3_long_noise.wav", generate_white_noise(30.0, SAMPLE_RATE))

    manifest = {
        "D1_tone_400.wav": {
            "ui": "katso saumataulukko README-hakemistosta alla",
            "expect": "400 Hz:n kuoren verhoussiirto saumassa",
        },
        "D2_tone_1000.wav": {
            "ui": None,
            "expect": "1000 Hz:n kuoren verhoussiirto saumassa",
        },
        "D3_long_noise.wav": {
            "ui": "kaksi raitaa samaan istuntoon: kokonainen vs. kahtia pilkottu",
            "expect": "renderöintien differenssi = sauman muokkaus",
        },
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Kirjoitti {len(manifest)} tiedostoa + manifestin")


def main():
    parser = argparse.ArgumentParser(description="Generoi Hindenburg-parserin validointiin testisignaaleja")
    parser.add_argument("--out", type=Path, default=Path("test_signals"), help="Tulokansio")
    parser.add_argument("--which", choices=["A", "B", "C", "D", "all"], default="all", help="Mikä tiedostopaketti")
    parser.add_argument("--sr", type=int, default=48000, help="Näytetaajuus")
    args = parser.parse_args()

    global SAMPLE_RATE
    SAMPLE_RATE = args.sr

    base = args.out
    if args.which in ("A", "all"):
        generate_file_a_laws(base / "file_a_laws")
    if args.which in ("B", "all"):
        generate_file_b_formats(base / "file_b_formats")
    if args.which in ("C", "all"):
        generate_file_c_structure(base / "file_c_structure")
    if args.which in ("D", "all"):
        generate_file_d_joints(base / "file_d_joints")

    print(f"\nKaikki testisignaalit generoitu kansioon {base}")
    print("Seuraavat vaiheet:")
    print("  1. Tuo WAV-tiedostot Hindenburgiin")
    print("  2. Rakenna manifestin ohjeiden mukaan istunnot (lait UI:ssä)")
    print("  3. Vie .nhsx + WAV-renderöinti jokaisesta istunnosta")
    print("  4. Sovita exportit PARSER-NEEDS.md:n reseptin mukaan")


if __name__ == "__main__":
    main()
