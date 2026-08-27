# Podcast Magic

Hindenburgin istunto sisään, Hindenburgin istunto ulos. Kaksi työkalua
saman `.nhsx`-tiedoston ympärillä, tilaa kolmannelle.

Koodi, kommentit ja docstringit ovat **suomeksi** — ne ovat tekijöille.
Käyttöliittymä ja dokumentaatio ovat suomeksi ja englanniksi. Pidä se niin.

## Istunto on ainoa yhteys moduulien välillä

`nhsx/` on kaikkien moduulien yhteinen, `transcribe/` ja `silence/` eivät
tunne toisiaan. Litterointi kirjoittaa sanat äänipooliin, vaimennus lukee ne
sieltä. Jos moduuli alkaa tarvita toisen sisäistä tilaa, se kuuluu `nhsx/`:ään
tai ei kuulu tänne.

Uusi moduuli on neljä asiaa: merkintä `modules.py`:ssä, `APIRouter`, yksi
`mod_*.js` ja mahdollisesti oma alipaketti. Kuori (`server/app.py`, `app.js`)
ei muutu. Istuntovalitsin ja työjono ovat kuoressa, joten moduuli perii ne.

## Sanan aika on tiedoston aikaa

`<w s="…">` on aikaa **tiedoston** alusta. Alueen `Offset` kertoo mistä
kohtaa tiedostoa alue alkaa ja `Start` mihin kohtaan aikajanaa se on
sijoitettu, joten sana osuu aikajanalla kohtaan `Start + (s - Offset)`.
Muunnos tehdään alueittain, koska sama tiedosto voi esiintyä aikajanalla
useaan kertaan.

Sama kaava toiseen suuntaan on `nhsx/pipeline.py`:n `Span.file_time`, ja se
on kaikki mitä ääniketju tarvitsee aikajanasta tietää.

Väärä muunnos ei näy XML:ssä mitenkään: tiedosto avautuu, alueet ovat oikean
mittaisia ja ääni tulee väärästä kohtaa tiedostoa.

## Nopein Whisper Macilla on MLX, ja syy kannattaa tietää

CTranslate2:ssa (faster-whisper) **ei ole Metal-taustaa lainkaan**. Macilla
se ajaa suorittimella, ja Colab-muistikirjan `--compute_type auto` ei löydä
näytönohjainta käytettäväksi. MLX ajaa saman mallin GPU:lla. Ero on
kertaluokka, ja siksi `mlx` on ensimmäisenä `BACKENDS`-listassa — valinta
`auto` ottaa listasta ensimmäisen asennetun.

`faster-whisper` on silti mukana: Intel-Macit, ja toinen mielipide silloin
kun tulos näyttää oudolta.

Ääni annetaan moottorille **valmiiksi puretuna taulukkona**, ei polkuna.
mlx-whisperin oma `load_audio` kutsuu ffmpegiä PATHista, ja pakatussa
sovelluksessa PATHissa ei ole mitään — binääri on paketin sisällä. Polkua
antamalla litterointi toimisi kehityskoneella ja kaatuisi valmiissa
`.app`-paketissa.

`mlx_whisper.transcribe` on **funktio**, ei alimoduuli: paketin `__init__`
tekee `from .transcribe import transcribe` ja varjostaa samannimisen
moduulin. Myös `import mlx_whisper.transcribe as x` päätyy funktioon. Moduuli
haetaan `sys.modules`ista, ja siitä paikataan `tqdm` edistymisen lukemiseksi
— ilman sitä tunnin jakso etenee ilman yhtään merkkiä etenemisestä.

## Tunniste, ei muutosaika

Valmis litterointi luetaan levyltä JSONina. Se, milloin sen saa lukea, on
`Options.fingerprint()`: malli, kieli, täytesanat ja hiljaisuuden suodatus.
Ilman tunnistetta mallin vaihtaminen ei tekisi mitään — vanha tulos löytyisi
levyltä eikä uutta mallia ajettaisi, eikä siitä sanottaisi mitään.

Kenttäluettelo on kirjoitettu käsin `test_fingerprint_fields_are_written_out_by_hand`iin,
jotta uusi asetus ei livahda tunnisteeseen tai siitä pois huomaamatta.

## Käsikirjoitusnäkymän kohdistin: mitä tiedetään ja mitä ei

Oire: aikajananäkymässä sanat osuvat kohdalleen, käsikirjoitusnäkymässä
toistokohdistin jää alkuun. Näkymät lukevat samaa dataa mutta eri tavalla:
aikajana piirtää sanat alueen sisään (muunnosta ei tarvita), käsikirjoitus on
erillinen dokumentti joka tarvitsee aikaindeksin. Epäonnistunut indeksi
osoittaa alkuun.

Syytä **ei tiedetä**. Formaattia ei ole dokumentoitu, eikä Hindenburgin omaa
litterointia ole vertailtavaksi. `nhsx/verify.py` on lista epäiltyjä, ei
diagnoosi, ja se erottaa vian (mitattavasti väärin) huomiosta (rakenteellinen
tosiasia tuotoksestamme). Älä muuta sitä diagnoosiksi ilman mittausta.

`nhsx/write.py` estää kolme epäiltyä rakenteellisesti: sanat lajitellaan,
päällekkäisyys korjataan **lyhentämällä edeltävää** sanaa eikä siirtämällä
seuraavaa (alkuaika on se mihin kohdistin osuu, ja siirtäminen kasaisi
virheen eteenpäin koko tiedoston läpi), ja pituudella on lattia.

`Options.paragraphs` on olemassa vertailua varten eikä mieltymyksenä: sama
istunto kahdella asetuksella kertoo onko kappalejako syy. Se on siksi myös
tunnisteessa — muuten toinen ajo lukisi ensimmäisen tuloksen levyltä eikä
vertailua tapahtuisi.

`sp="UU"` jätetään ennalleen, koska aikajananäkymä toimii sillä. Oikeaa
arvoa ei arvata: väärä puhujatunnus voisi rikkoa sen mikä nyt toimii.

## Ominaisuus, joka ei tuottanut mitään, sanoo sen

Tämän luokan viat ovat kaikki samanlaisia: kelvollinen tiedosto, puhdas ajo,
ei poikkeusta, väärä tulos — ja se huomataan vasta kuuntelemalla, jolloin
leikkaus on jo tehty käsin eikä sitä voi rakentaa uudestaan. Siksi:

* Litterointi, joka ei tunnistanut yhtään sanaa, **ei kirjoita istuntoa**.
  Tyhjä `<Transcription>` on kelvollinen ja saisi vaimennuksen vaientamaan
  koko raidan.
* Tason tarkistus päällä ja yhdenkään raidan ääntä ei löydy levyltä on
  **virhe**. Tulos olisi sama kuin ilman tarkistusta, ja käyttöliittymä
  lupasi muuta.
* Raita, jolla ei ole litterointia lainkaan, **jätetään koskematta**.
  Colab-muistikirja teki niin (`if not intervals: return`), ja se on oikein:
  tiedon puute ei ole päätös vaientaa. Musiikkiraita on tästä se tapaus jota
  ei huomaa ennen kuin se puuttuu.

## Kaksi säädintä sulkee taukoja, ja suurempi ratkaisee

`audible_zones` sulkee tauon jos se on lyhyempi kuin `gap` **tai** lyhyempi
kuin kaksi kertaa `tail`. Häntä puoli sekuntia sulkee sekunnin tauon vaikka
«lyhin tauko» olisi 0,4. Järjestys — sulje, sitten pehmennä — on tämä eikä
toisin päin: hännän lisääminen ensin sulkisi tauot pituuteen
`gap + 2 × tail` asti, eli säätimet laskisivat yhteen.

## Muuta

* **Lähdettä ei kirjoiteta koskaan yli.** Vienti on uusi tiedosto, ja jos
  sellainen on jo, siitä tulee `… v2`.
* **Alueen lapsielementit eivät seuraa pilkkomisessa.** Sama häivytys sadassa
  palassa on eri asia kuin yksi häivytys alueen alussa. Siitä kerrotaan
  lokissa; muistikirja pudotti ne hiljaa.
* **Yksi työ kerrallaan.** Kaksi litterointia jakaisi saman näytönohjaimen ja
  valmistuisi molemmat myöhemmin kuin peräkkäin ajettuina.
* **Tason mittauksen välimuisti pitää int16:ta.** Tunnin jakso on 16 kHz:llä
  115 MB int16:na ja 230 MB float32:na, ja niitä on istunnossa useita.
  Katto on kaksi tiedostoa: ajo etenee raita kerrallaan.
* **Mallien painoja ei paketoida.** `large-v3-turbo` on gigatavun luokkaa;
  se ladataan ensimmäisellä ajolla ja jää käyttäjän välimuistiin.

## Ääniketju tulee joskus, ei vielä

`nhsx/pipeline.py` on sauma autoraffkatin mitatulle puheenkäsittelyketjulle:
raita, jolla on puhuja, monolippu, bittisyvyys ja lista jaksoja
ohjelma-aikajanalla. Siinä ei ole yhtään käsittelyä eikä sitä pidä lisätä
tänne — ketju kuuluu jaettuun pakettiin, jotta se ei ehdi ajautua erilleen
kolmessa projektissa. Tämän tiedoston tehtävä on, ettei ketjun tuominen ole
lukijan uudelleenkirjoittamista.
