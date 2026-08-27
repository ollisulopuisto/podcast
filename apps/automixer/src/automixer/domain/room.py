"""Mikit huoneessa: automixerin istunto kirjaston saumana.

`shared.py` on ketjun sauma — näytteitä sisään, näytteitä ulos. Tämä on
**päätöskerroksen** sauma, ja se puuttui kokonaan. Sen puuttuminen jätti
tekemättä kolme asiaa jotka olivat kirjastossa valmiina:

* **vaimennus** — toisen mikin sulkeminen kun sen omistaja on hiljaa,
* **ristivuodon vähennys** — sama ääni toisessa mikissä, muutama
  millisekunti myöhemmin, eli kampasuodin summassa,
* **tasonkuljettaja** — hidas tasoitus ennen kompressoreita.

`SPEECHMIX-INVENTORY.md` kirjasi syyn kahdesti: «tarvitsee puheruudukon, eikä
automixerilla ole mikrofoneja joista sellaista rakentaa». Havainto oli oikea
ja johtopäätös väärä. Mikrofoneja on — jokainen `type: speech` -raita on
yhden ihmisen mikki — ne ovat vain wav-tiedostoja aikajanalla eivätkä FCPXML:n
kulmia. `speechmix.session` on se muoto jota kirjasto pyytää, ja koko muunnos
siihen on `listen`: nimi, näytteet ja alkuhetki.

## Miksi tässä ei ole yhtään laskentaa

Kaikki mitä alla tehdään on kirjaston kutsumista. Se on tarkoitus: se on sama
koodi jonka autoraffkat ajaa, joten mitattu korjaus autoraffkatin puolella
tulee tänne samassa commitissa ilman että kukaan siirtää sitä. Kopio ei kaadu
koskaan — se alkaa vain hiljaa erota, ja juuri niin automixer oli neljä
mitattua korjausta jäljessä kun se sulautettiin tähän repositorioon.

## Eikä mlx:ää

Ruudukko on numpyä ruudukon päällä ja vuodon vähennys scipyn FFT:tä. Kumpikaan
ei ole näytönohjaimen työtä, ja mlx-vapaana tämä moduuli on testattavissa myös
siellä missä mlx:ää ei ole. Muunnos mlx:ään tehdään `shared.py`:ssä, kerran.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from speechmix import chain, debleed, detect, envelopes, masks, session


@dataclass
class Mic:
    """Yksi puheraita: kenen mikki, mitä siinä on ja mistä se alkaa.

    ``samples`` on monoa. Kaksikanavainen mikki rikkoo laskennan useassa
    kohtaa hiljaa — vuodon vähennys katsoo vain ensimmäistä kanavaa ja
    panorointi on monolähteen käsite — ja `Track.read` summaa jo monoksi.
    """

    name: str
    samples: np.ndarray
    start_sec: float = 0.0
    path: str = ""
    sensitivity_db: float = detect.SENSITIVITY_DB
    gain_db: float = 0.0


@dataclass
class DuckSettings:
    """Mitä ``masks.duck_masks`` ja ``envelopes.duck_envelopes`` lukevat.

    Numerot **eivät** ole tässä kirjoitettuina auki: ne ovat mitattuja ja
    kirjaston omia (``masks.DUCK_DB`` ja sisarensa), ja irrallaan niistä ne
    olisivat vain lukuja jotka voivat erota autoraffkatin luvuista ilman että
    mikään kertoo eroa. Sama kuvio kuin `SpeechSettings`illä.
    """

    duck: bool = True
    duck_db: float = masks.DUCK_DB
    duck_lookahead: float = masks.DUCK_LOOKAHEAD
    duck_hold: float = masks.DUCK_HOLD
    duck_min_open: float = masks.DUCK_MIN_OPEN
    duck_dominance_db: float = masks.DUCK_DOMINANCE_DB
    duck_fade: float = masks.DUCK_FADE
    duck_release: float = masks.DUCK_RELEASE
    duck_min_closed: float = masks.DUCK_MIN_CLOSED


@dataclass
class Room:
    """Mikit aikajanalla ja niistä rakennettu ruudukko.

    Ohjelman alku on nolla: automixerin istunnossa aikajana alkaa siitä mistä
    se alkaa, eikä ohjelmaa rajata erikseen kuten monikamerassa.
    """

    rate: int
    tracks: dict[str, session.Track]
    grid: detect.Grid
    samples: dict[str, np.ndarray] = field(default_factory=dict)
    program_start: float = 0.0

    def samples_of(self, name: str) -> np.ndarray:
        return self.samples[name]

    def duck_envelopes(self, settings: DuckSettings) -> dict[str, list]:
        """Vaimennus käyränä: ``{puhuja: [(aika, dB), …]}``.

        Aikajanan aikaa, kuten autoraffkatilla. `duck_gain` muuttaa sen
        näytteiksi — se on ainoa ero isäntien välillä.
        """
        return envelopes.duck_envelopes(self.grid, settings, self.program_start)

    def duck_gain(self, name: str, points, frames: int) -> np.ndarray:
        """Käyrä tämän raidan näytteiden kertoimiksi, koko tiedoston pituudelta.

        Ykkösiä silloin kun puhujalle ei syntynyt käyrää: raita menee summaan
        sellaisenaan. Yhden alkion taulukko riittää siihen, koska se
        levittyy — eikä koko ohjelman mittaista ykköstaulukkoa kannata varata.
        """
        return envelopes.envelope_gain(
            self.tracks.get(name), points, 0, frames, self.rate
        )

    def solo_masks(self) -> dict:
        """Jaksot joissa **vain** tämä puhuja on äänessä.

        Vuodon estimointi tarvitsee juuri nämä: muualta estimoitu suodin
        vähentäisi kohteen omaa puhetta.
        """
        return masks.solo_masks(self.grid)

    def speech_masks(self) -> dict:
        """Puhuja -> milloin hän on äänessä."""
        return masks.speech_masks(self.grid)

    def own_speech(self, name: str, block: int, count: int):
        """Tasonkuljettajan maski: puhuiko tämän raidan omistaja tässä lohkossa.

        ``None`` jos puhujaa ei ole ruudukossa — silloin `chain.process`
        ohittaa vaiheen sen sijaan että arvaisi signaalista. Signaalista
        pääteltynä puolet «puheesta» olisi toisen vuotoa: mitattuna
        heuristiikka kutsui 74 % lohkoista puheeksi kun 53 % oli omaa, ja
        kuljettaja nosti vuotoa niin että tasonvaihtelu **huononi**.
        """
        mask = self.speech_masks().get(name)
        track = self.tracks.get(name)
        if mask is None or track is None:
            return None
        return session.mask_blocks(
            track, mask, self.program_start, self.rate, block, count
        )

    def rider_blocks(self, name: str, frames: int):
        """`own_speech` ketjun omalla lohkokoolla. Tätä `chain.process` odottaa."""
        block = max(1, int(chain.RIDER_BLOCK_S * self.rate))
        return self.own_speech(name, block, frames // block)

    def debleed(self, name: str, audio, sources: dict) -> tuple[np.ndarray, list[str]]:
        """Vähentää muiden mikkien vuodon ``audio``:sta.

        Yksi lähde kerrallaan ja aina tuoreimmasta tuloksesta: kun kolmas
        puhuja vuotaa kahteen muuhun, ensimmäisen vähennyksen jälkeen jäljellä
        oleva ei ole enää sama signaali kuin alussa.

        **Tämä ajetaan raa'alla äänellä ennen liitännäistä.** Liitännäinen on
        generatiivinen: se ei säilytä raitojen välistä lineaarista suhdetta, ja
        sen jälkeen vuotoa ei enää voi vähentää millään suotimella.

        Palauttaa ``(tulos, syyt)``. Hylätty suodin ei ole hiljainen: asetus
        päällä ja lopputuloksessa ei mitään on tämän projektin toistuva vika,
        ja siksi syy tulee ulos eikä vain lokiin.
        """
        notes: list[str] = []
        target = np.asarray(audio, dtype=np.float64).reshape(-1)
        frames = target.size
        solos = self.solo_masks()
        mine = solos.get(name)
        me = self.tracks.get(name)
        if mine is None or me is None:
            return np.asarray(audio), notes
        solo_target = session.mask_samples(
            me, mine, self.program_start, self.rate, frames
        )
        for other, samples in sources.items():
            theirs = solos.get(other)
            partner = self.tracks.get(other)
            if theirs is None or partner is None:
                continue
            if not session.overlaps(me, partner):
                continue  # eri kohta aikajanaa: ei yhtään yhteistä hetkeä
            source = session.aligned(me, partner, samples, self.rate, frames)
            solo_source = session.mask_samples(
                partner, theirs, self.program_start, self.rate, frames
            )
            target, info = debleed.remove(
                target, source, self.rate, solo_source, solo_target
            )
            if info["reason"]:
                notes.append(f"{other}: {info['reason']}")
        return target.astype(np.asarray(audio).dtype, copy=False), notes


def listen(mics: list[Mic], rate: int) -> Room:
    """Mikit ruudukoksi. Tämä on koko muunnos automixerin istunnosta.

    Ruudukko kattaa ohjelman viimeisen mikin loppuun asti, jotta raita joka
    alkaa myöhemmin osuu siihen kohtaan johon väylä sen summaa. Verhokäyrä
    lasketaan niistä näytteistä jotka on jo luettu — ffmpegiä ei tarvita,
    koska wav on muistissa.
    """
    seen = [mic.name for mic in mics]
    doubled = sorted({name for name in seen if seen.count(name) > 1})
    if doubled:
        # Kaikki alla avaimetaan puhujan nimellä. Törmäys ei kaataisi mitään:
        # toinen mikki jäisi pois ruudukosta, vaimennus laskettaisiin väärästä
        # parista, eikä siitä sanottaisi mitään.
        raise ValueError(f"kaksi raitaa samalla nimellä: {', '.join(doubled)}")
    tracks = {
        mic.name: session.whole_file(
            mic.path, mic.name, start=mic.start_sec,
            duration=len(mic.samples) / rate,
        )
        for mic in mics
    }
    end = max((float(t.timeline_end) for t in tracks.values()), default=0.0)
    n = int(end / masks.HOP)
    grid = detect.grid_for(
        {
            mic.name: [(
                tracks[mic.name],
                detect.rms_db(mic.samples, rate),
                mic.sensitivity_db,
                mic.gain_db,
            )]
            for mic in mics
        },
        0.0,
        n,
    )
    return Room(
        rate=rate,
        tracks=tracks,
        grid=grid,
        samples={mic.name: np.asarray(mic.samples) for mic in mics},
    )
