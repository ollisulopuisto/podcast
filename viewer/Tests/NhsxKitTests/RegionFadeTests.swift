import AVFoundation
import XCTest
@testable import NhsxKit

final class RegionFadeTests: XCTestCase {
    private func clip(_ attributes: String, children: String = "") throws -> Clip {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("nhsx-fades-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        FileManager.default.createFile(atPath: directory.appendingPathComponent("bed.wav").path,
                                       contents: Data())
        let path = directory.appendingPathComponent("session.nhsx")
        try """
        <Session><AudioPool><File Id="1" Name="bed.wav"/></AudioPool>
        <Track Name="bed"><Region Ref="1" Start="10" Length="4" Offset="20" \(attributes)>
        \(children)</Region></Track></Session>
        """.write(to: path, atomically: true, encoding: .utf8)
        let mix = plan(try readSession(at: path.path))
        XCTAssertEqual(mix.unknown, [:], "Edge fades must be recognized, rather than ignored")
        return try XCTUnwrap(mix.clips.first)
    }

    func testEdgeFadeAttributesAreRecognized() throws {
        _ = try clip("FadeIn=\"00:00:02\" FadeOut=\"1\"")
    }
    func testFadeDurationsAreBoundedAndInvalidValuesAreIgnored() throws {
        let bounded = try clip("FadeIn=\"8\" FadeOut=\"-1\"")
        XCTAssertEqual(bounded.fadeIn, 4)
        XCTAssertEqual(bounded.fadeOut, 0)
        let invalid = try clip("FadeIn=\"bad\" FadeOut=\"nan\"")
        XCTAssertEqual(invalid.fadeIn, 0)
        XCTAssertEqual(invalid.fadeOut, 0)
        XCTAssertFalse(invalid.hasEnvelope)
    }

    func testMidpointSamplesMatchPythonIncludingOverlappingFades() throws {
        let bed = try clip("FadeIn=\"4\" FadeOut=\"4\"")
        XCTAssertTrue(bed.hasEnvelope)
        // Synthetic 4-second clip at 2 Hz: first/last sample centers
        // lie 1/16 of the way along their respective fades.
        let near = (1 - cos(Double.pi / 16)) / 2
        let far = (1 - cos(Double.pi * 15 / 16)) / 2
        XCTAssertEqual(bed.envelopeLevel(atFrame: 0, sampleRate: 2), near * far, accuracy: 1e-12)
        XCTAssertEqual(bed.envelopeLevel(atFrame: 7, sampleRate: 2), near * far, accuracy: 1e-12)
    }

    func testFadesMultiplyRampsAndSeekUsesOriginalClipFrames() throws {
        let bed = try clip("FadeIn=\"2\" FadeOut=\"1\"",
                           children: "<Fade Start=\"0\" Length=\"1\" Gain=\"-6.020599913279624\"/>")
        // At 2 Hz frame 2 follows the completed ramp (0.5), but is still
        // inside the fade-in: the factor must not restart after seeking.
        let fade = (1 - cos(Double.pi * 2.5 / 4)) / 2
        XCTAssertEqual(bed.envelopeLevel(atFrame: 2, sampleRate: 2), 0.5 * fade, accuracy: 1e-12)
        XCTAssertEqual(bed.envelopeLevel(atFrame: 5, sampleRate: 2), 0.5, accuracy: 1e-12)
        XCTAssertEqual(bed.envelopeLevel(atFrame: 7, sampleRate: 2),
                       0.5 * (1 - cos(Double.pi / 4)) / 2, accuracy: 1e-12)
    }

    func testPlaybackBufferAppliesTheEnvelopeToEveryChannelAfterSeeking() throws {
        let bed = try clip("FadeIn=\"2\" FadeOut=\"1\"")
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 2, channels: 2))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 6))
        buffer.frameLength = 6
        let channels = try XCTUnwrap(buffer.floatChannelData)
        for channel in 0..<2 {
            for frame in 0..<6 { channels[channel][frame] = 1 }
        }
        MixPlayer.applyEnvelope(to: buffer, clip: bed, skipped: 1, rate: 2)
        for channel in 0..<2 {
            for frame in 0..<6 {
                XCTAssertEqual(Double(channels[channel][frame]),
                               bed.envelopeLevel(atFrame: frame + 2, sampleRate: 2), accuracy: 1e-7)
            }
        }
    }

}
