import AppKit
import SwiftUI

/// SwiftUI `Button`/`Menu` on macOS 26 can SIGSEGV in `_ButtonGesture` /
/// `MainActor.assumeIsolated` (GitHub #21). AppKit hit-targets avoid that path.

enum AppKitSafeMenuItem {
    case header(String)
    case separator
    case item(title: String, checked: Bool, enabled: Bool, handler: () -> Void)

    static func action(
        title: String,
        checked: Bool = false,
        enabled: Bool = true,
        handler: @escaping () -> Void
    ) -> AppKitSafeMenuItem {
        .item(title: title, checked: checked, enabled: enabled, handler: handler)
    }
}

struct AppKitPullDownMenu: NSViewRepresentable {
    var items: [AppKitSafeMenuItem]
    var isEnabled: Bool = true
    var accessibilityLabel: String
    var toolTip: String

    func makeNSView(context: Context) -> AppKitSafeMenuView {
        let view = AppKitSafeMenuView()
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.defaultLow, for: .vertical)
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        return view
    }

    func updateNSView(_ nsView: AppKitSafeMenuView, context: Context) {
        nsView.items = items
        nsView.isEnabledFlag = isEnabled
        nsView.toolTip = toolTip
        nsView.setAccessibilityElement(true)
        nsView.setAccessibilityRole(.popUpButton)
        nsView.setAccessibilityLabel(accessibilityLabel)
        nsView.setAccessibilityEnabled(isEnabled)
    }
}

struct AppKitClickTarget: NSViewRepresentable {
    var isEnabled: Bool = true
    var accessibilityLabel: String
    var action: () -> Void

    func makeNSView(context: Context) -> AppKitSafeClickView {
        let view = AppKitSafeClickView()
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.defaultLow, for: .vertical)
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        return view
    }

    func updateNSView(_ nsView: AppKitSafeClickView, context: Context) {
        nsView.action = action
        nsView.isEnabledFlag = isEnabled
        nsView.setAccessibilityElement(true)
        nsView.setAccessibilityRole(.button)
        nsView.setAccessibilityLabel(accessibilityLabel)
        nsView.setAccessibilityEnabled(isEnabled)
    }
}

final class AppKitSafeMenuView: NSView {
    var items: [AppKitSafeMenuItem] = []
    var isEnabledFlag = true
    private var actionHandlers: [() -> Void] = []

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric)
    }

    override var isOpaque: Bool { false }
    override var mouseDownCanMoveWindow: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func resetCursorRects() {
        if isEnabledFlag {
            addCursorRect(bounds, cursor: .pointingHand)
        }
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        bounds.contains(point) ? self : nil
    }

    override func mouseDown(with event: NSEvent) {
        guard isEnabledFlag else { return }
        popMenu()
    }

    @objc func runMenuItem(_ sender: NSMenuItem) {
        let tag = sender.tag
        guard tag >= 0, tag < actionHandlers.count else { return }
        let handler = actionHandlers[tag]
        if Thread.isMainThread {
            handler()
        } else {
            DispatchQueue.main.async(execute: handler)
        }
    }

    private func popMenu() {
        let menu = NSMenu()
        menu.autoenablesItems = false
        actionHandlers = []
        for item in items {
            switch item {
            case .header(let title):
                menu.addItem(.sectionHeader(title: title))
            case .separator:
                menu.addItem(.separator())
            case .item(let title, let checked, let enabled, let handler):
                let menuItem = NSMenuItem(
                    title: title,
                    action: #selector(runMenuItem(_:)),
                    keyEquivalent: ""
                )
                menuItem.target = self
                menuItem.tag = actionHandlers.count
                menuItem.state = checked ? .on : .off
                menuItem.isEnabled = enabled
                actionHandlers.append(handler)
                menu.addItem(menuItem)
            }
        }
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: 0), in: self)
    }
}

final class AppKitSafeClickView: NSView {
    var action: (() -> Void)?
    var isEnabledFlag = true

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric)
    }

    override var isOpaque: Bool { false }
    override var mouseDownCanMoveWindow: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func resetCursorRects() {
        if isEnabledFlag {
            addCursorRect(bounds, cursor: .pointingHand)
        }
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        bounds.contains(point) ? self : nil
    }

    override func mouseDown(with event: NSEvent) {}

    override func mouseUp(with event: NSEvent) {
        guard isEnabledFlag else { return }
        let point = convert(event.locationInWindow, from: nil)
        guard bounds.contains(point), let action else { return }
        if Thread.isMainThread {
            action()
        } else {
            DispatchQueue.main.async(execute: action)
        }
    }
}
