import SwiftUI
import AppKit

@main
struct MacWisprApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var appState = AppState()

    /// Status item must be installed **once**. Side-effect in `body` re-ran on
    /// every scene invalidation and rebuilt the popover host → ghosted UI.
    private static var didInstallMenuBar = false
    private static var didScheduleSelfTest = false

    var body: some Scene {
        let _ = Self.installMenuBarIfNeeded(appDelegate: appDelegate, appState: appState)

        // Menu-bar agent: the real dashboard is a single AppKit `NSWindow` owned by
        // `AppDelegate` (`showDashboard`). Do **not** declare `Window` / `WindowGroup`
        // here — that creates a second "MacWispr" window next to the AppKit host
        // (#15, and worsens #21 button-gesture crashes on macOS 26).
        //
        // SwiftUI still requires a Scene. `Settings` is only an anchor; product
        // Settings live in the dashboard. We replace the default Settings command
        // so Cmd+, opens the real UI, and keep default Quit (Cmd+Q).
        Settings {
            EmptyView()
        }
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") {
                    openDashboardSettings()
                }
                .keyboardShortcut(",", modifiers: .command)
            }
        }
    }

    private static func installMenuBarIfNeeded(appDelegate: AppDelegate, appState: AppState) {
        // Always keep the delegate’s pointer current (cheap).
        appDelegate.appState = appState
        guard !didInstallMenuBar else { return }
        didInstallMenuBar = true
        StatusBarController.shared.install(appState: appState)

        // Settings-only Scene defers SwiftUI runtime activation; kick self-test after
        // menu bar install so the MainActor Task actually runs (headless CI smoke).
        if CommandLine.arguments.contains("--self-test"), !didScheduleSelfTest {
            didScheduleSelfTest = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                AppDelegate.shared?.beginSelfTest()
            }
        }
    }

    private func openDashboardSettings() {
        AppDelegate.shared?.appState = appState
        AppDelegate.shared?.showDashboard()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            NotificationCenter.default.post(name: .macWisprShowSettings, object: nil)
        }
    }
}