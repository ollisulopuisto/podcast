"""Settings shared by mlx and disk based mixing routes."""

from dataclasses import dataclass

from speechmix import chain

HIGH_PASS_HZ = chain.HIGH_PASS_HZ


@dataclass
class SpeechSettings:
    """Mitä jaettu ketju lukee. Oletukset ovat kirjaston omat.

    `chain.process` on ankkatyypitetty: se lukee näitä nimiä eikä tiedä
    mistä ne tulevat. Numerot eivät ole tässä kirjoitettuina auki -- ne on
    viritetty yhdessä kynnysviitteen, suhteiden ja aikojen kanssa, ja
    irrallaan niistä ne voivat erota autoraffkatin numeroista ilman että
    mikään kertoo eroa.
    """

    high_pass_hz: float = HIGH_PASS_HZ
    peak_threshold_db: float = chain.PEAK_THRESHOLD_DB
    leveler_threshold_db: float = chain.LEVELER_THRESHOLD_DB
    declick: bool = True
    declick_sensitivity: float = 0.5
    # Tasonkuljettaja tarvitsee puhemaskin, jonka `domain/room.py` rakentaa
    # automixerin omista raidoista. Ilman maskia `chain.process` ohittaa
    # vaiheen eikä arvaa signaalista: mitattuna tasoheuristiikka kutsui 74 %
    # lohkoista puheeksi kun 53 % oli omaa, ja kuljettaja nosti vuotoa.
    rider: bool = True
