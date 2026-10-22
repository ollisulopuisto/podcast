"""Lippujen sallitut välit, ilman miksausketjua.

``cli_mix`` tarkistaa liput argparsen tyyppeinä, joten virheellinen arvo
pysäytetään ennen kuin mitään raskasta tuodaan. Tarkistukset olivat
``stems_mix``issa, jonka tuonti tuo ketjun ja ``scipy``n: pelkkä
``--bed-under-speech-db 99`` -virhe maksoi sen. ``stems_mix`` käyttää näitä
samoja ja antaa ne edelleen nimillään (``stems_mix.check_bed_offset``).
"""

from __future__ import annotations

#: Sallittu väli lipulle ``--bed-under-speech-db`` (dB käsitellyn puheen
#: suhteen). Alaraja: pohja kuuluu vielä; yläraja: selvästi puheen päällä.
BED_OFFSET_RANGE = (-30.0, 6.0)


def check_bed_offset(value) -> float:
    """Pohjan taso puheeseen nähden liukulukuna, tai ``ValueError`` jos se ei kelpaa.

    ``nan`` ja äärettömät hylätään: ``nan`` ei ole minkään välin sisällä, ja ne
    muuttaisivat pohjan vahvistuksen ``nan``iksi ilman että mikään kaatuu.
    """
    number = float(value)
    low, high = BED_OFFSET_RANGE
    if not (low <= number <= high):  # NaN ei ole välillä
        raise ValueError(f"{value}: must be between {low:g} and {high:g} dB")
    return number


#: Sallitut välit puhujien tasauksen lipuille (dB). Ylärajat ovat selvästi
#: kaiken järkevän yli: raja 0 jättää käyttäjän tasot, suuri raja tasaa täysin.
BALANCE_MAX_RANGE = (0.0, 60.0)
BALANCE_TOLERANCE_RANGE = (0.0, 30.0)


def _checked(value, flag: str, low: float, high: float) -> float:
    number = float(value)
    if not (low <= number <= high):  # NaN ei ole välillä
        raise ValueError(f"{flag}: {value} must be between {low:g} and {high:g} dB")
    return number


def check_balance_max(value) -> float:
    """``--balance-speakers-max-db`` liukulukuna, tai ``ValueError``."""
    return _checked(value, "--balance-speakers-max-db", *BALANCE_MAX_RANGE)


def check_balance_tolerance(value) -> float:
    """``--balance-speakers-tolerance-db`` liukulukuna, tai ``ValueError``."""
    return _checked(value, "--balance-speakers-tolerance-db", *BALANCE_TOLERANCE_RANGE)
