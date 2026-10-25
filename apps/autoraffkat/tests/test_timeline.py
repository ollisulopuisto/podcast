"""Aika elää `fcpxml`-paketissa; tämä moduuli on vain vanha tuontipolku.

Aikalaskennan väitteet (murtoluvut, kehykseen pyöristys, formaattinimet) ovat
paketin testeissä. Täällä väitetään vain, että polku johtaa samaan koodiin eikä
sen kopioon: kaksi määritelmää samalle ajalle on juuri se ajautuminen jota
yhteinen paketti on olemassa estämään.
"""

import inspect

import fcpxml.timeline as shared
import pytest

from autoraffkat import timeline as local


@pytest.mark.parametrize("name", local.__all__)
def test_the_import_path_leads_to_the_shared_definition(name):
    assert getattr(local, name) is getattr(shared, name)


def test_nothing_the_package_defines_is_missing_here():
    defined = {
        name
        for name, value in vars(shared).items()
        if inspect.isfunction(value) and value.__module__ == shared.__name__
    }
    assert defined <= set(local.__all__)
