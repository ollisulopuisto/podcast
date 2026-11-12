# Roadmap: Multi-NLE Support (DaVinci Resolve & Adobe Premiere Pro)

> **Looking to contribute?** Multi-NLE support is one of the highest-impact areas to work on in `autoraffkat`. If you use DaVinci Resolve or Adobe Premiere Pro, this is a fantastic project to tackle as an open-source contribution!

---

## Background & Architecture

`autoraffkat` was originally built around Final Cut Pro XML (`.fcpxml` / `.fcpxmld`), but its internal architecture is already decoupled from Final Cut Pro.

As described in [`DESIGN.md`](DESIGN.md):
```
   [Input File]  ──►  Reader (e.g. the fcpxml package)  ──►  Timeline (MediaItem + Placement)
                                                                   │
                                                ┌──────────────────┴──────────────────┐
                                                │                                     │
                                          audio/envelope.py                     User Roles &
                                          ffmpeg + RMS 20 ms                      Controls
                                                │                                     │
                                                └──────────────►  analysis.py  ◄──────┘
                                                                  MILLISECONDS
                                                                       │
                                                                       ▼
                                                                  decide.py
                                                                  thresholds, durations, overlap
                                                                       │
                                                       ┌───────────────┴───────────────┐
                                                       ▼                               ▼
                                                 preview.py                     Writer (e.g. finalcut/write.py)
                                                 web browser bar                New project / timeline
```

Everything in the middle—audio decoding, speaker energy envelopes, turn detection, cut decisions (`decide.py`), reaction shots, reframing, and the web preview—operates purely on the abstract [`Timeline`](src/autoraffkat/model.py) structure.

Supporting other Non-Linear Editors (NLEs) is therefore **purely an I/O interchange task**: reading the NLE's timeline format into `Timeline`, and serializing the cut list back into that format.

---

## Target NLEs & Implementation Phases

### Phase 1: DaVinci Resolve Compatibility via FCPXML (Starter PR / Good First Issue)

**Goal:** Allow users to round-trip projects between Blackmagic DaVinci Resolve (Free & Studio) and `autoraffkat` using `.fcpxml`.

* **The Opportunity:** DaVinci Resolve natively imports and exports `.fcpxml` (*File → Import → Timeline → Import AAF/EDL/XML*). Resolve has a very popular free tier widely used by podcast editors.
* **The Challenge:** Resolve's FCPXML parser is pickier than Apple's Final Cut Pro. It tends to prefer FCPXML v1.8 or v1.9, and handles certain elements (such as `<sync-source>`, timecode formats, or `<mc-clip>` multicam containers) with slight schema differences.
* **Tasks:**
  1. Export a multicam project from DaVinci Resolve as `.fcpxml` and test opening it in `autoraffkat`.
  2. Verify if autoraffkat's flat export (`export_flat`) already imports cleanly into Resolve.
  3. Identify any XML elements or attributes rejected by Resolve's XML importer when importing the cut multicam.
  4. Add an export option or dialect profile (e.g. `format="resolve"`) that writes Resolve-compatible FCPXML.
  5. Add test fixtures and assertions in `tests/test_write.py`.

---

### Phase 2: Classic FCP 7 XML (`xmeml`) — Unlocks BOTH Premiere Pro & DaVinci Resolve

**Goal:** Enable native import and export for Adobe Premiere Pro and DaVinci Resolve using the universal FCP 7 XML standard.

* **The Opportunity:** Adobe Premiere Pro **cannot** natively import modern Final Cut `.fcpxml` without commercial 3rd-party plugins. However, Premiere Pro AND DaVinci Resolve BOTH natively support classic Final Cut Pro 7 XML (`<xmeml version="4">` or `5`) via standard *File → Import* and *File → Export*.
* **Implementation:**
  1. **Reader (`src/autoraffkat/xmeml/read.py`):**
     * Parse `<xmeml>` sequences into `Timeline` (translating tracks, `<clipitem>`, media file paths, and timecodes).
     * Time in FCP 7 XML uses integer frames and timebase rates (simpler than FCPX rational fractions).
  2. **Writer (`src/autoraffkat/xmeml/write.py`):**
     * Generate an `<xmeml>` sequence with the cuts placed on video tracks and dialogue audio attached with appropriate roles.
  3. **Tests:**
     * Add round-trip tests in `tests/test_xmeml.py` with real Premiere Pro and DaVinci Resolve exported XML fixtures.
  4. **UI Integration:**
     * Accept `.xml` alongside `.fcpxml` in the file picker and auto-detect the parser based on root XML tag (`<xmeml>` vs `<fcpxml>`).

---

### Phase 3: DaVinci Resolve Live Python API (`DaVinciResolveScript`)

**Goal:** Zero-file-export editing directly inside running DaVinci Resolve instances.

* **The Opportunity:** DaVinci Resolve ships with a native Python scripting API (`DaVinciResolveScript`), available in both free and Studio versions on macOS, Windows, and Linux.
* **Implementation:**
  1. Add a bridge module that connects to Resolve (`dvr_script.GetResolve()`).
  2. Read active timeline tracks, clips, and timecodes directly into `Timeline`.
  3. Execute cut decisions by splitting clips or creating a cut timeline track via the API.
  4. Add a "Cut Active Resolve Timeline" button in the web UI.

---

## How to Get Started

If you'd like to work on this:
1. Open an issue on GitHub discussing your plan and the NLE version you're testing against.
2. Check [`CONTRIBUTING.md`](../../CONTRIBUTING.md) and [`CLAUDE.md`](../../CLAUDE.md) for local setup, test running, and code conventions.
3. Start small: Phase 1 (validating and adjusting FCPXML for DaVinci Resolve) is the fastest way to get a working PR merged!

---

## Editing: cut on movement

Cutting on a movement — a hand, a turn of the head — hides the cut, and is
what an editor does by eye. The video layer already measures faces per
keyframe (`video/`); a motion measure there could move a speaker change to
the nearest movement within a short reach, the same way a long-take break
moves to a measured reaction (`decide.REACTION_REACH`). Wanted after the
turn-taking fixes of 2026-09-23 have been listened to.

## Agent and command-line automation

Autoraffkat can already be launched with an FCPXML path and exposes internal
HTTP endpoints for state, settings, export, audio processing, and rendering.
Those endpoints are not yet a documented, stable automation interface, and
the CLI does not expose the full editing workflow. Make the app reliably
drivable by command-line tools and LLM agents:

1. Document a versioned API with explicit request and response schemas for
   supported actions, including validation and error cases.
2. Add headless CLI commands for the complete supported workflow, so agents
   can load a project, inspect and change settings, export, and run or stop
   processing without native dialogs or GUI interaction.
3. Emit structured progress and error output suitable for scripts, while
   keeping existing human-readable CLI output usable.
4. Keep the HTTP API and CLI behavior aligned, and document which actions
   require macOS or Final Cut Pro.

Treat the current web routes as implementation details until this contract
and its schemas are documented and supported. The existing local HTTP API and
the `autoraffkat` launcher are starting points, not complete agent interfaces.


## Agent operation (MCP) and automatic in/out markers

Requested 2026-11-12. Goal: a client opens an LLM agent (Claude) and tells it
to make a video from given camera and microphone files; the agent drives
Autoraffkat through MCP/API: sync audio to video, find the show's start and
end, cut, export.

### MCP adapter over the local API and CLI

Thin stdio MCP server wrapping the existing `/api/v1/*` endpoints and the
headless CLI (`autoraffkat edit` / `inspect`). The endpoints already cover the
workflow an agent needs: media inspect, sync estimate, source-project import,
open, settings, cut, export. Estimate ~1-2 days (a few hundred lines plus tool
schemas). The documented, stable v1 contract (section above) can lag the
adapter. One friction to fix on the way: `/api/media/import` currently expects
human-reviewed sync shifts, so the agent flow wants an explicit auto-accept
option that passes the measured shifts through.

Dependency to call out: the agent workflow leans on media routes that are
not yet part of the versioned contract — `/api/media/inspect`,
`/api/media/estimate`, `/api/media/import` and `/api/open` are unversioned
(`/api/v1` currently covers only project actions: state, settings, cut,
export). Before the MCP interface can be called stable, promote these to
v1 (`/api/v1/media/inspect|estimate|import`, `/api/v1/open`) with schemas,
or document the adapter as pinned to the unversioned routes until then.

### Clap/transient-based in/out markers (~2 days)

Manual in/out markers already exist (the program range setting). This
automates the suggestion: an opening clap is a broadband transient that lands
on **every** microphone at once — the all-tracks requirement is what rejects a
single-mic tap that must not end the episode. In-marker = first sustained
speech after the opening clap; out-marker = last sustained speech before the
closing clap; expected episode length as sanity rails. All DSP pieces exist:
envelope extraction (speechmix), silence runs (`audio/silence.py`), envelope
cross-correlation (`audio/sync.py`), speech-on grids from the analysis layer.
Result lands as an auto-suggested `program_range`, one click from override.

### Suomeksi: agenttikäyttö (MCP) ja automaattiset alku/loppumerkit

Pyydetty 2026-11-12. Tavoite: asiakas sanoo LLM-agentille (Claude) "tee
video näistä kamera- ja mikkitiedostoista", ja agentti ajaa Autoraffkatin
läpi MCP:llä/API:lla: synkkaa ääni kuvaan, löydä jakson alku ja loppu,
leikkaa, vie.

MCP-adapteri on ohut stdio-palvelin olemassa olevien `/api/v1/*`-reittien
ja pääkäyttäytymättömän CLI:n päälle, arviolta 1-2 päivää. Huomio: agentin
työnkulku nojaa medioihin liittyviin reitteihin (`/api/media/inspect`,
`/api/media/estimate`, `/api/media/import`, `/api/open`), jotka eivät vielä
kuulu versioituun rajapintaan — ne pitää nostaa v1:een ennen kuin MCP:tä
voi kutsua vakaaksi. Lisäksi `/api/media/import` odottaa nyt ihmisen
tarkistamia siirtoja, joten agenttivirtaan tarvitaan nimenomainen
auto-accept-valinta, joka syöttää mitatut siirrot suoraan.

Alku/loppumerkit automaattisesti: jakson aloittava taputus on laajakaistainen
transientti, joka näkyy **kaikissa** mikeissä yhtä aikaa — juuri tämä
kaikkien-raatojen vaatimus erottaa sen yhden mikin napautuksesta, joka ei
saa päättää jaksoa. Alkumerkki = ensimmäinen jatkuva puhe alkutaputuksen
jälkeen, loppumerkki = viimeinen jatkuva puhe ennen lopputaputusta, ja
odotettu jakson pituus järjen raiteina. Kaikki DSP-palikat ovat valmiina;
tulos ilmestyy ehdotettuna `program_range`:na, yhden klikkauksen päässä
ylikirjoituksesta.

### Media sync: wider search, listen-before-import, drift (phase 2)

From the 2026-11-12 spec and Olli's decisions. Phase 1 awaits his "build
it"; the vectorization groundwork is already done (`perf/sync-vectorize`).

**Phase 1 — search window and preview by listening.**
- Replace the fixed ±5 min search with confidence-gated auto-expansion
  (BBC audio-offset-finder pattern): search ±5 min; if the peak correlation
  is below threshold (~0.4, tune on real episodes), expand to the full
  recording. Manual presets (±5/±30 min/±2 h/full) stay available as an
  accuracy prior. The vectorized scorer makes full-range search ~0.09 s on
  two-hour envelopes, so the window is no longer a performance question.
- Listen-before-import in the sync panel: one 10 s "everybody talks" clip
  (camera picture + all mics mixed with the proposed offsets) and 5 s
  per-speaker clips, picked from the already-computed envelopes (maximal
  simultaneous speech / dominant mic). Listen → adjust the offset field →
  re-preview → import. syncstart ships the same idea as zoomed correlation
  diagrams; ears are the accepted fallback when confidence is low.

**Phase 2 — clock drift (Olli 2026-11-12: assume no drift by default; an
opt-in toggle, off).**
- Detection: after the first full-file match, re-measure the offset near
  the start and near the end of the shorter file, anchored to the known
  sync point. If start and end disagree beyond a tolerance (a frame or two
  per hour), the files drift.
- Failure path: when a sync attempt fails with a drift signature (good
  local matches that disagree), show "files seem to drift" and offer the
  drift-fix toggle instead of a bare failure.
- Correction, two candidates:
  - *Single linear resample* of the drifting track to the reference clock.
    Uniform timing, standard fix (protyposis.net/clockdrift); cost is one
    resampling pass and it assumes drift is constant — temperature and
    battery wobble leave a small residual.
  - *Piecewise re-sync at quiet points* (Olli's suggestion): keep constant
    offsets but re-anchor them about once a minute, or at points where
    nobody is talking (the speech grids already exist). Discontinuities
    land in silence so they are inaudible; no resampling artifacts; cost
    is more timeline bookkeeping — each drifting mic becomes several
    segments in the FCPXML — and drift still accumulates inside a segment
    (bounded by the segment length).
  - Decision when built: default to piecewise-at-silence for speech
    material (inaudible by construction), resample as the fallback when no
    usable silences exist.

### Suomeksi: mediasynkka — leveämpi haku, kuuntelu ennen tuontia, ajankuluminen (vaihe 2)

2026-11-12 speksistä ja Ollin päätöksistä. Vaihe 1 odottaa hänen "build
it" -käskyään; vektorointi on jo tehty (`perf/sync-vectorize`).

**Vaihe 1 — hakuikkuna ja kuunteluesikatselu.**
- Kiinteän ±5 min haun tilalle luottamuksella ohjattu automaattinen
  laajennus: haetaan ensin ±5 min, ja jos korrelaatiohuippu jää alle
  kynnyksen (~0.4, viritetään oikeilla jaksoilla), laajennetaan koko
  tallenteeseen. Käsin valittavat esiasetukset (±5/±30 min/±2 h/koko)
  säilyvät tarkkuuspriorina. Vektoroidun pisteytyksen myötä koko aineiston
  haku on ~0.09 s kahden tunnin verhoilla, joten ikkuna ei ole enää
  suorituskykykysymys.
- Kuuntelu ennen tuontia synkkapaneelissa: yksi 10 s "kaikki puhuvat"
  -pätkä (kameran kuva + kaikki mikit ehdotetuilla siirroilla) ja 5 s
  kaiutinraatapätkät, valittuna jo lasketuista verhoista. Kuuntele,
  säädä siirtoa, kuuntele uudestaan, tuo vasta kun kuulostaa oikealta.

**Vaihe 2 — kellon ajankuluminen (Olli 2026-11-12: oletus ei ajankulumista;
opt-in-kytkin, oletuksena pois päältä).**
- Tunnistus: ensimmäisen osuman jälkeen mitataan siirto uudelleen lyhyemmän
  tiedoston alun ja lopun läheltä, ankkuroituna tunnettuun synkkapisteeseen.
  Jos alku ja loppu ovat eri mieltä toleranssin yli (pari ruutua tunnissa),
  tiedostot kuluvat.
- Kun synkkaus epäonnistuu ajankulumisen jälkiin (hyvät paikalliset osumat
  ovat keskenään ristiriidassa), näytetään "tiedostot näyttävät kuluma" ja
  tarjotaan korjauskytkintä pelkän epäonnistumisen sijaan.
- Korjaus, kaksi ehdokasta: yhtenäinen lineaarinen uudelleennäytteistys
  viitekelloon (vakiomenetelmä, mutta olettaa vakion kuluman) tai
  paloittainen uudelleensynkkaus hiljaisissa kohdissa (Ollin ehdotus:
  ankkurointi noin minuutin välein tai kun kukaan ei puhu — katkot osuvat
  hiljaisuuteen eivätkä kuulu, hintana segmenttien kirjanpito ja segmentin
  sisällä kertyvä kuluma). Rakennettaessa oletus on paloittainen puhe-
  aineistolle, uudelleennäytteistys varatoimena kun hiljaisuutta ei ole.

### Browser SaaS notes (assessment 2026-11-12)

Constraints from Olli: nobody uploads 10+ GB of video, weak client PCs,
everything in the browser.

- **Option B — proxy/audio-upload SaaS (the natural fit).** The cut decision
  is speech-driven: upload audio stems (~100-500 MB per show-hour) plus
  low-res proxies (a few % of original size) for the video-measured features.
  The server runs the existing FastAPI engine almost untouched; the user gets
  back the FCPXML and relinks to local originals. Relink must be client-side:
  the hosted `relink_timeline` scans the machine it runs on, which is the
  server — it can never see the user's originals. Concretely (as in the VPS
  pilot spec): before download, rewrite the file URLs in the exported XML to
  bare file names, and the user points Final Cut at the local originals
  folder once. The server can also render the social/vertical outputs
  from proxies — the deliverable is 1080x1920 or below, so proxy-quality
  sources are legitimate. Full-quality masters need a resumable originals
  upload or a local render.
- **Option C — thin local agent + hosted web UI.** The app already is a
  localhost API server; keep it on the user's machine, add a hosted account/UI
  layer that drives it. Zero upload, and rendering happens where the originals
  live with hardware encode (`render_av.py`). Combines with B: server cut +
  server social render from proxies, local agent optional for masters.
- **Ruled out: pure WASM in-browser.** Pyodide + ffmpeg.wasm reading 10 GB
  originals on a weak PC is the worst combination; months of porting for a
  worse result.
- Cheapest validating step for B: run the existing app on one VPS, add a
  minimal upload form feeding `/api/media/import`, and put one real episode
  through it. Days to a private pilot.
- Unverified in the assessment: render times and output sizes, proxy-quality
  rendering end-to-end, how gracefully video-measured features degrade on
  audio-only uploads, WASM dependency compatibility, and the MCP wrapper
  itself (not prototyped).

### Tier plan (added 2026-11-12, revised pilot spec)

Pilot constraints from Olli: the client has **no Final Cut** — only video
files and maybe separate audio files — plus a slow uplink, a weak CPU and
little free disk. The deliverable is therefore rendered MP4s (horizontal
master + verticals + mixed audio), never XML to relink. Audio stems go up
as **Opus, not MP3** (smallest encoder priming, best quality per bit, light
wasm encoder); before launch, run the synthetic sync check: a known-offset
pair, both Opus-encoded, must recover the offset within ±40 ms (encoder
priming compensated on decode; untested until this runs).

- **Fast tier — browser-only, proxy-grade, ~1 h turnaround.** The browser
  extracts Opus audio stems and encodes 720p proxies with WebCodecs
  hardware encode (weak-CPU friendly; wasm fallback is several× realtime
  and is the biggest risk). Upload is ~2-2.5 GB per show-hour via resumable
  chunks. The server runs the existing engine and returns proxy-grade MP4s.
  Client does nothing but pick files.
- **Full tier — full-quality re-render on top of the same decisions.** The
  tier-1 cut is reused as an EDL-style decision list; the camera originals
  upload in the background (tens of GB per episode), ideally through a
  small desktop uploader app since a browser tab would have to stay open
  for the whole transfer. The server re-renders at full quality from the
  originals. Priced on what it actually costs: storage, egress, full-res
  CPU encode.
- **Risks:** tens of GB per episode of originals storage and its
  retention/deletion policy; full-res CPU encode time unmeasured; edits the
  client makes after the tier-1 delivery must be carried into the re-render
  (the decision list must stay the single source of truth).

### Suomeksi: selain-SaaS (arviointi 2026-11-12)

Ollin reunaehdot: kukaan ei lataa yli 10 gigaa videota verkkoon, asiakkaan
kone on hentoinen, kaiken pitää toimia selaimessa.

- **Vaihtoehto B — proxy-/äänivaralataus-SaaS (luonnollinen sopivuus).**
  Leikkauspäätös on puheohjattu: verkkoon siirtyvät vain ääniraidat
  (~100-500 MB per shown tunti) ja matalan resoluution proxyt (muutama
  prosentti alkuperäisen koosta) kuvamittausta varten. Palvelin ajaa
  nykyisen FastAPI-moottorin lähes koskemattomana. Käyttäjä saa takaisin
  FCPXML:n ja linkittää sen paikallisiin alkuperäisiin. Linkitys täytyy
  tehdä asiakkaalla: palvelimella ajettu `relink_timeline` skannaa sen
  koneen, jolla se pyörii — se ei koskaan näe käyttäjän alkuperäisiä.
  Käytännössä (kuten VPS-pilottispeksissä): ennen latausta viennin
  tiedostopolut kirjoitetaan pelkiksi tiedostonimiksi, ja käyttäjä näyttää
  Final Cutille kerran paikallisen kansion. Palvelin voi myös renderöidä
  some-/pystyversiot proxyista — lopputulos on korkeintaan 1080x1920, joten
  proxy-laatu riittää. Täyslaatuiset masterit vaativat jatkuvaa
  alkuperäislatausta tai paikallista renderöintiä.
- **Vaihtoehto C — ohut paikallinen agentti + isännöity web-UI.** Sovellus
  on jo valmiina localhost-API-palvelin; pidetään se käyttäjän koneella ja
  lisätään isännöity tunnus/UI-kerros, joka ohjaa sitä. Ei lainkaan
  latausta, ja renderöinti tapahtuu siellä missä alkuperäiset ovat,
  laitteistokiihdytyksellä (`render_av.py`). Yhdistyy B:hen: palvelinleikkaus
  ja some-renderit proxyista, paikallinen agentti vapaaehtoinen mastereille.
- **Hylätty: puhdas WASM selaimessa.** Pyodide + ffmpeg.wasm lukemassa
  10 gigan alkuperäisiä heikolla koneella on huonoin mahdollinen yhdistelmä;
  kuukausien porttaus huonompaan lopputulokseen.
- Halvin B:tä validoiva askel: aja nykyinen sovellus yhdellä VPS:llä, lisää
  minimaalinen latauslomake `/api/media/import`:iin syöttäväksi ja aja yksi
  oikea jakso läpi. Päiviä yksityiseen pilottiin.

### Suomeksi: tasosuunnitelma (lisätty 2026-11-12, uudistettu pilottispeksi)

Ollin pilotin reunaehdot: asiakkaalla **ei ole Final Cutia** — vain
videotiedostot ja ehkä erilliset äänitiedostot — sekä hidas yhteyttä,
hentoinen kone ja vähän levytilaa. Lopputuote on siis rendatut MP4:t
(vaakamasteri + pystyversiot + miksatty ääni), ei koskaan linkitettävää
XML:ää. Ääniraidat menevät verkkoon **Opuksena, ei MP3:na** (pienin
enkooderin alku-viive, paras laatu per bitti, kevyt wasm-enkooderi); ennen
julkaisua ajetaan synteettinen synkkatesti: tunnetun siirron pari, molemmat
Opus-koodattuna, pitää palauttaa siirto ±40 ms sisällä (alkuviive
korjautuu dekoodauksessa; testaamatta kunnes tämä on ajettu).

- **Nopea taso — pelkkä selain, proxy-laatu, ~1 h kiertoaika.** Selain
  poimii Opus-ääniraidat ja enkoodaa 720p-proxyt WebCodecsin
  laitteistoenkoodauksella (ystävällinen heikoille koneille; wasm-varatie
  on monta kertaa reaaliaikaa hitaampi ja suurin riski). Lataus on ~2-2,5
  Gt per shown tunti jatkuvina palasina. Palvelin ajaa nykyisen moottorin
  ja palauttaa proxy-laatuiset MP4:t. Asiakas vain valitsee tiedostot.
- **Täysi taso — täyslaatuinen uudelleenrenderöinti samojen päätösten
  päälle.** Ensimmäisen tason leikkaus toimii EDL-tyyppisenä
  päätöslistana; kameroiden alkuperäiset latautuvat taustalla (kymmeniä
  gigoja per jakso), mieluiten pienen työpöytälataajan kautta, koska
  selainvälilehden pitäisi olla auki koko siirron ajan. Palvelin rendaa
  uudelleen täydellä laadulla alkuperäisistä. Hinnoittelu sen mukaan mitä
  oikeasti maksaa: säilytys, liikenne ulos, täysresoluutioinen
  CPU-enkoodaus.
- **Riskit:** kymmenien gigojen alkuperäissäilytys per jakso ja sen
  säilytys-/poistopolitiikka; täysresoluutioisen CPU-enkoodauksen kesto
  mittaamatta; ensimmäisen tason jälkeen tehdyt muokkaukset pitää viedä
  mukana uudelleenrenderöintiin (päätöslistan on pysyttävä ainoana
  totuutena).

## Inserts: stills and video on screen (slideshow / B-roll)

Not started. Roadmap only (decided 2026-11-12). Show a still or a video clip over the picture while the hosts talk about it, for example a car image during a car segment.

### Idea
- A new "inserts" lane of video-only clips above the picture, the same pattern as reaction shots (connected clips on a positive lane, video only, enabled by default, one selection to remove).
- One shared clip list drives both the FCPXML export and Render video, so the two cannot drift. Titles, music-bed and credits clips (the "Package" idea) would use the same lane writer and renderer.
- Per item: start and length, fill with crop, fit with blurred background, or picture-in-picture; Ken Burns zoom and pan on stills; alpha PNG; fade in and out; video muted by default; optional credit lower third; same list fitted to 9:16 for vertical export.

### Placement
1. Manual first: drop files, drag on the lane, set start and length.
2. Later, transcript-assisted: show the transcript under the lane and click a word to place an insert; simple keyword matching against file names or tags. Model-picked images need a separate decision.
3. Asset source: own folder; Tekstitys' B-roll Reel search (public media, with credits) as a possible picker. Licence and attribution stay with the user.

### Risks and untested parts
- Nothing was imported into Final Cut. All Final Cut behavior is taken from CLAUDE.md, not tested.
- Connected clips can drift on a ripple edit in Final Cut (CLAUDE.md, "Reaction shots"). That matters for an image timed to a word. A nested clip may avoid it, but must be settled by importing.
- The AVFoundation renderer (render_av.py) was not read. Stills, alpha and extra video lanes there are unknown. The ffmpeg overlay path in render.py can composite alpha in principle.
- Ken Burns as keyframed transform on stills is untested.
- Video inserts must stay muted or they sum with the processed microphones (the same issue reaction clips had).
- Transcript code and Tekstitys' B-roll code were not read.
- Rough size: medium for manual placement (the cost is writing and rendering it twice); transcript-assisted is a separate spec.
