import Foundation

/// Events from a live Grok streaming STT session (Grok Build protocol).
enum GrokSTTEvent: Sendable {
    /// Full display text so far (committed speech_finals + live interim).
    case display(String)
    /// Non-fatal or fatal stream error message.
    case error(String)
}

/// Live xAI STT over `wss://api.x.ai/v1/stt` — same shape as Grok Build voice:
/// open mic + socket together, stream PCM while speaking, paint interim partials,
/// `audio.done` on release, then trailing final.
///
/// One session per dictation. Call `sendSamples` with new float32 mono @ 16 kHz
/// as audio arrives; call `finish()` when the user releases.
actor GrokStreamingSession {
    private static let sampleRate = 16_000
    private static let endpointingMs = 400
    private static let connectTimeout: TimeInterval = 15
    private static let finishTimeout: TimeInterval = 20
    private static let pcmChunkBytes = 3200 // ~100 ms @ 16 kHz mono s16le

    private let urlSession: URLSession
    private let task: URLSessionWebSocketTask
    private let onEvent: @Sendable (GrokSTTEvent) -> Void

    private var receiveLoop: Task<Void, Never>?
    private var lockedPrefix = ""
    private var committedFinals: [String] = []
    private var lastInterim = ""
    /// True after `finish()` / `cancel()` — no more PCM.
    private var closed = false
    /// Server sent `transcript.done` or the socket closed after audio.done.
    private var terminalResult: String?
    private var finishContinuation: CheckedContinuation<String, Error>?
    private var sawAnySpeech = false

    // MARK: - Lifecycle

    static func connect(
        bearer: String,
        language: String? = nil,
        onEvent: @escaping @Sendable (GrokSTTEvent) -> Void
    ) async throws -> GrokStreamingSession {
        let lang = (language?.trimmingCharacters(in: .whitespacesAndNewlines)).flatMap {
            $0.isEmpty ? nil : $0
        } ?? "en"

        var components = URLComponents(string: "wss://api.x.ai/v1/stt")!
        components.queryItems = [
            URLQueryItem(name: "sample_rate", value: "\(sampleRate)"),
            URLQueryItem(name: "encoding", value: "pcm"),
            URLQueryItem(name: "interim_results", value: "true"),
            URLQueryItem(name: "language", value: lang),
            URLQueryItem(name: "endpointing", value: "\(endpointingMs)"),
        ]
        guard let url = components.url else {
            throw CloudSTTError.invalidResponse
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = connectTimeout
        request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        request.setValue("MacWispr", forHTTPHeaderField: "User-Agent")
        request.setValue("macwispr", forHTTPHeaderField: "x-grok-client-identifier")

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = connectTimeout
        config.waitsForConnectivity = true
        let urlSession = URLSession(configuration: config)
        let task = urlSession.webSocketTask(with: request)
        task.resume()

        let session = GrokStreamingSession(
            urlSession: urlSession,
            task: task,
            onEvent: onEvent
        )
        try await session.waitReady()
        await session.startReceiveLoop()
        return session
    }

    private init(
        urlSession: URLSession,
        task: URLSessionWebSocketTask,
        onEvent: @escaping @Sendable (GrokSTTEvent) -> Void
    ) {
        self.urlSession = urlSession
        self.task = task
        self.onEvent = onEvent
    }

    deinit {
        receiveLoop?.cancel()
        task.cancel(with: .goingAway, reason: nil)
        urlSession.invalidateAndCancel()
    }

    // MARK: - Audio

    /// Append float32 mono samples (16 kHz). Sends as little-endian PCM16 binary frames.
    func sendSamples(_ samples: [Float]) async {
        guard !closed, !samples.isEmpty else { return }
        let pcm = AudioWAVEncoder.pcm16Data(from: samples)
        var offset = 0
        while offset < pcm.count {
            let end = min(offset + Self.pcmChunkBytes, pcm.count)
            let slice = pcm.subdata(in: offset..<end)
            do {
                try await task.send(.data(slice))
            } catch {
                // Drop remaining; finish()/receive loop will surface failure if needed.
                return
            }
            offset = end
        }
    }

    /// End capture: send `audio.done`, wait for trailing finals, tear down.
    func finish() async throws -> String {
        if let terminalResult {
            teardown()
            let cleaned = terminalResult.trimmingCharacters(in: .whitespacesAndNewlines)
            if cleaned.isEmpty {
                throw CloudSTTError.http(status: 0, body: "Grok STT: no speech detected")
            }
            return cleaned
        }
        closed = true

        do {
            try await task.send(.string(#"{"type":"audio.done"}"#))
        } catch {
            let text = bestText()
            teardown()
            if text.isEmpty {
                throw CloudSTTError.http(status: 0, body: "Grok STT: failed to end audio (\(error.localizedDescription))")
            }
            return text
        }

        do {
            let text: String = try await withThrowingTaskGroup(of: String.self) { group in
                group.addTask {
                    try await self.waitForTerminal()
                }
                group.addTask {
                    try await Task.sleep(nanoseconds: UInt64(Self.finishTimeout * 1_000_000_000))
                    throw CloudSTTError.http(status: 0, body: "Grok STT: finish timed out")
                }
                let result = try await group.next()!
                group.cancelAll()
                return result
            }
            teardown()
            let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if cleaned.isEmpty {
                throw CloudSTTError.http(status: 0, body: "Grok STT: no speech detected")
            }
            return cleaned
        } catch {
            let fallback = bestText()
            teardown()
            if !fallback.isEmpty {
                return fallback
            }
            throw error
        }
    }

    /// Abort without waiting for a final (cancel hotkey).
    func cancel() {
        closed = true
        if let cont = finishContinuation {
            finishContinuation = nil
            cont.resume(returning: bestText())
        }
        teardown()
    }

    // MARK: - Internals

    private func waitForTerminal() async throws -> String {
        if let terminalResult { return terminalResult }
        return try await withCheckedThrowingContinuation { cont in
            if let terminalResult {
                cont.resume(returning: terminalResult)
            } else {
                finishContinuation = cont
            }
        }
    }

    private func completeTerminal(_ text: String) {
        terminalResult = text
        if let cont = finishContinuation {
            finishContinuation = nil
            cont.resume(returning: text)
        }
    }

    private func failTerminal(_ error: Error) {
        if let cont = finishContinuation {
            finishContinuation = nil
            let fallback = bestText()
            if fallback.isEmpty {
                cont.resume(throwing: error)
            } else {
                cont.resume(returning: fallback)
            }
        } else if terminalResult == nil {
            terminalResult = bestText()
        }
    }

    private func waitReady() async throws {
        let deadline = Date().addingTimeInterval(Self.connectTimeout)
        while Date() < deadline {
            let message = try await receiveOnce(timeout: max(0.1, deadline.timeIntervalSinceNow))
            switch Self.parseServerEvent(message) {
            case .created:
                return
            case .error(let msg):
                throw CloudSTTError.http(status: 0, body: msg)
            case .partial, .done, .unknown:
                continue
            }
        }
        throw CloudSTTError.http(status: 0, body: "Grok STT: timed out waiting for transcript.created")
    }

    private func startReceiveLoop() {
        receiveLoop = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                let message: URLSessionWebSocketTask.Message
                do {
                    message = try await self.receiveOnce(timeout: 60)
                } catch {
                    await self.handleReceiveEnd(error: error)
                    return
                }
                await self.handleMessage(message)
            }
        }
    }

    private func handleReceiveEnd(error: Error) {
        // Stream closed after audio.done is normal — complete with best text.
        failTerminal(error)
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        switch Self.parseServerEvent(message) {
        case .created, .unknown:
            return
        case .error(let msg):
            onEvent(.error(msg))
            failTerminal(CloudSTTError.http(status: 0, body: msg))
        case .partial(let text, let isFinal, let speechFinal):
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return }
            sawAnySpeech = true

            // Mirror Grok Build pipeline stitching:
            // speech_final → commit utterance; is_final → lock chunk; else interim.
            if speechFinal {
                committedFinals.append(trimmed)
                lockedPrefix = ""
                lastInterim = ""
            } else if isFinal {
                if !lockedPrefix.isEmpty { lockedPrefix += " " }
                lockedPrefix += trimmed
                lastInterim = lockedPrefix
            } else if lockedPrefix.isEmpty {
                lastInterim = trimmed
            } else {
                lastInterim = "\(lockedPrefix) \(trimmed)"
            }
            emitDisplay()
        case .done(let text):
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                sawAnySpeech = true
                // Prefer clean one-pass done when we have no committed finals yet.
                if committedFinals.isEmpty {
                    committedFinals = [trimmed]
                    lockedPrefix = ""
                    lastInterim = ""
                } else {
                    // Server re-transcription of the whole turn often beats stitched deltas.
                    committedFinals = [trimmed]
                    lockedPrefix = ""
                    lastInterim = ""
                }
            }
            emitDisplay()
            completeTerminal(bestText())
        }
    }

    private func emitDisplay() {
        let text = bestText()
        guard !text.isEmpty else { return }
        onEvent(.display(text))
    }

    private func bestText() -> String {
        if !committedFinals.isEmpty {
            let base = committedFinals.joined(separator: " ")
            if lastInterim.isEmpty { return base }
            // Interim after a speech_final is the next utterance in progress.
            return "\(base) \(lastInterim)"
        }
        if !lastInterim.isEmpty { return lastInterim }
        if !lockedPrefix.isEmpty { return lockedPrefix }
        return ""
    }

    private func teardown() {
        receiveLoop?.cancel()
        receiveLoop = nil
        task.cancel(with: .goingAway, reason: nil)
        urlSession.invalidateAndCancel()
    }

    private func receiveOnce(timeout: TimeInterval) async throws -> URLSessionWebSocketTask.Message {
        try await withThrowingTaskGroup(of: URLSessionWebSocketTask.Message.self) { group in
            group.addTask {
                try await self.task.receive()
            }
            group.addTask {
                let ns = UInt64(max(timeout, 0.05) * 1_000_000_000)
                try await Task.sleep(nanoseconds: ns)
                throw CloudSTTError.http(status: 0, body: "Grok STT: receive timed out")
            }
            let result = try await group.next()!
            group.cancelAll()
            return result
        }
    }

    // MARK: - Protocol parse

    private enum ServerEvent {
        case created
        case partial(text: String, isFinal: Bool, speechFinal: Bool)
        case done(text: String)
        case error(String)
        case unknown
    }

    private static func parseServerEvent(_ message: URLSessionWebSocketTask.Message) -> ServerEvent {
        let text: String
        switch message {
        case .string(let s):
            text = s
        case .data(let d):
            guard let s = String(data: d, encoding: .utf8) else { return .unknown }
            text = s
        @unknown default:
            return .unknown
        }
        guard
            let data = text.data(using: .utf8),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = json["type"] as? String
        else {
            return .unknown
        }
        switch type {
        case "transcript.created":
            return .created
        case "transcript.partial":
            return .partial(
                text: (json["text"] as? String) ?? "",
                isFinal: (json["is_final"] as? Bool) ?? false,
                speechFinal: (json["speech_final"] as? Bool) ?? false
            )
        case "transcript.done":
            return .done(text: (json["text"] as? String) ?? "")
        case "error":
            return .error((json["message"] as? String) ?? "Grok STT error")
        default:
            return .unknown
        }
    }
}

/// Batch helper: open a short session, dump all PCM, finish (fallback if live stream failed).
enum GrokSTTClient {
    static func transcribe(
        samples: [Float],
        bearer: String,
        language: String? = nil
    ) async throws -> String {
        let session = try await GrokStreamingSession.connect(
            bearer: bearer,
            language: language,
            onEvent: { _ in }
        )
        await session.sendSamples(samples)
        return try await session.finish()
    }
}
