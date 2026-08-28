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
        case cannotOpen(String)
        public var description: String {
            switch self {
            case .cannotOpen(let name): return "Ääntä ei voi avata: \(name)"
            }
        }
    }

    private let engine = AVAudioEngine()
    private var nodes: [AVAudioPlayerNode] = []
    private var files: [String: AVAudioFile] = [:]
    private let mix: Mix

    /// Tiedostot, jotka eivät auenneet. Yksi rikkinäinen lähde vaientaa
    /// oman leikkeensä, ei koko esikatselua.
    public private(set) var unreadable: [String] = []

    public private(set) var isPlaying = false

    public init(mix: Mix) {
        self.mix = mix
    }

    public var duration: Double { mix.duration }

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
            throw Failure.cannotOpen((path as NSString).lastPathComponent)
        }
    }

    /// Soittaa ohjelman kohdasta `from` (ohjelma-aikaa sekunteina).
    public func play(from origin: Double = 0) {
        guard !isPlaying else { return }
        let rate = engine.mainMixerNode.outputFormat(forBus: 0).sampleRate
        // Yhteinen nollahetki kaikille solmuille: ilman sitä jokainen alkaisi
        // omasta käynnistyshetkestään ja raidat lipsuisivat toisistaan.
        let zero = AVAudioTime(sampleTime: AVAudioFramePosition(rate * 0.1), atRate: rate)

        for (node, clips) in groupedClips {
            for clip in clips where clip.end > origin {
                schedule(clip, on: node, origin: origin, zero: zero, rate: rate)
            }
            node.play(at: zero)
        }
        isPlaying = true
    }

    private func schedule(
        _ clip: Clip, on node: AVAudioPlayerNode,
        origin: Double, zero: AVAudioTime, rate: Double
    ) {
        let source: AVAudioFile
        do { source = try file(at: clip.path) } catch {
            let name = (clip.path as NSString).lastPathComponent
            if !unreadable.contains(name) { unreadable.append(name) }
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

        if clip.fadeIn == 0 && clip.fadeOut == 0 {
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
            let name = (clip.path as NSString).lastPathComponent
            if !unreadable.contains(name) { unreadable.append(name) }
            return
        }
        applyEnvelope(to: buffer, clip: clip, skipped: skipped, rate: sourceRate)
        node.scheduleBuffer(buffer, at: when, options: [], completionHandler: nil)
    }

    /// Lineaarinen häivytys sisään ja ulos, sama muoto kuin `nhsx-render`issa.
    ///
    /// `Clip` lupaa että häivytykset mahtuvat (`fadeIn + fadeOut <= length`),
    /// joten käyrät eivät voi mennä ristiin eikä summa painua nollan ali.
    private func applyEnvelope(
        to buffer: AVAudioPCMBuffer, clip: Clip, skipped: Double, rate: Double
    ) {
        guard let channels = buffer.floatChannelData else { return }
        let count = Int(buffer.frameLength)
        let inFrames = Int(max(0, clip.fadeIn - skipped) * rate)
        let outStart = count - Int(clip.fadeOut * rate)

        for channel in 0..<Int(buffer.format.channelCount) {
            let samples = channels[channel]
            if inFrames > 1 {
                for i in 0..<min(inFrames, count) {
                    samples[i] *= Float(Double(i) / Double(inFrames - 1))
                }
            }
            if outStart > 0, outStart < count {
                let span = count - outStart
                for i in outStart..<count {
                    samples[i] *= Float(1 - Double(i - outStart) / Double(span))
                }
            }
        }
    }

    public func stop() {
        guard isPlaying else { return }
        for node in nodes { node.stop() }
        engine.stop()
        isPlaying = false
    }

    deinit { stop() }
}
