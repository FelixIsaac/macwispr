import Foundation

/// Reads the Grok Build CLI login at `~/.grok/auth.json` (same file OpenUsage / `grok login` use).
/// Tokens are never copied into MacWispr Keychain; we only read (and optionally rotate) that file.
enum GrokOAuthStore {
    static let defaultClientID = "b1a00492-073a-47ea-816f-4c329264a828"
    static let refreshURL = URL(string: "https://auth.x.ai/oauth2/token")!
    /// UserDefaults: user accepted using Grok session for STT on this Mac.
    static let consentAcceptedKey = "grokSTTConsentAccepted"
    /// UserDefaults: user dismissed the one-shot offer (don't auto-prompt again).
    static let consentDismissedKey = "grokSTTConsentDismissed"
    /// Refresh when the access token expires within this window.
    private static let refreshBuffer: TimeInterval = 5 * 60

    static var hasAcceptedConsent: Bool {
        UserDefaults.standard.bool(forKey: consentAcceptedKey)
    }

    static var hasDismissedConsent: Bool {
        UserDefaults.standard.bool(forKey: consentDismissedKey)
    }

    static func acceptConsent() {
        UserDefaults.standard.set(true, forKey: consentAcceptedKey)
        UserDefaults.standard.set(true, forKey: consentDismissedKey)
    }

    static func declineConsent(dontAskAgain: Bool) {
        UserDefaults.standard.set(false, forKey: consentAcceptedKey)
        if dontAskAgain {
            UserDefaults.standard.set(true, forKey: consentDismissedKey)
        }
    }

    /// Show the one-shot “use Grok for dictation?” offer.
    static var shouldOfferConsent: Bool {
        isInstalled && !hasAcceptedConsent && !hasDismissedConsent
    }

    // MARK: - Paths

    static var grokHome: URL {
        if let raw = ProcessInfo.processInfo.environment["GROK_HOME"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !raw.isEmpty
        {
            return URL(fileURLWithPath: (raw as NSString).expandingTildeInPath, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".grok", isDirectory: true)
    }

    static var authJSONURL: URL {
        grokHome.appendingPathComponent("auth.json", isDirectory: false)
    }

    /// Local-only probe: Grok CLI session file exists and has at least one access token.
    static var isInstalled: Bool {
        (try? loadCandidates())?.isEmpty == false
    }

    // MARK: - Model

    struct Entry: Equatable {
        var key: String
        var refreshToken: String?
        var expiresAt: Date?
        var oidcClientID: String?
        var entryKey: String
        var email: String?
    }

    enum StoreError: LocalizedError {
        case notLoggedIn
        case invalidAuth
        case expired
        case refreshFailed(String)

        var errorDescription: String? {
            switch self {
            case .notLoggedIn:
                return "Grok not logged in. Run `grok login` in Terminal."
            case .invalidAuth:
                return "Grok auth file is invalid. Run `grok login` again."
            case .expired:
                return "Grok session expired. Run `grok login` again."
            case .refreshFailed(let detail):
                return "Grok token refresh failed: \(detail)"
            }
        }
    }

    // MARK: - Load

    static func loadCandidates() throws -> [Entry] {
        let url = authJSONURL
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw StoreError.notLoggedIn
        }
        let data = try Data(contentsOf: url)
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw StoreError.invalidAuth
        }

        var out: [Entry] = []
        for (entryKey, value) in root {
            guard let obj = value as? [String: Any] else { continue }
            guard let token = string(obj["key"]), !token.isEmpty else { continue }
            let refresh = string(obj["refresh_token"]) ?? string(obj["refresh"])
            let expiresAt = parseDate(string(obj["expires_at"]) ?? string(obj["expires"]))
            let clientID = string(obj["oidc_client_id"])
            let email = string(obj["email"])
            out.append(Entry(
                key: token,
                refreshToken: refresh,
                expiresAt: expiresAt,
                oidcClientID: clientID,
                entryKey: entryKey,
                email: email
            ))
        }
        guard !out.isEmpty else { throw StoreError.invalidAuth }
        return out
    }

    /// Best available bearer token, refreshing when near expiry.
    static func resolveBearer() async throws -> String {
        var candidates = try loadCandidates()
        // Prefer entries that still look fresh.
        candidates.sort { a, b in
            let ae = a.expiresAt ?? .distantPast
            let be = b.expiresAt ?? .distantPast
            return ae > be
        }

        var lastError: Error = StoreError.invalidAuth
        for var entry in candidates {
            do {
                if needsRefresh(entry) {
                    if let refreshed = try await refresh(&entry) {
                        return refreshed
                    }
                    if isExpired(entry) {
                        lastError = StoreError.expired
                        continue
                    }
                }
                return entry.key
            } catch {
                lastError = error
                continue
            }
        }
        throw lastError
    }

    static func maskedIdentity() -> String? {
        guard let entry = try? loadCandidates().first else { return nil }
        if let email = entry.email, !email.isEmpty {
            return email
        }
        return "Grok session"
    }

    // MARK: - Refresh

    private static func needsRefresh(_ entry: Entry) -> Bool {
        if let exp = tokenExpiry(fromJWT: entry.key) ?? entry.expiresAt {
            return exp.timeIntervalSinceNow <= refreshBuffer
        }
        return false
    }

    private static func isExpired(_ entry: Entry) -> Bool {
        if let exp = tokenExpiry(fromJWT: entry.key) ?? entry.expiresAt {
            return exp <= Date()
        }
        return false
    }

    private static func refresh(_ entry: inout Entry) async throws -> String? {
        guard let refreshToken = entry.refreshToken, !refreshToken.isEmpty else {
            return nil
        }
        let clientID = resolvedClientID(entry)

        var request = URLRequest(url: refreshURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 15
        let body =
            "grant_type=refresh_token" +
            "&client_id=\(formEncode(clientID))" +
            "&refresh_token=\(formEncode(refreshToken))"
        request.httpBody = Data(body.utf8)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200...299).contains(status) else {
            let snippet = String(data: data, encoding: .utf8)?
                .replacingOccurrences(of: "\n", with: " ")
                .prefix(120) ?? ""
            throw StoreError.refreshFailed("HTTP \(status) \(snippet)")
        }

        guard
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let access = string(json["access_token"]),
            !access.isEmpty
        else {
            throw StoreError.refreshFailed("empty access_token")
        }

        entry.key = access
        if let newRefresh = string(json["refresh_token"]), !newRefresh.isEmpty {
            entry.refreshToken = newRefresh
        }
        if let expiresIn = json["expires_in"] as? Double, expiresIn > 0 {
            entry.expiresAt = Date().addingTimeInterval(expiresIn)
        } else if let exp = tokenExpiry(fromJWT: access) {
            entry.expiresAt = exp
        } else {
            entry.expiresAt = Date().addingTimeInterval(3600)
        }

        // Best-effort write-back so Grok CLI and MacWispr stay in sync (OpenUsage pattern).
        try? persist(entry)
        return access
    }

    private static func persist(_ entry: Entry) throws {
        let url = authJSONURL
        var root: [String: Any]
        if FileManager.default.fileExists(atPath: url.path),
           let data = try? Data(contentsOf: url),
           let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        {
            root = parsed
        } else {
            root = [:]
        }
        var obj = root[entry.entryKey] as? [String: Any] ?? [:]
        obj["key"] = entry.key
        if let refresh = entry.refreshToken {
            obj["refresh_token"] = refresh
        }
        if let expiresAt = entry.expiresAt {
            obj["expires_at"] = iso8601(expiresAt)
        }
        root[entry.entryKey] = obj

        let out = try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys])
        try out.write(to: url, options: .atomic)
        try? FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    private static func resolvedClientID(_ entry: Entry) -> String {
        if let id = entry.oidcClientID, !id.isEmpty { return id }
        let parts = entry.entryKey.split(separator: "::", omittingEmptySubsequences: false)
        if let last = parts.last {
            let value = String(last).trimmingCharacters(in: .whitespacesAndNewlines)
            if !value.isEmpty { return value }
        }
        return defaultClientID
    }

    // MARK: - Helpers

    private static func string(_ any: Any?) -> String? {
        guard let s = any as? String else { return nil }
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private static func parseDate(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: raw) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: raw)
    }

    private static func iso8601(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: date)
    }

    private static func formEncode(_ value: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+?")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    private static func tokenExpiry(fromJWT token: String) -> Date? {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var payload = String(parts[1])
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while payload.count % 4 != 0 { payload.append("=") }
        guard let data = Data(base64Encoded: payload),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        if let exp = json["exp"] as? Double {
            return Date(timeIntervalSince1970: exp)
        }
        if let exp = json["exp"] as? Int {
            return Date(timeIntervalSince1970: TimeInterval(exp))
        }
        return nil
    }
}
