"""Kirjaston testit eivät saa riippua siitä kuka sattui tuomaan mitä.

``messages.set_translator`` on prosessin laajuinen, kuten gettextissä. Osa
tämän paketin testeistä tuo autoraffkatin sisään päästäkseen sen ``mix``iin
(``test_debleed``), ja **tuonti rekisteröi kääntäjän** — autoraffkatin
``i18n.py`` tekee sen itsestään. Sen jälkeen kirjaston viestit tulevat ulos
suomeksi, ja jokainen testi joka väittää jotain viestin tekstistä alkaa
riippua ajojärjestyksestä: yksin vihreä, sarjassa punainen.

Se ei kaatanut mitään ennen kuin viesteistä alettiin väittää. Vika oli silti
jo siellä, ja tämä on sen paikka: kirjaston oletus on englanti, ja isännän
kääntäjä on isännän testien asia.
"""

import pytest

from speechmix import messages


@pytest.fixture(autouse=True)
def _library_speaks_for_itself():
    messages.set_translator(None)
    yield
    messages.set_translator(None)
