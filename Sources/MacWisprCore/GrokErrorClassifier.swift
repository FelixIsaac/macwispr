import Foundation

public enum GrokSTTFailureKind: Equatable, Sendable {
    case quota
    case auth
    case network
    case server
    case empty
}

/// Maps xAI STT WebSocket / HTTP failures to an actionable, content-free message.
public enum GrokErrorClassifier {
    public static func classify(status: Int, body: String) -> GrokSTTFailureKind {
        let text = body.lowercased()
        if status == 401 || status == 403 {
            return .auth
        }
        if status == 429 {
            return .quota
        }
        if looksLikeQuota(text) {
            return .quota
        }
        if looksLikeAuth(text) {
            return .auth
        }
        if looksLikeEmpty(text) {
            return .empty
        }
        if status == 0, looksLikeNetwork(text) {
            return .network
        }
        if (500...599).contains(status) {
            return .server
        }
        if looksLikeNetwork(text) {
            return .network
        }
        return .server
    }

    public static func userMessage(for kind: GrokSTTFailureKind) -> String {
        switch kind {
        case .quota:
            return "Your Grok weekly limit has been reached. Try again after it resets, use another provider, or sign in with an account that has capacity."
        case .auth:
            return "Grok login expired. Run `grok login` in Terminal, then try again."
        case .network:
            return "Could not reach Grok STT. Check the network and try again."
        case .empty:
            return "Grok heard no speech. Hold a bit longer, or check the microphone."
        case .server:
            return "Grok STT returned a server error. Try again, or switch to Local / OpenAI."
        }
    }

    public static func looksLikeQuota(_ text: String) -> Bool {
        let needles = [
            "quota",
            "rate limit",
            "rate_limit",
            "resource exhausted",
            "resource_exhausted",
            "usage limit",
            "weekly limit",
            "weekly allowance",
            "token limit",
            "too many requests",
            "insufficient_quota",
            "exceeded your current quota",
            "out of credits",
            "no remaining",
            "limit reached",
            "limit has been reached",
        ]
        return needles.contains { text.contains($0) }
    }

    private static func looksLikeAuth(_ text: String) -> Bool {
        let needles = [
            "unauthorized",
            "unauthenticated",
            "invalid token",
            "expired token",
            "invalid_api_key",
            "authentication",
            "not authenticated",
            "forbidden",
        ]
        return needles.contains { text.contains($0) }
    }

    private static func looksLikeEmpty(_ text: String) -> Bool {
        text.contains("no speech") || text.contains("empty audio") || text.contains("no speech detected")
    }

    private static func looksLikeNetwork(_ text: String) -> Bool {
        let needles = [
            "timed out",
            "timeout",
            "network",
            "offline",
            "connection",
            "could not connect",
            "dns",
            "not connected",
        ]
        return needles.contains { text.contains($0) }
    }
}
