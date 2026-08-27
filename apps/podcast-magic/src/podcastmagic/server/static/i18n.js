'use strict';

/* Käyttöliittymän tekstit. Palvelimen omat viestit (lokirivit, virheet)
   tulevat suomeksi palvelimelta; tässä ovat vain selaimen omat. */

const STRINGS = {
  fi: {
    'app.session': 'Istunto',
    'app.browse': 'Selaa…',
    'app.change': 'Vaihda…',
    'app.tools': 'Työkalut',
    'app.options': 'Valinnat',
    'app.log': 'Loki',
    'app.cancel': 'Keskeytä',
    'app.progress': 'Työn kulku',
    'app.up': '⬆ ylempi kansio',
    'app.noSessions': 'Ei .nhsx-tiedostoja tässä kansiossa.',
    'app.pickFirst': 'Valitse ensin istuntotiedosto.',
    'app.notFound': 'Tiedostoa ei löydy.',
    'app.busy': 'Toinen työ on kesken.',
    'app.done': 'Valmis:',
    'app.failed': 'Epäonnistui:',
    'app.cancelled': 'Keskeytetty.',
    'app.reveal': 'Näytä Finderissa',
    'app.noFfmpeg': 'ffmpeg puuttuu. Ilman sitä ääntä ei voi purkaa. Asenna: brew install ffmpeg',
    'app.noServer': 'Palvelin ei vastaa: {error}',
    'app.words': '{n} sanaa istunnossa',
    'app.noWords': 'Ei litterointia — aja ensin litterointi.',
    'app.fileProgress': 'tämä tiedosto {p} %',
    'app.allProgress': 'kaikki {p} %',
    'app.spent': 'kulunut {t}',
    'app.left': 'jäljellä n. {t}',

    'tr.engine': 'Moottori',
    'tr.engineAuto': 'Automaattinen (nopein asennettu)',
    'tr.model': 'Malli',
    'tr.language': 'Kieli',
    'tr.languageAuto': 'Tunnista automaattisesti',
    'tr.fillers': 'Täytesanat mukaan',
    'tr.fillersWhy': 'Whisper siistii puheen oletuksena. Leikkuri tarvitsee myös «tota noin» — se on puhetta, ja ilman sitä se vaimennetaan.',
    'tr.vad': 'Hiljaisuuden suodatus',
    'tr.vadWhy': 'Estää mallia keksimästä sanoja tauolle.',
    'tr.prompt': 'Aloitusvihje',
    'tr.promptWhy': 'Nimiä ja termejä, jotka malli kirjoittaa muuten väärin.',
    'tr.paragraphs': 'Jaa kappaleisiin',
    'tr.paragraphsWhy': 'Käsikirjoitusnäkymä vierittää ja korostaa kappaleittain. Pois päältä kaikki menee yhteen kappaleeseen, kuten Colab-muistikirjassa — vertailua varten.',
    'tr.verify': 'Tarkista litterointi',
    'tr.force': 'Litteroi uudestaan',
    'tr.forceWhy': 'Ohittaa sekä istunnossa valmiina olevan litteroinnin että levyn JSONit.',
    'tr.run': 'Litteroi',
    'tr.plan': 'Mitä tehdään',
    'tr.todo': 'litteroidaan',
    'tr.skipped': 'jo litteroitu',
    'tr.missing': 'ei löydy levyltä',
    'tr.file': 'Tiedosto',
    'tr.state': 'Tila',
    'tr.noBackend': 'Yhtään Whisper-moottoria ei ole asennettu.',
    'tr.installHint': 'Asenna: {cmd}',
    'tr.nothing': 'Ei mitään litteroitavaa — kaikki poolin tiedostot on jo käsitelty.',

    'si.preset': 'Esivalinta',
    'si.preset.remote': 'Etäyhteys, ei vuotoa',
    'si.preset.bleed': 'Mikit vuotavat, tiukka',
    'si.preset.custom': 'Oma',
    'si.tail': 'Häntä',
    'si.tailWhy': 'Puhetta jätetään tämän verran sanan molemmin puolin.',
    'si.gap': 'Lyhin tauko',
    'si.gapWhy': 'Tätä lyhyempää taukoa ei vaimenneta.',
    'si.rms': 'Tarkista myös äänen taso',
    'si.rmsWhy': 'Kun mikit vuotavat, Whisper kuulee naapurin puheen myös tästä mikistä. Taso erottaa oman puheen vuodosta.',
    'si.threshold': 'Kynnys',
    'si.dominance': 'Erotus kovimpaan',
    'si.dominanceWhy': 'Samassa huoneessa jokainen mikki kuulee jokaisen. Vuoto on mediaanissa 12,8 dB hiljempaa kuin sama puhe omalla mikillä, joten sana jää sille raidalle jolla se on kovimmillaan — ja niille jotka ovat tämän sisällä siitä. Nolla ottaa vertailun pois.',
    'si.run': 'Vaimenna',
    'si.preview': 'Laske ennakko',
    'si.track': 'Raita',
    'si.trackWords': 'Sanoja',
    'si.zones': 'Kuuluvia jaksoja',
    'si.audible': 'Kuuluvaa aikaa',
    'si.heard': 'Auki',
    'si.muted': 'Vaiti',
    'si.rmsLater': 'Tason tarkistus tehdään vasta ajossa — nämä luvut ovat ilman sitä.',
    'si.quiet': 'Liian hiljaisia',
    'si.bled': 'Vuotoa',
    'si.untouched': 'ei kosketa',
  },

  en: {
    'app.session': 'Session',
    'app.browse': 'Browse…',
    'app.change': 'Change…',
    'app.tools': 'Tools',
    'app.options': 'Options',
    'app.log': 'Log',
    'app.cancel': 'Cancel',
    'app.progress': 'Progress',
    'app.up': '⬆ parent folder',
    'app.noSessions': 'No .nhsx files in this folder.',
    'app.pickFirst': 'Choose a session file first.',
    'app.notFound': 'File not found.',
    'app.busy': 'Another job is running.',
    'app.done': 'Done:',
    'app.failed': 'Failed:',
    'app.cancelled': 'Cancelled.',
    'app.reveal': 'Show in Finder',
    'app.noFfmpeg': 'ffmpeg is missing. Without it no audio can be decoded. Install: brew install ffmpeg',
    'app.noServer': 'The server is not answering: {error}',
    'app.words': '{n} words in the session',
    'app.noWords': 'No transcription — run the transcriber first.',
    'app.fileProgress': 'this file {p} %',
    'app.allProgress': 'all files {p} %',
    'app.spent': '{t} elapsed',
    'app.left': 'about {t} left',

    'tr.engine': 'Engine',
    'tr.engineAuto': 'Automatic (fastest installed)',
    'tr.model': 'Model',
    'tr.language': 'Language',
    'tr.languageAuto': 'Detect automatically',
    'tr.fillers': 'Keep filler words',
    'tr.fillersWhy': 'Whisper tidies speech up by default. The silencer needs the “um” too — it is speech, and without it the pause gets muted.',
    'tr.vad': 'Silence filtering',
    'tr.vadWhy': 'Stops the model inventing words for a pause.',
    'tr.prompt': 'Initial prompt',
    'tr.promptWhy': 'Names and terms the model otherwise spells wrong.',
    'tr.paragraphs': 'Split into paragraphs',
    'tr.paragraphsWhy': 'The script view scrolls and highlights by paragraph. Off puts everything in one paragraph, as the Colab notebook did — for comparison.',
    'tr.verify': 'Check the transcription',
    'tr.force': 'Transcribe again',
    'tr.forceWhy': 'Ignores both the transcription already in the session and the JSON files on disk.',
    'tr.run': 'Transcribe',
    'tr.plan': 'What will happen',
    'tr.todo': 'to transcribe',
    'tr.skipped': 'already transcribed',
    'tr.missing': 'not found on disk',
    'tr.file': 'File',
    'tr.state': 'State',
    'tr.noBackend': 'No Whisper engine is installed.',
    'tr.installHint': 'Install: {cmd}',
    'tr.nothing': 'Nothing to transcribe — every file in the pool is done.',

    'si.preset': 'Preset',
    'si.preset.remote': 'Remote recording, no bleed',
    'si.preset.bleed': 'Microphones bleed, aggressive',
    'si.preset.custom': 'Custom',
    'si.tail': 'Tail',
    'si.tailWhy': 'This much speech is kept on either side of a word.',
    'si.gap': 'Shortest gap',
    'si.gapWhy': 'A pause shorter than this is not muted.',
    'si.rms': 'Check the audio level too',
    'si.rmsWhy': 'When microphones bleed, Whisper hears the other person on this one as well. Level tells own speech from bleed; text cannot.',
    'si.threshold': 'Threshold',
    'si.dominance': 'Margin to loudest',
    'si.dominanceWhy': 'In one room every microphone hears everyone. Bleed is a median 12.8 dB quieter than the same speech on its own microphone, so a word stays on the track where it is loudest — and on any within this margin of it. Zero turns the comparison off.',
    'si.run': 'Mute the silence',
    'si.preview': 'Estimate',
    'si.track': 'Track',
    'si.trackWords': 'Words',
    'si.zones': 'Audible spans',
    'si.audible': 'Audible time',
    'si.heard': 'Open',
    'si.muted': 'Muted',
    'si.rmsLater': 'The level check runs only in the job itself — these numbers are without it.',
    'si.quiet': 'Too quiet',
    'si.bled': 'Bleed',
    'si.untouched': 'left alone',
  },
};

const I18N = {
  lang: 'fi',

  detect() {
    const stored = (() => { try { return localStorage.getItem('pm.lang'); } catch { return null; } })();
    if (stored && STRINGS[stored]) return stored;
    const nav = (navigator.language || 'fi').slice(0, 2).toLowerCase();
    return STRINGS[nav] ? nav : 'en';
  },

  set(lang) {
    if (!STRINGS[lang]) return;
    this.lang = lang;
    try { localStorage.setItem('pm.lang', lang); } catch { /* yksityinen ikkuna */ }
    document.documentElement.lang = lang;
  },

  t(key, vars) {
    const table = STRINGS[this.lang] || STRINGS.fi;
    let text = table[key] ?? STRINGS.fi[key] ?? key;
    if (vars) {
      for (const [name, value] of Object.entries(vars)) {
        text = text.replaceAll(`{${name}}`, String(value));
      }
    }
    return text;
  },

  apply(root) {
    (root || document).querySelectorAll('[data-t]').forEach((el) => {
      el.textContent = this.t(el.dataset.t);
    });
  },
};
