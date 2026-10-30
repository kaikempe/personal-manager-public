// Draws the app icon: Apple-style squircle, blue tint gradient (the dashboard's accent),
// white sheet with three priority rows, the first one ticked.
// usage: swift make_icon.swift <out.iconset dir>
import Cocoa

func render(_ px: Int) -> Data {
    let s = CGFloat(px) / 1024
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.scaleBy(x: s, y: s)

    // Icon body: 824pt squircle centred in the 1024 canvas, soft drop shadow below it.
    let body = CGRect(x: 100, y: 100, width: 824, height: 824)
    let squircle = NSBezierPath(roundedRect: body, xRadius: 190, yRadius: 190)
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 28, color: NSColor.black.withAlphaComponent(0.28).cgColor)
    NSColor.black.setFill(); squircle.fill()
    ctx.restoreGState()

    ctx.saveGState()
    squircle.addClip()
    // Dark glass tile, like the other dark icons in the Dock.
    let g = NSGradient(colors: [NSColor(srgbRed: 0.20, green: 0.20, blue: 0.22, alpha: 1),
                                NSColor(srgbRed: 0.07, green: 0.07, blue: 0.08, alpha: 1)])!
    g.draw(in: body, angle: -90)
    let hl = NSGradient(colors: [NSColor.white.withAlphaComponent(0.10), NSColor.white.withAlphaComponent(0)])!
    hl.draw(in: CGRect(x: 100, y: 520, width: 824, height: 404), angle: -90)
    ctx.restoreGState()
    // Hairline edge so the dark tile keeps its shape against a dark Dock.
    let edge = NSBezierPath(roundedRect: body.insetBy(dx: 2, dy: 2), xRadius: 188, yRadius: 188)
    edge.lineWidth = 4; NSColor.white.withAlphaComponent(0.14).setStroke(); edge.stroke()

    // Three priority rows, the first one ticked, in the system blue.
    let tint = NSColor(srgbRed: 0.04, green: 0.52, blue: 1.0, alpha: 1)
    let gray = NSColor(srgbRed: 0.56, green: 0.56, blue: 0.60, alpha: 1)
    let rows: [(CGFloat, CGFloat)] = [(672, 330), (512, 270), (352, 200)]
    for (i, (y, barW)) in rows.enumerated() {
        let dot = CGRect(x: 277, y: y - 50, width: 100, height: 100)
        if i == 0 {
            tint.setFill(); NSBezierPath(ovalIn: dot).fill()
            let tick = NSBezierPath()
            tick.move(to: CGPoint(x: 301, y: y - 2)); tick.line(to: CGPoint(x: 321, y: y - 24)); tick.line(to: CGPoint(x: 357, y: y + 22))
            tick.lineWidth = 16; tick.lineCapStyle = .round; tick.lineJoinStyle = .round
            NSColor.white.setStroke(); tick.stroke()
        } else {
            let ring = NSBezierPath(ovalIn: dot.insetBy(dx: 7, dy: 7)); ring.lineWidth = 13
            gray.withAlphaComponent(0.75).setStroke(); ring.stroke()
        }
        let bar = CGRect(x: 417, y: y - 24, width: barW, height: 48)
        (i == 0 ? tint : gray.withAlphaComponent(0.55)).setFill()
        NSBezierPath(roundedRect: bar, xRadius: 24, yRadius: 24).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let dir = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
for base in [16, 32, 128, 256, 512] {
    try! render(base).write(to: URL(fileURLWithPath: "\(dir)/icon_\(base)x\(base).png"))
    try! render(base * 2).write(to: URL(fileURLWithPath: "\(dir)/icon_\(base)x\(base)@2x.png"))
}
