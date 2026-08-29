"""Vaimennuksen asetukset ja esivalinnat."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from speechmix import grid, masks


@dataclass
class Settings:
    """Mitä vaimennus tekee.

    ``tail``: kuinka paljon puhetta jätetään ympärille. Sanan aikaleima on
    sanan reuna, ja tarkalleen reunasta katkaistu puhe kuulostaa katkaisulta —
    hengitys ja sanan häntä ovat osa sitä.

    ``gap``: kuinka lyhyt tauko jätetään sulkematta. Sanaväli on kymmenesosia;
    jos jokainen niistä vaiennettaisiin, raita naksuisi joka sanan välissä.

    ``rms`` ja ``sensitivity``: tarkistetaanko sanan kohdalta myös äänen taso.
    Kun mikit vuotavat toisiinsa, Whisper kuulee naapurin puheen myös tästä
    mikistä ja merkitsee sen sanaksi. Taso erottaa oman puheen vuodosta,
    puhuttua tekstiä ei — sama sana kuuluu molemmilla raidoilla, eikä
    litteroinneista löydy edes samaa merkkijonoa vertailtavaksi.

    ``sensitivity`` on desibeleitä **raidan oman pohjakohinan yli**, ei
    absoluuttinen kynnys. Kiinteä −35 dBFS tarkoitti eri asiaa jokaisella
    mikillä, koska se liikkuu esivahvistuksen mukana: hiljaiseksi ajettu mikki
    menetti oikeaa puhetta ja kohiseva päästi vuodon läpi. Pohja mitataan
    raidasta itsestään, joten sama asetus tarkoittaa samaa joka mikillä.
    Luku tulee kirjastosta (``grid.FLOOR_MARGIN_DB``) eikä tästä.

    Mitattuna jaksolla ``vst s13e01`` (4 raitaa, 9 412 sanaa): kiinteä
    −35 dBFS vaiensi 18–39 % sanoista raidasta riippuen, pohja + 12 dB
    2,6–7,6 %. Hiljaisimman mikin pohja oli −93 dB, eli 58 dB kiinteän
    kynnyksen oletuksen alapuolella.

    ``dominance``: kuinka monta desibeliä hiljempaa kuin sillä hetkellä kovin
    raita sana saa olla ja silti olla omaa puhetta. Tämä ratkaisee sen mitä
    ``sensitivity`` ei ratkaise. Hiljaisessa studiossa hyvillä mikeillä vuoto
    ei ole hiljaista vaan *hiljaisempaa*: autoraffkatissa mitattuna molemmat
    mikit ylittävät kynnyksen 41 % ajasta, mutta vuoto on mediaanissa
    12,8 dB hiljempaa kuin sama puhe omalla mikillä. Absoluuttinen taso
    liikkuu jokaisen mikin esivahvistuksen mukana; raitojen välinen ero ei.

    Kaista eikä «kovin voittaa»: 6 dB jättää mitatusta 12,8 dB:n erosta noin
    6,8 dB pelivaraa, ja päästää päällekkäisen puheen läpi. Kova sääntö
    «vain yksi kerrallaan» leikkaisi keskeytykset ja naurut, eli juuri sen
    mikä tekee keskustelusta keskustelun. ``0`` on sääntö pois päältä — se
    on eri asia kuin nollan desibelin kaista.
    """

    tail: float = 0.4
    gap: float = 0.4
    rms: bool = False
    sensitivity: float = grid.FLOOR_MARGIN_DB
    # Sama luku kuin maskeilla, samasta mittauksesta: sama päätös samasta
    # äänestä pitää tehdä samoin, ja nyt myös samasta paikasta luettuna.
    dominance: float = masks.DUCK_DOMINANCE_DB

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Settings":
        raw = raw or {}
        base = cls()
        return cls(
            tail=_clamp(_number(raw.get("tail"), base.tail), 0.0, 5.0),
            gap=_clamp(_number(raw.get("gap"), base.gap), 0.0, 5.0),
            rms=bool(raw.get("rms", base.rms)),
            sensitivity=_clamp(
                _number(raw.get("sensitivity"), base.sensitivity), 0.0, 24.0
            ),
            dominance=_clamp(_number(raw.get("dominance"), base.dominance), 0.0, 60.0),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# Esivalinnat Colab-muistikirjasta. Nimet kertovat äänitystilanteen, koska
# se on se mitä käyttäjä tietää — ei se, mikä liukusäädin pitäisi mihinkin
# asentoon vetää.
PRESETS: dict[str, Settings] = {
    # Etäjakso: jokaisella oma huone, joten vuotoa ei ole eikä vertailtavaa.
    # `dominance` on silti oletuksessaan eikä nollassa, samasta syystä kuin
    # `sensitivity`: molemmat ovat `rms`:n takana, joten kumpikaan ei tee tässä
    # mitään. Nolla erottaisi tämän oletuksesta, ja vanha levylle tallennettu
    # «remote» — jossa kenttää ei ole lainkaan — lakkaisi täsmäämästä ja
    # näkyisi «omana». Mikään ei olisi muuttunut paitsi se mitä ruudulla lukee.
    "remote": Settings(tail=1.0, gap=1.0, rms=False),
    # Sama huone: tässä vertailu raitojen välillä on koko ratkaisu.
    "bleed": Settings(tail=0.4, gap=0.4, rms=True),
}

DEFAULT_PRESET = "remote"
