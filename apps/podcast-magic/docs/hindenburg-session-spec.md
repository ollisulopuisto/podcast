<!-- Tämä dokumentti muutti `hindenburg-helpers`-repositoriosta 2026-08-30.
     Se on `nhsx/read.py`:n esi-isi ja kuvailee datamallin oikein: sanojen
     aika on tiedostoa, regionin `Offset` kertoo mistä kohtaa tiedostoa alue
     alkaa, ja aikajanalla sana on `Start + (s - Offset)`.

     Kaksi neuvoa siinä ei pidä paikkaansa. `xml.etree.ElementTree` on
     vaihdettu lxml:ään, koska Hindenburgin viennit ovat joskus
     nimiavaruudessa ja joskus eivät — suoralla tagilla haku löytää
     nimiavaruudellisesta tiedostosta nolla osumaa. Ja `34:46.400` on
     2086,4 sekuntia, ei millisekuntien päätyminen sekuntien paikalle —
     `nhsx/read.py`:n `time_to_seconds` on se laki jota tämä kuvailee. -->

## Speksifikaatio: Hindenburg XML -sessiotiedoston Ohjelmallinen Muokkaus

### 1. Tavoite

Tämän dokumentin tavoitteena on määritellä toimintalogiikka ja datamalli Python-ohjelmalle, joka pystyy automaattisesti muokkaamaan Hindenburg-sessiotiedostoja (.xml). Ensimmäinen toteutettava ominaisuus on **älykkäiden vaimennusten lisääminen**: ohjelma vaimentaa raidat, joilla ei ole puhetta, niiden aikaleikkeiden osalta, joilla toisella raidalla on puhetta.

### 2. Tiedoston Rakenne (Objektimalli)

Ohjelman tulee jäsentää XML-tiedosto ja luoda siitä sisäinen tietorakenne (objektimalli), joka on helppo käsitellä. Tässä keskeiset objektit ja niiden ominaisuudet:

* **`Session`**: Pääobjekti, joka sisältää koko projektin.
    * `audio_files`: Lista `AudioFile`-objekteja.
    * `tracks`: Lista `Track`-objekteja.
    * `markers`: Lista `Marker`-objekteja.

* **`AudioFile`**: Edustaa yhtä äänitiedostoa `<AudioPool>`-osiossa.
    * `id`: Tunnistenumero (esim. "1").
    * `name`: Tiedostonimi (esim. "Raita 1 2L.wav").
    * `duration`: Lähdetiedoston kokonaiskesto sekunteina.
    * `words`: Lista `Word`-objekteja transkriptiosta.

* **`Word`**: Edustaa yhtä sanaa `<Transcription>`-osiossa.
    * `text`: Sana itse (esim. "Tämähän").
    * `start_time`: Sanan alkamisaika lähdetiedostossa sekunteina (`s`-attribuutti).
    * `length`: Sanan kesto sekunteina (`l`-attribuutti).

* **`Track`**: Edustaa yhtä raitaa aikajanalla.
    * `name`: Raidan nimi (esim. "Olli").
    * `regions`: Lista `Region`-objekteja.

* **`Region`**: Edustaa yhtä leikettä (klippiä) raidalla.
    * `source_file_id`: Viittaus `AudioFile`-objektin `id`:hen (`Ref`-attribuutti).
    * `start_time`: Leikkeen alkamisaika **aikajanalla** sekunteina (`Start`-attribuutti).
    * `length`: Leikkeen kesto **aikajanalla** sekunteina (`Length`-attribuutti).
    * `offset`: Aloituskohta **lähdetiedostossa** sekunteina (`Offset`-attribuutti).
    * `muted`: Boolean-arvo (tosi/epätosi), joka kertoo, onko leike vaimennettu (`Muted`-attribuutti).

### 3. Toimintalogiikka: Hiljaisuuden Poisto ("Ducking")

Tämä prosessi toteutetaan neljässä vaiheessa:

#### Vaihe 1: Datan Jäsentäminen ja Mallintaminen
Lue XML-tiedosto ja luo yllä kuvatun kaltainen objektirakenne muistiin. Muunna kaikki aikaleimat (esim. "34:46.400") sekunneiksi (esim. 2086.4) käsittelyn helpottamiseksi.

#### Vaihe 2: Puheaktiviteetin Kartta (Speech Activity Map)
Tämä on logiikan ydin. Tarkoitus on luoda koko aikajanasta kartta, joka kertoo jokaisella ajanhetkellä, mitkä raidat ovat "äänessä".

1.  **Iteroi kaikkien `Track`-objektien läpi.**
2.  Jokaisen raidan sisällä, iteroi sen `Region`-objektien läpi.
3.  Jokaisen regionin kohdalla, hae vastaava `AudioFile` sen `source_file_id`:n perusteella.
4.  Käy läpi `AudioFile`-objektin `words`-lista. Laske jokaiselle sanalle sen **absoluuttinen alkamis- ja loppumisaika aikajanalla**:
    * `word_timeline_start = region.start_time + (word.source_start_time - region.offset)`
    * `word_timeline_end = word_timeline_start + word.length`
5.  Tallenna nämä aikavälit ja niihin liittyvä raidan nimi (`track.name`) listaan. Lopputuloksena on "puhekartta", esim:
    * `[ (aika_alku, aika_loppu, "Olli"), (aika_alku, aika_loppu, "Panu"), ... ]`

#### Vaihe 3: Leikkeiden Käsittely ja Vaimennus
Nyt kun tiedetään, kuka puhuu ja milloin, käydään kaikki leikkeet uudelleen läpi ja tehdään vaimennuspäätökset.

1.  **Iteroi kaikkien `Track`-objektien ja niiden `Region`-objektien läpi.**
2.  Määritä jokaiselle leikkeelle sen aikaväli: `region_start = region.start_time` ja `region_end = region.start_time + region.length`.
3.  Tarkista, onko kyseisellä leikkeellä itsellään lainkaan puhetta (onko sen `words`-listassa sanoja, jotka osuvat sen `offset`-aikavälille).
    * **Jos leikkeellä EI ole puhetta:**
        * Tarkista "puhekartasta" (Vaihe 2), puhuuko joku toinen samalla aikavälillä (`region_start`...`region_end`).
        * Jos puhuu, aseta leikkeen `muted`-arvoksi `True`.
    * **Jos leikkeellä ON puhetta:** Sitä ei vaimenneta. Tämä varmistaa, että päällekkäin puhutut kohdat säilyvät.

#### Vaihe 4: Uuden XML-tiedoston Kirjoittaminen
Kun kaikki leikkeet on käsitelty ja `muted`-attribuutit on asetettu, rakenna muokatusta objektimallista uusi XML-merkkijono ja tallenna se uuteen tiedostoon. Varmista, että tiedoston rakenne ja syntaksi pysyvät Hindenburgin vaatimusten mukaisina.

### 4. Python-toteutuksen Vinkkejä 🐍

* **XML-jäsennys**: Käytä Pythonin sisäänrakennettua `xml.etree.ElementTree`-kirjastoa. Se on tehokas ja sopii tähän tehtävään täydellisesti.
* **Oliomallinnus**: Luo Python-luokat (`class Track`, `class Region` jne.) vastaamaan yllä kuvattua datamallia. Tämä tekee koodista selkeämpää kuin pelkkien sanakirjojen (dictionary) käsittely.
* **Ajan käsittely**: Kirjoita apufunktiot, jotka muuntavat Hindenburgin aikamuodon (`HH:MM:SS.sss`) sekunneiksi ja takaisin. Tämä yksinkertaistaa laskutoimituksia huomattavasti.

### 5. Laajennusmahdollisuudet

Tämä sama perusrakenne mahdollistaa monia muita tehokkaita editointiautomaatioita:

* **Tekstipohjainen editointi**: Koska transkriptio on olemassa, voisit antaa komentoja kuten "Poista kaikki 'ööö'-sanat Karin raidalta". Ohjelma etsisi vastaavat `<w>`-elementit, laskisi niiden aikavälit ja leikkaisi ne pois muokkaamalla `<Region>`-elementtejä.
* **Automaattinen tasojen säätö**: Voitaisiin analysoida leikkeiden keskimääräinen äänenvoimakkuus ja säätää `Gain`-arvoja automaattisesti.
* **Musiikin automaattinen "dukkaus"**: Jos projektissa olisi musiikkiraita, samaa logiikkaa voisi käyttää musiikin vaimentamiseen aina, kun jollain puheraidalla on transkriptio.