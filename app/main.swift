// Personal Manager: a native window around the local dashboard (dashboard/server.py).
// The server runs under launchd (scripts/install_dashboard.sh); this app only shows it.
import Cocoa
import WebKit

let url = URL(string: "http://127.0.0.1:8765")!

final class DragStrip: NSView {
    override var mouseDownCanMoveWindow: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 { window?.performZoom(nil) } else { window?.performDrag(with: event) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var retry: Timer?

    func applicationDidFinishLaunching(_ note: Notification) {
        let strip: CGFloat = 40   // height of the title bar zone (traffic lights); the page pads itself below it
        let size = NSSize(width: 1240, height: 860)
        let cfg = WKWebViewConfiguration()
        // Tells the page it runs in the app window, so it can leave room for the traffic lights.
        cfg.userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.classList.add('native')",
            injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: cfg)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.setValue(false, forKey: "drawsBackground")

        window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Personal Manager"
        window.minSize = NSSize(width: 760, height: 520)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        // Same colour as the dashboard's --bg, so the strip and the page read as one surface.
        window.backgroundColor = NSColor(name: nil) { a in
            a.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                ? NSColor.black : NSColor(srgbRed: 0.949, green: 0.949, blue: 0.969, alpha: 1)
        }
        window.contentView?.addSubview(web)
        // A web view swallows mouse-downs, so a transparent native strip on top keeps the window draggable.
        let drag = DragStrip(frame: NSRect(x: 0, y: size.height - strip, width: size.width, height: strip))
        drag.autoresizingMask = [.width, .minYMargin]
        window.contentView?.addSubview(drag)
        window.center()
        window.setFrameAutosaveName("PersonalManagerMain")
        window.makeKeyAndOrderFront(nil)

        buildMenu()
        NSApp.activate(ignoringOtherApps: true)
        load()
    }

    func load() { web.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)) }

    // Server not up yet (login race, restart): retry quietly instead of showing an error page.
    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { scheduleRetry() }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { scheduleRetry() }
    func scheduleRetry() {
        retry?.invalidate()
        retry = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: false) { [weak self] _ in self?.load() }
    }

    // Anything that is not the dashboard opens in the default browser.
    func webView(_ w: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = action.request.url, u.host != url.host, ["http", "https"].contains(u.scheme ?? "") {
            NSWorkspace.shared.open(u); decisionHandler(.cancel)
        } else { decisionHandler(.allow) }
    }
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration,
                 for a: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = a.request.url { NSWorkspace.shared.open(u) }
        return nil
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    @objc func reload() { load() }

    func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [(String, Selector?, String)], to bar: NSMenu) {
            let item = NSMenuItem(); bar.addItem(item)
            let m = NSMenu(title: title); item.submenu = m
            for (t, s, k) in items {
                if t == "-" { m.addItem(.separator()); continue }
                let mi = NSMenuItem(title: t, action: s, keyEquivalent: k)
                if s == #selector(reload) { mi.target = self }
                m.addItem(mi)
            }
        }
        add("Personal Manager", [
            ("About Personal Manager", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
            ("-", nil, ""),
            ("Hide Personal Manager", #selector(NSApplication.hide(_:)), "h"),
            ("Quit Personal Manager", #selector(NSApplication.terminate(_:)), "q")], to: main)
        add("Edit", [
            ("Cut", #selector(NSText.cut(_:)), "x"), ("Copy", #selector(NSText.copy(_:)), "c"),
            ("Paste", #selector(NSText.paste(_:)), "v"), ("Select All", #selector(NSText.selectAll(_:)), "a")], to: main)
        add("View", [("Reload", #selector(reload), "r")], to: main)
        add("Window", [
            ("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            ("Close", #selector(NSWindow.performClose(_:)), "w")], to: main)
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
