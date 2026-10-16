// SPDX-License-Identifier: MIT
// A native viewer/input bridge only. Pixels come from the running ARM guest's
// QMP screendump; Shell state, graphics and navigation remain in the guest.
import AppKit
import Foundation

private let screenWidth = 240
private let screenHeight = 320
private let rgbBytes = screenWidth * screenHeight * 3
private let maximumPPMBytes = rgbBytes + 4096

private enum ViewerError: Error, CustomStringConvertible {
    case invalid(String)
    var description: String {
        switch self { case .invalid(let message): return message }
    }
}

private struct Frame {
    let rgb: Data
    var checksum: UInt64 {
        rgb.reduce(UInt64(0xcbf29ce484222325)) { ($0 ^ UInt64($1)) &* 0x100000001b3 }
    }
}

private func isWhitespace(_ byte: UInt8) -> Bool {
    byte == 9 || byte == 10 || byte == 11 || byte == 12 || byte == 13 || byte == 32
}

private func parsePPM(_ data: Data) throws -> Frame {
    guard data.count <= maximumPPMBytes else { throw ViewerError.invalid("PPM exceeds bounded frame size") }
    let bytes = [UInt8](data)
    var position = 0
    func token() throws -> String {
        while position < bytes.count {
            guard position < 4096 else { throw ViewerError.invalid("PPM header exceeds4096 bytes") }
            if isWhitespace(bytes[position]) { position += 1; continue }
            if bytes[position] == 35 { // Header comment, never interpreted in raster bytes.
                while position < bytes.count && bytes[position] != 10 {
                    position += 1
                    guard position < 4096 else { throw ViewerError.invalid("PPM comment exceeds header bound") }
                }
                continue
            }
            break
        }
        let start = position
        while position < bytes.count && !isWhitespace(bytes[position]) {
            position += 1
            guard position - start <= 16 && position < 4096 else {
                throw ViewerError.invalid("PPM header token exceeds bound")
            }
        }
        guard position > start, let result = String(bytes: bytes[start..<position], encoding: .ascii) else {
            throw ViewerError.invalid("Missing ASCII PPM header token")
        }
        return result
    }
    guard try token() == "P6" else { throw ViewerError.invalid("Only binary P6 QMP frames are accepted") }
    // Compare bounded decimal tokens directly; no attacker-selected arithmetic
    // or allocations are performed before the fixed geometry is established.
    guard try token() == "240", try token() == "320", try token() == "255" else {
        throw ViewerError.invalid("Need exactly240x320 RGB888/max255")
    }
    guard position < bytes.count && isWhitespace(bytes[position]) else {
        throw ViewerError.invalid("Missing PPM raster separator")
    }
    let separator = bytes[position]
    position += 1
    if separator == 13 && position < bytes.count && bytes[position] == 10 { position += 1 }
    // Consume only the required separator, preserving a raster that begins
    // with whitespace or '#'. Trailing bytes and incomplete frames are errors.
    guard bytes.count - position == rgbBytes else { throw ViewerError.invalid("Incomplete or oversized PPM raster") }
    return Frame(rgb: Data(bytes[position...]))
}

private func readFrame(_ path: String) throws -> Frame {
    let handle = try FileHandle(forReadingFrom: URL(fileURLWithPath: path))
    defer { try? handle.close() }
    // The backend replaces this regular file atomically. Even if a caller gives
    // another file, this reader never allocates beyond one bounded frame.
    let data = try handle.read(upToCount: maximumPPMBytes + 1) ?? Data()
    return try parsePPM(data)
}

private func eventWires(keyCode: UInt16, characters: String) -> [UInt32] {
    let tag: UInt32?
    switch keyCode {
    case 126: tag = 1 // Up
    case 125: tag = 2 // Down
    case 123: tag = 3 // Left
    case 124: tag = 4 // Right
    case 36, 76: tag = 5 // Return/keypad Enter: Select
    case 53: tag = 6 // Escape: Back
    case 109: tag = 7 // F10: Menu
    case 51, 117: return [0x08000008] // Backspace/Delete: existing text erase intent.
    case 115: return [0x0800e000] // Home
    case 122: return [0x0800e001] // F1: direct left softkey
    case 120: return [0x0800e002] // F2: direct right softkey
    case 99: return [0x0800e003] // F3: switch screen task
    default: tag = nil
    }
    if let tag { return [tag << 24] }
    return characters.unicodeScalars.compactMap { scalar in
        let value = scalar.value
        // AppKit function-key scalars are not printable text. The four PUA
        // controls above are emitted only by the explicit keycode mapping.
        guard value >= 0x20 && value != 0x7f && !(0xe000...0xf8ff).contains(value) else { return nil }
        return UInt32(8 << 24) | value
    }
}

private func emit(_ line: String) {
    try? FileHandle.standardOutput.write(contentsOf: Data((line + "\n").utf8))
}

@MainActor
private final class GuestView: NSView {
    private let framePath: String
    private var image: NSImage?
    private var previousRGB: Data?
    private var timer: Timer?
    override var acceptsFirstResponder: Bool { true }

    init(path: String) {
        framePath = path
        super.init(frame: NSRect(x: 0, y: 0, width: CGFloat(screenWidth), height: CGFloat(screenHeight)))
        autoresizingMask = [.width, .height]
        timer = Timer.scheduledTimer(timeInterval: 0.05, target: self,
                                    selector: #selector(updateFrame), userInfo: nil, repeats: true)
        updateFrame()
    }
    required init?(coder: NSCoder) { fatalError("GuestView is created programmatically") }

    @objc private func updateFrame() {
        guard let frame = try? readFrame(framePath), frame.rgb != previousRGB else { return }
        guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: screenWidth,
                                           pixelsHigh: screenHeight, bitsPerSample: 8,
                                           samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
                                           colorSpaceName: .deviceRGB, bytesPerRow: screenWidth * 3,
                                           bitsPerPixel: 24), let pixels = bitmap.bitmapData else { return }
        frame.rgb.copyBytes(to: pixels, count: rgbBytes)
        let next = NSImage(size: NSSize(width: CGFloat(screenWidth), height: CGFloat(screenHeight)))
        next.addRepresentation(bitmap)
        image = next
        previousRGB = frame.rgb
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
        guard let image else { return }
        let scale = min(bounds.width / CGFloat(screenWidth), bounds.height / CGFloat(screenHeight))
        let size = NSSize(width: CGFloat(screenWidth) * scale, height: CGFloat(screenHeight) * scale)
        let destination = NSRect(x: (bounds.width - size.width) / 2,
                                 y: (bounds.height - size.height) / 2,
                                 width: size.width, height: size.height)
        NSGraphicsContext.current?.imageInterpolation = .none
        image.draw(in: destination, from: .zero, operation: .copy, fraction: 1)
    }

    override func keyDown(with event: NSEvent) {
        guard !event.modifierFlags.contains(.command) else { super.keyDown(with: event); return }
        for wire in eventWires(keyCode: event.keyCode, characters: event.characters ?? "") {
            emit("event \(wire)")
        }
    }
}

@MainActor
private final class ApplicationDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let framePath: String
    private var window: NSWindow?
    private var sentQuit = false
    private let windowTest: Bool
    private var testTimer: Timer?
    init(path: String, windowTest: Bool = false) { framePath = path; self.windowTest = windowTest }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = GuestView(path: framePath)
        let next = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 640),
                            styleMask: [.titled, .closable, .miniaturizable, .resizable],
                            backing: .buffered, defer: false)
        next.title = "Crosshair Shell0.1 — ARM QEMU"
        next.contentView = view
        next.contentMinSize = NSSize(width: CGFloat(screenWidth), height: CGFloat(screenHeight))
        next.contentAspectRatio = NSSize(width: CGFloat(screenWidth), height: CGFloat(screenHeight))
        next.isReleasedWhenClosed = false
        next.delegate = self
        next.center()
        next.makeKeyAndOrderFront(nil)
        next.makeFirstResponder(view)
        window = next
        NSApplication.shared.activate(ignoringOtherApps: true)
        if windowTest {
            emit("window-ready \(next.isVisible ? 1 : 0)")
            // Only the explicit test flag schedules input and closes the window.
            // Events traverse NSApplication's normal key-window/first-responder
            // routing, then the same FIFO bridge as physical MacBook keys.
            let codes: [UInt16] = [122, 36, 53, 115]
            var step = 0
            testTimer = Timer.scheduledTimer(withTimeInterval: 0.7, repeats: true) { [weak self, weak next] timer in
                MainActor.assumeIsolated {
                    guard let self, let next else { timer.invalidate(); return }
                    if step == codes.count {
                        timer.invalidate(); next.performClose(nil); return
                    }
                    if let event = NSEvent.keyEvent(with: .keyDown, location: .zero,
                        modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                        windowNumber: next.windowNumber, context: nil, characters: "",
                        charactersIgnoringModifiers: "", isARepeat: false, keyCode: codes[step]) {
                        NSApplication.shared.postEvent(event, atStart: false)
                    }
                    step += 1
                    _ = self
                }
            }
        }
    }
    func windowWillClose(_ notification: Notification) {
        requestQuit()
        NSApplication.shared.terminate(nil)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        requestQuit()
        return .terminateNow
    }
    private func requestQuit() {
        if !sentQuit { emit("quit"); sentQuit = true }
    }
}

private func selfTest() throws {
    let keyFixtures: [(UInt16, UInt32)] = [(126, 0x01000000), (125, 0x02000000),
                             (123, 0x03000000), (124, 0x04000000), (36, 0x05000000),
                             (76, 0x05000000), (53, 0x06000000), (109, 0x07000000),
                             (51, 0x08000008), (117, 0x08000008),
                             (115, 0x0800e000), (122, 0x0800e001), (120, 0x0800e002), (99, 0x0800e003)]
    for (code, expected) in keyFixtures {
        guard eventWires(keyCode: code, characters: "") == [expected] else {
            throw ViewerError.invalid("Keycode mapping self-test failed")
        }
    }
    guard eventWires(keyCode: 0, characters: "AЁ") == [0x08000041, 0x08000401],
          eventWires(keyCode: 0, characters: "\u{7f}\u{f700}") == [] else {
        throw ViewerError.invalid("Unicode mapping self-test failed")
    }
    var header = Data("P6\n# QMP fixture\n240 320\n255\n".utf8)
    var pixels = Data(repeating: 0x5a, count: rgbBytes)
    pixels[0] = 10 // A raster-leading whitespace must not be skipped.
    pixels[1] = 35
    header.append(pixels)
    guard try parsePPM(header).rgb == pixels else { throw ViewerError.invalid("PPM pixel preservation failed") }
    var invalids = [Data("P6\n99999999999999999 320\n255\n".utf8), Data(header.dropLast()),
                    Data("P3\n240 320\n255\n".utf8), Data(repeating: 32, count: maximumPPMBytes + 1),
                    Data("P6\n240 320\n256\n".utf8)]
    var trailing = header
    trailing.append(0)
    invalids.append(trailing)
    for invalid in invalids {
        do { _ = try parsePPM(invalid) } catch { continue }
        throw ViewerError.invalid("Corrupted or truncated PPM accepted")
    }
    print("PASS Crosshair GUI: key mapping, Unicode, bounded P6 parser and corrupted/truncated input")
}

let arguments = CommandLine.arguments
if arguments.count == 2 && arguments[1] == "--self-test" {
    do { try selfTest() } catch { fputs("\(error)\n", stderr); exit(1) }
} else if arguments.count == 3 && arguments[1] == "--inspect-ppm" {
    do {
        let frame = try readFrame(arguments[2])
        print("{\"width\":240,\"height\":320,\"rgb_bytes\":\(frame.rgb.count),\"rgb_fnv1a64\":\"\(String(format: "%016llx", frame.checksum))\"}")
    } catch { fputs("\(error)\n", stderr); exit(1) }
} else if (arguments.count == 2 && !arguments[1].hasPrefix("--")) ||
          (arguments.count == 3 && arguments[1] == "--window-test") {
    // The executable's synchronous top-level entry runs on the main thread.
    // No AppKit object is constructed on a worker or the headless test paths.
    MainActor.assumeIsolated {
        let app = NSApplication.shared
        let testing = arguments.count == 3
        let delegate = ApplicationDelegate(path: arguments[testing ? 2 : 1], windowTest: testing)
        app.setActivationPolicy(.regular)
        app.delegate = delegate
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "Quit Crosshair Viewer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        menu.addItem(applicationItem)
        app.mainMenu = menu
        app.run()
        withExtendedLifetime(delegate) {}
    }
} else {
    fputs("Usage: crosshair-gui FRAME.ppm | --self-test | --inspect-ppm FRAME.ppm | --window-test FRAME.ppm\n", stderr)
    exit(2)
}
