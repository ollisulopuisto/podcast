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

## Luettu XML on aina kovennettu

Kaikki `.nhsx`:n luenta kulkee saman kovennetun parserin läpi
(`_SAFE_PARSER`: `lxml.etree`, ei DTD:n latausta, ei entiteettien
ratkaisu, ei verkkoa), ja `<!DOCTYPE>`-julistus hylätään heti
(`_reject_doctype`). XXE- ja entiteettipommi-iskuväylä on näin suljettu
molemmissa ovia — `inject_transcriptions_to_nhsx` ja `run_auto_silence`
kulkevat samaa tietä. Kovennus on käsin siirretty podcast-magicin lukijasta
tähän snapshotiin, eli se on driftin vaaraan kuuluvaa: jos lukijaa muutetaan,
tämä ei näe muutosta automaattisesti.

## Luettu XML on aina kovennettu

`.nhsx`:n molemmat lukupolut — transkriptioitten injektointi ja
Auto-Silence — käyvät saman kovennetun parserin kautta. `<!DOCTYPE>`
hylätään heti, ja parser ei lataa DTD:tä, ratkaise entiteettejä eikä ota
yhteyttä verkkoon: XXE- ja entiteettipommien iskuväylä on suljettu
molemmissa ovia kerralla. Tämäkin on käsin siirretty kopio
podcast-magicin lukijasta, eli driftin vaara pätee: jos jompaa parseria
muutetaan, toinen ei näe muutosta.

## Yksi suunnitelma, kolme ovea

`driver.plan_commands` on ainoa paikka jossa Colab-komentoja rakennetaan.
TUI ja komentorivi molemmat kulkevat sen kautta, ja `--dry-run` tulostaa
samat komennot jotka oikea ajo suorittaa. Jos komennon muoto muuttuu,
muuttuu vain `driver.py` ja sen testit — ei kolmea kopiota.

`colab`-työkalu on ulkoinen riippuvuus (ei pypi, ei brew-formulaa tässä
repossa). Ajuri ei tarkista sen olemassaoloa etukäteen: puuttuva komento
näkee vasta ensimmäinen ajo, ja se palauttaa 127:n lopettamatta mitään
keskellä. Istunto jää auki keskeytyneen ajon jälkeen — sulku on aina
suunnitelman viimeinen komento, ja keskeytyneen ajon jälkeen Colabin oma
käyttöliittymä on se joka sen saa kiinni.

## Versio

`__init__.py` johtaa version `importlib.metadata`sta eikä kirjoita sitä
auki: yksi numero vähemmän joka voi jäädä jälkeen, ja
`scripts/bump_version.py` osaa ohittaa sen. Ei `.spec`iä, koska ei
paketoitavaa `.app`ia — ketju ajaa pilvessä, paikallinen kone vain ajaa.

## Testit

Ajuri on testattu ilman verkkoa: `plan_commands` on puhdas funktio, ja
TUI:n ajo pistetään testeissä välikäsiin `runner`-argumentilla. Testit,
jotka kutsuisivat `colab`ia tai Colabia, eivät ole testit vaan vedonlyöntiä.
