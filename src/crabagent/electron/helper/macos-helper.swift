// CrabAgent macOS computer-use helper (M0/M1).
// One-shot invocation: Electron writes a request JSON file (mode 0600), passes
// `--request-file <path> --secret <per-launch nonce>`; the helper validates the secret,
// executes one allowlisted command, prints one JSON response to stdout, and exits.
// Never spawns subprocesses or executes shell commands. Input commands (click/type/key/
// scroll) require the target app to be frontmost, allowlisted, and the session unlocked;
// they stay behind explicit per-task opt-in on the Electron side (M1).

import AppKit
import ApplicationServices
import Carbon.HIToolbox
import CoreGraphics
import Foundation
import ScreenCaptureKit

enum HelperError: Error, CustomStringConvertible {
    case badUsage(String)
    case badSecret
    case badRequest(String)
    case unknownCommand(String)
    case notImplemented(String)
    case permissionDenied(String)
    case preconditionFailed(String)

    var description: String {
        switch self {
        case .badUsage(let detail): return "usage: \(detail)"
        case .badSecret: return "bad secret"
        case .badRequest(let detail): return "bad request: \(detail)"
        case .unknownCommand(let name): return "unknown command: \(name)"
        case .notImplemented(let what): return "not implemented: \(what)"
        case .permissionDenied(let what): return "permission denied: \(what)"
        case .preconditionFailed(let what): return "precondition failed: \(what)"
        }
    }
}

let maxRequestBytes = 256 * 1024
let maxAxNodes = 300
let maxAxDepth = 8
let maxValueChars = 120

// MARK: - permissions

func preflightAccessibility() -> Bool {
    // Prompt-free check; requesting prompts is a user-driven settings action, not helper's job.
    return AXIsProcessTrusted()
}

func preflightScreenRecording() -> Bool {
    return CGPreflightScreenCaptureAccess()
}

func permissionsPayload() -> [String: Any] {
    let v = ProcessInfo.processInfo.operatingSystemVersion
    return [
        "accessibility": preflightAccessibility(),
        "screenRecording": preflightScreenRecording(),
        "secureInput": IsSecureEventInputEnabled(),
        "bundleId": Bundle.main.bundleIdentifier ?? ProcessInfo.processInfo.processName,
        "osVersion": "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)",
    ]
}

// MARK: - window listing

func windowEntries() -> [[String: Any]] {
    let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    var out: [[String: Any]] = []
    for entry in list.prefix(64) {
        guard let windowId = entry[kCGWindowNumber as String] as? Int,
              let pid = entry[kCGWindowOwnerPID as String] as? Int else { continue }
        let layer = entry[kCGWindowLayer as String] as? Int ?? 0
        guard layer == 0 else { continue } // normal windows only
        let owner = entry[kCGWindowOwnerName as String] as? String ?? ""
        let name = entry[kCGWindowName as String] as? String ?? ""
        let boundsRaw = entry[kCGWindowBounds as String] as? [String: Any] ?? [:]
        let bounds: [String: Any] = [
            "x": boundsRaw["X"] ?? 0, "y": boundsRaw["Y"] ?? 0,
            "width": boundsRaw["Width"] ?? 0, "height": boundsRaw["Height"] ?? 0,
        ]
        var bundleId = ""
        if let app = NSRunningApplication(processIdentifier: pid_t(pid)) {
            bundleId = app.bundleIdentifier ?? ""
        }
        out.append([
            "windowId": windowId, "pid": pid, "bundleId": bundleId,
            "owner": owner, "title": name, "bounds": bounds,
        ])
    }
    return out
}

func windowsPayload() -> [String: Any] {
    return ["windows": windowEntries()]
}

// MARK: - AX observation (M1)

func axString(_ element: AXUIElement, _ attribute: String) -> String? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return nil }
    return value as? String
}

func axFrame(_ element: AXUIElement) -> [String: Int]? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &value) == .success,
          let position = value,
          AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &value) == .success,
          let size = value else { return nil }
    var point = CGPoint(); var dims = CGSize()
    let positionValue = position as! AXValue
    let sizeValue = size as! AXValue
    AXValueGetValue(positionValue, .cgPoint, &point)
    AXValueGetValue(sizeValue, .cgSize, &dims)
    return ["x": Int(point.x), "y": Int(point.y), "width": Int(dims.width), "height": Int(dims.height)]
}

func axChildren(_ element: AXUIElement) -> [AXUIElement] {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &value) == .success,
          let children = value as? [AXUIElement] else { return [] }
    return children
}

var axNodeBudget = maxAxNodes

func axWalk(_ element: AXUIElement, depth: Int, into nodes: inout [[String: Any]]) {
    guard axNodeBudget > 0, depth <= maxAxDepth else { return }
    axNodeBudget -= 1
    var node: [String: Any] = [:]
    if let role = axString(element, kAXRoleAttribute) { node["role"] = role }
    if let subrole = axString(element, kAXSubroleAttribute) { node["subrole"] = subrole }
    if let title = axString(element, kAXTitleAttribute), !title.isEmpty {
        node["title"] = String(title.prefix(maxValueChars))
    }
    if let label = axString(element, kAXDescriptionAttribute), !label.isEmpty {
        node["label"] = String(label.prefix(maxValueChars))
    }
    if let value = axString(element, kAXValueAttribute), !value.isEmpty {
        node["value"] = String(value.prefix(maxValueChars))
    }
    var focusedValue: CFTypeRef?
    if AXUIElementCopyAttributeValue(element, kAXFocusedAttribute as CFString, &focusedValue) == .success {
        node["focused"] = (focusedValue as? Bool) ?? false
    }
    if let frame = axFrame(element) { node["frame"] = frame }
    nodes.append(node)
    for child in axChildren(element) {
        axWalk(child, depth: depth + 1, into: &nodes)
    }
}

// Match an AX window element to the CGWindowID by comparing position+size with the
// CGWindowList bounds (avoids private _AXUIElementGetWindow).
func axWindowElement(pid: Int, windowId: Int) -> (element: AXUIElement, frame: [String: Int])? {
    guard let entry = windowEntries().first(where: { $0["windowId"] as? Int == windowId }),
          entry["pid"] as? Int == pid, let bounds = entry["bounds"] as? [String: Any],
          let width = bounds["width"] as? Int, width > 0 else { return nil }
    let appElement = AXUIElementCreateApplication(pid_t(pid))
    for window in axChildren(appElement) where axString(window, kAXRoleAttribute) == "AXWindow" {
        if let frame = axFrame(window),
           frame["width"] == width,
           frame["x"] == bounds["x"] as? Int, frame["y"] == bounds["y"] as? Int {
            return (window, frame)
        }
    }
    return nil
}

func observePayload(_ request: [String: Any]) -> Result<[String: Any], HelperError> {
    guard preflightAccessibility() else {
        return .failure(.permissionDenied("accessibility not granted"))
    }
    guard let windowId = request["windowId"] as? Int, let pid = request["pid"] as? Int else {
        return .failure(.badRequest("windowId and pid are required"))
    }
    guard let matched = axWindowElement(pid: pid, windowId: windowId) else {
        return .failure(.preconditionFailed("window not found or AX frame mismatch"))
    }
    axNodeBudget = maxAxNodes
    var nodes: [[String: Any]] = []
    axWalk(matched.element, depth: 0, into: &nodes)
    return .success([
        "backend": "macos-ax", "windowId": windowId, "pid": pid,
        "windowFrame": matched.frame, "nodes": nodes, "truncated": axNodeBudget <= 0,
    ])
}

// MARK: - window capture (M1, ScreenCaptureKit)

func capturePayload(_ request: [String: Any]) async -> Result<[String: Any], HelperError> {
    guard preflightScreenRecording() else {
        return .failure(.permissionDenied("screen recording not granted"))
    }
    guard let windowId = request["windowId"] as? Int else {
        return .failure(.badRequest("windowId is required"))
    }
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let scWindow = content.windows.first(where: { $0.windowID == CGWindowID(windowId) }) else {
            return .failure(.preconditionFailed("window not found in shareable content"))
        }
        let filter = SCContentFilter(desktopIndependentWindow: scWindow)
        let config = SCStreamConfiguration()
        // 1 image pixel == 1 window point. Unset width/height made ScreenCaptureKit
        // return an arbitrary canvas (e.g. 1920x1080 with the window letterboxed into
        // it), so image pixels could not be mapped to click coordinates. Capturing at
        // the window's point size makes conversion exact: global = windowFrame.origin + pixel.
        let frame = scWindow.frame
        config.width = max(1, Int(frame.width))
        config.height = max(1, Int(frame.height))
        config.scalesToFit = true
        config.capturesAudio = false
        config.showsCursor = false
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
        let rect = CGRect(origin: .zero, size: CGSize(width: image.width, height: image.height))
        guard let cgImage = image.cropping(to: rect) else {
            return .failure(.preconditionFailed("capture crop failed"))
        }
        let bitmap = NSBitmapImageRep(cgImage: cgImage)
        guard let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.7]),
              jpeg.count <= 2_000_000 else {
            return .failure(.preconditionFailed("capture exceeds size limit"))
        }
        return .success([
            "windowId": windowId,
            "width": cgImage.width, "height": cgImage.height,
            "windowFrame": [
                "x": Int(frame.origin.x), "y": Int(frame.origin.y),
                "width": Int(frame.width), "height": Int(frame.height),
            ],
            "mime": "image/jpeg", "dataUrl": "data:image/jpeg;base64,\(jpeg.base64EncodedString())",
        ])
    } catch {
        return .failure(.preconditionFailed("capture failed: \(error.localizedDescription)"))
    }
}

// MARK: - input (M1, opt-in; foreground allowlisted apps only)

func sessionUnlocked() -> Bool {
    // When the console session is locked, CGSessionCopyCurrentDictionary omits the
    // kCGSSessionOnConsoleKey or reports it as false.
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
    return (session["kCGSSessionOnConsoleKey"] as? Bool) ?? true
}

func inputPreconditions(_ request: [String: Any]) -> Result<Void, HelperError> {
    if IsSecureEventInputEnabled() {
        return .failure(.preconditionFailed("secure input is active"))
    }
    if !sessionUnlocked() {
        return .failure(.preconditionFailed("session is locked"))
    }
    guard let allowlist = request["allowlist"] as? [String], !allowlist.isEmpty else {
        return .failure(.preconditionFailed("empty app allowlist"))
    }
    guard let front = NSWorkspace.shared.frontmostApplication, let bundleId = front.bundleIdentifier else {
        return .failure(.preconditionFailed("no frontmost application"))
    }
    if !allowlist.contains(bundleId) {
        // Soft refusal: Python surfaces an allow-confirmation to the user; on approval the
        // bundle is added to the allowlist and the action is retried once.
        return .failure(.preconditionFailed("APP_NOT_ALLOWLISTED: \(bundleId)"))
    }
    if let windowId = request["windowId"] as? Int {
        guard let entry = windowEntries().first(where: { $0["windowId"] as? Int == windowId }),
              entry["bundleId"] as? String == bundleId else {
            return .failure(.preconditionFailed("target window is no longer frontmost for this app"))
        }
    }
    return .success(())
}

func intField(_ request: [String: Any], _ key: String) -> Result<Int, HelperError> {
    guard let value = request[key] as? Int else { return .failure(.badRequest("\(key) is required")) }
    return .success(value)
}

// Explicit surface activation: part of the design (switching surfaces needs explicit
// activation), gated like input — opt-in + allowlist.
func performActivate(_ request: [String: Any]) async -> Result<[String: Any], HelperError> {
    guard let bundleId = request["bundleId"] as? String, !bundleId.isEmpty else {
        return .failure(.badRequest("bundleId is required"))
    }
    // Activation is the *entry* to the foreground, so the gate here is: opt-in handled by
    // the caller dispatch, and the TARGET app must be allowlisted (not the current
    // frontmost, which by definition is not the target yet).
    guard let allowlist = request["allowlist"] as? [String] else {
        return .failure(.badRequest("allowlist is required"))
    }
    if !allowlist.contains(bundleId) {
        // Soft refusal: Python surfaces an allow-confirmation; approval adds the bundle.
        return .failure(.preconditionFailed("APP_NOT_ALLOWLISTED: \(bundleId)"))
    }
    if IsSecureEventInputEnabled() { return .failure(.preconditionFailed("secure input is active")) }
    if !sessionUnlocked() { return .failure(.preconditionFailed("session is locked")) }
    var app = NSRunningApplication.runningApplications(withBundleIdentifier: bundleId).first
    if app == nil {
        // Not running yet: launch it, then activate. The allowlist gate already covered
        // the user's consent for this bundle.
        guard let appUrl = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) else {
            return .failure(.preconditionFailed("app not installed: \(bundleId)"))
        }
        do {
            _ = try await NSWorkspace.shared.openApplication(at: appUrl, configuration: NSWorkspace.OpenConfiguration())
        } catch {
            return .failure(.preconditionFailed("could not launch app: \(error.localizedDescription)"))
        }
        for _ in 0..<50 {
            usleep(100_000)
            if let running = NSRunningApplication.runningApplications(withBundleIdentifier: bundleId).first {
                app = running
                break
            }
        }
        guard app != nil else { return .failure(.preconditionFailed("app launched but not registered: \(bundleId)")) }
    }
    let ok = app!.activate(options: [])
    guard ok else { return .failure(.preconditionFailed("activation refused")) }
    let pidValue = Int(app!.processIdentifier)
    var windowsNow = windowEntries().filter { $0["pid"] as? Int == pidValue }
    if windowsNow.isEmpty {
        // Windowless-but-running apps (common after relaunch): give the app a moment, then
        // synthesize the platform-convention Cmd+N to create a window.
        for _ in 0..<6 {
            usleep(200_000)
            windowsNow = windowEntries().filter { $0["pid"] as? Int == pidValue }
            if !windowsNow.isEmpty { break }
        }
        if windowsNow.isEmpty {
            if case .success(let (flags, baseKey)) = parseKeyCombo("cmd+n") {
                postKey(keyCodes[baseKey]!, flags: flags)
                for _ in 0..<10 {
                    usleep(200_000)
                    windowsNow = windowEntries().filter { $0["pid"] as? Int == pidValue }
                    if !windowsNow.isEmpty { break }
                }
            }
        }
    }
    let windowIdValue = windowsNow.first?["windowId"] as? Int
    var response: [String: Any] = ["activated": bundleId, "launched": true, "windowCreated": !windowsNow.isEmpty]
    if let windowIdValue = windowIdValue { response["windowId"] = windowIdValue }
    return .success(response)
}

func performClick(_ request: [String: Any]) -> Result<[String: Any], HelperError> {
    guard case .success(let x) = intField(request, "x"), case .success(let y) = intField(request, "y") else {
        return .failure(.badRequest("x and y are required"))
    }
    switch inputPreconditions(request) {
    case .success: break
    case .failure(let error): return .failure(error)
    }
    let point = CGPoint(x: x, y: y)
    for type in [CGEventType.mouseMoved, .leftMouseDown, .leftMouseUp] {
        let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left)
        event?.post(tap: .cghidEventTap)
        usleep(30_000)
    }
    return .success(["clicked": ["x": x, "y": y]])
}

func performType(_ request: [String: Any]) -> Result<[String: Any], HelperError> {
    guard let text = request["text"] as? String, !text.isEmpty, text.utf8.count <= 10_000 else {
        return .failure(.badRequest("text is required (<=10000 bytes)"))
    }
    switch inputPreconditions(request) {
    case .success: break
    case .failure(let error): return .failure(error)
    }
    // Convert to UTF-16 code units once; surrogates post as two separate events.
    let units = Array(text.utf16)
    for unit in units {
        let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true)
        event?.keyboardSetUnicodeString(stringLength: 1, unicodeString: [UniChar(unit)])
        event?.post(tap: .cghidEventTap)
        let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)
        up?.keyboardSetUnicodeString(stringLength: 1, unicodeString: [UniChar(unit)])
        up?.post(tap: .cghidEventTap)
        usleep(8_000)
    }
    return .success(["typed": text.count])
}

let keyCodes: [String: UInt16] = [
    "return": 36, "enter": 36, "escape": 53, "tab": 48, "space": 49, "delete": 51,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
]

// Parse "key" or "mod+key" (cmd/ctrl/alt/shift). Denies combos that escape the allowlisted
// surface or destroy it: Cmd+Tab (app switcher) and Cmd+Q (quit).
func parseKeyCombo(_ raw: String) -> Result<(CGEventFlags, String), HelperError> {
    let parts = raw.lowercased().split(separator: "+").map(String.init)
    guard let last = parts.last, keyCodes[last] != nil else {
        return .failure(.badRequest("unsupported key: \(raw)"))
    }
    var flags: CGEventFlags = []
    for mod in parts.dropLast() {
        switch mod {
        case "cmd", "command": flags.insert(.maskCommand)
        case "ctrl", "control": flags.insert(.maskControl)
        case "alt", "option": flags.insert(.maskAlternate)
        case "shift": flags.insert(.maskShift)
        default: return .failure(.badRequest("unsupported modifier: \(mod)"))
        }
    }
    if flags.contains(.maskCommand) {
        if last == "tab" { return .failure(.badRequest("cmd+tab escapes the allowlisted app")) }
        if last == "q" && parts.count == 2 { return .failure(.badRequest("cmd+q would quit the allowlisted app")) }
    }
    return .success((flags, last))
}

func postKey(_ virtualKey: UInt16, flags: CGEventFlags) {
    for down in [true, false] {
        let event = CGEvent(keyboardEventSource: nil, virtualKey: virtualKey, keyDown: down)
        event?.flags = flags
        event?.post(tap: CGEventTapLocation.cghidEventTap)
    }
}

func performKey(_ request: [String: Any]) -> Result<[String: Any], HelperError> {
    guard let key = request["key"] as? String, !key.isEmpty else {
        return .failure(.badRequest("key is required"))
    }
    guard case .success(let (flags, baseKey)) = parseKeyCombo(key) else {
        return .failure(.badRequest("unsupported key: \(key)"))
    }
    switch inputPreconditions(request) {
    case .success: break
    case .failure(let error): return .failure(error)
    }
    postKey(keyCodes[baseKey]!, flags: flags)
    return .success(["key": key])
}

func performScroll(_ request: [String: Any]) -> Result<[String: Any], HelperError> {
    guard case .success(let amount) = intField(request, "amount"), abs(amount) <= 2000 else {
        return .failure(.badRequest("amount is required (-2000..2000)"))
    }
    switch inputPreconditions(request) {
    case .success: break
    case .failure(let error): return .failure(error)
    }
    let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1,
                        wheel1: Int32(-amount), wheel2: 0, wheel3: 0)
    event?.post(tap: .cghidEventTap)
    return .success(["scrolled": amount])
}

// MARK: - dispatch

func handleRequest(_ request: [String: Any]) async -> Result<[String: Any], HelperError> {
    guard let command = request["command"] as? String else { return .failure(.badRequest("missing command")) }
    switch command {
    case "permissions":
        return .success(["permissions": permissionsPayload()])
    case "request_permissions":
        // Standard TCC flow: prompting variants register this binary in the
        // Accessibility / Screen Recording panes and surface the system dialog.
        let promptAX = AXIsProcessTrustedWithOptions(
            [kAXTrustedCheckOptionPrompt.takeRetainedValue(): true] as CFDictionary
        )
        let promptScreen = CGRequestScreenCaptureAccess()
        return .success(["permissions": permissionsPayload().merging([
            "accessibilityPrompted": promptAX, "screenRecordingPrompted": promptScreen,
        ]) { _, new in new }])
    case "windows":
        return .success(windowsPayload())
    case "observe":
        return observePayload(request)
    case "capture":
        return await capturePayload(request)
    case "activate":
        return await performActivate(request)
    case "click":
        return performClick(request)
    case "type":
        return performType(request)
    case "key":
        return performKey(request)
    case "scroll":
        return performScroll(request)
    default:
        return .failure(.unknownCommand(command))
    }
}

func respond(_ payload: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: payload),
       let line = String(data: data, encoding: .utf8) {
        print(line)
    }
}

// ── main ──
var arguments = CommandLine.arguments
guard let requestIndex = arguments.firstIndex(of: "--request-file"), arguments.count > requestIndex + 1,
      let secretIndex = arguments.firstIndex(of: "--secret"), arguments.count > secretIndex + 1 else {
    FileHandle.standardError.write(Data("usage: macos-helper --request-file <path> --secret <nonce>\n".utf8))
    exit(2)
}
let requestPath = arguments[requestIndex + 1]
let secret = arguments[secretIndex + 1]

// CoreGraphics/ScreenCaptureKit require process-level CG initialization before any CG
// call from concurrency-pool threads; without this the process aborts (CGS_REQUIRE_INIT).
_ = NSApplication.shared
_ = CGMainDisplayID()

guard let requestData = FileManager.default.contents(atPath: requestPath) else {
    respond(["ok": false, "error": "request file unreadable"]); exit(1)
}
guard requestData.count <= maxRequestBytes else {
    respond(["ok": false, "error": "request too large"]); exit(1)
}
// Per-launch nonce comparison: helper exits after one command, so a stolen file+secret pair
// is useless for future commands.
guard let request = try? JSONSerialization.jsonObject(with: requestData) as? [String: Any],
      let gotSecret = request["secret"] as? String, gotSecret == secret else {
    respond(["ok": false, "error": "bad request or secret"]); exit(1)
}

// Input commands require explicit opt-in per Electron config; the helper double-checks a
// marker so an allowlist can never authorize input while macOS input is disabled.
let inputCommands: Set<String> = ["activate", "click", "type", "key", "scroll"]
if inputCommands.contains(request["command"] as? String ?? "")
    && ProcessInfo.processInfo.environment["CRAB_MACOS_INPUT"] != "1" {
    respond(["ok": false, "error": "macos input is disabled (opt-in required)"]); exit(1)
}

let result = await handleRequest(request)
switch result {
case .success(let payload):
    respond(payload.merging(["ok": true]) { current, _ in current })
case .failure(let error):
    respond(["ok": false, "error": error.description])
}
