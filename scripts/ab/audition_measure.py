"""Audition-mittaukset: onko Mix lineaarinen, ja kuinka pitkä esiaika riittää.

    uv run --package speechmix python scripts/ab/audition_measure.py JAKSO.wav \\
        --plugin /Library/Audio/Plug-Ins/VST3/dxRevive.vst3 \\
        --state tila.b64 --start 600 --seconds 10 --mix-param NIMI

Kaksi kysymystä, jotka ``docs/plans/2026-10-16-voice-presets.md`` (osa B) jätti
mitattaviksi, ja yksi ajo vastaa molempiin:

**A0. Onko Mix lineaarinen dry/wet-sekoitus?** Ajetaan ikkuna 100 %:lla ja
pienemmillä arvoilla, ja verrataan jokaista osittaista ajoa raakaäänen ja
100 %:n ajon samaan sekoitukseen. Jäännös alle ``LINEAR_DB`` (−60 dB) viiveen
korjauksen jälkeen tarkoittaa lineaarista: yhdestä 100 %:n renderistä saa
jatkuvan liukusäätimen. Muuten vain erilliset ajot ovat rehellisiä.

**A1. Kuinka pitkä esiaika, ja mitä ajo maksaa?** Sama ikkuna ajetaan eri
esiajoilla; lyhin esiaika, jonka tulos on pidimmän kanssa samaa
(``LINEAR_DB``:n sisällä), on se jonka jälkeen liitännäinen on asettunut.
Kellot otetaan 1, 2 ja 4 työntekijällä.

Mittari on erillään liitännäisestä, ja sen testit ajetaan tunnetuilla
valeliitännäisillä (``tests/test_audition_measure.py``): lineaarisella jonka
pitää nollautua, epälineaarisella jonka ei, ja muistillisella jonka esiaika
löytyy. Oikea dxRevive kuuluu vain tähän ajoon, eikä sitä ole pilvessä.

Tulos tulostuu taulukkoina, jotka liitetään ``SHARED-AUDIO.md``:hen.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

#: Jäännöksen raja, jonka alle kaksi renderiä ovat «sama». −60 dB on kuulon
#: ulkopuolella ja selvästi yli float32:n kohinan; sama raja on suunnitelmassa.
LINEAR_DB = -60.0

#: Kuinka monta dB:n verran jäännöksen pitää ylittää toistokohina, jotta ero
#: luetaan todelliseksi. 10 dB = kolminkertainen amplitudi.
BEYOND_NOISE_DB = 10.0

#: Jälkiaika sekunteina. Viiveellinen liitännäinen siirtää sisältöä myöhemmäksi
#: mutta pitää pituuden, joten ikkunan loppu jää ulos ellei sen perään anneta
#: tilaa. Viiveet ovat satoja millisekunteja korkeintaan (dxRevive: 4641
#: näytettä = 0,097 s 48 kHz:llä).
DEFAULT_TAIL = 0.5


def residual_db(target: np.ndarray, candidate: np.ndarray) -> float:
    """``candidate``:n ero ``target``:sta dB:nä ``target``:n tehoon nähden.

    0 dB = ei mitään yhteistä, −60 dB = tuhannesosa amplitudista. Nimittäjä on
    ``target`` eli osittainen ajo, jota sekoitus yrittää kuvata.
    """
    n = min(target.shape[-1], candidate.shape[-1])
    a = target[..., :n].astype(np.float64)
    b = candidate[..., :n].astype(np.float64)
    power = float(np.sqrt(np.mean(a**2)))
    if power == 0.0:
        return float("inf")
    error = float(np.sqrt(np.mean((a - b) ** 2)))
    return 20.0 * np.log10(max(error, 1e-12) / power)


def is_linear(residual: float) -> bool:
    return residual < LINEAR_DB


def _shift_back(audio: np.ndarray, lag: int) -> np.ndarray:
    """Siirtää ``audio``:ta ``lag`` näytettä aikaisemmaksi, pituus säilyy."""
    if lag == 0:
        return audio
    out = np.zeros_like(audio)
    if lag > 0:
        out[..., : audio.shape[-1] - lag] = audio[..., lag:]
    else:
        out[..., -lag:] = audio[..., : audio.shape[-1] + lag]
    return out


def render_window(
    plugin,
    audio: np.ndarray,
    rate: int,
    start: float,
    end: float,
    preroll: float,
    tail: float = DEFAULT_TAIL,
    lag: int | None = None,
) -> tuple[np.ndarray, int]:
    """Ikkuna ``[start, end)`` liitännäisen läpi, viive pois, ikkunan mittaiseksi.

    Palaa ``(ikkuna, viive)``. Ajo on kokonainen ``reset=True``-ajo
    ``start - preroll`` .. ``end + tail``, koska liitännäinen ei saa jatkaa
    edellisen ajon tilasta (ks. ``chain.apply_plugin``), ja esiaika lämmittää
    sen ennen ikkunaa. ``lag`` annettuna käytetään sitä; muuten se mitataan
    näytetarkkuudella. Liitännäisen ilmoittamaan viiveeseen ei luoteta
    (``chain.lag_samples``).
    """
    from speechmix import chain

    if start - preroll < 0:
        raise ValueError(
            f"the window starts at {start:.1f} s, before the preroll of {preroll:.1f} s"
        )
    first = int((start - preroll) * rate)
    last = min(audio.shape[1], int((end + tail) * rate))
    piece = np.ascontiguousarray(audio[:, first:last], dtype=np.float32)
    done = chain.apply_plugin(plugin, piece, rate)
    if lag is None:
        # bin_ms = 1 näyte: oletus 1 ms antaisi ±48 näytteen epävarmuuden, ja
        # −60 dB:n nollaus vaatii näytetarkkuuden.
        lag = chain.lag_samples(piece[0], done[0], rate, bin_ms=1000.0 / rate)
    aligned = _shift_back(done, lag)
    low = int(start * rate) - first
    high = low + int((end - start) * rate)
    return aligned[:, low:high], lag


def linear_mix_residual_db(
    raw: np.ndarray, full: np.ndarray, partial: np.ndarray, level: float
) -> float:
    """Osittaisen ajon ero raakaäänen ja täyden ajon sekoituksesta, dB.

    Kaikki kolme ovat samaan aikaan viivekorjattuja ikkunoita
    (``render_window``). ``level`` on 0–1: 0,5 = puolet täydestä.
    """
    blend = (1.0 - level) * raw.astype(np.float64) + level * full.astype(np.float64)
    return residual_db(partial, blend)


def fit_blend(
    raw: np.ndarray, full: np.ndarray, partial: np.ndarray
) -> tuple[float, float, float]:
    """``partial`` ≈ ``a``·``raw`` + ``b``·``full`` pienimmän neliösumman mielessä.

    Palaa ``(a, b, jäännös dB)``. Kysymys on yleisempi kuin «onko Mix (1-m)/m»:
    onko osittainen ajo **minkä tahansa** kahden osan summa, ja mitkä ovat
    painot. Jos jäännös on toistokohinan tasolla, ``a`` ja ``b`` ovat Mixin
    laki tällä tasolla (esim. 0,75/0,25 neliöllä tai cos/sin tasavirtaisella),
    ja yksi 100 %:n ajo riittää jatkuvaan säätimeen sen lain mukaan. Jos ei,
    märkä osa itsessään riippuu Mixistä, eikä yksi ajo riitä.
    """
    x = np.stack([raw.ravel(), full.ravel()], axis=1).astype(np.float64)
    y = partial.ravel().astype(np.float64)
    (a, b), *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = (a * raw + b * full).astype(np.float64)
    return float(a), float(b), residual_db(partial, fitted)


def settled_preroll(
    renders: dict[float, np.ndarray], floor_db: float | None = None
) -> float | None:
    """Lyhin esiaika, jonka tulos on pidimmän kanssa samaa.

    ``renders`` on esiaika -> ikkuna. Pisin esiaika on viite, joten se on
    itsensä kanssa aina sama eikä ratkaise mitään: palautetaan lyhin
    **lyhyempi** joka asettuu, tai ``None`` jos mikään ei ole.

    «Samaa» on ``LINEAR_DB``, ellei liitännäinen itse toista itseään sitä
    tarkemmin: ``floor_db`` on kahden samanlaisen ajon ero (``repeat_residual_db``),
    ja raja nousee sen yläpuolelle kolme desibeliä. Ilman tätä ei toistettava
    liitännäinen ei koskaan «asettuisi», vaikka syy olisi kohinassa eikä muistissa.
    """
    limit = LINEAR_DB if floor_db is None else max(LINEAR_DB, floor_db + 3.0)
    reference_key = max(renders)
    reference = renders[reference_key]
    for key in sorted(renders):
        if key == reference_key:
            continue
        if residual_db(reference, renders[key]) < limit:
            return key
    return None


def repeat_residual_db(
    plugin,
    audio: np.ndarray,
    rate: int,
    start: float,
    end: float,
    preroll: float,
    tail: float = DEFAULT_TAIL,
) -> float:
    """Kahden samanlaisen ajon ero, dB: mittauksen oma kohinalattia.

    Sama ikkuna, samat asetukset, kaksi täyttä ``reset=True``-ajoa. Jos tämä
    on jo −60 dB:n yläpuolella, liitännäinen ei toista itseään (generatiivinen
    malli tai ajosta riippuva tila), ja **kaikki muut tämän skriptin jäännökset
    sisältävät saman kohinan**: ne eivät kerro Mixistä eivätkä esiajasta mitään
    sen alapuolella. Lineaarisuuden «ei» ilman tätä kontrollia on väite jota ei
    ole osoitettu.
    """
    first, lag = render_window(plugin, audio, rate, start, end, preroll, tail=tail)
    second, _ = render_window(
        plugin, audio, rate, start, end, preroll, tail=tail, lag=lag
    )
    return residual_db(first, second)


def render_variants_full(
    plugins: list,
    variants: list[dict],
    audio: np.ndarray,
    rate: int,
    start: float,
    end: float,
    preroll: float,
    workers: int,
    tail: float = DEFAULT_TAIL,
    lag: int | None = None,
) -> tuple[list[np.ndarray], list[int], float]:
    """Ikkuna kullakin arvolla rinnakkain. Palaa ``(ajot, viiveet, sekunnit)``.

    Yksi instanssi per arvo: VST3-olio on tilallinen eikä sitä voi ajaa kahdesta
    säikeestä yhtä aikaa (``chain.PluginPool``). Ladattujen instanssien pitää olla
    kutsujan lataamia (pääsäie), tässä vain käytetään. Tuntematon parametrin nimi
    on virhe: ``chain.apply_parameters`` ohittaisi sen hiljaa, ja mittaus
    kuvaisi liitännäisen oletusta.

    ``lag`` annettuna käytetään sitä kaikkiin. Ilman sitä jokainen ajo mitataan
    omalla viiveellään, ja ne palautetaan: viive voi riippua Mixistä (kuiva ja
    märkä polku eivät aina viivästy yhtä paljon), ja yhteinen viive siirtäisi
    silloin toisen komponentin pois paikaltaan.
    """
    from speechmix import chain

    if len(plugins) != len(variants):
        raise ValueError("one plug-in instance per variant")
    for plugin, params in zip(plugins, variants, strict=True):
        skipped = chain.apply_parameters(plugin, params)
        if skipped:
            raise ValueError(f"the plug-in has no parameter {', '.join(skipped)}")

    def one(index: int):
        return render_window(
            plugins[index], audio, rate, start, end, preroll, tail=tail, lag=lag
        )

    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, range(len(plugins))))
    seconds = time.perf_counter() - began
    return [w for w, _ in results], [lg for _, lg in results], seconds


def render_variants(*args, **kwargs) -> tuple[list[np.ndarray], float]:
    """Kuten ``render_variants_full``, ilman viiveitä."""
    windows, _, seconds = render_variants_full(*args, **kwargs)
    return windows, seconds


def format_linearity(residuals: dict[float, float], control: float | None = None) -> str:
    """Taulukko ``SHARED-AUDIO.md``:hen ja yksi lause siitä mitä se tarkoittaa.

    ``control`` on kahden samanlaisen ajon ero (``repeat_residual_db``). Jos
    se on ``LINEAR_DB``:n yläpuolella, jäännökset eivät kerro lineaarisuudesta
    mitään, ja lause sanoo niin.
    """
    lines = ["| level | residual vs raw/100 % blend |", "|---|---|"]
    for level in sorted(residuals):
        lines.append(f"| {level:g} | {residuals[level]:.1f} dB |")
    if control is not None:
        lines.append(f"| repeat (same setting twice) | {control:.1f} dB |")
    worst = max(residuals.values())
    margin = None if control is None else worst - control
    if control is not None and not is_linear(control) and margin >= BEYOND_NOISE_DB:
        verdict = (
            f"Not linear beyond the repeat noise: the worst residual {worst:.1f} dB "
            f"is {margin:.1f} dB above the repeat noise ({control:.1f} dB), so the "
            "Mix is not a plain dry/wet blend. The weights below say what it is."
        )
    elif control is not None and not is_linear(control):
        verdict = (
            f"Inconclusive: two identical renders already differ by {control:.1f} dB "
            f"(repeat noise), above {LINEAR_DB:.0f} dB, so the residuals above "
            "include the plug-in's own run-to-run variation. Neither linear nor "
            "non-linear is shown."
        )
    elif is_linear(worst):
        verdict = (
            f"Linear: the worst residual {worst:.1f} dB is below {LINEAR_DB:.0f} dB, "
            "so one 100 % render can serve a continuous level slider."
        )
    else:
        verdict = (
            f"Not linear: the worst residual {worst:.1f} dB is above "
            f"{LINEAR_DB:.0f} dB, so only discrete renders are honest."
        )
    return "\n".join([*lines, "", verdict])


def format_blend_fit(
    fits: dict[float, tuple[float, float, float]], control: float | None = None
) -> str:
    """Painot ``a`` (kuiva) ja ``b`` (märkä) tasoittain, ja sopiiko kahden osan malli."""
    lines = [
        "| level | dry weight | wet weight | residual after fit |",
        "|---|---|---|---|",
    ]
    for level in sorted(fits):
        a, b, residual = fits[level]
        lines.append(f"| {level:g} | {a:.2f} | {b:.2f} | {residual:.1f} dB |")
    limit = LINEAR_DB if control is None else max(LINEAR_DB, control + 3.0)
    ok = all(residual < limit for _, _, residual in fits.values())
    if ok:
        verdict = (
            f"A two-component blend explains every level (residual below {limit:.0f} dB): "
            "the weights above are the Mix law, and one 100 % render can serve a "
            "continuous slider by that law."
        )
    else:
        verdict = (
            f"Not a two-component blend: some level stays above {limit:.0f} dB after "
            "the best fit, so the wet part itself changes with Mix and one render "
            "is not enough."
        )
    return "\n".join([*lines, "", verdict])


def format_preroll(
    residuals: dict[float, float], settled: float | None, control: float | None = None
) -> str:
    lines = ["| preroll | residual vs longest |", "|---|---|"]
    for preroll in sorted(residuals):
        lines.append(f"| {preroll:g} s | {residuals[preroll]:.1f} dB |")
    limit = LINEAR_DB
    if control is not None:
        lines.append(f"| repeat of the longest | {control:.1f} dB |")
        limit = max(LINEAR_DB, control + 3.0)
    if settled is None:
        verdict = "No shorter preroll settled: use at least the longest tried."
    else:
        verdict = f"Settled from {settled:g} s (residual below {limit:.0f} dB"
        verdict += ", repeat noise + 3 dB)." if limit > LINEAR_DB else ")."
    return "\n".join([*lines, "", verdict])


def format_timing(rows: dict[int, float], values: int, seconds: float) -> str:
    lines = [
        f"| workers | batch of {values} values | per value |",
        "|---|---|---|",
    ]
    for workers in sorted(rows):
        lines.append(
            f"| {workers} | {rows[workers]:.1f} s | {rows[workers] / values:.1f} s |"
        )
    lines += ["", f"Window: {seconds:g} s."]
    return "\n".join(lines)


def _load_instances(path: str, state: str | None, count: int) -> list:
    """Kaikki instanssit pääsäikeessä: pedalboard sallii latauksen vain siellä."""
    from speechmix import chain

    return [chain.load_plugin(path, None, state) for _ in range(count)]


def _mix_param_default(path: str) -> str | None:
    from speechmix import chain

    specs, _ = chain.parameter_specs(path)
    for spec in specs:
        if "mix" in str(spec.get("name", "")).lower():
            return spec["name"]
    return None


def main(argv: list[str] | None = None) -> int:
    import soundfile as sf

    from speechmix import chain

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio")
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--state", help="tiedosto, jossa liitännäisen tila base64:nä")
    parser.add_argument("--start", type=float, required=True, help="sekuntia")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument(
        "--mix-param", help="Mix-säätimen nimi (oletus: ensimmäinen 'mix')"
    )
    parser.add_argument(
        "--values", default="25,50,75", help="osittaiset Mix-arvot, yksiköissä"
    )
    parser.add_argument("--full", type=float, default=100.0, help="täyden ajon Mix")
    parser.add_argument(
        "--preroll",
        type=float,
        default=8.0,
        help="esiaika A0:lle ja kelloille (A1:n lista on erikseen)",
    )
    parser.add_argument("--prerolls", default="0,2,4,8,16")
    parser.add_argument("--workers", default="1,2,4")
    parser.add_argument(
        "--only-a0",
        action="store_true",
        help="vain A0 (Mixin laki): ei esiaikaa eikä kelloa, nopea tiheälle --values-listalle",
    )
    args = parser.parse_args(argv)

    param = args.mix_param or _mix_param_default(args.plugin)
    if not param:
        print("No Mix parameter found; pass --mix-param.", file=sys.stderr)
        return 2
    state = None
    if args.state:
        with open(args.state, encoding="ascii") as handle:
            state = handle.read().strip()

    values = [float(v) for v in args.values.split(",")]
    prerolls = sorted(float(v) for v in args.prerolls.split(","))
    worker_counts = [int(v) for v in args.workers.split(",")]
    end = args.start + args.seconds

    info = sf.info(args.audio)
    rate = info.samplerate
    first = int(max(0.0, args.start - max(*prerolls, args.preroll)) * rate)
    last = int((end + DEFAULT_TAIL) * rate)
    data, _ = sf.read(args.audio, start=first, stop=last, dtype="float32", always_2d=True)
    # Ikkunan origo: luettu pala alkaa `first`:stä, joten ajat suhteutetaan siihen.
    offset = first / rate
    audio = data.T
    start, stop = args.start - offset, end - offset

    # A0: yksi instanssi per arvo (+ täysi + kuiva)
    levels = [*values, args.full]
    instances = _load_instances(args.plugin, state, len(levels) + 1)
    dry_plugin, level_plugins = instances[0], instances[1:]
    preroll = args.preroll
    chain.apply_parameters(dry_plugin, {param: 0.0})
    # Jokainen ajo mitataan omalla viiveellään (ks. render_variants_full).
    dry, dry_lag = render_window(dry_plugin, audio, rate, start, stop, preroll)
    renders, lags, _ = render_variants_full(
        level_plugins,
        [{param: v} for v in levels],
        audio,
        rate,
        start,
        stop,
        preroll,
        workers=len(levels),
    )
    full = renders[-1]
    residuals = {
        v / args.full: linear_mix_residual_db(dry, full, renders[i], v / args.full)
        for i, v in enumerate(values)
    }
    fits = {v / args.full: fit_blend(dry, full, renders[i]) for i, v in enumerate(values)}
    # Kontrolli: sama asetus kahdesti. Ilman sitä jäännös voi olla pelkkää
    # liitännäisen omaa vaihtelua.
    control = repeat_residual_db(level_plugins[-1], audio, rate, start, stop, preroll)
    print("## A0: is Mix a linear dry/wet blend?\n")
    print(format_linearity(residuals, control), "\n")
    print("### Mix weights, best two-component fit (raw and 100 % render)\n")
    print(format_blend_fit(fits, control), "\n")
    print("### Delay per render (samples)\n")
    print("| render | delay |\n|---|---|")
    print(f"| 0 % (dry) | {dry_lag} |")
    for level, value in zip(levels, lags, strict=True):
        print(f"| {level:g} | {value} |")
    print()

    if args.only_a0:
        return 0

    # A1: esiaika, täydellä Mixillä, yksi instanssi
    plugin = level_plugins[-1]
    chain.apply_parameters(plugin, {param: args.full})
    by_preroll = {
        p: render_window(plugin, audio, rate, start, stop, p)[0] for p in prerolls
    }
    longest = by_preroll[max(by_preroll)]
    preroll_residuals = {
        p: residual_db(longest, by_preroll[p]) for p in prerolls if p != max(prerolls)
    }
    floor = repeat_residual_db(plugin, audio, rate, start, stop, max(prerolls))
    print("## A1: preroll\n")
    settled = settled_preroll(by_preroll, floor_db=floor)
    print(format_preroll(preroll_residuals, settled, control=floor), "\n")

    # A1: kello. Uudet instanssit joka kierrokselle, jotta lataus ei sotkeudu.
    timing: dict[int, float] = {}
    for workers in worker_counts:
        fresh = _load_instances(args.plugin, state, len(levels))
        _, seconds = render_variants(
            fresh,
            [{param: v} for v in levels],
            audio,
            rate,
            start,
            stop,
            preroll,
            workers=workers,
        )
        timing[workers] = seconds
    print("## A1: time\n")
    print(format_timing(timing, len(levels), args.seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
