import Foundation

/// 16 kHz capture buffer that keeps only a short RAM tail and spills older
/// samples to a PCM16 temp file so hour-long dictation does not grow RSS.
public final class SampleRing: @unchecked Sendable {
    public let sampleRate: Int
    public let ramCapSamples: Int
    public let keepTailSamples: Int

    private let lock = NSLock()
    private var ram: [Float] = []
    /// Absolute index of `ram[0]` in the session (samples already spilled).
    private var ramStart = 0
    private var spilledURL: URL?
    private var spilledHandle: FileHandle?
    private var spilledCount = 0
    private var totalCount = 0

    public init(
        sampleRate: Int = AudioChunkPlanner.sampleRate,
        ramCapSeconds: Int = MemoryPressurePolicy.ramCapSeconds,
        keepTailSeconds: Int = MemoryPressurePolicy.ramLiveWindowSeconds
    ) {
        self.sampleRate = sampleRate
        self.ramCapSamples = max(sampleRate, ramCapSeconds * sampleRate)
        self.keepTailSamples = min(
            ramCapSamples,
            max(sampleRate / 4, keepTailSeconds * sampleRate)
        )
        ram.reserveCapacity(min(ramCapSamples, sampleRate * 8))
    }

    deinit {
        closeSpill(delete: true)
    }

    public var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return totalCount
    }

    public var duration: TimeInterval {
        Double(count) / Double(sampleRate)
    }

    public func reset() {
        lock.lock()
        ram.removeAll(keepingCapacity: true)
        ramStart = 0
        totalCount = 0
        spilledCount = 0
        lock.unlock()
        closeSpill(delete: true)
    }

    public func append(_ samples: [Float]) {
        samples.withUnsafeBufferPointer { append($0) }
    }

    public func append(_ samples: UnsafeBufferPointer<Float>) {
        guard !samples.isEmpty else { return }
        lock.lock()
        ram.append(contentsOf: samples)
        totalCount += samples.count
        let overflow = ram.count > ramCapSamples
        lock.unlock()
        if overflow {
            spillIfNeeded()
        }
    }

    /// Copy samples at `absoluteOffset..<count` (for Grok delta send).
    public func copyNew(from absoluteOffset: Int) -> [Float] {
        lock.lock()
        let end = totalCount
        lock.unlock()
        let start = max(0, absoluteOffset)
        guard start < end else { return [] }
        return loadRange(start: start, count: end - start)
    }

    public func snapshotTail(maxSamples: Int) -> [Float] {
        lock.lock()
        let end = totalCount
        lock.unlock()
        let n = min(max(0, maxSamples), end)
        guard n > 0 else { return [] }
        return loadRange(start: end - n, count: n)
    }

    public func loadRange(start: Int, count requested: Int) -> [Float] {
        guard requested > 0 else { return [] }
        lock.lock()
        let end = min(start + requested, totalCount)
        let from = max(0, start)
        guard from < end else {
            lock.unlock()
            return []
        }
        let ramStartCopy = ramStart
        let ramCopy: [Float]
        let needSpill = from < ramStartCopy
        ramCopy = ram
        let spilledURLCopy = spilledURL
        lock.unlock()

        var out = [Float](repeating: 0, count: end - from)
        var i = 0
        var cursor = from
        if needSpill, let url = spilledURLCopy {
            let spillEnd = min(end, ramStartCopy)
            if cursor < spillEnd {
                let spillSamples = Self.readSpill(url: url, start: cursor, count: spillEnd - cursor)
                for s in spillSamples {
                    out[i] = s
                    i += 1
                }
                cursor += spillSamples.count
            }
        }
        while cursor < end {
            let local = cursor - ramStartCopy
            if local >= 0, local < ramCopy.count {
                out[i] = ramCopy[local]
                i += 1
                cursor += 1
            } else {
                break
            }
        }
        if i < out.count {
            out.removeLast(out.count - i)
        }
        return out
    }

    /// Reconstruct the whole capture. Avoid on hour-long clips — prefer `loadRange`.
    public func takeAllAndClear() -> [Float] {
        let all = loadRange(start: 0, count: count)
        reset()
        return all
    }

    /// Transcribe overlapping windows without materializing the full session.
    public func transcribeWindows(
        windowSamples: Int,
        overlapSamples: Int,
        transcribe: ([Float]) async throws -> String
    ) async throws -> String {
        let n = count
        let windows = AudioChunkPlanner.windows(
            sampleCount: n,
            windowSamples: windowSamples,
            overlapSamples: overlapSamples
        )
        var parts: [String] = []
        parts.reserveCapacity(windows.count)
        for w in windows {
            let chunk = loadRange(start: w.startSample, count: w.count)
            let text = try await transcribe(chunk)
            parts.append(text)
        }
        return TranscriptStitch.join(parts)
    }

    private func spillIfNeeded() {
        lock.lock()
        let extra = ram.count - keepTailSamples
        guard extra > 0, ram.count > ramCapSamples else {
            lock.unlock()
            return
        }
        let toSpill = Array(ram.prefix(extra))
        ram.removeFirst(extra)
        ramStart += extra
        spilledCount += extra
        lock.unlock()

        let data = PCMCodec.int16Data(from: toSpill)
        do {
            let handle = try spillHandle()
            try handle.write(contentsOf: data)
            try handle.synchronize()
        } catch {
            // If spill fails, put samples back so we do not silently drop audio.
            lock.lock()
            ram.insert(contentsOf: toSpill, at: 0)
            ramStart -= extra
            spilledCount -= extra
            lock.unlock()
            NSLog("MacWispr SampleRing: spill failed: \(error.localizedDescription)")
        }
    }

    private func spillHandle() throws -> FileHandle {
        if let spilledHandle { return spilledHandle }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("macwispr-\(UUID().uuidString).pcm16")
        FileManager.default.createFile(atPath: url.path, contents: nil)
        let handle = try FileHandle(forWritingTo: url)
        spilledURL = url
        spilledHandle = handle
        return handle
    }

    private func closeSpill(delete: Bool) {
        try? spilledHandle?.close()
        spilledHandle = nil
        if delete, let url = spilledURL {
            try? FileManager.default.removeItem(at: url)
        }
        spilledURL = nil
    }

    private static func readSpill(url: URL, start: Int, count: Int) -> [Float] {
        guard count > 0 else { return [] }
        guard let handle = try? FileHandle(forReadingFrom: url) else { return [] }
        defer { try? handle.close() }
        let byteStart = UInt64(start) * 2
        let byteCount = count * 2
        do {
            try handle.seek(toOffset: byteStart)
            guard let data = try handle.read(upToCount: byteCount) else { return [] }
            return PCMCodec.floats(fromInt16: data)
        } catch {
            return []
        }
    }
}
