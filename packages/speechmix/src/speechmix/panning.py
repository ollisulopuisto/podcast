"""Puhujien panorointi: kuinka leveälle, ja järjestyksen mukaan tasan.

Panorointi on **hyvin** hienovarainen. Kuulokkeilla kuunneltuna sitä ei
juuri huomaa, ja se on tarkoituskin: puhe kuuluu keskeltä, ja leveä
panorointi tekee kahden puhujan keskustelusta radiokuunnelman. Muutama
prosentti riittää antamaan kuvalle ja äänelle saman maantieteen.

Järjestys on isännän: autoraffkat mittaa istumajärjestyksen kuvasta,
automixer käyttää raitojen järjestystä. Leveys on yksi ja asuu täällä,
koska automixer levitti omalla luvullaan kolme kertaa leveämmälle.
"""

from __future__ import annotations

import numpy as np

# Kuinka leveälle puhujat levitetään, prosentteina (-100 = vasen, +100 =
# oikea; Final Cutin asteikko). Ensimmäinen luku on kahdelle puhujalle.
#
# Nämä eivät ole mitattuja lukuja vaan valittu yläraja: mitattavaa olisi
# «kuuluuko tämä», ja siihen vastaus on että ei juuri pidäkään. Leveys
# kasvaa puhujamäärän mukana vain sen verran että paikat pysyvät erillään.
PAN_WIDTH = {2: 6.0, 3: 8.0, 4: 10.0, 5: 12.0}

# Useampaa kuin viittä ei panoroida. Kuudella paikat ovat niin lähellä
# toisiaan ettei ero ole enää paikka vaan epätarkkuus, ja silloin keskeltä
# on parempi kuin melkein keskeltä.
PAN_MAX_SPEAKERS = 5


def spread(count: int) -> list[float]:
    """``count`` puhujan paikat vasemmalta oikealle, prosentteina.

    Tasavälit -leveys/2 … +leveys/2. Parittomalla määrällä keskimmäinen
    osuu nollaan itsestään, mikä on juuri haluttu: kolmesta yksi on
    keskellä eikä ketään siirretä turhaan.
    """
    if count < 2 or count > PAN_MAX_SPEAKERS:
        return [0.0] * max(0, count)
    width = PAN_WIDTH[count]
    return [round(float(v), 2) for v in np.linspace(-width / 2.0, width / 2.0, count)]
