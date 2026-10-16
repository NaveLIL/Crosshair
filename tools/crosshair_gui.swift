// SPDX-License-Identifier: MIT
// A native viewer/input bridge only. Pixels come from the running ARM guest's
// QMP screendump; Shell state, graphics and navigation remain in the guest.
import AppKit
import Foundation

private let screenWidth = 240
private let screenHeight = 320
private let rgbBytes = screenWidth * screenHeight * 3
private let maximumPPMBytes = rgbBytes + 4096
private let pointerScalarBase: UInt32 = 0xf0000
private struct AutomatedEventSignature: Hashable {
    let type: UInt
    let timestamp: TimeInterval
    let keyCode: UInt16
    init(_ event: NSEvent) {
        type = event.type.rawValue
        timestamp = event.timestamp
        keyCode = event.type == .keyDown || event.type == .keyUp ? event.keyCode : 0
    }
}
@MainActor private var queuedAutomatedEvents: Set<AutomatedEventSignature> = []

@MainActor private func postAutomatedEvent(_ event: NSEvent) {
    // Explicit test windows may be focused while the owner types elsewhere.
    // Mark only our posted events, so unrelated physical input cannot alter an
    // automated trace. Normal live windows apply no such filter.
    // Keep the original NSEvent: recreating a mouse event from CGEvent loses
    // its NSWindow-relative routing. AppKit may copy posted events, so match
    // their preserved type/timestamp/keycode fields in this bounded registry.
    if [.keyDown, .keyUp, .leftMouseDown, .leftMouseDragged, .leftMouseUp].contains(event.type) {
        queuedAutomatedEvents.insert(AutomatedEventSignature(event))
    }
    NSApplication.shared.postEvent(event, atStart: false)
}

// AppKit points and NSImage drawing use the same aspect-fit rectangle. Keeping
// this calculation shared prevents resize/letterbox offsets from becoming
// guest coordinates. The guest coordinate origin is the top-left pixel.
private func contentRectangle(in bounds: NSRect) -> NSRect? {
    guard bounds.origin.x.isFinite, bounds.origin.y.isFinite,
          bounds.width.isFinite, bounds.height.isFinite,
          bounds.width > 0, bounds.height > 0 else { return nil }
    let scale = min(bounds.width / CGFloat(screenWidth), bounds.height / CGFloat(screenHeight))
    let size = NSSize(width: CGFloat(screenWidth) * scale, height: CGFloat(screenHeight) * scale)
    return NSRect(x: bounds.minX + (bounds.width - size.width) / 2,
                  y: bounds.minY + (bounds.height - size.height) / 2,
                  width: size.width, height: size.height)
}

private func logicalPoint(_ point: NSPoint, in bounds: NSRect) -> (Int, Int)? {
    guard point.x.isFinite, point.y.isFinite, let rectangle = contentRectangle(in: bounds),
          point.x >= rectangle.minX, point.x < rectangle.maxX,
          point.y > rectangle.minY, point.y <= rectangle.maxY else { return nil }
    let x = Int(floor((point.x - rectangle.minX) * CGFloat(screenWidth) / rectangle.width))
    let y = Int(floor((rectangle.maxY - point.y) * CGFloat(screenHeight) / rectangle.height))
    guard x >= 0, x < screenWidth, y >= 0, y < screenHeight else { return nil }
    return (x, y)
}

private func pointerWire(x: Int, y: Int) -> UInt32? {
    guard x >= 0, x < screenWidth, y >= 0, y < screenHeight else { return nil }
    // A reserved supplementary PUA scalar passes the unchanged Unicode FIFO.
    // Addition preserves the ninth Y bit; OR with0xf0000 would lose it.
    return 0x08000000 | (pointerScalarBase + UInt32(y << 8) + UInt32(x))
}

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
        guard value >= 0x20 && value != 0x7f && !(0xe000...0xf8ff).contains(value) && !(0x90000...0x10ffff).contains(value) else { return nil }
        return UInt32(8 << 24) | value
    }
}

// Semantic IDs belong to the emulator adapter; these are not PDA scan codes.
private func hardwareKey(_ keyCode: UInt16) -> Int? {
    switch keyCode {
    case 126: return 0
    case 125: return 1
    case 123: return 2
    case 124: return 3
    case 36, 76: return 4
    case 53: return 5
    case 109: return 12 // F10: Shell-owned system panel
    case 115, 118: return 7
    case 122: return 11 // F1: Shell-owned Start
    case 120: return 9 // F2: current context action
    case 99: return 10
    default: return nil
    }
}

private func emit(_ line: String) {
    try? FileHandle.standardOutput.write(contentsOf: Data((line + "\n").utf8))
}

@MainActor
private final class GuestView: NSView {
    private let framePath: String
    private let automated: Bool
    private var image: NSImage?
    private var previousRGB: Data?
    private var timer: Timer?
    private(set) var ignoredTestInputs = 0
    private var pressClock: TimeInterval?
    private var pressPoint: (Int, Int)?
    private var lastPoint: (Int, Int)?
    private var movedSincePress = false
    private var sentHold = false
    private var holdTimer: Timer?
    private var heldKeys: Set<Int> = []
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    init(path: String, automated: Bool = false) {
        framePath = path
        self.automated = automated
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
        guard let destination = contentRectangle(in: bounds) else { return }
        NSGraphicsContext.current?.imageInterpolation = .none
        image.draw(in: destination, from: .zero, operation: .copy, fraction: 1)
    }

    private func emitPointer(_ phase: Int, _ x: Int = 0, _ y: Int = 0, held: Int = 0) {
        emit("pointer \(phase) \(x) \(y) \(held)")
    }
    private func clearPointer() {
        holdTimer?.invalidate(); holdTimer = nil
        pressClock = nil; pressPoint = nil; lastPoint = nil
        movedSincePress = false; sentHold = false
    }
    func cancelSource() {
        if pressClock != nil || !heldKeys.isEmpty { emit("event \(UInt32(0x0800e007))") }
        clearPointer(); heldKeys.removeAll()
    }
    private func cancelPointer() {
        if pressClock != nil { emitPointer(4) }
        clearPointer()
    }
    override func mouseDown(with event: NSEvent) {
        guard acceptsInput(event) else { return }
        let point = convert(event.locationInWindow, from: nil)
        guard let (x, y) = logicalPoint(point, in: bounds) else { cancelPointer(); return }
        cancelPointer()
        window?.makeFirstResponder(self)
        // Use actual monotonic receipt time, never NSEvent's timestamp. Test
        // routing timestamps are deliberately synthetic future integers.
        pressClock = ProcessInfo.processInfo.systemUptime
        pressPoint = (x,y); lastPoint = (x,y)
        emitPointer(1,x,y)
        holdTimer = Timer.scheduledTimer(withTimeInterval: 0.025, repeats: true) { [weak self] timer in
            MainActor.assumeIsolated {
                guard let self, let started = self.pressClock, let point = self.lastPoint,
                      !self.movedSincePress, !self.sentHold else { timer.invalidate(); return }
                let elapsed = ProcessInfo.processInfo.systemUptime - started
                if elapsed >= 0.6 {
                    let millis = Int(min(elapsed * 1000, Double(UInt32.max)))
                    self.emitPointer(5,point.0,point.1,held:millis)
                    self.sentHold = true
                    timer.invalidate()
                }
            }
        }
    }
    override func mouseDragged(with event: NSEvent) {
        guard acceptsInput(event), pressClock != nil else { return }
        let point = convert(event.locationInWindow, from: nil)
        guard let (x,y) = logicalPoint(point, in: bounds) else { cancelPointer(); return }
        if lastPoint?.0 != x || lastPoint?.1 != y {
            movedSincePress = true
            holdTimer?.invalidate(); holdTimer = nil
            lastPoint = (x,y)
            emitPointer(2,x,y)
        }
    }
    override func mouseUp(with event: NSEvent) {
        guard acceptsInput(event), pressClock != nil else { return }
        let point = convert(event.locationInWindow, from: nil)
        guard let (x,y) = logicalPoint(point, in: bounds) else { cancelPointer(); return }
        emitPointer(3,x,y)
        clearPointer()
    }

    private func acceptsInput(_ event: NSEvent) -> Bool {
        if !automated { return true }
        let accepted = queuedAutomatedEvents.remove(AutomatedEventSignature(event)) != nil
        if !accepted { ignoredTestInputs += 1 }
        return accepted
    }

    override func keyDown(with event: NSEvent) {
        guard acceptsInput(event) else { return }
        guard !event.modifierFlags.contains(.command) else { super.keyDown(with: event); return }
        if let key = hardwareKey(event.keyCode) {
            heldKeys.insert(key)
            emit("key \(event.isARepeat ? 1 : 0) \(key)")
        } else {
            for wire in eventWires(keyCode: event.keyCode, characters: event.characters ?? "") {
                emit("event \(wire)")
            }
        }
    }
    override func keyUp(with event: NSEvent) {
        guard acceptsInput(event), let key = hardwareKey(event.keyCode) else { return }
        heldKeys.remove(key)
        emit("key 2 \(key)")
    }
}

private enum NativeTestEvent {
    case key(UInt16, String)
    case pointer(Int, Int)
    case mouse(NSEvent.EventType, Int, Int)
    case keyEdge(UInt16, NSEvent.EventType, Bool)
    case pause
}

@MainActor
private final class ApplicationDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let framePath: String
    private var window: NSWindow?
    private var sentQuit = false
    private let windowTest: Bool
    private let pointerWindowTest: Bool
    private let adaptiveWindowTest: Bool
    private var testTimer: Timer?
    init(path: String, windowTest: Bool = false, pointerWindowTest: Bool = false, adaptiveWindowTest: Bool = false) {
        framePath = path; self.windowTest = windowTest; self.pointerWindowTest = pointerWindowTest
        self.adaptiveWindowTest = adaptiveWindowTest
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = GuestView(path: framePath, automated: windowTest || pointerWindowTest || adaptiveWindowTest)
        let next = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 640),
                            styleMask: [.titled, .closable, .miniaturizable, .resizable],
                            backing: .buffered, defer: false)
        next.title = "Crosshair Shell0.1 — ARM QEMU"
        if windowTest || pointerWindowTest || adaptiveWindowTest { next.animationBehavior = .none }
        next.contentView = view
        next.contentMinSize = NSSize(width: CGFloat(screenWidth), height: CGFloat(screenHeight))
        next.contentAspectRatio = NSSize(width: CGFloat(screenWidth), height: CGFloat(screenHeight))
        next.isReleasedWhenClosed = false
        next.delegate = self
        next.center()
        next.makeKeyAndOrderFront(nil)
        next.makeFirstResponder(view)
        window = next
        if !windowTest && !pointerWindowTest && !adaptiveWindowTest {
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
        if windowTest || pointerWindowTest || adaptiveWindowTest {
            emit("window-ready \(next.isVisible ? 1 : 0)")
            // Only the explicit test flag schedules input and closes the window.
            // Events traverse NSApplication's normal key-window/first-responder
            // routing, then the same FIFO bridge as physical MacBook keys.
            let adaptiveEvents: [NativeTestEvent] = [
                .mouse(.leftMouseDown,40,68), .mouse(.leftMouseDragged,130,150),
                .mouse(.leftMouseDragged,40,68), .mouse(.leftMouseUp,40,68),
                .mouse(.leftMouseDown,40,68), .pause,.pause,.pause,.pause,.pause,.pause,.pause,.pause,
                .mouse(.leftMouseUp,40,68), .key(53,""),
                .keyEdge(125,.keyDown,false), .keyEdge(125,.keyDown,true), .keyEdge(125,.keyDown,true), .keyEdge(125,.keyUp,false),
                .key(36,""), .key(109,""), .pointer(30,214), .key(109,""), .pointer(30,240),
                .pointer(230,8), .pointer(30,188), .key(118,"")]
            let events: [NativeTestEvent] = adaptiveWindowTest ? adaptiveEvents : pointerWindowTest
                ? [.pointer(40, 68), .key(53, ""), .pointer(12, 8), .key(31, "О"),
                   .key(36, ""), .pointer(227, 12), .key(118, "")]
                : [.key(122, ""), .key(36, ""), .key(53, ""), .key(118, "")]
            // Regression fixture: unrelated text follows the normal AppKit
            // route but is absent from the explicit test-event registry.
            Timer.scheduledTimer(withTimeInterval: 0.2, repeats: false) { [weak next] _ in
                MainActor.assumeIsolated {
                    guard let next, let event = NSEvent.keyEvent(with: .keyDown, location: .zero,
                        modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                        windowNumber: next.windowNumber, context: nil, characters: "Т",
                        charactersIgnoringModifiers: "Т", isARepeat: false, keyCode: 17) else { return }
                    NSApplication.shared.postEvent(event, atStart: false)
                }
            }
            var step = 0
            testTimer = Timer.scheduledTimer(withTimeInterval: adaptiveWindowTest ? 0.12 : 0.7, repeats: true) { [weak self, weak next] timer in
                MainActor.assumeIsolated {
                    guard let self, let next else { timer.invalidate(); return }
                    if step == events.count {
                        emit("automation-isolation \(view.ignoredTestInputs > 0 ? 1 : 0)")
                        timer.invalidate(); next.performClose(nil); return
                    }
                    // Exactly representable integer timestamps survive AppKit
                    // copies unchanged and cannot match concurrent physical
                    // input, whose timestamps remain near the current uptime.
                    let testTimestamp = floor(ProcessInfo.processInfo.systemUptime) + 1000 + Double(step)
                    switch events[step] {
                    case .key(let code, let characters):
                        for type in [NSEvent.EventType.keyDown, .keyUp] {
                            if let event = NSEvent.keyEvent(with: type, location: .zero,
                                modifierFlags: [], timestamp: testTimestamp,
                                windowNumber: next.windowNumber, context: nil, characters: characters,
                                charactersIgnoringModifiers: characters, isARepeat: false, keyCode: code) {
                                postAutomatedEvent(event)
                            }
                        }
                    case .pause:
                        break
                    case .keyEdge(let code, let type, let repeated):
                        if let event = NSEvent.keyEvent(with: type, location: .zero,
                            modifierFlags: [], timestamp: testTimestamp, windowNumber: next.windowNumber,
                            context: nil, characters: "", charactersIgnoringModifiers: "", isARepeat: repeated, keyCode: code) {
                            postAutomatedEvent(event)
                        }
                    case .mouse(let type, let x, let y):
                        guard let rectangle = contentRectangle(in: view.bounds) else { return }
                        let point = NSPoint(x: rectangle.minX + (CGFloat(x)+0.5)*rectangle.width/CGFloat(screenWidth),
                                            y: rectangle.maxY - (CGFloat(y)+0.5)*rectangle.height/CGFloat(screenHeight))
                        if let event = NSEvent.mouseEvent(with: type, location: view.convert(point,to:nil),
                            modifierFlags: [], timestamp: testTimestamp, windowNumber: next.windowNumber,
                            context: nil, eventNumber: step, clickCount: 1, pressure: type == .leftMouseUp ? 0 : 1) {
                            postAutomatedEvent(event)
                        }
                    case .pointer(let x, let y):
                        guard let rectangle = contentRectangle(in: view.bounds) else { return }
                        let point = NSPoint(x: rectangle.minX + (CGFloat(x) + 0.5) * rectangle.width / CGFloat(screenWidth),
                                            y: rectangle.maxY - (CGFloat(y) + 0.5) * rectangle.height / CGFloat(screenHeight))
                        let location = view.convert(point, to: nil)
                        for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
                            if let event = NSEvent.mouseEvent(with: type, location: location,
                                modifierFlags: [], timestamp: testTimestamp,
                                windowNumber: next.windowNumber, context: nil, eventNumber: step,
                                clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0) {
                                postAutomatedEvent(event)
                            }
                        }
                    }
                    step += 1
                    _ = self
                }
            }
        }
    }
    func windowDidResignKey(_ notification: Notification) {
        (window?.contentView as? GuestView)?.cancelSource()
    }
    func windowWillClose(_ notification: Notification) {
        (window?.contentView as? GuestView)?.cancelSource()
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
    // Logical coordinates use half-open top/left pixel bounds, including the
    // last pixel without admitting letterboxing, NaN, or out-of-range taps.
    let rectangles = [NSRect(x: 0, y: 0, width: 240, height: 320),
                      NSRect(x: 0, y: 0, width: 480, height: 640),
                      NSRect(x: 0, y: 0, width: 640, height: 400),
                      NSRect(x: 10, y: 20, width: 240, height: 400)]
    for bounds in rectangles {
        guard let rectangle = contentRectangle(in: bounds) else { throw ViewerError.invalid("Missing aspect-fit rectangle") }
        for y in 0..<screenHeight {
            for x in 0..<screenWidth {
                let point = NSPoint(x: rectangle.minX + (CGFloat(x) + 0.5) * rectangle.width / CGFloat(screenWidth),
                                    y: rectangle.maxY - (CGFloat(y) + 0.5) * rectangle.height / CGFloat(screenHeight))
                guard let mapped = logicalPoint(point, in: bounds), mapped.0 == x, mapped.1 == y else {
                    throw ViewerError.invalid("Scaled/letterboxed pointer coordinate mapping failed")
                }
                guard pointerWire(x: x, y: y) == 0x08000000 | (pointerScalarBase + UInt32(y << 8) + UInt32(x)) else {
                    throw ViewerError.invalid("Pointer wire lost coordinate bits")
                }
            }
        }
        let outside = [NSPoint(x: rectangle.minX - 0.01, y: rectangle.midY),
                       NSPoint(x: rectangle.maxX, y: rectangle.midY),
                       NSPoint(x: rectangle.midX, y: rectangle.minY),
                       NSPoint(x: rectangle.midX, y: rectangle.maxY + 0.01)]
        for point in outside {
            guard logicalPoint(point, in: bounds) == nil else { throw ViewerError.invalid("Letterbox/outside tap accepted") }
        }
    }
    guard logicalPoint(NSPoint(x: CGFloat.nan, y: 0), in: rectangles[0]) == nil,
          logicalPoint(.zero, in: .zero) == nil,
          pointerWire(x: -1, y: 0) == nil, pointerWire(x: 240, y: 0) == nil,
          pointerWire(x: 0, y: 320) == nil,
          eventWires(keyCode: 0, characters: "\u{90000}\u{d0000}\u{f0000}\u{103fef}\u{10ffff}") == [] else {
        throw ViewerError.invalid("Invalid pointer or reserved text accepted")
    }
    let hardwareFixtures: [(UInt16,Int)] = [(126,0),(125,1),(123,2),(124,3),(36,4),(53,5),
                                           (115,7),(118,7),(122,11),(120,9),(99,10),(109,12)]
    for (code,key) in hardwareFixtures {
        guard hardwareKey(code) == key else { throw ViewerError.invalid("Hardware semantic key mapping failed") }
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
    print("PASS Crosshair GUI: key mapping, Unicode, pointer scale/letterbox/bounds, bounded P6 parser and corrupted/truncated input")
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
          (arguments.count == 3 && ["--window-test", "--pointer-window-test", "--adaptive-window-test"].contains(arguments[1])) {
    // The executable's synchronous top-level entry runs on the main thread.
    // No AppKit object is constructed on a worker or the headless test paths.
    MainActor.assumeIsolated {
        let app = NSApplication.shared
        let testing = arguments.count == 3
        let delegate = ApplicationDelegate(path: arguments[testing ? 2 : 1],
            windowTest: testing && arguments[1] == "--window-test",
            pointerWindowTest: testing && arguments[1] == "--pointer-window-test",
            adaptiveWindowTest: testing && arguments[1] == "--adaptive-window-test")
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
    fputs("Usage: crosshair-gui FRAME.ppm | --self-test | --inspect-ppm FRAME.ppm | --window-test FRAME.ppm | --pointer-window-test FRAME.ppm | --adaptive-window-test FRAME.ppm\n", stderr)
    exit(2)
}
