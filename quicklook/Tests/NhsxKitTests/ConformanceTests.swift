import XCTest
@testable import NhsxKit

/// Kaksi toteutusta, yksi vastaus.
///
/// Tämä on `apps/podcast-magic/tests/test_conformance.py`:n kaksonen. Ne
/// lukevat saman istunnon ja saman kirjatun vastauksen, eivätkä jaa
/// riviäkään koodia — laajennus on hiekkalaatikossa eikä voi käynnistää
/// Pythonia, joten koodin jakaminen ei ole vaihtoehto. Vastauksen jakaminen
/// on.
///
/// Jos nämä eroavat, esikatselu näyttää eri jakson kuin `nhsx-render`
/// renderöi — eikä kumpikaan kaadu, mikä on juuri tämän talon vikaluokka.
final class ConformanceTests: XCTestCase {

    /// `quicklook/Conformance/`, tämän tiedoston paikan kautta.
    ///
    /// Ei SwiftPM-resurssina: fikstuuri on kahden kielen yhteinen eikä
    /// kummankaan paketin sisus, ja resurssiksi niputettuna Python-puoli
    /// lukisi eri tiedostoa kuin tämä.
    static var conformanceDirectory: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // NhsxKitTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // quicklook
            .appendingPathComponent("Conformance")
    }

    struct ExpectedClip: Decodable, Equatable {
        let file: String
        let speaker: String
        let start: Double
        let length: Double
        let file_offset: Double
        let gain: Double
        let pan: Double
        let fade_in: Double
        let fade_out: Double
    }

    struct ExpectedPlan: Decodable {
        let version: Int
        let duration: Double
        let muted: Int
        let unknown: [String: Int]
        let speakers: [String]
        let clips: [ExpectedClip]
    }

    /// Suunnitelman muoto, jonka tämä osaa lukea. Tuntemattomasta
    /// versiosta kieltäydytään mieluummin kuin luetaan se väärin.
    static let planVersion = 1

    /// Poolin tiedostot tehdään testissä: suunnitelma ei lue ääntä, se vain
    /// tarkistaa että tiedosto on olemassa. Repositorio pysyy tekstinä.
    private func stage() throws -> Session {
        let directory = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("nhsx-conformance-\(UUID().uuidString)")
        try FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }

        let session = directory.appendingPathComponent("session.nhsx")
        try FileManager.default.copyItem(
            at: Self.conformanceDirectory.appendingPathComponent("session.nhsx"), to: session)
        for name in ["olli.wav", "panu.wav", "musiikki.wav"] {
            FileManager.default.createFile(
                atPath: directory.appendingPathComponent(name).path, contents: Data())
        }
        return try readSession(at: session.path)
    }

    private func expected() throws -> ExpectedPlan {
        let data = try Data(
            contentsOf: Self.conformanceDirectory.appendingPathComponent("plan.json"))
        return try JSONDecoder().decode(ExpectedPlan.self, from: data)
    }

    func testTheFixtureAndItsAnswerAreBothHere() throws {
        let directory = Self.conformanceDirectory
        XCTAssertTrue(FileManager.default.fileExists(
            atPath: directory.appendingPathComponent("session.nhsx").path))
        XCTAssertTrue(FileManager.default.fileExists(
            atPath: directory.appendingPathComponent("plan.json").path))
    }

    func testThePlanVersionIsTheOneWeUnderstand() throws {
        XCTAssertEqual(try expected().version, Self.planVersion)
    }

    /// Tämä on se testi. Python-puolella on sen kaksonen.
    func testThisImplementationProducesTheAgreedPlan() throws {
        let want = try expected()
        let got = plan(try stage())

        XCTAssertEqual(got.duration, want.duration, accuracy: 1e-6, "ohjelman pituus")
        XCTAssertEqual(got.muted, want.muted, "vaimennettujen alueiden määrä")
        XCTAssertEqual(got.unknown, want.unknown, "tuntemattomat attribuutit")
        XCTAssertEqual(got.speakers, want.speakers, "puhujat järjestyksessä")
        XCTAssertEqual(got.clips.count, want.clips.count, "leikkeiden määrä")

        for (index, pair) in zip(got.clips, want.clips).enumerated() {
            let (mine, theirs) = pair
            let where_ = "leike \(index) (@\(theirs.start) s, \(theirs.speaker))"
            XCTAssertEqual(mine.file, theirs.file, "\(where_): tiedosto")
            XCTAssertEqual(mine.speaker, theirs.speaker, "\(where_): puhuja")
            XCTAssertEqual(mine.start, theirs.start, accuracy: 1e-6, "\(where_): alku")
            XCTAssertEqual(mine.length, theirs.length, accuracy: 1e-6, "\(where_): pituus")
            XCTAssertEqual(mine.fileOffset, theirs.file_offset, accuracy: 1e-6,
                           "\(where_): tiedosto-offset")
            XCTAssertEqual(mine.gain, theirs.gain, accuracy: 1e-6, "\(where_): taso")
            XCTAssertEqual(mine.pan, theirs.pan, accuracy: 1e-6, "\(where_): panorointi")
            XCTAssertEqual(mine.fadeIn, theirs.fade_in, accuracy: 1e-6, "\(where_): häivytys sisään")
            XCTAssertEqual(mine.fadeOut, theirs.fade_out, accuracy: 1e-6, "\(where_): häivytys ulos")
        }
    }

    /// Sama kuin Python-puolen samanniminen testi: jos vastaus joskus
    /// luodaan uudestaan väärästä koodista, tämä kertoo *mikä* päätös
    /// muuttui eikä vain että tiedostot eroavat.
    func testTheAnswerCoversEveryDecisionTheSessionWasBuiltToTest() throws {
        let want = try expected()
        let byStart = Dictionary(uniqueKeysWithValues: want.clips.map { ($0.start, $0) })

        XCTAssertEqual(want.duration, 40.0)          // myös vaimennettu raita pidentää
        XCTAssertEqual(want.muted, 3)                // "True", "1" ja vaimennettu raita
        XCTAssertEqual(want.unknown, ["Volyymi": 1]) // tuntematon kerrotaan
        XCTAssertEqual(want.clips.count, 6)          // nollan mittainen ei ole leike

        XCTAssertEqual(byStart[2.0]?.file_offset, 30.0)     // tiedostoaika ≠ ohjelma-aika
        XCTAssertEqual(byStart[12.0]?.file_offset, 120.5)   // sama tiedosto toisesta kohdasta
        XCTAssertEqual(byStart[1.0]?.gain, 0.25)            // raita × alue
        XCTAssertEqual(byStart[1.0]?.pan, 0.3)              // raita siirtää aluetta
        XCTAssertEqual(byStart[14.0]?.length, 2.5)          // kaksoispistemuotoinen aika
        XCTAssertEqual(byStart[14.0]?.file_offset, 5.25)
        XCTAssertEqual(byStart[30.0]?.fade_in, 0.5)         // 2 s + 2 s sekunnin leikkeessä
        XCTAssertEqual(byStart[30.0]?.fade_out, 0.5)
        XCTAssertEqual(byStart[0.0]?.fade_in, 1.5)          // mahtuvia ei kutisteta
        XCTAssertEqual(byStart[0.0]?.fade_out, 3.0)
    }

    // MARK: - Yksikkötestit niille kohdille, joissa Swift eroaa Pythonista

    func testTimesReadInBothFormats() {
        XCTAssertEqual(timeToSeconds("12.500"), 12.5, accuracy: 1e-9)
        XCTAssertEqual(timeToSeconds("00:00:12.500"), 12.5, accuracy: 1e-9)
        XCTAssertEqual(timeToSeconds("34:46.400"), 2086.4, accuracy: 1e-9)
        XCTAssertEqual(timeToSeconds("01:05:03"), 3903, accuracy: 1e-9)
        // Kelvoton on nolla eikä virhe.
        XCTAssertEqual(timeToSeconds("kissa"), 0)
        XCTAssertEqual(timeToSeconds(nil), 0)
        XCTAssertEqual(timeToSeconds(""), 0)
    }

    func testTheCentreIsThreeDecibelsDownOnEachSide() {
        let (left, right) = panGains(0)
        XCTAssertEqual(left, right, accuracy: 1e-12)
        XCTAssertEqual(20 * log10(left), -3.0103, accuracy: 1e-4)
        for pan in [-1.0, -0.5, 0, 0.5, 1.0] {
            let (l, r) = panGains(pan)
            XCTAssertEqual(l * l + r * r, 1, accuracy: 1e-12, "teho ei säily kohdassa \(pan)")
        }
    }

    func testAPanOutsideTheScaleIsClampedNotWrapped() {
        XCTAssertEqual(panGains(-4).left, panGains(-1).left, accuracy: 1e-12)
        XCTAssertEqual(panGains(4).right, panGains(1).right, accuracy: 1e-12)
    }

    func testDecibelsBecomeALinearFactor() {
        XCTAssertEqual(dbToLinear(0), 1, accuracy: 1e-12)
        XCTAssertEqual(dbToLinear(-6.0206), 0.5, accuracy: 1e-4)
        XCTAssertEqual(dbToLinear(-.infinity), 0)
    }

    /// Nimiavaruus on se kohta, jossa Swiftin XML-rajapinta eroaa
    /// Pythonin `lxml`istä eniten: `elements(forName:)` vertaa kokonimeen ja
    /// löytäisi nimiavaruudellisesta istunnosta nolla osumaa.
    func testANamespacedSessionReadsTheSame() throws {
        let plain = try String(
            contentsOf: Self.conformanceDirectory.appendingPathComponent("session.nhsx"),
            encoding: .utf8)
        let namespaced = plain.replacingOccurrences(
            of: "<Session Name=", with: "<Session xmlns=\"urn:hindenburg\" Name=")

        let directory = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("nhsx-ns-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        let session = directory.appendingPathComponent("session.nhsx")
        try namespaced.write(to: session, atomically: true, encoding: .utf8)
        for name in ["olli.wav", "panu.wav", "musiikki.wav"] {
            FileManager.default.createFile(
                atPath: directory.appendingPathComponent(name).path, contents: Data())
        }

        let got = plan(try readSession(at: session.path))
        let want = try expected()
        XCTAssertEqual(got.clips.count, want.clips.count)
        XCTAssertEqual(got.duration, want.duration, accuracy: 1e-6)
        XCTAssertEqual(got.unknown, want.unknown)
    }
}
