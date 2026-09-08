import Accelerate
import Foundation

/// Fast float32 ↔ PCM16 conversion (16-bit little-endian, clamped).
/// Used for cloud uploads, Grok WebSocket frames, and the long-capture spill file.
public enum PCMCodec {
    public static func int16Data(from samples: [Float]) -> Data {
        samples.withUnsafeBufferPointer { int16Data(from: $0) }
    }

    public static func int16Data(from samples: UnsafeBufferPointer<Float>) -> Data {
        let n = samples.count
        guard n > 0 else { return Data() }
        var scaled = [Float](repeating: 0, count: n)
        var scale: Float = 32767
        samples.baseAddress!.withMemoryRebound(to: Float.self, capacity: n) { src in
            vDSP_vsmul(src, 1, &scale, &scaled, 1, vDSP_Length(n))
        }
        var lo: Float = -32768
        var hi: Float = 32767
        vDSP_vclip(scaled, 1, &lo, &hi, &scaled, 1, vDSP_Length(n))
        var ints = [Int16](repeating: 0, count: n)
        vDSP_vfixr16(scaled, 1, &ints, 1, vDSP_Length(n))
        return ints.withUnsafeBufferPointer { Data(buffer: $0) }
    }

    public static func floats(fromInt16 data: Data) -> [Float] {
        let n = data.count / MemoryLayout<Int16>.size
        guard n > 0 else { return [] }
        var ints = [Int16](repeating: 0, count: n)
        _ = ints.withUnsafeMutableBytes { dst in
            data.copyBytes(to: dst, count: n * MemoryLayout<Int16>.size)
        }
        var out = [Float](repeating: 0, count: n)
        vDSP_vflt16(ints, 1, &out, 1, vDSP_Length(n))
        var scale: Float = 1.0 / 32767.0
        vDSP_vsmul(out, 1, &scale, &out, 1, vDSP_Length(n))
        return out
    }
}
