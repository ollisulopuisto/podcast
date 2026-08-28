"""Miksaus ääneksi: leikkeet sisään, ohjelma-WAV ulos.

Tämä on se puolisko, jota Hindenburg ei tarvitse olla olemassa jotta se
toimisi. ``mix.plan`` kertoo mitä kuuluu ja milloin; tämä lukee lähteet ja
summaa ne. Yhdessä ne ovat istunnon lukukelpoisuus ilman sitä ohjelmaa jolla
se tehtiin.

## Ohjelmaa ei pidetä muistissa

Tunnin jakso on 48 kHz:llä stereona liukulukuina 1,4 GB, ja se on pelkkä
lopputulos — lähteitä on lisäksi yksi per raita. Siksi renderöinti etenee
**lohkoina**: ``blocks`` antaa ohjelman pala kerrallaan ja ``to_wav``
kirjoittaa jokaisen palan levylle heti. Muistissa on kerrallaan yksi lohko
ja yhden leikkeen verran lähdettä.

Lähteestä puretaan **vain se kohta jota tarvitaan** (``-ss``/``-t``), ei
koko tiedostoa. Se on sekä muistin että nopeuden takia: kolmen sekunnin
leike tunnin nauhalta on kolmen sekunnin purku.

Lohkon raja on tämän rakenteen vaarallinen kohta. Leike voi katketa siihen,
häivytys voi alkaa siitä alusta, lähteestä voi tulla luetuksi väärä kohta —
eikä mikään niistä kaada mitään: tulos on kelvollinen WAV, jossa on
naksahdus tasavälein. Siksi verhokäyrä lasketaan **koko leikkeelle** ja
viipaloidaan lohkoon, kaikki paikat lasketaan näyteindekseinä eikä
sekunteina, ja ``test_the_block_size_does_not_change_the_result`` ajaa saman
miksauksen kahdella lohkokoolla.

## Ylivuoto rajataan ja kerrotaan

Kahdeksan raidan summa menee yli. Kiertyvä ylivuoto ei ole kova ääni vaan
rätinää, joten summa rajataan — mutta rajaus on tieto, ei korjaus, ja
``Report`` kertoo huipun ja rajattujen näytteiden määrän. Ilman sitä
renderöinti «onnistuisi» ja tulos olisi särönä.
"""

from __future__ import annotations

import subprocess
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..binaries import get_binary_path
from .mix import Mix, envelope, pan_gains

# Ohjelman oletustaajuus. 48 kHz eikä 44,1: Hindenburgin lähteet ovat
# käytännössä 48 kHz, ja renderöinti ilman uudelleennäytteistystä on sekä
# nopeampi että lähempänä alkuperäistä.
SAMPLE_RATE = 48000

# Lohkon pituus sekunteina. 30 s on 48 kHz:llä stereona 11 MB — pieni
# tarpeeksi kannettavalle, iso tarpeeksi ettei ffmpegiä käynnistetä
# jatkuvasti pikkupaloihin.
BLOCK = 30.0

# Ulostulon kanavamäärä. Panorointi on stereokäsite ja esikatselu on
# stereona; monolähde levitetään, stereolähde säilyttää puolensa.
CHANNELS = 2

pan_of = pan_gains  # testien ja esikatselun luettavampi nimi


@dataclass
class Report:
    """Mitä renderöinnissä tapahtui. Tyhjä raportti on hyvä uutinen."""

    peak: float = 0.0
    clipped: int = 0
    duration: float = 0.0
    unreadable: list[str] = field(default_factory=list)

    @property
    def peak_dbfs(self) -> float:
        return 20.0 * float(np.log10(self.peak)) if self.peak > 0 else float("-inf")


def decode_slice(path: str, start: float, length: float, sample_rate: int) -> np.ndarray:
    """Purkaa lähteestä jakson ``[start, start+length)`` taulukoksi ``(n, kanavat)``.

    ``-ss`` ennen ``-i``:tä, koska silloin ffmpeg hakee tiedostossa sen
    sijaan että purkaisi alusta ja heittäisi pois: tunnin nauhan lopusta
    otettu kolmen sekunnin leike on muuten kolmen sekunnin sijaan tunnin
    työ. Kanavat säilytetään kahteen asti — stereo musiikkipohja monoksi
    summattuna on kuultava virhe eikä pyöristys.
    """
    out = subprocess.run(
        decode_command(path, start, length, sample_rate), capture_output=True, check=True
    ).stdout
    return np.frombuffer(out, np.float32).reshape(-1, 2)


def decode_command(path: str, start: float, length: float, sample_rate: int) -> list[str]:
    """``decode_slice``in komentorivi omana funktionaan, jotta se on väitettävissä.

    Argumenttien **järjestys** on tässä se mikä ratkaisee, eikä sitä voi
    tarkistaa tuloksesta: ``-ss`` väärällä puolella ``-i``:tä antaa täsmälleen
    saman äänen, se vain puretaan alusta asti ja heitetään pois. Tunnin nauhan
    lopusta otettu kolmen sekunnin leike on silloin kolmen sekunnin sijaan
    tunnin työ — esikatselu ei riko mitään, se vain lakkaa olemasta
    esikatselu. Kellosta mitattuna sen erottaisi vasta tiedostolla, joka on
    liian iso testattavaksi; komennosta sen näkee suoraan.
    """
    return [
        get_binary_path("ffmpeg"),
        "-nostdin",
        # Ennen -i:tä: hae tiedostossa. Jälkeen: pura alusta ja heitä pois.
        "-ss", f"{max(0.0, start):.6f}",
        "-i", str(path),
        "-t", f"{max(0.0, length):.6f}",
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ar", str(sample_rate),
        "-ac", "2",
        "-",
    ]


def _spread(samples: np.ndarray, want: int) -> np.ndarray:
    """Purun tulos halutun mittaiseksi, ``(want, kanavat)``.

    Lyhyt lähde **täytetään hiljaisuudella** eikä toisteta: alue voi olla
    lähdettään pidempi (Hindenburgissa venytetty tai lähde vaihdettu), ja
    toistettu alku olisi ääntä joka ei ole missään.
    """
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    n = samples.shape[0]
    if n == want:
        return samples
    if n > want:
        return samples[:want]
    pad = np.zeros((want - n, samples.shape[1]), dtype=np.float32)
    return np.concatenate([samples, pad])


def blocks(
    mixdown: Mix,
    sample_rate: int = SAMPLE_RATE,
    decode: Callable[..., np.ndarray] | None = None,
    block: float = BLOCK,
    report: Report | None = None,
) -> Iterator[np.ndarray]:
    """Ohjelma lohkoina, jokainen ``(n, 2)`` liukulukuina välillä [−1, 1].

    Purkaja on parametri eikä tuonti, jotta summaus on testattavissa ilman
    ffmpegiä. CI ei skippaa: ffmpegiä tarvitseva testi olisi vihreä siellä
    missä ffmpegiä ei ole, eli sama kuin ettei sitä olisi.
    """
    decode = decode or decode_slice
    report = report if report is not None else Report()

    total = int(round(mixdown.duration * sample_rate))
    report.duration = total / sample_rate
    block_n = max(1, int(round(block * sample_rate)))
    broken: set[str] = set()

    # Verhokäyrä ja panorointi ovat leikkeen ominaisuuksia, eivät lohkon.
    # Lasketaan kerran, viipaloidaan lohkoihin — tämä on se kohta, jossa
    # lohkoraja muuten kuuluisi.
    prepared = []
    for clip in mixdown.clips:
        first = int(round(clip.start * sample_rate))
        count = int(round(clip.length * sample_rate))
        if count <= 0:
            continue
        env = envelope(clip.length, sample_rate, clip.ramps)
        env = _spread(env.reshape(-1, 1), count).reshape(-1)
        left, right = pan_gains(clip.pan)
        prepared.append((clip, first, count, env, np.float32(left), np.float32(right)))

    if total <= 0:
        return

    for begin in range(0, total, block_n):
        end = min(total, begin + block_n)
        out = np.zeros((end - begin, CHANNELS), dtype=np.float32)

        for clip, first, count, env, left, right in prepared:
            lo = max(begin, first)
            hi = min(end, first + count)
            if hi <= lo:
                continue
            if clip.path in broken:
                continue

            # Kaikki paikat näyteindekseinä. Sekunneista laskettuna lohkon
            # raja pyöristyisi eri suuntaan kuin leikkeen alku, ja ero
            # kasvaisi ohjelman mitassa.
            want = hi - lo
            file_start = clip.file_offset + (lo - first) / sample_rate
            try:
                source = decode(clip.path, file_start, want / sample_rate, sample_rate)
            except (OSError, subprocess.CalledProcessError, ValueError):
                broken.add(clip.path)
                if clip.path not in report.unreadable:
                    report.unreadable.append(clip.path)
                continue

            source = _spread(np.asarray(source, dtype=np.float32), want)
            shaped = source * (env[lo - first : hi - first, None] * clip.gain)

            if shaped.shape[1] == 1:
                out[lo - begin : hi - begin, 0] += shaped[:, 0] * left
                out[lo - begin : hi - begin, 1] += shaped[:, 0] * right
            else:
                # Stereolähde säilyttää puolensa; panorointi kallistaa
                # tasapainoa eikä sekoita kanavia keskenään.
                out[lo - begin : hi - begin, 0] += shaped[:, 0] * (left * np.sqrt(2.0))
                out[lo - begin : hi - begin, 1] += shaped[:, 1] * (right * np.sqrt(2.0))

        peak = float(np.abs(out).max()) if out.size else 0.0
        report.peak = max(report.peak, peak)
        if peak > 1.0:
            report.clipped += int(np.count_nonzero(np.abs(out) > 1.0))
            np.clip(out, -1.0, 1.0, out=out)

        yield out


def to_wav(
    mixdown: Mix,
    path: str | Path,
    sample_rate: int = SAMPLE_RATE,
    bit_depth: int = 24,
    decode: Callable[..., np.ndarray] | None = None,
    block: float = BLOCK,
    progress: Callable[[float], None] | None = None,
) -> Report:
    """Renderöi ohjelman WAV-tiedostoksi lohko kerrallaan.

    24 bittiä oletuksena: tämä on istunnon arkistokopio, ja lähteet ovat
    yleensä 24-bittisiä. 16 on olemassa julkaisua varten.
    """
    if bit_depth not in (16, 24):
        raise ValueError(f"Bittisyvyys on 16 tai 24, ei {bit_depth}.")

    report = Report()
    written = 0
    total = max(1, int(round(mixdown.duration * sample_rate)))

    with wave.open(str(path), "wb") as out:
        out.setnchannels(CHANNELS)
        out.setsampwidth(bit_depth // 8)
        out.setframerate(sample_rate)
        for chunk in blocks(mixdown, sample_rate, decode, block, report):
            out.writeframes(_pack(chunk, bit_depth))
            written += chunk.shape[0]
            if progress is not None:
                progress(min(1.0, written / total))

    return report


def _pack(chunk: np.ndarray, bit_depth: int) -> bytes:
    """Liukuluvut kokonaisluvuiksi tavuina.

    Skaala on ``2**(bits-1) - 1`` eikä ``2**(bits-1)``, jotta täysi +1,0 ei
    kierry negatiiviseksi. Ero on yhden bitin verran tasoa ja koko ero
    kuultavana.
    """
    full = float(2 ** (bit_depth - 1) - 1)
    scaled = np.clip(chunk, -1.0, 1.0) * full
    if bit_depth == 16:
        return scaled.astype("<i2").tobytes()
    # 24-bittiselle ei ole omaa dtypeä: kirjoitetaan 32-bittisenä ja otetaan
    # **kolme alinta** tavua, jotka ovat little-endianina ensimmäiset. Ylin
    # tavu on etumerkin jatke ja se pudotetaan; arvo mahtuu 24 bittiin, joten
    # kahden komplementti säilyy oikein.
    #
    # Kolme *ylintä* olisi sama luku 8 bittiä siirrettynä eli 48 dB liian
    # hiljaa, eikä mikään kaatuisi: WAV olisi kelvollinen, kesto oikea ja
    # `Report.peak` — joka mitataan liukuluvuista ennen pakkausta — kertoisi
    # oikean huipun tiedostosta joka on 256× hiljaisempi. Niin tässä oli, ja
    # se jäi kiinni vasta oikeasta renderöinnistä.
    as32 = scaled.astype("<i4")
    return as32.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
