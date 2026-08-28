import Foundation

/// Hindenburgin istuntotiedoston luku.
///
/// Tämä on `apps/podcast-magic/src/podcastmagic/nhsx/read.py`:n kaksonen.
/// Ne eivät jaa riviäkään koodia — laajennus on hiekkalaatikossa eikä voi
/// käynnistää Pythonia — joten ainoa asia joka pitää ne samaa mieltä on
/// `Conformance/`in istunto ja sen kirjattu vastaus, jota molemmat testaavat
/// itseään vasten.
///
/// Kaksi asiaa, jotka on helppo tehdä väärin ja jotka eivät kaadu:
///
/// * **Nimiavaruudet.** Hindenburgin viemät istunnot ovat joskus
///   nimiavaruudessa ja joskus eivät. Siksi elementit ja attribuutit haetaan
///   *paikallisnimellä*, ei `elements(forName:)`illä, joka vertaa
///   kokonimeen ja löytää nimiavaruudellisesta istunnosta nolla osumaa.
/// * **Aikamuoto.** `Start="12.500"` ja `Start="00:00:12.500"` ovat sama
///   hetki. Kelvoton arvo on nolla eikä virhe: yksi sekaisin mennyt
///   attribuutti ei saa kaataa koko esikatselua.

public enum NhsxError: Error, CustomStringConvertible {
    case unreadable(String)
    case notASession

    public var description: String {
        switch self {
        case .unreadable(let why): return "Istuntoa ei voi lukea: \(why)"
        case .notASession: return "Tiedostosta ei löytynyt äänipoolia eikä raitoja."
        }
    }
}

// MARK: - XML paikallisnimellä

extension XMLElement {
    /// Suorat lapsielementit paikallisnimellä.
    func children(named name: String) -> [XMLElement] {
        guard let kids = children else { return [] }
        return kids.compactMap { $0 as? XMLElement }
            .filter { ($0.localName ?? $0.name ?? "") == name }
    }

    /// Kaikki jälkeläiset paikallisnimellä, tämä mukaan lukien.
    func descendants(named name: String) -> [XMLElement] {
        var found: [XMLElement] = []
        if (localName ?? self.name ?? "") == name { found.append(self) }
        for kid in children?.compactMap({ $0 as? XMLElement }) ?? [] {
            found.append(contentsOf: kid.descendants(named: name))
        }
        return found
    }

    /// Ensimmäinen jälkeläinen paikallisnimellä.
    func firstDescendant(named name: String) -> XMLElement? {
        descendants(named: name).first
    }

    /// Attribuutin arvo paikallisnimellä.
    func attr(_ name: String) -> String? {
        for node in attributes ?? [] where (node.localName ?? node.name ?? "") == name {
            return node.stringValue
        }
        return nil
    }

    /// Attribuuttien paikallisnimet.
    var attributeNames: [String] {
        (attributes ?? []).map { $0.localName ?? $0.name ?? "" }.filter { !$0.isEmpty }
    }

    var local: String { localName ?? name ?? "" }
}

// MARK: - Ajat

/// Aika sekunteina, muodossa `123.45` tai `[HH:]MM:SS[.mmm]`.
///
/// Kelvoton arvo on nolla eikä virhe — sama päätös kuin Pythonin
/// `time_to_seconds`issa, ja se on osa yhteistä vastausta.
public func timeToSeconds(_ value: String?) -> Double {
    guard let value, !value.isEmpty else { return 0 }
    if value.contains(":") {
        var total = 0.0
        var scale = 1.0
        for part in value.split(separator: ":").reversed() {
            guard let n = Double(part) else { return 0 }
            total += n * scale
            scale *= 60
        }
        return total
    }
    return Double(value) ?? 0
}

// MARK: - Malli

public struct PoolFile {
    public let id: String
    public let name: String
    public let path: String
}

public struct Region {
    public let ref: String
    public let start: Double
    public let length: Double
    public let offset: Double
    public let muted: Bool
    public let gainDb: Double?
    public let pan: Double?
    public let fadeIn: Double
    public let fadeOut: Double
    /// Attribuutit ja lapsielementit, joita tämä ei osaa lukea.
    public let unknown: [String]

    public var end: Double { start + length }
}

public struct Track {
    public let name: String
    public let muted: Bool
    public let gainDb: Double?
    public let pan: Double?
    public let regions: [Region]
    public let unknown: [String]
}

public struct Session {
    public let path: String
    public let name: String
    public let audioDirectory: String
    public let files: [PoolFile]
    public let tracks: [Track]

    public func file(id: String) -> PoolFile? {
        files.first { $0.id == id }
    }
}

// MARK: - Mitä osataan lukea

/// Alueen attribuutit, jotka luetaan. Sama käsin kirjoitettu lista kuin
/// Pythonin `KNOWN_REGION_ATTRS` — ja samasta syystä käsin: nimi ei saa
/// livahtaa tunnettujen joukkoon ilman että joku päätti niin.
public let knownRegionAttributes: Set<String> = [
    "Ref", "Start", "Length", "Offset", "Muted", "Name", "Gain", "Pan",
]

public let knownTrackAttributes: Set<String> = ["Name", "Gain", "Pan", "Muted"]

public let fadeElement = "Fade"

/// `Muted` on eri istunnoissa `True`, `true` tai `1`.
func truthy(_ value: String?) -> Bool {
    guard let value else { return false }
    return ["true", "1", "yes"].contains(value.trimmingCharacters(in: .whitespaces).lowercased())
}

// MARK: - Luku

public func readSession(at path: String) throws -> Session {
    let url = URL(fileURLWithPath: path)
    let document: XMLDocument
    do {
        document = try XMLDocument(contentsOf: url, options: [.nodePreserveWhitespace])
    } catch {
        throw NhsxError.unreadable(error.localizedDescription)
    }
    guard let root = document.rootElement() else { throw NhsxError.notASession }

    let pool = root.firstDescendant(named: "AudioPool")
    var files: [PoolFile] = []
    if let pool {
        for element in pool.children(named: "File") {
            files.append(PoolFile(
                id: element.attr("Id") ?? "",
                name: element.attr("Name") ?? "",
                path: element.attr("Path") ?? element.attr("Name") ?? ""
            ))
        }
    }

    var tracks: [Track] = []
    for element in root.descendants(named: "Track") {
        var regions: [Region] = []
        for node in element.children(named: "Region") {
            var unknown = node.attributeNames.filter { !knownRegionAttributes.contains($0) }
            var fadeIn = 0.0
            var fadeOut = 0.0
            for kid in node.children?.compactMap({ $0 as? XMLElement }) ?? [] {
                if kid.local == fadeElement {
                    fadeIn = max(fadeIn, timeToSeconds(kid.attr("In")))
                    fadeOut = max(fadeOut, timeToSeconds(kid.attr("Out")))
                } else if !kid.local.isEmpty {
                    unknown.append(kid.local)
                }
            }
            regions.append(Region(
                ref: node.attr("Ref") ?? "",
                start: timeToSeconds(node.attr("Start")),
                length: timeToSeconds(node.attr("Length")),
                offset: timeToSeconds(node.attr("Offset")),
                muted: truthy(node.attr("Muted")),
                gainDb: node.attr("Gain").flatMap(Double.init),
                pan: node.attr("Pan").flatMap(Double.init),
                fadeIn: fadeIn,
                fadeOut: fadeOut,
                unknown: unknown
            ))
        }
        tracks.append(Track(
            name: element.attr("Name") ?? "",
            muted: truthy(element.attr("Muted")),
            gainDb: element.attr("Gain").flatMap(Double.init),
            pan: element.attr("Pan").flatMap(Double.init),
            regions: regions,
            unknown: element.attributeNames
                .filter { !knownTrackAttributes.contains($0) }
                .map { "Track/\($0)" }
        ))
    }

    if pool == nil && tracks.isEmpty { throw NhsxError.notASession }

    // Äänipoolin `Path` on suhteellinen istuntoon nähden ja usein tyhjä;
    // istunnon oma hakemisto on silloin oikea oletus eikä varasija.
    let base = url.deletingLastPathComponent()
    let poolPath = (pool?.attr("Path") ?? "").trimmingCharacters(in: .whitespaces)
    let audioDirectory = poolPath.isEmpty
        ? base.path
        : URL(fileURLWithPath: poolPath, relativeTo: base).standardized.path

    return Session(
        path: path,
        name: root.attr("Name") ?? url.deletingPathExtension().lastPathComponent,
        audioDirectory: audioDirectory,
        files: files,
        tracks: tracks
    )
}
