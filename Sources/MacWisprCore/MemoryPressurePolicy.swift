import Foundation

public enum MemoryPressureLevel: Equatable, Sendable {
    case normal
    case warning
    case critical
}

public enum ModelMemoryAction: Equatable, Sendable {
    case keep
    case unloadPolish
    case unloadASRAndPolish
}

/// Idle / pressure rules so a menu-bar app does not pin GPU weights for days.
public enum MemoryPressurePolicy {
    /// Unload local polish after this idle (seconds).
    public static let idlePolishUnloadSeconds: TimeInterval = 2 * 60
    /// Unload local ASR after this idle (seconds). Disk cache is kept.
    public static let idleASRUnloadSeconds: TimeInterval = 8 * 60
    /// Live / RAM window — last N seconds stay in process memory.
    public static let ramLiveWindowSeconds = 40
    /// Spill older PCM to a temp file after this many seconds in RAM.
    public static let ramCapSeconds = 90
    /// Qwen 1.7B needs headroom beyond weights (~2.3 GB on disk, more at runtime).
    public static let largeModelMinAvailableBytes: UInt64 = 2_500_000_000
    public static let smallModelMinAvailableBytes: UInt64 = 900_000_000

    public static func action(
        level: MemoryPressureLevel,
        availableBytes: UInt64?,
        asrLoaded: Bool,
        polishLoaded: Bool,
        recording: Bool
    ) -> ModelMemoryAction {
        if recording { return .keep }
        switch level {
        case .critical:
            if asrLoaded || polishLoaded { return .unloadASRAndPolish }
            return .keep
        case .warning:
            if polishLoaded { return .unloadPolish }
            if let available = availableBytes, available < smallModelMinAvailableBytes, asrLoaded {
                return .unloadASRAndPolish
            }
            return .keep
        case .normal:
            if let available = availableBytes, available < smallModelMinAvailableBytes {
                if asrLoaded { return .unloadASRAndPolish }
                if polishLoaded { return .unloadPolish }
            }
            return .keep
        }
    }

    public static func canLoadLargeQwen(availableBytes: UInt64?) -> Bool {
        guard let available = availableBytes else { return true }
        return available >= largeModelMinAvailableBytes
    }

    public static func canLoadSmallQwen(availableBytes: UInt64?) -> Bool {
        guard let available = availableBytes else { return true }
        return available >= smallModelMinAvailableBytes
    }

    public static func looksLikeOOM(_ error: String) -> Bool {
        let text = error.lowercased()
        let needles = [
            "out of memory",
            "out-of-memory",
            "oom",
            "memory pressure",
            "insufficient memory",
            "not enough memory",
            "failed to allocate",
            "couldn't allocate",
            "could not allocate",
            "malloc",
            "metal command buffer",
            "insufficient resources",
            "resource limit",
        ]
        return needles.contains { text.contains($0) }
    }

    public static func oomUserMessage(triedLarge: Bool) -> String {
        if triedLarge {
            return "Not enough memory — try Qwen 0.6B or Grok/OpenAI."
        }
        return "Not enough memory to load the on-device model. Switch to Grok or OpenAI, or free RAM and retry."
    }
}
