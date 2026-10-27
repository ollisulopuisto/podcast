# colab-transcribe

Litterointi ja Auto-Silence Colabin näytönohjaimella: paikallinen ajuri,
pilvessä ajettava ketju.

Koodi, kommentit ja docstringit ovat **suomeksi** — ne ovat tekijöille.
Dokumentaatio ja käyttäjän näkemä teksti ovat suomeksi ja englanniksi
(käyttöliittymä tällä hetkellä suomeksi, kuten Colabissa ajettava skriptikin).

## Ladattava skripti on resurssi, ei työtilan koodia

`src/colabtranscribe/colab/pipeline.py` ei ole koodia jota tämä työtila
ajaisi: ajuri lataa sen `/content/pipeline.py`ksi ja Colabin Python ajaa
sen. Se ei voi tuoda `speechmix`ia eikä mitään muuta työtilasta — siksi se
on oma snapshotkinsa podcaust-magicin ketjusta ja **driftin vaara on
todellinen**. Kun jaettuun ketjuun tulee mitattu korjaus, tämä skripti ei
saa sitä automaattisesti; silloin se siirretään käsin ja kerrotaan
commitviestissä. Jos skriptin tuottama tulos alkaa erota podcaust-magicin
tuloksesta, syyn etsiminen aloitetaan tästä.

Siksi tämä sovellus ei myöskään seiso `apps/`issa sen enempää kuin se
ottaisi `speechmix`ia: se on juuressa `viewer/`in tapaan, mutta
pyproject.tomlilla, ja listattu eksplisiittisesti työtilan jäseneksi.

Poikkeus: `silencelearn` (ks. «Opittu kynnys ladataan, ei kopioida»). Se on
työtilan paketti, mutta ajuri lataa sen Colabiin tiedostona.

## Käsikirjoitus on snapshot, ja sen drift on testi

`pipeline.write_script` kirjoittaa valmiista istunnosta `.md`:n (puhujan
vuoro per kappale, raidan nimi puhujana). Se on kopio
podcast-magicin `script/core.py`:stä, koska Colabissa ajettava skripti ei voi
tuoda työtilaa. Driftin vaara on sama kuin muulla skriptillä, mutta tämän
kohdalla se on testattu: `test_the_snapshot_script_matches_podcast_magics`
ajaa samalle istunnolle molemmat ja vaatii täsmälleen saman tekstin. Jos
muotoilu muuttuu `script/core.py`:ssä, testi kaatuu tänne, ja muutos
siirretään käsin. Teksti syntyy Colabissa ja tulee alas muiden tulosten
mukana, joten paikallinen puoli ei muutu eikä saa uusia riippuvuuksia.

## Downmix on snapshot

`--source downmix` litteroi koko miksauksen kerran ilman puhujia ja palauttaa
`<nimi> downmix.md`:n. Miksaus on **vain gain-summaus**: `ClipGain` voittaa
`Gain`in, raidan `Volume` (dB) kerrotaan mukaan, mykistetyt raidat ja alueet
ohitetaan; panorointi, ramppi ja häivytys jätetään pois. Parakeet Ultra ottaa monon,
joten ne eivät tuo mitään.

Osio on käsin kopioitu neljästä lähteestä, eikä mikään commit tavoita sitä:
podcast-magicin `transcribe/downmix.py`, `packages/nhsx`:n `mix.py` ja
`read.locate` sekä podcast-magicin `nhsx/write.py`:n `paragraphs` (kynnys
1,2 s, enintään 80 sanaa). Driftin vaara on sama kuin muulla skriptillä.
Testi vartioi vain tekstiä: `test_downmix_text_matches_podcast_magics`
vertaa `paragraph_lines`ia alkuperäiseen. Gain-säännöt ja tiedostohaku ovat
pinnattu omilla testeillään mutta **ei** vertailtu alkuperäiseen, joten
muutos `mix.py`:ssä ei kaada mitään täällä — siirrä se käsin.

numpy tulee Colabin ASR-ympäristöstä. Ajuri kertoo
valmiin tiedoston `Käsikirjoitus luotu:` -rivillä; `.md` tulee alas koko
tulostekansion mukana, joten uutta `driver.parse_*`-markeria ei tarvita.

## Pelkkä ääni on kuulaksen rajapinta

`--source audio` (`--audio`/`--json`) ei ole sisäinen tila: tulostiedosto
`<nimi>.words.json`, `PROGRESS <0-100> <viesti>` -rivit, poistumiskoodit ja
SIGTERM ovat sopimus (`docs/KUULAS-COLAB.md`), jonka toisessa päässä on toinen
ohjelma. Siksi: sanat järjestetään ja `s < e` taataan `words_document`issa
(snapshot, ei muuta tilaa), edistymisluku ei laske eikä ylitä sataa, ja
`*.words.json` poistetaan ennen ajoa, koska muuten vanha tiedosto kelpaisi
puuttuvan uuden tilalle. Suunnitelma on `driver.plan_audio_commands`, ei
`plan_commands`: aina suora siirto, ei `silencelearn`ia. Äänitila ei tuota
`.nhsx`:ää, joten sen virheet näkyvät vain tiedostossa ja poistumiskoodissa.
Pilvipään ajoa ei ole kokeiltu oikealla Colabilla tässä ympäristössä.

`--events` (kuulaksen BUGS 107) on samaa sopimusta: rivit `@@kuulas <json>`
stdoutiin tekstirivien rinnalle, `schema` 1, kentät lisätään eikä nimetä
uudelleen (`docs/KUULAS-COLAB.md`, «Live events»). `events.py` on automixerin
`events.py`:n kopio, koska tämä sovellus ei tunne muita työtilan jäseniä;
etuliite ja muoto pidetään samoina käsin. Vaiheet tulevat kahdesta paikasta:
komennon alusta (`driver.stage_of`, siirroille `driver.upload_info`: nimi,
tavut, tapa) ja pilvipään riveistä (`driver.stage_of_line`, samat merkit kuin
`on_progress`illa, nimi rivin lopusta), ja `StageTrail` sulkee edellisen
vaiheen kun seuraava alkaa. Kaatuneessa ajossa vaihe jää auki, ja
`error`-tapahtuma kertoo sen; `error.message` on aina yksi rivi (`_one_line`,
enintään 200 merkkiä), ei loki. Siirron tavut ovat alkuperäisen tiedoston
myös FLACina lähetettäessä, ja ne kulkevat omalla `transfer`-tapahtumallaan,
ei uudella `stage`-tilalla: lukija joka tuntee vain `start` ja `done` ei saa
ottaa päivitystä vaiheen päättymiseksi. Colab CLI:n päivitysilmoitukset eivät
ole `progress.message` (`_COLAB_UPDATE`).

Kadonnut istunto korjataan työkalun sisällä (`run_audio_mode`): jos ajo kaatuu
ja Colab CLI sanoi istunnon kadonneen, istunto suljetaan, `session` kertoo
`reset`/`lost`, ja ajo tehdään kerran uudelleen tuoreella koneella. Toista
kertaa ei yritetä, eikä keskeytystä (130) tai muuta vikaa uusita. Tämä on
käytöstä myös ilman `--events`ia; kuulaksen oma uudelleenyritys jää varalle.
Kuulaksen toiveet ovat `docs/PODCAST-MAGIC.md`:ssä (kuulas-repo); kenttien
muoto on rakennettu niiden mukaan, mutta kuulas ei lue niitä vielä eikä
pilvipään ajoa ole kokeiltu oikealla Colabilla.

`--align` lataa Colabiin toisen yhden tiedoston, `wordalign.py`n
(`driver.ALIGN_MODULE`), samalla tavalla kuin `silencelearn`in. Kohdistin
ajetaan **omassa prosessissaan** ja torch omaan kansioonsa
(`pipeline.ALIGN_SITE`, `aligner_env`), jotta kohdistimen torch 2.8:n
riippuvuudet pysyvät erillään Photon-ASR:n ympäristöstä. Kohdistin
tarkistetaan ennen litterointia (`check_aligner`), ja jos mikään sana ei
kohdistu, ajo kaatuu: korjatuksi merkitty tiedosto, jossa on ASR:n aika, olisi
juuri se hiljainen vika. `ALIGN_TIMING` seuraa `wordalign.VERSION`ia testillä.

## Parakeet Ultra ja podcastin puheajat

Pilven ASR on Moondreamin Parakeet Ultra Photon-ajurilla (`moondream/parakeet-ultra`). Photon tukee
25 kieltä, niiden joukossa suomi, ja hoitaa pitkän äänen segmentoinnin sekä sanakohtaiset
aikaleimat. Mallin painot ladataan ensimmäisellä ajolla. Polku ajettiin oikealla T4-Colabilla
2026-10-27 synteettisellä suomenkielisellä äänellä: Photon latasi 1,26 Gt mallitiedostoja ja
kirjoitti seitsemän sanaa aikaleimoineen. Tämä on toimintatesti, ei tarkkuusmittaus.

Parakeet Ultra ei tue Whisperin `initial_prompt`ia eikä tässä toteutuksessa hotword-biasointia. `--prompt`
ja `--model` säilyvät vanhojen komentojen yhteensopivuuden vuoksi, mutta eivät vaikuta dekoodaukseen;
mukautetusta promptista annetaan varoitus. VAD ja jälkikäsittely eivät poista täytesanoja tai
peräkkäistoistoja. Whisperin vanhat laatumittaukset eivät päde tähän malliin. Ultra-polku on testattu paikallisilla
yksikkötesteillä ja lyhyellä oikean Colab T4 -ajolla; mallin podcast-tarkkuutta, pitkän äänen
toimivuutta tai suoritusnopeutta ei ole vielä mitattu tuotantoraidalla.

## Opittu kynnys ladataan, ei kopioida

`--preset learned` opettaa kynnyksen käsin vaimennetuista alueista, ja
laskenta on `packages/silencelearn`issa: **yksi tiedosto, pelkkä
standardikirjasto**. Ajuri lataa sen Colabiin skriptin viereen
(`driver.LEARN_MODULE` -> `/content/silencelearn.py`, kummassakin
siirtotavassa) ja skripti tuo sen `calibrate_tree`ssä; `/content` on skriptin
`sys.path`issa, koska se ajetaan sieltä. podcast-magic tuo saman tiedoston,
joten kopiota ei ole eikä sen driftiä tarvitse vartioida.

Tämä on ainoa osa skriptiä jota ladataan eikä kopioida — käsikirjoitus,
downmix ja lukijan kovennus ovat yhä snapshoteja alla. Se on myös ainoa
työtilan paketti jonka tämä sovellus ottaa (`pyproject.toml`), ja siksi että
se ei tuo mitään mukanaan: ei numpya, ei lxml:ää. Jos kirjastoon tulee tuonti
standardikirjaston ulkopuolelta, Colab kaatuu tuontiin eikä mikään paikallinen
ajo huomaa; `test_the_library_imports_nothing_but_the_standard_library`
(silencelearn) vartioi sitä, ja `test_the_library_is_uploaded_beside_the_
script_before_it_runs` sitä että tiedosto lähtee mukaan.

Täällä on vain tämän skriptin puoli: `_Levels` antaa kirjastolle sanat
(lxml) ja tasot (ffmpeg, 16 kHz mono, RMS) ja pitää jokaisen puretun
tiedoston muistissa ilman kattoa. `test_the_learned_threshold_matches_
podcast_magics` ajaa tämän sovittimen ja podcast-magicin sovittimen samalle
istunnolle ja äänelle ja vaatii saman luvun: kirjasto on yhteinen, mutta
`_dbfs`, sanojen luku ja alueiden poiminta ovat kahdessa paikassa. Testin
ääni on **ramppi**, ei kaksiarvoinen: kaksiarvoisella aineistolla
persentiilin muuttaminen 90:stä 80:een ei muuttanut mitään eikä testi
huomannut sitä.

Mitä ei käytetä: kirjasto laskee myös ero-rajan raitojen välillä
(`Calibration.dominance`), mutta tässä skriptissä ei ole sanakohtaista
vertailua toisiin raitoihin lainkaan, joten rajalle ei ole paikkaa. Se on oma
ominaisuutensa.

Käyttäjä vaimentaa istunnon alun **ennen ajoa**, litteroimattomaan
istuntoon: kynnys luetaan vain äänestä ja vaimennuksista, ja litteroinnin
sanat tulevat mukaan vasta puhevartijaan ja päästettävän sanan kattoon.
Luvut ovat kirjastossa makuarvoja, ja sama tarkistamatta oikealla
istunnolla. Ladattu kirjasto on ajettu kokonaisena vain puhtaassa
hakemistossa ilman työtilaa (kaksi tiedostoa, oikea ffmpeg), ei Colabissa.

## Luettu XML on aina kovennettu

Kaikki `.nhsx`:n luenta kulkee saman kovennetun parserin läpi
(`_SAFE_PARSER`: `lxml.etree`, ei DTD:n latausta, ei entiteettien
ratkaisu, ei verkkoa), ja `<!DOCTYPE>`-julistus hylätään heti
(`_reject_doctype`). XXE- ja entiteettipommi-iskuväylä on näin suljettu
molemmissa ovia — `inject_transcriptions_to_nhsx` ja `run_auto_silence`
kulkevat samaa tietä. Kovennus on käsin siirretty podcast-magicin lukijasta
tähän snapshotiin, eli se on driftin vaaraan kuuluvaa: jos lukijaa muutetaan,
tämä ei näe muutosta automaattisesti.

## Nopea siirto Google Driven kautta

Drive-siirto (`transfer="drive"`, ei enää oletus: uusilla tileillä Drive API vastaa 403:lla, ja ajo putoaa silloin itse suoraan siirtoon, `driver.direct_tail`) pakkaa syötetiedostot paikallisesti
`input.tar`-paketiksi (ilman raskasta gzip-pakkausta) ja lataa sen suoraan Google Driveen (`gdrive.py`)
resumable upload -protokollalla käyttäen olemassa olevia Colab CLI -tunnisteita
(`token.json`). Colab-koneessa Google Drive liitetään (`colab drivemount`), jolloin
tiedostot puretaan Google-sisäverkon nopeudella sekunneissa virtuaalikoneelle.
Ajon päätteeksi väliaikainen siirtokansio siivotaan automaattisesti Drivesta.
Haluttaessa vanha hidas suora siirto voidaan valita parametrilla `--transfer direct`
tai `--no-drive`.

## Yksi suunnitelma, kolme ovea

`driver.plan_commands` on ainoa paikka jossa Colab-komentoja rakennetaan.
TUI ja komentorivi molemmat kulkevat sen kautta, ja `--dry-run` tulostaa
samat komennot jotka oikea ajo suorittaa. Jos komennon muoto muuttuu,
muuttuu vain `driver.py` ja sen testit — ei kolmea kopiota.

`colab`-työkalu (`google-colab-cli`) on riippuvuus, jotta `uvx` riittää
asennukseksi. Se ja Googlen `jupyter-kernel-client`-fork ovat suoria
git-viittauksia kiinnitettyinä toimiviksi todettuihin committeihin: PyPI:n
samanniminen `jupyter-kernel-client` on eri paketti, eikä Colab CLI:n oma
`[tool.uv.sources]` päde kun se on toisen riippuvuus. `onboarding.bundled_colab`
löytää sen oman Pythonin vierestä, ja `colab_env` lisää sen hakemiston
PATHin alkuun: komennot pysyvät muodossa `colab ...`, joten `--dry-run`
näyttää täsmälleen mitä ajetaan. uv:n `#!/bin/sh`-käynnistimen takana
oleva Python haetaan `_script_python`illa — shebangista luettuna se olisi
`/bin/sh`, ja tarkistukset ja korjaukset epäonnistuisivat hiljaa.
Ensimmäinen kirjautuminen: `colab-transcribe --login` (ajaa `colab usage`,
joka kysyy Google-tunnuksen); gcloudia ei tarvita.

Järjestelmä tarkistaa apuohjelman olemassaolon
sekä tunnistetiedot (`onboarding.py`): jos ne puuttuvat, TUI avaa opastusikkunan
ja komentorivi antaa selkeät asennus- ja kirjautumiskomennot ennen ajoa.
TUI:ssa syöte- ja tulostekansiot valitaan interaktiivisilla valintaikkunoilla
(`picker.py`), joten polkuja ei tarvitse kirjoittaa käsin.

## Istunnon elinkaari ja uudelleenkäyttö

Colab-istunnon tila tarkistetaan ennen komentosuunnitelman luomista (`session.py`).
Jos istunto on jo käynnissä:
* Oletuksena istunto **uudelleenkäytetään**: `colab new` ohitetaan ja etäkansiot tyhjennetään uutta ajoa varten. Tämä säästää virtuaalikoneen käynnistysajan ja estää Colabin samanaikaisuusrajan virheet (`412 Precondition Failed`).
* Valitsimella `--reset-session` olemassa oleva istunto suljetaan ensin ja luodaan puhdas virtuaalikone.
* Valitsimella `--keep-session` istunto jätetään käyntiin ajon jälkeen nopeita peräkkäisiä ajoja varten.
* Komennolla `colab-transcribe --stop` (tai TUI:n "Pysäytä istunto" -painikkeella) istunto voidaan vapauttaa suoraan.
* Ajuri nappaa `KeyboardInterrupt`in (Ctrl+C) ja ilmoittaa tilasta, jos käyttäjä keskeyttää ajon kesken suorituksen.

## Versio

`__init__.py` johtaa version `importlib.metadata`sta eikä kirjoita sitä
auki: yksi numero vähemmän joka voi jäädä jälkeen, ja
`scripts/bump_version.py` osaa ohittaa sen. Ei `.spec`iä, koska ei
paketoitavaa `.app`ia — ketju ajaa pilvessä, paikallinen kone vain ajaa.

## Testit

Ajuri on testattu ilman verkkoa: `plan_commands` on puhdas funktio, ja
TUI:n ajo pistetään testeissä välikäsiin `runner`-argumentilla. Testit,
jotka kutsuisivat `colab`ia tai Colabia, eivät ole testit vaan vedonlyöntiä.

## Vuodon suodatus on vain tässä snapshotissa

`_bleed_dropped` (``colab/pipeline.py``) pudottaa sanat jotka ovat toisen mikin
vuotoa, sekä injektiossa (``_injection_bleed``) että skriptissä
(``_drop_bleed``). podcast-magicin ``script/core.py`` ei tee sitä, eikä sen
tarvitse: se ei kirjoita litterointeja istuntoon. Snapshot-testi
(``test_the_snapshot_script_matches_podcast_magics``) ajaa skriptin ilman
``audio_dirs``-parametria, jolloin suodatus ei ole mukana ja tulos on sama.
Raja ``BLEED_MARGIN_DB`` on mitattu yhdestä kahden mikin istunnosta.

## Puhejakso on määritelty kerran

"Missä raidan puhe alkaa ja loppuu" ratkaistaan ``merge_intervals_with_gap``illa
(Auto-Silence) ja ``_split_bursts`` (skripti) käyttää samaa funktiota samalla
``gap``illa, joka tulee presetistä. Älä lisää skriptiin omaa taukovakiota:
``TURN_GAP_S`` on vain oletus kun ``write_script``ia kutsutaan ilman ajoa.
podcast-magicin ``script/core.py`` ei voi tuoda sitä (työtilan raja) ja pitää
oman 1 s:n kopionsa; testi pitää tulokset samoina oletusgapilla.
