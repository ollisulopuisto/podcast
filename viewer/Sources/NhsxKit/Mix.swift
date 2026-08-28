import Foundation

/// Istunto miksauksena: mikä kuuluu, milloin, miten kovaa ja kummalta puolelta.
///
/// `apps/podcast-magic/src/podcastmagic/nhsx/mix.py`:n kaksonen. Jokainen
/// päätös tässä on sama päätös siellä, ja `Conformance/plan.json` on se
/// vastaus, jonka molempien on tuotettava. Kun muutat jompaakumpaa, aja
/// molemmat testit.
///
/// Mitä tässä **ei** ole: taajuuskorjausta, kompressointia eikä Hindenburgin
/// omia ääniprofiileja. Esikatselu on geometria, taso, häivytys ja
/// panorointi — ja juuri siksi se voi olla nopea. Se ei siis kuulosta
/// Hindenburgin toistolta silloin kun istunnossa on käytetty profiileja.

public struct Clip {
    public let path: String
    public let file: String
    public let speaker: String
    public let start: Double
    public let length: Double
    public let fileOffset: Double
    public let gain: Double
    public let pan: Double
    /// Äänenvoimakkuuskäyrä. Luiskat on leikattu leikkeen sisään.
    public let ramps: [Ramp]

    public var end: Double { start + length }

    /// Käyrän arvo `when` sekuntia leikkeen alusta.
    public func level(at when: Double) -> Double {
        var level = 1.0
        for ramp in ramps {
            if when <= ramp.start { return level }
            if when >= ramp.end { level = ramp.gain; continue }
            if ramp.length <= 0 { return ramp.gain }
            return level + (ramp.gain - level) * ((when - ramp.start) / ramp.length)
        }
        return level
    }

    /// Ohjelma-ajasta tiedostoaikaan. Yksi kaava, ja se on kaikki mitä
    /// aikajanasta tarvitsee tietää.
    public func fileTime(at programmeTime: Double) -> Double {
        fileOffset + (programmeTime - start)
    }
}

/// Yksi äänenvoimakkuuskäyrän luiska leikkeen sisällä.
///
/// Hindenburgin `<Fade>` ei ole häivytys hiljaisuuteen vaan **luiska
/// tasolle**: se kulkee edellisestä tasosta arvoon `gain` ajassa `length`
/// ja jää sinne. Mitattu Hindenburgin omasta renderistä; ks.
/// `apps/podcast-magic/tests/test_measured_session.py`.
public struct Ramp: Equatable {
    public let start: Double
    public let length: Double
    public let gain: Double

    public init(start: Double, length: Double, gain: Double) {
        self.start = start
        self.length = length
        self.gain = gain
    }

    public var end: Double { start + length }
}

public struct Mix {
    public var clips: [Clip] = []
    public var duration: Double = 0
    public var muted: Int = 0
    public var missing: [String] = []
    public var unknown: [String: Int] = [:]

    public var speakers: [String] {
        var seen: [String] = []
        for clip in clips where !seen.contains(clip.speaker) { seen.append(clip.speaker) }
        return seen
    }
}

/// Desibelit kertoimeksi.
public func dbToLinear(_ db: Double) -> Double {
    db.isInfinite && db < 0 ? 0 : pow(10, db / 20)
}

/// Panoroinnin kertoimet: **lineaarinen, vakiosummainen, positiivinen vasen**.
///
/// Mitattu Hindenburgin omasta renderistä eikä valittu. Pienimmän
/// neliösumman sovitus `R = k·L` antoi `Pan="0.625"`:lle 0,23027
/// (ennuste 0,23077) ja `Pan="-0.55"`:lle 3,44347 (ennuste 3,44444).
///
/// Tämä oli ennen vakiotehoinen ja **väärin päin**. Väärin päin oleva
/// panorointi on kelvollinen tiedosto, jossa puhujat ovat vaihtaneet
/// puolta: mikään ei kaadu, eikä sitä huomaa muuten kuin kuuntelemalla.
///
/// Asteikon ulkopuolinen arvo **rajataan** eikä kierretä: kierrettynä se
/// olisi negatiivinen vahvistus eli vaihekäännös.
public func panGains(_ pan: Double) -> (left: Double, right: Double) {
    let p = min(max(pan, -1), 1)
    return ((1 + p) / 2, (1 - p) / 2)
}

/// Äänipoolin tiedosto levyltä.
///
/// `Path` on istunnoissa milloin absoluuttinen, milloin istuntoon nähden
/// suhteellinen, milloin pelkkä nimi. Kaikki kolme kokeillaan, ja vasta
/// sitten haetaan nimellä syvemmältä — rekursio on hidas verkkolevyllä.
public func locate(_ file: PoolFile, in session: Session, extraDirectory: String = "") -> String? {
    let manager = FileManager.default
    let raw = file.path.isEmpty ? file.name : file.path
    let name = (raw as NSString).lastPathComponent
    let roots = [extraDirectory, session.audioDirectory,
                 (session.path as NSString).deletingLastPathComponent]
        .filter { !$0.isEmpty }

    if (raw as NSString).isAbsolutePath, manager.fileExists(atPath: raw) { return raw }
    for root in roots {
        for candidate in [(root as NSString).appendingPathComponent(raw),
                          (root as NSString).appendingPathComponent(name)]
        where manager.fileExists(atPath: candidate) {
            return candidate
        }
    }
    for root in roots {
        guard let walker = manager.enumerator(atPath: root) else { continue }
        for case let found as String in walker where (found as NSString).lastPathComponent == name {
            let full = (root as NSString).appendingPathComponent(found)
            var isDirectory: ObjCBool = false
            if manager.fileExists(atPath: full, isDirectory: &isDirectory), !isDirectory.boolValue {
                return full
            }
        }
    }
    return nil
}

/// Istunnon leikkeet ohjelma-aikajanalla, järjestyksessä.
///
/// Ohjelman pituus lasketaan **kaikista** alueista, myös vaimennetuista ja
/// niistä joiden tiedostoa ei löytynyt: aikajana on yhtä pitkä riippumatta
/// siitä kuuluuko sen loppu.
public func plan(_ session: Session, extraDirectory: String = "") -> Mix {
    var mix = Mix()
    var seenMissing: Set<String> = []

    for track in session.tracks {
        let trackGain = dbToLinear(track.gainDb ?? 0)
        let trackPan = min(max(track.pan ?? 0, -1), 1)
        for name in track.unknown { mix.unknown[name, default: 0] += 1 }

        for region in track.regions {
            mix.duration = max(mix.duration, region.end)
            if region.length <= 0 { continue }

            // Tuntemattomat lasketaan ennen vaimennuksen tarkistusta, kuten
            // Pythonissa: vaimennetun alueen outo attribuutti on yhtä lailla
            // asia jota emme osaa lukea.
            for name in region.unknown { mix.unknown[name, default: 0] += 1 }

            if track.muted || region.muted {
                mix.muted += 1
                continue
            }
            guard let info = session.file(id: region.ref) else { continue }
            guard let path = locate(info, in: session, extraDirectory: extraDirectory) else {
                if !seenMissing.contains(info.name) {
                    seenMissing.insert(info.name)
                    mix.missing.append(info.name)
                }
                continue
            }

            let regionPan = min(max(region.pan ?? 0, -1), 1)
            mix.clips.append(Clip(
                path: path,
                file: (path as NSString).lastPathComponent,
                speaker: track.name,
                start: region.start,
                length: region.length,
                fileOffset: region.offset,
                gain: dbToLinear(region.gainDb ?? 0) * trackGain,
                // Raidan panorointi siirtää leikkeen omaa, ei korvaa sitä.
                pan: min(max(regionPan + trackPan, -1), 1),
                ramps: region.ramps
            ))
        }
    }

    mix.clips.sort { ($0.start, $0.speaker) < ($1.start, $1.speaker) }
    return mix
}
