"""Ruudukon askel on yksi luku, ja sen on oltava yksi olio.

Kaksi kappaletta samasta vakiosta ei kaada mitään. Ne vain ajautuvat
erilleen jonain päivänä, ja silloin verhokäyrä lasketaan yhdellä
askeleella ja päätös luetaan toisella: leikkaukset siirtyvät sitä enemmän
mitä pidemmälle aikajanalla mennään, eikä mikään kerro siitä. Juuri se
ajautuminen on syy jonka takia tämä paketti on olemassa.

``is`` eikä ``==``: yhtä suuret luvut on täsmälleen se tila josta tämä
alkaa, ja sen huomaa vain identiteetti.
"""

from speechmix import grid, masks


def test_there_is_one_hop():
    assert masks.HOP is grid.HOP_SEC


def test_the_hop_is_twenty_milliseconds():
    """20 ms: lyhyin ikkuna josta puheen RMS on vielä vakaa.

    Ja karkeampi kuin yksi äänihuulten jakso, joten yksittäinen pulssi ei
    käännä päätöstä. 50 arvoa sekunnissa, 180 000 tunnissa.
    """
    assert masks.HOP == 0.02
