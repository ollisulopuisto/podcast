"""Vaimennuksen asetukset ja esivalinnat."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Settings:
    """Mitä vaimennus tekee.

    ``tail``: kuinka paljon puhetta jätetään ympärille. Sanan aikaleima on
    sanan reuna, ja tarkalleen reunasta katkaistu puhe kuulostaa katkaisulta —
    hengitys ja sanan häntä ovat osa sitä.

    ``gap``: kuinka lyhyt tauko jätetään sulkematta. Sanaväli on kymmenesosia;
    jos jokainen niistä vaiennettaisiin, raita naksuisi joka sanan välissä.

    ``rms`` ja ``threshold``: tarkistetaanko sanan kohdalta myös äänen taso.
    Kun mikit vuotavat toisiinsa, Whisper kuulee naapurin puheen myös tästä
    mikistä ja merkitsee sen sanaksi. Taso erottaa oman puheen vuodosta,
    puhuttua tekstiä ei.
    """

    tail: float = 0.4
    gap: float = 0.4
    rms: bool = False
    threshold: float = -35.0

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Settings":
        raw = raw or {}
        base = cls()
        return cls(
            tail=_clamp(_number(raw.get("tail"), base.tail), 0.0, 5.0),
            gap=_clamp(_number(raw.get("gap"), base.gap), 0.0, 5.0),
            rms=bool(raw.get("rms", base.rms)),
            threshold=_clamp(_number(raw.get("threshold"), base.threshold), -80.0, 0.0),
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
    "remote": Settings(tail=1.0, gap=1.0, rms=False, threshold=-35.0),
    "bleed": Settings(tail=0.4, gap=0.4, rms=True, threshold=-35.0),
}

DEFAULT_PRESET = "remote"
