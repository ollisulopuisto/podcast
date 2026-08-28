import AVFoundation

/// Miksauksen toisto **ilman renderöintiä**.
///
/// Tämä on koko esikatselun idea. `nhsx-render` summaa näytteet itse, koska
/// se kirjoittaa tiedoston; esikatselun ei tarvitse. Se sijoittaa lähteet
/// aikajanalle ja antaa käyttöjärjestelmän summata ne toiston aikana. Siksi
/// välilyönnin painamisen ja äänen välissä ei ole renderöintiä vaan tiedoston
/// avaus — tunnin istunto on yhtä nopea kuin minuutin.
///
/// ## Solmuja on ryhmä, ei leike
///
/// `AVAudioPlayerNode`n äänenvoimakkuus ja panorointi ovat solmun
/// ominaisuuksia, eivät ajastetun palan. Yksi solmu per leike antaisi
/// oikean tuloksen mutta ei toimisi: vaimennuksen läpi ajettu istunto on
/// satoja pikkualueita raitaa kohden, ja se olisi satoja solmuja.
///
/// Leikkeet ryhmitellään siksi **(puhuja, taso, panorointi)** -kolmikon
/// mukaan, ja ryhmä saa yhden solmun. Käytännössä raidan kaikki alueet
/// jakavat raidan faderin ja panoroinnin, joten pilkottu raita on yksi
/// ryhmä — sama tulos, muutama solmu.
///
/// ## Häivytys on poikkeus, ja siksi se on hybridi
///
/// Häivytystä ei voi ajastaa solmun ominaisuutena palakohtaisesti. Leikkeet
/// joilla **ei** ole häivytystä ajastetaan `scheduleSegment`illä, joka
/// lukee levyltä virtana eikä varaa muistia. Ne harvat joilla on —
/// käytännössä musiikkipohjan alku ja loppu — luetaan puskuriin ja
/// verhokäyrä kerrotaan sisään ennen ajastusta.
///
/// Näin yleinen tapaus on halpa ja harvinainen on oikein, eikä kumpikaan
/// tapaus ole väärin.
///
/// ## Yksi tietoinen ero `nhsx-render`iin
///
/// Panorointi tehdään tässä `AVAudioPlayerNode.pan`illa, eli
/// **käyttöjärjestelmän panorointilailla**, kun `nhsx-render` laskee
/// vakiotehoiset kertoimet itse (`panGains`). Lait ovat lähellä toisiaan
/// mutta eivät välttämättä samat, joten kovasti laidalle ajettu raita voi
/// olla esikatselussa aavistuksen eri tasolla kuin renderöidyssä
/// tiedostossa.
///
/// Ero on tässä tahallinen: oma laki vaatisi kanavakohtaisen käsittelyn,
/// eli jokaisen leikkeen lukemisen puskuriin, mikä veisi juuri sen
/// nopeuden jonka takia esikatselu on olemassa. `Conformance/plan.json`
/// sitoo *suunnitelman* — mikä kuuluu, milloin, millä tasolla ja missä
/// kohtaa kuvaa — eikä toiston viimeistä desibeliä. Kun taso pitää tietää
/// tarkasti, `nhsx-render` kirjoittaa tiedoston.
public final class MixPlayer {

    public enum Failure: Error, CustomStringConvertible {
        /// Nimi **ja syy**. Syy oli aiemmin nielty, ja se maksoi: julkaistu
        /// esikatselu kertoi «ei auennut» eikä mitään muuta, ja kaksi täysin
        /// eri vikaa — hiekkalaatikon esto ja väärin päätelty polku —
        /// näyttivät samalta. Ne erottaa yksi sana: «Operation not
        /// permitted» vastaan «No such file or directory».
        case cannotOpen(name: String, reason: String)
        public var description: String {
            switch self {
            case .cannotOpen(let name, let reason): return "Ääntä ei voi avata: \(name) — \(reason)"
            }
        }
    }

    /// Yhden lähteen epäonnistuminen nimineen ja syineen.
    public struct Unreadable: Equatable {
        public let name: String
        public let reason: String
        public var described: String { "\(name) — \(reason)" }
    }

    private let engine = AVAudioEngine()
    private var nodes: [AVAudioPlayerNode] = []
    private var files: [String: AVAudioFile] = [:]
    private let mix: Mix

    /// Tiedostot, jotka eivät auenneet. Yksi rikkinäinen lähde vaientaa
    /// oman leikkeensä, ei koko esikatselua.
    public private(set) var unreadable: [Unreadable] = []

    public private(set) var isPlaying = false

    /// Mistä ohjelma-ajan kohdasta nykyinen ajastus alkoi.
    private var origin: Double = 0

    /// Asetettu kun toisto on tauolla. Silloin `currentTime` on tämä:
    /// pysähtynyt solmu ei kerro aikaansa.
    private var paused: Double?

    public var isPaused: Bool { paused != nil }

    public init(mix: Mix) {
        self.mix = mix
    }

    public var duration: Double { mix.duration }

    /// Toiston kohta ohjelma-aikana.
    ///
    /// Luetaan äänimoottorin omasta kellosta eikä seinäkellosta. `Timer`
    /// ja ääni ajautuvat erilleen — eri kellot, eri tarkkuus — ja se
    /// ajautuminen näkyy juuri siinä mitä osoitin on olemassa
    /// näyttämään: osoitin ei ole siinä mistä ääni kuuluu. Ero kasvaa
    /// jakson mittaan, joten tunnin istunnossa se on iso.
    public var currentTime: Double {
        if let paused { return paused }
        guard let node = nodes.first,
              let nodeTime = node.lastRenderTime,
              let played = node.playerTime(forNodeTime: nodeTime)
        else { return origin }
        // Ajastus alkaa `zero`sta, joka on hieman tulevaisuudessa: ennen
        // sitä solmun oma aika on negatiivinen.
        let seconds = max(0, Double(played.sampleTime) / played.sampleRate)
        return min(origin + seconds, duration)
    }

    /// Onko jakso soitettu loppuun. Näkymä nollaa säätimet tästä.
    public var hasReachedEnd: Bool { isPlaying && currentTime >= duration }

    /// Avaa lähteet ja rakentaa graafin. Ei vielä soita.
    public func prepare() throws {
        let groups = Dictionary(grouping: mix.clips) {
            GroupKey(speaker: $0.speaker, gain: $0.gain, pan: $0.pan)
        }
        // Järjestetään: sanakirja ei lupaa järjestystä, ja solmujen
        // vaihtuva luomisjärjestys tekisi virhetilanteista sellaisia jotka
        // toistuvat joka toinen kerta.
        for key in groups.keys.sorted(by: { ($0.speaker, $0.gain, $0.pan) < ($1.speaker, $1.gain, $1.pan) }) {
            let clips = groups[key] ?? []
            let node = AVAudioPlayerNode()
            engine.attach(node)
            // Yhteinen muoto: lähteet voivat olla eri taajuudella, ja
            // mikseri hoitaa muunnoksen. `nil` antaisi solmun oman muodon
            // ja kaataisi graafin ensimmäiseen eroavaan tiedostoon.
            engine.connect(node, to: engine.mainMixerNode, format: nil)
            node.volume = Float(key.gain)
            node.pan = Float(key.pan)
            nodes.append(node)
            groupedClips.append((node, clips))
        }
        try engine.start()
    }

    private struct GroupKey: Hashable {
        let speaker: String
        let gain: Double
        let pan: Double
    }

    private var groupedClips: [(AVAudioPlayerNode, [Clip])] = []

    /// Avaa tiedoston kerran ja pitää sen. Sama lähde esiintyy aikajanalla
    /// monta kertaa, eikä sitä kannata avata joka kerta.
    private func file(at path: String) throws -> AVAudioFile {
        if let open = files[path] { return open }
        do {
            let opened = try AVAudioFile(forReading: URL(fileURLWithPath: path))
            files[path] = opened
            return opened
        } catch {
            // `localizedDescription` kantaa POSIX-syyn: eston ja puuttuvan
            // tiedoston ero on juuri se mitä tästä halutaan tietää.
            throw Failure.cannotOpen(
                name: (path as NSString).lastPathComponent,
                reason: error.localizedDescription
            )
        }
    }

    /// Kirjaa lähteen, joka ei auennut. Sama tiedosto vain kerran.
    private func note(_ path: String, _ error: Error) {
        let name = (path as NSString).lastPathComponent
        var reason = error.localizedDescription
        if case .cannotOpen(_, let why)? = error as? Failure { reason = why }
        guard !unreadable.contains(where: { $0.name == name }) else { return }
        unreadable.append(Unreadable(name: name, reason: reason))
    }

    /// Soittaa ohjelman kohdasta `from` (ohjelma-aikaa sekunteina).
    ///
    /// Kutsuttavissa myös kesken toiston: silloin tämä on kelaus.
    public func play(from time: Double = 0) {
        // `stop()` pysäyttää moottorin; uusi soitto käynnistää sen taas.
        // Ilman tätä toinen soitto samalla soittimella olisi hiljaisuutta.
        if !engine.isRunning { try? engine.start() }
        origin = min(max(time, 0), duration)
        paused = nil
        scheduleAll()
        isPlaying = true
    }

    /// Tauko. Kohta jää muistiin, eikä graafia pureta.
    public func pause() {
        guard isPlaying else { return }
        paused = currentTime
        for node in nodes { node.pause() }
        isPlaying = false
    }

    /// Jatkaa tauolta.
    ///
    /// Ajastetaan uudestaan sen sijaan että solmut vain käynnistettäisiin.
    /// `AVAudioPlayerNode`n oma aika tauon yli on asia jota ei voi täältä
    /// mitata, ja jos se laskisi tauon mukaan, osoitin hyppäisi jatkaessa
    /// tauon verran eteenpäin. Uudelleenajastus on halpa — `scheduleSegment`
    /// lukee levyltä virtana — ja se on oikein tietämättä.
    public func resume() {
        guard let at = paused else { return }
        play(from: at)
    }

    /// Kelaa. Soiva jatkaa soimista, tauolla oleva jää tauolle.
    public func seek(to time: Double) {
        let wasPlaying = isPlaying
        play(from: time)
        if !wasPlaying { pause() }
    }

    private func scheduleAll() {
        // Solmun pysäytys tyhjentää aiemman ajastuksen ja nollaa sen oman
        // kellon. Kelaus ilman tätä soittaisi vanhan ja uuden päällekkäin.
        for node in nodes { node.stop() }

        // Yhteinen nollahetki kaikille solmuille: ilman sitä jokainen alkaisi
        // omasta käynnistyshetkestään ja raidat lipsuisivat toisistaan.
        //
        // Hetki lasketaan **nykyisestä** rendausajasta eikä vakiosta.
        // Vakio riitti niin kauan kuin soitin oli kertakäyttöinen ja
        // moottori juuri käynnistetty. Kelaus soittaa saman soittimen
        // uudestaan, ja silloin menneisyydessä oleva hetki tarkoittaa
        // «heti» — eri solmuille eri hetkellä, eli juuri se lipsuminen
        // jota vastaan yhteinen nollahetki on.
        let mixRate = engine.mainMixerNode.outputFormat(forBus: 0).sampleRate
        let reference = nodes.first?.lastRenderTime
        let valid = reference?.isSampleTimeValid == true
        let rate = valid ? (reference?.sampleRate ?? mixRate) : mixRate
        let base = valid ? (reference?.sampleTime ?? 0) : 0
        let zero = AVAudioTime(
            sampleTime: base + AVAudioFramePosition(rate * 0.1), atRate: rate)

        for (node, clips) in groupedClips {
            for clip in clips where clip.end > origin {
                schedule(clip, on: node, origin: origin, zero: zero, rate: rate)
            }
            node.play(at: zero)
        }
    }

    private func schedule(
        _ clip: Clip, on node: AVAudioPlayerNode,
        origin: Double, zero: AVAudioTime, rate: Double
    ) {
        let source: AVAudioFile
        do { source = try file(at: clip.path) } catch {
            note(clip.path, error)
            return
        }

        // Leike voi alkaa ennen soiton aloituskohtaa: silloin siitä
        // kuullaan vain loppuosa, ja lähteestä luetaan vastaavasti
        // myöhempää kohtaa.
        let skipped = max(0, origin - clip.start)
        let heardLength = clip.length - skipped
        guard heardLength > 0 else { return }

        let sourceRate = source.processingFormat.sampleRate
        let startFrame = AVAudioFramePosition((clip.fileOffset + skipped) * sourceRate)
        let frames = AVAudioFrameCount(heardLength * sourceRate)
        guard startFrame >= 0, startFrame < source.length, frames > 0 else { return }
        let available = AVAudioFrameCount(min(Int64(frames), source.length - startFrame))
        guard available > 0 else { return }

        let when = AVAudioTime(
            sampleTime: zero.sampleTime + AVAudioFramePosition((clip.start - origin + skipped) * rate),
            atRate: rate)

        if clip.ramps.isEmpty {
            node.scheduleSegment(
                source, startingFrame: startFrame, frameCount: available,
                at: when, completionHandler: nil)
            return
        }

        // Häivytetty leike puskurin kautta, verhokäyrä sisään kerrottuna.
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: source.processingFormat, frameCapacity: available) else { return }
        do {
            source.framePosition = startFrame
            try source.read(into: buffer, frameCount: available)
        } catch {
            note(clip.path, error)
            return
        }
        applyEnvelope(to: buffer, clip: clip, skipped: skipped, rate: sourceRate)
        node.scheduleBuffer(buffer, at: when, options: [], completionHandler: nil)
    }

    /// Äänenvoimakkuuskäyrä, sama muoto kuin `nhsx-render`issa.
    ///
    /// Luiskat seuraavat toisiaan eivätkä summaudu, joten käyrä ei voi
    /// painua nollan ali. `skipped` on se osa leikkeestä joka on jo mennyt,
    /// kun soitto aloitetaan keskeltä.
    private func applyEnvelope(
        to buffer: AVAudioPCMBuffer, clip: Clip, skipped: Double, rate: Double
    ) {
        guard let channels = buffer.floatChannelData else { return }
        let count = Int(buffer.frameLength)
        guard count > 0 else { return }

        var curve = [Float](repeating: 1, count: count)
        for i in 0..<count {
            curve[i] = Float(clip.level(at: skipped + Double(i) / rate))
        }
        for channel in 0..<Int(buffer.format.channelCount) {
            let samples = channels[channel]
            for i in 0..<count { samples[i] *= curve[i] }
        }
    }

    public func stop() {
        // Myös tauolta: muuten tauolle jäänyt soitin jäisi pystyyn
        // pitämään äänilaitetta, eikä `paused` nollautuisi.
        guard isPlaying || paused != nil else { return }
        for node in nodes { node.stop() }
        engine.stop()
        isPlaying = false
        paused = nil
        origin = 0
    }

    deinit { stop() }
}
