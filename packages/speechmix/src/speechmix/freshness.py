"""Mikä tekee käsitellystä tiedostosta vanhentuneen.

«Ajan tasalla» on sormenjälki, ei muokkausaika. Käsitelty tiedosto joka on
lähdettään uudempi ei todista mitään: liitännäinen, sen säätimet, tavoitetaso
ja vaimennuksen syvyys eivät koske lähteeseen. Pelkkien aikojen vertailu sai
painikkeen ohittamaan jokaisen tiedoston ja palaamaan ennen ensimmäistä
lokiriviä — erottamattomana rikkinäisestä painikkeesta.

Kentät ja versio kuvaavat **mitä ketju tekee**, joten ne kuuluvat ketjulle.
*Missä leima sijaitsee* on sovelluskohtaista ja jää isännälle. Väärin päin
jokainen sovellus keksii oman käsityksensä ajantasaisuudesta, ja se on tämän
projektin toistuvin vikaluokka.

Siirretty autoraffkatin ``audio/mix.py``:stä, ei kopioitu.
"""

# Asetukset joista lopputulos riippuu. ``enabled`` ja ``room_track``
# päättävät tehdäänkö työtä lainkaan, eivät miltä tulos kuulostaa, joten ne
# eivät ole mukana. Lista on tahallaan kirjoitettu auki eikä johdettu
# kentistä: uusi säädin ei saa livahtaa mukaan tai pois huomaamatta, ja
# ``test_fingerprint_covers_every_setting`` kaatuu jos niin käy.
FINGERPRINT_FIELDS = (
    "high_pass_hz",
    "target_lufs",
    "peak_threshold_db",
    "leveler_threshold_db",
    "rider",
    # Kuljettajan alue on **mukana**, toisin kuin jakelutaso: se muuttaa
    # tiedostoon kirjoitettua ääntä, joten sen muuttaminen vanhentaa stemit.
    "rider_max_db",
    "declick",
    "declick_sensitivity",
    "plugin_path",
    "plugin_params",
    # Vaimennuksen luvut **eivät** ole tässä, ja se on tarkoitus: ne eivät
    # enää kosketa tiedostoon vaan menevät vientiin käyränä. Vaimennuksen
    # syvyyden muuttaminen on siis ilmaista — vie uudestaan, älä käsittele.
    "gain_db",
    "room_db",
    "program_target",
    "plugin_workers",
    "debleed",
    "plugin_state",
)

# Kasvatetaan kun ketju itse muuttuu niin että vanha tulos ei enää vastaa
# samoilla asetuksilla syntyvää. Sama tarkoitus kuin verhokäyrän
# ``CACHE_VERSION``:illa.
#
# 8: ristivuoto ratkeaa myös pitkissä osissa.
# 7: tasonkuljettaja ennen kompressoreita.
# 6: vaimennusta ei enää polteta tiedostoon.
# 5: ketjun kolmas kompressori oli kuollut ja on nyt elossa.
# 4: liitännäisen oma tila on osa lopputulosta.
# 3: ristivuodon vähennys ajetaan ennen liitännäistä.
# 2: naksunpoiston kynnys. Vanhat tiedostot on tehty detektorilla joka
#    korjasi 2 % kaikista näytteistä; ne eivät ole ajan tasalla millään
#    asetuksella, ja ilman tätä painike olisi kertonut päinvastaista.
FINGERPRINT_VERSION = 8
