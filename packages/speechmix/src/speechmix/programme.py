"""Ohjelmatason päätökset: katto ja trimmi summasta, ei yhdestä stemistä.

Molemmat korjaavat saman virheen kahdella eri suureella. Ketju takaa katon ja
tason **jokaiselle tiedostolle erikseen**, mutta isäntä soittaa niiden
**summan**, ja summa ei noudata kumpaakaan.

Tiedostojen lukeminen, paloittelu ja kirjoittaminen jäävät isännälle: ne ovat
istuntokohtaista I/O:ta. Täällä on se laskenta jonka pitää olla sama
riippumatta siitä kuka lukee tiedostot — ja ne kaksi sääntöä joita on helppo
rikkoa vahingossa: katto lasketaan summasta yhtenä käyränä, ja trimmi menee
**tavoitteeseen** eikä vahvistukseen.

Siirretty autoraffkatin ``audio/mix.py``:stä, ei kopioitu.
"""

import numpy as np

from . import chain

#: Palan pituus ja marginaali, kun summa lasketaan paloittain: koko ohjelma
#: muistissa olisi useita gigatavuja. Rajoittimen muisti on ennakko (5 ms) ja
#: palautus (120 ms), joten sekunnin marginaali on kertaluokkaa liikaa — ja
#: liikaa on tässä oikea suunta, koska palan raja ei saa näkyä.
CEILING_CHUNK = 60.0
CEILING_MARGIN = 1.0

#: Trimmin mittausikkuna. Koko ohjelman käsittely ensin maksaisi noin
#: viidenneksen lisää aikaa, ja ero on murto-osa desibeliä.
PROGRAM_WINDOW = 720.0

#: Trimmiä ei sallita rajattomasti: se on korjaus päällekkäisyyteen, ei toinen
#: normalisointi. Kuudesta desibelistä ylöspäin olisi kyse mittausvirheestä.
MAX_PROGRAM_TRIM = 6.0


def shared_gain(blocks, rate: int,
                ceiling_db: float = chain.CEILING_DB) -> np.ndarray:
    """Yksi rajoittimen käyrä stemien **summasta**.

    Tämä on koko korjaus yhtenä rivinä. Kaksi stemiä joiden huiput on
    molemmat painettu -1,5 dBTP:hen ylittävät täyden asteikon aina kun huiput
    osuvat samaan hetkeen — teoriassa +4,5 dB, oikealla jaksolla mitattuna
    **+4,51 dBFS, 200 ylityspursketta minuutissa**, mediaanipituus 0,23 ms.

    Korjaus ei ole kovempi rajoitus stemeittäin — silloin jokainen stemi
    maksaisi kuusi desibeliä crestiä sen takia mitä *toinen* tiedosto sattuu
    tekemään. Käyrä lasketaan summasta ja kerrotaan jokaiseen stemiin
    **samanlaisena**, jolloin summa noudattaa kattoa eikä puhujien tasapaino
    voi muuttua. Mitattuna +4,51 -> -1,51 dBFS ja hinta 0,50 LU.

    Idempotentti rakenteeltaan: käyrä on ``min(1, katto/huippu)``, joten
    summalle joka jo noudattaa kattoa se on ykkönen kaikkialla.

    ``ceiling_db`` on oletuksena ketjun oma stemikatto. Jakelussa se on eri
    luku: stemin katto jättää varaa summalle, ohjelman katto on se johon
    valmis miksaus rajataan.
    """
    total = None
    for block in blocks:
        total = block if total is None else total + block
    if total is None:
        raise ValueError("ohjelmakatto ilman stemejä")
    return chain.limiter_gain(total, rate, ceiling_db)


def reduction_db(gain: np.ndarray) -> float:
    """Käyrän suurin vaimennus desibeleinä (≤ 0). Nolla tarkoittaa ettei mitään tehty."""
    if gain.size == 0:
        return 0.0
    return float(20.0 * np.log10(max(float(gain.min()), 1e-9)))


def at_target(block: np.ndarray, rate: int, target_lufs: float):
    """Stemi sillä tasolla jolla se on aikajanalle tulossa, tai ``None``.

    ``block`` on **monoa**: äänekkyys mitataan yhdestä kanavasta, ja summa
    lasketaan monona. Katto sen sijaan on kanavatietoinen, ks. ``shared_gain``.

    Summa mitataan siitä mitä *tulee*, ei siitä mitä levyllä on nyt: käsittely
    normalisoi jokaisen mikin tavoitteeseen, joten sama nosto on tehtävä myös
    mittaukseen. ``None`` tarkoittaa ettei tämä mikki ole äänessä ikkunassa —
    toisen osan tiedosto tai hiljainen kohta. Se ei ole virhe eikä lisää
    summaan mitään.
    """
    measured = chain.loudness(block, rate)
    if measured is None:
        return None
    return block * float(10 ** ((target_lufs - measured) / 20))


def shared_backoff(backoffs) -> dict:
    """Sama peruutus jokaiselle stemille: ``{avain: lisävaimennus dB}`` (≤ 0).

    Budjetti lasketaan stemikohtaisesti, koska crest on puhujakohtainen —
    mitattuna toinen mikki tarvitsi 5,9 dB ja toinen ei mitään. Sellaisenaan
    sovellettuna se **siirtää puhujien tasapainoa**: mitattuna 1,1 dB:n ero
    kasvoi 5,9 dB:iin, eli ohjelman kovempi puhuja jäi yhtä tiivistetyksi ja
    hiljaisempi vain vaimeni. Se ei ole korjaus vaan uusi vika.

    Sama peruste kuin ``shared_gain``illa: käyrä lasketaan summasta ja
    kerrotaan jokaiseen stemiin **samanlaisena**. Tässä luku on vakio eikä
    käyrä, mutta sääntö on sama — eniten tarvitseva sanelee, ja kaikki
    seuraavat, jolloin taso siirtyy eikä tasapaino.

    **Tämä ei vielä riitä.** Peruutusten tasaaminen ei tasaa lopputulosta,
    koska ketjun hakusilmukka ajetaan vain niille stemeille joita budjetti ei
    sitonut: sidottu stemi jää siihen mihin budjetti sen jätti, sitomaton
    nostetaan tavoitteeseen. Mitattuna 6 dB:n budjetilla puhujien ero oli
    ilman tasausta 1,07 -> 5,90 dB ja tasauksen kanssa 1,07 -> 3,28 dB: kaksi
    kolmasosaa virheestä pois, kolmasosa jäljellä. Loppu vaatii että koko
    ohjelma päättää hakusilmukasta yhdessä — sidottu stemi tekee ohjelmasta
    sidotun — eikä sitä voi päättää yhtä stemiä katsomalla.
    """
    if not backoffs:
        return {}
    deepest = min(0.0, min(float(v) for v in backoffs.values()))
    return {key: round(deepest - min(0.0, float(v)), 2)
            for key, v in backoffs.items()}


#: Kuinka paljon jakelutason eteen saa nostaa. Rajaton nosto olisi sama vika
#: kuin rajaton rajoitin: hiljainen tai tyhjä mittausikkuna pyytäisi
#: kymmeniä desibelejä, ja jaettu käyrä maksaisi ne crestinä.
MAX_PROGRAM_BOOST = 12.0


def boost_to(summed: np.ndarray, rate: int, target_lufs: float | None,
             max_boost: float = MAX_PROGRAM_BOOST) -> float:
    """Kuinka paljon **summa** on jakelutason alla, desibeleinä (≥ 0).

    Stemin tavoite ja jakelun tavoite ovat eri asia, ja niiden sekoittaminen
    on koko tiivistysongelman juuri: -14 LUFS on jakelutason luku, ja
    stemiltä pyydettynä se vaatii crestin jota puheella ei ole. Summasta
    pyydettynä sama luku maksaa rajoitusta vain siellä missä huiput osuvat
    yhteen — ja sen hoitaa ``shared_gain``, sama jaettu käyrä joka pitää
    katon, eikä yksikään stemi maksa toisen puolesta.

    ``None`` tai nolla on pois päältä eikä nollaan normalisointia: jakelutaso
    on valinta, ja valitsematta jättäminen tarkoittaa että taso tulee
    stemeistä kuten ennenkin.
    """
    if not target_lufs:
        return 0.0
    measured = chain.loudness(np.asarray(summed).mean(axis=0)
                              if np.ndim(summed) > 1 else np.asarray(summed), rate)
    if measured is None:
        return 0.0
    return round(max(0.0, min(float(max_boost), float(target_lufs) - measured)), 2)


#: Kuinka nopeasti lyhytaikainen veto liikkuu. Kolme sekuntia on ikkunan oma
#: pituus: sitä nopeampi veto reagoisi ikkunan sisään eikä sen mittaamaan
#: asiaan, ja kuuluisi pumppauksena.
SHORT_TERM_GLIDE_SEC = 3.0


def short_term_ride(short_term_db, target_db: float,
                    step_sec: float,
                    glide_sec: float = SHORT_TERM_GLIDE_SEC) -> np.ndarray:
    """Vaimennus jolla lyhytaikainen äänekkyys mahtuu kattoonsa, dB (≤ 0).

    Hidas veto, ei rajoitin. Kolmen sekunnin ikkuna on kolme kertaluokkaa
    rajoittimen muistia pidempi, joten rajoittimella hoidettuna se söisi
    mikrodynamiikan koko sen ajan — juuri sen jonka takia taso ylipäätään
    tehdään summasta eikä stemeistä.

    Ylitys otetaan pois tasona ja käyrä pehmennetään ikkunan omalla
    pituudella: nopeampi veto reagoisi ikkunan **sisään** eikä sen
    mittaamaan asiaan, ja kuuluisi pumppauksena.

    Vain vaimennus. Katon alla olevaan ohjelmaan ei kosketa, koska tämä on
    raja eikä tavoite.
    """
    values = np.asarray(short_term_db, dtype=np.float64)
    if not values.size or not target_db:
        return np.zeros(values.shape)
    over = np.minimum(0.0, target_db - values)
    over[~np.isfinite(over)] = 0.0
    if not over.any():
        return np.zeros(values.shape)
    # Pehmennys molempiin suuntiin, jotta veto ehtii alkaa ennen ylitystä
    # eikä jää jälkeen sen jälkeen. Minimi ennen keskiarvoa: keskiarvo yksin
    # päästäisi huipun läpi puoliksi.
    span = max(1, int(round(glide_sec / max(step_sec, 1e-6))))
    pad = span
    padded = np.pad(over, pad, mode="edge")
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    held = minimum_filter1d(padded, size=2 * span + 1, mode="nearest")
    smooth = uniform_filter1d(held, size=2 * span + 1, mode="nearest")
    return np.minimum(0.0, smooth[pad : pad + values.size])


def short_term_lift(short_term_db, floor_db: float, step_sec: float,
                    max_lift: float,
                    glide_sec: float = SHORT_TERM_GLIDE_SEC) -> np.ndarray:
    """Nosto jolla hiljaiset jaksot yltävät lattiaansa, dB (≥ 0).

    ``short_term_ride``in duaali, ja se on tarkoituksella eri työkalu.
    Äänekkyyttä voi ostaa kahdella tavalla: painamalla huiput alas tai
    nostamalla pohjaa ylös. Ensimmäinen maksaa rajoitusta ja transientteja,
    toinen ei maksa rajoitusta lainkaan — hiljaisissa kohdissa on
    huippuvaraa, joten nosto ei kosketa kattoa.

    Vaihteluväli kapenee kummallakin tavalla. Ero on siinä **mitä** kuulee:
    litistetty transientti kuuluu tiivistyksenä, nostettu hiljainen jakso
    kuuluu siltä että se on lähempänä. Siksi kun tavoitteeseen ei päästä
    rajoitinbudjetin sisällä, loppu otetaan täältä eikä katosta.

    Nostolla on oma kattonsa: rajaton nosto veisi pohjakohinan mukanaan.
    """
    values = np.asarray(short_term_db, dtype=np.float64)
    if not values.size or not floor_db or max_lift <= 0:
        return np.zeros(values.shape)
    under = np.maximum(0.0, floor_db - values)
    under[~np.isfinite(under)] = 0.0
    under = np.minimum(under, max_lift)
    if not under.any():
        return np.zeros(values.shape)
    # Pehmennys kuten vedossa, mutta maksimi ennen keskiarvoa: keskiarvo
    # yksin jättäisi lyhyen hiljaisen kohdan puoliksi nostamatta.
    from scipy.ndimage import maximum_filter1d, uniform_filter1d

    span = max(1, int(round(glide_sec / max(step_sec, 1e-6))))
    padded = np.pad(under, span, mode="edge")
    held = maximum_filter1d(padded, size=2 * span + 1, mode="nearest")
    smooth = uniform_filter1d(held, size=2 * span + 1, mode="nearest")
    return np.clip(smooth[span : span + values.size], 0.0, max_lift)


def trim_to_target(summed: np.ndarray, rate: int, target_lufs: float,
                   max_trim: float = MAX_PROGRAM_TRIM) -> float:
    """Kuinka paljon mikkien summa on tavoitteen yli, desibeleinä (≤ 0).

    ``summed`` on **monoa**, ``at_target``in palauttamien osuuksien summa.

    Kaksi -14 LUFS:n mikkiä ei summaudu -14:ään: tällä aineistolla mitattu
    summa oli -12,3. Ero ei ole 3 dB (silloin molemmat puhuisivat koko ajan)
    eikä 0 dB (silloin toinen mikki olisi täysin hiljaa toisen puhuessa),
    joten se mitataan eikä arvata.

    Palautettu luku kuuluu **tavoitteeseen**, ei vahvistukseen: ketju
    normalisoi tavoitteeseen viimeisenä työnään, joten vahvistukseen lisätty
    trimmi poistuu täsmälleen — ja lukema näyttää silti oikealta.
    """
    measured = chain.loudness(summed, rate)
    if measured is None:
        return 0.0
    trim = float(target_lufs - measured)
    return round(max(-abs(max_trim), min(0.0, trim)), 2)
